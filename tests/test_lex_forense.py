# -*- coding: utf-8 -*-
"""Testes do lex_forense — análise forense quantitativa (determinística, sem rede)."""
from compliance_agent import lex_forense as F


def _linhas(valores, datas=None, orgaos=None):
    datas = datas or ["2024-05-10"] * len(valores)
    orgaos = orgaos or ["ORGAO A"] * len(valores)
    return [{"valor": v, "data": d, "orgao": o} for v, d, o in zip(valores, datas, orgaos)]


def test_benford_amostra_insuficiente_declara_e_nao_calcula():
    r = F.benford([123.45] * 50)
    assert r["ok"] is False and "insuficiente" in r["motivo"]


def test_benford_serie_conforme_aprovada():
    # série sintética seguindo Benford exatamente (frequência proporcional a log10(1+1/d))
    vals = []
    for d in range(1, 10):
        vals += [float(f"{d}23.45")] * round(F._BENFORD_ESPERADO[d] * 1000)
    r = F.benford(vals)
    assert r["ok"] and r["mad"] <= 0.006 and r["rotulo"] == "conformidade próxima"


def test_benford_serie_distorcida_reprova():
    r = F.benford([900.0] * 200 + [100.0] * 20)  # dígito 9 estufado
    assert r["ok"] and r["mad"] > 0.015 and r["rotulo"].startswith("NÃO")
    assert r["pior_digito"] == 9


def test_redondos_conta_milhar_exato():
    r = F.redondos([1000.0, 2000.0, 1234.56, 5100.0])
    assert r["ok"] and r["n"] == 4 and abs(r["pct_mil"] - 50.0) < 0.01
    assert abs(r["pct_cem"] - 75.0) < 0.01


def test_sazonalidade_agrega_ano_mes():
    m = F.sazonalidade(_linhas([100.0, 200.0, 300.0],
                               ["2024-01-05", "2024-01-20", "2024-12-01"]))
    assert m[2024][1] == 300.0 and m[2024][12] == 300.0


def test_cadencia_por_orgao_ordena_por_total():
    cad = F.cadencia_por_orgao(_linhas([10.0, 999.0, 5.0],
                                       ["2024-01-01", "2024-02-01", "2024-03-01"],
                                       ["A", "B", "A"]))
    assert cad[0]["orgao"] == "B" and cad[0]["maior"] == 999.0
    assert cad[1]["n"] == 2 and cad[1]["meses_ativos"] == 2


def test_rastreabilidade_mede_cobertura_e_sombra():
    r = F.rastreabilidade([{"n_obs": 2, "total": 500.0}],
                          {"n_geral": 10, "total_geral": 2000.0})
    assert r["ok"] and abs(r["pct_n"] - 20.0) < 0.01 and abs(r["pct_v"] - 25.0) < 0.01
    assert abs(r["descoberto_v"] - 1500.0) < 0.01


def test_linha_do_tempo_ordena_eventos():
    ev = F.linha_do_tempo({"data_abertura": "2020-01-01",
                           "socios": [{"nome": "FULANO", "entrada": "2023-06-01"}]},
                          _linhas([50.0, 900.0], ["2022-03-01", "2024-04-04"]), [])
    datas = [d for d, _ in ev]
    assert datas == sorted(datas) and datas[0] == "2020-01-01"
    assert any("Maior OB" in e for _, e in ev)


def test_cenarios_usa_defesa_do_exculpatorio_e_discriminante_por_rf():
    cs = F.cenarios([{"rf": "R8", "grav": 3}, {"rf": "DD/H-X", "grav": 4}],
                    [{"rf": "R8", "defesa": "mercado concentrado legítimo", "sobrevive": True}])
    por_rf = {c["rf"]: c for c in cs}
    assert por_rf["R8"]["benigno"] == "mercado concentrado legítimo" and por_rf["R8"]["sobrevive"]
    assert "atas" in por_rf["R8"]["teste"]
    assert "sede" in por_rf["DD/H-X"]["teste"]


def test_secao_forense_vazia_sem_pagamentos():
    assert F.secao_forense_md({"pagamentos": {}}, {}) == ""
