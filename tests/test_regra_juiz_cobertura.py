# -*- coding: utf-8 -*-
"""Juiz com cobertura TOTAL (20/11/2026, dono: "como que o juiz não julga tudo? precisa julgar, não apenas um baixo
limite"). Antes: amostra de 6–12 por noite sobre 166 candidatas; texto corrigido levava dias para ser rejulgado.

Agora: fila completa por impressão do texto (cache por conteúdo), lotes de K numa chamada (JSON por item, com o id
ecoado), orçamento por tempo que corta e retoma, e cobertura medida (sensor CST-15 acusa pendente há > 48 h).
Nenhum teste chama o Claude de verdade (executor dublê).
"""
from __future__ import annotations

import fcntl
import json
import re
from datetime import datetime, timedelta

import pytest

from compliance_agent.llm import claude_motor
from compliance_agent.qualidade import estado, juiz, regras, sensores

AGORA = datetime(2026, 11, 20, 23, 0)
BOAS = {c: 4 for c in regras.rubricas()}


def _af(i, **kw) -> juiz.Afirmacao:
    base = dict(id=f"vault:caso-{i}", sistema="vault", rotulo=f"caso {i}", grau="alto", valor=10.0 ** (i % 7 + 1),
                texto=f"Empresa Fictícia {i} recebeu R$ {i}.000,00; indício a verificar.")
    return juiz.Afirmacao(**(base | kw))


def _julgada(a: juiz.Afirmacao, em: datetime = AGORA, notas: dict | None = None, impressao: str | None = None) -> dict:
    return {"id": a.id, "impressao": impressao or a.impressao, "em": em.isoformat(), "estado": "JULGADA",
            "notas": notas or {"moldura": 3}}


def _ids_do_prompt(prompt: str) -> list[tuple[str, str]]:
    return re.findall(r"ITEM (A\d+) — id: (\S+) \(", prompt)


def _pensar_lote(chamadas: list, notas: dict | None = None, estragar=None):
    """Dublê do Claude: responde ao prompt de lote com JSON por item (ou ao de 1 item com o JSON simples)."""
    def pensar(tarefa, prompt, **kw):
        chamadas.append({"tarefa": tarefa, "prompt": prompt, **kw})
        itens = _ids_do_prompt(prompt)
        n = notas or BOAS
        if not itens:
            corpo = {"notas": n, "motivos": {}, "veredito": "aprovada", "o_que_falta": "", "escalar": False}
        else:
            corpo = {"itens": {rot: {"id": iid, "notas": n, "motivos": {}, "o_que_falta": "", "escalar": False}
                               for rot, iid in itens}}
        texto = json.dumps(corpo, ensure_ascii=False)
        if estragar:
            texto = estragar(corpo, texto)
        return claude_motor.Pensamento(texto=texto, modelo="claude-duble", segundos=0.1, tarefa=tarefa)
    return pensar


def _ctx(tmp_path, n_casos: int = 0) -> sensores.Ctx:
    ctx = sensores.Ctx(dados=tmp_path / "dados", vault=tmp_path / "vault", hermes=tmp_path / "h", repo=tmp_path / "repo",
                       api=lambda r: {}, agora=AGORA)
    casos = tmp_path / "vault" / "casos"
    casos.mkdir(parents=True, exist_ok=True)
    for i in range(n_casos):
        (casos / f"caso-{i:02d}.md").write_text(f"---\ntipo: caso\ngrau: alto\nstatus: aberto\nvalor: {1000 * (i + 1)}\n---\n"
                                                f"Achado sintético {i}.\n", encoding="utf-8")
    return ctx


# ───────────────────────── fila completa e cache por conteúdo ─────────────────────────
def test_fila_ordena_corrigida_nova_mudada_e_revalidacao_no_fim():
    cands = [_af(i) for i in range(6)]
    hist = {
        cands[0].id: _julgada(cands[0]),                                             # vigente: não volta
        cands[1].id: _julgada(cands[1], notas={"moldura": 1}, impressao="antiga"),   # reprovada e corrigida
        cands[2].id: _julgada(cands[2], impressao="antiga"),                         # aprovada, texto mudou
        cands[3].id: _julgada(cands[3], em=AGORA - timedelta(days=45)),              # texto igual, veredito velho
    }
    ordem = [a.id for a in juiz.fila(cands, hist, AGORA)]
    assert cands[0].id not in ordem                                                  # controle negativo
    assert ordem[0] == cands[1].id                                                   # (a) corrigida
    assert set(ordem[1:3]) == {cands[4].id, cands[5].id}                             # (b) nunca julgadas
    assert ordem[3] == cands[2].id and ordem[-1] == cands[3].id                      # (c) mudada · (d) revalidar
    assert juiz.situacao(cands[0], hist, AGORA) == "vigente"
    assert juiz.situacao(cands[3], hist, AGORA) == "revalidar"


