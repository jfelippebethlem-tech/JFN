#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""painel_css_inversao — QUEM muda de vencedor quando o CSS entra em `@layer`. Todas, de uma vez.

POR QUE ESTE ARQUIVO EXISTE, e a resposta e uma conta de tempo.

`@layer` troca a regra de desempate da cascata: dentro de uma camada quem decide e a
ESPECIFICIDADE; entre camadas, a especificidade nao conta — a camada mais alta vence, por menos
especifica que seja. Num CSS sedimentar como este (`.btn` declarado em 14 pontos, `.card` em tres
geracoes), isso inverte duelos que o arquivo usa de proposito.

Achar essas inversoes RODANDO O NAVEGADOR funciona e e caro: cada rodada e um baseline mais uma
comparacao, ~1 h nesta VM, e revela UMA familia de cada vez — corrigiu `.btn`, apareceu `.card`.
Com quatro ou cinco familias, o §6.2-A vira um dia inteiro de espera.

Este script responde a mesma pergunta em segundos, e responde INTEIRA. Ele nao substitui o
`painel_computado`: o navegador continua sendo quem diz a verdade, e a ordem certa e usar este
para achar a lista, marcar todas com `@camada:`, e gastar UMA verificacao viva no fim.

═══ COMO ELE DECIDE ═══

Para cada par de regras que declara a MESMA propriedade e que pode atingir o MESMO elemento:

    hoje      vence a de maior especificidade; empate, a ultima do documento
    camadado  vence a da camada mais alta; empate, maior especificidade; empate, a ultima

Se os dois vencedores diferem, ha inversao — e ela e listada com arquivo, linha e propriedade.

═══ A APROXIMACAO, DECLARADA ═══

"Pode atingir o mesmo elemento" e, no caso geral, indecidivel sem o DOM. A heuristica: dois
seletores sao comparaveis quando compartilham a mesma CHAVE — a ultima classe, id ou tag do
seletor, que e o que o navegador usa para indexar. `.btn` e `.btn.ghost` compartilham `btn`;
`.card` e `.grid>.card` compartilham `card`.

Isso GERA falso positivo (dois seletores com a mesma chave podem nunca casar o mesmo elemento) e
NAO gera falso negativo do tipo que importa — se dois seletores atingem o mesmo elemento, eles
compartilham a chave. Para uma lista que existe para ser conferida a mao antes de marcar, errar
para mais e o lado certo de errar.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.painel_css_inversao
    PYTHONPATH=. .venv/bin/python -m tools.painel_css_inversao --prop background,color
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "static" / "css" / "src"

# A ordem das camadas — a mesma de `painel_css_camadar`. Duplicar aqui seria a quinta lista
# divergente da casa; importar mantem as duas honestas.
try:
    from tools.painel_css_camadar import _blocos, _CAMADAS, _ESCOTILHA
except ImportError:                                          # rodado fora do PYTHONPATH
    sys.path.insert(0, str(_REPO))
    from tools.painel_css_camadar import _blocos, _CAMADAS, _ESCOTILHA

# Propriedades que valem a pena vigiar por padrao: as que MUDAM A CARA. Geometria e tipografia
# tambem podem inverter, mas a lista completa afoga o sinal — e quem le esta procurando o botao
# que trocou de cor, nao o `letter-spacing` que mudou 0,1px.
_PROP_PADRAO = ("background", "color", "border", "box-shadow", "opacity", "filter")


def _especificidade(sel: str) -> tuple[int, int, int]:
    """(id, classe/atributo/pseudo-classe, tipo/pseudo-elemento). Suficiente para comparar.

    `:not(...)`, `:is(...)` e `:has(...)` contam pelo argumento mais especifico — aqui, simplificado
    para "conta o conteudo como se estivesse solto", que superestima e nunca subestima.
    """
    s = re.sub(r"::[\w-]+", " PSEUDOEL ", sel)
    ids = len(re.findall(r"#[\w-]+", s))
    cls = len(re.findall(r"\.[\w-]+", s)) + len(re.findall(r"\[[^\]]+\]", s)) \
        + len(re.findall(r":(?!:)[\w-]+", s))
    tipos = len(re.findall(r"(?:^|[\s>+~,(])([a-zA-Z][\w-]*)", s)) + s.count("PSEUDOEL")
    return (ids, cls, tipos)


def _partes(sel: str) -> list[set[str]]:
    """O seletor em compostos, cada um como conjunto de simples. `.a .b.c` -> [{a},{b,c}]."""
    limpo = re.sub(r"::[\w-]+", "", sel)
    fora = []
    for comp in re.split(r"[\s>+~]+", limpo.strip()):
        if not comp:
            continue
        fora.append(set(re.findall(r"[.#]?[\w-]+(?:\([^)]*\))?", comp)))
    return fora


