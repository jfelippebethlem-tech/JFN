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
import sys
from pathlib import Path

import pytest

# `tests/` no sys.path para que os módulos de teste possam importar `helpers_ambiente`
# (o "este ambiente tem os dados?" de um lugar só). Sem isto o import falha na COLETA, que é
# pior que a falha original: derruba o arquivo inteiro.
sys.path.insert(0, str(Path(__file__).resolve().parent))

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
_MODULOS_ISOLAR_DB = {"test_offline", "test_goal_modes_smoke", "test_dossie_smoke",
                      "test_anomalia_receita"}


@pytest.fixture(autouse=True)
def _isola_db(request, tmp_path, monkeypatch):
    nome = request.module.__name__.split(".")[-1]
    if nome in _MODULOS_ISOLAR_DB:
        monkeypatch.setenv("JFN_DB", str(tmp_path / "test_compliance.db"))
    yield


# ─────────────────────────────────────────────────────────────────────────────
# Falha de AMBIENTE não é regressão (2026-08-02)
#
# O runner do GitHub não tem a `compliance.db` (2,6 GB, não versionada) — mas ELA APARECE lá,
# vazia, criada por testes que escrevem. Guard por existência de arquivo (`Path(_DB).exists()`)
# passa, o teste roda contra um banco sem tabelas e morre com "no such table". O `ci_delta` lê
# isso como REGRESSÃO NOVA e reprova o CI; foi assim que 4 testes viraram alarme falso num dia,
# cada um exigindo uma linha na BASE-FALHAS-CI.txt — remendo que não escala.
#
# Aqui a falha vira SKIP, mas SÓ quando o ambiente comprovadamente não tem a base utilizável.
# Na VM (base completa) `_BASE_UTILIZAVEL` é True e qualquer "no such table" continua FALHANDO,
# como tem de ser: é o mesmo princípio da casa — INDISPONÍVEL ≠ 0, e ambiente ≠ código.
# ─────────────────────────────────────────────────────────────────────────────
def _base_utilizavel() -> bool:
    import sqlite3
    from pathlib import Path
    try:
        from compliance_agent.reporting.intel_base import _DB
    except Exception:
        return False
    p = Path(_DB)
    if not p.exists() or p.stat().st_size < 1_000_000:      # base vazia/embrionária não conta
        return False
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            n = con.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return False
    return n > 20        # a base real tem dezenas de tabelas; a criada por teste, poucas


_BASE_UTILIZAVEL = _base_utilizavel()
_SINTOMAS_SEM_BASE = ("no such table", "no such column", "unable to open database file")


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_makereport(item, call):
    rel = yield
    rep = rel.get_result()
    if _BASE_UTILIZAVEL or rep.when != "call" or rep.outcome != "failed":
        return
    texto = str(getattr(call, "excinfo", "") or "").lower() + str(rep.longrepr or "").lower()
    if any(s in texto for s in _SINTOMAS_SEM_BASE):
        rep.outcome = "skipped"
        rep.longrepr = (__file__, 0,
                        "AMBIENTE sem compliance.db utilizável (tabelas ausentes) — "
                        "não é regressão de código; roda na VM com a base real")