def test_revalidacao_desligada_pelo_ambiente(monkeypatch):
    a = _af(1)
    hist = {a.id: _julgada(a, em=AGORA - timedelta(days=400))}
    monkeypatch.setenv("JFN_JUIZ_REVALIDAR_DIAS", "0")
    assert juiz.fila([a], hist, AGORA) == []                                         # cache por conteúdo puro


def test_superficie_retirada_que_volta_e_julgada_de_novo():
    a = _af(1)
    hist = {a.id: _julgada(a) | {"estado": "SUPERFICIE_RETIRADA"}}
    assert [x.id for x in juiz.fila([a], hist, AGORA)] == [a.id]


def test_nunca_julgada_reserva_a_cabeca_de_cada_grupo():
    cands = [_af(i, id=f"painel:m{i}", sistema="painel", grau="manchete", valor=10.0 ** (9 - i), publica=True) for i in range(4)]
    cands += [_af(9, id="yoda:y", sistema="yoda", grau="", valor=1.0), _af(8, id="produto:rel", sistema="relatorios", valor=1.0)]
    ordem = [a.id for a in juiz.fila(cands, {}, AGORA)]
    assert ordem[0] == "painel:m0" and set(ordem[1:3]) == {"yoda:y", "produto:rel"} and ordem[3:] == ["painel:m1", "painel:m2", "painel:m3"]


# ───────────────────────── lotes ─────────────────────────
def test_lotes_respeitam_rubrica_canal_e_tamanho():
    vault = [_af(i) for i in range(5)]                                               # publica=False
    painel = [_af(i, id=f"painel:c{i}", sistema="painel", grau="manchete", publica=True) for i in range(3)]
    plano = juiz.lotes([vault[0], painel[0], *vault[1:], *painel[1:]], 4)
    assert [len(x) for x in plano] == [4, 3, 1]
    for lt in plano:
        assert len({juiz.chave_lote(a) for a in lt}) == 1                           # nunca mistura canal/rubrica
    assert plano[0][0].id == vault[0].id and plano[1][0].id == painel[0].id          # cabeça da fila abre o lote


def test_lote_numa_chamada_so_pela_assinatura_com_prazo_proporcional():
    lote, chamadas = [_af(i) for i in range(4)], []
    avs = juiz.julgar_lote(lote, pensar=_pensar_lote(chamadas), agora=AGORA)
    assert len(chamadas) == 1 and chamadas[0]["backend"] == "cli" and chamadas[0]["modelo"] == claude_motor.MODELO_JUIZO
    assert chamadas[0]["timeout"] == juiz.timeout_lote(4) > juiz.TIMEOUT_ITEM_S
    assert [av.estado for av in avs] == ["JULGADA"] * 4 and all(av.veredito == "aprovada" for av in avs)
    for a in lote:
        assert a.texto in chamadas[0]["prompt"] and f"id: {a.id}" in chamadas[0]["prompt"]


def test_json_parcial_so_o_item_ruim_volta_para_a_fila():
    lote = [_af(i) for i in range(4)]

    def estragar(corpo, _):
        it = corpo["itens"]
        del it["A2"]                                                                 # item faltando
        it["A3"]["id"] = lote[0].id                                                  # id trocado
        it["A4"]["notas"] = {"moldura": 9, "auditor": "alta"}                        # nota fora da escala
        return json.dumps(corpo)
    avs = juiz.julgar_lote(lote, pensar=_pensar_lote([], estragar=estragar), agora=AGORA)
    assert [av.estado for av in avs] == ["JULGADA", "PENDENTE", "PENDENTE", "PENDENTE"]
    assert all(not av.notas for av in avs[1:])                                       # nada inventado
    assert "ausente ou com id trocado" in avs[1].juiz and "sem notas" in avs[3].juiz


def test_json_invalido_nao_grava_nota_de_ninguem(tmp_path):
    ctx = _ctx(tmp_path, 3)
    r = juiz.rodar(ctx, None, pensar=_pensar_lote([], estragar=lambda c, t: "não consigo avaliar {"), lote=4)
    assert r["julgadas_nesta_rodada"] == 0 and r["vigentes"] == 0 and r["pendentes"] == 3
    hist = json.loads((ctx.dados / "qualidade_juiz_historico.json").read_text(encoding="utf-8"))
    assert not any(h.get("estado") == "JULGADA" for h in hist.values())


