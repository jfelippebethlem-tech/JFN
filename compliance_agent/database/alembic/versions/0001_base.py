"""base: schema do compliance.db em 24/11/2026

Gerada por `alembic revision --autogenerate` contra a CÓPIA do snapshot congelado
(~/snapshot-20261124/compliance.db, md5 b20799beee1cb0a130689ccec1665ca2) e CONFERIDA: com o filtro
`migrar.incluir_objeto`, zero diferença entre os modelos ORM e o banco — upgrade e downgrade são no-op.
Sem o filtro havia 2 propostas DESTRUTIVAS (DROP de `alertas.visto_em` e `registros_folha.matricula`,
colunas criadas por ALTER cru fora do modelo) e, sem o filtro de tabela, DROP das ~160 tabelas não-ORM.

As 3 migrações do runner caseiro (database/migrations/001_extract_raw_json_data,
002_categorize_ordens_bancarias, 003_missoes_auditoria) estão ABSORVIDAS aqui: o banco vivo já as tem
(registradas na tabela caseira, renomeada para `_jfn_migracoes_legado` pelo `migrar stamp`). Banco novo
nasce de `init_db()` (create_all) e é carimbado no head na hora — 001/002 são enriquecimento de dados
sobre tabela vazia e 003 só criava `missoes_auditoria`, que o create_all já cria.

Revision ID: 0001_base
Revises: 
Create Date: 2026-11-24 14:48:59.010968

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '0001_base'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
