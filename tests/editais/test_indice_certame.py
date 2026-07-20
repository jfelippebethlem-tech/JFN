# -*- coding: utf-8 -*-
"""Task 4.3 — Índice de Direcionamento de Certame (máximo por família, pesos, honestidade).

Fixtures replicam as COLUNAS reais do compliance.db (PRAGMA table_info verificado em
2026-07-19): pncp_resultado, fantasma_score, sancoes_federais; proposta_item via
`coletor_propostas.garantir_tabela`; clausula_veredito/certame_indice via `db.init_schema`.
"""
import math
import sqlite3

import pytest

from compliance_agent.editais.coletor_propostas import garantir_tabela, persistir_propostas
from compliance_agent.editais.db import init_schema
from compliance_agent.editais.indice_certame import (
    _PESOS_FAMILIA,
    calcular,
    calcular_e_persistir,
)

VENC_A = "11111111000191"   # vencedor podre (fantasma alto + sanção vigente)
VENC_B = "22222222000272"   # vencedor podre-2 (só sanção — prova do máximo por família)
VENC_L = "33333333000353"   # vencedor limpo
COBER_1 = "44444444000144"  # proponentes de cobertura
COBER_2 = "55555555000135"

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
SANCOES_DDL = """CREATE TABLE sancoes_federais (
    cadastro TEXT, cpf_cnpj TEXT, nome TEXT, categoria TEXT, data_inicio TEXT,
    data_fim TEXT, orgao TEXT, uf TEXT, processo TEXT, fundamentacao TEXT)"""


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    init_schema(con)          # edital_documento, clausula_veredito, certame_indice...
    for ddl in (PNCP_DDL, FANTASMA_DDL, SANCOES_DDL):
        con.execute(ddl)
    con.commit()
    yield p, con
    con.close()


