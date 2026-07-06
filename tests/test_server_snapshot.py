# -*- coding: utf-8 -*-
"""
Snapshot de REFACTOR do server.py — rede de segurança p/ o split em routers.

1) Inventário de rotas (método+path+handler) comparado byte a byte com o golden —
   rota sumida/renomeada/duplicada no split aparece como diff.
2) Smoke em GETs determinísticos (TestClient, sem rede): o handler responde 200/ok.

Regravar o golden após mudança INTENCIONAL de rotas:
    .venv/bin/python -m pytest tests/test_server_snapshot.py -q --update-rotas
    (ou apagar tests/golden/server_rotas.txt e rodar o teste)
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GOLDEN = REPO / "tests" / "golden" / "server_rotas.txt"

os.environ.setdefault("JFN_LEX_LER_SEI", "0")
os.environ.setdefault("JFN_LEX_DISCURSIVO", "0")
os.environ.setdefault("JFN_VEREDITO_LLM_DISABLED", "1")


def _app():
    sys.path.insert(0, str(REPO))
    import server
    return server.app


def _inventario() -> str:
    def _expandir(rotas):
        for r in rotas:
            orig = getattr(r, "original_router", None)  # _IncludedRouter (FastAPI novo): router lazy
            if orig is not None:
                yield from _expandir(orig.routes)
            else:
                yield r

    linhas = []
    for r in _expandir(_app().routes):
        metodos = ",".join(sorted(getattr(r, "methods", None) or ["WS"]))
        nome = getattr(getattr(r, "endpoint", None), "__name__", type(r).__name__)
        linhas.append(f"{metodos} {r.path} -> {nome}")
    return "\n".join(sorted(linhas)) + "\n"


def test_inventario_de_rotas_identico_ao_golden():
    atual = _inventario()
    if not GOLDEN.exists():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(atual, encoding="utf-8")
        return  # primeira geração = golden
    esperado = GOLDEN.read_text(encoding="utf-8")
    if atual != esperado:
        import difflib
        diff = "\n".join(difflib.unified_diff(
            esperado.splitlines(), atual.splitlines(),
            fromfile="golden/server_rotas.txt", tofile="atual", lineterm=""))
        raise AssertionError(f"rotas divergem do golden:\n{diff}")


def test_smoke_gets_deterministicos():
    from fastapi.testclient import TestClient
    with TestClient(_app(), raise_server_exceptions=False) as cli:
        # /status fica de fora: sobe o agente SIAFE (browser) — não é smoke offline.
        for rota in ("/api/agenda", "/api/lista", "/api/skills", "/api/ugs", "/api/sweeps/status"):
            r = cli.get(rota)
            assert r.status_code == 200, f"{rota} → {r.status_code}"
            corpo = r.json()
            if isinstance(corpo, dict) and "ok" in corpo:
                assert corpo["ok"] is True, f"{rota} → ok={corpo.get('ok')} erro={str(corpo.get('erro'))[:120]}"
