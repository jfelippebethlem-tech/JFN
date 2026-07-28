# -*- coding: utf-8 -*-
"""json_resposta — o parse ÚNICO da resposta em JSON do LLM.

POR QUE EXISTE. A casa tinha três implementações divergentes deste mesmo parse
(`direcionamento_cerebro`, `detectores/base`, `llm/groq_agent`) e todas desistiam nas mesmas
formas de resposta que o modelo produz todo dia: cerca ```json no meio da prosa, uma chave
solta no texto antes do objeto, um `}` dentro de uma string, vírgula sobrando, e — o caso mais
caro — a resposta CORTADA pelo limite de tokens.

O QUE ESTÁ EM JOGO. Resposta descartada é evidência coletada e jogada fora: o OSINT já foi
buscado, a cota do modelo já foi gasta, e o resultado vira "não consolidada". Eram 16% das
pesquisas (sessão 2026-07-28).

A REGRA DE HONESTIDADE. Reparar um objeto truncado recupera o que o modelo chegou a escrever —
nunca o que ele não escreveu. Por isso o objeto reparado sai marcado com `_truncado: True`:
apresentar leitura parcial como completa é exatamente o erro que esta casa já cometeu com os
lotes de leitura do SEI. E reparo que não recupera CONTEÚDO nenhum (um `{` solto vira `{}`) não
é resultado — é `None`.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_CERCA = re.compile(r"```[a-zA-Z]*\s*\n?(.*?)```", re.DOTALL)
_VIRGULA_SOBRANDO = re.compile(r",(\s*[}\]])")
_ABERTURAS = {"{": "}", "[": "]"}


def _carregar(txt: str):
    """`json.loads` tolerando a vírgula sobrando antes do fechamento."""
    for tentativa in (txt, _VIRGULA_SOBRANDO.sub(r"\1", txt)):
        try:
            return json.loads(tentativa)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _fragmento(texto: str, inicio: int) -> tuple[str, bool]:
    """Do `inicio` até o fechamento equilibrado. `(fragmento, truncado)`.

    Respeita string e escape — um `}` dentro de `"custo } por item"` não fecha nada. Quando o
    texto acaba com estruturas abertas, devolve o fragmento cru e `truncado=True`.
    """
    pilha: list[str] = []
    em_string = False
    escapado = False
    for i in range(inicio, len(texto)):
        c = texto[i]
        if escapado:
            escapado = False
            continue
        if c == "\\":
            escapado = True
            continue
        if c == '"':
            em_string = not em_string
            continue
        if em_string:
            continue
        if c in _ABERTURAS:
            pilha.append(_ABERTURAS[c])
        elif c in ("}", "]"):
            if not pilha or pilha.pop() != c:
                break
            if not pilha:
                return texto[inicio:i + 1], False
    return texto[inicio:], True


def _reparar(fragmento: str):
    """Fecha o que ficou aberto num fragmento cortado no meio. `None` se nada se recupera."""
    pilha: list[str] = []
    em_string = False
    escapado = False
    for c in fragmento:
        if escapado:
            escapado = False
            continue
        if c == "\\":
            escapado = True
            continue
        if c == '"':
            em_string = not em_string
            continue
        if em_string:
            continue
        if c in _ABERTURAS:
            pilha.append(_ABERTURAS[c])
        elif c in ("}", "]") and pilha:
            pilha.pop()
    cauda = ('"' if em_string else "") + "".join(reversed(pilha))
    corpo = fragmento
    # A cauda basta quando o corte caiu depois de um valor completo. Quando caiu no meio de uma
    # chave sem valor (`{"a":1,"b":`), recua até a última vírgula de topo e tenta de novo.
    for _ in range(24):
        dados = _carregar(corpo + cauda)
        if dados:  # objeto/lista VAZIO não é recuperação — é um `{` solto
            return dados
        corte = corpo.rfind(",")
        if corte <= 0:
            return None
        corpo = corpo[:corte]
        # o recuo pode ter descartado aberturas: recalcula a cauda para o corpo encurtado
        cauda = _reparar_cauda(corpo)
    return None


def _reparar_cauda(fragmento: str) -> str:
    pilha: list[str] = []
    em_string = False
    escapado = False
    for c in fragmento:
        if escapado:
            escapado = False
            continue
        if c == "\\":
            escapado = True
            continue
        if c == '"':
            em_string = not em_string
            continue
        if em_string:
            continue
        if c in _ABERTURAS:
            pilha.append(_ABERTURAS[c])
        elif c in ("}", "]") and pilha:
            pilha.pop()
    return ('"' if em_string else "") + "".join(reversed(pilha))


def parse_json_llm(raw: str | None):
    """O JSON da resposta do LLM, ou `None` quando não há JSON algum.

    Objeto recuperado de resposta cortada vem com `_truncado: True`.
    """
    if not raw or not raw.strip():
        return None
    candidatos = [m.group(1) for m in _CERCA.finditer(raw)]
    candidatos.append(re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw.strip()))
    for texto in candidatos:
        texto = texto.strip()
        dados = _carregar(texto)
        if dados is not None:
            return dados
        for i, c in enumerate(texto):
            if c not in _ABERTURAS:
                continue
            fragmento, truncado = _fragmento(texto, i)
            if not truncado:
                dados = _carregar(fragmento)
                if dados is not None:
                    return dados
                continue
            dados = _reparar(fragmento)
            if dados is None:
                continue
            logger.debug("resposta do LLM cortada no meio — %d caractere(s) recuperados", len(fragmento))
            if isinstance(dados, dict):
                dados["_truncado"] = True
            return dados
    return None
