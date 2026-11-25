# -*- coding: utf-8 -*-
"""retomada_gerar — regenera as seções de ESTADO do ~/vault/RETOMADA.md a partir das fontes, sem tocar no que é
escrito à mão (plano mestre v2 §9 O8.4 "RETOMADA gerada").

POR QUE EXISTE. O RETOMADA é o documento único de passagem (regra do dono, 23/11/2026), mas o estado nele era copiado
à mão: "Em andamento" envelhecia em horas e dizia o que já tinha terminado. O estado tem fonte — o backlog
(docs/refatoracao/backlog.yaml), o quadro de sessões (~/sessoes/abertas) e o git — e passa a sair delas.

O QUE É GERADO. Só o que está entre marcadores:
    <!-- gerado:backlog -->   …   <!-- /gerado:backlog -->     contagem por estado, em curso, do dono, prontos
    <!-- gerado:quadro -->    …   <!-- /gerado:quadro -->      frentes abertas + última nota de cada
    <!-- gerado:git -->       …   <!-- /gerado:git -->         branch, commits sem push, últimos commits
Fora dos marcadores, nenhum byte muda (frontmatter, decisões do dono, "Feito", pendências). Arquivo sem os marcadores
ganha UMA seção "## 7. Estado gerado" no fim com os três blocos. Escrita atômica (temporário + rename) e só quando
o conteúdo muda. Sem rede: o quadro é lido do clone local (`quadro ver` puxa do GitHub; rode-o antes, se quiser).

    python tools/retomada_gerar.py              # regenera no lugar
    python tools/retomada_gerar.py --stdout     # imprime o resultado, não grava
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
RETOMADA = Path.home() / "vault" / "RETOMADA.md"
BACKLOG = RAIZ / "docs" / "refatoracao" / "backlog.yaml"
QUADRO = Path.home() / "sessoes" / "abertas"
BLOCOS = ("backlog", "quadro", "git")
ESTADOS = ("pendente", "em_curso", "sombra", "bloqueado_dono", "feito")


def _abre(nome: str) -> str:
    return f"<!-- gerado:{nome} -->"


def _fecha(nome: str) -> str:
    return f"<!-- /gerado:{nome} -->"


# ── renderização (pura) ───────────────────────────────────────────────────────────────────────────────────────────
def render_backlog(itens: list[dict], max_linhas: int = 12) -> str:
    por = {e: [i for i in itens if i.get("estado") == e] for e in ESTADOS}
    outros = [i for i in itens if i.get("estado") not in ESTADOS]
    feitos = {i["id"] for i in por["feito"]}
    prontos = [i for i in por["pendente"] if all(d in feitos for d in i.get("dep") or [])]
    L = ["**Backlog** (`docs/refatoracao/backlog.yaml`): " + " · ".join(f"{e} {len(v)}" for e, v in por.items())
         + (f" · estado desconhecido {len(outros)}" if outros else "") + f" · total {len(itens)}"]

    def lista(titulo: str, its: list[dict]) -> None:
        if not its:
            return
        L.append(f"\n{titulo} ({len(its)}):")
        for i in its[:max_linhas]:
            nota = f" — {str(i['nota'])[:110]}" if i.get("nota") else ""
            L.append(f"- `{i['id']}` [{i.get('maq', '?')}] {i.get('titulo', '')}{nota}")
        if len(its) > max_linhas:
            L.append(f"- … e mais {len(its) - max_linhas}")

    lista("Em curso", por["em_curso"])
    lista("Bloqueado pelo dono", por["bloqueado_dono"])
    lista("Prontos para começar (dependências feitas)", prontos)
    lista("Estado desconhecido no backlog", outros)
    return "\n".join(L)


def ler_frente(texto: str, ident: str) -> dict:
    campo = lambda k: (re.search(rf"^{k}: (.*)$", texto, re.M) or [None, ""])[1].strip()  # noqa: E731
    notas = [ln[2:].strip() for ln in texto.splitlines() if ln.startswith("> ")]
    return {"id": ident, "projeto": campo("projeto"), "oque": campo("oque"), "maquina": campo("maquina"),
            "desde": campo("desde"), "ultima": notas[-1] if notas else ""}


def render_quadro(frentes: list[dict]) -> str:
    if not frentes:
        return "**Quadro de sessões:** nenhuma frente aberta."
    L = [f"**Quadro de sessões** (`~/sessoes/abertas`): {len(frentes)} frente(s) aberta(s)."]
    for f in sorted(frentes, key=lambda x: x["id"]):
        L.append(f"- `{f['id']}` {f['projeto']} — {f['oque'][:140]} · desde {f['desde']}")
        if f["ultima"]:
            L.append(f"  - última nota: {f['ultima'][:220]}")
    return "\n".join(L)


def render_git(branch: str, sem_push: int | None, commits: list[str]) -> str:
    sp = "INDISPONÍVEL (sem upstream)" if sem_push is None else str(sem_push)
    L = [f"**Git** (`~/JFN`): branch `{branch}` · commits sem push: {sp}"]
    L += [f"- `{c}`" for c in commits]
    return "\n".join(L)


def substituir_blocos(texto: str, blocos: dict[str, str], carimbo: str) -> str:
    """Troca SÓ o conteúdo entre os marcadores; o resto do arquivo fica byte a byte. Sem marcadores: acrescenta a
    seção gerada no fim. Marcador aberto sem o de fechamento (ou duplicado) = erro: não adivinho onde termina."""
    faltam = []
    for nome, corpo in blocos.items():
        a, f = _abre(nome), _fecha(nome)
        na, nf = texto.count(a), texto.count(f)
        if na == 0 and nf == 0:
            faltam.append(nome)
            continue
        if na != 1 or nf != 1 or texto.index(a) > texto.index(f):
            raise ValueError(f"marcadores de '{nome}' inconsistentes ({na} abre, {nf} fecha)")
        i, j = texto.index(a) + len(a), texto.index(f)
        texto = texto[:i] + f"\n{corpo}\n" + texto[j:]
    if faltam:
        sec = [f"\n\n## 7. Estado gerado ({carimbo}; `python tools/retomada_gerar.py` — não editar entre os marcadores)\n"]
        for nome in faltam:
            sec.append(f"{_abre(nome)}\n{blocos[nome]}\n{_fecha(nome)}\n")
        texto = texto.rstrip("\n") + "\n".join(sec)
    texto = _CARIMBO.sub(rf"\g<1>{carimbo}\2", texto, count=1)
    return texto if texto.endswith("\n") else texto + "\n"


# ── leitura do mundo ──────────────────────────────────────────────────────────────────────────────────────────────
def _git(*args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout.strip()


def coletar(backlog: Path = BACKLOG, quadro: Path = QUADRO, n_commits: int = 12) -> dict[str, str]:
    itens = (yaml.safe_load(backlog.read_text(encoding="utf-8")) or {}).get("itens") or []
    frentes = [ler_frente(p.read_text(encoding="utf-8"), p.stem) for p in sorted(quadro.glob("*.md"))] \
        if quadro.is_dir() else []
    rc, branch = _git("branch", "--show-current")
    rc_up, n = _git("rev-list", "--count", "@{u}..HEAD")
    _rc, log = _git("log", f"-{n_commits}", "--format=%h %cd %s", "--date=format:%d/%m %H:%M")
    return {"backlog": render_backlog(itens),
            "quadro": render_quadro(frentes) if quadro.is_dir() else "**Quadro de sessões:** INDISPONÍVEL "
                                                                       f"({quadro} ausente)",
            "git": render_git(branch if rc == 0 else "?", int(n) if rc_up == 0 and n.isdigit() else None,
                              [ln[:150] for ln in log.splitlines()])}


_CARIMBO = re.compile(r"^(## 7\. Estado gerado \()[^;]*(;)", re.M)


def mudou(antes: str, depois: str) -> bool:
    """Só o carimbo de hora mudou não é mudança (senão cada rodada reescreveria o vault à toa)."""
    return _CARIMBO.sub(r"\1\2", antes) != _CARIMBO.sub(r"\1\2", depois)


def gravar(caminho: Path, texto: str) -> bool:
    if caminho.exists() and not mudou(caminho.read_text(encoding="utf-8"), texto):
        return False
    tmp = caminho.with_name(f".{caminho.name}.gerando")
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, caminho)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python tools/retomada_gerar.py")
    ap.add_argument("--arquivo", type=Path, default=RETOMADA)
    ap.add_argument("--stdout", action="store_true", help="imprime o resultado sem gravar")
    a = ap.parse_args(argv)
    original = a.arquivo.read_text(encoding="utf-8")
    novo = substituir_blocos(original, coletar(), datetime.now().strftime("%d/%m/%Y %H:%M"))
    if a.stdout:
        sys.stdout.write(novo)
        return 0
    print(f"retomada: {'regenerado' if gravar(a.arquivo, novo) else 'sem mudança'} — {a.arquivo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
