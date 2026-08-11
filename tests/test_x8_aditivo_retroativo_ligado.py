# -*- coding: utf-8 -*-
"""X8 (aditivo retroativo) estava fora da varredura por um bloqueio que CADUCOU.

O cabeçalho de `varredura_execucao` dizia que `contrato_aditivo` não guarda a data de assinatura do
termo. Era verdade quando foi escrito, e deixou de ser em 2026-08-09, quando o coletor do PNCP
passou a gravar `dataAssinatura` — 1.684 dos 1.770 termos (95,1%). Ninguém releu o comentário, e o
detector seguia desligado por um motivo inexistente.

Ao ligar, medido no acervo: **36 contratos de 1.099** têm termo assinado depois do fim da vigência
corrente. Um deles, do MPRJ (R$ 3.620.859,02), teve o 1º termo — acréscimo quantitativo — assinado
em 29/11/2024, quatro dias após a vigência expirar em 25/11/2024.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.varredura_execucao import DETECTORES_EXECUCAO
from compliance_agent.varredura_execucao_ctx import montar_contexto


def test_x8_esta_na_lista_da_varredura():
    assert "X8" in DETECTORES_EXECUCAO


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
      create table pcrj_contratos (numero_controle_pncp text, orgao_cnpj text, orgao_nome text,
        unidade text, fornecedor_documento text, fornecedor_nome text, objeto text,
        valor_inicial real, valor_global real, data_assinatura text, vigencia_ini text,
        vigencia_fim text, num_aditivos integer, ano integer);
      create table contrato_aditivo (numero_controle_pncp text, sequencial_termo integer,
        numero_termo text, objeto text, valor_acrescido real, valor_global real,
        prazo_aditado_dias integer, vigencia_fim text, qualif_acrescimo text,
        qualif_vigencia text, qualif_reajuste text, fundamento_legal text,
        data_assinatura text, tipo_termo text, processo text, id integer primary key);
    """)
    c.execute("""insert into pcrj_contratos (numero_controle_pncp, orgao_nome, fornecedor_nome,
                 objeto, valor_inicial, valor_global, data_assinatura, vigencia_ini, vigencia_fim,
                 num_aditivos, ano) values ('CC1','MPRJ','ALFA','servico',1000.0,1000.0,
                 '2024-05-29','2024-05-29','2024-11-25',1,2024)""")
    return c


def test_contexto_entrega_a_data_de_assinatura_do_termo(con):
    """Era o elo que faltava: a consulta já trazia a coluna, o contexto não a repassava."""
    con.execute("""insert into contrato_aditivo (numero_controle_pncp, sequencial_termo,
                   numero_termo, objeto, vigencia_fim, data_assinatura)
                   values ('CC1',1,'1TA/2024','Acréscimo quantitativo','2025-03-25','2024-11-29')""")
    con.commit()
    ctx = montar_contexto(con, "CC1")
    assert ctx["aditivos"][0]["data_assinatura"] == "2024-11-29"


def test_contexto_entrega_a_vigencia_ORIGINAL(con):
    """`vigencia_fim_atual` já vem estendida pelos termos de prazo — o X8 compara com a original."""
    con.execute("""insert into contrato_aditivo (numero_controle_pncp, sequencial_termo,
                   numero_termo, objeto, vigencia_fim, data_assinatura, prazo_aditado_dias)
                   values ('CC1',1,'1TA','Prorrogação do prazo','2025-03-25','2024-10-01',120)""")
    con.commit()
    ctx = montar_contexto(con, "CC1")
    assert ctx["vigencia_fim"] == "2024-11-25"
    assert ctx["vigencia_fim_atual"] == "2025-03-25"


def test_x8_confirma_o_termo_assinado_depois_do_fim(con):
    con.execute("""insert into contrato_aditivo (numero_controle_pncp, sequencial_termo,
                   numero_termo, objeto, vigencia_fim, data_assinatura)
                   values ('CC1',1,'1TA/2024','Acréscimo quantitativo','2025-03-25','2024-11-29')""")
    con.commit()
    from compliance_agent.detectores import REGISTRO
    r = REGISTRO["X8"].avaliar(dict(montar_contexto(con, "CC1")))
    assert r.status == "confirmado"


def test_x8_nao_acusa_termo_assinado_DENTRO_da_vigencia(con):
    con.execute("""insert into contrato_aditivo (numero_controle_pncp, sequencial_termo,
                   numero_termo, objeto, vigencia_fim, data_assinatura)
                   values ('CC1',1,'1TA/2024','Acréscimo quantitativo','2025-03-25','2024-10-10')""")
    con.commit()
    from compliance_agent.detectores import REGISTRO
    r = REGISTRO["X8"].avaliar(dict(montar_contexto(con, "CC1")))
    assert r.status != "confirmado"


def test_sem_data_de_assinatura_e_NAO_AVALIAVEL_nao_confirmado(con):
    """O falso positivo que eu criei ao ligar o X8, e que só apareceu na conferência à mão.

    O contexto guardava em `data` a NOVA vigência do termo de prazo, e o X8 usa
    `data_assinatura or data`. Como a nova vigência é, por definição, posterior ao fim da antiga,
    TODA prorrogação saía como assinada fora do prazo. Pego num contrato de R$ 199 mi da Prefeitura
    do Rio cujos três termos têm `data_assinatura` NULA e mesmo assim vinham confirmados: 48
    confirmados viraram 36 depois do conserto.
    """
    con.execute("""insert into contrato_aditivo (numero_controle_pncp, sequencial_termo,
                   numero_termo, objeto, vigencia_fim, prazo_aditado_dias)
                   values ('CC1',1,'02/2026','Prorrogação do prazo por 12 meses','2027-01-26',365)""")
    con.commit()
    from compliance_agent.detectores import REGISTRO
    ctx = montar_contexto(con, "CC1")
    assert ctx["aditivos"][0]["data"] is None, "`data` é a data do ATO, não a nova vigência"
    r = REGISTRO["X8"].avaliar(dict(ctx))
    assert r.status == "nao_avaliavel", "sem data de assinatura não se afirma retroatividade"
