#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VM-2 como nó de cálculo das ÍNTEGRAS do SEI — as duas pontas num arquivo só.

POR QUE EXISTE. Medido em 13/11/2026: a VM-1 (jfn-core) roda com load 10-13 à tarde e à noite (sweep SEI,
OCR, navegadores de agentes) e a fila de íntegras se ADIA por carga — na madrugada de 13/11 a rodada `--geral`
de 2 h tentou 3 processos e encerrou com "três adiamentos seguidos por carga". A VM-2 (JFN-Agent-2) tem
load ~0,5. O SEI aceita a mesma conta em duas máquinas ao mesmo tempo: os sweeps das duas capturam juntos
desde 28/07 (fatias 0/2 e 1/2), com rc=0 nos dois lados no mesmo horário.

DESENHO (a VM-1 continua dona da verdade — banco, arquivo, painel):
  1. VM-2 → `ssh vm1 … exportar`: a VM-1 monta a fila com o MESMO critério de `sei_integra_fila`
     (caso ativo dos bombeiros → fila por dinheiro pago → geral: inscritos, não arquivados, re-ler por OB),
     filtra o que já tem conteúdo e o que voltou vazio há < 7 dias, e grava a RESERVA dos que despachou.
  2. VM-2 roda `sei_integra_fila.py --fila <exportada>` no clone git `~/JFN-worker` (código idêntico ao da VM-1).
  3. VM-2 → `devolver`: rsync de `data/sei_arquivo/<proc>/` e `data/sei_cache/integra_<proc>/` para a VM-1
     (caminho COMPLETO no destino; md5 do manifesto conferido nas duas pontas), e as linhas da rodada entram em
     `data/sei_integra_fila.log` da VM-1 — é dele que o motor `sei-integras` do AO VIVO mede o efeito. Só
     entra "proc: ok" no log da VM-1 o que CHEGOU lá; o que não chegou é reescrito como `nao-entregue`.
  4. `batida`: `data/.integras_na_vm2` na VM-1. Enquanto fresco (< 30 h), a fila da VM-1 cede a vez
     (`sei_integra_fila._delegado_vm2`). Apagar o arquivo — ou a VM-2 parar de bater — traz a fila de volta.

Uso:
    (VM-1) python -m tools.sei_integra_vm2 exportar --max 300 > fila.json
    (VM-1) python -m tools.sei_integra_vm2 aceita 040047_001174_2023 …
    (VM-1) python -m tools.sei_integra_vm2 batida
    (VM-2) python -m tools.sei_integra_vm2 devolver --desde <byte do log antes da rodada>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from tools import sei_integra_fila as F  # noqa: E402

RESERVA = RAIZ / "data" / ".integras_vm2_reserva.json"
BATIDA = RAIZ / "data" / ".integras_na_vm2"
RESUMO = RAIZ / "data" / "vm2_integras_resumo.jsonl"
VM1 = os.environ.get("JFN_VM1_SSH", "vm1-ts")
VM1_JFN = os.environ.get("JFN_VM1_DIR", "/home/ubuntu/JFN")
K_BOMBEIROS = 6          # o caso ativo vem primeiro, como no timer da VM-1 (lá: --max 4)


# ───────────────────────────── lado VM-1 ─────────────────────────────

def _ler_fila(caminho: Path) -> list[dict]:
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in d if isinstance(e, dict)] if isinstance(d, list) else []


def montar_fila(max_n: int, k_bombeiros: int = K_BOMBEIROS) -> list[dict]:
    """Fila na ORDEM do código da VM-1: bombeiros (por score) → dinheiro (por valor pago) → geral."""
    bomb = sorted(_ler_fila(RAIZ / "data" / "bombeiros_sei_fila.json"), key=lambda e: -(e.get("score") or 0))
    dinheiro = _ler_fila(RAIZ / "data" / "sei_fila_dinheiro.json")
    reler = F._fila_reler_por_ob()
    geral = list(dict.fromkeys(F._fila_inscrita() + [c["sei"] for c in F._fila_geral()] + reler))
    fontes = [("bombeiros", [e.get("sei", "") for e in bomb], k_bombeiros),
              ("dinheiro", [e.get("sei", "") for e in dinheiro], max_n),
              ("geral", geral, max_n)]
    vistos: set[str] = set()
    out: list[dict] = []
    for fonte, seis, teto in fontes:
        n_fonte = 0
        for sei in seis:
            if len(out) >= max_n or n_fonte >= teto:
                break
            proc = F._proc_limpo(sei)
            if not proc or proc in vistos:
                continue
            vistos.add(proc)
            pasta = F.ARQUIVO / proc.replace("/", "_")
            if F._arquivado_ok(pasta) and f"SEI-{proc}" not in reler:
                continue
            if F._vazio_recente(pasta):
                continue
            out.append({"sei": f"SEI-{proc}", "fonte": fonte})
            n_fonte += 1
    # `--fila` reordena por score: o score é a POSIÇÃO, para a VM-2 seguir exatamente esta ordem
    for i, e in enumerate(out):
        e["score"] = len(out) - i
    return out


def exportar(max_n: int) -> list[dict]:
    fila = montar_fila(max_n)
    RESERVA.write_text(json.dumps({"ts": time.time(), "host": "vm2",
                                   "procs": [F._proc_limpo(e["sei"]) for e in fila]}), encoding="utf-8")
    return fila


def aceita(tags: list[str]) -> list[str]:
    """Pastas que a VM-1 aceita receber de uma captura VAZIA: só onde ela não tem conteúdo.
    Uma releitura que voltou vazia não pode sobrescrever um arquivo bom (vazio ≠ ausência de documento)."""
    return [t for t in tags if re.fullmatch(r"\d{6}_\d{6}_\d{4}", t) and not F._arquivado_ok(F.ARQUIVO / t)]