def test_lote_interno_nunca_vai_a_cascata(monkeypatch):
    monkeypatch.setenv("JFN_JUIZ_CRUZAR", "1")
    usou = []
    juiz.julgar_lote([_af(i) for i in range(3)], pensar=_pensar_lote([]), cascata=lambda *a, **k: usou.append(1) or "{}",
                     agora=AGORA)
    assert not usou
    with pytest.raises(ValueError):                                                  # misturar canais é erro, não silêncio
        juiz.julgar_lote([_af(1), _af(2, publica=True)], pensar=_pensar_lote([]), agora=AGORA)


def test_normalizar_lote_e_o_pior_veredito_pelas_notas():
    txt = json.dumps({"itens": {"A1": {"notas": {"moldura": 4}}, "A2": {"notas": {"moldura": 1}, "veredito": "aprovada"}}})
    assert juiz.normalizar_lote(txt)[:2] == ("reprovada", 2)
    assert juiz.normalizar_lote("lixo") == (None, None, None)


# ───────────────────────── rodada até esvaziar, orçamento e retomada ─────────────────────────
def test_ate_esvaziar_julga_tudo_em_lotes_e_a_segunda_rodada_nao_rejulga(tmp_path):
    ctx, chamadas = _ctx(tmp_path, 10), []
    r = juiz.rodar(ctx, None, pensar=_pensar_lote(chamadas), lote=4)
    assert r["julgadas_nesta_rodada"] == 10 and len(chamadas) == 3 == r["chamadas"]   # 4 + 4 + 2
    assert r["cobertura_pct"] == 100.0 and r["pendentes"] == 0 and r["candidatas"] == 10
    chamadas.clear()
    r2 = juiz.rodar(ctx, None, pensar=_pensar_lote(chamadas), lote=4)
    assert not chamadas and r2["julgadas_nesta_rodada"] == 0 and r2["vigentes"] == 10   # controle negativo


def test_orcamento_de_tempo_corta_no_meio_grava_e_retoma(tmp_path):
    ctx, chamadas = _ctx(tmp_path, 10), []
    relogio = iter([0.0, 0.0, 30 * 60.0]).__next__                                   # início · 1º lote · já sem tempo
    r = juiz.rodar(ctx, None, pensar=_pensar_lote(chamadas), lote=4, minutos=30, relogio=relogio)
    assert len(chamadas) == 1 and r["julgadas_nesta_rodada"] == 4 and r["pendentes"] == 6
    assert "orçamento de tempo" in r["parada"]
    disco = json.loads((ctx.dados / "qualidade_juiz_fila.json").read_text(encoding="utf-8"))
    assert disco["pendentes"] == 6 and disco["julgadas_vigentes"] == 4
    julgados = {iid for c in chamadas for _, iid in _ids_do_prompt(c["prompt"])}
    chamadas.clear()
    r2 = juiz.rodar(ctx, None, pensar=_pensar_lote(chamadas), lote=4)
    assert r2["pendentes"] == 0 and r2["julgadas_nesta_rodada"] == 6
    assert not julgados & {iid for c in chamadas for _, iid in _ids_do_prompt(c["prompt"])}   # retomou, não repetiu


def test_teto_do_motor_para_limpo_e_guarda_o_progresso(tmp_path):
    ctx, n = _ctx(tmp_path, 10), {"i": 0}
    boa = _pensar_lote([])

    def pensar(tarefa, prompt, **kw):
        n["i"] += 1
        if n["i"] > 1:
            claude_motor.ultimo_motivo = "teto diário da tarefa juiz_qualidade (40 chamadas)"
            return None
        return boa(tarefa, prompt, **kw)
    r = juiz.rodar(ctx, None, pensar=pensar, lote=4)
    assert n["i"] == 2 and r["julgadas_nesta_rodada"] == 4 and "teto diário" in r["parada"]
    assert r["em"] == AGORA.isoformat(timespec="seconds")                            # houve juízo: rodada vale


def test_n_compativel_limita_afirmacoes_nao_chamadas(tmp_path):
    ctx, chamadas = _ctx(tmp_path, 10), []
    r = juiz.rodar(ctx, 6, pensar=_pensar_lote(chamadas), lote=4)
    assert r["julgadas_nesta_rodada"] == 6 and len(chamadas) == 2 and r["pendentes"] == 4


