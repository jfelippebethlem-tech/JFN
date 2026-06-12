# -*- coding: utf-8 -*-
"""Testes do módulo de relações (sócio↔empresa↔empresa↔órgão). SQLite temporário, sem rede."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from compliance_agent import relacoes as R


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    p = tmp_path / "t.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE socios_fornecedor (cnpj TEXT, razao TEXT, socio_nome TEXT, socio_nome_norm TEXT, socio_doc TEXT, qualificacao TEXT, ingerido_em TEXT)")
    con.execute("CREATE TABLE endereco_fornecedor (cnpj TEXT, razao TEXT, endereco TEXT, endereco_norm TEXT, municipio TEXT, uf TEXT, cep TEXT, atualizado_em TEXT)")
    con.execute("CREATE TABLE ordens_bancarias (favorecido_cpf TEXT, ug_codigo TEXT, ug_nome TEXT, favorecido_nome TEXT, valor REAL)")
    # empresa A (raiz 11111111) e B (raiz 22222222) compartilham o sócio JOAO → grupo (raízes distintas)
    socios = [
        ("11111111000110", "EMPRESA A", "JOAO SILVA", "JOAO SILVA", "***1**", "Sócio"),
        ("22222222000120", "EMPRESA B", "JOAO SILVA", "JOAO SILVA", "***1**", "Sócio"),
        # filial de A (mesma raiz 11111111) — NÃO conta como vínculo
        ("11111111000291", "EMPRESA A FILIAL", "JOAO SILVA", "JOAO SILVA", "***1**", "Sócio"),
    ]
    con.executemany("INSERT INTO socios_fornecedor (cnpj,razao,socio_nome,socio_nome_norm,socio_doc,qualificacao) VALUES (?,?,?,?,?,?)", socios)
    con.executemany("INSERT INTO endereco_fornecedor (cnpj,razao,endereco_norm) VALUES (?,?,?)", [
        ("11111111000110", "EMPRESA A", "RUA DAS FLORES 100 NITEROI"),
        ("22222222000120", "EMPRESA B", "RUA DAS FLORES 100 NITEROI")])
    con.executemany("INSERT INTO ordens_bancarias (favorecido_cpf,ug_codigo,ug_nome,favorecido_nome,valor) VALUES (?,?,?,?,?)", [
        ("11111111000110", "030100", "TJ", "EMPRESA A", 1000.0),
        ("22222222000120", "030100", "TJ", "EMPRESA B", 2000.0)])
    con.commit(); con.close()
    return p


def test_empresa_detecta_grupo_por_socio_e_ug_comum(db: Path):
    r = R.relacoes("11111111000110", db_path=db)
    assert r["ok"] and r["tipo"] == "empresa"
    vs = r["empresas_via_socio"]
    cnpjs = {e["cnpj"][:8] for e in vs}
    assert "22222222" in cnpjs            # EMPRESA B (raiz distinta) é vínculo
    assert "11111111" not in cnpjs        # filial (mesma raiz) NÃO conta
    b = next(e for e in vs if e["cnpj"].startswith("22222222"))
    assert "030100" in b["ugs_em_comum"]  # mesma UG → indício de concorrência fictícia


def test_co_endereco_exclui_filial(db: Path):
    r = R.relacoes("11111111000110", db_path=db)
    rz = {e["cnpj"][:8] for e in r["empresas_via_endereco"]}
    assert "22222222" in rz and "11111111" not in rz


def test_socio_lista_empresas(db: Path):
    r = R.relacoes("JOAO SILVA", db_path=db)
    assert r["tipo"] == "socio"
    assert r["n_empresas"] >= 2


def test_orgao_top_fornecedores(db: Path):
    r = R.relacoes("030100", db_path=db)
    assert r["tipo"] == "orgao"
    assert len(r["fornecedores"]) == 2


def test_render_e_honesto(db: Path):
    md = R.render_md(R.relacoes("11111111000110", db_path=db))
    assert "não prova" in md.lower() and "Relações" in md
