# -*- coding: utf-8 -*-
"""Screens de participação — e o cuidado estatístico sem o qual eles medem vizinhança de mercado.

`cruzamentos_intel.perdedoras_contumazes` já responde à pergunta, mas sobre as atas extraídas do
SEI, que são poucas. Com `tcerj_licitante`, a mesma leitura passa a ter milhares de certames
municipais com vencedor E perdedores nominados.

A decisão que define este módulo: **co-ocorrência bruta não significa nada**. Duas empresas do
mesmo ramo, no mesmo município, vão se encontrar — e ranquear por co-ocorrência colocaria no topo
justamente as empresas grandes, que aparecem em tudo. A medida certa é o LIFT: quanto o observado
supera o esperado se as participações fossem independentes.

E a segunda: **concentração sem alternância é monopólio, não rodízio**. Confundir os dois
transforma fornecedor único legítimo em suspeito.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.editais.screens_participacao import (
    normalizar_nome,
    pares_cobertura,
    perdedoras_contumazes,
    rodizio,
)


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE tcerj_licitante (
        ente TEXT, ano INTEGER, mes INTEGER, processo TEXT, participante TEXT, resultado TEXT,
        tipo_participacao TEXT, data_homologacao TEXT, modalidade TEXT, objeto TEXT,
        qtd_participantes INTEGER, valor_homologacao REAL, valor_estimado REAL,
        tipologia TEXT, coletado_em TEXT)""")
    return c


def _certame(con, processo, vencedor, perdedores, *, ente="MUN", tipologia="OUTRAS COMPRAS"):
    linhas = [(ente, 2024, 1, processo, vencedor, "VENCEDOR", "COMUM", "", "PREGÃO", "obj",
               len(perdedores) + 1, 100.0, 120.0, tipologia, "")]
    linhas += [(ente, 2024, 1, processo, p, "PERDEDOR", "COMUM", "", "PREGÃO", "obj",
                len(perdedores) + 1, 100.0, 120.0, tipologia, "") for p in perdedores]
    con.executemany("INSERT INTO tcerj_licitante VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", linhas)
    con.commit()


# ───────────────────────── normalização ───────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("ALFA COMERCIO LTDA", "Alfa Comércio Ltda."),
    ("BETA SERVICOS EIRELI", "BETA SERVIÇOS - EIRELI"),
    ("GAMA S/A", "Gama S.A."),
])
def test_variacoes_de_grafia_colapsam(a, b):
    assert normalizar_nome(a) == normalizar_nome(b)


def test_empresas_diferentes_nao_colapsam():
    assert normalizar_nome("ALFA LTDA") != normalizar_nome("BETA LTDA")


# ───────────────────────── perdedora contumaz ─────────────────────────────────────────────────

def test_quem_participa_muito_e_nunca_vence_aparece(con):
    for i in range(6):
        _certame(con, f"p{i}", "ALFA", ["BETA"])
    r = perdedoras_contumazes(con)
    nomes = {a["participante"] for a in r["achados"]}
    assert "BETA" in nomes and "ALFA" not in nomes


def test_quem_vence_alguma_vez_nao_e_contumaz(con):
    for i in range(6):
        _certame(con, f"p{i}", "ALFA", ["BETA"])
    _certame(con, "p9", "BETA", ["ALFA"])
    assert not [a for a in perdedoras_contumazes(con)["achados"] if a["participante"] == "BETA"]


def test_o_screen_declara_que_e_FRACO_sozinho(con):
    for i in range(6):
        _certame(con, f"p{i}", "ALFA", ["BETA"])
    r = perdedoras_contumazes(con)
    assert r["nivel"] == "fraco"
    assert "funcionamento normal do mercado" in r["motivo"]


def test_amostra_pequena_nao_produz_achado(con):
    _certame(con, "p1", "ALFA", ["BETA"])
    assert perdedoras_contumazes(con)["achados"] == []


# ───────────────────────── par de cobertura (LIFT) ────────────────────────────────────────────

def test_par_que_se_encontra_muito_acima_do_acaso(con):
    for i in range(6):
        _certame(con, f"p{i}", "ALFA", ["BETA"])
    for i in range(6, 20):                       # ruído: outros certames sem o par
        _certame(con, f"p{i}", f"EMP{i}", [f"OUTRA{i}"])
    r = pares_cobertura(con)
    assert r["achados"] and r["achados"][0]["vencedor"] == "ALFA"
    assert r["achados"][0]["perdedor"] == "BETA"
    assert r["achados"][0]["lift"] >= 3.0


