# -*- coding: utf-8 -*-
"""Índice da memória dos agentes (`MEMORY.md`) dentro do limite — reorganização automática e segura.

Por quê: o Claude Code carrega só as 200 primeiras linhas do `MEMORY.md`. Medido em 20/11/2026: 213 linhas — as 13
cortadas são as do FIM, isto é, as entradas mais novas (entrada nova é acrescentada embaixo, com o gancho escrito
na própria linha). O detalhe já mora no arquivo de cada memória (362 de 362 têm `description` no cabeçalho); o
índice só precisa dizer que a memória existe e de que tema é.

O que a reorganização faz, até o índice caber em `ALVO` linhas:
  · reempacota as linhas só de slugs de cada seção (medido: 2 a 3 slugs por linha onde cabem 5) e leva cada
    entrada com gancho para a seção do tema dela (as novas vinham sendo empilhadas na última seção);
  · se ainda não couber, do mais antigo para o mais novo: a entrada com gancho (`- `slug` — texto`) vira só o
    slug, empacotado na seção do TEMA dela (`TEMAS`; sem tema pelo nome, a memória `type: feedback` é regra do dono);
  · o gancho que sai vai para o arquivo-razão `RAZAO`, na mesma pasta — nada é apagado;
  · as entradas mais novas mantêm o gancho; arquivo de memória que estava fora do índice entra no tema dele.
O que ela nunca faz: tocar em arquivo de memória; rebaixar entrada sem arquivo ou sem `description` (ali o gancho
é o único registro); gravar um índice que perca slug ou link (`conferir`) — nesse caso recusa e nada é escrito.

Uso:
    python tools/memoria_indice.py estado            # mede; sai com 1 se passou do limite (serve de sensor)
    python tools/memoria_indice.py propor --saida D  # grava a proposta em D/ (não toca na pasta de memória)
    python tools/memoria_indice.py aplicar           # grava, guardando cópia `MEMORY.md.antes-<carimbo>`
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

PASTA = Path.home() / ".claude" / "projects" / "-home-ubuntu" / "memory"
INDICE = "MEMORY.md"
RAZAO = "indice-ganchos-arquivados.md"
LIMITE = 200        # linhas que o Claude Code carrega
ALVO = 170          # folga para ~30 entradas novas antes de a reorganização rodar de novo
LARGURA = 190       # o carregamento pede entrada de índice abaixo de ~200 caracteres
DIVERSOS = "Diversos"
REGRAS = "Regras e diretrizes permanentes"
# tema → pedaços de slug. Os títulos são os das seções que o índice já tem; a ordem decide o empate.
TEMAS = (
    ("SEI", ("sei-",)),
    ("Painel (design e armadilhas)", ("painel", "aba-", "css-", "modo-sobrio")),
    ("Polimonitor / Bond", ("polimonitor", "bond-", "apoiadores", "curtidores", "viral")),
    ("Dados e fontes", ("siafe", "tfe", "ob-", "pncp", "doerj", "doweb", "dados-abertos", "tse-", "inep", "siconfi",
                        "datajud", "eleicao", "fonte")),
    ("Detecção, dossiê e relatórios", ("pericia", "detector", "conluio", "fiscalizacao", "indeterminad", "laudo",
                                      "recaptura", "dossie", "relatorio", "fachada", "foto", "triagem", "achado")),
    ("Infra, IA e ecossistema", ("yoda", "hermes", "claude", "gemini", "vm", "disco", "cron", "github", "ruflo", "api-",
                                 "assinatura", "it-campo", "update", "whatsapp", "atena", "modelo", "catalogo-free",
                                 "contingencia", "llm", "openrouter", "youtube", "git-", "vacuum", "cerebro", "brain",
                                 "higgsfield", "automelhoria", "propagacao", "otimizacao")),
)
_SLUG = re.compile(r"`([A-Za-z0-9][A-Za-z0-9_.\-]*)`")
_LINK = re.compile(r"\]\(([^)\s]+)\)")
_GANCHO = re.compile(r"^- `([A-Za-z0-9][A-Za-z0-9_.\-]*)`(?: \([^)]*\))? — (.+)$")


def referencias(texto: str) -> set[str]:
    """O que o índice aponta: em cada entrada (`- …`), os slugs e links ANTES do gancho. Crase dentro do gancho
    (`ps`, `--bare`) é texto, não referência."""
    refs = set()
    for linha in texto.splitlines():
        if linha.startswith("- "):
            cabeca = linha.split(" — ", 1)[0]
            refs |= set(_SLUG.findall(cabeca)) | set(_LINK.findall(cabeca))
    return refs


def _cabecalhos(pasta: Path) -> dict[str, str]:
    """slug → `type` do cabeçalho ("" se não declara), só dos arquivos que têm `description` (o detalhe mora lá)."""
    out = {}
    for arq in pasta.glob("*.md"):
        if arq.name in (INDICE, RAZAO):
            continue
        txt = arq.read_text(encoding="utf-8", errors="replace")[:2000]
        cab = txt.split("\n---", 2)[0] if txt.startswith("---") else ""
        if re.search(r"^description:\s*\S", cab, re.M):
            tipo = re.search(r"^\s*type:\s*(\w+)", cab, re.M)
            out[arq.stem] = tipo.group(1) if tipo else ""
    return out


def _tema(slug: str, tipo: str = "") -> str:
    for titulo, pedacos in TEMAS:
        if any(slug.startswith(p) or f"-{p}" in f"-{slug}" for p in pedacos):
            return titulo
    return REGRAS if tipo == "feedback" else DIVERSOS


def _so_fichas(linha: str) -> list[str] | None:
    """As fichas de uma linha que é só slugs/links separados por ` · ` (None se a linha tem gancho ou outro texto)."""
    if not linha.startswith("- ") or " — " in linha:
        return None
    fichas = linha[2:].split(" · ")
    return fichas if all(re.fullmatch(r"`[^`]+`|\[[^\]]*\]\([^)\s]+\)", f.strip()) for f in fichas) else None


def estado(pasta: Path = PASTA) -> dict:
    texto = (pasta / INDICE).read_text(encoding="utf-8")
    linhas = texto.splitlines()
    refs = referencias(texto)
    arquivos = {a.stem for a in pasta.glob("*.md") if a.name not in (INDICE, RAZAO)}
    return {"linhas": len(linhas), "limite": LIMITE, "cortadas_no_carregamento": max(0, len(linhas) - LIMITE),
            "entradas_com_gancho": sum(1 for x in linhas if x.startswith("- ") and " — " in x),
            "linhas_acima_da_largura": sum(1 for x in linhas if len(x) > 200),
            "fora_do_indice": sorted(arquivos - refs),
            "sem_arquivo": sorted(r for r in refs - arquivos if "/" not in r)}


def _empacotar(fichas: list[str]) -> list[str]:
    linhas, atual = [], "-"
    for f in fichas:
        prox = f"{atual} {f}" if atual == "-" else f"{atual} · {f}"
        if len(prox) > LARGURA and atual != "-":
            linhas.append(atual)
            prox = f"- {f}"
        atual = prox
    return linhas + ([atual] if atual != "-" else [])


def _montar(linhas: list[str], rebaixar: set[int], por_tema: dict[str, list[str]], mover: dict[int, str]) -> str:
    """O índice remontado por seção: as linhas só-de-fichas reempacotadas (com as fichas de `por_tema`), depois as
    entradas com gancho na ordem em que estavam. `rebaixar` = linhas que saem (viraram ficha em `por_tema`);
    `mover` = linha com gancho → seção do tema dela."""
    cabecalho: list[str] = []
    secoes: dict[str, dict[str, list[str]]] = {}
    atual = None
    for i, linha in enumerate(linhas):
        if linha.startswith("## "):
            atual = secoes.setdefault(linha[3:].strip(), {"fichas": [], "ganchos": []})
        elif atual is None:
            cabecalho.append(linha)
        elif not linha.strip() or i in rebaixar:
            continue
        elif (fs := _so_fichas(linha)) is not None:
            atual["fichas"] += [f.strip() for f in fs]
        else:
            atual["ganchos"].append((i, linha))
    for titulo in list(secoes):                                # só depois de conhecer todas as seções
        for i, linha in [g for g in secoes[titulo]["ganchos"] if mover.get(g[0], titulo) != titulo]:
            secoes[titulo]["ganchos"].remove((i, linha))
            secoes.setdefault(mover[i], {"fichas": [], "ganchos": []})["ganchos"].append((i, linha))
    for titulo, fs in por_tema.items():
        secoes.setdefault(titulo, {"fichas": [], "ganchos": []})["fichas"] += fs
    while cabecalho and not cabecalho[-1].strip():
        cabecalho.pop()
    out = cabecalho
    for titulo, sec in secoes.items():
        out += ["", f"## {titulo}", *_empacotar(sec["fichas"]), *(x for _, x in sorted(sec["ganchos"]))]
    return "\n".join(out).rstrip("\n") + "\n"


def conferir(antes: str, depois: str) -> list[str]:
    """Motivos para NÃO gravar `depois` no lugar de `antes` (lista vazia = pode)."""
    motivos = []
    perdidas = referencias(antes) - referencias(depois)
    if perdidas:
        motivos.append(f"perderia {len(perdidas)} referência(s): {', '.join(sorted(perdidas)[:8])}")
    n = len(depois.splitlines())
    if n > LIMITE:
        motivos.append(f"ficaria com {n} linhas (limite {LIMITE})")
    return motivos


def reorganizar(pasta: Path = PASTA) -> dict:
    """A proposta: {texto, rebaixados: [slug], ganchos_arquivados: texto do razão, entraram: [slug], motivo}."""
    antes = (pasta / INDICE).read_text(encoding="utf-8")
    linhas = antes.splitlines()
    tipos = _cabecalhos(pasta)
    orfaos = estado(pasta)["fora_do_indice"]
    if len(linhas) <= LIMITE and not orfaos:
        return {"texto": antes, "rebaixados": [], "entraram": [], "ganchos_arquivados": "", "motivo": "dentro do limite"}
    candidatos = [(i, m.group(1), m.group(2)) for i, x in enumerate(linhas)
                  if (m := _GANCHO.match(x)) and m.group(1) in tipos and not _LINK.search(x)]
    # entrada com gancho acrescentada no fim do arquivo vai para a seção do tema dela (sem tema reconhecido, fica)
    mover = {i: t for i, slug, _ in candidatos if (t := _tema(slug, tipos[slug])) != DIVERSOS}
    for n in range(len(candidatos) + 1):                   # do mais antigo (topo) para o mais novo, só o necessário
        por_tema: dict[str, list[str]] = {}
        for slug in [s for _, s, _ in candidatos[:n]] + orfaos:
            por_tema.setdefault(_tema(slug, tipos.get(slug, "")), []).append(f"`{slug}`")
        texto = _montar(linhas, {i for i, _, _ in candidatos[:n]}, por_tema, mover)
        if len(texto.splitlines()) <= ALVO:
            break
    razao = "".join(f"- `{s}` — {g}\n" for _, s, g in candidatos[:n])
    return {"texto": texto, "rebaixados": [s for _, s, _ in candidatos[:n]], "entraram": orfaos,
            "ganchos_arquivados": razao, "motivo": None}


def _texto_do_razao(pasta: Path, novos: str) -> str:
    arq = pasta / RAZAO
    base = arq.read_text(encoding="utf-8") if arq.exists() else (
        "---\nname: indice-ganchos-arquivados\ndescription: ganchos que saíram do MEMORY.md na reorganização automática "
        "(tools/memoria_indice.py do JFN); o detalhe vigente de cada memória é a description do arquivo dela\n"
        "metadata:\n  type: reference\n---\n")
    return base + f"\n## Reorganização de {time.strftime('%d/%m/%Y %H:%M')}\n{novos}"


def aplicar(pasta: Path = PASTA) -> dict:
    """Grava a proposta na pasta de memória. Só escreve o índice, a cópia do anterior e o arquivo-razão."""
    antes = (pasta / INDICE).read_text(encoding="utf-8")
    r = reorganizar(pasta)
    if r["texto"] == antes:
        return {"aplicado": False, "motivo": r["motivo"] or "nada a mudar", "linhas": len(antes.splitlines())}
    motivos = conferir(antes, r["texto"])
    if motivos:
        raise RuntimeError("reorganização recusada: " + "; ".join(motivos))
    copia = pasta / f"{INDICE}.antes-{time.strftime('%Y%m%d-%H%M%S')}"
    copia.write_text(antes, encoding="utf-8")
    if r["ganchos_arquivados"]:
        (pasta / RAZAO).write_text(_texto_do_razao(pasta, r["ganchos_arquivados"]), encoding="utf-8")
    tmp = pasta / f".{INDICE}.novo"
    tmp.write_text(r["texto"], encoding="utf-8")
    tmp.replace(pasta / INDICE)
    return {"aplicado": True, "copia": str(copia), "linhas_antes": len(antes.splitlines()),
            "linhas_depois": len(r["texto"].splitlines()), "rebaixados": len(r["rebaixados"]), "entraram": len(r["entraram"])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Índice da memória dos agentes dentro do limite de carregamento")
    ap.add_argument("cmd", choices=("estado", "propor", "aplicar"))
    ap.add_argument("--pasta", type=Path, default=PASTA)
    ap.add_argument("--saida", type=Path, help="pasta onde `propor` grava a proposta")
    a = ap.parse_args(argv)
    if a.cmd == "estado":
        e = estado(a.pasta)
        print(json.dumps(e, ensure_ascii=False, indent=1))
        return 1 if e["linhas"] > LIMITE else 0
    if a.cmd == "aplicar":
        print(json.dumps(aplicar(a.pasta), ensure_ascii=False, indent=1))
        return 0
    if not a.saida:
        ap.error("propor exige --saida")
    antes = (a.pasta / INDICE).read_text(encoding="utf-8")
    r = reorganizar(a.pasta)
    a.saida.mkdir(parents=True, exist_ok=True)
    (a.saida / INDICE).write_text(r["texto"], encoding="utf-8")
    if r["ganchos_arquivados"]:
        (a.saida / RAZAO).write_text(_texto_do_razao(a.pasta, r["ganchos_arquivados"]), encoding="utf-8")
    print(json.dumps({"linhas_antes": len(antes.splitlines()), "linhas_depois": len(r["texto"].splitlines()),
                      "rebaixados": len(r["rebaixados"]), "entraram_no_indice": len(r["entraram"]),
                      "recusas": conferir(antes, r["texto"]), "proposta": str(a.saida / INDICE)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
