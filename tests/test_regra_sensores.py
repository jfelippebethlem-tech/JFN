# -*- coding: utf-8 -*-
"""Sensores das regras de qualidade, sobre dado SINTÉTICO (nenhuma rota, banco ou caso real).

Cada sensor tem a prova (COR-15): o defeito montado em `tmp_path` é acusado e o cenário conforme passa. Mais os
três contratos: sensor cego vira problema (CST-10), rodar duas vezes não duplica (CST-06) e a fila recebe um item
por regra e sistema — não uma mensagem por violação.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

import pytest
import yaml

from compliance_agent.qualidade import sensores

AGORA = datetime(2026, 11, 13, 22, 0)
PROV = {"fonte": "SIAFE", "data_ref": "2026-11-12", "cobertura": "100% das UGs", "estado": "PENDENTE",
        "natureza": "pago", "esfera": "estadual"}


def _ctx(tmp_path, payloads=None, manchetes=None, metricas=None):
    """Repositório, dados e vault sintéticos. `payloads`: rota → dict (ou Exception para simular rota fora do ar)."""
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True, exist_ok=True)
    (repo / "config" / "qualidade_inventario.yaml").write_text(yaml.safe_dump({"manchetes": manchetes or []}), encoding="utf-8")
    (repo / "config" / "qualidade_metricas.yaml").write_text(yaml.safe_dump({"metricas": metricas or []}), encoding="utf-8")
    payloads = payloads or {}

    def api(rota):
        r = payloads.get(rota)
        if r is None or isinstance(r, Exception):
            raise r if isinstance(r, Exception) else OSError(f"sem rota {rota}")
        return r
    return sensores.Ctx(dados=tmp_path / "data", vault=tmp_path / "vault", hermes=tmp_path / "hermes",
                        hermes_agent=tmp_path / "hermes-agent", repo=repo, api=api, agora=AGORA)


M = [{"id": "cki-x", "rota": "/api/x", "campos": {"valor": "total", "contagem": "n"}}]


# ───────────────────────── proveniência ─────────────────────────
def test_prova_manchete_sem_proveniencia_e_acusada(tmp_path):
    vio = sensores.sensor_proveniencia(_ctx(tmp_path, {"/api/x": {"total": 10.0, "n": 2}}, M))
    assert [x["regra"] for x in vio] == ["PAD-01"] and vio[0]["chave"] == "cki-x"
    ok = sensores.sensor_proveniencia(_ctx(tmp_path, {"/api/x": {"total": 10.0, "proveniencia": PROV}}, M))
    assert not ok


def test_prova_proveniencia_parcial_aponta_cada_regra(tmp_path):
    p = {"proveniencia": PROV | {"estado": "", "esfera": "", "natureza": ""}}
    assert {x["regra"] for x in sensores.sensor_proveniencia(_ctx(tmp_path, {"/api/x": p}, M))} == {"PAD-02", "PAD-06", "PAD-07"}


# ───────────────────────── payloads ─────────────────────────
def test_prova_payload_com_cpf_lista_no_teto_e_rota_muda(tmp_path):
    m = M + [{"id": "cki-y", "rota": "/api/y", "campos": {}}]
    p = {"/api/x": {"itens": [{"nome": "Fulano Sintético", "doc": "111.444.777-35"}] * 100}, "/api/y": OSError("caiu")}
    vio = sensores.sensor_payloads_painel(_ctx(tmp_path, p, m))
    assert {x["regra"] for x in vio} == {"PAD-04", "COR-07", "CST-10"}
    assert "111.444.777-35" not in json.dumps(vio)                              # a violação não vaza o CPF
    limpo = {"/api/x": {"itens": [{"doc": "***.444.777-**"}] * 100, "n": 554}, "/api/y": {"ok": True}}
    assert not sensores.sensor_payloads_painel(_ctx(tmp_path, limpo, m))


def test_prova_manchete_refem_de_poucos_registros(tmp_path):
    m = [{"id": "cki-f", "rota": "/api/f", "campos": {"valor": "total"},
          "concentracao": {"lista": "achados", "item": "valor", "filtro": {"conta": True}}}]
    itens = [{"valor": 95.0, "conta": True}] + [{"valor": 1.0, "conta": True}] * 5 + [{"valor": 9999.0, "conta": False}]
    vio = sensores.sensor_payloads_painel(_ctx(tmp_path, {"/api/f": {"total": 100.0, "achados": itens, "n": 7}}, m))
    assert [x["regra"] for x in vio] == ["COR-11"]
    diz = {"total": 100.0, "achados": itens, "n": 7, "concentracao_top3": 0.97}
    assert not sensores.sensor_payloads_painel(_ctx(tmp_path, {"/api/f": diz}, m))  # a manchete já informa: conforme


# ───────────────────────── variação de manchete ─────────────────────────
def test_prova_variacao_brusca_entre_execucoes(tmp_path):
    assert not sensores.sensor_manchetes_variacao(_ctx(tmp_path, {"/api/x": {"total": 592_785_486.56, "n": 146}}, M))  # 1ª leitura
    vio = sensores.sensor_manchetes_variacao(_ctx(tmp_path, {"/api/x": {"total": 16_390_000.0, "n": 14}}, M))
    assert {x["chave"] for x in vio} == {"cki-x:valor", "cki-x:contagem"} and all(x["regra"] == "CST-02" for x in vio)
    assert not sensores.sensor_manchetes_variacao(_ctx(tmp_path, {"/api/x": {"total": 16_500_000.0, "n": 14}}, M))    # +0,7%: normal
    serie = json.loads((tmp_path / "data" / "qualidade_manchetes.json").read_text())["cki-x"]
    assert len(serie) == 3


def test_leitura_repetida_nao_engorda_o_historico(tmp_path):
    for _ in range(3):
        sensores.sensor_manchetes_variacao(_ctx(tmp_path, {"/api/x": {"total": 5.0, "n": 1}}, M))
    assert len(json.loads((tmp_path / "data" / "qualidade_manchetes.json").read_text())["cki-x"]) == 1


# ───────────────────────── constância ─────────────────────────
def test_prova_constancia_parte_maior_que_todo_cache_velho_e_total_x_lista(tmp_path):
    met = [
        {"id": "parte", "tipo": "parte_todo", "titulo": "parte × todo", "parte": {"rota": "/api/e", "campo": "por_orgao.0.economia"},
         "todo": {"rota": "/api/e", "campo": "economia_total"}},
        {"id": "cache", "regra": "CST-07", "tipo": "igual", "titulo": "servido × arquivo", "a": {"rota": "/api/r", "campo": "n"},
         "b": {"arquivo": "cache/r.json", "campo": "n"}},
        {"id": "lista", "regra": "CST-13", "tipo": "total_lista", "titulo": "total × lista", "total": {"arquivo": "cache/r.json", "campo": "total_alto"},
         "lista": {"arquivo": "cache/r.json", "lista": "grupos", "item": "v", "filtro": {"grau": "alto"}}},
    ]
    ctx = _ctx(tmp_path, {"/api/e": {"economia_total": 5.0, "por_orgao": [{"economia": 25.0}]}, "/api/r": {"n": 3}}, metricas=met)
    (ctx.dados / "cache").mkdir(parents=True)
    (ctx.dados / "cache" / "r.json").write_text(json.dumps(
        {"n": 1, "total_alto": 1772.0, "grupos": [{"v": 10.0, "grau": "alto"}, {"v": 7.0, "grau": "alto"}, {"v": 900.0, "grau": "baixo"}]}))
    vio = {x["chave"]: x["regra"] for x in sensores.sensor_constancia_superficies(ctx)}
    assert vio == {"parte": "CST-01", "cache": "CST-07", "lista": "CST-13"}
    (ctx.dados / "cache" / "r.json").write_text(json.dumps({"n": 3, "total_alto": 17.0, "grupos": [{"v": 10.0, "grau": "alto"}, {"v": 7.0, "grau": "alto"}]}))
    ctx2 = _ctx(tmp_path, {"/api/e": {"economia_total": 50.0, "por_orgao": [{"economia": 25.0}]}, "/api/r": {"n": 3}}, metricas=met)
    assert not sensores.sensor_constancia_superficies(ctx2)


# ───────────────────────── motores ─────────────────────────
def test_prova_motor_rodando_sem_efeito(tmp_path):
    est = {"motores": [{"id": "a", "nome": "A", "efeito": {"ultimo": "2026-11-10T00:00:00", "horas": 24, "parado": True}},
                       {"id": "b", "efeito": {"parado": False}}, {"id": "c", "efeito": None}]}
    vio = sensores.sensor_motores_sem_efeito(_ctx(tmp_path, {"/api/ao-vivo/estado": est}))
    assert [x["chave"] for x in vio] == ["a"] and vio[0]["regra"] == "CST-03"


# ───────────────────────── vault ─────────────────────────
def _caso(ctx, nome, fm, corpo):
    pasta = ctx.vault / "casos"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / nome).write_text("---\n" + yaml.safe_dump(fm, allow_unicode=True) + "---\n" + corpo, encoding="utf-8")


def test_prova_casos_do_vault(tmp_path):
    ctx = _ctx(tmp_path)
    _caso(ctx, "incoerente.md", {"tipo": "caso", "grau": "alto", "status": "aberto", "esfera": "estadual"},
          "# Caso\n\n**Desfecho:** 🟢 sem irregularidade — a diferença era devolução bancária.\n\n"
          "Fonte: DOERJ de 12/03/2026, p. 14: «o termo foi publicado com vigência a partir de janeiro de 2026»\n")
    _caso(ctx, "sem-prova.md", {"tipo": "caso", "grau": "alto", "status": "aberto", "esfera": "estadual"},
          "# Caso\n\nO detector apontou score 10/10 para o fornecedor Alfa (fictício).\n")
    _caso(ctx, "sem-esfera.md", {"tipo": "caso", "grau": "medio", "status": "aberto"}, "# Caso\n\nNota.\n")
    _caso(ctx, "revisado.md", {"tipo": "caso", "severidade": "🔴 9/10", "status": "aberto — conferir", "esfera": "estadual",
                               "grau_revisado": "🟢 vedação afastada"},
          "# Caso\n\nFonte: DOERJ de 12/03/2026, p. 14: «o termo foi publicado com vigência a partir de janeiro de 2026»\n")
    _caso(ctx, "conforme.md", {"tipo": "caso", "grau": "alto", "status": "aberto", "esfera": "estadual"},
          "# Caso\n\nFonte: DOERJ de 12/03/2026, p. 14:\n\n> o extrato do termo de ajuste de contas nº 06 foi publicado nesta data\n")
    vio = {(x["chave"], x["regra"]) for x in sensores.sensor_vault_casos(ctx)}
    assert vio == {("incoerente.md", "CST-08"), ("sem-prova.md", "COR-01"), ("sem-esfera.md", "CNF-12"),
                   ("revisado.md", "CST-08")}


def test_prova_revisao_sem_errata(tmp_path):
    ctx = _ctx(tmp_path)
    _caso(ctx, "c.md", {"tipo": "caso", "grau": "baixo", "status": "encerrado"}, "x\n")
    (ctx.vault / "notas").mkdir()
    (ctx.vault / "notas" / "revisao-cetica-2026-11-13.md").write_text("| D1 | **REFUTADA** |\n| D2 | **PARCIAL** |\n", encoding="utf-8")
    assert [x["regra"] for x in sensores.sensor_vault_casos(ctx)] == ["CST-14"]
    (ctx.vault / "notas" / "errata-2026-11-13.md").write_text("errata\n", encoding="utf-8")
    assert not sensores.sensor_vault_casos(ctx)


def test_vault_sem_caso_legivel_e_cegueira_nao_zero(tmp_path):
    ctx = _ctx(tmp_path)
    (ctx.vault / "casos").mkdir(parents=True)
    with pytest.raises(RuntimeError):
        sensores.sensor_vault_casos(ctx)


# ───────────────────────── base de alertas e OB ─────────────────────────
def _banco(ctx, alertas, obs):
    ctx.dados.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ctx.dados / "compliance.db")
    con.execute("CREATE TABLE IF NOT EXISTS alertas (id INTEGER PRIMARY KEY, tipo TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS ob_orcamentaria_siafe (numero_ob TEXT, valor REAL)")
    con.execute("DELETE FROM alertas")
    con.execute("DELETE FROM ob_orcamentaria_siafe")
    con.executemany("INSERT INTO alertas (tipo) VALUES (?)", [(t,) for t in alertas])
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?, 1.0)", [(o,) for o in obs])
    con.commit()
    con.close()


def test_prova_alertas_sem_codigo_salto_de_volume_tipo_dominante_e_ob_sem_chave(tmp_path):
    ctx = _ctx(tmp_path)
    _banco(ctx, ["acumulacao"] * 300 + ["teto"] * 300 + [""] * 2, ["2026OB1", ""])
    assert {x["regra"] for x in sensores.sensor_alertas_base(ctx)} == {"PAD-10", "COR-12"}      # 1ª leitura: sem salto
    _banco(ctx, ["acumulacao"] * 5800 + ["teto"] * 300, ["2026OB1"])
    vio = sensores.sensor_alertas_base(ctx)
    assert sorted(x["chave"] for x in vio) == ["alertas:acumulacao", "alertas:acumulacao:dominante"]
    assert all(x["regra"] == "COR-16" for x in vio)


def test_banco_ausente_e_cegueira(tmp_path):
    with pytest.raises(RuntimeError):
        sensores.sensor_alertas_base(_ctx(tmp_path))


# ───────────────────────── gasto, Hermes, juiz ─────────────────────────
def test_prova_gasto_de_api_perto_do_teto(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.dados.mkdir(parents=True)
    (ctx.dados / "claude_api_gasto.json").write_text(json.dumps({"total_usd": 85.0}))
    assert [x["regra"] for x in sensores.sensor_gasto_api(ctx)] == ["CNF-10"]
    (ctx.dados / "claude_api_gasto.json").write_text(json.dumps({"total_usd": 0.03}))
    assert not sensores.sensor_gasto_api(ctx)


def test_prova_personalizacao_do_hermes_sumiu(tmp_path):
    ctx = _ctx(tmp_path)
    ad = ctx.hermes_agent / "plugins" / "platforms" / "telegram"
    ad.mkdir(parents=True)
    (ad / "adapter.py").write_text("_JFN_MENU_TEXT = 1\n_JFN_MENU_HINTS = 1\n", encoding="utf-8")   # o update levou duas
    vio = sensores.sensor_hermes_personalizacoes(ctx)
    assert {x["chave"] for x in vio} == {"hermes:_aplicar_orcamento_de_imagem", "hermes:_ORCAMENTO_IMAGEM_TURNO", "hermes:script_seguro"}
    (ad / "adapter.py").write_text("\n".join(sensores.MARCADORES_HERMES), encoding="utf-8")
    (ctx.hermes_agent / "update-hermes-safe.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    assert not sensores.sensor_hermes_personalizacoes(ctx)


def test_prova_juiz_calado_e_nota_baixa(tmp_path):
    ctx = _ctx(tmp_path)
    assert [x["chave"] for x in sensores.sensor_juiz_qualidade(ctx)] == ["juiz:nunca"]
    ctx.dados.mkdir(parents=True)
    av = {"id": "painel:cki-x", "sistema": "painel", "rotulo": "card X", "notas": {"moldura": 1, "clareza": 4},
          "motivos": {"moldura": "afirma mais que o dado"}, "escalar": True}
    (ctx.dados / "qualidade_juiz.json").write_text(json.dumps({"em": (AGORA - timedelta(hours=60)).isoformat(), "avaliacoes": [av]}))
    vio = {x["chave"]: x["regra"] for x in sensores.sensor_juiz_qualidade(ctx)}
    assert vio == {"juiz:silencio": "CST-15", "juiz:painel:cki-x:moldura": "SUB-02"}


# ───────────────────────── contratos do laço ─────────────────────────
def test_sensor_cego_vira_problema(tmp_path):
    """CST-10: sensor que levanta entra em `cegos` e vira item `sensor:` na fila — nunca some, nunca vira "ok"."""
    def quebrado(ctx):
        raise RuntimeError("rota fora do ar")
    est = sensores.rodar(_ctx(tmp_path), {"quebrado": quebrado, "limpo": lambda ctx: []})
    assert est["total"] == 0 and list(est["cegos"]) == ["quebrado"]
    itens = sensores.para_automelhoria(est)
    assert [(i["area"], i["chave"]) for i in itens] == [("sensor", "qualidade.quebrado")]


def test_rodar_duas_vezes_nao_duplica(tmp_path):
    """CST-06: duas rodadas na mesma hora = uma linha no histórico e a mesma fotografia."""
    sens = {"s": lambda ctx: [sensores.violacao("PAD-01", "painel", "cki-x", "sem proveniência")]}
    ctx = _ctx(tmp_path)
    a = sensores.rodar(ctx, sens)
    b = sensores.rodar(ctx, sens)
    assert a == b
    assert len((ctx.dados / "qualidade_historico.jsonl").read_text().splitlines()) == 1
    ctx.agora = AGORA + timedelta(hours=1)
    sensores.rodar(ctx, sens)
    assert len((ctx.dados / "qualidade_historico.jsonl").read_text().splitlines()) == 2


def test_fila_recebe_um_item_por_regra_e_sistema(tmp_path):
    sens = {"s": lambda ctx: [sensores.violacao("PAD-01", "painel", f"cki-{i}", f"manchete {i} sem proveniência") for i in range(12)]
            + [sensores.violacao("CST-08", "vault", "c.md", "caso incoerente")]}
    est = sensores.rodar(_ctx(tmp_path), sens)
    itens = sensores.para_automelhoria(est)
    assert [i["chave"] for i in itens] == ["CST-08:vault", "PAD-01:painel"]
    assert "12 violação(ões)" in itens[1]["titulo"] and itens[1]["severidade"] == "alta"
    assert est["violacoes"][0]["severidade"] == "alta" and est["violacoes"][0]["sensor"] == "s"


def test_notas_do_juiz_viram_um_item_por_sistema(tmp_path):
    sens = {"juiz_qualidade": lambda ctx: [
        sensores.violacao("SUB-02", "painel", "juiz:painel:cki-x:moldura", "nota 1 em moldura"),
        sensores.violacao("SUB-03", "painel", "juiz:painel:cki-x:inocente", "nota 1 em inocente"),
        sensores.violacao("SUB-07", "painel", "juiz:painel:cki-y:utilidade", "nota 1 em utilidade")]}
    itens = sensores.para_automelhoria(sensores.rodar(_ctx(tmp_path), sens))
    assert [i["chave"] for i in itens] == ["SUB:painel"] and "2 afirmação(ões)" in itens[0]["titulo"]
    assert itens[0]["severidade"] == "bloqueante" and "painel:cki-x" in itens[0]["detalhe"]


def test_todo_sensor_registrado_e_usado_por_alguma_regra():
    """Produtor sem consumidor (CST-04): sensor que nenhuma regra aponta é trabalho que ninguém cobra."""
    from compliance_agent.qualidade import regras
    usados = {ref for r in regras.carregar() for ref in r.refs("sensor")}
    assert set(sensores.SENSORES) == usados, f"sensores sem regra: {set(sensores.SENSORES) - usados}; regras sem sensor: {usados - set(sensores.SENSORES)}"
