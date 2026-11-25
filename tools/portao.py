# -*- coding: utf-8 -*-
"""Portão de pre-push v2 (O2.5 da Esteira Única): testes pelo grafo de import, rodados FORA da VM-1.

POR QUE EXISTE. O portão v1 (tools/pre_push_gate.sh) tinha três buracos medidos em 24/11:
  1. escolhia testes por NOME e deixou passar falhas que só a suíte completa pegou — a seleção agora é a de
     tools/portao_grafo.py (import transitivo + catracas + transversais);
  2. empacotava a ÁRVORE DE TRABALHO (com o WIP das outras frentes) e não o commit que sobe — agora o nó busca o
     próprio commit num espelho git (tools/portao_no.sh), então as catracas de `git ls-files` também rodam lá;
  3. com a VM-2 fora ele dizia "dívida, não aprovação" e DEIXAVA PASSAR (exit 0). Agora: nenhum nó respondeu → o push
     NÃO passa, e fica registrado em data/push_divida.json; `python -m tools.push_divida drenar` testa e empurra
     quando um nó voltar. Nunca há --no-verify implícito.

NÓS. VM-2 primeiro (2 vCPU, 1 lote); it-campo (WSL, 24 fios) é o segundo e, com seleção grande, divide o lote com a
VM-2 em paralelo (6 pytest no it-campo, cada um no seu worktree). Nó que cai no meio → a parte dele vai para o outro.

COMO LIGAR (desligado por padrão; o v1 segue para quem não ligar):
    git config jfn.portaov2 1        # repo inteiro: todo push/commit de toda sessão passa pelo v2
    export JFN_PORTAO_V2=1           # só a sessão/shell atual
    git config --unset jfn.portaov2  # desligar (a variável, se exportada, vence o git config)
  Liga junto: .git/hooks/pre-commit → tools/pre_commit_v2.sh (só checagens) e .git/hooks/post-commit →
  tools/grafo_pos_commit.sh (graphify/codegraph/compressão em 2º plano, no it-campo quando ele responde).

    python -m tools.portao pre-push <remoto> <url>   < linhas do git    # o hook (via tools/pre_push_gate.sh)
    python -m tools.portao testar <base> <sha>                          # mede um intervalo sem empurrar
    python -m tools.portao nos                                          # quem está respondendo
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from tools import portao_grafo

RAIZ = Path(__file__).resolve().parent.parent
CORPO_NO = RAIZ / "tools" / "portao_no.sh"
ORIGEM = os.environ.get("JFN_PORTAO_ORIGEM", "ssh://vm1-ts/home/ubuntu/JFN")
ZERO = "0" * 40
LIMIAR_PARALELO = int(os.environ.get("JFN_PORTAO_LIMIAR_PARALELO", "40"))   # arquivos; abaixo disso, um nó só
TETO_NO = int(os.environ.get("JFN_PORTAO_TETO", "2400"))                    # s por nó (o nó desiste sozinho antes)
LOG = Path(os.environ.get("JFN_PORTAO_LOG", "/tmp/pre_push_v2.log"))

_SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=4"]


@dataclass(frozen=True)
class No:
    nome: str
    argv: tuple[str, ...]      # comando que recebe o script pelo stdin
    paralelo: int              # pytest simultâneos no nó
    peso: float                # fatia relativa quando a seleção é dividida
    referencia: bool = False   # ambiente de referência (o do CI): confirma falha vista em nó acelerador


NOS: tuple[No, ...] = (
    # pesos medidos em 24/11 (9d40ae78, 293 arquivos): VM-2 60 arquivos em 233 s (1 pytest, load 8 dos outros
    # trabalhos dela); it-campo 233 arquivos em 46 s (6 pytest) — ~18× a vazão. Peso 1 × 15.
    No("vm2", (*_SSH, "vm2-ts", "bash -s"), paralelo=1, peso=1.0, referencia=True),
    No("itcampo", (*_SSH, "it-campo", "wsl -d Ubuntu bash -s"), paralelo=6, peso=15.0),
)


def _rodar(argv: tuple[str, ...], script: str, timeout: int) -> tuple[int, str]:
    """ÚNICA porta para o ssh (os testes trocam esta função por um fake)."""
    try:
        r = subprocess.run(list(argv), input=script, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        saida = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return 124, saida + f"\nPORTAO_INFRA ssh sem resposta em {timeout} s"
    except OSError as e:
        return 127, f"PORTAO_INFRA ssh não executou: {e}"
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def sondar(no: No, timeout: int = 40) -> bool:
    rc, out = _rodar(no.argv, "echo PORTAO_VIVO $(nproc)\n", timeout)
    return "PORTAO_VIVO" in out


def nos_vivos(nos: tuple[No, ...] | None = None) -> list[No]:
    nos = nos or NOS
    with ThreadPoolExecutor(len(nos)) as ex:
        vivos = list(ex.map(sondar, nos))
    return [n for n, v in zip(nos, vivos) if v]


@dataclass
class Resultado:
    estado: str                       # "ok" | "falhou" | "infra"
    no: str
    testes: list[str]
    falhas: list[str] = field(default_factory=list)
    resumo: list[str] = field(default_factory=list)
    motivo: str = ""
    saida: str = ""
    segundos: float = 0.0


def interpretar(no: str, testes: list[str], rc: int, saida: str) -> Resultado:
    """Só o contrato de linhas de tools/portao_no.sh conta. Sem PORTAO_FIM a rodada não aconteceu (infra) — nunca
    "passou"."""
    linhas = saida.splitlines()
    infra = [ln[len("PORTAO_INFRA "):] for ln in linhas if ln.startswith("PORTAO_INFRA ")]
    fim = [ln for ln in linhas if ln.startswith("PORTAO_FIM rc=")]
    falhas = [ln[len("PORTAO_FALHA "):] for ln in linhas if ln.startswith("PORTAO_FALHA ")]
    resumo = [ln[len("PORTAO_LOTE "):] for ln in linhas if ln.startswith("PORTAO_LOTE ")]
    if infra or not fim:
        motivo = infra[-1] if infra else f"saída sem PORTAO_FIM (rc do ssh {rc})"
        return Resultado("infra", no, testes, falhas, resumo, motivo, saida)
    estado = "ok" if fim[-1].strip() == "PORTAO_FIM rc=0" else "falhou"
    if estado == "falhou" and not falhas:
        falhas = ["(lote falhou sem linha FAILED — ver o log)"]
    return Resultado(estado, no, testes, falhas, resumo, "", saida)


def montar_script(sha: str, testes: list[str], paralelo: int, run: str, teto: int, ref: str) -> str:
    cab = {"SHA": sha, "REF": ref, "ORIGEM": ORIGEM, "RUN": run, "PAR": str(max(1, min(paralelo, len(testes)))),
           "TESTES": " ".join(testes), "TETO": str(teto)}
    return "".join(f"{k}={shlex.quote(v)}\n" for k, v in cab.items()) + CORPO_NO.read_text(encoding="utf-8")


def rodar_no(no: No, sha: str, testes: list[str], run: str, ref: str) -> Resultado:
    script = montar_script(sha, testes, no.paralelo, f"{run}-{no.nome}", TETO_NO - 60, ref)
    t0 = time.time()
    rc, out = _rodar(no.argv, script, TETO_NO)
    r = interpretar(no.nome, testes, rc, out)
    r.segundos = time.time() - t0
    return r


def dividir(testes: list[str], nos: list[No], custo: dict[str, int]) -> dict[str, list[str]]:
    """Guloso por custo (tamanho do arquivo): o mais caro vai para o nó com menos carga relativa ao peso."""
    carga = {n.nome: 0.0 for n in nos}
    partes: dict[str, list[str]] = {n.nome: [] for n in nos}
    peso = {n.nome: n.peso for n in nos}
    for t in sorted(testes, key=lambda x: (-custo.get(x, 1), x)):
        alvo = min(carga, key=lambda k: ((carga[k] + custo.get(t, 1)) / peso[k], k))
        partes[alvo].append(t)
        carga[alvo] += custo.get(t, 1)
    return {k: sorted(v) for k, v in partes.items() if v}


@dataclass
class Veredito:
    estado: str                       # "aprovado" | "reprovado" | "nao_medido"
    resultados: list[Resultado]
    motivo: str = ""


def executar(sha: str, testes: list[str], custo: dict[str, int] | None = None,
             nos: tuple[No, ...] | None = None, ref: str = "") -> Veredito:
    run = f"{time.strftime('%Y%m%d%H%M%S')}-{os.getpid()}"
    ref = ref or sha
    nos = nos or NOS
    vivos = nos_vivos(nos)
    if not vivos:
        return Veredito("nao_medido", [], "nenhum nó de teste respondeu (" + ", ".join(n.nome for n in nos) + ")")
    if len(testes) >= LIMIAR_PARALELO and len(vivos) > 1:
        partes = dividir(testes, vivos, custo or {})
    else:
        partes = {vivos[0].nome: list(testes)}     # VM-2 primeiro (ordem de NOS); fora, o it-campo
    por_nome = {n.nome: n for n in vivos}
    with ThreadPoolExecutor(len(partes)) as ex:
        res = list(ex.map(lambda kv: rodar_no(por_nome[kv[0]], sha, kv[1], run, ref), partes.items()))
    finais: list[Resultado] = []
    caidos = {r.no for r in res if r.estado == "infra"}
    for r in res:
        if r.estado != "infra":
            finais.append(r)
            continue
        outro = next((n for n in vivos if n.nome not in caidos), None)
        if outro is None:
            return Veredito("nao_medido", [*finais, r], f"{r.no}: {r.motivo}; nenhum outro nó para refazer a parte dele")
        print(f"[portão] {r.no} não mediu ({r.motivo}) — refazendo os {len(r.testes)} arquivos no {outro.nome}",
              file=sys.stderr)
        r2 = rodar_no(outro, sha, r.testes, run + "-refeito", ref)
        if r2.estado == "infra":
            return Veredito("nao_medido", [*finais, r, r2], f"{r.no}: {r.motivo}; {outro.nome}: {r2.motivo}")
        finais.append(r2)
    finais = _confirmar_na_referencia(finais, vivos, sha, run, ref)
    estado = "aprovado" if all(r.estado == "ok" for r in finais) else "reprovado"
    return Veredito(estado, finais)


_NODEID = re.compile(r"^(?:FAILED|ERROR) (\S+?\.py)\b")


def _confirmar_na_referencia(finais: list[Resultado], vivos: list[No], sha: str, run: str, ref: str) -> list[Resultado]:
    """Falha vista num nó ACELERADOR (it-campo) é refeita no nó de REFERÊNCIA (VM-2, o ambiente do CI) antes de
    reprovar. Medido em 24/11: o WSL do it-campo não tem `unzip` (nem zstd, node, ffmpeg, xvfb-run; sem sudo), e
    tests/test_socio_pj_raiz.py falhava lá com FileNotFoundError e passava na VM-2. Vale o veredito da referência —
    se ela também falha, reprova; se ela está fora, a falha fica (bloquear é o lado seguro) e o motivo é dito."""
    ref_no = next((n for n in vivos if n.referencia), None)
    saida: list[Resultado] = []
    for r in finais:
        no = next((n for n in vivos if n.nome == r.no), None)
        if r.estado != "falhou" or no is None or no.referencia:
            saida.append(r)
            continue
        arquivos = sorted({m.group(1) for f in r.falhas if (m := _NODEID.match(f))})
        if ref_no is None or not arquivos:
            r.motivo = (r.motivo + " · " if r.motivo else "") + (
                "sem nó de referência vivo para confirmar" if ref_no is None else "falha sem nodeid para refazer")
            saida.append(r)
            continue
        print(f"[portão] {r.no} acusou {len(arquivos)} arquivo(s) — confirmando na {ref_no.nome} (referência)",
              file=sys.stderr)
        conf = rodar_no(ref_no, sha, arquivos, run + "-confirma", ref)
        if conf.estado == "infra":
            r.motivo = f"confirmação na {ref_no.nome} não mediu ({conf.motivo})"
            saida.append(r)
            continue
        if conf.estado == "ok":
            print(f"[portão]   {', '.join(arquivos)}: falha só no {r.no} (ambiente) — a {ref_no.nome} passa",
                  file=sys.stderr)
        r.estado = "ok" if conf.estado == "ok" else "falhou"
        r.motivo = f"falha do {r.no} refeita na {ref_no.nome}: {conf.estado}"
        r.falhas = conf.falhas
        r.resumo = [*r.resumo, *(f"{ref_no.nome}: {x}" for x in conf.resumo)]
        saida.append(r)
    return saida


def _git(*args: str, repo: Path | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def base_do_push(sha_local: str, sha_remoto: str, repo: Path) -> str:
    """Contra o que o remoto já tem; ref nova → merge-base com o upstream/origin/HEAD; sem nada → o pai."""
    if sha_remoto != ZERO:
        try:
            _git("cat-file", "-e", f"{sha_remoto}^{{commit}}", repo=repo)
            return sha_remoto
        except RuntimeError:
            print(f"[portão] o remoto está em {sha_remoto[:10]}, que não existe aqui — medindo contra o pai",
                  file=sys.stderr)
    for ref in ("@{u}", "origin/HEAD", "origin/main"):
        try:
            return _git("merge-base", sha_local, ref, repo=repo)
        except RuntimeError:
            continue
    return f"{sha_local}~1"


def _custo(repo: Path, sha: str, testes: list[str]) -> dict[str, int]:
    arv = portao_grafo.arvore(repo, sha)
    return {t: arv[t][1] for t in testes if t in arv}


def _imprimir(v: Veredito) -> None:
    for r in v.resultados:
        print(f"[portão]   {r.no}: {r.estado} · {len(r.testes)} arquivo(s) em {r.segundos:.0f} s · "
              + " | ".join(r.resumo or [r.motivo]))
        for f in r.falhas[:15]:
            print(f"[portão]     {f}")


def medir(repo: Path, base: str, sha: str) -> Veredito:
    sel = portao_grafo.selecionar(repo, base, sha)
    print(f"[portão] {sha[:10]} contra {base[:10]}: {len(sel.mudados)} arquivo(s) mudados → {len(sel.testes)} arquivo(s)"
          f" de teste {json.dumps(sel.motivos, ensure_ascii=False)}")
    t0 = time.time()
    # ref temporária: o nó busca por ela (o upload-pack não serve commit que não seja ponta de ref anunciada)
    ref = f"refs/portao/{time.strftime('%Y%m%d%H%M%S')}-{os.getpid()}"
    _git("update-ref", ref, sha, repo=repo)
    try:
        v = executar(sha, sel.testes, _custo(repo, sha, sel.testes), ref=ref)
    finally:
        _git("update-ref", "-d", ref, repo=repo)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"\n=== {time.strftime('%F %T')} {sha} base {base} → {v.estado} em {time.time() - t0:.0f} s\n")
        for r in v.resultados:
            fh.write(f"--- {r.no} ({r.estado}, {r.segundos:.0f} s) {r.motivo}\n{r.saida}\n")
    _imprimir(v)
    print(f"[portão] {v.estado} em {time.time() - t0:.0f} s (log: {LOG})")
    return v


def _scan_pii(repo: Path, base: str, sha: str) -> bool:
    """O0.5: o repo é público — CPF com DV válido no diff do push bloqueia. Barato e local (só o diff)."""
    py = Path(_git("rev-parse", "--git-common-dir", repo=repo)).resolve()
    py = (py if py.name != ".git" else py.parent) / ".venv" / "bin" / "python"
    r = subprocess.run([str(py if py.exists() else sys.executable), "-m", "tools.scan_pii", "--faixa", f"{base}..{sha}"],
                       cwd=repo, timeout=300)
    return r.returncode == 0


def pre_push(remoto: str, url: str, linhas: list[str], repo: Path) -> int:
    from tools import push_divida

    pedidos = []
    for ln in linhas:
        partes = ln.split()
        if len(partes) != 4:
            continue
        ref_local, sha_local, ref_remota, sha_remoto = partes
        if sha_local == ZERO:          # apagar ref remota: não há código a testar
            continue
        pedidos.append((ref_local, sha_local, ref_remota, base_do_push(sha_local, sha_remoto, repo)))
    if not pedidos:
        print("[portão] nada a testar neste push (só remoção de ref)")
        return 0
    for ref_local, sha, ref_remota, base in pedidos:
        if not _scan_pii(repo, base, sha):
            print(f"[portão] ⛔ CPF com DV válido no que este push leva ({base[:10]}..{sha[:10]}) — mascare antes de subir")
            return 1
        v = medir(repo, base, sha)
        if v.estado == "reprovado":
            print(f"[portão] ❌ BLOQUEADO — teste falhando em {sha[:10]} (o CI mandaria e-mail de falha)")
            return 1
        if v.estado == "nao_medido":
            push_divida.registrar(sha=sha, ref_local=ref_local, ref_remota=ref_remota, remoto=remoto, url=url,
                                  repo=str(repo), motivo=v.motivo)
            print(f"[portão] ❌ BLOQUEADO — NÃO MEDIDO: {v.motivo}.\n"
                  f"[portão]    Registrado em data/push_divida.json. Quando um nó voltar:"
                  f" .venv/bin/python -m tools.push_divida drenar")
            return 1
        push_divida.quitar(sha, ref_remota, "aprovado no portão")
    print("[portão] ✅ aprovado")
    return 0


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(line_buffering=True)      # o hook mistura stdout e stderr: na ordem em que acontecem
    repo = Path(_git("rev-parse", "--show-toplevel"))
    if argv[:1] == ["pre-push"] and len(argv) >= 2:
        return pre_push(argv[1], argv[2] if len(argv) > 2 else "", sys.stdin.read().splitlines(), repo)
    if argv[:1] == ["testar"] and len(argv) == 3:
        v = medir(repo, _git("rev-parse", argv[1], repo=repo), _git("rev-parse", argv[2], repo=repo))
        return {"aprovado": 0, "reprovado": 1}.get(v.estado, 3)
    if argv[:1] == ["nos"]:
        vivos = {n.nome for n in nos_vivos()}
        for n in NOS:
            print(f"{n.nome}: {'responde' if n.nome in vivos else 'NÃO responde'}")
        return 0 if vivos else 3
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
