# -*- coding: utf-8 -*-
"""Taxa por unidade: denominador honesto, sem taxa sobre anedota, controlada por profundidade.

O achado que motivou a ferramenta (2026-08-09): "pagamento sem evidência de execução" em 45,8% dos
processos avaliados do Fundo Estadual da Saúde contra 0% dos 44 do Fundo dos Bombeiros. Como as
unidades leem em profundidades diferentes, a taxa bruta seria contestável — por isso a medida sai
sempre por faixa de documentos LIDOS, e processos `NAO_AVALIAVEL` ficam fora do denominador
(captura insuficiente não é conclusão sobre a unidade).
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from tools.taxa_lacuna_por_unidade import MIN_N, markdown, medir


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE processo_avaliacao (numero_sei TEXT, faixa TEXT, "
                "cobertura_json TEXT, lacunas_json TEXT)")
    def linha(numero, faixa, lidos, tem):
        con.execute("INSERT INTO processo_avaliacao VALUES (?,?,?,?)", (
            numero, faixa, json.dumps({"n_com_texto": lidos}),
            json.dumps({"processo": ([{"falta": "Evidência de execução (medição/atesto)",
                                       "gravidade": "critica"}] if tem else [])})))
    for i in range(12):
        linha(f"260007/{i:06d}/2024", "ALTO", 12, tem=i < 8)      # 8 de 12 na faixa 10-19
    for i in range(11):
        linha(f"270006/{i:06d}/2024", "MEDIO", 12, tem=False)     # 0 de 11, mesma faixa
    linha("260007/999999/2024", "NAO_AVALIAVEL", 3, tem=True)     # fora do denominador
    linha("030001/000001/2024", "ALTO", 12, tem=True)             # unidade com n=1
    con.commit()
    con.close()
    return str(p)


def test_nao_avaliavel_fica_fora_do_denominador(db):
    d = medir("execu", db)
    assert d["260007"]["n"] == 12, "processo NAO_AVALIAVEL entrou na conta da unidade"
    assert d["260007"]["com"] == 8


def test_contraste_sobrevive_na_mesma_faixa_de_profundidade(db):
    d = medir("execu", db)
    assert d["260007"]["faixas"]["10-19"] == [12, 8]
    assert d["270006"]["faixas"]["10-19"] == [11, 0], (
        "a unidade de contraste perdeu o zero — sem ele não há prova de que não é o gate")


def test_taxa_nao_e_impressa_sobre_anedota(db):
    texto = markdown(medir("execu", db), "execu")
    assert "030001" not in texto, f"unidade com n=1 virou taxa (MIN_N={MIN_N})"
    assert "260007" in texto and "270006" in texto


def test_termo_diferente_nao_casa_a_lacuna_de_execucao(db):
    d = medir("sobrepreco", db)
    assert d["260007"]["com"] == 0