def _pncp(con, certame, fornecedor, *, vu=100.0, valor=500_000.0, modalidade=6,
          data_pub="2026-01-10", ordem=1, descricao="caneta esferografica azul"):
    con.execute("INSERT INTO pncp_resultado (certame, modalidade, data_pub, item, "
                "fornecedor_cnpj, valor_homologado, ordem_classificacao, item_descricao, "
                "valor_unitario, quantidade) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (certame, modalidade, data_pub, 1, fornecedor, valor, ordem, descricao, vu, 1))


def _referencias_preco(con, n=6, vu=50.0):
    """n compras do MESMO item em OUTROS certames a vu → mediana 50 (sobrepreço vs 100 = 2x)."""
    for i in range(n):
        _pncp(con, f"REF-1-{i:06d}/2025", f"9999999900{i:04d}", vu=vu, valor=vu)


def _lances(con, certame, lances: dict[str, float]):
    """Lances TOTAIS (item=0, convenção da ata) em proposta_item."""
    garantir_tabela(con)
    persistir_propostas(con, certame, [
        {"item": 0, "fornecedor_cnpj": c, "valor_total": v, "fonte": "ata"}
        for c, v in lances.items()])


def _clausula(con, certame, score=9):
    con.execute("INSERT INTO clausula_veredito (numero_controle_pncp, score_final, veredito, "
                "forca_e7) VALUES (?,?,?,?)", (certame, score, "direcionamento", "forte"))


def _montar_podre(con, certame, vencedor, *, com_fantasma):
    """1 vencedor no PNCP + 3 lances de cobertura + cláusula 9/10 + sobrepreço 2x + sanção."""
    _pncp(con, certame, vencedor, vu=100.0)
    # lances: vencedor descolado, perdedores aglomerados e altos -> rd_alto+cobertura+skew_negativa
    _lances(con, certame, {vencedor: 100_000.0, COBER_1: 150_000.0, COBER_2: 152_000.0})
    _clausula(con, certame, score=9)
    if com_fantasma:
        con.execute("INSERT INTO fantasma_score (cnpj, score, classificacao) VALUES (?,?,?)",
                    (vencedor, 95, "alto"))
    # sanção VIGENTE à época (2026-01-10), cpf_cnpj formatado prova o join por dígitos
    doc = f"{vencedor[:2]}.{vencedor[2:5]}.{vencedor[5:8]}/{vencedor[8:12]}-{vencedor[12:]}"
    con.execute("INSERT INTO sancoes_federais (cadastro, cpf_cnpj, data_inicio, data_fim) "
                "VALUES ('CEIS', ?, '2025-01-01', NULL)", (doc,))


# ─────────────────── 1. certame podre → EXTREMO + máximo por família ───────────────────
def test_certame_podre_extremo_com_drivers(db):
    p, con = db
    _referencias_preco(con)
    _montar_podre(con, "PODRE-1-000001/2026", VENC_A, com_fantasma=True)
    con.commit()

    r = calcular("PODRE-1-000001/2026", p)
    assert r["faixa"] == "EXTREMO" and r["score"] >= 75
    # drivers de >=3 famílias distintas, cada um com evidência textual
    fams = {d["familia"] for d in r["drivers"]}
    assert len(fams) >= 3
    assert fams >= {"competicao", "conluio", "fraude_cadastral", "preco"}
    assert all(d["evidencia"] for d in r["drivers"])
    # execucao INDISPONÍVEL honesta (sem ponte compra->contrato) não zera o certame
    assert r["familias"]["execucao"]["apuravel"] is False
    # 7 famílias desde 2026-07-20 (certame_ata): sem ata persistida, confiança = 5/7
    assert r["confianca"] == pytest.approx(5 / 7, abs=0.01)
    # matriz S x V no contrato do _matriz_risco (1-5 cada, produto 1-25)
    m = r["matriz_sv"]
    assert m["severidade"] == 5 and m["verossimilhanca"] == 5 and m["produto"] == 25
    assert m["nivel"] == "CRÍTICO"


def test_maximo_por_familia_nao_soma(db):
    """2 flags ALTOS da mesma família (fantasma 0.95 + sanção 1.0) não elevam além do máximo:
    o certame com os dois flags pontua IGUAL ao certame com só o flag máximo (sanção=1.0)."""
    p, con = db
    _referencias_preco(con)
    _montar_podre(con, "PODRE-1-000001/2026", VENC_A, com_fantasma=True)   # 2 flags na família
    _montar_podre(con, "PODRE-1-000002/2026", VENC_B, com_fantasma=False)  # 1 flag (o máximo)
    con.commit()

    r2flags = calcular("PODRE-1-000001/2026", p)
    r1flag = calcular("PODRE-1-000002/2026", p)
    f2 = r2flags["familias"]["fraude_cadastral"]
    assert len(f2["flags"]) == 2 and f2["valor"] == 1.0          # máximo, nunca 1.95
    assert r1flag["familias"]["fraude_cadastral"]["valor"] == 1.0
    assert r2flags["score"] == r1flag["score"]                   # somar inflaria o primeiro


# ──────────────────────────── 2. certame limpo → BAIXO ────────────────────────────
def test_certame_limpo_baixo(db):
    p, con = db
    _referencias_preco(con)
    _pncp(con, "LIMPO-1-000001/2026", VENC_L, vu=50.0, valor=100_000.0)  # preço = mediana
    _lances(con, "LIMPO-1-000001/2026", {                                # 5 lances dispersos
        VENC_L: 100_000.0, COBER_1: 110_000.0, COBER_2: 125_000.0,
        "66666666000116": 145_000.0, "77777777000107": 170_000.0})
    con.execute("INSERT INTO fantasma_score (cnpj, score, classificacao) VALUES (?, 5, 'baixo')",
                (VENC_L,))
    con.commit()

    r = calcular("LIMPO-1-000001/2026", p)
    assert r["faixa"] == "BAIXO" and r["score"] < 25
    assert r["drivers"] == []
    assert r["familias"]["competicao"]["valor"] == 0.0  # 5 proponentes = competição saudável


def test_licitante_unico_flag(db):
    """1 proposta na ata = licitante único genuíno (a ata lista TODOS os proponentes)."""
    p, con = db
    _pncp(con, "UNICO-1-000001/2026", VENC_L)
    _lances(con, "UNICO-1-000001/2026", {VENC_L: 100_000.0})
    con.commit()
    r = calcular("UNICO-1-000001/2026", p)
    comp = r["familias"]["competicao"]
    assert any(f["flag"] == "licitante_unico" and f["valor"] == 1.0 for f in comp["flags"])
    assert comp["valor"] == 1.0


# ─────────────── 3. só 2 famílias apuráveis → confiança 0.33, score só sobre elas ───────────────
def test_confianca_duas_familias(db):
    """Inexigibilidade (transparencia=1.0) + fantasma 50/100 (fraude=0.5); sem propostas, sem
    cláusulas, sem referência de preço, sem aditivo → 4 famílias INDISPONÍVEIS. Score é a média
    ponderada SÓ das apuráveis: 100*(0.10*1.0 + 0.15*0.5)/(0.10+0.15) = 70."""
    p, con = db
    _pncp(con, "DUAS-1-000001/2026", VENC_A, modalidade=9, descricao="servico exotico xpto")
    con.execute("INSERT INTO fantasma_score (cnpj, score, classificacao) VALUES (?, 50, 'medio')",
                (VENC_A,))
    con.commit()

    r = calcular("DUAS-1-000001/2026", p)
    apuraveis = [f for f, d in r["familias"].items() if d["apuravel"]]
    assert sorted(apuraveis) == ["fraude_cadastral", "transparencia"]
    assert r["confianca"] == pytest.approx(2 / 7, abs=0.01)  # 7 famílias desde certame_ata
    pt, pf = _PESOS_FAMILIA["transparencia"], _PESOS_FAMILIA["fraude_cadastral"]
    assert r["score"] == pytest.approx(100 * (pt * 1.0 + pf * 0.5) / (pt + pf), abs=0.01)
    # INDISPONÍVEL não zera: com 4 famílias sem dado o score NÃO é diluído para ~17
    assert r["score"] == pytest.approx(70.0, abs=0.01)


# ──────────────── 4. materialidade só na prioridade (score idêntico) ────────────────
def test_prioridade_cresce_com_valor_score_identico(db):
    p, con = db
    _pncp(con, "VAL-1-000001/2026", VENC_A, modalidade=9, valor=10_000.0,
          descricao="servico exotico abc")
    _pncp(con, "VAL-1-000002/2026", VENC_A, modalidade=9, valor=10_000_000.0,
          descricao="servico exotico def")
    con.execute("INSERT INTO fantasma_score (cnpj, score, classificacao) VALUES (?, 50, 'medio')",
                (VENC_A,))
    con.commit()

    barato = calcular("VAL-1-000001/2026", p)
    caro = calcular("VAL-1-000002/2026", p)
    assert barato["score"] == caro["score"]                  # materialidade NUNCA entra no risco
    assert caro["prioridade"] > barato["prioridade"]
    assert barato["prioridade"] == pytest.approx(barato["score"] * math.log1p(10_000.0), abs=0.1)


# ───────────────────────────── persistência em certame_indice ─────────────────────────────
def test_calcular_e_persistir(db):
    p, con = db
    _pncp(con, "DUAS-1-000001/2026", VENC_A, modalidade=9, descricao="servico exotico xpto")
    con.commit()

    r = calcular_e_persistir("DUAS-1-000001/2026", p)
    row = con.execute("SELECT score, prioridade, faixa, confianca, familias_json, drivers_json "
                      "FROM certame_indice WHERE certame=?", ("DUAS-1-000001/2026",)).fetchone()
    assert row is not None
    assert row[0] == r["score"] and row[2] == r["faixa"]
    assert "transparencia" in row[4] and row[5] is not None
    # UPSERT idempotente
    calcular_e_persistir("DUAS-1-000001/2026", p)
    n = con.execute("SELECT COUNT(*) FROM certame_indice").fetchone()[0]
    assert n == 1
