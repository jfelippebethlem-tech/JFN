# -*- coding: utf-8 -*-
"""integracao_conferir — o que a integração por patch de um agente DEIXA PARA TRÁS, conferido por código.

POR QUE EXISTE (20/11/2026, duas falhas do mesmo dia, as duas da integração do trabalho de agentes em worktree):
  1. REMOÇÃO PERDIDA. O commit de integração filtrava os caminhos por "existe no disco"; arquivo apagado não existe,
     saiu da lista, e 14 arquivos "apagados" pelos agentes seguiram no repositório — um deles mandava Telegram ao ser
     IMPORTADO. Só apareceu na passada final, por uma catraca vermelha.
  2. WORKTREE ESQUECIDO. 45 worktrees de agentes (14 GB) encheram o disco a 100%; a auto-atualização do Claude Code
     rodou sem espaço, o binário sumiu e todo `claude -p` (juiz, conferência do Opus, /cc) caiu.

    python -m tools.integracao_conferir remocoes <branch-do-agente> [--em HEAD]   # exit 1 se alguma remoção não chegou
    python -m tools.integracao_conferir stage                                    # remoção parada no índice
    python -m tools.integracao_conferir worktrees [--aplicar] [--horas 6]        # lista / remove os que já podem sair

`worktrees --aplicar` só remove worktree LIMPO (nada fora de commit), PARADO há `--horas`, SEM processo vivo dentro e
INTEGRADO (decisão 6 do dono, 20/11/2026): a ponta já está no HEAD (ancestral) ou o conteúdo do que o agente mudou já
está aplicado no HEAD (diff vazio, nos caminhos que a branch tocou, contra o HEAD — é a integração por patch). A branch
fica: os commits do agente continuam no repositório. Sujo, recente, em uso ou não integrado nunca é tocado — vai listado.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
PREFIXO = ".claude/worktrees/"
HORAS_PARADO = 6


def _git(*args: str, cwd: Path | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=cwd or _REPO, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}: {r.stderr.strip()[:200]}")
    return r.stdout


def remocoes_pendentes(ref: str, em: str = "HEAD", repo: Path | None = None) -> list[str]:
    """Caminhos que `ref` APAGOU ou RENOMEOU (origem) desde a base comum com `em` e que ainda existem em `em`."""
    base = _git("merge-base", em, ref, cwd=repo).strip()
    saida = _git("diff", "--name-status", "--find-renames", "--diff-filter=DR", base, ref, cwd=repo)
    apagados = [ln.split("\t")[1] for ln in saida.splitlines() if ln.strip()]
    if not apagados:
        return []
    existem = set(_git("ls-tree", "-r", "--name-only", em, "--", *apagados, cwd=repo).splitlines())
    return sorted(p for p in apagados if p in existem)


def remocoes_em_stage(repo: Path | None = None) -> list[str]:
    """Remoções paradas no índice (a marca que a integração de 20/11 deixou)."""
    return sorted(_git("diff", "--cached", "--name-only", "--diff-filter=D", cwd=repo).splitlines())


def _processos_dentro(caminho: Path) -> int:
    n = 0
    alvo = str(caminho)
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            cwd = os.readlink(p / "cwd")
        except OSError:
            continue
        n += cwd == alvo or cwd.startswith(alvo + "/")
    return n


def integrado(ponta: str, head: str, repo: Path | None = None, com_branch: bool = True) -> str | None:
    """'ancestral' (a ponta já está no HEAD), 'aplicado' (os caminhos que a branch mudou estão iguais no HEAD) ou
    None (há trabalho do agente que o HEAD não tem). Sem branch (HEAD destacado) só vale 'ancestral': removido o
    worktree, nada mais segura os commits."""
    r = subprocess.run(["git", "merge-base", "--is-ancestor", ponta, head], cwd=repo or _REPO, capture_output=True,
                       timeout=120)
    if r.returncode == 0:
        return "ancestral"
    if r.returncode != 1 or not com_branch:
        return None
    base = _git("merge-base", head, ponta, cwd=repo).strip()
    mudou = _git("diff", "--name-only", "--no-renames", base, ponta, cwd=repo).splitlines()
    if not mudou:
        return "aplicado"
    falta = _git("diff", "--name-only", "--no-renames", head, ponta, "--", *mudou, cwd=repo).strip()
    return None if falta else "aplicado"


def worktrees(repo: Path | None = None, agora: float | None = None, horas: float = HORAS_PARADO) -> list[dict]:
    """Os worktrees de agente, cada um com o que decide se pode sair: sujo, idade da última atividade, processos e
    se o trabalho já está integrado no HEAD do repositório principal."""
    repo = repo or _REPO
    agora = agora or time.time()
    head = _git("rev-parse", "HEAD", cwd=repo).strip()
    out, atual = [], {}
    for ln in _git("worktree", "list", "--porcelain", cwd=repo).splitlines() + [""]:
        if ln.startswith("worktree "):
            atual = {"caminho": ln[9:]}
        elif ln.startswith("HEAD "):
            atual["ponta"] = ln[5:]
        elif ln.startswith("branch "):
            atual["branch"] = ln[7:].removeprefix("refs/heads/")
        elif not ln and atual:
            c = Path(atual["caminho"])
            if PREFIXO in atual["caminho"] and c.is_dir():
                adm = Path(_git("rev-parse", "--absolute-git-dir", cwd=c).strip())
                marcas = [f.stat().st_mtime for f in (adm / "HEAD", adm / "index", adm / "logs" / "HEAD") if f.exists()]
                sujo = len(_git("status", "--porcelain", cwd=c).splitlines())
                parado_h = (agora - max(marcas)) / 3600 if marcas else 0.0
                vivos = _processos_dentro(c)
                integ = integrado(atual["ponta"], head, repo, com_branch=bool(atual.get("branch")))
                atual.update(sujo=sujo, parado_h=round(parado_h, 1), processos=vivos, integrado=integ,
                             pode_sair=sujo == 0 and vivos == 0 and parado_h >= horas and integ is not None)
                out.append(atual)
            atual = {}
    return out


def remover(lista: list[dict], repo: Path | None = None) -> list[str]:
    feitos = []
    for w in lista:
        if w["pode_sair"]:
            _git("worktree", "remove", w["caminho"], cwd=repo)     # sem --force: se sujou no meio, o git recusa
            feitos.append(w["caminho"])
    if feitos:
        _git("worktree", "prune", cwd=repo)
    return feitos


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("remocoes")
    r.add_argument("ref")
    r.add_argument("--em", default="HEAD")
    sub.add_parser("stage")
    w = sub.add_parser("worktrees")
    w.add_argument("--aplicar", action="store_true")
    w.add_argument("--horas", type=float, default=HORAS_PARADO)
    a = ap.parse_args()
    if a.cmd == "remocoes":
        falta = remocoes_pendentes(a.ref, a.em)
        print(json.dumps({"ref": a.ref, "em": a.em, "remocoes_que_nao_chegaram": falta}, ensure_ascii=False, indent=1))
        return 1 if falta else 0
    if a.cmd == "stage":
        falta = remocoes_em_stage()
        print(json.dumps({"remocoes_paradas_no_indice": falta}, ensure_ascii=False, indent=1))
        return 1 if falta else 0
    lista = worktrees(horas=a.horas)
    feitos = remover(lista) if a.aplicar else []
    print(json.dumps({"worktrees": len(lista), "podem_sair": sum(x["pode_sair"] for x in lista), "removidos": feitos,
                      "ficam": [{k: x[k] for k in ("caminho", "sujo", "parado_h", "processos", "integrado")}
                                for x in lista if not x["pode_sair"]]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
