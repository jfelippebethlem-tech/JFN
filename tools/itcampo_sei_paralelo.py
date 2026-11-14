#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""it-campo como nó de ÍNTEGRAS do SEI com N SESSÕES SIMULTÂNEAS (pedido do dono, 14/11/2026).

POR QUE EXISTE. A fila de íntegras andava ~25 processos/dia (177 novos em 7 dias, medido em 14/11) com um navegador
por máquina. O it-campo (Windows, 24 threads, 31 GB, WSL Ubuntu, Tailscale) roda várias sessões itkava ao mesmo
tempo. O dono autorizou levar a senha do SEI até lá e exigiu ver tudo na tela ("nada de janelas ocultas").

DESENHO (a VM-1 continua dona da verdade — banco, arquivo, painel; nada daqui escreve no acervo dela):
  base     ~/JFN-worker (clone git da VM-1 pelo Tailscale; `git pull --ff-only` a cada rodada)
  sessões  ~/JFN-sessoes/s1..sN = `git worktree` da base (código idêntico; data/, browser.lock e TMPDIR PRÓPRIOS:
           o mutex de navegador da casa é por árvore e a limpeza de órfãos do vm_guard não alcança o perfil alheio)
  rodada   1. VM-1 `sei_integra_vm2 exportar --no itcampo --validade-h 3` — mesma ordem da fila da VM-1
              (bombeiros → dinheiro → geral), SEM o que outro nó reservou (a VM-2 tem a dela); reserva por 3 h
           2. fatias DISJUNTAS por round-robin (cada sessão leva a sua parte da ordem de prioridade)
           3. uma JANELA por sessão (`cmd.exe /c start "JFN SEI sessão k/N" wsl.exe … tools/itcampo_sessao.sh`),
              navegador visível pelo WSLg; o título diz o processo e quantos foram feitos
           4. cada sessão entrega o próprio LOTE (`sei_integra_vm2 devolver` → `vm2_conferencia importar` na VM-1:
              md5, documentos × árvore, texto legível, amostra independente; reprovado ⇒ quarentena)
           5. métricas da rodada (processos/hora, erro, documentos vazios, s/documento) em
              `data/itcampo_rodadas.jsonl` daqui E da VM-1; batida `.integras_na_itcampo` na VM-1
  fora do ar  a reserva vale 3 h e é renovada a cada rodada: it-campo desligado ⇒ os processos voltam sozinhos
              para a VM-1/VM-2 (que já excluem só reservas frescas).

Controle (no WSL do it-campo):
  data/itcampo_n          nº de sessões (lido a cada rodada; degraus 2 → 4 → 6 → …)
  data/.pause_itcampo     pausa ENTRE rodadas (a rodada em curso termina e entrega)

Uso:
  python -m tools.itcampo_sei_paralelo rodar [--rodadas K] [--n N]      # orquestrador (janela visível)
  python -m tools.itcampo_sei_paralelo metricas --desde <byte do log>   # chamado por cada sessão
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
SESSOES = Path(os.environ.get("JFN_ITCAMPO_SESSOES", str(Path.home() / "JFN-sessoes")))
CFG_N = DATA / "itcampo_n"
PAUSA = DATA / ".pause_itcampo"
RODADAS = DATA / "itcampo_rodadas.jsonl"
PAINEL = DATA / "itcampo_montagem.log"          # o que a janela de status do Windows mostra
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
    with PAINEL.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")


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


# ───────────────────────────── orquestrador ─────────────────────────────

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


def fatiar(fila: list[dict], n: int) -> list[list[dict]]:
    """Fatias DISJUNTAS por round-robin: cada sessão pega a sua parte da ordem de prioridade. O score de cada
    fatia é a posição (o `--fila` reordena por score desc)."""
    fatias = [fila[i::n] for i in range(n)]
    for f in fatias:
        for j, e in enumerate(f):
            e["score"] = len(f) - j
    return fatias


