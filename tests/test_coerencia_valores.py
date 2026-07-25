# -*- coding: utf-8 -*-
"""COERÊNCIA DE VALORES dentro do processo (2026-07-24).

O processo carrega os mesmos números em peças diferentes — contrato, empenho, nota fiscal, ordem
bancária. Quando eles não fecham, alguma coisa aconteceu: pagou-se acima do contratado, empenhou-se
menos do que se pagou, ou a nota é de outro valor. Ninguém verificava isso, embora 1.587 dos 2.050
processos do acervo tragam valores em R$ no texto.

Honestidade: divergência de valor é INDÍCIO — aditivo, reajuste, glosa e pagamento parcelado explicam
muitas delas legitimamente. O módulo aponta a diferença e diz o que a explicaria; não acusa.
"""
from __future__ import annotations

from compliance_agent import coerencia_valores as CV


def _doc(titulo, texto, tipo=""):
    return {"titulo": titulo, "tipo": tipo, "texto": texto}


# ───────────────────────────── leitura de valores ─────────────────────────────

def test_le_valor_brasileiro_no_texto():
    assert CV.valores("pagamento de R$ 1.234.567,89 ao fornecedor") == [1234567.89]
    assert CV.valores("R$ 10,00 e R$ 2.500,50") == [10.0, 2500.5]
    assert CV.valores("sem valor algum") == []


def test_ignora_numero_que_nao_e_dinheiro():
    """Processo, CNPJ e data têm dígitos e ponto — não são valores."""
    assert CV.valores("Processo 080001.012345/2024-11 de 05/03/2024, CNPJ 12.345.678/0001-99") == []


# ───────────────────────────── pago × contratado ─────────────────────────────

def test_pago_acima_do_contratado_e_apontado():
    docs = [_doc("Termo de Contrato 10/2024", "Valor global do contrato: R$ 100.000,00", "contrato"),
            _doc("Ordem Bancária 2024OB001", "Ordem Bancária no valor de R$ 150.000,00", "ordem_bancaria")]
    r = CV.analisar_valores(docs)
    assert r["grau"] == "vermelho"
    assert r["pago"] == 150000.0 and r["contratado"] == 100000.0
    assert "aditivo" in r["explicacoes_possiveis"][0].lower() or \
           any("aditivo" in e.lower() for e in r["explicacoes_possiveis"])


def test_pago_dentro_do_contratado_nao_acusa():
    docs = [_doc("Termo de Contrato", "Valor global do contrato: R$ 100.000,00", "contrato"),
            _doc("Ordem Bancária", "Ordem Bancária no valor de R$ 40.000,00", "ordem_bancaria")]
    r = CV.analisar_valores(docs)
    assert r["grau"] == "verde"


def test_aditivo_no_processo_entra_no_teto():
    """Se o processo tem aditivo de valor, o teto sobe — pagar acima do contrato original é normal."""
    docs = [_doc("Contrato", "Valor global do contrato: R$ 100.000,00", "contrato"),
            _doc("Primeiro Termo Aditivo", "Acréscimo de R$ 20.000,00 ao valor contratual", "aditivo"),
            _doc("Ordem Bancária", "Ordem Bancária no valor de R$ 115.000,00", "ordem_bancaria")]
    r = CV.analisar_valores(docs)
    assert r["contratado"] == 120000.0
    assert r["grau"] == "verde"


def test_tolerancia_para_centavos_e_reajuste_pequeno():
    docs = [_doc("Contrato", "Valor global do contrato: R$ 100.000,00", "contrato"),
            _doc("Ordem Bancária", "Ordem Bancária no valor de R$ 100.300,00", "ordem_bancaria")]
    r = CV.analisar_valores(docs)
    assert r["grau"] == "verde"          # 0,3% — dentro do ruído de reajuste/arredondamento


# ───────────────────────────── favorecido ─────────────────────────────

