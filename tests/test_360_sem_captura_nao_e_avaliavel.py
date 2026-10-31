# -*- coding: utf-8 -*-
"""Processo sem captura íntegra não recebe faixa de risco — INDISPONÍVEL ≠ irregular.

Medido em 2026-08-03: **199 processos do acervo têm ZERO caractere capturado** e, ainda assim,
25 deles carregavam score >= 70; o pior estava gravado como 89,0 EXTREMO. Reavaliando um deles
depois das correções de fase/natureza, o resultado ainda saía como
`status: OK · faixa: MEDIO · grau: C FLAG SUSPEITO` — um rótulo de suspeita sobre um processo do
qual a casa não leu uma única letra.

O 360 já MEDE a integridade da captura (`manifesto_norm.captura_integra`) e já separa
`lacunas_captura` de `lacunas_processo`. O que faltava era a consequência: sem captura íntegra,
o veredito de risco não se emite — declara-se `NAO_AVALIAVEL`. O score continua calculado (serve
para ordenar o trabalho de recaptura), mas não vira faixa nem grau, que são o que o entregável
mostra e o que a fila do fiscal ordena.
"""
from compliance_agent import processo_360 as P


def test_faixa_de_processo_sem_captura_e_declarada_nao_avaliavel():
    assert P.faixa_com_captura(48.0, integra=False) == "NAO_AVALIAVEL"
    assert P.faixa_com_captura(89.0, integra=False) == "NAO_AVALIAVEL"


def test_captura_integra_mantem_a_faixa_normal():
    assert P.faixa_com_captura(89.0, integra=True) == "EXTREMO"
    assert P.faixa_com_captura(48.0, integra=True) == "MEDIO"
    assert P.faixa_com_captura(10.0, integra=True) == "BAIXO"


def test_grau_de_processo_sem_captura_nao_afirma_suspeita():
    g = P.grau_com_captura({"grau": "C", "rotulo": "FLAG SUSPEITO", "emoji": "🟡",
                            "pode_fundamentar_peca": False, "motivo": "x"}, integra=False)
    assert g["grau"] == "-"
    assert "SUSPEITO" not in g["rotulo"].upper()
    assert g["pode_fundamentar_peca"] is False
    assert "captur" in g["motivo"].lower()


def test_grau_com_captura_integra_passa_intacto():
    orig = {"grau": "B", "rotulo": "INDÍCIO", "emoji": "🟠", "pode_fundamentar_peca": True,
            "motivo": "convergência"}
    assert P.grau_com_captura(orig, integra=True) == orig


def test_o_score_continua_existindo_para_ordenar_a_recaptura():
    """Zerar o score esconderia quais processos vale a pena recapturar primeiro."""
    assert P.faixa_com_captura(0.0, integra=False) == "NAO_AVALIAVEL"