def test_texto_corrigido_volta_na_mesma_noite(tmp_path):
    ctx = _ctx(tmp_path, 3)
    juiz.rodar(ctx, None, pensar=_pensar_lote([], notas=BOAS | {"inocente": 1}), lote=4)
    (tmp_path / "vault" / "casos" / "caso-01.md").write_text(
        "---\ntipo: caso\ngrau: alto\nstatus: aberto\nvalor: 2000\n---\nAchado sintético 1, hipótese inocente descartada.\n",
        encoding="utf-8")
    chamadas = []
    r = juiz.rodar(ctx, None, pensar=_pensar_lote(chamadas), lote=4)
    assert len(chamadas) == 1 and "hipótese inocente descartada" in chamadas[0]["prompt"]   # só a corrigida volta
    assert r["reprovadas"] == ["vault:caso-00", "vault:caso-02"]


# ───────────────────────── cobertura medida, sensor e painel ─────────────────────────
def test_cobertura_conta_e_guarda_desde_quando_esta_pendente():
    cands = [_af(i) for i in range(4)]
    hist = {cands[0].id: _julgada(cands[0])}
    c1 = juiz.cobertura(cands, hist, AGORA - timedelta(hours=60), None, 4)
    assert (c1["candidatas"], c1["julgadas_vigentes"], c1["pendentes"], c1["cobertura_pct"]) == (4, 1, 3, 25.0)
    assert c1["chamadas_para_zerar"] == 1
    c2 = juiz.cobertura(cands, hist, AGORA, c1, 4)
    assert c2["mais_antiga_pendente_dias"] == 2.5                                    # a data veio da medição anterior
    cands[1].texto += " (texto novo)"                                                # mudou: o relógio recomeça
    c3 = juiz.cobertura(cands, hist, AGORA, c2, 4)
    assert c3["pendentes_desde"][cands[1].id]["desde"] == AGORA.isoformat(timespec="seconds")


def _grava_fila(ctx, cob: dict) -> None:
    ctx.dados.mkdir(parents=True, exist_ok=True)
    (ctx.dados / "qualidade_juiz.json").write_text(json.dumps({"em": AGORA.isoformat(), "avaliacoes": []}), encoding="utf-8")
    (ctx.dados / "qualidade_juiz_fila.json").write_text(json.dumps(cob), encoding="utf-8")


def test_sensor_acusa_pendente_ha_mais_de_48h(tmp_path):
    ctx = _ctx(tmp_path)
    cands = [_af(i) for i in range(3)]
    _grava_fila(ctx, juiz.cobertura(cands, {}, AGORA - timedelta(hours=50), None, 4))
    vio = [x for x in sensores.sensor_juiz_qualidade(ctx) if x["chave"] == "juiz:cobertura"]
    assert len(vio) == 1 and vio[0]["regra"] == "CST-15" and "3 há mais de 48 h" in vio[0]["titulo"]


def test_prova_sensor_quieto_com_pendente_recente_ou_cobertura_total(tmp_path):
    ctx = _ctx(tmp_path)
    cands = [_af(i) for i in range(3)]
    _grava_fila(ctx, juiz.cobertura(cands, {}, AGORA - timedelta(hours=10), None, 4))
    assert not [x for x in sensores.sensor_juiz_qualidade(ctx) if x["chave"] == "juiz:cobertura"]
    _grava_fila(ctx, juiz.cobertura(cands, {a.id: _julgada(a) for a in cands}, AGORA - timedelta(days=9), None, 4))
    assert not [x for x in sensores.sensor_juiz_qualidade(ctx) if x["chave"] == "juiz:cobertura"]


def test_painel_mostra_a_cobertura_do_juiz(tmp_path):
    ctx = _ctx(tmp_path)
    cands = [_af(i) for i in range(4)]
    _grava_fila(ctx, juiz.cobertura(cands, {cands[0].id: _julgada(cands[0])}, AGORA - timedelta(days=3), None, 4))
    j = estado.painel(ctx.dados, AGORA)["juiz"]
    assert (j["candidatas"], j["julgadas_vigentes"], j["cobertura_pct"], j["pendentes"]) == (4, 1, 25.0, 3)
    assert j["mais_antiga_pendente_dias"] == 3.0                                     # contada AGORA, não na gravação


def test_medir_fila_nao_chama_modelo_e_respeita_a_rodada_em_curso(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, 3)
    monkeypatch.setattr(juiz, "julgar_lote", lambda *a, **k: pytest.fail("medir a fila não julga"))
    r = juiz.medir_fila(ctx, 4)
    assert r["gravado"] and r["pendentes"] == 3 and r["chamadas_para_zerar"] == 1
    with open(ctx.dados / "qualidade_juiz.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        assert juiz.medir_fila(ctx, 4)["gravado"] is False
