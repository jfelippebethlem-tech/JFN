# -*- coding: utf-8 -*-
"""
validate_capabilities — valida o contrato único capabilities.yaml (JFN 2.0, Onda 0).

Checa: (1) schema mínimo de cada capacidade; (2) ids únicos; (3) que toda capacidade HTTP marcada
status: PRONTO tenha a rota declarada existente em server.py; (4) status válido (PRONTO | "ONDA N").
Sai com código != 0 se houver erro (uso em CI / pre-commit). Não altera nada.

Uso: cd ~/JFN && PYTHONPATH=. .venv/bin/python -m tools.validate_capabilities
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parent.parent
_YAML = _REPO / "capabilities.yaml"
_SERVER = _REPO / "server.py"

_OBRIGATORIOS = {"id", "agente", "dominio", "tipo", "status", "descricao"}
_STATUS_RE = re.compile(r"^(PRONTO|ONDA \d+)$")


def _rotas_no_server() -> set[str]:
    """Extrai os paths registrados no app: server.py (@app.*) + rotas/*.py (@router.*, split 2026-07-06)."""
    if not _SERVER.exists():
        return set()
    fontes = [_SERVER] + sorted((_REPO / "rotas").glob("*.py"))
    rotas: set[str] = set()
    for f in fontes:
        txt = f.read_text(encoding="utf-8")
        rotas |= set(re.findall(r'@(?:app|router)\.(?:get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']', txt))
    return rotas


def validar() -> list[str]:
    erros: list[str] = []
    if not _YAML.exists():
        return [f"capabilities.yaml ausente em {_YAML}"]
    try:
        doc = yaml.safe_load(_YAML.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return [f"YAML inválido: {e}"]

    caps = (doc or {}).get("capacidades") or []
    if not caps:
        return ["capabilities.yaml sem 'capacidades'"]

    rotas_server = _rotas_no_server()
    vistos: set[str] = set()
    for c in caps:
        cid = c.get("id", "<sem id>")
        faltam = _OBRIGATORIOS - set(c)
        if faltam:
            erros.append(f"[{cid}] faltam campos: {sorted(faltam)}")
        if cid in vistos:
            erros.append(f"[{cid}] id duplicado")
        vistos.add(cid)
        st = str(c.get("status", ""))
        if not _STATUS_RE.match(st):
            erros.append(f"[{cid}] status inválido: {st!r} (use PRONTO ou 'ONDA N')")
        # rota PRONTA tem que existir no server (só http; cli não tem rota)
        if c.get("tipo") == "http" and st == "PRONTO":
            rota = c.get("rota", "")
            # normaliza paths com {param} — compara o template literal
            if rota not in rotas_server:
                erros.append(f"[{cid}] rota PRONTO ausente em server.py: {rota}")
    return erros


def main() -> int:
    erros = validar()
    if erros:
        print("❌ capabilities.yaml INVÁLIDO:")
        for e in erros:
            print(f"  - {e}")
        return 1
    doc = yaml.safe_load(_YAML.read_text(encoding="utf-8"))
    caps = doc["capacidades"]
    prontas = sum(1 for c in caps if c.get("status") == "PRONTO")
    ondas = sum(1 for c in caps if str(c.get("status", "")).startswith("ONDA"))
    print(f"✅ capabilities.yaml OK — {len(caps)} capacidades ({prontas} PRONTO, {ondas} em onda).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
