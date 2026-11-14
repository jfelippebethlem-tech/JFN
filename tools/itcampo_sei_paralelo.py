#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""it-campo como nó de ÍNTEGRAS do SEI com N SESSÕES SIMULTÂNEAS E CONTÍNUAS (pedido do dono, 14/11/2026).

POR QUE EXISTE. A fila de íntegras andava ~25 processos/dia (177 novos em 7 dias, medido em 14/11) com um navegador
por máquina. O it-campo (Windows, 24 threads, 31 GB, WSL Ubuntu, Tailscale) roda várias sessões itkava ao mesmo
tempo. O dono autorizou levar a senha do SEI até lá, exigiu ver tudo na tela ("nada de janelas ocultas") e mandou
"nunca pare as capturas" — por isso nenhuma sessão espera a outra.

DESENHO (a VM-1 continua dona da verdade — banco, arquivo, painel; nada daqui escreve no acervo dela):
  base     ~/JFN-worker (clone git da VM-1 pelo Tailscale; o orquestrador faz `git pull --ff-only` a cada 10 min)
  sessões  ~/JFN-sessoes/s1..sN = `git worktree` da base (data/, browser.lock e TMPDIR PRÓPRIOS: o mutex de
           navegador da casa é por árvore e a limpeza de órfãos do vm_guard não alcança o perfil alheio)
  sessão k LAÇO CONTÍNUO na sua JANELA (`cmd.exe /c start "JFN SEI sessão k/N" wsl.exe …`):
           1. VM-1 `sei_integra_vm2 exportar --no itcampo<k> --validade-h 3` — mesma ordem da fila da VM-1
              (bombeiros → dinheiro → geral), SEM reserva alheia (VM-2 e as outras sessões) nem RESTRITO confirmado
           2. `sei_integra_fila.py --fila` (código da casa) por ~30 min; o título mostra processo e contagem, a janela
              mostra o progresso documento a documento (navegador headless: PDF em janela trava 450 s/doc, medido)
           3. entrega o LOTE (`sei_integra_vm2 devolver` → `vm2_conferencia importar` na VM-1: md5, documentos ×
              árvore, texto legível, amostra independente; reprovado ⇒ quarentena; restrito declarado ⇒ registro)
           4. métricas da volta em `data/itcampo_rodadas.jsonl` (base) e na VM-1; batida `.integras_na_itcampo`
           e recomeça na hora. Código novo na base ⇒ a sessão termina a volta e o orquestrador a reabre atualizada.
  orquest. garante as N janelas vivas (sessão viva = algum processo com cwd no worktree dela) e mostra o painel.
  fora do ar  reserva de 3 h renovada a cada volta e batida de 4 h: it-campo desligado ⇒ a fila volta sozinha
              para a VM-1/VM-2.

Controle (no WSL do it-campo):
  ~/JFN-worker/data/itcampo_n         nº de sessões (lido a cada minuto; sessão k > N termina a volta e fecha)
  ~/JFN-worker/data/.pause_itcampo    pausa (cada sessão termina e entrega a volta em curso, depois espera)

Uso:
  python -m tools.itcampo_sei_paralelo rodar                 # orquestrador (janela visível, tarefa JFN-SEI-Paralelo)
  python -m tools.itcampo_sei_paralelo sessao --k K          # uma sessão (aberta pelo orquestrador)
  python -m tools.itcampo_sei_paralelo relatorio             # ritmo por nº de sessões (degraus)
  python -m tools.itcampo_sei_paralelo metricas --desde <byte do log>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

DATA = RAIZ / "data"
BASE = Path(os.environ.get("JFN_ITCAMPO_BASE", str(Path.home() / "JFN-worker")))
SESSOES = Path(os.environ.get("JFN_ITCAMPO_SESSOES", str(Path.home() / "JFN-sessoes")))
CFG_N = BASE / "data" / "itcampo_n"
CFG_V = BASE / "data" / "itcampo_varredura_n"      # nº de sessões de VARREDURA (fatia 0/2 da VM-1)
PAUSA = BASE / "data" / ".pause_itcampo"
RODADAS = BASE / "data" / "itcampo_rodadas.jsonl"
PAINEL = BASE / "data" / "itcampo_montagem.log"          # painel do orquestrador
VM1 = os.environ.get("JFN_VM1_SSH", "vm1-ts")
VM1_JFN = os.environ.get("JFN_VM1_DIR", "/home/ubuntu/JFN")
NO = "itcampo"
FATIA_S = int(os.environ.get("JFN_ITCAMPO_FATIA", "1800"))
POR_SESSAO = int(os.environ.get("JFN_ITCAMPO_POR_SESSAO", "12"))   # ~2,5 min/processo medidos → folga
VALIDADE_H = 3.0
N_MAX = 12

