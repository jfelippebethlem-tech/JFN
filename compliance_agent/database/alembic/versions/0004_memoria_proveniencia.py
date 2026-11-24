"""memória: proveniência e estado categórico (O6.7 do plano Esteira Única; auditoria AI-01/AI-02)

`memoria_aprendizado` ganha 5 colunas NULÁVEIS — nada é apagado nem reescrito no valor:
  • `origem`        fonte_primaria | humano | regra | desconhecida | llm
  • `estado`        nao_confirmado | corroborado | refutado | expirado
  • `fontes_raiz`   JSON com os source_root_id DISTINTOS que corroboraram (mesma origem não reforça)
  • `historico`     JSON com as versões do valor (o "mais longo" não substitui mais calado)
  • `confirmado_em` última corroboração por fonte primária

Backfill (só onde está NULL, então reaplicar é no-op): estado = 'nao_confirmado' em TODAS as linhas existentes —
nenhuma delas tem fonte primária registrada; origem = 'llm' quando o rótulo `fonte` é de saída de modelo
(hermes*, groq, orquestrador, auto_melhoria, pericia_aprendizado*…), senão 'desconhecida'. `confianca` fica
como está (é histórico); quem lê usa a confiança EFETIVA de `llm/memoria.py`, que limita item não confirmado.

Idempotente: coluna que já existe não é recriada (banco que passou por `_sync_columns` com JFN_SYNC_COLUMNS=1).
Retrocompatível: escritores em SQL cru (enxame/memoria.py, lex_base_empirica.py) seguem gravando sem as colunas;
NULL é lido como desconhecida / nao_confirmado.

Revision ID: 0004_memoria_proveniencia
Revises: 0003_ingestao_quarentena
Create Date: 2026-11-24 19:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_memoria_proveniencia"
down_revision: Union[str, None] = "0003_ingestao_quarentena"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABELA = "memoria_aprendizado"
COLUNAS = (
    ("origem", sa.String(20)),
    ("estado", sa.String(20)),
    ("fontes_raiz", sa.Text()),
    ("historico", sa.Text()),
    ("confirmado_em", sa.DateTime()),
)
# Congelado AQUI (migração não importa código de aplicação): rótulos de `fonte` que são saída de LLM em 24/11/2026.
_LLM_LIKE = ("hermes%", "groq%", "gemini%", "claude%", "llm%", "openrouter%", "comotor%", "orquestrador%",
             "agente%", "pericia_aprendizado%", "lex_aprendizado%")
_LLM_EXATOS = ("auto_melhoria",)


def _existentes(bind) -> set[str]:
    insp = sa.inspect(bind)
    if TABELA not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(TABELA)}


def upgrade() -> None:
    bind = op.get_bind()
    tem = _existentes(bind)
    if not tem:                      # banco sem a tabela: create_all a cria já com as colunas
        return
    for nome, tipo in COLUNAS:
        if nome not in tem:
            op.add_column(TABELA, sa.Column(nome, tipo, nullable=True))
    op.execute(f"UPDATE {TABELA} SET estado = 'nao_confirmado' WHERE estado IS NULL")
    cond = " OR ".join([f"lower(fonte) LIKE '{p}'" for p in _LLM_LIKE] + [f"lower(fonte) = '{e}'" for e in _LLM_EXATOS])
    op.execute(f"UPDATE {TABELA} SET origem = CASE WHEN ({cond}) THEN 'llm' ELSE 'desconhecida' END "
               "WHERE origem IS NULL")


def downgrade() -> None:
    tem = _existentes(op.get_bind())
    with op.batch_alter_table(TABELA) as batch:
        for nome, _tipo in reversed(COLUNAS):
            if nome in tem:
                batch.drop_column(nome)
