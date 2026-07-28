# -*- coding: utf-8 -*-
"""O universo do sweep SEI vem do SIAFE, não do espelho TFE.

MEDIDO em 2026-07-28, investigando "o sweep itkava está funcionando 100%?": o log repetia
**"nada novo na fila (tudo já lido/cacheado)"** enquanto 3.228 processos conhecidos seguiam sem
captura. A causa não era o leitor — era o UNIVERSO:

    universo do espelho TFE (`ordens_bancarias`)      22.016 processos
    universo do SIAFE (`ob_orcamentaria_siafe`)       41.740 processos
    contidos só no SIAFE                             +19.724  (+90%)

E o conjunto do espelho está **inteiramente contido** no do SIAFE — trocar a fonte não perde
nada e quase dobra o que o sweep enxerga. É a regra da casa aplicada onde faltava: OB e
pagamento vêm do SIAFE, nunca do espelho.

O sintoma é o mais perigoso que existe aqui: um pipeline que se declara **em dia** porque
esgotou uma fila que era metade do trabalho.
"""
from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture()
def con(tmp_path):
    c = sqlite3.connect(tmp_path / "t.db")
    c.executescript("""
        CREATE TABLE ordens_bancarias (numero_sei TEXT, ug_codigo TEXT, valor REAL,
            favorecido_cpf TEXT);
        CREATE TABLE ob_orcamentaria_siafe (processo TEXT, ug_emitente TEXT, valor REAL,
            credor TEXT);
    """)
    # o espelho conhece um; o SIAFE conhece os dois
    c.execute("INSERT INTO ordens_bancarias VALUES ('SEI-030001/000001/2026','030001',100.0,'')")
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?)", [
        ("SEI-030001/000001/2026", "030001", 100.0, "11222333000144"),
        ("SEI-030001/000002/2026", "030001", 900.0, "11222333000144"),
    ])
    c.commit()
    return c


_SQL = ("SELECT processo, COUNT(*) nob, ROUND(SUM(valor),2) tot FROM ob_orcamentaria_siafe "
        "WHERE processo LIKE 'SEI-%/%/20%' GROUP BY processo ORDER BY tot DESC")


def test_o_siafe_alcanca_o_que_o_espelho_nao_ve(con):
    siafe = {r[0] for r in con.execute(_SQL)}
    espelho = {r[0] for r in con.execute(
        "SELECT DISTINCT numero_sei FROM ordens_bancarias WHERE numero_sei LIKE 'SEI-%'")}
    assert espelho < siafe, "o espelho tem de ser subconjunto próprio do SIAFE"
    assert "SEI-030001/000002/2026" in siafe - espelho


def test_ordena_por_valor_desc(con):
    rows = list(con.execute(_SQL))
    assert rows[0][0] == "SEI-030001/000002/2026", "o de maior valor vem primeiro"


def test_filtro_por_ug_usa_a_coluna_do_siafe(con):
    """`ug_codigo` é do espelho; no SIAFE a coluna é `ug_emitente`. Trocar a fonte sem trocar a
    coluna daria erro de SQL — ou, pior, filtro silenciosamente vazio."""
    n = con.execute("SELECT COUNT(DISTINCT processo) FROM ob_orcamentaria_siafe "
                    "WHERE processo LIKE 'SEI-%' AND ug_emitente = ?", ("030001",)).fetchone()[0]
    assert n == 2


def test_filtro_por_fornecedor_usa_credor(con):
    """No espelho é `favorecido_cpf` com máscara; no SIAFE é `credor`, já só dígitos."""
    n = con.execute("SELECT COUNT(DISTINCT processo) FROM ob_orcamentaria_siafe "
                    "WHERE credor = ?", ("11222333000144",)).fetchone()[0]
    assert n == 2


def test_o_codigo_do_sweep_usa_a_tabela_do_siafe():
    """A trava: se alguém voltar a fonte para o espelho, isto falha."""
    import pathlib
    fonte = pathlib.Path("tools/sei_sweep.py").read_text()
    trecho = fonte[fonte.index("def _fila("):fonte.index("def _arvores_encerradas(")]
    assert "ob_orcamentaria_siafe" in trecho
    assert "FROM ordens_bancarias" not in trecho, "voltou a montar a fila pelo espelho TFE"
