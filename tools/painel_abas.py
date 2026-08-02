"""Fonte unica da lista de abas do painel — lida do proprio HTML.

Os dois auditores (contraste e layout) mantinham uma copia manual de 9 abas. O
painel tem 51. Copia de lista diverge — foi assim que a constante de dispensa
ganhou uma terceira copia dentro de um detector e produziu falso positivo publico.
Aqui a divergencia era pior porque silenciosa: o auditor dizia "9 abas limpas" e o
laudo era lido como "o painel esta limpo".

Le o bloco `const TABS={...}` de static/jfn-painel.html e devolve os ids na ordem
em que o painel os monta.
"""

from __future__ import annotations

import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
PAINEL = _RAIZ / "static" / "jfn-painel.html"
# v49: os 337 KB de JS sairam de dentro do HTML para `static/js/painel.js` (servido com gzip e
# cache). O `const TABS` foi junto. Procurar so no HTML passou a levantar "nao achei TABS" — que e
# verdade e nao e problema. As duas formas sao lidas: enquanto o monolito existir, e depois dele.
# v58: o monolito virou `static/js/src/` + bundle. `TABS` mora no fonte, e o fonte e o que um
# humano edita — e dele que esta lista tem de sair. O bundle NAO entra: ele e derivado, e ler o
# derivado esconderia justamente o caso "editei o fonte e nao reconstrui".
_FONTES = (_RAIZ / "static" / "js" / "src" / "app" / "tabs.js",
           _RAIZ / "static" / "js" / "src" / "entrada.js",
           _RAIZ / "static" / "js" / "painel.js",
           PAINEL)

_BLOCO = re.compile(r"const TABS=\{(.*?)\n\};", re.S)
_ESFERA = re.compile(r"^\s{2}(\w+):\[", re.M)
_ID = re.compile(r"id:'([a-z_]+)'")


def _corpo() -> str:
    tentadas = []
    for f in _FONTES:
        tentadas.append(str(f))
        if not f.exists():
            continue
        m = _BLOCO.search(f.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    raise RuntimeError("nao achei `const TABS={...}` em nenhuma fonte: " + ", ".join(tentadas))


def abas_por_esfera() -> dict[str, list[str]]:
    """{esfera: [id, ...]} na ordem do painel."""
    corpo = _corpo()
    marcas = list(_ESFERA.finditer(corpo))
    fora: dict[str, list[str]] = {}
    for i, mk in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(corpo)
        fora[mk.group(1)] = _ID.findall(corpo[mk.end(): fim])
    return fora


def abas() -> list[str]:
    """Todos os ids, na ordem do painel."""
    return [a for lista in abas_por_esfera().values() for a in lista]


if __name__ == "__main__":
    for esf, lista in abas_por_esfera().items():
        print(f"{esf:12s} {len(lista):2d}  {' '.join(lista)}")
