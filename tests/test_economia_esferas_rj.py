# -*- coding: utf-8 -*-
"""economia_potencial — o ACHADO fica restrito aos entes fiscalizados (Estado RJ +
Prefeitura do Rio) por padrão, mesmo sem escolher aba.

Pedido do dono (2026-07-24): "economia potencial continua aparecendo órgãos que não
são nem prefeitura do rio nem governo do estado. as medianas podem até ser calculadas
com outros órgãos, mas eu quero acesso aos órgãos do governo do estado e da prefeitura
do rio que estão comprando superfaturado." → mediana GLOBAL, achado só {estado, prefeitura}.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import comparador_precos as CP

_DDL = """CREATE TABLE pncp_resultado (item_descricao TEXT, unidade_medida TEXT,
    valor_unitario REAL, quantidade REAL, orgao_nome TEXT, orgao_cnpj TEXT, unidade_nome TEXT,
    municipio TEXT, fornecedor_nome TEXT, fornecedor_cnpj TEXT, ordem_classificacao INTEGER,
    data_pub TEXT, certame TEXT)"""
_INS = ("INSERT INTO pncp_resultado (item_descricao, unidade_medida, valor_unitario, "
        "quantidade, orgao_nome, orgao_cnpj, unidade_nome, municipio, fornecedor_nome, "
        "fornecedor_cnpj, ordem_classificacao, certame) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)")


@pytest.fixture()
def db(tmp_path):
    """Mediana da cadeira = 10. Três compradores acima da mediana, um por esfera:
    Estado RJ, Prefeitura do Rio, e um município de fora (Niterói)."""
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.execute(_DDL)
    rows = [
        # base da mediana (10) — 5 órgãos genéricos (esfera 'outros'); quantidade>=2 é
        # exigência de _linhas (senão a linha é descartada e a mediana desloca).
        ("Cadeira", "UN", 10.0, 2, "ORG A", "", "ORG A", "", "F", "11111111000111", "c1"),
        ("Cadeira", "UN", 10.0, 2, "ORG B", "", "ORG B", "", "F", "11111111000111", "c2"),
        ("Cadeira", "UN", 10.0, 2, "ORG C", "", "ORG C", "", "F", "11111111000111", "c3"),
        ("Cadeira", "UN", 10.0, 2, "ORG D", "", "ORG D", "", "F", "11111111000111", "c5"),
        ("Cadeira", "UN", 10.0, 2, "ORG E", "", "ORG E", "", "F", "11111111000111", "c6"),
        # sobrepreço ESTADO RJ: (30-10)×100 = 2.000
        ("Cadeira", "UN", 30.0, 100, "GOVERNO DO ESTADO DO RIO DE JANEIRO", "",
         "SECRETARIA DE ESTADO DE SAUDE", "rio de janeiro", "FE", "22222222000122", "cE"),
        # sobrepreço PREFEITURA do Rio: (25-10)×100 = 1.500
        ("Cadeira", "UN", 25.0, 100, "MUNICIPIO DE RIO DE JANEIRO", "",
         "SECRETARIA MUNICIPAL DE EDUCACAO", "rio de janeiro", "FP", "33333333000133", "cP"),
        # sobrepreço NITERÓI (fora dos dois entes): (40-10)×100 = 3.000 — NÃO pode aparecer
        ("Cadeira", "UN", 40.0, 100, "MUNICIPIO DE NITEROI", "",
         "SECRETARIA MUNICIPAL DE OBRAS", "niteroi", "FN", "44444444000144", "cN"),
    ]
    con.executemany(_INS, rows)
    con.commit()
    con.close()
    return p


def _orgaos(d):
    return {o["orgao"] for o in d["por_orgao"]}


def test_default_restringe_aos_dois_entes_rj(db):
    """Sem escolher aba, o achado é só Estado RJ + Prefeitura do Rio."""
    d = CP.economia_potencial(db_path=db, min_amostra=3, min_orgaos=2, min_certames=3)
    orgs = _orgaos(d)
    assert any("ESTADO" in o for o in orgs)
    assert any("EDUCACAO" in o or "MUNICIPAL" in o for o in orgs)
    assert not any("OBRAS" in o for o in orgs), "Niterói (fora dos entes) vazou no achado"
    # Niterói (3.000) fora; total = 2.000 (estado) + 1.500 (prefeitura)
    assert d["economia_total"] == pytest.approx(3500.0)


def test_mediana_continua_global(db):
    """A mediana usa TODAS as compras (inclui federal), não só as dos dois entes.
    Se a mediana virasse local, o excesso mudaria — aqui deve seguir 10."""
    d = CP.economia_potencial(db_path=db, min_amostra=3, min_orgaos=2, min_certames=3)
    # excesso do estado = (30-10)×100 = 2000 confirma mediana 10 (global)
    est = [o for o in d["por_orgao"] if "ESTADO" in o["orgao"]][0]
    assert est["economia"] == pytest.approx(2000.0)


def test_aba_estado_isola_so_o_estado(db):
    d = CP.economia_potencial(db_path=db, esfera="estado", min_amostra=3,
                              min_orgaos=2, min_certames=3)
    orgs = _orgaos(d)
    assert any("ESTADO" in o for o in orgs)
    assert not any("EDUCACAO" in o or "OBRAS" in o for o in orgs)


def test_aba_prefeitura_isola_so_a_prefeitura(db):
    d = CP.economia_potencial(db_path=db, esfera="prefeitura", min_amostra=3,
                              min_orgaos=2, min_certames=3)
    orgs = _orgaos(d)
    assert any("EDUCACAO" in o or "MUNICIPAL" in o for o in orgs)
    assert not any("ESTADO" in o or "OBRAS" in o for o in orgs)


def test_pode_pedir_tudo_explicitamente(db):
    """esfera='todas' volta ao comportamento antigo (achado global) — para quem quiser."""
    d = CP.economia_potencial(db_path=db, esfera="todas", min_amostra=3,
                              min_orgaos=2, min_certames=3)
    assert any("OBRAS" in o["orgao"] for o in d["por_orgao"])
