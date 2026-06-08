#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verifica se uma chave Gemini já está no pool de rotação (dedup) — JFN 2.0.

Uso: PYTHONPATH=. .venv/bin/python -m tools.check_gemini_key "AQ.Ab8RN6..."
Compara por fingerprint sha1[:8] contra o pool em ~/.hermes/auth.json + os .env. NÃO imprime a chave.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


def _fps_no_pool() -> set[str]:
    fps: set[str] = set()
    auth = Path.home() / ".hermes" / "auth.json"
    if auth.exists():
        try:
            pool = json.loads(auth.read_text(encoding="utf-8")).get("credential_pool", {})
            for k in re.findall(r"AQ\.Ab8RN6[A-Za-z0-9_-]{40,}|AIza[0-9A-Za-z_-]{30,}", json.dumps(pool)):
                fps.add(hashlib.sha1(k.encode()).hexdigest()[:8])
        except Exception:
            pass
    for envf in [Path.home() / ".hermes/.env", Path.home() / "JFN/.env"]:
        if envf.exists():
            for k in re.findall(r"AQ\.Ab8RN6[A-Za-z0-9_-]{40,}|AIza[0-9A-Za-z_-]{30,}", envf.read_text()):
                fps.add(hashlib.sha1(k.encode()).hexdigest()[:8])
    return fps


def checar(chave: str) -> dict:
    fp = hashlib.sha1(chave.strip().encode()).hexdigest()[:8]
    pool = _fps_no_pool()
    return {"fingerprint": fp, "ja_no_pool": fp in pool, "total_no_pool": len(pool)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("uso: python -m tools.check_gemini_key <CHAVE>")
        sys.exit(1)
    r = checar(sys.argv[1])
    print(f"fingerprint={r['fingerprint']} | {'JÁ NO POOL (repetida)' if r['ja_no_pool'] else 'NOVA (adicionar)'} "
          f"| total no pool: {r['total_no_pool']}")
