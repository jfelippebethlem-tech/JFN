# -*- coding: utf-8 -*-
"""Decisões delegadas pelo dono em 24/11/2026 (noite), aplicadas EM SOMBRA — ~/vault/refatoracao/
decisoes-delegadas-20261124.md. Cada decisão tem controle positivo e negativo.

§1 E9-9   testes contábeis OB × NL exigem `universo`/`registro_liquido` (Lei 4.320 art. 62: todo credor)
§2        rules.ob_favorecido_doerj_cruzado: fora de manchete, erro grave aberto; cláusula ≠ ato praticado
§3 O66-P3 FP > 50% COMPROVADA (Clopper-Pearson inferior) → Tier 3
§4        limiar do P4 mantido em 0,35
§5 E9-1/E9-2/E9-5, D3, D11 (as demais ficam registradas, sem código)
"""
from __future__ import annotations

from datetime import date

import pytest

from compliance_agent.aplicacao.estagios import elegibilidade as E
from compliance_agent.dominio.regime import Regime, regime_contrato
from compliance_agent.qualidade import detectores as Q
from compliance_agent.rules.doerj_casamento import eh_dever_ser, ocorrencias


def _ob(**kw):
    base = dict(unidade="ob_siafe", chave="010100|2025OB1|2025", paga=True, credor_classe="PJ_PRIVADA",
                natureza_despesa="33903900", natureza_pagamento="PARCELA_CONTRATO", nao_e_contratacao_nova=True,
                credor_e_fornecedor=True, elemento="39")
    base.update(kw)
    return E.Fatos(**base)


# ── §1 E9-9 ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_e9_9_testes_contabeis_exigem_registro_de_todo_credor():
    assert E.exiges_do_detector("e10.ob_paga_acima_liquidado") == {"ob_siafe": "registro_liquido"}
    assert E.exiges_do_detector("e10.ob_antes_da_liquidacao") == {"ob_siafe": "universo"}
    assert E.exiges_do_detector("a_portar.lex_fatos.c_pago_maior_que_nl") == {"ob_siafe": "registro_liquido"}
    assert E.exiges_do_detector("a_portar.lex_fatos.c_ob_antes_da_nl") == {"ob_siafe": "universo"}


@pytest.mark.parametrize("kw", [dict(credor_classe="ENTE_PUBLICO"), dict(credor_classe="UG_PROPRIA"),
                                dict(natureza_pagamento="FOLHA_BENEFICIO", credor_classe="PF"),
                                dict(natureza_pagamento="TRANSFERENCIA", credor_e_fornecedor=False)])
def test_e9_9_positivo_repasse_e_folha_entram_no_registro(kw):
    ex = _ob(**kw).exiges()
    assert ex["registro_liquido"] == "E" and ex["execucao"] != "E"     # antes caíam pela régua de execução


def test_e9_9_negativo_gd_sem_valor_apurado_segue_indeterminada():
    assert _ob(devolucao="nao_apurada", credor_classe="ENTE_PUBLICO").exiges()["registro_liquido"] == \
        "?:DEVOLUCAO_NAO_APURADA"


# ── §2 doerj ────────────────────────────────────────────────────────────────────────────────────────────────────
NOME, CNPJ = "ACME SERVICOS DE LIMPEZA LTDA", "12345678000190"
EXTRATO_CLAUSULA = (
    "SECRETARIA DE ESTADO DE SAÚDE EXTRATO DE CONTRATO INSTRUMENTO: Contrato nº 10/2026. PARTES: Estado do Rio de "
    "Janeiro e ACME SERVICOS DE LIMPEZA LTDA, CNPJ 12.345.678/0001-90. OBJETO: limpeza predial. VALOR: R$ 100.000,00. "
    "O descumprimento sujeitará a CONTRATADA às sanções de advertência e multa previstas na cláusula décima. "
    "Id: 2740001")
DECISAO_SANCAO = (
    "SECRETARIA DE ESTADO DE POLÍCIA PENAL DESPACHO DO SUBSECRETÁRIO DE 19.10.2026 PROCESSO Nº SEI-210001/077100/2026 - "
    "DECIDO pela aplicação ACME SERVIÇOS DE LIMPEZA LTDA CNPJ nº 12.345.678/0001-90, as penalidades de Ad- vertência "
    "e Multa de 0,3% ao contrato nº 25/2023. Id: 2740002")


def test_doerj_clausula_de_multa_no_extrato_nao_e_sancao():
    """Controle NEGATIVO (2 dos 4 erros graves conferidos: Agevap e Oncovit)."""
    assert ocorrencias(EXTRATO_CLAUSULA, NOME, CNPJ) == []


def test_doerj_sancao_decidida_continua_casando():
    """Controle POSITIVO — 'penalidades de' é dispositivo, não dever-ser (sanção real do replay de 24/11)."""
    assert [o["termo"] for o in ocorrencias(DECISAO_SANCAO, NOME, CNPJ)] == ["multa"]


