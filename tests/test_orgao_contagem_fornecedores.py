# -*- coding: utf-8 -*-
"""
Teste do P3.6 do QA: off-by-one na contagem de fornecedores do relatório de ÓRGÃO.
SUMÁRIO/§1 contavam por CNPJ distinto (n_fornecedores) e a §3 (fatos p/ a análise raciocinada)
contava por NOME distinto (len(por_favorecido_geral)) — quando um mesmo CNPJ aparece sob duas
grafias, o nº de nomes infla 1 → "115 vs 116". Agora tudo conta por CNPJ (identidade canônica).

DB SQLite temporário (sem rede).

Como rodar:
    cd ~/JFN && .venv/bin/python -m pytest tests/test_orgao_contagem_fornecedores.py -v
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

UG = "660100"


@pytest.fixture()
def db_um_cnpj_duas_grafias(tmp_path, monkeypatch):
    """1 CNPJ sob DUAS grafias + 1 CNPJ distinto → 2 CNPJs, 3 NOMES (o off-by-one clássico)."""
    p = tmp_path / "orgao.db"
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE ordens_bancarias (
        numero_ob TEXT, data_pagamento TEXT, data_emissao TEXT, favorecido_cpf TEXT,
        favorecido_nome TEXT, valor REAL, exercicio INT, ug_codigo TEXT)""")
    linhas = [
        ("OB1", "2025-01-01", None, "11111111111111", "EMPRESA ALFA LTDA", 100.0, 2025, UG),
        ("OB2", "2025-02-01", None, "11111111111111", "EMPRESA ALFA",      200.0, 2025, UG),  # mesma PJ, outra grafia
        ("OB3", "2025-03-01", None, "22222222222222", "BETA SERVICOS SA",  300.0, 2025, UG),
    ]
    con.executemany("INSERT INTO ordens_bancarias VALUES (?,?,?,?,?,?,?,?)", linhas)
    # o pago vem do SIAFE (régua `_ob_paga`, 21/11/2026): as mesmas OB, contabilizadas
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT,"
                " credor TEXT, nome_credor TEXT, valor REAL)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?)",
                    [(n, ug, f"{d[8:10]}/{d[5:7]}/{d[:4]}", "Contabilizado", c, nm, v)
                     for n, d, _e, c, nm, v, _x, ug in linhas])
    con.commit(); con.close()
    monkeypatch.setattr(O, "_DB", p)
    return p


def test_n_fornecedores_conta_cnpj_distinto(db_um_cnpj_duas_grafias):
    agg = O.consultar_orgao(UG)
    assert agg["tem_dados"] is True
    assert agg["n_fornecedores"] == 2          # 2 CNPJs distintos
    assert len(agg["por_favorecido_geral"]) == 3  # 3 NOMES (uma PJ tem 2 grafias) — a fonte do off-by-one


def test_fatos_orgao_usa_n_fornecedores_nao_nomes(db_um_cnpj_duas_grafias):
    agg = O.consultar_orgao(UG)
    ctx = {"nome": "Secretaria das Cidades", "ug": UG, "pagamentos": agg}
    fatos = O._fatos_orgao(ctx)
    # P3.6: a §3 deve dizer "2 fornecedores" (por CNPJ), não "3" (por nome)
    assert "2 fornecedores" in fatos
    assert "3 fornecedores" not in fatos
