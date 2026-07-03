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
CACHE = RAIZ / "data" / "sei_cache"
DB = RAIZ / "data" / "compliance.db"
PAUSA = RAIZ / "data" / ".pause_bombeiros"
PAUSA_SEI = RAIZ / "data" / ".pause_sei_sweep"
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


def _sweep_no_browser() -> bool:
    """Há um sweep segurando o browser AGORA? (sei_integra_completa NÃO usa browser_lock → nunca 2 browsers)."""
    try:
        return subprocess.run(["pgrep", "-f", r"tools\.sei_sweep|tools\.sei_bombeiros_sweep"],
                              stdout=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False


def _esperar_browser_livre(espera_max: int = 300) -> None:
    """Espera o sweep em voo soltar o browser (as pausas já impedem novo lote). Bounded; não trava."""
    t0 = time.time()
    while _sweep_no_browser() and time.time() - t0 < espera_max:
        time.sleep(10)


def _arquivado_ok(dir_arq: Path) -> bool:
    """True só se o arquivo tem CONTEÚDO real (>=1 texto/*.txt). Um STUB (manifest.json docs=0 de
    download que falhou) NÃO conta — senão a fila pula pra sempre e o processo nunca é baixado
    ('uns salvos, outros não'). Fix 2026-07-03; ver vault/aprendizados/sei-leitura-itkava."""
    txt = dir_arq / "texto"
    return txt.is_dir() and any(txt.glob("*.txt"))


def _valor_por_processo() -> dict:
    """Valor total pago (OB) por processo SEI — p/ priorizar o arquivo por EXPOSIÇÃO. {} se sem DB."""
    if not DB.exists():
        return {}
    import sqlite3
    con = sqlite3.connect(str(DB))
    try:
        rows = con.execute(
            "SELECT numero_sei, ROUND(SUM(valor),2) FROM ordens_bancarias "
            "WHERE numero_sei LIKE 'SEI-%/%/20%' GROUP BY numero_sei").fetchall()
        return {p: (v or 0) for p, v in rows}
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def _fila_geral() -> list[dict]:
    """Fila de arquivo de TODO o SEI: processos com cdp BOM (docs>0) ainda não arquivados, ordenados por
    EXPOSIÇÃO (valor da OB desc — arquiva o de maior risco primeiro). Cobre além dos bombeiros; o sweep
    geral já leu esses processos, aqui baixamos+organizamos a íntegra pública. Resumível (pula os OK)."""
    valores = _valor_por_processo()
    out: list[dict] = []
    for f in CACHE.glob("cdp_*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not (d.get("documentos") or []):
            continue
        num = d.get("numero", "")
        proc = _proc_limpo(num)
        if not proc or _arquivado_ok(ARQUIVO / proc.replace("/", "_")):
            continue
        out.append({"sei": num, "score": valores.get(num, 0)})
    out.sort(key=lambda e: -(e.get("score") or 0))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=int(os.environ.get("INTEGRA_FILA_MAX", "2")))
    ap.add_argument("--fila", default=str(RAIZ / "data" / "bombeiros_sei_fila.json"))
    ap.add_argument("--geral", action="store_true",
                    help="fila = TODO o SEI (cdp bons não arquivados, por valor), não só bombeiros")
    ap.add_argument("--segundos", type=int, default=int(os.environ.get("INTEGRA_FILA_SEGUNDOS", "0")),
                    help="orçamento de tempo (passe bounded); 0 = usa --max")
    args = ap.parse_args()

    # candidatos ordenados (não arquivados). Fonte: geral (todo o SEI) ou a fila json (bombeiros).
    if args.geral:
        candidatos = [c["sei"] for c in _fila_geral()]
        _log(f"fonte=GERAL: {len(candidatos)} processos com cdp bom ainda não arquivados")
    else:
        fila_path = Path(args.fila)
        if not fila_path.exists():
            _log(f"fila inexistente: {fila_path}")
            return 0
        fila = json.loads(fila_path.read_text(encoding="utf-8"))
        fila.sort(key=lambda e: -(e.get("score") or 0))
        candidatos = [e.get("sei", "") for e in fila]

    alvos = []
    for sei in candidatos:
        proc = _proc_limpo(sei)
        if not proc:
            continue
        if _arquivado_ok(ARQUIVO / proc.replace("/", "_")):
            continue                      # já arquivado COM conteúdo — resumível
        alvos.append(proc)
        if not args.segundos and len(alvos) >= args.max:
            break                         # sem orçamento de tempo → corta em --max (comportamento antigo)
    if not alvos:
        _log("fila drenada — nada a baixar")
        return 0

    # orçamento de tempo: processa até o deadline (velocidade sem derrubar a VM). Sem --segundos, roda os alvos.
    deadline = time.time() + args.segundos if args.segundos else None
    _log(f"rodada: {len(alvos)} candidato(s)"
         + (f", orçamento {args.segundos}s" if deadline else f" (max {args.max})"))
    # NUNCA 2 browsers (sei_integra_completa não usa browser_lock): pausa OS DOIS sweeps e espera o
    # lote em voo soltar o browser antes de baixar. Sem isto, a passe geral derruba a VM (2 chromium).
    PAUSA.touch()
    PAUSA_SEI.touch()
    _esperar_browser_livre()
    feitos = 0
    try:
        env = dict(os.environ, SEI_SEM_TG="1", PYTHONPATH=str(RAIZ))
        for proc in alvos:
            if deadline and time.time() > deadline:
                _log(f"orçamento de {args.segundos}s esgotado — encerrando limpo ({feitos} feitos)")
                break
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
            feitos += 1
            time.sleep(5)
    finally:
        PAUSA.unlink(missing_ok=True)
        PAUSA_SEI.unlink(missing_ok=True)
        _log(f"rodada encerrada — sweeps despausados ({feitos} arquivado(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
