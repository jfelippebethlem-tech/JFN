# -*- coding: utf-8 -*-
"""Núcleo PURO da concentração por grupo econômico (sem DB): union-find por sócio + métrica."""
from compliance_agent.grafo_cartel import _uniao_por_socio, _metrica_grupos


def test_uniao_por_socio_liga_cnpjs_de_raizes_distintas_com_socio_comum():
    # A (raiz 11111111) e B (raiz 22222222) partilham "joao"; C (raiz 33333333) isolado.
    cnpjs = ["11111111000101", "22222222000102", "33333333000103"]
    socios = {
        "11111111000101": {"joao silva"},
        "22222222000102": {"joao silva", "maria"},
        "33333333000103": {"pedro"},
    }
    gid = _uniao_por_socio(cnpjs, socios)
    assert gid["11111111000101"] == gid["22222222000102"]  # mesmo grupo
    assert gid["33333333000103"] != gid["11111111000101"]  # grupo separado
    assert gid["11111111000101"] == "11111111"             # id = menor raiz (determinístico)


def test_matriz_filial_mesma_raiz_caem_no_mesmo_grupo_sem_socio():
    cnpjs = ["44444444000101", "44444444000288"]  # matriz + filial, mesma raiz
    gid = _uniao_por_socio(cnpjs, {})
    assert gid["44444444000101"] == gid["44444444000288"] == "44444444"


def test_metrica_grupos_colapsa_diversidade_ficticia():
    # 3 CNPJs do mesmo grupo (R$ 90 somados) + 1 concorrente real (R$ 10).
    totais = {"11111111000101": 30.0, "22222222000102": 30.0, "55555555000105": 30.0,
              "99999999000109": 10.0}
    nomes = {c: f"Empresa {c[:8]}" for c in totais}
    gid = {"11111111000101": "11111111", "22222222000102": "11111111",
           "55555555000105": "11111111", "99999999000109": "99999999"}
    m = _metrica_grupos(totais, nomes, gid)
    assert m["n_cnpjs"] == 4
    assert m["n_grupos"] == 2                       # 4 CNPJs colapsam em 2 grupos
    assert m["n_grupos_multi"] == 1
    assert m["maior_grupo_multi"]["n_cnpjs"] == 3
    assert m["maior_grupo_multi"]["share"] == 90.0  # grupo domina 90% apesar de "4 concorrentes"
    # concentração por grupo (90/10) é MAIOR que por CNPJ (30/30/30/10) → diversidade fictícia
    assert m["hhi_grupo"] > m["hhi_cnpj"]
    assert m["delta_hhi"] > 0


def test_metrica_sem_grupo_multi_nao_aponta_diversidade_ficticia():
    totais = {"11111111000101": 50.0, "99999999000109": 50.0}
    nomes = {c: c for c in totais}
    gid = {"11111111000101": "11111111", "99999999000109": "99999999"}
    m = _metrica_grupos(totais, nomes, gid)
    assert m["n_grupos_multi"] == 0
    assert m["maior_grupo_multi"] is None
    assert m["hhi_grupo"] == m["hhi_cnpj"]  # nenhum colapso → idêntico
