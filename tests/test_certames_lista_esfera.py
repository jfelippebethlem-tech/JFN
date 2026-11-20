# -*- coding: utf-8 -*-
"""/api/certames/lista: esfera fechada e pela régua (20/11/2026).

Rótulo fora do vocabulário devolvia a tabela inteira (mais de 9 mil certames federais na aba de quem pediu) e
"estado" era só a raiz 42498600 — 393 certames de órgão estadual com CNPJ próprio (ALERJ, TJRJ, DETRAN…) sumiam.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

ESTADO, ALERJ, PCRJ, EXERCITO, NITEROI = ("42498600000171", "30449862000167", "42498733000148",
                                          "00394452000103", "28521748000159")


@pytest.fixture()
def rota(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    con = sqlite3.connect(tmp_path / "data" / "compliance.db")
    con.executescript("""
    CREATE TABLE edital_documento (numero_controle_pncp TEXT, orgao_cnpj TEXT, ano INT, objeto TEXT, valor_estimado REAL);
    CREATE TABLE certame_indice (certame TEXT, score REAL, faixa TEXT, confianca REAL, prioridade REAL, familias_json TEXT);
    CREATE TABLE orgao_esfera (cnpj TEXT, nome TEXT, esfera TEXT);
    """)
    for cnpj in (ESTADO, ALERJ, PCRJ, EXERCITO, NITEROI):
        con.execute("INSERT INTO edital_documento VALUES (?,?,2025,'objeto',1000)", (f"{cnpj}-1-000001/2025", cnpj))
    con.executemany("INSERT INTO orgao_esfera VALUES (?,?,?)", [
        (ESTADO, "ESTADO DO RIO DE JANEIRO", "estadual-rj"), (ALERJ, "ASSEMBLEIA LEGISLATIVA DO ERJ", "estadual-rj"),
        (PCRJ, "MUNICIPIO DE RIO DE JANEIRO", "municipal-rio"), (EXERCITO, "COMANDO DO EXERCITO", "federal"),
        (NITEROI, "MUNICIPIO DE NITEROI", "outro-municipio")])
    con.commit()
    con.close()
    from rotas import investigacao as R
    monkeypatch.setattr(R, "RAIZ", tmp_path)

    def chamar(**kw):
        r = R.api_certames_lista(**kw)
        return r.status_code, json.loads(r.body)
    return chamar


def test_estado_inclui_orgao_estadual_com_cnpj_proprio_e_so_ele(rota):
    st, d = rota(esfera="estado")
    assert st == 200 and d["esfera"] == "estado"
    assert {i["nc"][:14] for i in d["itens"]} == {ESTADO, ALERJ}          # ALERJ entra; federal e Prefeitura não
    assert d["resumo"]["total"] == 2


def test_prefeitura_e_so_o_municipio_do_rio(rota):
    st, d = rota(esfera="prefeitura")
    assert {i["nc"][:14] for i in d["itens"]} == {PCRJ} and d["resumo"]["total"] == 1   # Niterói não é a Prefeitura


@pytest.mark.parametrize("ruim", ["estadual", "todas", "", "federal"])
def test_esfera_fora_do_vocabulario_e_recusada_e_nao_devolve_a_tabela_inteira(rota, ruim):
    st, d = rota(esfera=ruim)
    assert st == 400 and d["ok"] is False and "itens" not in d
