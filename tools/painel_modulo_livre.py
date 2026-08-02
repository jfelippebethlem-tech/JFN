#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""painel_modulo_livre — nenhum modulo do painel usa um simbolo da casa sem importar.

POR QUE EXISTE. E o bug numero 2 da tabela do `PAINEL-v58-ESTADO-E-CONTINUACAO` §3:

    "`X is not defined` no primeiro quadro | um modulo le um simbolo que ficou no entrypoint"

Ele nao aparece em revisao de codigo e nao aparece na BUILD. `esbuild` so falha em `import` que
nao resolve; identificador LIVRE ele assume que e global do navegador e empacota calado. O erro
so nasce no primeiro quadro, numa aba de cada vez — e ate a v59 a unica rede que o pegava era o
`painel_boot_check`, que precisa de servidor, navegador e uns vinte minutos numa VM de 2 vCPU.

Aconteceu de novo no corte da v59 (§6.2-B): `cena/fundo.js` saiu com `$` livre e o painel inteiro
morreu com `$ is not defined`. O boot_check pegou. Esta ferramenta pega em 40 ms, sem navegador.

E entao ela achou o que o boot_check NAO pegava. `ui/index.js` chamava `sec` e `leitura` sem
importar desde o corte do v58 — e a chamada de `sec("Contato & rede (Receita)")` em `abrirDossie`
e INCONDICIONAL. Medido no bundle publicado em `30a04e94`: SETE chamadas a `sec(` e ZERO
definicoes (o esbuild renomeou a de `nucleo/dom.js` para `sec2`, porque so renomeia quando ha
colisao, e o nome livre nao tinha a quem se ligar). Confirmado no navegador servindo aquele
bundle: `ReferenceError: sec is not defined at abrirDossie`.

O DOSSIE — a interacao mais usada do painel — estava quebrado em producao, e nenhuma rede pegava:
o `boot_check` percorre as 60 abas e nao CLICA num CNPJ. E a licao que este arquivo carrega: um
gate que so anda pelos caminhos principais mede os caminhos principais, e o resto apodrece calado.

O QUE ELA NAO E. Nao e um analisador de escopo de JavaScript, e nao tenta ser. Ela olha uma lista
FECHADA de simbolos — os que os modulos da casa exportam entre si — e pergunta, para cada modulo,
se ele usa algum deles sem ter declarado nem importado. Fora dessa lista ela nao opina: `window`,
`document`, `Math` e os globais de script classico (`CAPS_MESTRAS`, `RJ_MALHA`) sao livres de
proposito e nao entram.

Fechada e a palavra importante: uma lista aberta exigiria resolver escopo de verdade (parametros,
desestruturacao, closures) e daria falso positivo em cada variavel local homonima. A lista fechada
troca cobertura por CONFIANCA — o que ela acusa e sempre real, e um detector que nunca mente e o
unico que continua sendo lido depois do terceiro alarme falso.

⚠️ DECLARADOR MULTIPLO. `export let _ckMX = .5, _ckMY = .5;` declara DOIS nomes e regex de
`^export let (\\w+)` casa so o primeiro. Este arquivo ja nasceu com essa armadilha desarmada
(`_DECL_MULTI`), porque ela ja cegou duas ferramentas desta casa numa sessao so — o extrator da
ponte e o gerador de setters — e cegou a primeira versao DESTE script, que acusou `_ckMY` em
`cena/ponteiro.js`, o arquivo de duas linhas que o declara.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.painel_modulo_livre
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "static" / "js" / "src"