def test_empresa_grande_que_aparece_em_tudo_NAO_sobe_por_co_ocorrencia_bruta():
    """O ponto do lift: co-ocorrência bruta ranquearia a onipresente no topo."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE tcerj_licitante (
        ente TEXT, ano INTEGER, mes INTEGER, processo TEXT, participante TEXT, resultado TEXT,
        tipo_participacao TEXT, data_homologacao TEXT, modalidade TEXT, objeto TEXT,
        qtd_participantes INTEGER, valor_homologacao REAL, valor_estimado REAL,
        tipologia TEXT, coletado_em TEXT)""")
    # GRANDE participa de TODOS os 30 certames; ONIPRESENTE perde em todos.
    for i in range(30):
        _certame(c, f"g{i}", "GRANDE", ["ONIPRESENTE", f"EMP{i}"])
    # O par ALFA×BETA aparece em 5 de 30, mas ambos só participam desses 5.
    for i in range(5):
        _certame(c, f"a{i}", "ALFA", ["BETA"])
    r = pares_cobertura(c)
    topo = r["achados"][0]
    assert (topo["vencedor"], topo["perdedor"]) == ("ALFA", "BETA"), (
        f"o par onipresente subiu ao topo: {topo}")


def test_lift_alto_sobre_poucos_encontros_e_ruido_e_fica_de_fora(con):
    _certame(con, "p1", "ALFA", ["BETA"])
    _certame(con, "p2", "ALFA", ["BETA"])
    for i in range(20):
        _certame(con, f"o{i}", f"E{i}", [f"P{i}"])
    assert not [a for a in pares_cobertura(con)["achados"]
                if a["vencedor"] == "ALFA" and a["perdedor"] == "BETA"]


def test_o_texto_do_achado_mostra_observado_e_esperado(con):
    for i in range(6):
        _certame(con, f"p{i}", "ALFA", ["BETA"])
    for i in range(6, 20):
        _certame(con, f"p{i}", f"EMP{i}", [f"OUTRA{i}"])
    t = pares_cobertura(con)["achados"][0]["texto"]
    assert "o acaso explicaria" in t and "lift" in t


# ───────────────────────── rodízio × concentração ─────────────────────────────────────────────

def test_alternancia_entre_poucos_nomes_e_RODIZIO(con):
    for i in range(12):
        _certame(con, f"p{i}", "ALFA" if i % 2 == 0 else "BETA", ["OUTRA"])
    r = rodizio(con)
    assert r["n_rodizio"] >= 1
    a = next(x for x in r["achados"] if x["classe"] == "rodizio")
    assert a["vencedores_distintos"] == 2 and a["alternancia"] >= 0.9


def test_vencedor_unico_e_CONCENTRACAO_nao_rodizio(con):
    """Confundir os dois transforma fornecedor único legítimo em suspeito."""
    for i in range(12):
        _certame(con, f"p{i}", "ALFA", ["OUTRA"])
    r = rodizio(con)
    a = next(x for x in r["achados"] if x["ente"] == "MUN")
    assert a["classe"] == "concentracao" and a["nivel"] == "fraco"
    assert "outro problema e outra peça" in a["texto"]


def test_mercado_disperso_nao_aparece(con):
    for i in range(12):
        _certame(con, f"p{i}", f"EMP{i}", ["OUTRA"])
    assert rodizio(con)["achados"] == []


def test_amostra_abaixo_do_minimo_nao_aparece(con):
    for i in range(5):
        _certame(con, f"p{i}", "ALFA", ["OUTRA"])
    assert rodizio(con)["achados"] == []


# ───────────────────────── a limitação da fonte ───────────────────────────────────────────────

def test_todos_os_screens_declaram_que_NOME_nao_e_CNPJ(con):
    _certame(con, "p1", "ALFA", ["BETA"])
    for r in (perdedoras_contumazes(con), pares_cobertura(con), rodizio(con)):
        assert "NOME, não por CNPJ" in r["ressalva"]
        assert "MUNICIPAL" in r["ressalva"]


def test_base_sem_a_tabela_nao_quebra():
    vazio = sqlite3.connect(":memory:")
    vazio.row_factory = sqlite3.Row
    assert perdedoras_contumazes(vazio)["achados"] == []
    assert pares_cobertura(vazio)["achados"] == []
    assert rodizio(vazio)["achados"] == []
