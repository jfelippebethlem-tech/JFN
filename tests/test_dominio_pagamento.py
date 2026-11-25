# -*- coding: utf-8 -*-
"""O4.1 — `dominio.pagamento.ob_paga_sql` É o predicado canônico `cruzamentos_intel._ob_paga` (invariante 1:
pago = OB paga do SIAFE). Paridade nos três schemas que o predicado distingue."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.cruzamentos_intel import _ob_paga
from compliance_agent.dominio.pagamento import ob_paga_sql

SCHEMAS = {
    "antigo": "CREATE TABLE ob_orcamentaria_siafe(numero_ob TEXT, ug_emitente TEXT, status TEXT, valor REAL)",
    "envio": "CREATE TABLE ob_orcamentaria_siafe(numero_ob TEXT, ug_emitente TEXT, status TEXT, status_envio TEXT, valor REAL)",
    "completo": ("CREATE TABLE ob_orcamentaria_siafe(numero_ob TEXT, ug_emitente TEXT, status TEXT, status_envio TEXT,"
                 " tipo_regularizacao TEXT, valor REAL); CREATE TABLE ob_reemitida(ob TEXT, ug TEXT)"),
}


@pytest.mark.parametrize("schema", sorted(SCHEMAS))
@pytest.mark.parametrize("alias", ["", "o"])
def test_ob_paga_sql_identico_ao_canonico(schema, alias):
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMAS[schema])
    assert ob_paga_sql(con, alias) == _ob_paga(con, alias)
    assert ob_paga_sql(con) == _ob_paga(con)


def test_ob_paga_sql_filtra_de_verdade():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMAS["completo"])
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES(?,?,?,?,?,?)", [
        ("2026OB00001", "080001", "Contabilizado", "Enviado ao Banco", "", 10.0),
        ("2026OB00002", "080001", "Anulado", "", "", 20.0),
        ("2026OB00003", "080001", "Contabilizado", "Erro no Pagamento", "", 40.0),
        ("2026OB00004", "080001", "Contabilizado", "Enviado Manualmente", "Pagamento Complementar", 80.0),
        ("", "080001", "Contabilizado", "", "", 160.0),
    ])
    assert con.execute(f"SELECT SUM(valor) FROM ob_orcamentaria_siafe WHERE {ob_paga_sql(con)}").fetchone()[0] == 10.0


# ══ O4.6 — natureza_pagamento × origem_exercicio (dois eixos) — tabela-ouro com a fonte de cada caso ═════════════
# Fontes verbatim: MCASP 11ª ed. (manuais/STN-MCASP-11a-ed.pdf, md5 16e7f095b37baa97ffd3bdd10cb6f6fb), Parte I —
# listas de modalidades e elementos; Lei 4.320 (L4320.htm) arts. 36 e 37; doutrina MAPA-DE-REGIMES §1 e §3.
from compliance_agent.dominio.pagamento import (NaturezaPagamento as NP, OrigemExercicio as OE,  # noqa: E402
                                                decompor_natureza, natureza_pagamento, origem_exercicio)

OURO_NATUREZA = [
    # (natureza_despesa, vinculo, nat. jurídica credor, esperado, nao_e_contratacao_nova, credor_e_fornecedor, fonte)
    ("334041", None, None, NP.TRANSFERENCIA, True, False, "MCASP: '41 Transferências a Municípios - Fundo a Fundo'"),
    ("335043", None, "3999", NP.TRANSFERENCIA, True, None, "MCASP: '50 [...] sem Fins Lucrativos' + '43 Subvenções "
                                                           "Sociais': parceria MROSC ou AAE — instrumento a confirmar (D5)"),
    ("335039", None, "3999", NP.TRANSFERENCIA, True, True, "mod. 50 com elemento de serviço: OSC fornecedor (dono)"),
    ("339085", None, "3999", NP.TRANSFERENCIA, True, True, "MCASP: '85 - Contrato de Gestão [...] organizações sociais'"),
    ("447142", None, None, NP.TRANSFERENCIA, True, False, "MCASP: '71 Transferências a Consórcios Públicos [...] rateio'"),
    ("333081", None, None, NP.TRANSFERENCIA, True, False, "MCASP: '81 - Distribuição Constitucional ou Legal'"),
    ("336739", None, None, NP.PARCELA_CONTRATO, True, True, "MCASP: '67 Execução de Contrato de PPP'"),
    ("339039", True, None, NP.PARCELA_CONTRATO, True, True, "aplicação direta + vínculo (4.320 arts. 62–63)"),
    ("339039", False, None, NP.CONTRATACAO_NOVA, False, True, "aplicação direta sem contrato (MAPA §1 passo 6)"),
    ("339039", None, None, NP.INDETERMINADO, False, True, "vínculo desconhecido não vira contratação nova"),
    ("339037", None, None, NP.INDETERMINADO, True, True, "MCASP: '37 – Locação de Mão-de-Obra [...] contrato' — o "
                                                         "elemento não prova o contrato (D7, TCU 1181/2012-P)"),
    ("339037", True, None, NP.PARCELA_CONTRATO, True, True, "el. 37 com vínculo conferido: parcela de contrato"),
    ("339093", None, None, NP.INDENIZACAO, True, False, "MCASP: '93 – Indenizações e Restituições'"),
    ("339091", None, None, NP.INDENIZACAO, True, False, "MCASP: '91 – Sentenças Judiciais'"),
    ("339092", None, None, NP.INDETERMINADO, True, None, "MCASP: '92 – DEA' (4.320 art. 37): nunca contratação nova"),
    ("339047", None, None, NP.INDETERMINADO, True, False, "MCASP: '47 – Obrigações Tributárias e Contributivas'"),
    ("319011", None, None, NP.FOLHA_BENEFICIO, True, False, "MCASP: grupo '1 Pessoal e Encargos Sociais'"),
    ("339048", None, None, NP.FOLHA_BENEFICIO, True, False, "MCASP: '48 Outros Auxílios Financeiros a Pessoas Físicas'"),
    ("339014", None, None, NP.FOLHA_BENEFICIO, True, False, "MCASP: '14 Diárias – Civil'"),
    ("329021", None, None, NP.INDETERMINADO, True, False, "MCASP: grupo '2 Juros e Encargos da Dívida'"),
    ("339139", False, None, NP.CONTRATACAO_NOVA, False, True, "MCASP: '91 Aplicação Direta Decorrente de Operação "
                                                              "entre Órgãos' (14.133 art. 75 IX)"),
    ("", None, None, NP.INDETERMINADO, False, None, "sem NE ligada"),
    ("CG0004700", None, None, NP.INDETERMINADO, False, None, "credor genérico não é natureza da despesa"),
]


@pytest.mark.parametrize("nd,vinc,nj,esp,fora75,forn,fonte", OURO_NATUREZA,
                         ids=[f"{o[0] or 'vazio'}-{o[1]}" for o in OURO_NATUREZA])
def test_tabela_ouro_natureza(nd, vinc, nj, esp, fora75, forn, fonte):
    d = natureza_pagamento(natureza_despesa=nd, vinculo_contrato=vinc, natureza_juridica_credor=nj)
    assert d.natureza is esp, f"{fonte}: {d}"
    assert d.nao_e_contratacao_nova is fora75, fonte
    assert d.credor_e_fornecedor is forn, fonte
    assert d.fonte


def test_os_osc_nao_e_excluida():
    """Plano §4.3: OS/OSC é fornecedor com regime próprio — transferência para o art. 75, mas segue fiscalizada."""
    d = natureza_pagamento(natureza_despesa="339085", natureza_juridica_credor="3999")
    assert d.natureza is NP.TRANSFERENCIA and d.credor_e_fornecedor is True and "9.637" in d.regime_proprio
    d = natureza_pagamento(natureza_despesa="335041")      # D5 (O4.10): sem o instrumento, não se sabe
    assert "13.019" in d.regime_proprio and d.credor_e_fornecedor is None


def test_classifica_pela_natureza_nunca_pelo_nome():
    import inspect
    assert "nome" not in inspect.signature(natureza_pagamento).parameters


@pytest.mark.parametrize("cod,ok", [("339039", True), ("3.3.90.39", True), ("33903911", True), ("99", False),
                                    ("739039", False), (None, False)])
def test_decompor(cod, ok):
    assert (decompor_natureza(cod) is not None) is ok


OURO_ORIGEM = [
    (dict(tipo_ob="Orçamentária", exercicio_ob=2025), OE.CORRENTE, "execução do exercício"),
    (dict(tipo_ob="RPP"), OE.RP, "4.320 art. 36: 'processadas'"),
    (dict(tipo_ob="RPNP Liquidados no Exercício"), OE.RP, "4.320 art. 36: 'não processadas'"),
    (dict(tipo_ob="Orçamentária", elemento="92"), OE.DEA, "4.320 art. 37 — DEA prevalece"),
    (dict(tipo_ob="", exercicio_ob=2025, exercicio_empenho=2024), OE.RP, "empenho de exercício anterior"),
    (dict(tipo_ob="", exercicio_ob=2025, exercicio_empenho=2025), OE.CORRENTE, "mesmo exercício"),
    (dict(tipo_ob="27763754000150"), OE.INDETERMINADO, "coluna deslocada na coleta não decide"),
    (dict(), OE.INDETERMINADO, "sem dado"),
]


@pytest.mark.parametrize("kw,esp,fonte", OURO_ORIGEM, ids=[o[2] for o in OURO_ORIGEM])
def test_tabela_ouro_origem(kw, esp, fonte):
    assert origem_exercicio(**kw).origem is esp, fonte


def test_eixos_independentes():
    """DEA é origem, não natureza: o mesmo 339092 tem origem DEA e natureza que não é contratação nova."""
    assert origem_exercicio(elemento="92").origem is OE.DEA
    assert natureza_pagamento(natureza_despesa="339092").nao_e_contratacao_nova is True
