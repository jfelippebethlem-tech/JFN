"""
Configuração de coleta do pytest.

Auto-marca como `network` os módulos de teste que tocam serviços externos
(PNCP/SEI/Receita/SIAFE/Chrome) — eles podem pendurar quando a VM (IP GCP) é
barrada por WAF/DNS. Assim a suíte rápida do dia a dia roda limpa:

    pytest -m "not network and not integration"

e os de rede ficam disponíveis explicitamente:

    pytest -m network

Marcar num lugar só evita poluir 6 arquivos com decorators e mantém o critério
auditável. Ver docs/PLANO-BENCHMARKS-E-CODIFICACAO-2026-06-09.md.
"""
import pytest

# Módulos cujos testes batem em rede (apurado por grep httpx/playwright/portais
# + os hangs documentados no handoff 2026-06-09: PNCP/SEI/Receita).
_MODULOS_REDE = {
    "test_jfn2_onda6",       # PNCP
    "test_jfn2_onda8",       # integração externa
    "test_jfn2_onda12",      # integração externa
    "test_jfn2_sei",         # SEI (WAF)
    "test_jfn2_receita",     # Receita/BrasilAPI
    "test_relatorio_riscos",  # consulta externa
    "test_offline",          # exercita caminhos de fallback de rede
}


def pytest_collection_modifyitems(config, items):
    for item in items:
        nome = item.module.__name__.split(".")[-1]
        if nome in _MODULOS_REDE:
            item.add_marker(pytest.mark.network)


# Módulos cujos testes ESCREVEM no DB criando os próprios dados (OBs, memória, hipóteses) → isolar num
# tmp DB para NÃO poluir a `compliance.db` de produção ("TESTE LTDA"/"missão de teste") nem disputar o write
# lock com o jfn.service vivo. Resolvido via env JFN_DB (compliance_agent.database.models._resolver_db).
_MODULOS_ISOLAR_DB = {"test_offline"}


@pytest.fixture(autouse=True)
def _isola_db(request, tmp_path, monkeypatch):
    nome = request.module.__name__.split(".")[-1]
    if nome in _MODULOS_ISOLAR_DB:
        monkeypatch.setenv("JFN_DB", str(tmp_path / "test_compliance.db"))
    yield
