# -*- coding: utf-8 -*-
"""Task 4.5 — Índice de Direcionamento integrado a casos, endpoint e relatório.

Fixtures replicam as colunas reais do compliance.db (mesmo padrão de
test_indice_certame.py); a tabela `caso` espelha o PRAGMA verificado em 2026-07-19.
"""
import json
import sqlite3

import pytest

from compliance_agent.editais.db import init_schema
from compliance_agent.editais.indice_certame import (
    DDL_CASO,
    calcular_e_persistir,
    gravar_caso_se_alto,
)
from compliance_agent.reporting.relatorio_direcionamento import (
    _bloco_indice_certame,
    montar_ctx,
)
from rotas.produtos import _indice_certame_payload

VENC = "11111111000191"

PNCP_DDL = """CREATE TABLE pncp_resultado (
    certame TEXT, orgao_cnpj TEXT, orgao_nome TEXT, uf TEXT, municipio TEXT,
    modalidade INTEGER, objeto TEXT, data_pub TEXT, item INTEGER,
    fornecedor_cnpj TEXT, fornecedor_nome TEXT, valor_homologado REAL,
    ordem_classificacao INTEGER, porte_fornecedor TEXT, coletado_em TEXT,
    unidade_codigo TEXT, unidade_nome TEXT, item_descricao TEXT,
    unidade_medida TEXT, valor_unitario REAL, quantidade REAL)"""
FANTASMA_DDL = """CREATE TABLE fantasma_score (
    cnpj TEXT PRIMARY KEY, razao_social TEXT, score INTEGER, classificacao TEXT,
    sinais_json TEXT, origem TEXT, avaliado_em TEXT)"""


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    init_schema(con)
    for ddl in (PNCP_DDL, FANTASMA_DDL, DDL_CASO):  # caso já existe no compliance.db real
        con.execute(ddl)
    con.commit()
    yield p, con
    con.close()


def _pncp(con, certame, *, modalidade=6, fantasma=None):
    con.execute("INSERT INTO pncp_resultado (certame, modalidade, data_pub, item, "
                "fornecedor_cnpj, valor_homologado, ordem_classificacao, item_descricao, "
                "valor_unitario, quantidade) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (certame, modalidade, "2026-01-10", 1, VENC, 500_000.0, 1,
                 "servico exotico xpto", 100.0, 1))
    if fantasma is not None:
        con.execute("INSERT OR REPLACE INTO fantasma_score (cnpj, score, classificacao) "
                    "VALUES (?,?,?)", (VENC, fantasma, "alto" if fantasma >= 70 else "baixo"))


# ──────────────── (a) faixa EXTREMO grava caso 1x (idempotente) ────────────────
def test_extremo_grava_caso_idempotente(db):
    p, con = db
    # inexigibilidade (transparencia=1.0) + fantasma 100 (fraude=1.0) → score 100 = EXTREMO
    _pncp(con, "EXT-1-000001/2026", modalidade=9, fantasma=100)
    con.commit()

    r = calcular_e_persistir("EXT-1-000001/2026", p)
    assert r["faixa"] == "EXTREMO"
    row = con.execute("SELECT * FROM caso WHERE alvo=? AND tipo_achado='direcionamento'",
                      ("EXT-1-000001/2026",)).fetchone()
    assert row is not None
    assert row["status"] == "novo"
    assert row["risco_achado"] == r["score"]
    assert row["risco_punicao"] is None and row["economia_potencial"] is None  # INDISPONÍVEL ≠ 0
    evid = json.loads(row["evidencia_ids"])
    assert {d["familia"] for d in evid} == {d["familia"] for d in r["drivers"]}
    assert all(d["evidencia"] for d in evid)

    # 2ª chamada: recomputar não duplica nem sobrescreve o caso
    con.execute("UPDATE caso SET status='apurando' WHERE alvo=?", ("EXT-1-000001/2026",))
    con.commit()
    r2 = calcular_e_persistir("EXT-1-000001/2026", p)
    assert gravar_caso_se_alto(r2, p) is False
    rows = con.execute("SELECT status FROM caso WHERE alvo=?", ("EXT-1-000001/2026",)).fetchall()
    assert len(rows) == 1 and rows[0]["status"] == "apurando"  # status do fluxo preservado


def test_flag_gravar_caso_desligada(db):
    p, con = db
    _pncp(con, "EXT-1-000002/2026", modalidade=9, fantasma=100)
    con.commit()
    r = calcular_e_persistir("EXT-1-000002/2026", p, gravar_caso=False)
    assert r["faixa"] == "EXTREMO"
    n = con.execute("SELECT COUNT(*) FROM caso").fetchone()[0]
    assert n == 0