def preparar(n: int) -> str:
    """Atualiza a base e põe cada worktree de sessão no mesmo commit. Devolve o commit."""
    r = _run(["git", "-C", str(RAIZ), "pull", "--ff-only", "-q"], timeout=300)
    if r.returncode != 0:
        painel(f"git pull falhou ({r.stderr.strip()[:120]}) — seguindo com o código que há")
    head = _run(["git", "-C", str(RAIZ), "rev-parse", "HEAD"]).stdout.strip()
    SESSOES.mkdir(parents=True, exist_ok=True)
    for k in range(1, n + 1):
        s = SESSOES / f"s{k}"
        if not (s / ".git").exists():
            _run(["git", "-C", str(RAIZ), "worktree", "prune"])
            r = _run(["git", "-C", str(RAIZ), "worktree", "add", "-q", "--detach", str(s), head], timeout=300)
            if r.returncode != 0:
                raise RuntimeError(f"worktree s{k}: {r.stderr.strip()[:200]}")
        else:
            _run(["git", "-C", str(s), "checkout", "-q", "--detach", head], timeout=300)
        for nome in (".venv", ".env"):
            if not (s / nome).exists():
                (s / nome).symlink_to(RAIZ / nome)
        (s / "data").mkdir(exist_ok=True)
        (s / "data" / ".siafe_host").write_text("jfn-core\n")       # SIAFE é sessão única, na VM-1
        (s / "tmp").mkdir(exist_ok=True)
    return head[:8]


def exportar(n: int) -> list[dict]:
    m = n * POR_SESSAO
    r = _ssh(f"cd {VM1_JFN} && PYTHONPATH=. nice -n 10 .venv/bin/python -m tools.sei_integra_vm2 exportar "
             f"--no {NO} --max {m} --validade-h {VALIDADE_H} --k-bombeiros {max(1, m // 4)}")
    if r.returncode != 0:
        raise RuntimeError(f"exportar na VM-1 falhou: {r.stderr.strip()[-200:]}")
    return json.loads(r.stdout)


