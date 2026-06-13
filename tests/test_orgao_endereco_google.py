# -*- coding: utf-8 -*-
"""
Seção 1-E do /orgao (realidade do endereço das sedes): a agregação deve PREFERIR a verificação
autoritativa do Google (`verificacao_sede`) e cair p/ o OSM antigo (`endereco_verificacao`) só quando
o CNPJ ainda não foi varrido pelo Google — espelha o padrão honesto de `inteligencia._realidade_sede_texto`.

Honestidade: INDISPONÍVEL continua INDISPONÍVEL (≠ 0); número nunca inventado; selo da fonte Google quando vier de lá.

DB SQLite temporário (sem rede / sem DB real).

Como rodar:
    cd ~/JFN && .venv/bin/python -m pytest tests/test_orgao_endereco_google.py -v -p no:cacheprovider
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from compliance_agent.reporting import inteligencia_orgao as O  # noqa: E402

UG = "133100"

# 3 fornecedores PJ da UG:
#   A: Google=AFASTADO, OSM=INDICIO   → vale o Google (AFASTADO)  [Google sobrepõe OSM]
#   B: só OSM=INDICIO                 → fallback OSM (INDICIO)
#   C: só Google=INDISPONIVEL         → Google (INDISPONIVEL, segue INDISPONÍVEL, ≠ 0)
CNPJ_A = "11111111000111"
CNPJ_B = "22222222000122"
CNPJ_C = "33333333000133"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "orgao.db"
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE ordens_bancarias (
        numero_ob TEXT, data_pagamento TEXT, data_emissao TEXT, favorecido_cpf TEXT,
        favorecido_nome TEXT, valor REAL, exercicio INT, ug_codigo TEXT)""")
    con.executemany("INSERT INTO ordens_bancarias VALUES (?,?,?,?,?,?,?,?)", [
        ("OB1", "2025-01-01", None, CNPJ_A, "ALFA LTDA", 100.0, 2025, UG),
        ("OB2", "2025-02-01", None, CNPJ_B, "BETA SA", 200.0, 2025, UG),
        ("OB3", "2025-03-01", None, CNPJ_C, "GAMA ME", 300.0, 2025, UG),
    ])
    # OSM (deprecado): A=INDICIO, B=INDICIO
    con.execute("""CREATE TABLE endereco_verificacao (
        cnpj TEXT, status TEXT, nivel TEXT, evidencia TEXT)""")
    con.executemany("INSERT INTO endereco_verificacao (cnpj,status,nivel,evidencia) VALUES (?,?,?,?)", [
        (CNPJ_A, "INDICIO", "MEDIO", "OSM: ponto sem edificação"),
        (CNPJ_B, "INDICIO", "MEDIO", "OSM: centróide de rua"),
    ])
    # Google (autoritativo): A=AFASTADO, C=INDISPONIVEL
    con.execute("""CREATE TABLE verificacao_sede (
        cnpj TEXT, status TEXT, nivel TEXT, evidencia TEXT)""")
    con.executemany("INSERT INTO verificacao_sede (cnpj,status,nivel,evidencia) VALUES (?,?,?,?)", [
        (CNPJ_A, "AFASTADO", "ALTO", "Google: Places confirma estabelecimento no endereço"),
        (CNPJ_C, "INDISPONIVEL", "—", "Google: Places sem retorno"),
    ])
    con.commit(); con.close()
    monkeypatch.setattr(O, "_DB", p)
    return p


def test_google_sobrepoe_osm_e_conta_honesto(db):
    er = O._endereco_real_orgao(UG)
    assert er["ok"] is True
    assert er["n_forn"] == 3
    assert er["n_verificados"] == 3          # 1 veredito por CNPJ (COALESCE de fontes)
    # A: Google AFASTADO vence o OSM INDICIO → afastado=1 (não conta como indício)
    assert er["afastado"] == 1
    # B: só OSM INDICIO (fallback)
    assert er["indicio"] == 1
    # C: Google INDISPONIVEL segue INDISPONÍVEL (≠ 0)
    assert er["indisponivel"] == 1
    # 2 dos 3 vereditos vieram do Google (A, C) → fonte MISTA
    assert er["n_google"] == 2
    assert er["fonte"] == "MISTA"
    # o indício remanescente é o do OSM (CNPJ_B), com nome resolvido
    assert er["indicios"] and er["indicios"][0]["cnpj"] == CNPJ_B
    assert er["indicios"][0]["nome"] == "BETA SA"
    assert er["indicios"][0]["google"] is False


def test_selo_google_no_render(db):
    er = O._endereco_real_orgao(UG)
    ctx = {"endereco_real": er}
    L = []
    O._secao_endereco_md(L.append, ctx)
    md = "\n".join(L)
    assert "## 1-E." in md
    assert "Google" in md            # selo da fonte aparece
    assert "fonte mista" in md       # 2 Google + 1 OSM
    # contagem honesta refletida na prosa de cobertura
    assert "1 sede real (afastado)" in md
    assert "1 com indício" in md
    assert "1 sem conclusão" in md


def test_fallback_so_osm_quando_google_vazio(tmp_path, monkeypatch):
    """Sem verificacao_sede populada p/ os CNPJs → cai 100% no OSM, selo OSM, sem inventar nada."""
    p = tmp_path / "orgao.db"
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE ordens_bancarias (
        numero_ob TEXT, data_pagamento TEXT, data_emissao TEXT, favorecido_cpf TEXT,
        favorecido_nome TEXT, valor REAL, exercicio INT, ug_codigo TEXT)""")
    con.execute("INSERT INTO ordens_bancarias VALUES (?,?,?,?,?,?,?,?)",
                ("OB1", "2025-01-01", None, CNPJ_B, "BETA SA", 200.0, 2025, UG))
    con.execute("CREATE TABLE endereco_verificacao (cnpj TEXT, status TEXT, nivel TEXT, evidencia TEXT)")
    con.execute("INSERT INTO endereco_verificacao (cnpj,status,nivel,evidencia) VALUES (?,?,?,?)",
                (CNPJ_B, "AFASTADO", "ALTO", "OSM: sede edificada"))
    con.execute("CREATE TABLE verificacao_sede (cnpj TEXT, status TEXT, nivel TEXT, evidencia TEXT)")  # vazia
    con.commit(); con.close()
    monkeypatch.setattr(O, "_DB", p)
    er = O._endereco_real_orgao(UG)
    assert er["ok"] is True
    assert er["afastado"] == 1 and er["n_google"] == 0
    assert er["fonte"] == "OSM"
