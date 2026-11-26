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
import logging
import os
import signal
import sys
import subprocess
import time

# Limiares p/ 2 vCPU + ~11GB RAM (ecossistema sempre-on já usa ~2GB/1 core).
MAX_LOAD1 = float(os.environ.get("VM_GUARD_MAX_LOAD", "1.7"))   # load 1min; >1.7 em 2 vCPU = saturando (legado)


def limite_carga() -> float:
    """Load1 acima do qual a máquina satura: 0,85 × núcleos (1,7 na VM-1 de 2 vCPU, como sempre). 26/11/2026: o limite
    fixo de 1,7 adiava à toa a captura do it-campo (24 núcleos) — o sensor `motor` da automelhoria contou 15× em 24 h.
    VM_GUARD_MAX_LOAD explícito continua valendo."""
    if os.environ.get("VM_GUARD_MAX_LOAD"):
        return float(os.environ["VM_GUARD_MAX_LOAD"])
    return round(0.85 * (os.cpu_count() or 2), 2)
MIN_FREE_GB = float(os.environ.get("VM_GUARD_MIN_FREE_GB", "2.5"))
PRESERVE = "chrome-jfn"   # o chromium persistente do ecossistema (porta 9222) — NUNCA matar
# navegador FIXO das sessões do it-campo (tools/itcampo_sei_paralelo.comando_navegador): fica aberto e logado entre
# processos e é reaproveitado pela sessão que reabre na mesma porta — órfão por um instante não é lixo
PRESERVE_FIXO = "navegador-fixo"


def _meminfo_available_gb() -> float:
    try:
        with open("/proc/meminfo") as f:
            for ln in f:
                if ln.startswith("MemAvailable:"):
                    return int(ln.split()[1]) / 1024 / 1024
    except Exception:
        logging.getLogger(__name__).debug("exceção tolerada em vm_guard", exc_info=True)
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
            if PRESERVE in cmd or PRESERVE_FIXO in cmd:
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
        except OSError as e:                       # processo já saiu ou não é nosso: registra e segue
            print(f"vm_guard: não matei {pid}: {e}", file=sys.stderr)
    limpar_perfis_orfaos()
    return n


def _cmdlines_vivas() -> list[str]:
    out = []
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                with open(f"/proc/{d}/cmdline", "rb") as f:
                    out.append(f.read().replace(b"\0", b" ").decode("utf-8", "ignore"))
            except OSError:
                continue
    return out


def limpar_perfis_orfaos(base: str = "/tmp") -> int:
    """Apaga perfis temporários do Chromium que NENHUM processo vivo usa. 26/11/2026: o rm -rf de todos os
    `/tmp/playwright_chromiumdev_profile-*` apagava o perfil de um navegador VIVO de outra captura simultânea."""
    import glob
    import shutil
    vivas = " ".join(_cmdlines_vivas())
    n = 0
    for p in glob.glob(os.path.join(base, "playwright_chromiumdev_profile-*")) + \
            glob.glob(os.path.join(base, ".org.chromium.*")):
        if p in vivas:
            continue
        shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.path.exists(p) and os.remove(p)
        n += 1
    return n


def preflight(max_load: float | None = None, min_free_gb: float = MIN_FREE_GB) -> tuple[bool, str]:
    """True se for seguro lançar trabalho pesado de browser/OCR agora."""
    max_load = limite_carga() if max_load is None else max_load
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


# ── Navegador do Claude (CDP 127.0.0.1:9333) ────────────────────────────────────────────────────
# 14-15/11/2026: ficou 18 h em higgsfield.ai com o gpu-process a 30 % de CPU constante (~5,4 h de CPU)
# e já chegou a 85 %. Não é órfão (tem dono, start.sh), então cleanup_orphans() não o vê. Regra: página
# que não é about:blank, parada na MESMA URL há > NAV_MAX_MIN e com a árvore do navegador acima de
# NAV_MAX_CPU % → volta para about:blank (Page.navigate). Nunca mata o processo nem fecha a aba.
NAV_CDP = os.environ.get("VM_GUARD_NAV_CDP", "http://127.0.0.1:9333")
NAV_PERFIL = "navegador-claude/profile"
NAV_MAX_MIN = float(os.environ.get("VM_GUARD_NAV_MAX_MIN", "30"))
NAV_MAX_CPU = float(os.environ.get("VM_GUARD_NAV_MAX_CPU", "25"))   # % de UM núcleo, soma da árvore
NAV_ESTADO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", ".navegador_claude_guard.json")