def test_doerj_dever_ser_so_na_mesma_frase():
    seg = "CLAUSULA QUINTA. VALOR R$ 10,00. A EMPRESA PAGOU MULTA"
    assert not eh_dever_ser(seg, seg.index("MULTA"))
    seg2 = "A CONTRATADA ESTARA SUJEITA A MULTA"
    assert eh_dever_ser(seg2, seg2.index("MULTA"))


def test_doerj_registro_fora_de_manchete_com_erro_grave():
    e = Q.carregar()["rules.ob_favorecido_doerj_cruzado"]
    assert e["manchete"] is False and len(e["calibracao"]["erro_grave_aberto"]) == 4
    t = Q.avaliar_tier(e, date(2026, 11, 25))
    assert t["tier"] == 2 and "erro_grave_conferido" in t["tier_motivo"]


# ── §3 O66-P3 ───────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("k, n, esperado", [(5, 5, 0.478176), (4, 5, 0.283582), (43, 43, 0.917789),
                                            (24, 26, 0.748697), (0, 10, 0.0)])
def test_clopper_pearson_inferior(k, n, esperado):
    assert Q.clopper_pearson_inferior(k, n) == pytest.approx(esperado, abs=1e-5)


def _medida(k, n):
    return {"fp_medida": {"data": "2026-11-20", "amostra": "a", "taxa": "t", "fonte_primaria": "f", "onde": "o",
                          "n": n, "falsos": k, "estratificada": False}, "dominio": "x"}


def test_fp_comprovada_acima_de_50pct_vai_ao_tier3():
    t = Q.avaliar_tier(_medida(24, 26), date(2026, 11, 25))
    assert t["tier"] == 3 and t["tier_motivo"].startswith("fp_acima_de_50pct_comprovada")


@pytest.mark.parametrize("k, n", [(5, 5), (4, 4), (12, 16), (8, 16)])
def test_fp_alta_sem_prova_fica_no_tier2(k, n):
    """Wilson rebaixaria 5/5, 4/4 e 12/16; o exato não — n pequeno não basta para ocultar."""
    assert Q.avaliar_tier(_medida(k, n), date(2026, 11, 25))["tier"] == 2


# ── §4 limiar do P4 ─────────────────────────────────────────────────────────────────────────────────────────────
def test_limiar_do_p4_mantido():
    from compliance_agent import objeto_similaridade as OS
    assert OS.LIMIAR == 0.35


# ── §5 E9-1/E9-2, E9-5, D3, D11 ────────────────────────────────────────────────────────────────────────────────
def test_e9_1_ente_publico_em_execucao_so_sai_com_natureza_provada():
    assert _ob(credor_classe="ENTE_PUBLICO").exiges()["execucao"] == "?:ENTE_PUBLICO"
    assert _ob(credor_classe="ENTE_PUBLICO", natureza_pagamento="TRANSFERENCIA",
               credor_e_fornecedor=False).exiges()["execucao"] == "I:TRANSFERENCIA"
    assert _ob(credor_classe="ENTE_PUBLICO").exiges()["fornecedor"] == "I:ENTE_PUBLICO"     # E9-1 confirmada


def test_e9_5_ordem_cronologica_tira_osc_e_mantem_privado():
    assert E.exiges_do_detector("ordem_cronologica") == {"ob_siafe": "execucao_14133"}
    assert _ob(credor_classe="OS_OSC").exiges()["execucao_14133"] == "I:REGIME_PROPRIO_MROSC"
    assert _ob(credor_classe="OS_OSC").exiges()["execucao"] == "E"           # padrao.mrosc_* continuam vendo a OSC
    assert _ob().exiges()["execucao_14133"] == "E"


def test_d3_estatal_sem_data_e_indeterminado_e_declarada_decide():
    assert regime_contrato(contratante_estatal=True).regime is Regime.INDETERMINADO
    assert regime_contrato(contratante_estatal=True, lei_declarada_texto="Lei 13.303/2016").regime is Regime.L13303
    assert regime_contrato(contratante_estatal=True, data_assinatura=date(2025, 3, 1)).regime is Regime.L13303


class _Q:
    estatais = {"EMPRESA X"}


def test_d11_indicio_de_estatal_nao_decide_regime_nem_teto():
    reg, fonte, est = E._regime(_Q(), "EMPRESA X", "Lei 14.133/2021, Art. 75, II", date(2025, 3, 1), True)
    assert reg == Regime.INDETERMINADO.value and est is False and "D11" in fonte
    reg, _, est = E._regime(_Q(), "EMPRESA X", "Lei 13.303/2016, Art. 29, II", date(2025, 3, 1), True)
    assert reg == Regime.L13303.value and est is False
    reg, _, _ = E._regime(_Q(), "OUTRA", "Lei 14.133/2021, Art. 75, II", date(2025, 3, 1), True)
    assert reg == Regime.L14133.value
