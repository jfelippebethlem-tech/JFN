"""ingestão: lote e quarentena (O4.11 do plano Esteira Única; doc 2 §40.1–40.2)

Duas tabelas NOVAS, nenhuma alteração em tabela existente:
  • `ingestao_lote`       — contagens por lote (recebidos, aceitos, rejeitados, duplicados, conflitos, quarentena),
                            total declarado pela origem (reconciliação), hash do lote e como a paginação terminou;
  • `ingestao_quarentena` — registro inválido ou em conflito com o PAYLOAD ORIGINAL, lote, motivo e ação;
                            nunca se apaga: `resolvido_em`/`resolucao` fecham o item.

O DDL é igual ao de `compliance_agent/ingestao/quarentena.DDL` (tests/test_ingestao_contrato.py confere).
Encadeia na `0002_datas_iso` (O4.3, commit cba39ce6). Cabeça única é exigida por tests/test_ingestao_contrato.py:
duas revisões no mesmo pai fazem o `migrar status` falhar e o boot do painel responder 503.

Ensaio (24/11/2026): cópia do snapshot ~/snapshot-20261124/compliance.db no scratchpad — stamp → upgrade →
current == head; downgrade → upgrade de novo; `migrar diff` = 0. VIVO NÃO TOCADO.

Revision ID: 0003_ingestao_quarentena
Revises: 0002_datas_iso
Create Date: 2026-11-24 17:00:00
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003_ingestao_quarentena"
down_revision: Union[str, None] = "0002_datas_iso"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABELAS = ("ingestao_quarentena", "ingestao_lote")


# Congelado AQUI (migração não importa código de aplicação: mudar o módulo não pode reescrever o passado).
DDL = """
CREATE TABLE IF NOT EXISTS ingestao_lote (
    lote TEXT PRIMARY KEY,
    fonte TEXT NOT NULL,
    contrato_versao INTEGER NOT NULL,
    parser_versao TEXT,
    iniciado_em TEXT NOT NULL,
    terminado_em TEXT,
    recebidos INTEGER NOT NULL DEFAULT 0,
    aceitos INTEGER NOT NULL DEFAULT 0,
    rejeitados INTEGER NOT NULL DEFAULT 0,
    duplicados INTEGER NOT NULL DEFAULT 0,
    conflitos INTEGER NOT NULL DEFAULT 0,
    quarentena INTEGER NOT NULL DEFAULT 0,
    origem_declarada INTEGER,
    hash_lote TEXT,
    fim_paginacao TEXT,
    extensoes TEXT,
    observacao TEXT
);
CREATE INDEX IF NOT EXISTS ix_ingestao_lote_fonte ON ingestao_lote (fonte, iniciado_em);
CREATE TABLE IF NOT EXISTS ingestao_quarentena (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fonte TEXT NOT NULL,
    lote TEXT NOT NULL,
    chave TEXT,
    payload TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    motivo TEXT NOT NULL,
    acao TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    resolvido_em TEXT,
    resolucao TEXT,
    UNIQUE (fonte, lote, payload_sha256)
);
CREATE INDEX IF NOT EXISTS ix_ingestao_quarentena_aberta ON ingestao_quarentena (fonte, resolvido_em);
"""


def upgrade() -> None:
    for comando in (c.strip() for c in DDL.split(";")):
        if comando:
            op.execute(comando)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ingestao_quarentena_aberta")
    op.execute("DROP INDEX IF EXISTS ix_ingestao_lote_fonte")
    for t in _TABELAS:
        op.execute(f"DROP TABLE IF EXISTS {t}")
