# -*- coding: utf-8 -*-
"""`minerar_extratos` — de uma PÁGINA do D.O. Rio (vários extratos colados) para EVENTOS por processo.

`pcrj_doe_materia.tipo` é o TERMO DE BUSCA da página, não o tipo do extrato: uma página
"inexigibilidade" continha um EXTRATO DE TERMO ADITIVO. Por isso a mineração segmenta pelo
cabeçalho real e prende cada campo ao seu segmento. Trechos abaixo são reais (2026).
"""
from __future__ import annotations

from compliance_agent.pcrj.doe_minerador import minerar_extratos

_PAGINA = (
    "D.O. RIO Diário Oficial do Município do Rio de Janeiro SECRETARIA MUNICIPAL DE SAÚDE "
    "EXTRATO DE INSTRUMENTO CONTRATUAL Processo Instrutivo nº: 000900.051272/2026-71 Contrato nº 2608190 "
    "Data da Assinatura: 10/06/2026 Partes: PCRJ/SMS e SIMPRESS COMERCIO LOCAÇÃO E SERVIÇOS LTDA. "
    "Objeto: Contratação de empresa para prestação de serviços de outsourcing de impressão. "
    "Prazo: 12 meses Valor: R$ 1.234.567,89 Fundamento: Lei Federal nº 14.133/2021, art. 75, inciso VIII "
    "Programa de Trabalho: 18.01.10.302.0400 "
    "EXTRATO DE TERMO ADITIVO PROCESSO INSTRUTIVO N.º: 08/000.500/2022. INSTRUMENTO CONTRATUAL N.º: 062/2023 "
    "Livro SMAS n.º 03 DATA DA ASSINATURA: 07/11/2023 PARTES: Secretaria Municipal de Assistência Social e "
    "Quimilar Comércio e Serviços Especializados Ltda. CNPJ: 86.776.499/0001-49. OBJETO: Contratação de empresa "
    "especializada para extintores. PRAZO: 12 meses, 07/11/2023 a 06/11/2024 VALOR TOTAL: R$ 502.590,00 "
    "Programa de Trabalho: 17.01.08.244.0628"
)


def test_segmenta_pelo_cabecalho_real_e_prende_os_campos():
    ev = minerar_extratos(_PAGINA)
    assert [e["tipo"] for e in ev] == ["contrato", "aditivo"]
    c, a = ev
    assert "000900.051272/2026-71" in c["processos"]
    assert c["contrato_num"] == "2608190"
    assert c["data_assinatura"] == "2026-06-10"
    assert c["valor"] == 1234567.89
    assert c["fundamento"] == "art. 75, VIII"
    assert "SIMPRESS" in c["partes"]
    # o aditivo NÃO herda nada do contrato anterior
    assert "08/000.500/2022" in a["processos"] and "000900.051272/2026-71" not in a["processos"]
    assert a["valor"] == 502590.0
    assert a["data_assinatura"] == "2023-11-07"
    assert a["fundamento"] is None


def test_dispensa_e_ratificacao_viram_tipo_proprio():
    tx = ("TERMO DE RATIFICAÇÃO Processo nº 000900.061498/2026-81. Ratifico a dispensa de licitação com "
          "fundamento no art. 75, inciso II, da Lei nº 14.133/2021. Valor: R$ 8.640,00. "
          "AVISO DE LICITAÇÃO Pregão Eletrônico nº 100/2026 Processo: 001200.000097/2026-12 Objeto: merenda.")
    ev = minerar_extratos(tx)
    assert [e["tipo"] for e in ev] == ["ratificacao", "aviso"]
    assert ev[0]["fundamento"] == "art. 75, II" and ev[0]["valor"] == 8640.0
    assert ev[1]["processos"] == ["001200.000097/2026-12"]


def test_aditivo_real_valor_do_termo_e_ordinal():
    tx = ("EXTRATO DE TERMO ADITIVO Processo: 000600.000099/2026-28 Instrumento: 4º Termo Aditivo nº 66/2026 ao "
          "Contrato Nº 136/2022. Data da assinatura: 14/07/2026 Partes: MUNICÍPIO DO RIO DE JANEIRO - SMI e EXCEL "
          "ELEVADORES LTDA Objeto: Prorrogação do prazo. Valor do Termo: R$ 1.285.266,59 (um milhão) "
          "Programa de Trabalho: 10.1501.15.122 Fundamento: Art. nº 57, inciso II da Lei 8.666/93")
    (e,) = minerar_extratos(tx)
    assert e["tipo"] == "aditivo" and e["aditivo_n"] == 4
    assert e["contrato_num"] == "136/2022" and e["valor"] == 1285266.59
    assert e["fundamento"] is None          # art. 57 não é base de contratação direta


def test_pagina_sem_cabecalho_devolve_vazio():
    assert minerar_extratos("Diário Oficial — expediente do dia, sem extratos.") == []
