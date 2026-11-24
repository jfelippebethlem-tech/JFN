# -*- coding: utf-8 -*-
"""O4.13 — `dominio.identidade`: identidade conservadora (plano mestre v2 §4.7 item 7).

CPF com DV válido NUNCA aparece literal aqui (repo público; `tools/scan_pii.py` barra): os completos são GERADOS
em tempo de teste a partir de uma base fictícia; os literais têm DV inválido de propósito.
"""
from __future__ import annotations

import random

import pytest

from compliance_agent.dominio import identidade as I
from compliance_agent.dominio.digitos import cpf_valido


def _cpf_ficticio(base9: str) -> str:
    """Completa 9 dígitos com o DV do módulo 11 (gera CPF válido só em memória)."""
    n = base9
    for tam in (9, 10):
        s = sum(int(n[i]) * (tam + 1 - i) for i in range(tam))
        n += str((s * 10 % 11) % 10)
    assert cpf_valido(n)
    return n


CPF_A = _cpf_ficticio("100200300")
CPF_B = _cpf_ficticio("100200301")
CPF_DV_RUIM = CPF_A[:9] + str((int(CPF_A[9]) + 1) % 10) + CPF_A[10]
CNPJ = "11222333000181"            # CNPJ de exemplo, DV válido (CNPJ é público)
CNPJ_FILIAL_DV_RUIM = "11222333000299"
CNPJ_OUTRO = "99888777000100"     # fictício, DV válido


def _mascara_pad04(cpf: str) -> str:           # ***.456.789-**  (posições 4–9)
    return f"***.{cpf[3:6]}.{cpf[6:9]}-**"


def _mascara_folha(cpf: str) -> str:           # XX345678XXX     (posições 3–8)
    return f"XX{cpf[2:8]}XXX"


NOME = "Maria da Conceição dos Santos"
NOME_VARIANTE = "MARIA CONCEICAO  SANTOS"


CASOS = [
    # (id, a, b, nível esperado)
    ("cnpj_igual", {"cnpj": CNPJ}, {"cnpj": "11.222.333/0001-81"}, "forte"),
    ("cnpj_diferente", {"cnpj": CNPJ}, {"cnpj": CNPJ_OUTRO}, "divergente"),
    ("cnpj_raiz_vs_completo_nome", {"cnpj": "11222333", "nome": "ACME LTDA"}, {"cnpj": CNPJ, "nome": "Acme Ltda."},
     "parcial"),
    ("cnpj_raiz_vs_completo_sem_nome", {"cnpj": "11.222.333"}, {"cnpj": CNPJ}, "indeterminado"),
    ("cnpj_raiz_diferente", {"cnpj": "99888777"}, {"cnpj": CNPJ}, "divergente"),
    ("cnpj_dv_invalido_ignorado", {"cnpj": CNPJ_FILIAL_DV_RUIM, "nome": "ACME"}, {"cnpj": CNPJ, "nome": "ACME"},
     "homonimo"),
    ("cpf_igual", {"cpf": CPF_A}, {"cpf": f"{CPF_A[:3]}.{CPF_A[3:6]}.{CPF_A[6:9]}-{CPF_A[9:]}"}, "forte"),
    ("cpf_diferente", {"cpf": CPF_A, "nome": NOME}, {"cpf": CPF_B, "nome": NOME}, "divergente"),
    ("cpf_dv_invalido_nao_e_forte", {"cpf": CPF_DV_RUIM, "nome": NOME}, {"cpf": CPF_DV_RUIM, "nome": NOME},
     "homonimo"),
    ("mascara_pad04_mais_nome", {"cpf": _mascara_pad04(CPF_A), "nome": NOME},
     {"cpf": _mascara_pad04(CPF_A), "nome": NOME_VARIANTE}, "parcial"),
    ("mascara_folha_mais_nome", {"cpf": _mascara_folha(CPF_A), "nome": NOME},
     {"cpf": _mascara_folha(CPF_A), "nome": NOME}, "parcial"),
    ("mascara_cruzada_mais_nome", {"cpf": _mascara_folha(CPF_A), "nome": NOME},
     {"cpf": _mascara_pad04(CPF_A), "nome": NOME}, "parcial"),
    ("mascara_vs_completo_mais_nome", {"cpf": _mascara_folha(CPF_A), "nome": NOME}, {"cpf": CPF_A, "nome": NOME},
     "parcial"),
    ("mascara_sem_nome", {"cpf": _mascara_folha(CPF_A)}, {"cpf": _mascara_folha(CPF_A)}, "indeterminado"),
    ("mascara_incompativel", {"cpf": "XX111111XXX", "nome": NOME}, {"cpf": "XX222222XXX", "nome": NOME},
     "divergente"),
    ("mascara_nome_diferente", {"cpf": _mascara_folha(CPF_A), "nome": NOME},
     {"cpf": _mascara_folha(CPF_A), "nome": "JOSÉ DA SILVA"}, "indeterminado"),
    ("matricula_orgao", {"matricula": "123.456-7", "orgao": "SEEDUC"}, {"matricula": "123.456-7", "orgao": "seeduc"},
     "forte"),
    ("matricula_sem_orgao", {"matricula": "1234567", "nome": NOME}, {"matricula": "1234567", "nome": NOME},
     "homonimo"),
    ("matricula_orgao_diferente", {"matricula": "1234567", "orgao": "SEEDUC"},
     {"matricula": "1234567", "orgao": "SES"}, "indeterminado"),
    ("nome_mais_nascimento_parcial", {"nome": NOME, "nascimento": "1980"},
     {"nome": NOME_VARIANTE, "data_nascimento": "12/03/1980"}, "probabilistico"),
    ("nome_mais_municipio", {"nome": NOME, "municipio": "Niterói"}, {"nome": NOME, "municipio": "NITEROI"},
     "probabilistico"),
    ("nome_nascimento_conflitante", {"nome": NOME, "nascimento": "1980-03-12"},
     {"nome": NOME, "nascimento": "13/03/1980"}, "homonimo"),
    ("so_nome_acento_preposicao", {"nome": "João de Souza e Silva"}, {"nome": "JOAO SOUZA SILVA"}, "homonimo"),
    ("nada", {}, {}, "indeterminado"),
    ("none", None, None, "indeterminado"),
]


