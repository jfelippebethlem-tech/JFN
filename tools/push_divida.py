# -*- coding: utf-8 -*-
"""push_divida — o push que o portão NÃO pôde medir fica aqui, bloqueado, até um nó de teste voltar (O2.5).

POR QUE EXISTE. O portão v1, com a VM-2 fora, dizia "testes NÃO rodados. Isto é dívida, não aprovação" e saía com
0 — o push passava calado e a dívida não ficava escrita em lugar nenhum. Agora o portão v2 BLOQUEIA e registra aqui
(commit, ref, quando, motivo); `drenar` refaz o push quando um nó responde — pelo `git push` normal, com o hook
ligado: quem testa é o mesmo portão, nunca um `--no-verify`.

Estado: data/push_divida.json (lista; uma entrada por commit×ref remota). Leitura-modificação-escrita sob flock.

    .venv/bin/python -m tools.push_divida listar
    .venv/bin/python -m tools.push_divida drenar
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQ = Path(os.environ.get("JFN_PUSH_DIVIDA", RAIZ / "data" / "push_divida.json"))


@contextmanager
def _travado():
    ARQ.parent.mkdir(parents=True, exist_ok=True)
    with open(ARQ.with_suffix(".lock"), "w") as trava:
        fcntl.flock(trava, fcntl.LOCK_EX)
        try:
            dados = json.loads(ARQ.read_text(encoding="utf-8")) if ARQ.exists() else []
        except json.JSONDecodeError as e:
            raise SystemExit(f"[push_divida] {ARQ} ilegível ({e}) — corrija à mão; nada foi sobrescrito") from e
        caixa = {"itens": dados}
        yield caixa
        tmp = ARQ.with_suffix(f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(caixa["itens"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(ARQ)


def registrar(*, sha: str, ref_local: str, ref_remota: str, remoto: str, url: str, repo: str, motivo: str) -> dict:
    agora = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with _travado() as c:
        for it in c["itens"]:
            if it["commit"] == sha and it["ref_remota"] == ref_remota:
                it.update(tentativas=it.get("tentativas", 1) + 1, ultima=agora, motivo=motivo)
                return it
        it = {"commit": sha, "ref_local": ref_local, "ref_remota": ref_remota, "remoto": remoto, "url": url,
              "repo": repo, "quando": agora, "ultima": agora, "motivo": motivo, "tentativas": 1}
        c["itens"].append(it)
        return it


def quitar(sha: str, ref_remota: str, como: str) -> bool:
    if not ARQ.exists():
        return False
    with _travado() as c:
        antes = len(c["itens"])
        c["itens"] = [it for it in c["itens"] if not (it["commit"] == sha and it["ref_remota"] == ref_remota)]
        saiu = len(c["itens"]) < antes
    if saiu:
        print(f"[push_divida] quitado {sha[:10]} → {ref_remota} ({como})")
    return saiu


def listar() -> list[dict]:
    if not ARQ.exists():
        return []
    return json.loads(ARQ.read_text(encoding="utf-8"))


def _git(repo: str, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout)


def ja_subiu(it: dict) -> bool:
    """O remoto já tem o commit (alguém empurrou depois, com o portão)?"""
    r = _git(it["repo"], "ls-remote", it["remoto"], it["ref_remota"])
    if r.returncode != 0 or not r.stdout.strip():
        return False
    ponta = r.stdout.split()[0]
    if ponta == it["commit"]:
        return True
    return _git(it["repo"], "merge-base", "--is-ancestor", it["commit"], ponta).returncode == 0


def _empurrar(it: dict) -> int:
    """`git push` NORMAL: o hook pre-push roda e o portão v2 mede. Sem --no-verify."""
    env = {**os.environ, "JFN_PORTAO_V2": "1"}
    return subprocess.run(["git", "-C", it["repo"], "push", it["remoto"], f"{it['commit']}:{it['ref_remota']}"],
                          env=env, timeout=3600).returncode


def drenar() -> int:
    from tools import portao

    itens = listar()
    if not itens:
        print("[push_divida] nada pendente")
        return 0
    vivos = portao.nos_vivos()
    if not vivos:
        print(f"[push_divida] {len(itens)} push(es) pendente(s) e nenhum nó de teste responde — continua devendo")
        return 3
    print(f"[push_divida] nós: {', '.join(n.nome for n in vivos)} · {len(itens)} pendente(s)")
    falhou = 0
    for it in itens:
        if not Path(it["repo"]).is_dir():
            it = {**it, "repo": str(RAIZ)}       # worktree de agente já removido: o objeto está no repo comum
        if ja_subiu(it):
            quitar(it["commit"], it["ref_remota"], "o remoto já tem")
            continue
        print(f"[push_divida] {it['commit'][:10]} → {it['remoto']} {it['ref_remota']} (devido desde {it['quando']})")
        if _empurrar(it) == 0:
            quitar(it["commit"], it["ref_remota"], "testado e empurrado")
        else:
            falhou += 1
            print(f"[push_divida] {it['commit'][:10]} segue pendente (o portão recusou ou não mediu — ver acima)")
    return 1 if falhou else 0


def main(argv: list[str]) -> int:
    if argv == ["listar"]:
        itens = listar()
        for it in itens:
            print(f"{it['commit'][:10]} → {it['remoto']} {it['ref_remota']} · desde {it['quando']} · "
                  f"{it.get('tentativas', 1)} tentativa(s) · {it['motivo']}")
        print(f"{len(itens)} pendente(s)")
        return 0
    if argv == ["drenar"]:
        return drenar()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
