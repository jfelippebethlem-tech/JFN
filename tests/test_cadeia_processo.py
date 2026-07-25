# -*- coding: utf-8 -*-
"""CADEIA do processo: as peças existem — mas estão na ORDEM que a lei exige? (2026-07-24)

`sei/fases.lacunas` já responde o que FALTA nos autos. O que ninguém verificava é a SEQUÊNCIA: contrato
assinado antes do parecer jurídico esvazia o controle prévio do art. 53; pagamento antes da liquidação
viola os arts. 62-63 da Lei 4.320/1964; atesto depois da liquidação inverte a comprovação. Presença sem
ordem não prova regularidade nenhuma.

O relógio dos autos é o **ID do documento no SEI**: ele é sequencial e global, então cresce com o tempo
mesmo quando o documento não traz data no título. É proxy — e o módulo diz isso.
"""
from __future__ import annotations

from compliance_agent import cadeia_processo as CP


def _d(i, titulo, tipo=""):
    return {"i": str(i), "titulo": titulo, "tipo": tipo}


# ───────────────────────────── relógio dos autos ─────────────────────────────

def test_diferenca_de_id_precisa_representar_DIAS():
    """O ID anda ~113 mil/dia (medido). Os testes usam distâncias que representam dias, não minutos —
    senão validariam um comportamento que o dado real não sustenta."""
    assert CP._TOLERANCIA_ID >= 50_000


def test_id_do_documento_sei_serve_de_relogio():
    assert CP.id_sei("Parecer 126 (68524831)") == 68524831
    assert CP.id_sei("Anexo NF 16787 - VENDA (87898953)") == 87898953
    assert CP.id_sei("Documento sem id") is None


def test_data_no_titulo_tem_precedencia_sobre_o_id():
    """Quando o título traz data explícita, ela manda — o ID é só o substituto."""
    assert CP.momento({"titulo": "Contrato 12/2024 de 05/03/2024 (68525777)"})[0] == "data"
    assert CP.momento({"titulo": "Contrato (68525777)"})[0] == "id_sei"


def test_id_curto_demais_nao_e_id_do_sei():
    """(100) ou (2024) no título não são ID do SEI — o ID real tem 6+ dígitos. Confundir criaria
    cronologia inventada a partir de número de contrato ou de ano."""
    assert CP.id_sei("Contrato 45/2024 (100)") is None
    assert CP.id_sei("Termo (2024)") is None


# ───────────────────────────── inversões que a lei não admite ─────────────────────────────

def test_contrato_antes_do_parecer_juridico_e_apontado():
    """Art. 53 da Lei 14.133: a análise jurídica é PRÉVIA. Contrato assinado antes esvazia o controle."""
    docs = [_d(0, "Termo de Contrato 45/2024 (68524831)", "contrato"),
            _d(1, "Parecer Jurídico PGE 88/2024 (68724999)", "parecer_juridico")]
    r = CP.analisar_cadeia(docs)
    assert r["grau"] == "vermelho"
    assert any(x["tipo"] == "contrato_antes_do_parecer" for x in r["inversoes"])
    assert "53" in r["inversoes"][0]["fundamento"]


def test_ordem_correta_nao_gera_achado():
    docs = [_d(0, "Parecer Jurídico PGE 88/2024 (68524831)", "parecer_juridico"),
            _d(1, "Termo de Contrato 45/2024 (68724999)", "contrato")]
    r = CP.analisar_cadeia(docs)
    assert r["inversoes"] == []
    assert r["grau"] in ("verde", "nao_aplicavel")


def test_pagamento_antes_da_liquidacao_viola_a_4320():
    docs = [_d(0, "Ordem Bancária 2024OB0001 (68524831)", "ordem_bancaria"),
            _d(1, "Nota de Liquidação 2024NL0001 (68724999)", "nota_liquidacao")]
    r = CP.analisar_cadeia(docs)
    assert any(x["tipo"] == "pagamento_antes_da_liquidacao" for x in r["inversoes"])
    assert "4.320" in [x["fundamento"] for x in r["inversoes"]][0]


def test_empenho_depois_da_liquidacao_e_apontado():
    docs = [_d(0, "Nota de Liquidação 2024NL0001 (68524831)", "nota_liquidacao"),
            _d(1, "Nota de Empenho 2024NE0001 (68724999)", "nota_empenho")]
    r = CP.analisar_cadeia(docs)
    assert any(x["tipo"] == "liquidacao_antes_do_empenho" for x in r["inversoes"])


def test_aditivo_antes_do_contrato_e_apontado():
    docs = [_d(0, "Primeiro Termo Aditivo (68524831)", "aditivo"),
            _d(1, "Termo de Contrato 45/2024 (68724999)", "contrato")]
    r = CP.analisar_cadeia(docs)
    assert any(x["tipo"] == "aditivo_antes_do_contrato" for x in r["inversoes"])


