"""Trava a causa-raiz de 2026-09-05: INSERT posicional quebra quando o schema ganha coluna.

O OCR acrescentou `fonte_texto` a contrato_integra. O sweep gravava com
``INSERT OR REPLACE INTO contrato_integra VALUES (?,…)`` — 13 valores para 14 colunas — e
passou DOIS DIAS falhando a cada passada, sem gravar nada. O processo rodava; o placar não
andava. Colunas nomeadas tornam o INSERT imune a coluna nova.
"""
import sqlite3

from tools.sweep_integra_contratos_pcrj import COLS, DDL


def _tabela_com_coluna_extra() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute(DDL)
    con.execute("ALTER TABLE contrato_integra ADD COLUMN fonte_texto VARCHAR")
    return con


def test_insert_nomeado_sobrevive_a_coluna_nova():
    con = _tabela_com_coluna_extra()
    valores = ["x-1/2026", "42498733000148", "2026", "1", "FORN", 1.0,
               "t.pdf", "http://u", 10, "texto", "[]", "TEXTO_OK", "2026-09-05T00:00:00"]
    con.execute(f"INSERT OR REPLACE INTO contrato_integra ({COLS}) "
                f"VALUES ({','.join('?' * len(valores))})", valores)
    assert con.execute("SELECT count(*) FROM contrato_integra").fetchone()[0] == 1


def test_insert_posicional_quebraria():
    """Prova que o modo antigo falha — sem isso o teste acima não demonstra nada."""
    con = _tabela_com_coluna_extra()
    valores = ["x-1/2026", "cnpj", "2026", "1", "F", 1.0, "t", "u", 1, "tx", "[]",
               "TEXTO_OK", "2026-09-05T00:00:00"]
    try:
        con.execute(f"INSERT OR REPLACE INTO contrato_integra "
                    f"VALUES ({','.join('?' * len(valores))})", valores)
    except sqlite3.OperationalError as exc:
        assert "columns but 13 values" in str(exc)
    else:
        raise AssertionError("o INSERT posicional deveria falhar com a coluna extra")


def test_cols_cobre_todas_as_colunas_do_ddl_menos_a_do_ocr():
    con = sqlite3.connect(":memory:")
    con.execute(DDL)
    do_ddl = [r[1] for r in con.execute("PRAGMA table_info(contrato_integra)")]
    assert [c.strip() for c in COLS.split(",")] == do_ddl