# ──────────────────────── (b) faixa BAIXO não grava caso ────────────────────────
def test_baixo_nao_grava_caso(db):
    p, con = db
    _pncp(con, "BAIXO-1-000001/2026", modalidade=6, fantasma=5)  # disputa + fantasma baixo
    con.commit()
    r = calcular_e_persistir("BAIXO-1-000001/2026", p)
    assert r["faixa"] == "BAIXO"
    assert gravar_caso_se_alto(r, p) is False
    n = con.execute("SELECT COUNT(*) FROM caso").fetchone()[0]
    assert n == 0


# ──────────────── (c) endpoint /api/certame/indice (lógica testável) ────────────────
def test_endpoint_sem_certame():
    assert _indice_certame_payload("") == {
        "ok": False, "erro": "informe ?certame=<numero de controle PNCP>"}


def test_endpoint_le_persistido_recente(db):
    p, con = db
    _pncp(con, "EXT-1-000001/2026", modalidade=9, fantasma=100)
    con.commit()
    r = calcular_e_persistir("EXT-1-000001/2026", p)

    out = _indice_certame_payload("EXT-1-000001/2026", db_path=p)
    assert out["ok"] is True and out["fonte"] == "certame_indice"
    ind = out["indice"]
    assert ind["score"] == r["score"] and ind["faixa"] == "EXTREMO"
    assert set(ind) == {"score", "prioridade", "faixa", "confianca",
                        "familias", "drivers", "matriz_sv"}
    assert ind["matriz_sv"]["severidade"] == 5
    assert out["narrativa"] is None  # sem narrativa_json persistida

    # narrativa persistida acompanha a resposta
    con.execute("ALTER TABLE certame_indice ADD COLUMN narrativa_json TEXT")
    con.execute("UPDATE certame_indice SET narrativa_json=? WHERE certame=?",
                (json.dumps({"tese": "direcionamento", "paragrafo": "certame sem disputa"}),
                 "EXT-1-000001/2026"))
    con.commit()
    out2 = _indice_certame_payload("EXT-1-000001/2026", db_path=p)
    assert out2["narrativa"]["tese"] == "direcionamento"


def test_endpoint_calcula_quando_stale_ou_ausente(db):
    p, con = db
    _pncp(con, "EXT-1-000001/2026", modalidade=9, fantasma=100)
    # linha persistida VELHA (score divergente de propósito) → recalcula na hora
    con.execute("INSERT INTO certame_indice (certame, score, prioridade, faixa, confianca, "
                "gerado_em) VALUES (?, 1.0, 1.0, 'BAIXO', 0.1, '2020-01-01 00:00:00')",
                ("EXT-1-000001/2026",))
    con.commit()
    out = _indice_certame_payload("EXT-1-000001/2026", db_path=p)
    assert out["fonte"] == "calculado" and out["indice"]["faixa"] == "EXTREMO"
    # certame sem NENHUM registro → calcula honesto (tudo INDISPONÍVEL, BAIXO)
    out2 = _indice_certame_payload("NADA-1-000001/2026", db_path=p)
    assert out2["ok"] is True and out2["fonte"] == "calculado"
    assert out2["indice"]["confianca"] == 0.0


# ──────────────── (d) _bloco_indice_certame + relatório aditivo ────────────────
def test_bloco_indice_certame_renderiza(db):
    p, con = db
    _pncp(con, "EXT-1-000001/2026", modalidade=9, fantasma=100)
    con.commit()
    calcular_e_persistir("EXT-1-000001/2026", p)
    row = con.execute("SELECT * FROM certame_indice WHERE certame=?",
                      ("EXT-1-000001/2026",)).fetchone()

    html = _bloco_indice_certame(row)
    assert "Contexto do certame" in html
    assert "100.0/100" in html and "EXTREMO" in html
    assert "contratacao_direta" in html and "inexigibilidade" in html  # driver + evidência
    assert "vencedor_fantasma" in html
    assert "INDISPONÍVEL" in html                       # famílias sem fonte, honestas
    assert "Matriz de risco do certame" in html
    assert "indício ≠ acusação" in html