def _sem_ruido(js: str) -> str:
    r"""Deixa so codigo: sem comentario, sem string, sem template e sem literal de expressao regular.

    E UMA VARREDURA DA ESQUERDA PARA A DIREITA, e nao uma pilha de `re.sub`, porque a pilha erra
    nos dois sentidos e o erro e silencioso:
      · tirando literal ANTES de comentario, uma crase dentro de comentario (`--bpm`, e este
        arquivo esta cheio delas) casa com outra crase la adiante e o varredor come pedaco de
        codigo de verdade;
      · tirando comentario ANTES de literal, um `//` dentro de uma URL em string come o resto da
        linha.
    A primeira versao deste script fazia a primeira coisa, e as SEIS acusacoes que ela produziu
    eram todas falsas — `rot`, `sweep`, `abrirDossie`, `filtrar`, `$` — vindas de comentario
    picado, de template e de literal de regex. Um detector que erra seis em seis para de ser lido.

    O literal de regex e o caso que so a varredura resolve: `/filtrar\(this/` e uma barra que
    inicia expressao, e `a / b` e divisao. A distincao esta no token ANTERIOR — depois de
    identificador, numero ou fecha-parenteses, `/` e divisao; em qualquer outro lugar, e regex.
    """
    fora = []
    i, n = 0, len(js)
    ant = ""                       # ultimo caractere significativo ja emitido
    while i < n:
        c = js[i]
        d = js[i:i + 2]
        if d == "//":
            i = js.find("\n", i)
            if i < 0:
                break
            continue
        if d == "/*":
            f = js.find("*/", i + 2)
            i = n if f < 0 else f + 2
            continue
        if c == "`":
            # TEMPLATE: o texto literal sai, mas o que esta dentro de `${...}` FICA. Este painel
            # monta HTML com template e chama funcao de dentro da interpolacao o tempo todo
            # (`${sec(titulo)}`, `${fmtR(v)}`); apagar o template inteiro cegaria o detector
            # justamente onde mais ha chamada. As chaves aninhadas sao contadas para achar o `}`
            # certo — objeto literal dentro de interpolacao e comum aqui.
            i += 1
            while i < n:
                if js[i] == "\\":
                    i += 2
                    continue
                if js[i] == "`":
                    i += 1
                    break
                if js[i:i + 2] == "${":
                    prof, j = 1, i + 2
                    while j < n and prof:
                        if js[j] == "{":
                            prof += 1
                        elif js[j] == "}":
                            prof -= 1
                        j += 1
                    fora.append(" " + _sem_ruido(js[i + 2:j - 1]) + " ")
                    i = j
                    continue
                i += 1
            fora.append(' "" ')
            ant = '"'
            continue
        if c in "\"'":
            asp = c
            i += 1
            while i < n:
                if js[i] == "\\":
                    i += 2
                    continue
                if js[i] == asp:
                    i += 1
                    break
                i += 1
            fora.append('""')
            ant = '"'
            continue
        if c == "/" and ant not in ")]}" and not (ant and (ant.isalnum() or ant in "_$")):
            # literal de regex: consome ate a barra de fechamento, respeitando classe [...]
            i += 1
            classe = False
            while i < n:
                if js[i] == "\\":
                    i += 2
                    continue
                if js[i] == "[":
                    classe = True
                elif js[i] == "]":
                    classe = False
                elif js[i] == "/" and not classe:
                    i += 1
                    break
                elif js[i] == "\n":
                    break            # regex nao atravessa linha: era divisao mesmo, desiste
                i += 1
            fora.append(" 0 ")
            ant = "0"
            continue
        fora.append(c)
        if not c.isspace():
            ant = c
        i += 1
    return "".join(fora)


# Parametros de funcao e de arrow. Sem eles, `const barra = (rot, v, teto, unid) => ...` acusa
# `rot`, que e o formatador de `nucleo/formato.js` — nome local homonimo, o falso positivo mais
# obvio que existe. Captura a lista entre parenteses; `_nomes_da_lista` separa e ignora o que nao
# for nome simples (desestruturacao, valor padrao com chamada).
_PARAMS = (
    re.compile(r"\(([^()]*)\)\s*=>"),                    # arrow com parenteses
    re.compile(r"function\s*\w*\s*\(([^()]*)\)"),        # declaracao e expressao de funcao
    re.compile(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*=>"),     # arrow de um parametro, sem parenteses
    re.compile(r"catch\s*\(([^()]*)\)"),                  # `catch(e)` liga `e`
    re.compile(r"for\s*\(\s*(?:const|let|var)\s+([^;)]*?)\s+of\s"),   # `for (const x of ...)`
)


# `export let a=1, b=2, c` — captura a LISTA inteira; quem separa os nomes e `_nomes_declarados`.
_DECL_MULTI = re.compile(r"^(?:export\s+)?(?:const|let|var)\s+([^;\n]+)", re.M)
_DECL_FUNC = re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)", re.M)
_IMPORTA = re.compile(r"^import\s*\{([^}]*)\}", re.M | re.S)
_EXPORTA_FUNC = re.compile(r"^export\s+(?:async\s+)?function\s+(\w+)", re.M)
_EXPORTA_DECL = re.compile(r"^export\s+(?:const|let|var)\s+([^;\n]+)", re.M)
_REEXPORTA = re.compile(r"^export\s*\{([^}]*)\}\s*from", re.M | re.S)