_RX_INI = re.compile(r"^\[([^\]]+)\] ÍNTEGRA (\d{6}/\d{6}/\d{4})")
_RX_FIM = re.compile(r"^\[([^\]]+)\]\s+(\d{6}/\d{6}/\d{4}): (\w+)\s*$")
_RX_RESTRITO = re.compile(r"^\[[^\]]+\]\s+(\d{6}/\d{6}/\d{4}): SEM ÁRVORE .*RESTRITO")
# o que conta como ERRO DO MÉTODO (regra da casa: erro é do método até prova em contrário — nunca WAF/acesso)
STATUS_ERRO = {"erro", "timeout", "login"}


def _ts(s: str) -> float:
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        return 0.0


def painel(msg: str) -> None:
    linha = f"[{time.strftime('%F %T')}] {msg}"
    print(linha, flush=True)
    try:
        with PAINEL.open("a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass


def titulo(t: str) -> None:
    sys.stdout.write(f"\033]0;{t}\007")
    sys.stdout.flush()


# ───────────────────────────── métricas de UMA sessão ─────────────────────────────

def _ler_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def metricas_do_log(linhas: list[str], arquivo: Path, cache: Path) -> dict:
    """Mede a rodada de uma sessão a partir das linhas do `sei_integra_fila.log` e dos manifestos LOCAIS
    (antes do `devolver`, que os leva para o lote)."""
    inicio: dict[str, float] = {}
    procs: dict[str, dict] = {}
    restritos: set[str] = set()
    for ln in linhas:
        m = _RX_INI.match(ln)
        if m:
            inicio[m.group(2)] = _ts(m.group(1))
            continue
        m = _RX_RESTRITO.match(ln)
        if m:
            restritos.add(m.group(1))
            continue
        m = _RX_FIM.match(ln)
        if m and m.group(2) in inicio:
            proc, status = m.group(2), m.group(3)
            seg = max(0.0, _ts(m.group(1)) - inicio[proc])
            tag = proc.replace("/", "_")
            d = {"status": status, "segundos": round(seg, 1)}
            arq = _ler_json(arquivo / tag / "manifest.json")
            cman = _ler_json(cache / f"integra_{tag}" / "manifest.json")
            if isinstance(arq, dict):
                docs = [x for x in arq.get("docs") or [] if isinstance(x, dict)]
                d["docs"] = len(docs)
                d["docs_com_teor"] = sum(1 for x in docs if int(x.get("chars") or 0) >= 40)
            if isinstance(cman, dict):
                cd = [x for x in cman.get("docs") or [] if isinstance(x, dict)]
                d["arvore"] = int(cman.get("total_arvore") or 0)
                d["docs_falhos"] = sum(1 for x in cd if not x.get("ok"))
            d["restrito"] = proc in restritos
            procs[proc] = d
    return {"procs": procs, **_totais(procs)}


def _totais(procs: dict) -> dict:
    n = len(procs)
    st = [p["status"] for p in procs.values()]
    erros = sum(1 for p in procs.values() if p["status"] in STATUS_ERRO
                or (p["status"] == "sem_arvore" and not p.get("restrito")))
    docs = sum(p.get("docs", 0) for p in procs.values() if p["status"] == "ok")
    teor = sum(p.get("docs_com_teor", 0) for p in procs.values() if p["status"] == "ok")
    seg_ok = sum(p["segundos"] for p in procs.values() if p["status"] == "ok")
    return {"tentados": n, "ok": st.count("ok"), "vazio": st.count("vazio"),
            "sem_arvore": st.count("sem_arvore"), "restritos": sum(1 for p in procs.values() if p.get("restrito")),
            "erros_metodo": erros, "taxa_erro": round(erros / n, 3) if n else None,
            "docs": docs, "docs_com_teor": teor,
            "taxa_docs_vazios": round(1 - teor / docs, 3) if docs else None,
            "s_por_doc": round(seg_ok / docs, 1) if docs else None,
            "s_por_processo": round(sum(p["segundos"] for p in procs.values()) / n, 1) if n else None}


def metricas(desde: int) -> dict:
    from tools import sei_integra_fila as F
    try:
        with F.LOG.open("rb") as f:
            f.seek(desde)
            linhas = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        linhas = []
    return metricas_do_log(linhas, F.ARQUIVO, F.CACHE)


# ───────────────────────────── comum ─────────────────────────────

def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _ssh(cmd: str, entrada: str | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", VM1, cmd],
                          input=entrada, capture_output=True, text=True, timeout=timeout)


def n_sessoes(padrao: int = 2) -> int:
    try:
        return max(1, min(N_MAX, int(CFG_N.read_text().strip())))
    except (OSError, ValueError):
        return padrao


def n_varredura() -> int:
    try:
        return max(0, min(N_MAX, int(CFG_V.read_text().strip())))
    except (OSError, ValueError):
        return 0


def _dir(modo: str, k: int) -> Path:
    return SESSOES / (f"s{k}" if modo == "integras" else f"v{k}")


def _head(arvore: Path) -> str:
    return _run(["git", "-C", str(arvore), "rev-parse", "HEAD"]).stdout.strip()


def preparar_worktree(k: int, head: str, modo: str = "integras") -> Path:
    """Cria (ou põe no commit `head`) o worktree da sessão k, com venv/.env da base e trava do SIAFE."""
    s = _dir(modo, k)
    SESSOES.mkdir(parents=True, exist_ok=True)
    if not (s / ".git").exists():
        _run(["git", "-C", str(BASE), "worktree", "prune"])
        r = _run(["git", "-C", str(BASE), "worktree", "add", "-q", "--detach", str(s), head], timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"worktree s{k}: {r.stderr.strip()[:200]}")
    elif _head(s) != head:
        _run(["git", "-C", str(s), "checkout", "-q", "--detach", head], timeout=300)
    for nome in (".venv", ".env"):
        if not (s / nome).exists():
            (s / nome).symlink_to(BASE / nome)
    (s / "data").mkdir(exist_ok=True)
    (s / "data" / ".siafe_host").write_text("jfn-core\n")       # SIAFE é sessão única, na VM-1
    (s / "tmp").mkdir(exist_ok=True)
    return s


# ───────────────────────────── uma sessão (laço contínuo) ─────────────────────────────

def exportar_slot(k: int, m: int) -> list[dict]:
    r = _ssh(f"cd {VM1_JFN} && PYTHONPATH=. nice -n 10 .venv/bin/python -m tools.sei_integra_vm2 exportar "
             f"--no {NO}{k} --max {m} --validade-h {VALIDADE_H} --k-bombeiros {max(1, m // 4)}")
    if r.returncode != 0:
        raise RuntimeError(f"exportar na VM-1 falhou: {r.stderr.strip()[-200:]}")
    fila = json.loads(r.stdout)
    for j, e in enumerate(fila):
        e["score"] = len(fila) - j
    return fila


def _progresso(s: Path, estado: dict, parar) -> None:
    """Linha de progresso documento a documento (a saída da captura fica dentro da fila da casa)."""
    while not parar.wait(30):
        proc = estado.get("atual")
        if not proc:
            continue
        m = _ler_json(s / "data" / "sei_cache" / f"integra_{proc.replace('/', '_')}" / "manifest.json")
        if isinstance(m, dict):
            docs = [x for x in m.get("docs") or [] if isinstance(x, dict)]
            print(f"[{time.strftime('%F %T')}]     {proc}: documento {len(docs)} de {m.get('total_arvore')} "
                  f"({sum(1 for x in docs if x.get('ok'))} com teor)", flush=True)


def uma_volta(k: int, s: Path, segundos: int) -> dict | None:
    import threading
    fila = exportar_slot(k, POR_SESSAO)
    if not fila:
        return None
    n = n_sessoes()
    (s / "data" / "fila_itcampo.json").write_text(json.dumps(fila, ensure_ascii=False), encoding="utf-8")
    log = s / "data" / "sei_integra_fila.log"
    desde = log.stat().st_size if log.exists() else 0
    t0 = time.time()
    print(f"\n=== JFN SEI — sessão {k} de {n} — {time.strftime('%F %T')} — {len(fila)} processo(s) reservados, "
          f"orçamento {segundos // 60} min ===", flush=True)
    titulo(f"JFN SEI sessão {k}/{n} — começando ({len(fila)} na fila)")
    estado = {"atual": "", "feitos": 0}
    parar = threading.Event()
    threading.Thread(target=_progresso, args=(s, estado, parar), daemon=True).start()
    p = subprocess.Popen(["timeout", "-k", "120", "--foreground", str(segundos + 3900), str(s / ".venv/bin/python"),
                          "-u", "tools/sei_integra_fila.py", "--fila", "data/fila_itcampo.json",
                          "--segundos", str(segundos)], cwd=s, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    for ln in p.stdout:
        ln = ln.rstrip("\n")
        print(ln, flush=True)
        m = _RX_INI.match(ln)
        if m:
            estado["atual"] = m.group(2)
        elif _RX_FIM.match(ln):
            estado["feitos"] += 1
        titulo(f"JFN SEI sessão {k}/{n} — processo {estado['atual'] or '-'}, {estado['feitos']} feitos")
        (s / "data" / "itcampo_estado.txt").write_text(f"{estado['atual'] or '-'} {estado['feitos']}")
    rc = p.wait()
    parar.set()
    titulo(f"JFN SEI sessão {k}/{n} — medindo e entregando o lote à VM-1")
    print("--- medindo a volta e entregando o lote à VM-1 (conferência com quarentena) ---", flush=True)
    met = metricas_do_log(_linhas(log, desde), s / "data" / "sei_arquivo", s / "data" / "sei_cache")
    r = _run([str(s / ".venv/bin/python"), "-m", "tools.sei_integra_vm2", "devolver", "--desde", str(desde),
              "--fila", "data/fila_itcampo.json"], cwd=s, timeout=7200)
    try:
        dev = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except (ValueError, IndexError):
        dev = {}
    lote = dev.get("lote") or {}
    rec = {"ts": time.strftime("%F %T"), "no": NO, "slot": k, "sessoes": n, "commit": _head(s)[:8],
           "inicio": time.strftime("%F %T", time.localtime(t0)), "duracao_s": round(time.time() - t0), "rc": rc,
           **{c: v for c, v in met.items() if c != "procs"},
           "aprovados": len(lote.get("aprovados") or []), "quarentena": len(lote.get("reprovados") or {}),
           "lote_nao_chegou": bool(dev.get("status")) and not lote,
           "nao_entregues": len(dev.get("nao_entregues") or {}), "procs": met.get("procs")}
    registrar(rec)
    print(f"=== volta terminada: {rec['tentados']} tentados, {rec['ok']} ok, {rec['docs']} docs, "
          f"erro {rec['taxa_erro']}, lote {rec['aprovados']} aprovados / {rec['quarentena']} quarentena ===",
          flush=True)
    return rec


FILA_V_HORAS = 3


def volta_varredura(k: int, s: Path, segundos: int) -> dict | None:
    """Uma volta de VARREDURA (cache CDP, 1ª leitura do processo) na sub-fatia 2(k-1)/2M da metade da VM-1 —
    o fluxo da VM-2 (`tools/vm2_sweep_geral.py`), sem alteração: fila da VM-1, progresso e restritos da VM-1
    copiados para o `_pular` decidir igual, lote `sweep` conferido. Bate `.varredura_na_itcampo` na VM-1."""
    m = max(1, n_varredura())
    fatia = f"{2 * (k - 1)}/{2 * m}"
    fila = s / "data" / "fila_sweep_vm2.json"
    rotulo = s / "data" / "fila_sweep_fatia.txt"
    velha = (not fila.exists() or time.time() - fila.stat().st_mtime > FILA_V_HORAS * 3600
             or (rotulo.read_text().strip() if rotulo.exists() else "") != fatia)
    if velha:
        r = _ssh(f"cd {VM1_JFN} && PYTHONPATH=. nice -n 10 timeout 900 .venv/bin/python -m tools.vm2_sweep_geral "
                 f"exportar --max 120 --fatia {fatia}", timeout=1000)
        if r.returncode != 0:
            raise RuntimeError(f"exportar varredura na VM-1 falhou: {r.stderr.strip()[-200:]}")
        fila.write_text(r.stdout, encoding="utf-8")
        rotulo.write_text(fatia)
    if not _ler_json(fila):
        return None
    (s / "data" / "sei_cache").mkdir(parents=True, exist_ok=True)
    for orig, dest in ((f"{VM1_JFN}/data/sei_cache/sei_sweep_progress.json", s / "data/sei_cache/sei_sweep_progress.json"),
                       (f"{VM1_JFN}/data/sei_restritos.json", s / "data/sei_restritos.json")):
        r = _run(["rsync", "-a", f"{VM1}:{orig}", str(dest)], timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"sem o progresso da VM-1 o _pular releria o já lido: {r.stderr.strip()[:150]}")
    import shutil
    shutil.copy2(s / "data/sei_cache/sei_sweep_progress.json", s / "data/.vm2_prog_antes.json")
    shutil.copy2(s / "data/sei_restritos.json", s / "data/.vm2_restritos_antes.json")
    n = n_varredura()
    t0 = time.time()
    print(f"\n=== JFN SEI — VARREDURA {k} de {n} (sub-fatia {fatia}) — {time.strftime('%F %T')} — "
          f"{len(_ler_json(fila) or [])} na fila da VM-1 ===", flush=True)
    titulo(f"JFN SEI varredura {k}/{n} — lendo (sub-fatia {fatia})")
    env = dict(os.environ, JFN_SWEEP_FATIA=fatia, SEI_MAX_DOCS=os.environ.get("SEI_MAX_DOCS", "120"))
    p = subprocess.Popen(["timeout", "-k", "120", "--foreground", str(segundos + 1200), str(s / ".venv/bin/python"),
                          "-u", "-m", "tools.vm2_sweep_geral", "rodar", "--max", "8"], cwd=s, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace")
    lidos = 0
    for ln in p.stdout:
        ln = ln.rstrip("\n")
        print(ln, flush=True)
        mm = re.search(r"(\d{6}/\d{6}/\d{4})", ln)
        if mm:
            titulo(f"JFN SEI varredura {k}/{n} — processo {mm.group(1)}, {lidos} lote(s)")
            (s / "data" / "itcampo_estado.txt").write_text(f"{mm.group(1)} {lidos}")
    rc = p.wait()
    titulo(f"JFN SEI varredura {k}/{n} — entregando o lote à VM-1")
    r = _run([str(s / ".venv/bin/python"), "-m", "tools.vm2_sweep_geral", "devolver", "--desde", str(t0)],
             cwd=s, timeout=7200, env=env)
    try:
        dev = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except (ValueError, IndexError):
        dev = {}
    lote = dev.get("lote") or {}
    rec = {"ts": time.strftime("%F %T"), "no": NO, "modo": "varredura", "slot": k, "sessoes_varredura": n,
           "sessoes": n_sessoes(), "fatia": fatia, "commit": _head(s)[:8],
           "inicio": time.strftime("%F %T", time.localtime(t0)), "duracao_s": round(time.time() - t0), "rc": rc,
           "cdp": dev.get("cdp", 0), "com_docs": dev.get("com_docs", 0), "progresso": dev.get("progresso", 0),
           "aprovados": len(lote.get("aprovados") or []), "quarentena": len(lote.get("reprovados") or {}),
           "lote_nao_chegou": bool(dev.get("cdp")) and not lote}
    registrar(rec, batida="varredura")
    print(f"=== volta de varredura: {rec['cdp']} lidos ({rec['com_docs']} com documentos), lote "
          f"{rec['aprovados']} aprovados / {rec['quarentena']} quarentena ===", flush=True)
    return rec


def _linhas(log: Path, desde: int) -> list[str]:
    try:
        with log.open("rb") as f:
            f.seek(desde)
            return f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def sessao(k: int, segundos: int, modo: str = "integras") -> int:
    """Laço contínuo da sessão k na sua janela. Sai (e o orquestrador reabre) quando há código novo na base."""
    s = _dir(modo, k)
    limite = n_sessoes if modo == "integras" else n_varredura
    os.environ.update({"PYTHONPATH": str(s), "TMPDIR": str(s / "tmp"), "TZ": "America/Sao_Paulo",
                       "SEI_SEM_TG": "1", "JFN_CLAUDE_MAX_CONFERENCIA_VM2": "0"})
    # 24 threads / 15 GB no WSL: o limiar de 1,7 do vm_guard é para a VM-1 de 2 vCPU. Medido em 14/11 com 8 sessões
    # de íntegras + 4 de varredura: carga 21 (tesseract = ~8 núcleos) e 2 GB livres no WSL. O teto de carga sobe; o
    # PISO DE MEMÓRIA (1,5 GB) fica como válvula — o Windows do dono tinha só 3 GB livres, o WSL não cresce.
    os.environ.setdefault("VM_GUARD_MAX_LOAD", "28")
    os.environ.setdefault("VM_GUARD_MIN_FREE_GB", "1.5")
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    os.environ.setdefault("INTEGRA_TETO_PROCESSO_S", "3600")   # 707 docs × 2,7 s ≈ 32 min (o padrão 900 s os matava)      # tesseract: 1 thread por OCR (12 OCRs não disputam 24 núcleos)
    os.environ.pop("SEI_HEADED", None)     # headless: PDF em janela trava 450 s/doc (A/B medido em 14/11/2026)
    meu = _head(BASE)
    preparar_worktree(k, meu, modo)
    (s / "data" / "itcampo_sessao.pid").write_text(str(os.getpid()))
    while True:
        if k > limite():
            print(f"sessão {k} acima de N={limite()} — fechando", flush=True)
            return 0
        if _head(BASE) != meu:
            print("código novo na base — fechando para reabrir atualizada", flush=True)
            return 3
        if PAUSA.exists():
            titulo(f"JFN SEI sessão {k} — PAUSADA (.pause_itcampo)")
            time.sleep(60)
            continue
        try:
            rec = uma_volta(k, s, segundos) if modo == "integras" else volta_varredura(k, s, segundos)
        except (RuntimeError, subprocess.SubprocessError, OSError, ValueError) as exc:
            print(f"[{time.strftime('%F %T')}] volta falhou: {str(exc)[:200]} — nova tentativa em 5 min", flush=True)
            time.sleep(300)
            continue
        if rec is None:
            titulo(f"JFN SEI sessão {k} — fila vazia na VM-1, nova consulta em 20 min")
            time.sleep(1200)


def registrar(rec: dict, batida: str = "integras") -> None:
    linha = json.dumps(rec, ensure_ascii=False)
    with RODADAS.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")
    r = _ssh(f"cat >> {VM1_JFN}/data/itcampo_rodadas.jsonl", entrada=linha + "\n", timeout=120)
    if r.returncode != 0:
        return
    if batida == "integras":
        _ssh(f"cd {VM1_JFN} && PYTHONPATH=. .venv/bin/python -m tools.sei_integra_vm2 batida --no {NO}", timeout=120)
    elif rec.get("aprovados") or rec.get("progresso"):      # só bate quem ENTREGOU (a VM-1 cede a fatia por isso)
        _ssh(f"touch {VM1_JFN}/data/.varredura_na_itcampo", timeout=120)


# ───────────────────────────── orquestrador ─────────────────────────────

def viva(k: int, modo: str = "integras") -> bool:
    """Sessão k viva = algum processo com cwd dentro do worktree dela (vale para a janela, a fila e a captura)."""
    alvo = str(_dir(modo, k))
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            continue
        if cwd == alvo or cwd.startswith(alvo + "/"):
            return True
    return False


def lancar(k: int, n: int, modo: str = "integras") -> None:
    """Abre a JANELA da sessão k no Windows (visível, com título) — nunca processo escondido."""
    s = _dir(modo, k)
    distro = os.environ.get("WSL_DISTRO_NAME", "Ubuntu")
    nome = f"JFN SEI sessão {k}/{n}" if modo == "integras" else f"JFN SEI varredura {k}/{n}"
    subprocess.Popen(["cmd.exe", "/c", "start", nome, "wsl.exe", "-d", distro,
                      "--cd", str(s), "--", "bash", "-lc",
                      f"PYTHONPATH={s} {BASE}/.venv/bin/python -u -m tools.itcampo_sei_paralelo sessao --k {k} "
                      f"--modo {modo}; "
                      "echo; echo 'sessão encerrada — esta janela fecha em 20 s'; sleep 20"],
                     cwd="/mnt/c", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def rodar() -> int:
    ultimo_pull = 0.0
    while True:
        n = n_sessoes()
        if time.time() - ultimo_pull > 600:
            r = _run(["git", "-C", str(BASE), "pull", "--ff-only", "-q"], timeout=300)
            if r.returncode != 0:
                painel(f"git pull falhou ({r.stderr.strip()[:120]}) — seguindo com o código que há")
            ultimo_pull = time.time()
        head = _head(BASE)
        slots = [("integras", k, n) for k in range(1, n + 1)] + \
                [("varredura", k, n_varredura()) for k in range(1, n_varredura() + 1)]
        for modo, k, tot in slots:
            if PAUSA.exists() or viva(k, modo):
                continue
            try:
                preparar_worktree(k, head, modo)
            except (RuntimeError, OSError) as exc:
                painel(f"{modo} {k}: worktree falhou — {str(exc)[:150]}")
                continue
            lancar(k, tot, modo)
            painel(f"{modo} {k}/{tot} aberta em janela própria (código {head[:8]})")
            time.sleep(3)
        estados = []
        for modo, k, _ in slots:
            try:
                estados.append(f"{_dir(modo, k).name}:" + (_dir(modo, k) / "data" / "itcampo_estado.txt").read_text().strip())
            except OSError:
                estados.append(f"{_dir(modo, k).name}:-")
        vivas = sum(1 for modo, k, _ in slots if viva(k, modo))
        titulo(f"JFN SEI orquestrador — {vivas}/{len(slots)} sessões vivas" + (" — PAUSADO" if PAUSA.exists() else ""))
        print(f"[{time.strftime('%T')}] {vivas}/{len(slots)} vivas  " + "  ".join(estados), flush=True)
        time.sleep(60)


# ───────────────────────────── relatório por degrau ─────────────────────────────

def relatorio(registros: list[dict]) -> dict:
    """Ritmo por nº de sessões: processos/hora = tentados na janela de tempo em que aquele N vigorou."""
    por_n: dict[int, list[dict]] = {}
    for r in registros:
        if r.get("modo", "integras") != "integras":
            continue
        por_n.setdefault(int(r.get("sessoes") or 0), []).append(r)
    out = {}
    for n, rs in sorted(por_n.items()):
        ini = min(_ts(r.get("inicio") or r["ts"]) - (0 if r.get("inicio") else r.get("duracao_s", 0)) for r in rs)
        fim = max(_ts(r["ts"]) for r in rs)
        horas = max((fim - ini) / 3600, 1e-9)
        procs: dict = {}
        for r in rs:
            procs.update(r.get("procs") or {})
        t = _totais(procs)
        out[n] = {"voltas": len(rs), "horas": round(horas, 2), **t,
                  "proc_por_hora": round(t["tentados"] / horas, 1), "ok_por_hora": round(t["ok"] / horas, 1),
                  "docs_por_hora": round(t["docs"] / horas, 1),
                  "aprovados": sum(r.get("aprovados", 0) for r in rs),
                  "quarentena": sum(r.get("quarentena", 0) for r in rs)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rodar")
    s = sub.add_parser("sessao")
    s.add_argument("--k", type=int, required=True)
    s.add_argument("--segundos", type=int, default=FATIA_S)
    s.add_argument("--modo", choices=("integras", "varredura"), default="integras")
    sub.add_parser("relatorio")
    m = sub.add_parser("metricas")
    m.add_argument("--desde", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "metricas":
        print(json.dumps(metricas(a.desde), ensure_ascii=False))
        return 0
    if a.cmd == "sessao":
        return sessao(a.k, a.segundos, a.modo)
    if a.cmd == "relatorio":
        regs = [json.loads(ln) for ln in RODADAS.read_text(encoding="utf-8").splitlines() if ln.strip()] \
            if RODADAS.exists() else []
        print(json.dumps(relatorio(regs), ensure_ascii=False, indent=1))
        return 0
    return rodar()


if __name__ == "__main__":
    sys.exit(main())
