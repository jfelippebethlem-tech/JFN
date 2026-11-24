# -*- coding: utf-8 -*-
"""deploy_worker — E17 `manter:deploy_vm2` (plano mestre v2, O2.4): a árvore do worker anda até o HEAD da VM-1.

Antes (até 24/11/2026) cada script da VM-2 fazia o seu `git pull --ff-only` no início da rodada e seguia com o
código velho se falhasse ("segue com <sha>") — o worker ficava atrás calado (medido: 25 commits atrás na parada).
Agora é um job só, por evento (`codigo_commit`) com a agenda de rede de segurança:

  1. recusa árvore com código local modificado (fora de `data/`): deploy por cima de mudança à mão é deriva;
  2. `git fetch` + `git merge --ff-only @{u}` (= `pull --ff-only`, sem merge nem reset);
  3. confere: HEAD == o sha que o `origin` anuncia AGORA (`ls-remote`) e md5 da árvore de trabalho == md5 do HEAD
     (cada arquivo versionado fora de `data/`, byte a byte) — entrega conferida por md5 dos dois lados;
  4. só se o HEAD MUDOU e conferiu: agenda o `try-restart` do supervisor num timer transitório (60 s), FORA do
     cgroup deste job — o supervisor, ao parar, mata os filhos e devolveria este job à fila (laço).

Idempotente: HEAD igual = "sem novidade", sem recarga. A última linha é o efeito (`fluxo.yaml`, log_contem).

    python -m tools.deploy_worker --unit jfn-fluxo@vm2.service [--sem-recarga]
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FORA = ":(exclude)data"          # dado local da máquina (fila, progresso) não é código


def _git(raiz: Path, *args: str, texto: bool = True):
    p = subprocess.run(["git", "-C", str(raiz), *args], capture_output=True, timeout=300)
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return p.stdout.decode("utf-8", "replace").strip() if texto else p.stdout


def _blobs(raiz: Path) -> list[tuple[str, str]]:
    """(caminho, sha do blob) de cada arquivo versionado no HEAD, fora de `data/`."""
    linhas = _git(raiz, "ls-tree", "-r", "-z", "HEAD", texto=False).decode("utf-8").split("\0")
    itens = ((ln.split("\t", 1)[1], ln.split()[2]) for ln in linhas if ln and " blob " in ln)
    return sorted(i for i in itens if not i[0].startswith("data/"))


def md5_head(raiz: Path) -> str:
    """md5 do conteúdo do HEAD (um `cat-file --batch` só, sem um processo por arquivo)."""
    itens = _blobs(raiz)
    p = subprocess.run(["git", "-C", str(raiz), "cat-file", "--batch"], input="".join(f"{s}\n" for _, s in itens).encode(),
                       capture_output=True, timeout=600, check=True)
    saida, pos, h = p.stdout, 0, hashlib.md5()
    for caminho, _ in itens:
        fim = saida.index(b"\n", pos)
        tam = int(saida[pos:fim].split()[2])
        h.update(caminho.encode() + b"\0" + hashlib.md5(saida[fim + 1:fim + 1 + tam]).digest())
        pos = fim + 1 + tam + 1
    return h.hexdigest()


def md5_trabalho(raiz: Path) -> str:
    """md5 dos mesmos caminhos lidos do disco; ausente entra como ausente (nunca cai no conteúdo do HEAD)."""
    h = hashlib.md5()
    for caminho, _ in _blobs(raiz):
        p = raiz / caminho
        if p.is_symlink():
            conteudo = str(p.readlink()).encode()
        elif p.is_file():
            conteudo = p.read_bytes()
        else:
            conteudo = b"\0ausente\0"
        h.update(caminho.encode() + b"\0" + hashlib.md5(conteudo).digest())
    return h.hexdigest()


def agendar_recarga(unit: str, sha: str) -> None:
    subprocess.run(["systemd-run", "--user", "--collect", f"--unit=jfn-deploy-recarga-{sha[:8]}", "--on-active=60",
                    "systemctl", "--user", "try-restart", unit], check=True, capture_output=True, timeout=60)


def deploy(raiz: Path, unit: str | None, recarregar=agendar_recarga) -> dict:
    sujos = _git(raiz, "status", "--porcelain", "--untracked-files=no", "--", ".", FORA)
    if sujos:
        raise RuntimeError(f"código local modificado (deploy recusado): {sujos.splitlines()[:5]}")
    antes = _git(raiz, "rev-parse", "HEAD")
    _git(raiz, "fetch", "-q", "origin")
    _git(raiz, "merge", "--ff-only", "-q", "@{u}")
    head = _git(raiz, "rev-parse", "HEAD")
    ramo = _git(raiz, "rev-parse", "--abbrev-ref", "@{u}").split("/", 1)[1]
    anunciado = _git(raiz, "ls-remote", "origin", f"refs/heads/{ramo}").split()[0]
    if head != anunciado:
        raise RuntimeError(f"HEAD {head[:10]} ≠ origin/{ramo} {anunciado[:10]} (commit novo durante o deploy? repete)")
    m_head, m_trab = md5_head(raiz), md5_trabalho(raiz)
    if m_head != m_trab:
        raise RuntimeError(f"md5 da árvore {m_trab} ≠ md5 do HEAD {m_head}: entrega NÃO confere")
    mudou = head != antes
    if mudou and unit:
        recarregar(unit, head)
    return {"antes": antes, "head": head, "md5": m_head, "mudou": mudou, "recarga": bool(mudou and unit)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.deploy_worker")
    ap.add_argument("--unit", help="supervisor a recarregar quando o HEAD muda (ex.: jfn-fluxo@vm2.service)")
    ap.add_argument("--sem-recarga", action="store_true")
    a = ap.parse_args(argv)
    try:
        r = deploy(RAIZ, None if a.sem_recarga else a.unit)
    except (RuntimeError, subprocess.SubprocessError, OSError) as e:
        print(f"deploy_worker: FALHOU — {e}")
        return 1
    estado = ("recarga agendada" if r["recarga"] else "sem recarga") if r["mudou"] else "sem novidade"
    print(f"deploy_worker: HEAD {r['head']} confere (md5 {r['md5']}; antes {r['antes'][:10]}; {estado})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
