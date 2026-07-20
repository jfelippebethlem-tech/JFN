# -*- coding: utf-8 -*-
"""Dossiê Mestre F1 — ata persistida (certame_julgamento), família certame_ata do índice,
efeito combinado de cláusulas, acatamento de pareceres e avaliação de conjunto.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/editais/test_dossie_mestre_fase1.py -q
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.editais.avaliacao_conjunto import avaliar_orgao, avaliar_portfolio, ctx_secao
from compliance_agent.editais.db import init_schema, salvar_julgamento
from compliance_agent.editais.indice_certame import calcular
from compliance_agent.sei_recomendacoes import auditar_acatamento

CERT = "99999999000199-1-000001/2026"
ORGAO = "12345678000195"

# mesmas colunas reais do compliance.db (padrão de tests/editais/test_indice_certame.py)
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
    init_schema(con)
    for ddl in (PNCP_DDL, FANTASMA_DDL, SANCOES_DDL):
        con.execute(ddl)
    con.execute("INSERT INTO edital_documento (numero_controle_pncp, ano, orgao_cnpj, objeto) "
                "VALUES (?, 2026, ?, 'serviço de limpeza')", (CERT, ORGAO))
    con.execute("INSERT INTO pncp_resultado (certame, modalidade, data_pub, item, fornecedor_cnpj, "
                "valor_homologado, ordem_classificacao, item_descricao, valor_unitario, quantidade) "
                "VALUES (?, 6, '2026-01-10', 1, '11111111000191', 500000, 1, 'limpeza', 100, 1)", (CERT,))
    con.commit()
    yield p, con
    con.close()


RESULTADO = {"licitantes": 4, "inabilitados": 3, "vencedor_cnpj": "11111111000191",
             "motivos": ["ausência de assinatura na proposta",
                         "certidão de regularidade fiscal vencida",
                         "atestado não atende o quantitativo mínimo"]}


def test_salvar_julgamento_persiste_e_classifica(db):
    p, con = db
    agg = salvar_julgamento(con, CERT, RESULTADO)
    assert agg["triviais"] == 2 and agg["violacoes_saneamento"] == 2 and agg["substanciais"] == 1
    row = con.execute("SELECT licitantes, inabilitados FROM certame_julgamento WHERE certame=?",
                      (CERT,)).fetchone()
    assert tuple(row) == (4, 3)


def test_familia_certame_ata_entra_no_indice(db):
    p, con = db
    salvar_julgamento(con, CERT, RESULTADO)
    r = calcular(CERT, db_path=p)
    fam = r["familias"]["certame_ata"]
    assert fam["apuravel"] is True
    nomes = {f["flag"] for f in fam["flags"]}
    assert {"inabilitacao_em_massa", "licitante_unico_efetivo",
            "inabilitacao_trivial_sem_saneamento"} <= nomes
    assert fam["valor"] == 0.85  # máximo por família, nunca soma


def test_sem_ata_familia_indisponivel_nao_zera(db):
    p, con = db
    r = calcular(CERT, db_path=p)
    fam = r["familias"]["certame_ata"]
    assert fam["apuravel"] is False and fam["valor"] is None


def test_diligencia_na_sessao_exculpa_saneamento(db):
    p, con = db
    agg = salvar_julgamento(con, CERT, RESULTADO, houve_diligencia=True)
    assert agg["triviais"] == 2 and agg["violacoes_saneamento"] == 0
    r = calcular(CERT, db_path=p)
    nomes = {f["flag"] for f in r["familias"]["certame_ata"]["flags"]}
    assert "inabilitacao_trivial_sem_saneamento" not in nomes


def test_efeito_combinado_de_clausulas(db):
    p, con = db
    for i, sub in enumerate(("capital_patrimonio", "atestado_quantitativo", "visita_tecnica")):
        con.execute("INSERT INTO edital_clausula (numero_controle_pncp, eixo, subtipo, texto) "
                    "VALUES (?, 'habilitacao', ?, 'clausula')", (CERT, sub))
        cid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.execute("INSERT INTO clausula_veredito (clausula_id, numero_controle_pncp, score_final, "
                    "veredito, forca_e7) VALUES (?, ?, ?, 'restritiva', 'forte')", (cid, CERT, 8 + (i % 2)))
    con.commit()
    r = calcular(CERT, db_path=p)
    flags = {f["flag"]: f for f in r["familias"]["competicao"]["flags"]}
    assert "efeito_combinado" in flags and flags["efeito_combinado"]["valor"] == 0.85
    assert "272" in flags["efeito_combinado"]["evidencia"]


# ───────────────────────── acatamento de pareceres ─────────────────────────

def _doc(ref, tipo, texto):
    return {"ref": ref, "tipo": tipo, "texto": texto}


PARECER_RESSALVA = _doc("doc-2", "parecer", "Parecer da Assessoria Jurídica: aprovação com ressalvas — "
                        "recomenda-se a exclusão da exigência de capital social de 30%.")


def test_acatamento_acolhido():
    docs = [PARECER_RESSALVA,
            _doc("doc-3", "despacho", "Despacho: acolho o parecer jurídico e determino o ajuste do edital.")]
    assert auditar_acatamento(docs)["veredito"] == "ACOLHIDO"


def test_acatamento_contrariado_com_motivacao():
    docs = [PARECER_RESSALVA,
            _doc("doc-3", "despacho", "Despacho decisório: em que pese o parecer, deixo de acolher a "
                 "recomendação pelas razões de urgência expostas.")]
    assert auditar_acatamento(docs)["veredito"] == "CONTRARIADO_COM_MOTIVACAO"


def test_acatamento_ignorado_indicio():
    docs = [_doc("doc-2", "parecer", "Parecer PGE: recomendação de ajuste. Em nova análise, a ressalva "
                 "não foi atendida e permanece a pendência apontada."),
            _doc("doc-3", "despacho", "Despacho: homologo o certame e adjudico o objeto.")]
    assert auditar_acatamento(docs)["veredito"] == "IGNORADO_INDICIO"


def test_acatamento_silente():
    assert auditar_acatamento([PARECER_RESSALVA])["veredito"] == "SILENTE"


def test_sem_parecer_localizado_e_honesto():
    r = auditar_acatamento([_doc("doc-1", "edital", "Edital de pregão eletrônico nº 1/2026")])
    assert r["veredito"] == "SEM_PARECER_LOCALIZADO"
    assert "INDISPONÍVEL" in r["leitura"]


# ───────────────────────── avaliação de conjunto ─────────────────────────

def test_avaliar_orgao_agrega_e_gatilha_auditoria(db):
    p, con = db
    salvar_julgamento(con, CERT, RESULTADO)
    # 3 certames do órgão com o MESMO subtipo restritivo → gatilho de auditoria temática
    for i in range(3):
        c = f"{CERT}-{i}"
        con.execute("INSERT INTO edital_documento (numero_controle_pncp, ano, orgao_cnpj) "
                    "VALUES (?, 2026, ?)", (c, ORGAO))
        con.execute("INSERT INTO certame_indice (certame, score, prioridade, faixa, confianca) "
                    "VALUES (?, ?, ?, ?, 0.5)", (c, 30.0 + 20 * i, 100 + i, "MEDIO" if i < 2 else "ALTO"))
        con.execute("INSERT INTO edital_clausula (numero_controle_pncp, eixo, subtipo, texto) "
                    "VALUES (?, 'habilitacao', 'capital_patrimonio', 'x')", (c,))
        cid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.execute("INSERT INTO clausula_veredito (clausula_id, numero_controle_pncp, score_final, "
                    "veredito) VALUES (?, ?, 9, 'restritiva')", (cid, c))
    con.commit()
    av = avaliar_orgao(ORGAO, db_path=p)
    assert av["n_certames_indexados"] == 3
    assert av["score_mediana"] == 50.0
    assert av["auditoria_tematica"] and av["auditoria_tematica"][0]["subtipo"] == "capital_patrimonio"
    assert av["violacoes_saneamento"] == 2
    sec = ctx_secao(av)
    assert sec["titulo"].startswith("Avaliação de conjunto") and "auditoria temática" in sec["html"]


def test_avaliar_orgao_vazio_honesto(db):
    p, _con = db
    av = avaliar_orgao("00000000000000", db_path=p)
    assert av["n_certames_indexados"] == 0 and av["score_mediana"] is None
    assert "INDISPONÍVEL" in ctx_secao(av)["html"]


def test_portfolio_ranqueia_e_beira_pares(db):
    p, con = db
    for j, org in enumerate(("11111111000191", "22222222000272")):
        for i in range(3):
            c = f"C-{org}-{i}"
            con.execute("INSERT INTO edital_documento (numero_controle_pncp, ano, orgao_cnpj) "
                        "VALUES (?, 2026, ?)", (c, org))
            con.execute("INSERT INTO certame_indice (certame, score, prioridade, faixa, confianca) "
                        "VALUES (?, ?, 1, 'MEDIO', 0.5)", (c, 20.0 + 40 * j))
    con.commit()
    pf = avaliar_portfolio(db_path=p, min_certames=3)
    assert pf["n_orgaos"] == 2
    assert pf["orgaos"][0]["score_mediana"] == 60.0  # pior primeiro
    assert pf["orgaos"][0]["desvio_vs_pares"] == 20.0