def test_bloco_indice_certame_narrativa():
    row = {"score": 88.0, "prioridade": 900.0, "faixa": "EXTREMO", "confianca": 0.5,
           "familias_json": json.dumps({"transparencia": {
               "apuravel": True, "valor": 1.0, "fonte": "pncp_resultado",
               "flags": [{"flag": "contratacao_direta", "valor": 1.0, "evidencia": "modalidade 9"}]}}),
           "drivers_json": json.dumps([{"familia": "transparencia", "flag": "contratacao_direta",
                                        "valor": 1.0, "evidencia": "modalidade 9"}]),
           "narrativa_json": json.dumps({"tese": "indício de direcionamento",
                                         "paragrafo": "o certame correu sem disputa"})}
    html = _bloco_indice_certame(row)
    assert "indício de direcionamento" in html and "o certame correu sem disputa" in html


def _db_relatorio(tmp_path):
    """DB mínimo p/ montar_ctx: 1 veredito quente (score 9) com todas as tabelas da ficha."""
    p = tmp_path / "rel.db"
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    init_schema(con)
    con.execute("CREATE TABLE pcrj_licitacoes (numero_controle_pncp TEXT, orgao_nome TEXT, "
                "modalidade TEXT, valor_estimado REAL, data_abertura TEXT, situacao TEXT, "
                "orgao_cnpj TEXT)")
    nc = "REL-1-000001/2026"
    con.execute("INSERT INTO edital_documento (numero_controle_pncp, objeto, valor_estimado, "
                "texto) VALUES (?,?,?,?)",
                (nc, "aquisicao de canetas", 100_000.0,
                 "EDITAL. A visita tecnica e obrigatoria para todos os licitantes."))
    con.execute("INSERT INTO pcrj_licitacoes VALUES (?,?,?,?,?,?,?)",
                (nc, "SECRETARIA X", "Pregão Eletrônico", 100_000.0, "2026-01-10",
                 "aberta", "99999999000191"))
    cid = con.execute("INSERT INTO edital_clausula (numero_controle_pncp, eixo, subtipo, texto, "
                      "trecho_fonte) VALUES (?,?,?,?,?)",
                      (nc, "condicao_participacao", "visita_tecnica",
                       "A visita tecnica e obrigatoria", "A visita tecnica e obrigatoria")).lastrowid
    kid = con.execute("INSERT INTO edital_cluster (assinatura_objeto, membros_json, tamanho) "
                      "VALUES (?,?,?)", ("canetas", json.dumps([nc]), 1)).lastrowid
    con.execute("INSERT INTO clausula_veredito (clausula_id, cluster_id, numero_controle_pncp, "
                "raridade, forca_e7, sumula, votos_json, score_final, veredito) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (cid, kid, nc, None, "forte", "Súmula TCE-RJ 01", "{}", 9, "direcionamento"))
    con.commit()
    return con, nc


def test_relatorio_aditivo_com_e_sem_indice(tmp_path):
    """Sem linha em certame_indice o relatório sai idêntico ao de antes; com a linha,
    a ficha ganha a seção VIII — mudança estritamente aditiva."""
    con, nc = _db_relatorio(tmp_path)
    base = [s["html"] for s in montar_ctx(con)["secoes"]]
    assert not any("Contexto do certame" in h for h in base)

    familias = {"transparencia": {"apuravel": True, "valor": 1.0, "fonte": "pncp_resultado",
                                  "flags": [{"flag": "contratacao_direta", "valor": 1.0,
                                             "evidencia": "modalidade 9"}]},
                "execucao": {"apuravel": False, "valor": None, "flags": [],
                             "fonte": "contrato_aditivo", "nota": "sem vínculo compra→contrato"}}
    con.execute("INSERT INTO certame_indice (certame, score, prioridade, faixa, confianca, "
                "familias_json, drivers_json) VALUES (?,?,?,?,?,?,?)",
                (nc, 88.0, 900.0, "EXTREMO", 0.33, json.dumps(familias),
                 json.dumps([{"familia": "transparencia", "flag": "contratacao_direta",
                              "valor": 1.0, "evidencia": "modalidade 9"}])))
    con.commit()
    com = [s["html"] for s in montar_ctx(con)["secoes"]]
    ficha = next(h for h in com if "Achado nº 1" in h)
    assert "Contexto do certame" in ficha and "88.0/100" in ficha and "EXTREMO" in ficha
    assert ficha.rstrip().endswith("</div>")  # seção VIII entra DENTRO da ficha

    con.execute("DELETE FROM certame_indice WHERE certame=?", (nc,))
    con.commit()
    assert [s["html"] for s in montar_ctx(con)["secoes"]] == base  # regressão byte-idêntica
    con.close()
