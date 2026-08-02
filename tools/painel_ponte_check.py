#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""painel_ponte_check — todo nome que um handler inline usa AINDA existe no escopo global?

POR QUE ESTE SCRIPT EXISTE. O painel tem ~160 atributos `on*="..."` espalhados por 59 renders. O
navegador avalia esse codigo no escopo GLOBAL: `onclick="ir('g_acoes')"` so funciona porque `ir`
e uma global de verdade. Enquanto o painel foi um unico script classico isso era automatico e
invisivel. No momento em que o fonte vira modulos com build (`--format=iife`), TODO o codigo passa
a viver dentro de uma funcao — e cada nome que os handlers usam precisa ser reinstalado no `window`
de proposito. Esquecer um nao quebra o boot: quebra UM botao, de UMA aba, na hora em que alguem
clicar. Sem erro na revisao, sem erro no smoke test.

E ha um caso pior, que e o motivo real deste extrator olhar tambem posicao de ATRIBUICAO:

    onchange="_respProc=this.value;ir('e_resp')"

`_respProc` nao e lido, e ESCRITO de dentro do HTML. Reexportar a funcao no window resolve `ir`;
nao resolve `_respProc`. `window._respProc = 'X'` nao atualiza um `let _respProc` de modulo — o
filtro simplesmente para de responder, calado. Sao 20+ nomes nessa condicao, e a unica forma
correta de reinstala-los e `Object.defineProperty` com get E set encaminhando para a variavel do
modulo (a "ponte").

COMO LER O RESULTADO. Antes da migracao (painel.js monolitico) este check tem de dar 100% trivial:
tudo que os handlers usam ja e global. Isso NAO e um teste inutil — e a calibragem do extrator,
feita enquanto ele ainda nao esta segurando nada. Se ele acusa falso positivo hoje, vai acusar
falso negativo depois.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.painel_ponte_check            # laudo humano
    PYTHONPATH=. .venv/bin/python -m tools.painel_ponte_check --json     # para teste/CI
    PYTHONPATH=. .venv/bin/python -m tools.painel_ponte_check --listar   # so os nomes, um por linha
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_STATIC = _REPO / "static"

# Fontes que podem conter handler inline: o shell HTML e todo JS que monta markup.
# Pos-migracao, `static/js/src/**` entra sozinho — o glob ja cobre.
_HTML = _STATIC / "jfn-painel.html"


def _fontes_js() -> list[Path]:
    js = _STATIC / "js"
    src = js / "src"
    if src.is_dir():
        return sorted(p for p in src.rglob("*.js"))
    mono = js / "painel.js"
    return [mono] if mono.exists() else []


# --- extracao ------------------------------------------------------------------------------------

