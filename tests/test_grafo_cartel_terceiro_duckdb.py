"""O filtro de credor terceiro do grafo de cartel roda no DuckDB — e `x NOT GLOB y` não existe lá.

21/11/2026: `/api/cartel` dava 500 (`Parser Error: syntax error at or near "GLOB"`) porque `_TERCEIRO`
usava a forma do SQLite — e o glob do DuckDB nem nega com `[^...]`. Este teste roda o filtro no DuckDB de verdade.
"""
import duckdb

from compliance_agent.grafo_cartel import _TERCEIRO

_LINHAS = [("12345678000199",), ("12345678901",), ("CG1234567890AB",), ("123",), ("1234567800019X",)]
_ESPERADO = {"12345678000199", "12345678901"}


def _filtra(con, sql_tab: str) -> set[str]:
    return {r[0] for r in con.execute(f"SELECT credor FROM {sql_tab} WHERE {_TERCEIRO}").fetchall()}


def test_terceiro_parseia_e_filtra_no_duckdb():
    con = duckdb.connect()
    con.execute("CREATE TABLE t(credor VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?)", _LINHAS)
    assert _filtra(con, "t") == _ESPERADO


def test_terceiro_com_alias_continua_valido():
    con = duckdb.connect()
    con.execute("CREATE TABLE t(credor VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?)", _LINHAS)
    sql = _TERCEIRO.replace("credor", "o.credor")
    got = {r[0] for r in con.execute(f"SELECT o.credor FROM t o WHERE {sql}").fetchall()}
    assert got == _ESPERADO
