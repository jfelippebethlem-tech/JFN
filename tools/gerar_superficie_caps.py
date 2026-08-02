#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera `static/js/caps.js` — um botão por FUNÇÃO MESTRA, derivado de `capabilities.yaml`.

PEDIDO DO DONO: "facilitar criando um botão pra cada função mestra no painel".

POR QUE DERIVADO E NÃO ESCRITO À MÃO. `capabilities.yaml` já é a fonte única: o pre-commit valida e
regenera `data/jfn_tools.json`, `data/yoda_capabilities_prompt.txt` e `docs/CAPACIDADES.md` a partir
dele. Escrever os botões à mão criaria a QUINTA cópia da mesma lista — e a casa já tem cicatriz
disso: a constante de teto de dispensa ganhou uma terceira cópia divergente dentro de um detector e
produziu falso positivo público. Uma fonte, várias superfícies.

POR QUE EM BUILD E NÃO EM RUNTIME. Se os botões viessem de `fetch('/api/lista')`, a string literal
`/api/relatorio/orgao` **nunca apareceria no texto servido** — e as duas catracas de rota
(`test_rotas_sem_orfa`, teto 0, e `test_rotas_sem_superficie`) leem TEXTO. Runtime seria elegante e
faria a catraca acusar dezenas de rotas órfãs que não são órfãs. Gerando em arquivo, a rota aparece,
a catraca enxerga, e o botão existe.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.gerar_superficie_caps            # grava static/js/caps.js
    PYTHONPATH=. .venv/bin/python -m tools.gerar_superficie_caps --conferir # só verifica se está em dia
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parent.parent
_YAML = _REPO / "capabilities.yaml"
_SAIDA = _REPO / "static" / "js" / "caps.js"


def _ic_grupo(grupo: str) -> str:
    """Emoji inicial do rótulo do grupo (chave do JFN_ICO no painel); '' se não houver."""
    p = grupo.split(" ", 1)[0]
    return p if p and not p[0].isalnum() else ""


def _rot_grupo(grupo: str) -> str:
    """Rótulo do grupo sem o emoji inicial."""
    return grupo[len(_ic_grupo(grupo)):].strip() or grupo


def mestras() -> list[dict]:
    """Capacidades PRONTAS com bloco `menu:` — as que o dono quer alcançar por botão."""
    dados = yaml.safe_load(_YAML.read_text(encoding="utf-8"))
    saida = []
    for c in dados.get("capacidades") or []:
        menu = c.get("menu")
        if not menu or str(c.get("status", "")).upper() != "PRONTO":
            continue
        grupo = menu.get("grupo") or c.get("dominio") or "geral"
        saida.append({
            "id": c.get("id"),
            "grupo": grupo,
            # o emoji vive colado no rótulo do grupo na YAML (chave de ordenação e de
            # docs/CAPACIDADES.md). Aqui ele é SEPARADO para o painel desenhar o glifo
            # do jfn-icones.js no lugar do emoji colorido — sem mexer na YAML.
            "grupo_ic": _ic_grupo(grupo),
            "grupo_rot": _rot_grupo(grupo),
            "nome": menu.get("nome") or c.get("id"),
            "cmd": menu.get("cmd") or "",
            "exemplo": menu.get("exemplo") or "",
            "tipo": c.get("tipo") or "",
            "metodo": (c.get("metodo") or "GET").upper(),
            # a ROTA literal precisa sair no arquivo: é o que as catracas de rota enxergam
            "rota": c.get("rota") or "",
            "ordem": menu.get("ordem", 999),
            "descricao": (c.get("descricao") or "").split(".")[0][:180],
        })
    saida.sort(key=lambda x: (x["grupo"], x["ordem"], x["nome"]))
    return saida


_CABECALHO = """\
/* GERADO por tools/gerar_superficie_caps.py — NÃO EDITAR À MÃO.
   Fonte única: capabilities.yaml (bloco `menu:` das capacidades com status PRONTO).
   Editar aqui cria uma cópia divergente da lista, que é exatamente a família de bug que a casa já
   pagou três vezes. Mexa no YAML e regere.
   As rotas aparecem como STRING LITERAL de propósito: é assim que test_rotas_sem_orfa (teto 0) e
   test_rotas_sem_superficie enxergam que a capacidade tem ponto de entrada. */
"""


def render(caps: list[dict]) -> str:
    return (_CABECALHO
            + "const CAPS_MESTRAS = "
            + json.dumps(caps, ensure_ascii=False, indent=1)
            + ";\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conferir", action="store_true",
                    help="não grava; sai !=0 se o arquivo estiver desatualizado")
    a = ap.parse_args()
    caps = mestras()
    novo = render(caps)
    if a.conferir:
        atual = _SAIDA.read_text(encoding="utf-8") if _SAIDA.exists() else ""
        if atual != novo:
            print(f"DESATUALIZADO: {_SAIDA} difere do que capabilities.yaml produz. "
                  "Rode `python -m tools.gerar_superficie_caps`.")
            return 1
        print(f"em dia — {len(caps)} funções mestras")
        return 0
    _SAIDA.parent.mkdir(parents=True, exist_ok=True)
    _SAIDA.write_text(novo, encoding="utf-8")
    grupos = sorted({c["grupo"] for c in caps})
    print(f"{_SAIDA}: {len(caps)} funções mestras em {len(grupos)} grupos ({', '.join(grupos)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
