#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drena a FILA de íntegras SEI: baixa N processos por rodada (maior score
primeiro), arquiva (txt+fases+fotos) e sai. Resumível: pula o que já está em
data/sei_arquivo/. Serializa com o sweep via data/.pause_bombeiros.

    .venv/bin/python tools/sei_integra_fila.py [--max 2] [--fila data/bombeiros_sei_fila.json]

Agendado por deploy/systemd/jfn-integra-fila.timer (madrugada). Sem Telegram
(SEI_SEM_TG=1) — a íntegra vai para o ARQUIVO; quem quiser o PDF no chat usa
tools/sei_integra_completa.py direto. Ver docs/PLAYBOOK-SEI.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ARQUIVO = RAIZ / "data" / "sei_arquivo"
PAUSA = RAIZ / "data" / ".pause_bombeiros"
LOG = RAIZ / "data" / "sei_integra_fila.log"
PY = str(RAIZ / ".venv" / "bin" / "python")


def _log(msg: str) -> None:
    linha = f"[{time.strftime('%F %T')}] {msg}"
    print(linha, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")


def _proc_limpo(sei: str) -> str:
    m = re.search(r"(\d{6})/(\d{6})/(\d{4})", sei or "")
    return f"{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=int(os.environ.get("INTEGRA_FILA_MAX", "2")))
    ap.add_argument("--fila", default=str(RAIZ / "data" / "bombeiros_sei_fila.json"))
    args = ap.parse_args()

    fila_path = Path(args.fila)
    if not fila_path.exists():
        _log(f"fila inexistente: {fila_path}")
        return 0
    fila = json.loads(fila_path.read_text(encoding="utf-8"))
    fila.sort(key=lambda e: -(e.get("score") or 0))

    alvos = []
    for e in fila:
        proc = _proc_limpo(e.get("sei", ""))
        if not proc:
            continue
        tag = proc.replace("/", "_")
        if (ARQUIVO / tag / "manifest.json").exists():
            continue                      # já arquivado — resumível
        alvos.append(proc)
        if len(alvos) >= args.max:
            break
    if not alvos:
        _log("fila drenada — nada a baixar")
        return 0

    _log(f"rodada: {len(alvos)} íntegra(s) → {alvos}")
    PAUSA.touch()                         # serializa com o sweep (1 browser)
    try:
        env = dict(os.environ, SEI_SEM_TG="1", PYTHONPATH=str(RAIZ))
        for proc in alvos:
            _log(f"ÍNTEGRA {proc} …")
            rc = subprocess.run([PY, "tools/sei_integra_completa.py", proc],
                                cwd=RAIZ, env=env, timeout=900,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.STDOUT).returncode
            _log(f"  download rc={rc}")
            rc2 = subprocess.run([PY, "tools/sei_arquivar.py", proc],
                                 cwd=RAIZ, env=env, timeout=900,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.STDOUT).returncode
            _log(f"  arquivar rc={rc2}")
            time.sleep(5)
    finally:
        PAUSA.unlink(missing_ok=True)
        _log("rodada encerrada — sweep despausado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