# `on<evento>="..."` — DOTALL porque ha atributo que atravessa linha (o `_acPagPick`, com um
# `JSON.stringify(...).replace(/\n/g,...)` no meio). Aspas simples tambem aparecem em HTML gerado.
_ATTR = re.compile(r"""\bon([a-z]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.S)

# Handler montado em TEMPO DE EXECUCAO: `el.setAttribute('onclick', `ordenar('${x}',this)`)`.
# Nao e um atributo literal no fonte, entao o `_ATTR` nunca o veria — e o navegador o avalia no
# escopo global exatamente igual. Foi assim que `ordenar` quase ficou de fora da ponte na etapa 3:
# a funcao saiu para `nucleo/lista.js`, o bundle a fechou dentro do IIFE, e o unico sintoma seria
# um ReferenceError no clique do botao A-Z de uma lista. Nenhum teste veria; nenhuma revisao veria.
_SETATTR = re.compile(r"""setAttribute\(\s*['"]on[a-z]+['"]\s*,\s*(?:`([^`]*)`|'([^']*)'|"([^"]*)")""",
                      re.S)

# Interpolacao de template: `${...}` roda no escopo do MODULO, na hora de montar a string —
# nao no escopo global, na hora do clique. Nao entra na ponte. Remover com contagem de chaves,
# porque ha interpolacao com objeto literal dentro (`${JSON.stringify({a:1})}`).
def _sem_interpolacao(s: str) -> str:
    out, i, n = [], 0, len(s)
    while i < n:
        if s.startswith("${", i):
            prof, i = 1, i + 2
            while i < n and prof:
                if s[i] == "{":
                    prof += 1
                elif s[i] == "}":
                    prof -= 1
                i += 1
            out.append(" ")            # espaco: nao colar os tokens vizinhos
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


# Literais de string. As aspas DUPLAS entram na lista porque ha handler escrito com aspas simples
# no atributo (`onclick='_compGrupo=${...};ir("e_comp")'`) — ali `"..."` e string legitima, e sem
# remove-la o extrator "descobria" um global chamado `e_comp` que nunca existiu. Dentro de um
# atributo de aspas duplas nao pode haver `"`, entao remover as duas formas e sempre seguro.
_STR = re.compile(r"'[^']*'|\"[^\"]*\"|&quot;[^&]*&quot;|`[^`]*`")
_IDENT = re.compile(r"(?<![.\w$])([A-Za-z_$][\w$]*)")

# Nomes que o navegador ja fornece no escopo do handler, ou que sao palavra-chave / builtin.
# Um falso positivo aqui vira ruido; um falso NEGATIVO vira botao morto. Na duvida, nao listar.
_DADOS = {
    "this", "event", "arguments", "window", "document", "console", "location", "history",
    "navigator", "performance", "screen", "self", "globalThis",
    "const", "let", "var", "function", "return", "if", "else", "for", "while", "do", "switch",
    "case", "break", "continue", "new", "typeof", "instanceof", "delete", "void", "in", "of",
    "try", "catch", "finally", "throw", "class", "extends", "await", "async", "yield",
    "true", "false", "null", "undefined", "NaN", "Infinity",
    "Object", "Array", "String", "Number", "Boolean", "Math", "JSON", "Date", "RegExp", "Map",
    "Set", "Promise", "Error", "Symbol", "BigInt", "parseInt", "parseFloat", "isNaN", "encodeURI",
    "encodeURIComponent", "decodeURIComponent", "setTimeout", "setInterval", "clearTimeout",
    "clearInterval", "requestAnimationFrame", "alert", "confirm", "prompt", "fetch",
    "CustomEvent", "Event", "URL", "URLSearchParams", "FormData", "Intl",
}


# Escrita direta de global de dentro do HTML: `_respProc=this.value`, `aba='g_acoes'`, `_perGrau=''`.
# Nao confundir com comparacao (`==`, `===`, `!=`, `>=`, `<=`) nem com `=>`.
_ESCRITA = re.compile(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*(?:[-+*/|&^]|\*\*|<<|>>>?|\?\?|\|\||&&)?="
                      r"(?![=>])")


def _escritos_no_handler(corpo: str) -> set[str]:
    corpo = _STR.sub(" ", _sem_interpolacao(corpo))
    locais = set(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)", corpo))
    return {n for n in _ESCRITA.findall(corpo) if n not in _DADOS and n not in locais}


def _nomes_do_handler(corpo: str) -> set[str]:
    """Identificadores que o handler resolve no escopo GLOBAL — leitura, chamada ou escrita."""
    corpo = _sem_interpolacao(corpo)
    corpo = _STR.sub(" ", corpo)                       # literais de string nao contem identificador
    achados = set()
    locais = set(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)", corpo))
    # parametros de arrow function declarada dentro do proprio handler (o `autocompletar(...)` faz isso)
    for m in re.finditer(r"\(([^()]*)\)\s*=>", corpo):
        locais |= {p.strip().split("=")[0].strip() for p in m.group(1).split(",") if p.strip()}
    for m in re.finditer(r"(?<![\w$])([A-Za-z_$][\w$]*)\s*=>", corpo):
        locais.add(m.group(1))
    for m in _IDENT.finditer(corpo):
        nome = m.group(1)
        depois = corpo[m.end():m.end() + 2]
        if depois.startswith(":"):                     # chave de objeto literal / rotulo
            continue
        if nome in _DADOS or nome in locais:
            continue
        achados.add(nome)
    return achados


def coletar() -> dict:
    """Todo nome de escopo global exigido por handler inline, com onde ele aparece."""
    exigidos: dict[str, list[str]] = {}
    escritos: set[str] = set()
    total_handlers = 0
    for fonte in [_HTML, *_fontes_js()]:
        if not fonte.exists():
            continue
        texto = fonte.read_text(encoding="utf-8")
        rel = fonte.relative_to(_REPO).as_posix()
        achados = [(m, next(g for g in m.groups()[1:] if g is not None))
                   for m in _ATTR.finditer(texto)]
        achados += [(m, next(g for g in m.groups() if g is not None))
                    for m in _SETATTR.finditer(texto)]
        for m, corpo in achados:
            total_handlers += 1
            linha = texto.count("\n", 0, m.start()) + 1
            for nome in _nomes_do_handler(corpo):
                exigidos.setdefault(nome, [])
                if len(exigidos[nome]) < 3:
                    exigidos[nome].append(f"{rel}:{linha}")
            escritos |= _escritos_no_handler(corpo)
    return {"handlers": total_handlers, "exigidos": exigidos,
            "escritos": sorted(escritos & set(exigidos))}


# --- superficie disponivel -----------------------------------------------------------------------

# `export ` opcional: com a quebra em modulos, a MESMA declaracao de topo passa a ser escrita
# `export function ir(...)`. Sem aceitar o prefixo, o extrator para de ver metade da superficie e
# acusa como "sem ponte" nomes que estao la — o mesmo modo de falha do `_declaradores`, e a mesma
# licao: falso positivo e como uma ferramenta de seguranca vira ruido e depois vira desligada.
_FUNC = re.compile(r"^(?:export\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)", re.M)
_VAR = re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(.*)$", re.M)


def _declaradores(resto: str) -> set[str]:
    """Nomes declarados numa sentenca `let a=1, b=null, c='x'` — TODOS, nao so o primeiro.

    A versao ingenua (`^(let|var|const)\\s+(\\w+)`) via so `a`, e por isso acusava `_compGrupo`,
    `_compCat`, `_perGrau`, `_nuHover` e `aba` como "sem superficie" — todos declarados em
    sentenca multipla (`painel.js:1763`, `:2226`, `:3081`, `:983`). Falso positivo de extrator e
    exatamente o que esta calibragem existe para queimar antes de a ferramenta segurar algo.
    """
    nomes, prof, esperando = set(), 0, True
    for m in re.finditer(r"[()\[\]{}]|,|[A-Za-z_$][\w$]*|.", resto):
        t = m.group(0)
        if t in "([{":
            prof += 1
        elif t in ")]}":
            prof -= 1
        elif t == "," and prof == 0:
            esperando = True
        elif esperando and re.fullmatch(r"[A-Za-z_$][\w$]*", t):
            nomes.add(t)
            esperando = False
        elif prof == 0 and t not in " \t":
            esperando = False
    return nomes
# `src/ponte.js` declara a superficie; antes dele existir, a superficie E o topo do monolito.
_PONTE = _STATIC / "js" / "src" / "ponte.js"


_BUNDLE = _STATIC / "js" / "painel.bundle.js"
_ENTRADA = _STATIC / "js" / "src" / "entrada.js"


def _da_ponte(corpo: str) -> set[str]:
    """Nomes que o bloco da ponte instala no `window` — as tres formas que ela usa."""
    nomes: set[str] = set()
    for m in re.finditer(r"Object\.assign\(window,\s*\{(.*?)\}\s*\)", corpo, re.S):
        nomes |= set(re.findall(r"[A-Za-z_$][\w$]*", m.group(1)))
    # acessores get/set: `_respProc: [()=>_respProc, v=>{_respProc=v}]`. O `:\s*\[` e o que
    # distingue uma ENTRADA da caixa de qualquer outro dois-pontos dentro do bloco — e por que
    # nao se ancora em inicio de linha: a ponte escreve duas caixas por linha, e ancorar
    # perderia a segunda de cada par (oito nomes, silenciosamente).
    for m in re.finditer(r"const cx\s*=\s*\{(.*?)\n\}", corpo, re.S):
        nomes |= set(re.findall(r"([A-Za-z_$][\w$]*)\s*:\s*\[", m.group(1)))
    nomes |= set(re.findall(r"window\.([A-Za-z_$][\w$]*)\s*=", corpo))       # atribuicao direta
    return nomes


def superficie() -> tuple[set[str], str]:
    """Nomes disponiveis no escopo global — e a resposta MUDA com a arquitetura.

    Antes do build, todo `const`/`function` de topo era global de verdade: a superficie e o
    conjunto das declaracoes. Depois do build (`--format=iife`), NAO E MAIS — o codigo inteiro
    vive dentro de uma funcao e so chega ao `window` o que a ponte instala de proposito. Ler
    declaracoes nesse mundo daria um OK falso, que e pior do que nenhum check: foi assim que
    `ordenar` (ligado por `setAttribute`, extraido para `nucleo/lista.js` na etapa 3) passou pela
    checagem estatica enquanto ja estava fora da ponte.
    """
    if _PONTE.exists():
        corpo = _PONTE.read_text(encoding="utf-8")
        return _da_ponte(corpo), "static/js/src/ponte.js"
    if _BUNDLE.exists() and _ENTRADA.exists():
        return _da_ponte(_ENTRADA.read_text(encoding="utf-8")), "bloco da ponte em src/entrada.js"
    nomes: set[str] = set()
    for f in _fontes_js():
        corpo = f.read_text(encoding="utf-8")
        nomes |= set(_FUNC.findall(corpo))
        # so declaracao em coluna 0 — indentada e local. E o idioma do arquivo: todo global do
        # painel comeca na margem.
        for resto in _VAR.findall(corpo):
            nomes |= _declaradores(resto)
    return nomes, "declaracoes de topo do fonte (pre-migracao: tudo e global)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="laudo em JSON")
    ap.add_argument("--listar", action="store_true", help="so os nomes exigidos, um por linha")
    a = ap.parse_args(argv)

    dados = coletar()
    exigidos = dados["exigidos"]
    disponiveis, origem = superficie()
    faltando = {n: o for n, o in sorted(exigidos.items()) if n not in disponiveis}

    if a.listar:
        for n in sorted(exigidos):
            print(n)
        return 0
    if a.json:
        print(json.dumps({"handlers": dados["handlers"],
                          "exigidos": sorted(exigidos),
                          "escritos": dados["escritos"],
                          "origem_da_superficie": origem,
                          "faltando": faltando}, ensure_ascii=False, indent=1))
        return 1 if faltando else 0

    print(f"handlers inline analisados : {dados['handlers']}")
    print(f"nomes globais exigidos     : {len(exigidos)}")
    print(f"  destes, ESCRITOS inline  : {len(dados['escritos'])}  "
          f"(precisam de get+set na ponte, nao de Object.assign)")
    print(f"superficie disponivel      : {origem}")
    if not a.json:
        print("  " + ", ".join(dados["escritos"]))
    if faltando:
        print(f"\n=== {len(faltando)} NOME(S) SEM SUPERFICIE ===")
        print("Cada um destes e um handler que vai lancar ReferenceError no clique — calado ate la.")
        for n, onde in faltando.items():
            print(f" • {n:24s} usado em {', '.join(onde)}")
        return 1
    print("\nOK — todo nome exigido por handler inline tem superficie global.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
