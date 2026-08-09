# -*- coding: utf-8 -*-
"""Sem a DATA do termo, aditivo precoce é incalculável — e precocidade é o sinal.

A CGE apontou, em 09/08/2026, um acréscimo de **45,4% dezessete dias após a assinatura** de um
contrato de pavimentação da SECID. O sinal não é o percentual sozinho: acréscimo grande logo no
início da execução é o que distingue **falha de planejamento** (ou direcionamento) de
**recomposição legítima**, porque desequilíbrio econômico superveniente não se forma em duas
semanas.

Medido no mesmo dia: a casa tinha **1.729 aditivos coletados e nenhuma data de assinatura** — a
API do PNCP entrega `dataAssinatura` em todo termo e o parser a descartava, junto de
`tipoTermoContratoNome` (a classificação que a própria fonte dá ao termo, insumo direto da régua
do art. 125) e de `processo` (a ponte para os autos no SEI).

O que este teste trava é o contrato com a fonte: o que a API entrega e a casa precisa, a casa
guarda. É a família [[metadado-dentro-do-dado]] pelo avesso — aqui o metadado foi jogado fora.
"""
from __future__ import annotations

import sqlite3

from compliance_agent.collectors.pncp import _parse_termo
from compliance_agent.contratos.db import init_schema

# payload REAL do PNCP (contrato 28305936000140-2-000003/2025), reduzido aos campos que importam
TERMO = {
    "sequencialTermoContrato": 1,
    "numeroTermoContrato": "00015/2025",
    "objetoTermoContrato": "ACRESCIMO DE QUANTITATIVO",
    "valorAcrescido": 45_300_000.0,
    "valorGlobal": 144_900_000.0,
    "prazoAditadoDias": None,
    "dataVigenciaFim": "2026-01-27",
    "dataVigenciaInicio": "2025-09-02",
    "dataAssinatura": "2025-09-02",
    "tipoTermoContratoNome": "Termo de Aditamento",
    "processo": "SEI-510001/001417/2025",
    "qualificacaoAcrescimoSupressao": "1",
    "qualificacaoVigencia": "0",
    "qualificacaoReajuste": "0",
    "fundamentoLegal": "Art. 125 da Lei 14.133/2021",
}


def test_parser_guarda_data_tipo_e_processo():
    r = _parse_termo(TERMO)
    assert r["data_assinatura"] == "2025-09-02", "sem a data não há como medir aditivo precoce"
    assert r["tipo_termo"] == "Termo de Aditamento"
    assert r["processo"] == "SEI-510001/001417/2025", "sem o processo não se chega aos autos"


def test_parser_nao_perdeu_o_que_ja_guardava():
    r = _parse_termo(TERMO)
    assert r["valor_acrescido"] == 45_300_000.0 and r["valor_global"] == 144_900_000.0
    assert r["fundamento_legal"].startswith("Art. 125")
    assert r["sequencial_termo"] == 1


def test_termo_sem_data_nao_quebra():
    """Fonte omissa devolve None — ausência de dado nunca vira exceção nem data inventada."""
    assert _parse_termo({"sequencialTermoContrato": 2})["data_assinatura"] is None


def test_schema_tem_as_colunas_e_a_migracao_e_idempotente(tmp_path):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    # base ANTIGA, sem as três colunas — é o estado real do acervo (1.729 aditivos já gravados)
    con.execute("CREATE TABLE contrato_aditivo (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " numero_controle_pncp TEXT NOT NULL, sequencial_termo INTEGER,"
                " UNIQUE(numero_controle_pncp, sequencial_termo))")
    init_schema(con)
    init_schema(con)                       # segunda vez: a migração não pode explodir
    cols = {d[1] for d in con.execute("PRAGMA table_info(contrato_aditivo)")}
    assert {"data_assinatura", "tipo_termo", "processo"} <= cols
    con.close()


def test_insert_do_coletor_casa_com_o_schema(tmp_path):
    """O SQL do coletor precisa caber na tabela — o teste que faltava quando a coluna nasceu."""
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    init_schema(con)
    row = _parse_termo(TERMO)
    con.execute(
        "INSERT OR IGNORE INTO contrato_aditivo (numero_controle_pncp, sequencial_termo,"
        " numero_termo, objeto, valor_acrescido, valor_global, prazo_aditado_dias,"
        " vigencia_fim, qualif_acrescimo, qualif_vigencia, qualif_reajuste, fundamento_legal,"
        " data_assinatura, tipo_termo, processo)"
        " VALUES (:ncp,:sequencial_termo,:numero_termo,:objeto,:valor_acrescido,:valor_global,"
        " :prazo_aditado_dias,:vigencia_fim,:qualif_acrescimo,:qualif_vigencia,:qualif_reajuste,"
        " :fundamento_legal,:data_assinatura,:tipo_termo,:processo)",
        {**row, "ncp": "28305936000140-2-000003/2025"})
    con.commit()
    assert con.execute("SELECT data_assinatura FROM contrato_aditivo").fetchone()[0] == "2025-09-02"
    con.close()