def _pseudoel(sel: str) -> str:
    m = re.search(r"::([\w-]+)", sel)
    return m.group(1) if m else ""


def _subsequencia(curta: list[set[str]], longa: list[set[str]]) -> bool:
    """Cada composto de `curta` aparece em `longa`, na ordem, com o composto da longa contendo o
    da curta. E o teste de "um seletor e uma versao mais qualificada do outro"."""
    i = 0
    for c in longa:
        if i < len(curta) and curta[i] <= c:
            i += 1
    return i == len(curta)


def _compativel(a: str, b: str) -> bool:
    """Os dois PODEM casar o mesmo elemento?

    A versao anterior perguntava so se compartilhavam a ultima classe, e isso deu 47 duelos com a
    maioria impossivel: `.sph .i .jico` contra `.chip .jico` nunca atingem o mesmo no, e
    `.btn::before` contra `.btn` sao elementos DIFERENTES (o pseudo e um filho gerado).

    Tres exigencias, e cada uma matou uma familia inteira de falso positivo:
      1. mesmo pseudo-elemento (ou nenhum nos dois);
      2. o composto-chave de um contido no do outro (`.btn` cabe em `.btn.ghost`);
      3. a cadeia de ancestrais do mais curto e SUBSEQUENCIA da do mais longo — `.card` cabe em
         `.grid > .card`, mas `.chip .jico` nao cabe em `.sph .i .jico`.
    """
    if _pseudoel(a) != _pseudoel(b):
        return False
    pa, pb = _partes(a), _partes(b)
    if not pa or not pb:
        return False
    if not (pa[-1] <= pb[-1] or pb[-1] <= pa[-1]):
        return False
    # OS DOIS SENTIDOS. A versao anterior escolhia a "curta" pelo COMPRIMENTO da lista, e com
    # listas do mesmo tamanho isso escolhe errado: para `.btn.ghost` contra `.btn` ela testava se
    # `{btn,ghost}` cabia em `{btn}` — nao cabe — e devolvia False. Resultado: o detector nao
    # achava o unico bug que se sabia existir, e teria entrado dando OK sobre o `.btn` intacto.
    # Qualquer um dos dois sendo a versao mais qualificada do outro basta. 
    return _subsequencia(pa, pb) or _subsequencia(pb, pa)


def _chave(sel: str) -> str:
    """A ultima classe/id/tag do seletor — o que o navegador usa para indexar a regra."""
    limpo = re.sub(r"::?[\w-]+(\([^)]*\))?", "", sel).strip()
    partes = re.split(r"[\s>+~]+", limpo)
    ultimo = partes[-1] if partes else limpo
    m = re.findall(r"[.#]?[\w-]+", ultimo)
    return m[-1].lstrip(".#") if m else ultimo


def _regras(css: str, arq: str, camada: str):
    """(seletor, propriedade, arquivo, linha, camada) para cada declaracao de topo relevante.

    Regra dentro de `@media`/`@supports` entra com o seletor dela: para efeito de inversao o que
    importa e quem vence QUANDO os dois casam, e a condicao do `@media` nao muda a cascata.
    """
    css = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", "", m.group(0)), css, flags=re.S)
    pilha: list[str] = []
    buf = ""
    linha = 1
    fora = []
    for ch in css:
        if ch == "\n":
            linha += 1
        if ch == "{":
            pilha.append(buf.strip().replace("\n", " "))
            buf = ""
        elif ch in "};":
            if ch == ";" or buf.strip():
                sel = pilha[-1] if pilha else ""
                if sel and not sel.startswith("@") and ":" in buf:
                    prop = buf.split(":", 1)[0].strip().lower()
                    if prop and not prop.startswith("--"):
                        for um in sel.split(","):
                            um = um.strip()
                            if um and not um.startswith("@"):
                                fora.append((um, prop, arq, linha, camada))
            if ch == "}" and pilha:
                pilha.pop()
            buf = ""
        else:
            buf += ch
    return fora