def _cpu_ticks_perfil(perfil: str = NAV_PERFIL) -> int:
    """Soma utime+stime de todos os processos cujo cmdline contém o perfil (lê /proc, sem pgrep -f)."""
    tot = 0
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            if perfil.encode() not in open(f"/proc/{p}/cmdline", "rb").read():
                continue
            r = open(f"/proc/{p}/stat").read().rsplit(")", 1)[1].split()
            tot += int(r[11]) + int(r[12])
        except (OSError, IndexError, ValueError):
            continue
    return tot


def _cpu_pct_perfil(segundos: float = 10.0) -> float:
    a = _cpu_ticks_perfil(); time.sleep(segundos); b = _cpu_ticks_perfil()
    return max(0, b - a) * 100.0 / os.sysconf("SC_CLK_TCK") / segundos


def guarda_navegador_claude(agora: float | None = None, cpu_pct=None, paginas=None,
                            navegar=None, estado_path: str = NAV_ESTADO) -> dict:
    """Uma passada da guarda. Dependências injetáveis para teste (cpu_pct, paginas, navegar)."""
    import json
    import urllib.request
    agora = time.time() if agora is None else agora
    if paginas is None:
        try:
            with urllib.request.urlopen(f"{NAV_CDP}/json", timeout=5) as r:
                paginas = [p for p in json.load(r) if p.get("type") == "page"]
        except (OSError, ValueError) as e:   # navegador fechado/sem CDP (URLError é OSError): nada a guardar
            return {"acao": "nenhuma", "motivo": f"CDP indisponível: {e.__class__.__name__}"}
    try:
        estado = json.load(open(estado_path))
    except (OSError, ValueError):
        estado = {}
    novo, pesadas = {}, []
    for p in paginas:
        pid_, url = p.get("id"), p.get("url", "")
        if not pid_ or url.startswith("about:") or url.startswith("chrome://"):
            continue
        ant = estado.get(pid_)
        desde = ant["desde"] if ant and ant.get("url") == url else agora
        novo[pid_] = {"url": url, "desde": desde}
        if (agora - desde) / 60 >= NAV_MAX_MIN:
            pesadas.append(p)
    res = {"acao": "nenhuma", "paginas": len(novo), "paradas": len(pesadas)}
    if pesadas:
        cpu = cpu_pct() if cpu_pct else _cpu_pct_perfil()
        res["cpu_pct"] = round(cpu, 1)
        if cpu >= NAV_MAX_CPU:
            navegar = navegar or _cdp_navegar_blank
            for p in pesadas:
                ok = navegar(p)
                res.setdefault("voltou_blank", []).append({"url": p.get("url", "")[:120], "ok": ok})
                if ok:
                    novo.pop(p.get("id"), None)
            res["acao"] = "about:blank"
    try:
        os.makedirs(os.path.dirname(estado_path), exist_ok=True)
        with open(estado_path + ".tmp", "w") as f:
            json.dump(novo, f)
        os.replace(estado_path + ".tmp", estado_path)
    except OSError as e:
        res["erro_estado"] = str(e)
    return res


def _cdp_navegar_blank(pagina: dict) -> bool:
    import json
    import websocket                          # websocket-client (já no .venv)
    try:
        ws = websocket.create_connection(pagina["webSocketDebuggerUrl"], timeout=10)
        ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": "about:blank"}}))
        ws.recv(); ws.close()
        return True
    except (OSError, KeyError, websocket.WebSocketException) as e:
        print(f"vm_guard: navegador não voltou a about:blank: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    import json
    if "--navegador" in sys.argv:
        r = guarda_navegador_claude()
        if r.get("acao") != "nenhuma" or "--verboso" in sys.argv:
            print(time.strftime("%F %T"), json.dumps(r, ensure_ascii=False))
        sys.exit(0)
    n = cleanup_orphans()
    ok, motivo = preflight()
    print(json.dumps({"orfaos_mortos": n, "seguro": ok, "estado": motivo,
                      "load1": _load1(), "free_gb": round(_meminfo_available_gb(), 1)}, ensure_ascii=False))
