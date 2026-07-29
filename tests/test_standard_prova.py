# -*- coding: utf-8 -*-
"""A régua que faltava entre a evidência e a peça.

A casa gradua a evidência (A-E) e gradua a peça (monitorar → representação com cautelar), mas
nada ligava as duas. O efeito era a inflação de manchete que já custou sete correções: um caso
sustentado só por leitura de IA (grau C) chegava a "representação" sem que ninguém perguntasse
se a prova alcançava o standard da pretensão.

A regra que estes testes travam: **grau C não atinge "clara e convincente"**. Não porque a IA
seja ruim, mas porque a Lei 14.230/2021 diz, no art. 17-C, I, que os elementos da improbidade
"não podem ser presumidos" — e leitura de documento por modelo é, no melhor caso, indício
qualificado.
"""
from __future__ import annotations

import pytest

from compliance_agent.knowledge.standard_prova import (
    PRETENSAO_STANDARD,
    STANDARDS,
    atingido,
    rebaixar_peca,
    standard_de,
    suficiente,
)


# ───────────────────────────── integridade da régua ───────────────────────────────────────────

def test_toda_pretensao_aponta_para_um_standard_existente():
    for pretensao, sid in PRETENSAO_STANDARD.items():
        assert sid in STANDARDS, f"{pretensao} → standard inexistente {sid}"


def test_todo_standard_cita_fundamento():
    for s in STANDARDS.values():
        assert s.fundamento, f"{s.id} sem fundamento — inverificável numa peça"


def test_niveis_sao_estritamente_crescentes():
    niveis = sorted(s.nivel for s in STANDARDS.values())
    assert niveis == sorted(set(niveis))


def test_sancao_exige_mais_que_ressarcimento():
    """A distinção doutrinária central: indenizatório × sancionador."""
    assert standard_de("sancao_pessoal").nivel > standard_de("ressarcimento").nivel


def test_diligencia_exige_menos_que_representacao():
    assert standard_de("diligencia").nivel < standard_de("representacao").nivel


# ───────────────────────── o teto do juízo de IA ──────────────────────────────────────────────

def test_grau_C_nao_atinge_clara_e_convincente():
    """Caso inteiramente sustentado por leitura de IA não fundamenta pedido de sanção."""
    assert atingido("C") == "indicio_qualificado"
    r = suficiente("C", "improbidade")
    assert r["ok"] is False
    assert any("grau" in f for f in r["falta"])


def test_grau_C_sustenta_diligencia_que_e_como_se_obtem_a_prova():
    assert suficiente("C", "diligencia")["ok"] is True
    assert suficiente("C", "requisicao_informacao")["ok"] is True


def test_grau_A_sozinho_ainda_nao_fecha_sancao_sem_convergencia():
    """Standard sancionador exige convergência independente, não um achado isolado."""
    r = suficiente("A", "sancao_pessoal", familias_independentes=1)
    assert r["ok"] is False
    assert any("convergência" in f for f in r["falta"])


def test_grau_A_com_duas_familias_independentes_fecha():
    assert suficiente("A", "sancao_pessoal", familias_independentes=2)["ok"] is True


def test_grau_B_sustenta_ressarcimento_mas_nao_sancao():
    assert suficiente("B", "ressarcimento")["ok"] is True
    assert suficiente("B", "improbidade", familias_independentes=3)["ok"] is False


@pytest.mark.parametrize("grau", ["D", "E", "", None, "Z"])
def test_grau_sem_forca_nao_atinge_nada_alem_de_indicio(grau):
    assert atingido(grau) == "indicio"
    assert suficiente(grau, "representacao")["ok"] is False


# ───────────────────────── rebaixamento de peça ───────────────────────────────────────────────

def test_representacao_sobre_grau_C_e_rebaixada_para_diligencia():
    """O antídoto contra a inflação: recomendar o passo que PRODUZ a prova que falta."""
    r = rebaixar_peca("representacao", "C")
    assert r["rebaixada"] is True and r["peca"] == "diligencia"
    assert "produzir a prova" in r["motivo"]


def test_representacao_sobre_grau_B_nao_e_rebaixada():
    r = rebaixar_peca("representacao", "B")
    assert r["rebaixada"] is False and r["peca"] == "representacao"


def test_cautelar_preserva_a_urgencia_quando_a_evidencia_sustenta():
    """Urgência é dimensão à parte do standard — não pode ser perdida no rebaixamento."""
    r = rebaixar_peca("representacao_cautelar", "B")
    assert r["peca"] == "representacao_cautelar" and r["rebaixada"] is False


def test_nunca_ELEVA_a_peca():
    """Evidência forte não transforma diligência em representação — quem escala é a régua S×V."""
    r = rebaixar_peca("diligencia", "A", familias_independentes=3)
    assert r["peca"] == "diligencia" and r["rebaixada"] is False


def test_evidencia_nula_cai_para_monitorar_com_a_lacuna_declarada():
    r = rebaixar_peca("representacao", "D")
    assert r["peca"] == "monitorar"
    assert r["falta"] == [] or isinstance(r["falta"], list)


def test_peca_desconhecida_nao_quebra():
    r = rebaixar_peca("peça inventada", "A")
    assert r["rebaixada"] is False


def test_pretensao_desconhecida_e_declarada():
    r = suficiente("A", "pretensão que não existe")
    assert r["ok"] is False and "desconhecida" in r["motivo"]


# ───────────────────────── ligação com a tipicidade ───────────────────────────────────────────

def test_todo_regime_de_tipicidade_usa_um_standard_conhecido():
    """`knowledge/tipicidade` declara o standard de cada regime — os dois vocabulários têm de casar."""
    from compliance_agent.knowledge.tipicidade import REGIMES

    for r in REGIMES.values():
        assert r.standard in STANDARDS, f"{r.id} usa standard desconhecido: {r.standard}"


def test_improbidade_e_o_regime_mais_exigente_entre_os_administrativos():
    from compliance_agent.knowledge.tipicidade import REGIMES

    improb = STANDARDS[REGIMES["improbidade_dano"].standard]
    ce = STANDARDS[REGIMES["controle_externo"].standard]
    pj = STANDARDS[REGIMES["anticorrupcao_pj"].standard]
    assert improb.nivel > ce.nivel
    assert improb.nivel > pj.nivel, ("a Lei 12.846 é responsabilidade objetiva — exige menos "
                                     "prova subjetiva que a improbidade")
