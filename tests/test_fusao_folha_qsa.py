# -*- coding: utf-8 -*-
"""A máscara da folha expõe as MESMAS posições do QSA — a fusão prometia um dígito que não existe.

`folha_middle` documentava que a folha do Rio mascara o CPF expondo as **posições 3-8**, contra as
**4-9** do QSA, e `fusao_folha_qsa` usava essa diferença para (a) afirmar que o sócio é servidor e
(b) estreitar os candidatos de 1.000 para ~100 (sete dígitos conhecidos, posições 3-9).

CONTROLE POSITIVO (2026-08-12), com os 117 sócios cujo CPF COMPLETO já estava resolvido e cujo nome
consta na folha:

    máscara da folha = posições 3-8 ......  3
    máscara da folha = posições 4-9 ...... 94   ← o que o dado mostra
    nenhuma das duas (homônimo real) ..... 20

A premissa estava errada. E a consequência era pior que "não ganhar dígito": a comparação
`m6_qsa[0:5] == m_folha[1:6]` confrontava as posições **4-8 contra 5-9** — um deslocamento de um
dígito. Resultado no acervo: de 1.014 nomes de sócios presentes na folha, **1.007 eram declarados
"homônimos"** e os 7 restantes, marcados como servidores, casavam por coincidência.

Com a janela certa a fusão continua valendo — só que como ANTI-HOMÔNIMO, não como estreitamento:
nome igual + os seis dígitos iguais é a mesma régua que o cruzamento de benefício chama de ALTA.
E `n_candidatos` continua 1.000, porque não há dígito novo: prometer 100 seria mentir sobre o
esforço que falta.
"""
from __future__ import annotations

from compliance_agent.resolucao_cpf import fusao_folha_qsa


def _idx(nome_norm: str, *middles: str) -> dict:
    return {nome_norm: set(middles)}


def test_seis_digitos_iguais_confirmam_a_pessoa():
    r = fusao_folha_qsa("MARIA DA SILVA SANTOS", "***123456**",
                        _idx("MARIA DA SILVA SANTOS", "123456"))
    assert r["servidor"] is True
    assert "123456" in r["conhecidos_3a9"] or r["conhecidos_3a9"] == "123456"


def test_nao_promete_estreitar_o_que_nao_estreitou():
    """Mesma janela nos dois lados = zero dígito novo. `n_candidatos` continua 1.000."""
    r = fusao_folha_qsa("MARIA DA SILVA SANTOS", "***123456**",
                        _idx("MARIA DA SILVA SANTOS", "123456"))
    assert r["n_candidatos"] == 1000


def test_digitos_diferentes_sao_homonimo():
    r = fusao_folha_qsa("JOAO PEREIRA COSTA", "***123456**",
                        _idx("JOAO PEREIRA COSTA", "999999"))
    assert r["servidor"] is False
    assert "hom" in r["motivo"].lower()


def test_deslocamento_de_um_digito_NAO_confirma():
    """O bug antigo: `123456` do QSA casava com `X12345` da folha. Não pode voltar."""
    r = fusao_folha_qsa("ANA MARIA DE SOUZA", "***123456**",
                        _idx("ANA MARIA DE SOUZA", "912345"))
    assert r["servidor"] is False


def test_nome_fora_da_folha_nao_afirma_nada():
    r = fusao_folha_qsa("PESSOA QUE NAO E SERVIDORA", "***123456**", _idx("OUTRA PESSOA", "123456"))
    assert r["servidor"] is False
    assert "folha" in r["motivo"].lower()


def test_sem_mascara_no_qsa_degrada_honesto():
    r = fusao_folha_qsa("MARIA DA SILVA SANTOS", "", _idx("MARIA DA SILVA SANTOS", "123456"))
    assert r["servidor"] is False
