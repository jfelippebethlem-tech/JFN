#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""painel_efeitos_boot — o que o painel EXECUTA ao carregar, e em que ordem.

POR QUE ESTE SCRIPT EXISTE. O boot do painel e uma sequencia de 24 efeitos de topo: registros de
listener, duas IIFEs, um `fetch` de sonda, `sabreStart`, `portalStart`, um `setTimeout` de medicao.
Enquanto o painel foi UM script classico, essa ordem era a ordem do arquivo e ninguem precisava
pensar nela. Com modulos ES ela deixa de ser: efeito de topo de um modulo roda na ordem do IMPORT,
nao na ordem em que o codigo aparece no entrypoint. Quebrar um dominio de abas para fora pode,
sozinho, adiantar um `portalStart()` — e o sintoma nao e um erro, e o portal aparecendo depois do
cockpit, ou a corrida com View Transitions que ja matou este boot uma vez.

A DECISAO DE DESENHO, e ela e deliberada: os 24 efeitos NAO sao movidos para um bloco unico no fim
do entrypoint. Mover 24 efeitos de lugar e, literalmente, a operacao que reordena um boot em
silencio — o risco que se quer evitar seria pago para evitar o risco. Em vez disso eles ficam onde
estao e passam a ser INVENTARIADOS: este extrator le a ordem real, e o teste companheiro
(`tests/test_painel_ordem_de_boot.py`) falha se ela mudar, se um efeito sumir, ou se um efeito novo
aparecer sem alguem ter pensado nele.

A segunda garantia e a que a migracao precisa: NENHUM modulo sob `static/js/src/**` pode ter efeito
de topo. Enquanto isso valer, a ordem de import e irrelevante e o entrypoint continua sendo o unico
lugar onde o boot acontece.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.painel_efeitos_boot           # lista em ordem
    PYTHONPATH=. .venv/bin/python -m tools.painel_efeitos_boot --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "static" / "js" / "src"
_ENTRADA = _SRC / "entrada.js"

# Linha em coluna 0 que NAO abre uma declaracao, um comentario, um fechamento, nem e continuacao
# de literal (o shader do portal e um template de varias linhas em coluna 0 — dai `uniform`,
# `float`, `void`, `vec` e companhia na lista de exclusao).
#
# `export {` entra na lista na v59, quando o corte da cena e das abas (§6.2-B) passou a usar
# reexport para manter a porta de entrada dos chamadores. Ele NAO e efeito, com ou sem `from`: e
# declaracao estatica, resolvida na ligacao dos modulos, e nao executa uma instrucao sequer. Sem
# esta linha o detector acusava `cena/index.js` e `abas/index.js` de terem efeito de topo — falso
# positivo que, se fosse aceito como verdade, empurraria o corte para uma solucao pior (reescrever
# a lista de import de todo mundo) para resolver um problema que nao existe.
#
# A regra e por PREFIXO e nao pela linha inteira porque a lista de nomes reexportados quebra em
# varias linhas; as continuacoes comecam com espaco e ja caem no `\s` da lista.
_NAO_E_EFEITO = re.compile(
    r"^(?:export\s*\{"
    r"|(?:export\s+)?(?:const|let|var|function|class|async\s+function|import|//|/\*|\*|\}|\)|\]|;"
    r"|\s|\$|`|'|\"|<|uniform|float|void|vec\d|gl_|precision|attribute|varying|if\s*\())"
)

# Assinatura curta e ESTAVEL do efeito: o que ele faz, sem o corpo. E o que o teste compara —
# comparar a linha inteira faria qualquer reformatacao virar falha.
_ASSINATURAS = (
    (re.compile(r"^window\.__jfnBootReadyState"), "testemunha:readyState"),
    (re.compile(r"^(?:document\.|window\.)?addEventListener\(\s*'([A-Za-z]+)'"), "listener:{}"),
    (re.compile(r"^setTimeout\(\s*([A-Za-z_$][\w$]*)"), "setTimeout:{}"),
    (re.compile(r"^fetch\(\s*'([^']+)'"), "fetch:{}"),
    (re.compile(r"^\(async\s*\(\)"), "iife:boot-assincrono"),
    (re.compile(r"^\(function\s+([A-Za-z_$][\w$]*)"), "iife:{}"),
    (re.compile(r"^\(function\s*\(\)"), "iife:anonima"),
    (re.compile(r"^\(\(\)\s*=>"), "iife:arrow"),
    (re.compile(r"^window\.([A-Za-z_$][\w$]*)\s*="), "ponte:window.{}"),
    (re.compile(r"^Object\.assign\(window"), "ponte:Object.assign"),
    (re.compile(r"^for\s*\("), "ponte:defineProperty"),
    # Chamada de topo, com ou sem argumento. `sabreStart({...})` passou a levar ganchos quando o
    # barramento virou modulo, e a regra antiga — que exigia parenteses VAZIOS — deixou de
    # reconhece-la. Regra generica fica por ULTIMO de proposito: `setTimeout(` e `fetch(` tem
    # assinatura propria acima e precisam ganhar dela.
    (re.compile(r"^([A-Za-z_$][\w$]*)\("), "chamada:{}()"),
)


def _assinar(linha: str) -> str:
    for rx, molde in _ASSINATURAS:
        m = rx.match(linha)
        if m:
            return molde.format(*m.groups()) if m.groups() else molde
    return "DESCONHECIDO:" + linha[:60]


def efeitos(fonte: Path | None = None) -> list[dict]:
    """Efeitos de topo do arquivo, na ordem em que serao executados."""
    alvo = fonte or _ENTRADA
    if not alvo.exists():
        return []
    fora = []
    for n, ln in enumerate(alvo.read_text(encoding="utf-8").split("\n"), 1):
        if not ln or _NAO_E_EFEITO.match(ln):
            continue
        fora.append({"linha": n, "assinatura": _assinar(ln), "fonte": ln[:100]})
    return fora


def modulos_com_efeito() -> dict[str, list[dict]]:
    """Modulos que NAO deviam ter efeito de topo e tem. Vazio e o estado correto."""
    fora: dict[str, list[dict]] = {}
    if not _SRC.is_dir():
        return fora
    for p in sorted(_SRC.rglob("*.js")):
        if p == _ENTRADA:
            continue
        e = efeitos(p)
        if e:
            fora[p.relative_to(_REPO).as_posix()] = e
    return fora


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    seq = efeitos()
    sujos = modulos_com_efeito()
    if a.json:
        print(json.dumps({"sequencia": [e["assinatura"] for e in seq],
                          "detalhe": seq, "modulos_com_efeito": sujos},
                         ensure_ascii=False, indent=1))
        return 1 if sujos else 0

    print(f"SEQUENCIA DE BOOT — {len(seq)} efeitos de topo em src/entrada.js\n")
    for e in seq:
        print(f"  {e['linha']:5d}  {e['assinatura']:28s}  {e['fonte'][:58]}")
    if sujos:
        print(f"\n=== {len(sujos)} MODULO(S) COM EFEITO DE TOPO ===")
        print("Efeito de topo em modulo roda na ordem do IMPORT, nao na do entrypoint —")
        print("reordena o boot em silencio. Mova para a sequencia do entrada.js.")
        for arq, lst in sujos.items():
            for e in lst:
                print(f"  {arq}:{e['linha']}  {e['fonte'][:70]}")
        return 1
    print("\nOK — nenhum modulo tem efeito de topo; o boot acontece so no entrypoint.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