def batida() -> None:
    BATIDA.write_text(f"{time.strftime('%F %T')} {socket.gethostname()} — fila de íntegras na VM-2 "
                      "(apagar este arquivo devolve a fila à VM-1)\n", encoding="utf-8")


# ───────────────────────────── lado VM-2 ─────────────────────────────

_RX_STATUS = re.compile(r"^\[[^\]]+\]\s+(\d{6}/\d{6}/\d{4}): (\w+)\s*$")
_ENTREGAR = {"ok", "vazio", "sem_arvore"}


def _ssh(cmd: str, entrada: str | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", VM1, cmd],
                          input=entrada, capture_output=True, text=True, timeout=timeout)


def _md5_local(p: Path) -> str:
    import hashlib
    return hashlib.md5(p.read_bytes()).hexdigest()


def _rsync(origem: Path, destino: str) -> bool:
    r = subprocess.run(["rsync", "-a", "--partial", f"{origem}/", f"{VM1}:{destino}/"],
                       capture_output=True, text=True, timeout=3600)
    return r.returncode == 0


def _entregar(tag: str) -> tuple[bool, str, int]:
    """Copia pasta do arquivo + cache da íntegra para a VM-1 e confere o md5 do manifesto lá."""
    arq = F.ARQUIVO / tag
    man = arq / "manifest.json"
    if not man.exists():
        return False, "sem manifesto local", 0
    try:
        n_docs = len(json.loads(man.read_text(encoding="utf-8")).get("docs") or [])
    except (OSError, ValueError, AttributeError):
        n_docs = 0
    if not _rsync(arq, f"{VM1_JFN}/data/sei_arquivo/{tag}"):
        return False, "rsync do arquivo falhou", n_docs
    cache = F.CACHE / f"integra_{tag}"
    if cache.is_dir() and not _rsync(cache, f"{VM1_JFN}/data/sei_cache/integra_{tag}"):
        return False, "rsync do cache falhou", n_docs
    r = _ssh(f"md5sum {VM1_JFN}/data/sei_arquivo/{tag}/manifest.json")
    if r.returncode != 0 or r.stdout.split()[:1] != [_md5_local(man)]:
        return False, "md5 do manifesto não confere", n_docs
    return True, "", n_docs


def _limpar_local(tag: str) -> None:
    """A VM-1 é a dona do acervo: depois de conferido lá, a cópia daqui sai (disco e `_arquivado_ok` local)."""
    import shutil
    shutil.rmtree(F.ARQUIVO / tag, ignore_errors=True)
    shutil.rmtree(F.CACHE / f"integra_{tag}", ignore_errors=True)
    for p in F.CACHE.glob(f"INTEGRA_{tag}*.pdf"):
        p.unlink(missing_ok=True)


def devolver(desde: int) -> dict:
    try:
        with F.LOG.open("rb") as f:
            f.seek(desde)
            linhas = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        linhas = []
    status: dict[str, str] = {}
    for ln in linhas:
        m = _RX_STATUS.match(ln)
        if m:
            status[m.group(1)] = m.group(2)
    a_entregar = [p for p, s in status.items() if s in _ENTREGAR]
    vazios = [p.replace("/", "_") for p in a_entregar if status[p] != "ok"]
    aceitos = set()
    if vazios:
        r = _ssh(f"cd {VM1_JFN} && PYTHONPATH=. .venv/bin/python -m tools.sei_integra_vm2 aceita {' '.join(vazios)}")
        aceitos = set(r.stdout.split()) if r.returncode == 0 else set()
    entregues: dict[str, int] = {}
    falhas: dict[str, str] = {}
    for proc in a_entregar:
        tag = proc.replace("/", "_")
        if status[proc] != "ok" and tag not in aceitos:
            falhas[proc] = "VM-1 já tem conteúdo — vazio não sobrescreve"
            _limpar_local(tag)
            continue
        ok, motivo, n_docs = _entregar(tag)
        if ok:
            entregues[proc] = n_docs
            _limpar_local(tag)
        else:
            falhas[proc] = motivo
    # log para a VM-1: as linhas da rodada, com "ok" rebaixado onde o arquivo não chegou
    saida = [f"[{time.strftime('%F %T')}] VM-2 ({socket.gethostname()}): rodada remota — "
             f"{len(entregues)} entregue(s) em data/sei_arquivo, {len(falhas)} não entregue(s)"]
    for ln in linhas:
        m = _RX_STATUS.match(ln)
        if m and m.group(1) in falhas:
            ln = ln.rstrip() + f"-vm2-nao-entregue ({falhas[m.group(1)]})"
        saida.append(ln)
    r = _ssh(f"cat >> {VM1_JFN}/data/sei_integra_fila.log", entrada="\n".join(saida) + "\n")
    resumo = {"ts": time.strftime("%F %T"), "status": status, "entregues": entregues,
              "docs_entregues": sum(entregues.values()), "falhas": falhas, "log_vm1": r.returncode == 0}
    with RESUMO.open("a", encoding="utf-8") as f:
        f.write(json.dumps(resumo, ensure_ascii=False) + "\n")
    return resumo


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("exportar"); e.add_argument("--max", type=int, default=300)
    a = sub.add_parser("aceita"); a.add_argument("tags", nargs="*")
    sub.add_parser("batida")
    d = sub.add_parser("devolver"); d.add_argument("--desde", type=int, default=0)
    args = ap.parse_args()
    if args.cmd == "exportar":
        print(json.dumps(exportar(args.max), ensure_ascii=False))
    elif args.cmd == "aceita":
        print(" ".join(aceita(args.tags)))
    elif args.cmd == "batida":
        batida()
    else:
        print(json.dumps(devolver(args.desde), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
