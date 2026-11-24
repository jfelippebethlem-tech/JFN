"""datas do SIAFE em texto: coluna gerada `data_emissao_iso` + índice (O4.3)

`data_emissao` de `ob_orcamentaria_siafe`, `ne_siafe` e `nl_siafe` é TEXTO 'DD/MM/AAAA' (conferido no
snapshot ~/snapshot-20261124/compliance.db: 1.372.744 + 41.687 + 49.214 linhas, 100% no formato, zero
NULL). ORDER BY/MIN/MAX sobre o texto cru comparam o dia primeiro ('31/12/2025' > '02/01/2026').

Coluna GERADA VIRTUAL (SQLite ≥ 3.31; venv em 3.53.1, sistema 3.45.1): ALTER TABLE ADD COLUMN só grava o
schema (não reescreve a tabela de 6 GB), o valor é calculado na leitura e o índice materializa a ordem.
Texto fora do formato → NULL. Nada de `batch_alter_table`: o modo batch RECRIARIA a tabela inteira.

A expressão é cópia CONGELADA de `compliance_agent/database/datas_iso.py` (a migração não importa código
vivo); `tests/test_regra_data_texto.py` confere que as duas não divergem.

Tabela ausente (banco novo/de teste) é pulada: banco novo nasce no head por `init_db()` e as DDLs de
criação dessas tabelas já trazem a coluna gerada.

Revision ID: 0002_datas_iso
Revises: 0001_base
Create Date: 2026-11-24
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = '0002_datas_iso'
down_revision: Union[str, None] = '0001_base'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GLOB = "[0-3][0-9]/[0-1][0-9]/[12][0-9][0-9][0-9]"
COLUNAS = {"ob_orcamentaria_siafe": "data_emissao", "ne_siafe": "data_emissao", "nl_siafe": "data_emissao"}


def _expr(col: str) -> str:
    return (f"CASE WHEN {col} GLOB '{_GLOB}' "
            f"THEN substr({col},7,4)||'-'||substr({col},4,2)||'-'||substr({col},1,2) END")


def _colunas(con, tabela: str) -> set[str] | None:
    """Colunas da tabela INCLUINDO as geradas (table_xinfo); None se a tabela não existe."""
    linhas = con.execute(text(f'PRAGMA table_xinfo("{tabela}")')).fetchall()
    return {r[1] for r in linhas} if linhas else None


def upgrade() -> None:
    con = op.get_bind()
    for tabela, col in COLUNAS.items():
        cols = _colunas(con, tabela)
        if cols is None:
            continue
        if f"{col}_iso" not in cols:
            op.execute(f'ALTER TABLE "{tabela}" ADD COLUMN {col}_iso TEXT '
                       f'GENERATED ALWAYS AS ({_expr(col)}) VIRTUAL')
        op.execute(f'CREATE INDEX IF NOT EXISTS ix_{tabela}_{col}_iso ON "{tabela}"({col}_iso)')


def downgrade() -> None:
    con = op.get_bind()
    for tabela, col in COLUNAS.items():
        cols = _colunas(con, tabela)
        if cols is None:
            continue
        op.execute(f'DROP INDEX IF EXISTS ix_{tabela}_{col}_iso')
        if f"{col}_iso" in cols:
            op.execute(f'ALTER TABLE "{tabela}" DROP COLUMN {col}_iso')
