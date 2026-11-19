"""Roda todos os detectores de `compliance_agent/padroes/` (ou um, com --id) e grava `data/padroes/<id>.json`.

Contrato em docs/PADROES-DE-IRREGULARIDADE.md. Uso: nice -n 19 .venv/bin/python -m tools.padroes_varrer [--id X] [--limite N]
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import pkgutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
SAIDA = RAIZ / "data" / "padroes"


def ids() -> list[str]:
    import compliance_agent.padroes as pac
    return sorted(m.name for m in pkgutil.iter_modules(pac.__path__) if not m.name.startswith("_"))


def rodizio(orcamento_s: float, todos: list[str] | None = None) -> list[str]:
    """Detectores desta rodada (19/11/2026: os 25 juntos levam ~5,2 h — não cabem numa tarefa do despachante): o de saída
    mais velha (ou nunca rodado) primeiro; entra enquanto a duração da última vez couber no que sobra. O primeiro entra
    sempre — senão um detector mais longo que o orçamento nunca rodaria."""
    def ultima(i: str) -> tuple[float, float]:
        f = SAIDA / f"{i}.json"
        if not f.exists():
            return 0.0, 0.0
        try:
            seg = float(json.loads(f.read_text(encoding="utf-8")).get("segundos") or 0)
        except (ValueError, OSError):
            seg = 0.0
        return f.stat().st_mtime, seg
    est = {i: ultima(i) for i in (todos if todos is not None else ids())}
    escolha, resta = [], orcamento_s
    for i in sorted(est, key=lambda i: est[i][0]):
        if not escolha or est[i][1] <= resta:
            escolha.append(i)
            resta -= est[i][1]
    return escolha


def rodar(id_: str, limite: int | None = None) -> dict:
    mod = importlib.import_module(f"compliance_agent.padroes.{id_}")
    t0 = time.time()
    r = mod.varrer(limite=limite)
    r["segundos"] = round(time.time() - t0, 1)
    SAIDA.mkdir(parents=True, exist_ok=True)
    tmp = SAIDA / f"{id_}.json.tmp"
    tmp.write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(SAIDA / f"{id_}.json")
    return r


def mem_disponivel_gb() -> float:
    try:
        for ln in open("/proc/meminfo"):
            if ln.startswith("MemAvailable:"):
                return int(ln.split()[1]) / 1e6
    except OSError:
        pass
    return 99.0


def em_paralelo(lista: list[str], n: int, limite: int | None = None, mem_min_gb: float | None = None) -> int:
    """Cada detector num processo próprio, `n` de cada vez (19/11/2026: réplica no it-campo — 24 núcleos; os 25 em
    série levam ~5,2 h na VM-1). Só começa um detector com `mem_min_gb` disponíveis (o WSL é dividido com o OCR da
    GPU e as sessões do SEI). Um detector que quebra não derruba os outros; o código de saída diz quantos falharam."""
    mem_min = float(os.environ.get("JFN_PADROES_MEM_MIN_GB", "4")) if mem_min_gb is None else mem_min_gb
    falhas = []

    def um(i: str) -> None:
        while mem_disponivel_gb() < mem_min:
            time.sleep(30)
        cmd = [sys.executable, "-m", "tools.padroes_varrer", "--id", i] + (["--limite", str(limite)] if limite else [])
        r = subprocess.run(cmd, cwd=str(RAIZ), capture_output=True, text=True)
        print((r.stdout.strip().splitlines() or [json.dumps({"id": i, "rc": r.returncode})])[-1], flush=True)
        if r.returncode != 0:
            falhas.append(i)
            print(json.dumps({"id": i, "rc": r.returncode, "erro": r.stderr.strip()[-300:]}, ensure_ascii=False),
                  flush=True)

    with ThreadPoolExecutor(max(1, n)) as ex:
        list(ex.map(um, lista))
    return len(falhas)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", action="append")
    ap.add_argument("--limite", type=int)
    ap.add_argument("--orcamento-s", type=float, help="rodízio: saída mais velha primeiro, até gastar o orçamento")
    ap.add_argument("--paralelo", type=int, default=1, help="N detectores ao mesmo tempo, um processo cada")
    a = ap.parse_args(argv)
    lista = a.id or (rodizio(a.orcamento_s) if a.orcamento_s else ids())
    if a.paralelo > 1 and len(lista) > 1:
        return 1 if em_paralelo(lista, a.paralelo, a.limite) else 0
    for i in lista:
        r = rodar(i, a.limite)
        print(json.dumps({"id": i, "universo": r.get("universo"), "achados": len(r.get("achados") or []),
                          "segundos": r["segundos"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
