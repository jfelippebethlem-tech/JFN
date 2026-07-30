# -*- coding: utf-8 -*-
"""Caller do SpiderFoot — e as duas recusas que impedem o footprint de acusar o país inteiro.

A ponte estava implementada, testada, com o binário instalado, e sem caller — porque recebe
domínio/e-mail/IP e a casa não tinha o campo. Passou a ter com o I.1.2.

MEDIDO SOBRE OS 4.258.994 E-MAILS DO DUMP INTEIRO: **87,3% são de provedor livre** (gmail 54%,
hotmail 16%, yahoo 5%), e só **12,7% têm domínio próprio**. Daí as duas recusas:

  1. E-mail de provedor livre não é domínio da empresa — escanear `gmail.com` mediria o Google.
  2. **Não ter domínio próprio não é sinal de fachada**: é a norma de sete em cada oito empresas
     brasileiras. `score=1.0` (footprint vazio = máximo suspeito) para quem não tem domínio seria o
     defeito do laranja em 55% da base, repetido em escala maior.

E um detalhe de método que vale registro: a primeira medição usou `LIMIT 400000` e deu 83,2%; a de
`LIMIT 100000` deu 59,8%. `LIMIT` sem ordenação pega fatia contígua por rowid, enviesada por faixa de
CNPJ. Denominador errado é pior que denominador ausente — `cobertura_dominio` CONTA.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_footprint_alvo.py -q
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.enriquecimento.footprint_alvo import (
    PROVEDORES_LIVRES,
    avaliar_footprint,
    dominio_proprio_do_cnpj,
)

_DDL = """
CREATE TABLE estabelecimentos (
  cnpj TEXT PRIMARY KEY, cnpj_basico TEXT, telefone1 TEXT, telefone2 TEXT,
  correio_eletronico TEXT);
"""


@pytest.fixture()
def base(tmp_path):
    caminho = tmp_path / "estab.db"
    con = sqlite3.connect(caminho)
    con.executescript(_DDL)
    con.commit()
    con.close()
    return str(caminho)


def _ins(caminho, cnpj, email):
    con = sqlite3.connect(caminho)
    con.execute("INSERT OR REPLACE INTO estabelecimentos VALUES (?,?,'','',?)",
                (cnpj, cnpj[:8], email))
    con.commit()
    con.close()


@pytest.mark.parametrize("email", ["x@gmail.com", "y@hotmail.com", "z@yahoo.com.br",
                                   "w@outlook.com", "v@bol.com.br"])
def test_provedor_livre_nao_vira_dominio(base, email):
    """Escanear o provedor mediria o footprint dele, não o da empresa."""
    _ins(base, "11111111000100", email)
    r = dominio_proprio_do_cnpj("11111111000100", db_estab=base)
    assert r["dominio"] == ""
    assert "provedor livre" in r["motivo"]
    assert "87,3%" in r["motivo"], "o denominador tem de viajar com a recusa"
    assert "NORMA" in r["motivo"]


def test_dominio_proprio_passa(base):
    _ins(base, "11111111000100", "contato@construtoraalfa.com.br")
    r = dominio_proprio_do_cnpj("11111111000100", db_estab=base)
    assert r["dominio"] == "construtoraalfa.com.br"
    assert r["motivo"] == ""


def test_sem_dominio_o_score_e_None_nunca_1(base):
    """A distinção que separa este módulo de um acusador de sete em cada oito empresas."""
    _ins(base, "11111111000100", "dono@gmail.com")
    r = avaliar_footprint("11111111000100", radar_score=90, db_estab=base)
    assert r["estado"] == "INDISPONIVEL"
    assert r["score"] is None, (
        "ausência de domínio próprio virando 'footprint vazio = 1.0' acusaria 87,3% do país"
    )


def test_sem_email_publicado_e_lacuna_nao_ausencia(base):
    _ins(base, "11111111000100", "")
    r = dominio_proprio_do_cnpj("11111111000100", db_estab=base)
    assert "INDISPONÍVEL, não ausência" in r["motivo"]


def test_cnpj_fora_do_dump_e_lacuna_de_captura(base):
    r = dominio_proprio_do_cnpj("99999999000199", db_estab=base)
    assert "lacuna de captura" in r["motivo"]


def test_guarda_de_custo_barra_alvo_de_baixo_risco(base):
    """Cada scan são minutos e dezenas de requisições externas — nunca em sweep de massa."""
    _ins(base, "11111111000100", "contato@alfa.com.br")
    r = avaliar_footprint("11111111000100", radar_score=10, db_estab=base)
    assert r["estado"] == "INDISPONIVEL" and r["score"] is None
    assert "não elegível" in r["motivo"] and "sweep de massa" in r["motivo"]

    r2 = avaliar_footprint("11111111000100", radar_score=None, db_estab=base)
    assert r2["estado"] == "INDISPONIVEL", "sem radar_score não se gasta scan"


def test_o_scan_indisponivel_nao_vira_footprint_vazio(base, monkeypatch):
    _ins(base, "11111111000100", "contato@alfa.com.br")
    monkeypatch.setattr("compliance_agent.enriquecimento.footprint_alvo.footprint",
                        lambda *a, **k: None)
    r = avaliar_footprint("11111111000100", radar_score=90, db_estab=base)
    assert r["score"] is None
    assert "INDISPONÍVEL não é footprint vazio" in r["motivo"]


def test_footprint_medido_traz_leitura_e_ressalva(base, monkeypatch):
    _ins(base, "11111111000100", "contato@alfa.com.br")
    monkeypatch.setattr("compliance_agent.enriquecimento.footprint_alvo.footprint",
                        lambda *a, **k: {"n_achados": 0, "tipos": {}, "tem_site": False})
    r = avaliar_footprint("11111111000100", radar_score=90, db_estab=base)
    assert r["estado"] == "MEDIDO"
    assert r["score"] == pytest.approx(1.0), "domínio existe e nada foi achado: aí sim vale 1.0"
    assert "estrutura de papel" in r["leitura"]
    assert "nunca prova de fachada" in r["ressalva"]


def test_a_lista_de_provedores_cobre_os_campeoes():
    for d in ("gmail.com", "hotmail.com", "yahoo.com.br", "outlook.com", "bol.com.br", "uol.com.br"):
        assert d in PROVEDORES_LIVRES, f"{d} está entre os mais usados do dump e ficou de fora"