def test_cnpj_do_pagamento_diferente_do_contratado():
    docs = [_doc("Contrato", "CONTRATADA: ALFA LTDA, CNPJ 11.222.333/0001-44", "contrato"),
            _doc("Ordem Bancária", "Favorecido: BETA ME, CNPJ 99.888.777/0001-66", "ordem_bancaria")]
    r = CV.analisar_valores(docs)
    assert r["cnpj_divergente"] is True
    assert r["grau"] == "vermelho"
    assert any("cess" in e.lower() or "sub-rog" in e.lower() or "consórcio" in e.lower()
               for e in r["explicacoes_possiveis"])


def test_mesmo_cnpj_nao_acusa():
    docs = [_doc("Contrato", "CONTRATADA: ALFA LTDA, CNPJ 11.222.333/0001-44", "contrato"),
            _doc("Ordem Bancária", "Favorecido: ALFA LTDA 11.222.333/0001-44", "ordem_bancaria")]
    r = CV.analisar_valores(docs)
    assert r["cnpj_divergente"] is False


def test_filial_do_mesmo_grupo_nao_e_divergencia():
    """Mesma raiz de CNPJ (matriz/filial) não é pagamento a terceiro."""
    docs = [_doc("Contrato", "CONTRATADA: ALFA, CNPJ 11.222.333/0001-44", "contrato"),
            _doc("Ordem Bancária", "Favorecido: ALFA FILIAL 11.222.333/0002-25", "ordem_bancaria")]
    r = CV.analisar_valores(docs)
    assert r["cnpj_divergente"] is False


# ───────────────────────────── honestidade ─────────────────────────────

def test_sem_valores_e_resolvido():
    r = CV.analisar_valores([_doc("Despacho", "Encaminho o processo.", "despacho")])
    assert r["grau"] == "nao_aplicavel"
    assert r["grau"] not in ("indeterminado", "indisponivel")
    assert r["ressalva"]


def test_sem_contrato_nao_afirma_excesso():
    """Sem o valor contratado, pagamento algum é 'acima' — não se inventa teto."""
    docs = [_doc("Ordem Bancária", "Ordem Bancária no valor de R$ 500.000,00", "ordem_bancaria")]
    r = CV.analisar_valores(docs)
    assert r["grau"] in ("nao_aplicavel", "a_verificar")
    assert r["contratado"] is None


# ───────── falsos positivos medidos no acervo (2026-07-24) ─────────

def test_contrato_sem_valor_legivel_nao_gera_excesso():
    """Caso real (5 achados, todos falsos): a peça foi lida como contrato mas nenhum valor foi extraído
    dela. Teto ZERO faz qualquer pagamento 'exceder' — teto desconhecido não é teto zero."""
    docs = [_doc("Termo de Contrato", "Contrato firmado entre as partes, sem valor no texto lido.", "contrato"),
            _doc("Ordem Bancária", "Ordem Bancária no valor de R$ 70.706,00", "ordem_bancaria")]
    r = CV.analisar_valores(docs)
    assert r["grau"] == "a_verificar"
    assert r["contratado"] is None and r["excesso"] is None


def test_valor_avulso_na_peca_nao_vira_teto_contratual():
    """Caso real (260006/006916/2025): 'contratado' saiu R$ 192,17 — valor unitário/taxa citado no
    contrato, não o global. Sem marca de VALOR GLOBAL/TOTAL, não se assume teto."""
    docs = [_doc("Contrato", "Multa de R$ 192,17 por dia de atraso, conforme cláusula décima.", "contrato"),
            _doc("Ordem Bancária", "Ordem Bancária no valor de R$ 3.987,42", "ordem_bancaria")]
    r = CV.analisar_valores(docs)
    assert r["grau"] == "a_verificar"
    assert r["contratado"] is None


def test_valor_global_explicito_continua_valendo_como_teto():
    docs = [_doc("Contrato", "O valor global do contrato é de R$ 100.000,00.", "contrato"),
            _doc("Ordem Bancária", "Ordem Bancária no valor de R$ 150.000,00", "ordem_bancaria")]
    r = CV.analisar_valores(docs)
    assert r["contratado"] == 100000.0 and r["grau"] == "vermelho"
