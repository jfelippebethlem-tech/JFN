# -*- coding: utf-8 -*-
"""O4.1 — contrato de camada "dominio não importa I/O" (plano mestre v2, §3.9), sem depender do import-linter.

Mesma regra do `.importlinter` da raiz (contrato `dominio-sem-io`). Duas checagens:
1. AST: todo `import`/`from … import` de `compliance_agent/dominio/*.py` (inclusive dentro de função) é stdlib pura,
   o próprio domínio, ou um dos módulos do legado listados em `PERMITIDOS` (puros, conferidos aqui) ou
   `IGNORE_IMPORTS` (ponte tolerada; lista que só encolhe — a mesma do `.importlinter`);
2. execução: importar o domínio inteiro num processo limpo não carrega nenhum módulo de I/O além do que o
   `compliance_agent/__init__` já carrega.
"""
from __future__ import annotations

import ast
import configparser
import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DOMINIO = RAIZ / "compliance_agent" / "dominio"

STDLIB_OK = {"__future__", "re", "dataclasses", "enum", "typing", "functools", "itertools", "collections",
             "datetime", "decimal", "unicodedata", "math"}
PERMITIDOS = {"compliance_agent.cpf_cnpj"}                     # puro: só `re` (conferido abaixo)
IGNORE_IMPORTS = {("compliance_agent.dominio.pagamento", "compliance_agent.cruzamentos_intel")}
PROIBIDOS = ("fastapi", "starlette", "uvicorn", "sqlalchemy", "alembic", "psycopg", "psycopg2", "apsw", "sqlite3",
             "requests", "httpx", "aiohttp", "urllib3", "urllib", "socket", "subprocess", "anthropic", "openai",
             "google", "playwright", "patchright", "selenium", "rotas", "compliance_agent.rotas",
             "compliance_agent.database", "compliance_agent.llm", "compliance_agent.collectors")


def _imports(arquivo: Path) -> set[str]:
    out = set()
    for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            out |= {a.name for a in no.names}
        elif isinstance(no, ast.ImportFrom):
            assert no.level == 0, f"{arquivo.name}: import relativo — use o caminho absoluto"
            out.add(no.module)
    return out


def _proibido(mod: str) -> bool:
    return any(mod == p or mod.startswith(p + ".") for p in PROIBIDOS)


def test_dominio_so_importa_o_permitido():
    arquivos = sorted(DOMINIO.glob("*.py"))
    assert {a.stem for a in arquivos} >= {"__init__", "digitos", "processo_id", "documento_id", "contrato_id",
                                         "pagamento", "estados"}
    violacoes = []
    for a in arquivos:
        origem = f"compliance_agent.dominio.{a.stem}"
        for mod in _imports(a):
            ok = (mod.split(".")[0] in STDLIB_OK or mod.startswith("compliance_agent.dominio")
                  or mod in PERMITIDOS or (origem, mod) in IGNORE_IMPORTS)
            if not ok or _proibido(mod):
                violacoes.append(f"{origem} -> {mod}")
    assert not violacoes, violacoes


def test_permitidos_do_legado_sao_puros():
    for mod in PERMITIDOS:
        arq = RAIZ / (mod.replace(".", "/") + ".py")
        assert _imports(arq) <= STDLIB_OK, (mod, _imports(arq) - STDLIB_OK)


def test_importlinter_tem_o_mesmo_contrato():
    cfg = configparser.ConfigParser()
    cfg.read(RAIZ / ".importlinter", encoding="utf-8")
    c = cfg["importlinter:contract:dominio-sem-io"]
    assert c["type"] == "forbidden" and c["source_modules"].split() == ["compliance_agent.dominio"]
    proibidos_ini = set(c["forbidden_modules"].split())
    assert proibidos_ini <= set(PROIBIDOS)
    ignore = {tuple(x.strip() for x in ln.split("->")) for ln in c["ignore_imports"].strip().splitlines()}
    assert ignore == IGNORE_IMPORTS


def test_importar_o_dominio_nao_carrega_io():
    codigo = (
        "import sys, json, importlib; import compliance_agent; antes = set(sys.modules); "
        "[importlib.import_module('compliance_agent.dominio.' + m) for m in "
        "('digitos','processo_id','documento_id','contrato_id','pagamento','estados')]; "
        "print(json.dumps(sorted(set(sys.modules) - antes)))"
    )
    r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    novos = json.loads(r.stdout.strip().splitlines()[-1])
    assert not [m for m in novos if _proibido(m)], novos
    assert "compliance_agent.cruzamentos_intel" not in novos   # a ponte só carrega quando `ob_paga_sql` é chamada