def lancar(k: int, n: int, segundos: int) -> None:
    """Abre a JANELA da sessão k no Windows (visível, com título) — nunca processo escondido."""
    s = SESSOES / f"s{k}"
    distro = os.environ.get("WSL_DISTRO_NAME", "Ubuntu")
    subprocess.Popen(["cmd.exe", "/c", "start", f"JFN SEI sessão {k}/{n}", "wsl.exe", "-d", distro,
                      "--cd", str(s), "--", "bash", str(s / "tools" / "itcampo_sessao.sh"), str(k), str(n),
                      str(segundos)], cwd="/mnt/c", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def esperar(n: int, segundos: int, t0: float) -> list[int]:
    """Espera as N sessões terminarem (teto: orçamento + 40 min). Devolve as que não terminaram."""
    teto = t0 + segundos + 2400
    while True:
        faltam = [k for k in range(1, n + 1) if not (SESSOES / f"s{k}" / "data" / "itcampo_sessao_fim.json").exists()]
        estados = []
        for k in range(1, n + 1):
            try:
                estados.append(f"s{k}:" + (SESSOES / f"s{k}" / "data" / "itcampo_estado.txt").read_text().strip())
            except OSError:
                estados.append(f"s{k}:-")
        titulo(f"JFN SEI orquestrador — {n} sessões — {len(faltam)} rodando — {int((time.time()-t0)/60)} min")
        print(f"[{time.strftime('%T')}] " + "  ".join(estados), flush=True)
        if not faltam or time.time() > teto:
            return faltam
        time.sleep(60)


def agregar(n: int, t0: float, fila_n: int, commit: str) -> dict:
    procs: dict = {}
    lotes = {"aprovados": 0, "quarentena": 0, "nao_entregues": 0, "lote_nao_chegou": 0}
    for k in range(1, n + 1):
        d = SESSOES / f"s{k}" / "data"
        m = _ler_json(d / "itcampo_metricas.json") or {}
        procs.update(m.get("procs") or {})
        r = _ler_json(d / "itcampo_devolver.json") or {}
        lote = r.get("lote")
        if lote:
            lotes["aprovados"] += len(lote.get("aprovados") or [])
            lotes["quarentena"] += len(lote.get("reprovados") or {})
        elif r.get("status"):
            lotes["lote_nao_chegou"] += 1
        lotes["nao_entregues"] += len(r.get("nao_entregues") or {})
    dur = time.time() - t0
    tot = _totais(procs)
    rec = {"ts": time.strftime("%F %T"), "no": NO, "sessoes": n, "commit": commit, "fila_exportada": fila_n,
           "duracao_s": round(dur), **tot, **lotes,
           "proc_por_hora": round(tot["tentados"] / (dur / 3600), 1) if dur else None,
           "ok_por_hora": round(tot["ok"] / (dur / 3600), 1) if dur else None, "procs": procs}
    return rec


def registrar(rec: dict) -> None:
    linha = json.dumps(rec, ensure_ascii=False)
    with RODADAS.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")
    r = _ssh(f"cat >> {VM1_JFN}/data/itcampo_rodadas.jsonl", entrada=linha + "\n", timeout=120)
    if r.returncode == 0:
        _ssh(f"cd {VM1_JFN} && PYTHONPATH=. .venv/bin/python -m tools.sei_integra_vm2 batida --no {NO}", timeout=120)


def rodada(n: int, segundos: int) -> dict | None:
    t0 = time.time()
    commit = preparar(n)
    fila = exportar(n)
    painel(f"rodada: {n} sessões, código {commit}, VM-1 exportou {len(fila)} processo(s) (reserva de {VALIDADE_H:g} h)")
    if not fila:
        return None
    for k, fatia in enumerate(fatiar(fila, n), start=1):
        d = SESSOES / f"s{k}" / "data"
        (d / "itcampo_sessao_fim.json").unlink(missing_ok=True)
        for nome in ("itcampo_metricas.json", "itcampo_devolver.json", "itcampo_estado.txt"):
            (d / nome).unlink(missing_ok=True)
        (d / "fila_itcampo.json").write_text(json.dumps(fatia, ensure_ascii=False), encoding="utf-8")
        lancar(k, n, segundos)
        time.sleep(3)
    painel(f"{n} janela(s) de sessão abertas na tela — fatia de {segundos // 60} min cada")
    faltam = esperar(n, segundos, t0)
    if faltam:
        painel(f"sessões sem terminar no teto: {faltam} (seguem; a próxima rodada as reaproveita)")
    rec = agregar(n, t0, len(fila), commit)
    registrar(rec)
    painel(f"rodada medida: {rec['tentados']} tentados, {rec['ok']} ok, {rec['docs']} docs, "
           f"{rec['proc_por_hora']} proc/h, erro {rec['taxa_erro']}, docs vazios {rec['taxa_docs_vazios']}, "
           f"{rec['s_por_doc']} s/doc; lote: {rec['aprovados']} aprovados, {rec['quarentena']} em quarentena")
    return rec


def rodar(rodadas: int, n_fixo: int | None, segundos: int) -> int:
    feitas = 0
    while rodadas <= 0 or feitas < rodadas:
        if PAUSA.exists():
            titulo("JFN SEI orquestrador — PAUSADO (.pause_itcampo)")
            print(f"[{time.strftime('%T')}] pausado (data/.pause_itcampo) — confiro de novo em 5 min", flush=True)
            time.sleep(300)
            continue
        n = n_fixo or n_sessoes()
        try:
            rec = rodada(n, segundos)
        except (RuntimeError, subprocess.SubprocessError, OSError, ValueError) as exc:
            painel(f"rodada falhou: {str(exc)[:200]} — nova tentativa em 10 min")
            time.sleep(600)
            continue
        feitas += 1
        if rec is None:
            painel("fila vazia na VM-1 — nova consulta em 30 min")
            time.sleep(1800)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rodar")
    r.add_argument("--rodadas", type=int, default=0, help="0 = contínuo")
    r.add_argument("--n", type=int, default=0, help="sessões (padrão: data/itcampo_n)")
    r.add_argument("--segundos", type=int, default=FATIA_S)
    m = sub.add_parser("metricas")
    m.add_argument("--desde", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "metricas":
        print(json.dumps(metricas(a.desde), ensure_ascii=False))
        return 0
    return rodar(a.rodadas, a.n or None, a.segundos)


if __name__ == "__main__":
    sys.exit(main())