def inversoes(props: tuple[str, ...]) -> list[dict]:
    ordem = {n: i for i, (_, n) in enumerate(_CAMADAS)}
    todas = []
    for pref, nome in _CAMADAS:
        alvos = list(_SRC.glob(f"{pref}-*.css"))
        if not alvos:
            continue
        css = alvos[0].read_text(encoding="utf-8")
        # BLOCO por bloco, com o mesmo fatiador do `camadar`: so assim a escotilha `@camada:` cai
        # no bloco certo. Fatiar por comentario (a primeira versao) partia regra ao meio.
        desloc = 0
        for b in _blocos(css):
            m = _ESCOTILHA.search(b)
            cam = m.group(1) if m else nome
            for (sel, prop, arq, linha, c) in _regras(b, alvos[0].name, cam):
                todas.append((sel, prop, arq, linha + desloc, c))
            desloc += b.count("\n")

    # AGRUPA SO POR FAMILIA DE PROPRIEDADE, e compara par a par com `_compativel`.
    # A versao anterior agrupava por "ultima classe do seletor" e por isso NAO achava o bug
    # conhecido: `_chave('.btn.ghost')` devolvia `ghost`, `_chave('.btn')` devolvia `btn`, e os
    # dois nunca se encontravam. Um detector que nao acha o caso que se sabe existir nao prova
    # nada quando diz "nenhum" — foi assim que ele quase entrou dando OK sobre o `.btn` intacto.
    familias: dict[str, list[tuple]] = {}
    for k, (sel, prop, arq, linha, cam) in enumerate(todas):
        if not any(prop.startswith(p) for p in props):
            continue
        familias.setdefault(prop.split("-")[0], []).append((k, sel, prop, arq, linha, cam))

    # ── O VENCEDOR EFETIVO, e nao o duelo par a par ──────────────────────────────────────────
    # Comparar PARES acusa inversoes que nao mudam nada: `.btn.ghost:hover` do `base` perde para
    # `.btn` do `v55`, mas o proprio `v55` declara `.btn.ghost:hover`, que vence os dois nos dois
    # mundos. O duelo inverteu; a TELA nao mudou. Foram 31 acusacoes desse tipo, e uma lista com
    # 31 itens que nao mudam nada e uma lista que ninguem termina de conferir.
    #
    # Aqui cada regra e tomada como ARQUETIPO de elemento: junta-se tudo que casaria um elemento
    # atingido por ela (todo seletor que a generaliza, mais ela mesma) e pergunta-se quem vence o
    # conjunto — hoje e camadado. So entra na lista quando o VENCEDOR muda.
    achados = []
    vistos = set()
    for fam, lst in familias.items():
        for i, (ki, si, pi, ai, li, ci) in enumerate(lst):
            conj = [x for x in lst
                    if x[0] == ki or (_compativel(si, x[1]) and _subsequencia(_partes(x[1]),
                                                                             _partes(si)))]
            if len(conj) < 2:
                continue
            hoje = max(conj, key=lambda x: (_especificidade(x[1]), x[0]))
            depois = max(conj, key=lambda x: (ordem[x[5]], _especificidade(x[1]), x[0]))
            if hoje[0] == depois[0]:
                continue
            chave = (hoje[1], hoje[3], hoje[4], depois[1], depois[3], depois[4], fam)
            if chave in vistos:
                continue
            vistos.add(chave)
            achados.append({"familia": fam,
                            "hoje_vence": (hoje[1], hoje[3], hoje[4], hoje[5], hoje[2]),
                            "camadado_vence": (depois[1], depois[3], depois[4], depois[5], depois[2])})
    return achados


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prop", default=",".join(_PROP_PADRAO))
    a = ap.parse_args(argv)
    props = tuple(x.strip() for x in a.prop.split(",") if x.strip())

    achados = inversoes(props)
    if not achados:
        print(f"OK — nenhuma inversao de vencedor em [{', '.join(props)}] ao camadar.")
        return 0

    # agrupa por chave: e assim que se marca (um bloco por vez), e assim que se le
    porchave: dict[str, list[dict]] = {}
    for x in achados:
        porchave.setdefault(x["hoje_vence"][0], []).append(x)

    print(f"=== {len(achados)} INVERSAO(OES) em {len(porchave)} chave(s) ===")
    print("Cada uma e um duelo que HOJE a especificidade resolve e que a camada vai resolver ao")
    print("contrario. Confira e marque o bloco perdedor com `@camada: <a camada do vencedor>`.\n")
    for chave, lst in sorted(porchave.items(), key=lambda kv: -len(kv[1])):
        h = lst[0]["hoje_vence"]
        print(f"  `{chave}`  ({h[1]}:{h[2]}, camada {h[3]}) — {len(lst)} duelo(s):")
        for x in lst[:5]:
            d = x["camadado_vence"]
            print(f"     perde para `{d[0][:56]}`  ({d[1]}:{d[2]}, camada {d[3]})  [{x['familia']}]")
        if len(lst) > 5:
            print(f"     … e mais {len(lst) - 5}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
