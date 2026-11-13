"""A economia NÃO soma grupo de rótulo genérico — nem como "faixa superior".

Histórico: em 25/07/2026, 60,4% da "economia potencial" (R$ 9,41 mi de R$ 15,58 mi) vinha de
grupos cuja descrição do PNCP mistura produtos ('Peça mecânica / elétrica - veículo', dispersão
1.292×; 'Locação de Veículos - Leves / Pesados', 300×). A cura de então separou o total em
homogêneo × genérico, mas o genérico continuava somado num "total". Em 13/11/2026 (dono: "não
pode ter margem pra erro em nada") o grupo heterogêneo passou a INDETERMINADO: não entra em
soma nenhuma, e o motivo aparece por extenso.
"""
import sqlite3

import pytest

from compliance_agent.comparador_precos import economia_potencial

DDL = """
CREATE TABLE pncp_resultado (item_descricao TEXT, unidade_medida TEXT, valor_unitario REAL,
  quantidade REAL, orgao_nome TEXT, unidade_nome TEXT, fornecedor_nome TEXT,
  fornecedor_cnpj TEXT, certame TEXT, data_pub TEXT, ordem_classificacao INTEGER, item INTEGER);
"""


def _banco(tmp_path, linhas) -> str:
    p = str(tmp_path / "d.db")
    con = sqlite3.connect(p)
    con.executescript(DDL)
    con.executemany(
        "INSERT INTO pncp_resultado VALUES (?,?,?,?,?,?,?,?,?,?,1,1)",
        [(d, "unidade", vu, 10.0, f"ORGAO{i % 3}", f"ORGAO{i % 3}", "FORN", "11111111000191",
          f"c{i}", "2025-01-01") for i, (d, vu) in enumerate(linhas)])
    con.commit()
    con.close()
    return p


def _tudo(db):
    con = sqlite3.connect(db)
    certs = [r[0] for r in con.execute("SELECT certame FROM pncp_resultado")]
    con.close()
    return ({(c, 1, "11111111000191"): {"estado": "VERIFICADO"} for c in certs},
            {c: {"srp": False} for c in certs})


def test_grupo_homogeneo_com_sobrepreco_conta(tmp_path):
    db = _banco(tmp_path, [("caneta esferografica azul", p) for p in (10, 11, 12, 11, 10, 25)])
    v, i = _tudo(db)
    r = economia_potencial(db, esfera="todas", min_certames=3, verificacao=v, info_certames=i)
    assert r["economia_total"] > 0
    assert r["economia_descricao_generica"] == 0


def test_rotulo_generico_nao_entra_em_soma_nenhuma(tmp_path):
    """Mesmo rótulo de R$ 2 a R$ 2.500 sem salto ≥4×: heterogêneo → INDETERMINADO."""
    precos = (2, 5, 12, 30, 70, 160, 400, 1000, 2500)
    db = _banco(tmp_path, [("cabo eletrico flexivel", p) for p in precos])
    v, i = _tudo(db)
    r = economia_potencial(db, esfera="todas", min_certames=3, verificacao=v, info_certames=i)
    assert r["economia_total"] == 0 and r["economia_pendente"] == 0
    motivos = " ".join(m["motivo"] for m in r["indeterminados"]["por_motivo"])
    assert "heterog" in motivos