def _nomes_da_lista(lista: str) -> set[str]:
    """`a=1, b=2, c` -> {a,b,c}. Corta no `=` e ignora desestruturacao, que nao e nome simples."""
    fora = set()
    profundidade = 0
    atual = ""
    for ch in lista + ",":
        if ch in "([{":
            profundidade += 1
        elif ch in ")]}":
            profundidade -= 1
        if ch == "," and profundidade == 0:
            nome = atual.split("=")[0].strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*", nome):
                fora.add(nome)
            atual = ""
        else:
            atual += ch
    return fora


def _declarados(js: str) -> set[str]:
    nomes = set(_DECL_FUNC.findall(js))
    for rx in _PARAMS:
        for lista in rx.findall(js):
            nomes |= _nomes_da_lista(lista)
    for lista in _DECL_MULTI.findall(js):
        nomes |= _nomes_da_lista(lista)
    for lista in _IMPORTA.findall(js):
        for parte in lista.split(","):
            parte = parte.strip()
            if not parte:
                continue
            # `x as y` liga o nome LOCAL, que e o da direita
            nomes.add(parte.split(" as ")[-1].strip())
    return nomes


def vocabulario() -> dict[str, str]:
    """Todo simbolo exportado por algum modulo -> o arquivo que o exporta.

    E a lista fechada. Reexport (`export {x} from`) fica de FORA: ele nao declara nada, e incluir
    o nome faria o proprio arquivo que reexporta parecer dono de um simbolo que ele nao tem em
    escopo local — que e justamente a confusao que este script existe para desfazer.
    """
    voc: dict[str, str] = {}
    for p in sorted(_SRC.rglob("*.js")):
        js = p.read_text(encoding="utf-8")
        js = _REEXPORTA.sub("", js)
        nomes = set(_EXPORTA_FUNC.findall(js))
        for lista in _EXPORTA_DECL.findall(js):
            nomes |= _nomes_da_lista(lista)
        for n in nomes:
            voc.setdefault(n, p.relative_to(_REPO).as_posix())
    return voc


def livres() -> dict[str, list[dict]]:
    """Modulo -> simbolos da casa usados sem importar. Vazio e o estado correto."""
    voc = vocabulario()
    entrada = _SRC / "entrada.js"
    fora: dict[str, list[dict]] = {}
    for p in sorted(_SRC.rglob("*.js")):
        if p == entrada:          # o entrypoint importa tudo; e ele o dono do escopo global
            continue
        js = p.read_text(encoding="utf-8")
        tenho = _declarados(js)
        corpo = _sem_ruido(js)
        # o proprio bloco de reexport nao conta como uso: ele nomeia, nao le
        corpo = _REEXPORTA.sub("", corpo)
        achados = []
        for nome, dono in voc.items():
            if nome in tenho or dono == p.relative_to(_REPO).as_posix():
                continue
            # `(?!\s*:)` tira CHAVE DE OBJETO. `{marcha: _marcha, sweep: _sweepVivo}` nomeia dois
            # campos e nao le simbolo nenhum; sem esta guarda o `sweep` de `ritmo.js` era acusado
            # de usar o `sweep` de `abas/`. Custo: um `x ? sec : y` deixa de ser visto — perda de
            # cobertura, nunca invencao de achado, que e o unico erro tolerado aqui.
            if re.search(r"(?<![.\w$])" + re.escape(nome) + r"(?![\w$])(?!\s*:)", corpo):
                achados.append({"nome": nome, "mora_em": dono})
        if achados:
            fora[p.relative_to(_REPO).as_posix()] = sorted(achados, key=lambda d: d["nome"])
    return fora


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    maus = livres()
    if a.json:
        print(json.dumps(maus, ensure_ascii=False, indent=1))
        return 1 if maus else 0
    if not maus:
        voc = vocabulario()
        print(f"OK — {len(voc)} simbolos da casa, nenhum usado livre em modulo.")
        return 0
    print(f"=== {len(maus)} MODULO(S) COM SIMBOLO LIVRE ===")
    print("`esbuild` empacota isto sem reclamar; o erro nasce no PRIMEIRO QUADRO, como")
    print("`X is not defined`, numa aba de cada vez. Acrescente o import.\n")
    for arq, lst in maus.items():
        for d in lst:
            print(f"  {arq}: usa `{d['nome']}` sem importar — mora em {d['mora_em']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