@pytest.mark.parametrize("a,b,esperado", [c[1:] for c in CASOS], ids=[c[0] for c in CASOS])
def test_tabela(a, b, esperado):
    r = I.resolver(a, b)
    assert r.match_level == esperado, r
    assert r.match_level in I.NIVEIS
    assert I.sustenta_grave(r) is (esperado == "forte")
    assert I.resolver(b, a).match_level == esperado          # simétrico


def test_normalizar_nome():
    assert I.normalizar_nome("  Maria   da Conceição DOS Santos ") == "MARIA CONCEICAO SANTOS"
    assert I.normalizar_nome("Ação & Cia. Ltda") == "ACAO CIA LTDA"
    assert I.normalizar_nome(None) == ""


def test_cpf_mascarado():
    assert I.cpf_mascarado("XX123456XXX") and I.cpf_mascarado("***.123.456-**")
    assert not I.cpf_mascarado(CPF_A) and not I.cpf_mascarado("") and not I.cpf_mascarado("XX12")


def test_campos_usados():
    assert I.resolver({"cnpj": CNPJ}, {"cnpj": CNPJ}).campos_usados == ("cnpj",)
    assert I.resolver({"cpf": "XX123456XXX", "nome": "A"}, {"cpf": "XX123456XXX", "nome": "A"}).campos_usados == (
        "cpf", "nome")


@pytest.mark.parametrize("a,b", [({"cpf": CPF_A}, {"cpf": CPF_A}), ({"cpf": CPF_A}, {"cpf": CPF_B}),
                                 ({"cpf": CPF_DV_RUIM, "nome": "X"}, {"cpf": CPF_DV_RUIM, "nome": "X"}),
                                 ({"cpf": CPF_A, "nome": "X"}, {"cpf": _mascara_folha(CPF_A), "nome": "X"})])
def test_nunca_vaza_cpf(a, b):
    r = I.resolver(a, b)
    for txt in (r.motivo, repr(r), str(r)):
        for cpf in (CPF_A, CPF_B, CPF_DV_RUIM):
            assert cpf not in txt and cpf[3:9] not in txt


def test_sustenta_grave_so_resolucao_forte():
    assert not I.sustenta_grave(True) and not I.sustenta_grave(None) and not I.sustenta_grave("forte")
    assert I.sustenta_grave(I.Resolucao("forte", "x"))


def test_propriedade_parcial_nunca_sustenta_grave():
    """Propriedade: em combinações aleatórias de CPF mascarado/nome/município/nascimento, nada que não seja
    `forte` sustenta grave, e todo `parcial` usa CPF mascarado ou raiz de CNPJ — nunca documento completo igual."""
    rnd = random.Random(20261124)
    nomes = [NOME, NOME_VARIANTE, "JOSE DA SILVA", ""]
    cpfs = [_mascara_folha(CPF_A), _mascara_pad04(CPF_A), _mascara_folha(CPF_B), CPF_DV_RUIM, "", "XX000000XXX"]
    extras = [{}, {"municipio": "Niterói"}, {"nascimento": "1980"}, {"matricula": "1"}]
    vistos = set()
    for _ in range(600):
        a = {"cpf": rnd.choice(cpfs), "nome": rnd.choice(nomes), **rnd.choice(extras)}
        b = {"cpf": rnd.choice(cpfs), "nome": rnd.choice(nomes), **rnd.choice(extras)}
        r = I.resolver(a, b)
        vistos.add(r.match_level)
        assert r.match_level != "forte"
        assert not I.sustenta_grave(r)
    assert {"parcial", "homonimo", "divergente", "indeterminado", "probabilistico"} <= vistos
    for nivel in ("parcial", "probabilistico", "homonimo", "divergente", "indeterminado"):
        assert not I.sustenta_grave(I.Resolucao(nivel, ""))
