# -*- coding: utf-8 -*-
"""Detector determinístico de empresa fantasma/fachada (sem LLM).

Cada sinal é uma função pura sobre um 'perfil' (dict montado do banco). O score
agrega indícios com pesos; NENHUM sinal isolado 'condena' — é triagem, não prova
(indício ≠ acusação). Testes com perfis sintéticos ancorados nos dados reais.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compliance_agent.empresa_fantasma import avaliar_perfil, RISCOS


def _perfil(**kw):
    base = dict(cnpj="11222333000181", razao_social="X LTDA", situacao="ATIVA",
                capital_social=100_000.0, data_abertura="2015-01-01",
                cnae="Construção de edifícios", total_recebido=500_000.0,
                primeira_ob="2020-01-01", n_socios=2, endereco_norm="RUAX100",
                empresas_no_endereco=1, sancionada=False, objeto_pago="")
    base.update(kw)
    return base


def test_empresa_sadia_nao_dispara():
    r = avaliar_perfil(_perfil())
    assert r["score"] == 0 and r["sinais"] == []


def test_situacao_irregular_e_forte():
    r = avaliar_perfil(_perfil(situacao="BAIXADA"))
    assert "situacao_irregular" in {s["id"] for s in r["sinais"]}
    assert r["score"] >= 30


def test_capital_infimo_vs_recebido():
    r = avaliar_perfil(_perfil(capital_social=100.0, total_recebido=5_000_000.0))
    ids = {s["id"] for s in r["sinais"]}
    assert "capital_incompativel" in ids


def test_capital_proporcional_nao_dispara():
    r = avaliar_perfil(_perfil(capital_social=1_000_000.0, total_recebido=2_000_000.0))
    assert "capital_incompativel" not in {s["id"] for s in r["sinais"]}


def test_endereco_compartilhado_por_muitas():
    r = avaliar_perfil(_perfil(empresas_no_endereco=25))
    assert "endereco_compartilhado" in {s["id"] for s in r["sinais"]}


def test_recem_aberta_antes_de_contrato():
    r = avaliar_perfil(_perfil(data_abertura="2020-01-01", primeira_ob="2020-04-01",
                               total_recebido=3_000_000.0))
    assert "aberta_as_vesperas" in {s["id"] for s in r["sinais"]}


def test_socio_unico_capital_baixo():
    r = avaliar_perfil(_perfil(n_socios=1, capital_social=1_000.0))
    assert "socio_unico_capital_baixo" in {s["id"] for s in r["sinais"]}


def test_cnae_incompativel_com_objeto():
    r = avaliar_perfil(_perfil(cnae="Comércio varejista de roupas",
                               objeto_pago="obras de reforma predial e construção"))
    assert "cnae_incompativel" in {s["id"] for s in r["sinais"]}


def test_cnae_aderente_nao_dispara():
    r = avaliar_perfil(_perfil(cnae="Construção de edifícios",
                               objeto_pago="reforma e construção do prédio"))
    assert "cnae_incompativel" not in {s["id"] for s in r["sinais"]}


def test_multiplos_sinais_elevam_para_alto():
    r = avaliar_perfil(_perfil(situacao="INAPTA", capital_social=100.0,
                               total_recebido=10_000_000.0, empresas_no_endereco=30,
                               n_socios=1, sancionada=True))
    assert r["classificacao"] == "alto"
    assert r["score"] >= 70


def test_faixas_de_risco_definidas():
    assert set(RISCOS) == {"baixo", "medio", "alto"}


def test_sem_fins_lucrativos_capital_infimo_e_sinal_fraco():
    # OS/associação com capital baixo NÃO deve pesar como fantasma (falso+)
    com = avaliar_perfil(_perfil(razao_social="INSTITUTO X", capital_social=100.0,
                                 total_recebido=5_000_000.0, n_socios=1))
    sem = avaliar_perfil(_perfil(razao_social="EMPRESA Y LTDA", capital_social=100.0,
                                 total_recebido=5_000_000.0, n_socios=1))
    assert com["score"] < sem["score"]
    assert "socio_unico_capital_baixo" not in {s["id"] for s in com["sinais"]}


def test_indisponivel_nao_inventa():
    # sem capital nem total → não pode afirmar incompatibilidade (INDISPONÍVEL≠0)
    r = avaliar_perfil(_perfil(capital_social=None, total_recebido=None))
    assert "capital_incompativel" not in {s["id"] for s in r["sinais"]}
