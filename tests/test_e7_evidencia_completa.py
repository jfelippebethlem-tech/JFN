# -*- coding: utf-8 -*-
"""A cláusula chegava ao fiscal partida no meio da frase.

A tabela `edital_clausula` guarda o trecho já cortado na ingestão — mediana de **91 caracteres**,
e `trecho_fonte` traz exatamente o mesmo. Resultado nos 13 disparos do E7 medidos em 2026-08-04:

    "9.3.2 Prova de possuir no seu quadro permanente, na data da Concorrência, profissional ou"
    "Liquidez Geral (ILG) igual ou maior do que 1 (um), apurado nas demonstrações financeiras do"
    "pontuação das propostas técnicas, a metodologia de trabalho não foi"

Com meia cláusula não se decide nada — e a parte que sustenta a restrição ("profissionais de nível
superior detentores de atestado de responsabilidade técnica") ficava justamente do lado cortado.

O texto integral do edital JÁ ESTAVA no contexto (`tr_texto`). Basta relocalizar a cláusula nele.
"""
from compliance_agent.detectores.e7_clausula_restritiva import _trecho_completo

_EDITAL = ("Capítulo 9. 9.3 QUALIFICAÇÃO TÉCNICA. 9.3.2 Prova de possuir no seu quadro "
           "permanente, na data da Concorrência, profissional ou profissionais de nível superior "
           "detentores de atestado de responsabilidade técnica por execução de obra similar. "
           "9.4 Da qualificação econômico-financeira.")
_CLAUSULA = ("9.3.2 Prova de possuir no seu quadro permanente, na data da Concorrência, "
             "profissional ou")


def test_a_clausula_e_recortada_do_EDITAL_e_fica_inteira():
    t = _trecho_completo(_CLAUSULA, _EDITAL)
    assert "detentores de atestado de responsabilidade técnica" in t, (
        "a parte que sustenta a restrição continuava do lado cortado")
    assert len(t) > len(_CLAUSULA)


def test_termina_em_fronteira_de_frase():
    t = _trecho_completo(_CLAUSULA, _EDITAL)
    assert t.rstrip().endswith("."), "entregava palavra pela metade"


def test_sem_o_edital_devolve_o_que_havia_nunca_menos():
    """Contexto sem `tr_texto` não pode piorar a evidência."""
    assert _trecho_completo(_CLAUSULA, None) == _CLAUSULA


def test_clausula_que_nao_se_acha_no_edital_nao_inventa():
    """Se o literal não está no edital do contexto, devolve o literal do banco — jamais um trecho
    de outro lugar do documento."""
    t = _trecho_completo("cláusula que não existe neste edital", _EDITAL)
    assert t == "cláusula que não existe neste edital"


def test_clausula_vazia_nao_levanta():
    assert _trecho_completo("", _EDITAL) == ""
    assert _trecho_completo("   ", None) == ""