# ───────────────────────────── honestidade ─────────────────────────────

def test_sem_relogio_nao_afirma_ordem():
    """Sem data e sem ID, a ordem dos autos não é aferível — não se inventa cronologia."""
    docs = [_d(0, "Termo de Contrato", "contrato"), _d(1, "Parecer Jurídico", "parecer_juridico")]
    r = CP.analisar_cadeia(docs)
    assert r["grau"] == "nao_aplicavel"
    assert "não" in r["resumo"].lower() and ("relógio" in r["resumo"].lower() or "ordem" in r["resumo"].lower())
    assert r["inversoes"] == []


def test_peca_ausente_nao_vira_inversao():
    """Processo sem parecer não tem inversão de parecer — ausência é outra família (lacunas)."""
    docs = [_d(0, "Termo de Contrato 45/2024 (68524831)", "contrato")]
    r = CP.analisar_cadeia(docs)
    assert r["inversoes"] == []


def test_veredito_sempre_resolvido_e_com_ressalva():
    for docs in ([], [_d(0, "x", "")], [_d(0, "Contrato (68524831)", "contrato")]):
        r = CP.analisar_cadeia(docs)
        assert r["grau"] not in ("indeterminado", "indisponivel", "")
        assert r["ressalva"]


def test_proxy_do_id_e_declarado_no_achado():
    docs = [_d(0, "Termo de Contrato 45/2024 (68524831)", "contrato"),
            _d(1, "Parecer Jurídico PGE (68724999)", "parecer_juridico")]
    r = CP.analisar_cadeia(docs)
    assert "id" in r["inversoes"][0]["como_soube"].lower()
    assert "proxy" in r["ressalva"].lower() or "sequencial" in r["ressalva"].lower()


# ───────── falsos positivos medidos no acervo (2026-07-24) ─────────

def test_parecer_TECNICO_nao_e_parecer_juridico():
    """Caso real (070002/003793/2024): 'Parecer Técnico 5ª Medição' era lido como parecer jurídico e
    gerava "contrato antes do parecer". Parecer técnico de medição é peça de EXECUÇÃO — o controle
    prévio do art. 53 é do parecer JURÍDICO (PGE/procuradoria/assessoria jurídica)."""
    doc = {"titulo": "Parecer Técnico 5ª Medição (69866073)", "tipo": "parecer"}
    assert CP._marco(doc) != "parecer_juridico"
    docs = [_d(0, "Contrato 33/2023 - INEA (69844132)", "contrato"),
            _d(1, "Parecer Técnico 5ª Medição (69866073)", "parecer")]
    assert CP.analisar_cadeia(docs)["inversoes"] == []


def test_ids_proximos_sao_a_mesma_juntada_nao_inversao():
    """Caso real (030001/091921/2024): 'Despacho de Liquidação (87839016)' e 'Nota de Empenho (87839511)'
    — 495 de diferença. Medido no acervo, o ID do SEI anda ~113 mil por DIA: 495 são MINUTOS, isto é, a
    mesma sessão de juntada. Ordem de juntada não é ordem do ato."""
    docs = [_d(0, "Despacho de Liquidação da Despesa (87839016)", "nota_liquidacao"),
            _d(1, "Nota de Empenho Original - NE (87839511)", "nota_empenho")]
    r = CP.analisar_cadeia(docs)
    assert r["inversoes"] == []
    assert r["grau"] != "vermelho"


def test_distancia_grande_no_id_continua_valendo_como_inversao():
    docs = [_d(0, "Termo de Contrato 45/2024 (68000000)", "contrato"),
            _d(1, "Parecer Jurídico PGE 88/2024 (69000000)", "parecer_juridico")]
    r = CP.analisar_cadeia(docs)
    assert any(x["tipo"] == "contrato_antes_do_parecer" for x in r["inversoes"])


def test_titulo_desmente_o_tipo_quando_diz_TECNICO():
    """Caso real (070002/006215/2024): o classificador marca 'Parecer Técnico - 5ª Medição' com tipo
    'parecer_juridico'. Aqui o TÍTULO desmente o tipo: parecer técnico de medição não é o controle
    prévio do art. 53. Quando os dois discordam, vale o que está escrito no título."""
    doc = {"titulo": "Parecer Técnico - 5ª Medição (72269742)", "tipo": "parecer_juridico"}
    assert CP._marco(doc) != "parecer_juridico"
    doc2 = {"titulo": "Parecer 145/2024 PGE-RJ (72269742)", "tipo": "parecer_juridico"}
    assert CP._marco(doc2) == "parecer_juridico"
