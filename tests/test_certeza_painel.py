# -*- coding: utf-8 -*-
"""Painel de certeza, rota e sensor da automelhoria (docs/ARQUITETURA-DE-CERTEZA.md) — sem rede, em tmp_path."""
import json
import sqlite3
import time

import pytest

from compliance_agent.certeza import config, fatos, orquestrador


@pytest.fixture()
def pasta(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CERTEZA_DIR", str(tmp_path / "certeza"))
    for k in ("SINCRONIZAR", "CEREBRO", "GATILHOS", "KILL"):
        monkeypatch.delenv(f"JFN_CERTEZA_{k}", raising=False)
    return config.dados()


def _mapa(tmp_path, valor=10.0):
    (tmp_path / "d.json").write_text(json.dumps({"gerado_em": "2026-11-18T10:00:00", "total": valor}), encoding="utf-8")
    bloco = {"id": "demo:total", "arquivo": "d.json", "data_ref": "gerado_em", "fonte": "teste", "nivel_prova": 2, "estado": "VERIFICADO",
             "medidas": {"valor": {"campo": "total", "unidade": "BRL"}}}
    return {"fontes": {"f": {"nome": "f", "sonda": {"sql": "x"}}},
            "derivados": {"demo": {"nome": "d", "depende": ["f"], "comando": ["x"], "onde": "aba", "efeito": {"arquivo": "d.json"}, "fatos": [bloco]}},
            "contratos": {"fila": {"tabela": "fila", "chave": ["k"], "colunas": {"total_pago": {"monetaria": True, "min": 0}}}},
            "certeza": {"superficies": {"notas": {"pasta": str(tmp_path / "notas"), "glob": "*.md"}}}, "cerebro": []}


def _banco(tmp_path, valores=(10.0,)):
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE IF NOT EXISTS fila(k TEXT PRIMARY KEY, total_pago REAL)")
    con.execute("DELETE FROM fila")
    con.executemany("INSERT INTO fila VALUES (?,?)", [(str(i), v) for i, v in enumerate(valores)])
    con.commit()
    con.close()
    return db


def _ciclo(tmp_path, **k):
    (tmp_path / "notas").mkdir(exist_ok=True)
    if "cfg" not in k:
        k["cfg"] = _mapa(tmp_path)
    if "compliance_db" not in k:
        k["compliance_db"] = _banco(tmp_path)
    return orquestrador.ciclo(estado_prop={"ok": False}, raiz=tmp_path, buscar=None, cron="", **k)


def test_painel_grava_estado_e_relatorio_com_proveniencia_de_cada_fato(pasta, tmp_path):
    est = _ciclo(tmp_path)
    assert est["resumo"]["fatos"] == 1 and est["resumo"]["violacoes_de_contrato"] == 0 and est["resumo"]["divergencias_abertas"] == 0
    f = est["fatos"][0]
    assert f["id"] == "demo:total:valor" and f["valor_fmt"] == "R$ 10,00" and f["citar"] == "R$ 10,00<!--fato:demo:total:valor-->"
    assert set(f["proveniencia"]) == {"fonte", "consulta", "data_ref", "hash_fonte", "produtor"} and all(f["proveniencia"].values())
    assert set(est["proveniencia"]) == {"fonte", "data_ref", "cobertura"}                       # PAD-01 na própria rota
    lido = orquestrador.ler_estado()
    assert lido["ok"] and lido["fatos"][0]["id"] == "demo:total:valor"
    md = (pasta / "relatorio.md").read_text(encoding="utf-8")
    assert "# JFN — Painel de Certeza" in md and "`demo:total:valor`" in md and "INDISPONÍVEL ≠ 0" in md   # grafo sem despachante
    assert not list(pasta.glob("*.tmp"))


def test_sem_ciclo_o_estado_e_indisponivel_nunca_tudo_certo(pasta):
    assert orquestrador.ler_estado()["estado"] == "INDISPONIVEL"


def test_fato_que_a_fonte_deixou_de_produzir_fica_marcado(pasta, tmp_path):
    _ciclo(tmp_path)
    cfg = _mapa(tmp_path)
    cfg["derivados"]["demo"]["fatos"][0]["id"] = "demo:outro"
    est = _ciclo(tmp_path, cfg=cfg, agora=time.time() + 60)
    fr = {f["id"]: f["frescor"]["estado"] for f in est["fatos"]}
    assert fr["demo:total:valor"] == "a fonte não produz mais este fato"
    assert fr["demo:outro:valor"] == "INDISPONIVEL" and est["resumo"]["fatos_nao_frescos"] == 2   # sem despachante: frescor não medido ≠ fresco


def test_fila_de_reperica_que_nao_diminui_em_24h_e_acusada(pasta):
    cz = fatos.conectar()
    t = 1_800_000_000.0
    assert orquestrador._sem_drenar(cz, {"lex": 663}, t) == []                       # sem história: não acusa
    assert orquestrador._sem_drenar(cz, {"lex": 700}, t + 3600) == []                # menos de 24 h
    r = orquestrador._sem_drenar(cz, {"lex": 700}, t + 25 * 3600)
    assert r and r[0].startswith("lex: 700 item(ns)") and "eram 700" in r[0]         # compara com a medida de ≥ 24 h atrás
    assert orquestrador._sem_drenar(cz, {"lex": 100}, t + 50 * 3600) == []           # diminuiu
    assert orquestrador._sem_drenar(cz, {"lex": 0}, t + 80 * 3600) == []             # zerou
    cz.close()


def test_cerebro_so_recebe_fato_com_a_chave_ligada(pasta, tmp_path, monkeypatch):
    from compliance_agent import cerebro_compartilhado as cer
    enviados = []
    monkeypatch.setattr(cer, "registrar", lambda chave, txt, kind, assunto: enviados.append((chave, txt)) or "novo")
    assert _ciclo(tmp_path)["ciclo"]["cerebro"]["n"] == 0 and not enviados
    monkeypatch.setenv("JFN_CERTEZA_CEREBRO", "1")
    cfg = _mapa(tmp_path, 25.0)
    assert _ciclo(tmp_path, cfg=cfg)["ciclo"]["cerebro"]["n"] == 1
    assert enviados[0][0] == "fato:demo:total:valor" and "R$ 25,00" in enviados[0][1] and "VERIFICADO" in enviados[0][1]


def test_sensor_da_automelhoria(pasta, tmp_path, monkeypatch):
    from tools import automelhoria_geral as am
    assert am.sensor_certeza(tmp_path / "nao_existe") == []                          # o ciclo nunca rodou nesta máquina
    with pytest.raises(OSError):
        am.sensor_certeza(pasta)                                                     # pasta sem fotografia: sensor cego ≠ ok
    _ciclo(tmp_path)
    assert am.sensor_certeza(pasta) == []                                            # controle negativo: tudo certo, nenhum item
    (tmp_path / "notas" / "n.md").write_text("total R$ 99,00<!--fato:demo:total:valor-->\n", encoding="utf-8")
    _ciclo(tmp_path, compliance_db=_banco(tmp_path, (10.0, 1e12)), agora=time.time() + 5)
    itens = {i["assinatura"].split(":", 2)[1] + ":" + i["assinatura"].split(":", 2)[2].split(":")[0]: i for i in am.sensor_certeza(pasta)}
    assert set(itens) == {"divergencia:citacao_divergente", "contrato:fila"}
    assert "n.md:1 diz R$ 99,00, vigente R$ 10,00" in itens["divergencia:citacao_divergente"]["detalhe"]
    assert am.sensor_certeza(pasta, agora=time.time() + 30 * 3600)[0]["assinatura"] == "certeza:parada"
    assert "certeza" in am.SENSORES


def test_rota_filtra_por_fato_e_declara_indisponivel(pasta, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from rotas import propagacao as rota
    app = FastAPI()
    app.include_router(rota.router)
    cli = TestClient(app)
    assert cli.get("/api/sistema/certeza").json()["estado"] == "INDISPONIVEL"
    _ciclo(tmp_path)
    assert cli.get("/api/sistema/certeza").json()["resumo"]["fatos"] == 1
    assert cli.get("/api/sistema/certeza?fato=nao_existe").json()["fatos"] == []
