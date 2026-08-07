# -*- coding: utf-8 -*-
"""Matrícula → nome: FORMATO NÃO É IDENTIDADE, e foi isso que quase matou o cruzamento.

O SEI da Prefeitura publica `Assinado Documento 6223445 (Despacho) por 15508496` — a matrícula de
quem assinou, sem o nome. A folha municipal (`pcrj_folha_pref`, 12,1 mi de linhas) tem matrícula E
nome. Mas a folha guarda **7 dígitos com zero à esquerda** (`0000190`) e a assinatura traz **8**
(`01531789`).

Comparadas como TEXTO: **0 de 69**. Comparadas como NÚMERO: **51 de 69**.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_pcrj_assinaturas_x_folha.py -q
"""
from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture()
def folha(tmp_path):
    p = tmp_path / "pcrj.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE pcrj_folha_pref (nome_norm TEXT, nome TEXT, matricula TEXT, "
              "sigla_ua TEXT, orgao TEXT, tipo_folha TEXT, remun_bruta REAL, competencia TEXT, "
              "coletado_em TEXT)")
    c.executemany("INSERT INTO pcrj_folha_pref VALUES (?,?,?,?,?,?,?,?,?)", [
        # a folha zera à esquerda em 7 dígitos
        ("", "ANA PATRICIA DA CUNHA OLIVEIRA", "2969319", "CVL/SUBG", "Casa Civil", "NORMAL",
         0.0, "202605", ""),
        ("", "JOAQUIM FERNANDES LESSA", "1907211", "SMF", "Secretaria Municipal de Fazenda",
         "NORMAL", 0.0, "202605", ""),
        # matrícula com DUAS pessoas — homônimo de cadastro, não identificação
        ("", "PESSOA UM", "0000190", "X", "Órgão X", "NORMAL", 0.0, "202401", ""),
        ("", "PESSOA DOIS", "0000190", "Y", "Órgão Y", "NORMAL", 0.0, "202405", ""),
    ])
    c.commit(); c.close()
    return p


def test_matricula_casa_por_NUMERO_e_nao_por_texto(folha):
    from tools.pcrj_assinaturas_x_folha import identificar

    ass = [{"numero": "P1", "documento": "1", "tipo": "Despacho",
            "matricula": "02969319", "quando": "", "unidade": ""}]
    r = identificar(ass, pcrj=folha)
    assert r["identificadas"] == 1, "comparação por texto voltou — 0 de 69 é o resultado dela"
    assert r["itens"][0]["nome"] == "ANA PATRICIA DA CUNHA OLIVEIRA"


def test_matricula_com_duas_pessoas_e_marcada_ambigua(folha):
    """Eleger a mais frequente seria inventar identidade. A ambiguidade fica declarada."""
    from tools.pcrj_assinaturas_x_folha import identificar

    r = identificar([{"numero": "P1", "documento": "9", "tipo": "Despacho",
                      "matricula": "00000190", "quando": "", "unidade": ""}], pcrj=folha)
    assert r["itens"][0]["ambigua"] is True
    assert r["ambiguas"] == 1


def test_matricula_sem_par_na_folha_NAO_e_inexistente(folha):
    """Requisitado de outro ente, empresa pública com registro próprio, ou vínculo encerrado antes
    de 12/2020 — a primeira competência da folha. Fica contada e declarada."""
    from tools.pcrj_assinaturas_x_folha import identificar

    r = identificar([{"numero": "P1", "documento": "7", "tipo": "Despacho",
                      "matricula": "99999999", "quando": "", "unidade": ""}], pcrj=folha)
    assert r["identificadas"] == 0 and r["nao_identificadas"] == 1
    assert r["itens"][0]["identificada"] is False
    assert "NÃO são inexistentes" in r["ressalva"]


def test_sem_a_folha_declara_a_lacuna(tmp_path):
    from tools.pcrj_assinaturas_x_folha import identificar

    r = identificar([{"matricula": "123"}], pcrj=tmp_path / "nao_existe.db")
    assert r["identificadas"] == 0 and "erro" in r
