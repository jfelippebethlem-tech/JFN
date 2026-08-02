#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compara as falhas de uma rodada com a BASE conhecida — o critério é DELTA ZERO, não verde absoluto.

POR QUE ASSIM. A suíte tem 436 arquivos / ~3.900 testes e um conjunto de falhas que são de AMBIENTE,
não de código: `tests/BASE-FALHAS-VM2.txt` registra as 50 medidas na VM-2 (base ausente, sem Chrome,
sem chave). Exigir "0 falhas" numa máquina que não tem `data/compliance.db` transforma o gate em
alarme permanente — e alarme permanente é alarme desligado. O handoff da casa já mandava comparar
**nome a nome**, porque contagem igual pode ser 50 falhas DIFERENTES; o que faltava era a ferramenta.

Regras:
  • falha NOVA (não está em nenhuma base)  -> regressão, exit 1
  • falha que SUMIU (está na base, passou) -> ganho; avisa e manda tirar da base
  • falha conhecida que continua           -> tolerada, sem barulho

Uso:
    pytest ... -q -rf | tee /tmp/lote.log
    python -m tools.ci_delta /tmp/lote.log --base tests/BASE-FALHAS-VM2.txt [--base outra.txt]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_RE_FAILED = re.compile(r"^(?:FAILED|ERROR)\s+(\S+?)(?:\s+-\s+.*)?$")


def falhas_do_log(texto: str) -> set[str]:
    achadas = set()
    for ln in texto.splitlines():
        m = _RE_FAILED.match(ln.strip())
        if m:
            achadas.add(m.group(1))
    return achadas


def base_conhecida(caminhos: list[Path]) -> set[str]:
    conhecidas: set[str] = set()
    for p in caminhos:
        if not p.exists():
            print(f"[ci_delta] base ausente, ignorada: {p}", file=sys.stderr)
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            m = _RE_FAILED.match(ln)
            conhecidas.add(m.group(1) if m else ln)
    return conhecidas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log", type=Path, nargs="+", help="log(s) do pytest (com -rf)")
    ap.add_argument("--base", type=Path, action="append", default=[],
                    help="arquivo(s) de falhas conhecidas; pode repetir")
    a = ap.parse_args()

    agora: set[str] = set()
    for lg in a.log:
        agora |= falhas_do_log(lg.read_text(encoding="utf-8", errors="replace"))
    conhecidas = base_conhecida(a.base or [Path("tests/BASE-FALHAS-VM2.txt")])

    novas = sorted(agora - conhecidas)
    curadas = sorted(conhecidas - agora)

    print(f"[ci_delta] falhas nesta rodada: {len(agora)} | conhecidas na base: {len(conhecidas)}")
    if curadas:
        print(f"\n[ci_delta] ✅ {len(curadas)} falha(s) da base PASSARAM — tire da base e trave o ganho:")
        for t in curadas:
            print(f"    {t}")
    if novas:
        print(f"\n[ci_delta] ❌ {len(novas)} falha(s) NOVA(S) — regressão:")
        for t in novas:
            print(f"    {t}")
        return 1
    print("\n[ci_delta] ✅ delta zero — nenhuma falha nova.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
