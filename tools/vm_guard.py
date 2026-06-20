#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Guarda-corpos da VM (2 vCPU) p/ trabalho de browser/OCR — evita o freeze/reboot que ocorreu
em 2026-06-20 (chromium órfãos acumulados + OCR de 60 docs em background sobreposto).

Uso típico:
    from tools.vm_guard import preflight, cleanup_orphans, guarded_launch_args
    cleanup_orphans()                 # mata MEUS órfãos (preserva o chrome-jfn :9222 do ecossistema)
    ok, motivo = preflight()
    if not ok: ...                    # adia/aborta
    browser = await pw.chromium.launch(args=guarded_launch_args())
    ...
    cleanup_orphans()                 # de novo no fim

Regras de ouro: (1) UM browser pesado por vez, em FOREGROUND (nunca sobrepor em background);
(2) OCR só dos docs que importam (<=6) e poucas páginas; (3) sempre limpar antes E depois."""
from __future__ import annotations
import os
import signal
import subprocess
import time

# Limiares p/ 2 vCPU + ~11GB RAM (ecossistema sempre-on já usa ~2GB/1 core).
MAX_LOAD1 = float(os.environ.get("VM_GUARD_MAX_LOAD", "1.7"))   # load 1min; >1.7 em 2 vCPU = saturando
MIN_FREE_GB = float(os.environ.get("VM_GUARD_MIN_FREE_GB", "2.5"))
PRESERVE = "chrome-jfn"   # o chromium persistente do ecossistema (porta 9222) — NUNCA matar


def _meminfo_available_gb() -> float:
    try:
        with open("/proc/meminfo") as f:
            for ln in f:
                if ln.startswith("MemAvailable:"):
                    return int(ln.split()[1]) / 1024 / 1024
    except Exception:
        pass
    return 99.0


def _load1() -> float:
    try:
        return os.getloadavg()[0]
    except Exception:
        try:
            return float(open("/proc/loadavg").read().split()[0])
        except Exception:
            return 0.0


def _ppid(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().split()[3])
    except Exception:
        return -1


def _meus_chromium_pids(somente_orfaos: bool = True) -> list[int]:
    """PIDs de chromium playwright órfãos (preserva o chrome-jfn :9222 E o browser EM USO).

    ``somente_orfaos=True`` (default): só mata processos cujo PAI MORREU (ppid==1) — assim NUNCA
    mata o chromium que um script MEU está usando agora (cujo ancestral python está vivo, ppid!=1).
    Quando o script termina/timeout, o chromium vira órfão (ppid=1) e é limpo na próxima chamada.
    Foi o bug de 2026-06-20: chamar isto no meio do OCR matava o próprio browser."""
    pids = []
    try:
        out = subprocess.run(["pgrep", "-f", "ms-playwright/chromium|user-data-dir=/tmp/playwright"],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return pids
    for line in out.split():
        try:
            pid = int(line)
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode("utf-8", "ignore")
            if PRESERVE in cmd:
                continue
            if somente_orfaos and _ppid(pid) != 1:
                continue  # pai vivo → browser em uso, NÃO matar
            pids.append(pid)
        except Exception:
            continue
    return pids


def cleanup_orphans() -> int:
    """Mata MEUS chromiums playwright (preserva o chrome-jfn :9222) e remove perfis temporários.
    Retorna quantos matou. Idempotente — chamar antes E depois de cada sessão de browser."""
    pids = _meus_chromium_pids()
    n = 0
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL); n += 1
        except Exception:
            pass
    try:
        subprocess.run("rm -rf /tmp/playwright_chromiumdev_profile-* /tmp/.org.chromium.* 2>/dev/null",
                       shell=True, timeout=10)
    except Exception:
        pass
    return n


def preflight(max_load: float = MAX_LOAD1, min_free_gb: float = MIN_FREE_GB) -> tuple[bool, str]:
    """True se for seguro lançar trabalho pesado de browser/OCR agora."""
    load = _load1()
    free = _meminfo_available_gb()
    if load > max_load:
        return False, f"load1={load:.2f} > {max_load} (2 vCPU saturando)"
    if free < min_free_gb:
        return False, f"mem disponível {free:.1f}GB < {min_free_gb}GB"
    return True, f"ok (load1={load:.2f}, free={free:.1f}GB)"


def wait_until_safe(timeout_s: int = 180, intervalo: int = 10) -> tuple[bool, str]:
    """Limpa órfãos e espera (até timeout) a VM ficar segura. Foreground, sem loops auto-reativos."""
    cleanup_orphans()
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        ok, motivo = preflight()
        if ok:
            return True, motivo
        time.sleep(intervalo)
        cleanup_orphans()
    return False, f"VM seguiu saturada após {timeout_s}s"


def guarded_launch_args(extra: list[str] | None = None) -> list[str]:
    """Args de chromium com teto de memória/recursos p/ 2 vCPU."""
    # NOTA: NÃO usar --js-flags=--max-old-space-size nem --renderer-process-limit baixo:
    # derrubam o renderer nas frames pesadas do SEI ("Target page/context/browser closed").
    args = [
        "--no-sandbox", "--ignore-certificate-errors",
        "--disable-dev-shm-usage",            # não usa /dev/shm (pequeno) → menos OOM, sem matar renderer
        "--disable-gpu", "--disable-extensions",
        "--disable-background-networking",
    ]
    return args + (extra or [])


if __name__ == "__main__":
    import json
    n = cleanup_orphans()
    ok, motivo = preflight()
    print(json.dumps({"orfaos_mortos": n, "seguro": ok, "estado": motivo,
                      "load1": _load1(), "free_gb": round(_meminfo_available_gb(), 1)}, ensure_ascii=False))
