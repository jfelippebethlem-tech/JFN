# -*- coding: utf-8 -*-
"""Paridade da divisão de `rotas/investigacao.py` (O7.6, 2026-11-25).

As 106 rotas que moravam em `rotas/investigacao.py` foram repartidas em 7 módulos temáticos sem mudar
comportamento. O inventário de ANTES (método, caminho, nome da função, assinatura — na ordem de registro do app)
está congelado em `tests/fixtures/rotas_investigacao_inventario.json`. Este teste falha se:

1. alguma rota sumir, duplicar, mudar de nome/assinatura ou sair do módulo para onde foi movida;
2. a ordem RELATIVA das rotas dentro de cada módulo mudar (mover é copiar o bloco, não reordenar);
3. aparecer um par de rotas que possa casar a mesma URL (`/x/{id}` × `/x/estado`) envolvendo estas rotas, ou a
   ordem de um par já existente se inverter — o FastAPI entrega à PRIMEIRA que casa.
"""
import inspect
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "rotas_investigacao_inventario.json"

os.environ.setdefault("JFN_LEX_LER_SEI", "0")
os.environ.setdefault("JFN_LEX_DISCURSIVO", "0")
os.environ.setdefault("JFN_VEREDITO_LLM_DISABLED", "1")


def _rotas_do_app() -> list[dict]:
    sys.path.insert(0, str(REPO))
    import server

    def _expandir(rotas):
        for r in rotas:
            orig = getattr(r, "original_router", None)  # _IncludedRouter (FastAPI novo): router lazy
            if orig is not None:
                yield from _expandir(orig.routes)
            else:
                yield r

    out = []
    for r in _expandir(server.app.routes):
        ep = getattr(r, "endpoint", None)
        out.append({"metodos": sorted(getattr(r, "methods", None) or ["WS"]), "path": r.path,
                    "nome": getattr(ep, "__name__", type(r).__name__),
                    "assinatura": str(inspect.signature(ep)) if ep else None,
                    "modulo": getattr(ep, "__module__", None)})
    return out


def _chave(x: dict) -> tuple:
    return tuple(x["metodos"]), x["path"], x["nome"], x["assinatura"]


def _regex(path: str) -> re.Pattern:
    partes = re.split(r"(\{[^}]+\})", path)
    return re.compile("^" + "".join((".+" if ":path" in p else "[^/]+") if p.startswith("{") else re.escape(p)
                                    for p in partes) + "$")


def _podem_colidir(a: dict, b: dict) -> bool:
    if not set(a["metodos"]) & set(b["metodos"]):
        return False
    if a["path"] == b["path"]:
        return True
    amostra = lambda p: re.sub(r"\{[^}]+\}", "zz9", p)  # noqa: E731
    return bool(_regex(a["path"]).match(amostra(b["path"])) or _regex(b["path"]).match(amostra(a["path"])))


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_mesmas_106_rotas_cada_uma_no_modulo_para_onde_foi():
    esperado = _fixture()["rotas"]
    assert len(esperado) == 106
    modulos = {x["modulo"] for x in esperado}
    atual = [x for x in _rotas_do_app() if x["modulo"] in modulos]
    assert sorted(map(_chave, atual)) == sorted(map(_chave, esperado)), "rota sumida/duplicada/renomeada na divisão"
    onde = {_chave(x): x["modulo"] for x in atual}
    assert {_chave(x): x["modulo"] for x in esperado} == onde


def test_ordem_relativa_preservada_dentro_de_cada_modulo():
    esperado = _fixture()["rotas"]
    atual = _rotas_do_app()
    for mod in {x["modulo"] for x in esperado}:
        antes = [_chave(x) for x in esperado if x["modulo"] == mod]
        depois = [_chave(x) for x in atual if x["modulo"] == mod]
        assert depois == antes, f"{mod}: ordem de registro mudou"


def test_pares_que_podem_casar_a_mesma_url_mantem_a_ordem():
    fx = _fixture()
    modulos = {x["modulo"] for x in fx["rotas"]}
    atual = _rotas_do_app()
    pares = []
    for i, a in enumerate(atual):
        for b in atual[i + 1:]:
            if (a["modulo"] in modulos or b["modulo"] in modulos) and _podem_colidir(a, b):
                pares.append([f"{','.join(a['metodos'])} {a['path']}", f"{','.join(b['metodos'])} {b['path']}"])
    assert pares == fx["pares_que_colidem"], "par de rotas que casa a mesma URL surgiu ou inverteu a ordem"


def test_controle_positivo_do_detector_de_colisao():
    """O detector de par tem de enxergar o caso clássico — senão o teste acima passaria vazio por cegueira."""
    a = {"metodos": ["GET"], "path": "/api/x/{id}"}
    assert _podem_colidir(a, {"metodos": ["GET"], "path": "/api/x/estado"})
    assert _podem_colidir({"metodos": ["GET"], "path": "/api/p/{n:path}"}, {"metodos": ["GET"], "path": "/api/p/a/b"})
    assert not _podem_colidir(a, {"metodos": ["POST"], "path": "/api/x/estado"})
    assert not _podem_colidir(a, {"metodos": ["GET"], "path": "/api/y/estado"})
