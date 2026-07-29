# -*- coding: utf-8 -*-
"""A ponte vício → tipo, e a regra que ela existe para impedir: chamar formalidade de improbidade.

A Lei 14.230/2021 tornou a improbidade muito mais difícil de configurar, e o sistema não sabia
disso. Três exigências novas que este módulo carrega, todas com texto legal conferido no Planalto:

  · art. 1º §2º — dolo é "a vontade livre e consciente de alcançar o resultado ilícito ...,
    não bastando a voluntariedade do agente";
  · art. 10 caput e VIII — a lesão ao erário exige perda patrimonial "efetiva e
    comprovadamente" demonstrada;
  · art. 11, V — frustrar o caráter concorrencial exige finalidade específica de "obtenção de
    benefício próprio, direto ou indireto, ou de terceiros".

Daí decorre a regra que os testes travam: **cláusula restritiva sem dano comprovado e sem
beneficiário identificado não é improbidade** — é irregularidade administrativa, e pode ser
ilícito da pessoa jurídica pela Lei 12.846, que dispensa dolo do agente público.
"""
from __future__ import annotations

import pytest

from compliance_agent.knowledge.tipicidade import (
    ENQUADRAMENTOS,
    PROVAS,
    REGIMES,
    cobertura,
    enquadrar,
    o_que_falta,
    regime,
    validar,
)


# ───────────────────────────── integridade do mapa ────────────────────────────────────────────

def test_todo_ponteiro_resolve():
    assert validar() == []


def test_todo_regime_cita_o_dispositivo_e_o_orgao():
    for r in REGIMES.values():
        assert r.dispositivo, f"{r.id} sem dispositivo — inverificável numa peça"
        assert r.orgao_competente, f"{r.id} sem órgão competente"
        assert r.elementos, f"{r.id} sem elementos do tipo"


def test_cobertura_e_declarada_nao_fingida():
    c = cobertura()
    assert c["mapeados"] >= 15
    assert c["faltando"], "cobertura de 100% seria suspeita — o catálogo tem 42 vícios"
    assert c["mapeados"] + len(c["faltando"]) == c["total_catalogo"]


# ───────────────────────── a mudança de 2021, em código ───────────────────────────────────────

def test_improbidade_exige_dolo_especifico_em_todos_os_tipos():
    """A modalidade culposa foi extinta pela Lei 14.230/2021."""
    for rid in ("improbidade_dano", "improbidade_principios", "improbidade_enriquecimento"):
        assert REGIMES[rid].elemento_subjetivo == "dolo_especifico"


def test_lesao_ao_erario_exige_dano_efetivo_e_comprovado():
    r = REGIMES["improbidade_dano"]
    assert any("EFETIVA" in e or "efetiva" in e for e in r.elementos)
    assert "efetiva e comprovadamente" in r.verbatim


def test_art_11_exige_finalidade_de_beneficio():
    r = REGIMES["improbidade_principios"]
    assert "benefício" in r.verbatim
    assert any("benefício" in e for e in r.elementos)


def test_lei_anticorrupcao_e_o_unico_regime_objetivo_de_pessoa_juridica():
    r = REGIMES["anticorrupcao_pj"]
    assert r.elemento_subjetivo == "objetiva" and r.sujeito == "pessoa_juridica"


# ───────────────────────── a regra que evita a peça que morre na inicial ──────────────────────

def test_clausula_restritiva_sem_dano_nem_beneficiario_nao_fecha_improbidade():
    """O erro que este módulo existe para impedir."""
    r = o_que_falta("especificacao_dirigida", provas_disponiveis={"conduta", "norma"})
    improb = next(x for x in r["regimes"] if x["regime"] == "improbidade_principios")
    assert improb["fecha"] is False
    assert "beneficiario" in improb["provas_faltantes"]
    assert "dolo" in improb["provas_faltantes"]


def test_o_mesmo_achado_FECHA_no_controle_externo():
    """Não fechar improbidade não significa nada a fazer — muda a peça, não o achado."""
    r = o_que_falta("especificacao_dirigida", provas_disponiveis={"conduta", "norma"})
    ce = next(x for x in r["regimes"] if x["regime"] == "controle_externo")
    assert ce["fecha"] is True
    assert r["algum_fecha"] is True


def test_com_beneficiario_e_dolo_a_improbidade_passa_a_fechar():
    r = o_que_falta("especificacao_dirigida",
                    provas_disponiveis={"conduta", "norma", "beneficiario", "dolo"})
    improb = next(x for x in r["regimes"] if x["regime"] == "improbidade_principios")
    assert improb["fecha"] is True


def test_fracionamento_sem_sobrepreco_nao_fecha_o_art_10():
    """Art. 10, VIII exige perda patrimonial efetiva — burla ao art. 75, sozinha, não basta."""
    r = o_que_falta("fracionamento_despesa", provas_disponiveis={"conduta", "norma", "dolo"})
    dano = next(x for x in r["regimes"] if x["regime"] == "improbidade_dano")
    assert dano["fecha"] is False and "dano" in dano["provas_faltantes"]


def test_cartel_fecha_pela_lei_12846_sem_precisar_de_dolo_de_agente():
    """A via mais direta contra cartel dispensa provar dolo de agente público."""
    r = o_que_falta("cartel_rodizio", provas_disponiveis={"ato_lesivo"})
    pj = next(x for x in r["regimes"] if x["regime"] == "anticorrupcao_pj")
    assert pj["fecha"] is True
    improb = next(x for x in r["regimes"] if x["regime"] == "improbidade_principios")
    assert improb["fecha"] is False


def test_jogo_de_planilha_registra_que_independe_de_dolo_no_TCU():
    e = enquadrar("jogo_planilha")
    assert "INDEPENDE" in e.nota or "independe" in e.nota


# ───────────────────────── ordenação e ressalva ───────────────────────────────────────────────

def test_regimes_saem_do_mais_proximo_de_fechar_para_o_mais_distante():
    r = o_que_falta("fracionamento_despesa", provas_disponiveis={"conduta", "norma"})
    faltas = [len(x["provas_faltantes"]) for x in r["regimes"]]
    assert faltas == sorted(faltas)


def test_saida_traz_a_ressalva_de_que_nao_tipifica():
    r = o_que_falta("especificacao_dirigida")
    assert "hipot" in r["ressalva"].lower()
    assert "17-C" in r["ressalva"], "a ressalva deve ancorar em que os elementos não se presumem"


def test_lacunas_saem_descritas_em_portugues_util():
    """O checklist vira pedido de diligência — 'dolo' sozinho não orienta ninguém."""
    r = o_que_falta("fracionamento_despesa", provas_disponiveis=set())
    dano = next(x for x in r["regimes"] if x["regime"] == "improbidade_dano")
    assert any(len(d) > 30 for d in dano["faltam_descrito"])
    assert all(p in PROVAS for p in dano["provas_faltantes"])


def test_vicio_nao_mapeado_declara_a_lacuna():
    r = o_que_falta("vicio_que_nao_existe")
    assert r["mapeado"] is False and not r["regimes"]
    assert "lacuna declarada" in r["nota"]


def test_regime_desconhecido_devolve_none():
    assert regime("inexistente") is None
    assert enquadrar("") is None


def test_todo_enquadramento_inclui_controle_externo():
    """Sempre há o que fazer no Tribunal de Contas, mesmo quando a improbidade não fecha."""
    sem = [v for v, e in ENQUADRAMENTOS.items() if "controle_externo" not in e.regimes]
    assert not sem, f"vícios sem via de controle externo: {sem}"
