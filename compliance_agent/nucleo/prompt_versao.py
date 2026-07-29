# -*- coding: utf-8 -*-
"""Versão e impressão digital dos prompts que produzem juízo.

O PROBLEMA QUE ISTO RESOLVE. A qualidade do motor não-determinístico é medida
(`tools/eval_hermeneutica`) e agora travada por catraca — mas a medição só serve para
investigar regressão se for possível ligar o número À MUDANÇA QUE O CAUSOU. Hoje um prompt pode
ser reescrito em silêncio: o texto muda, o `PROMPT_VERSAO = "v1"` fica onde estava, e a
medição seguinte compara duas coisas diferentes acreditando comparar a mesma.

O MECANISMO. Cada prompt sob juízo entra no `REGISTRO` com a versão declarada e o SHA-256 do
texto (ou do código que o monta). O teste-catraca recalcula o hash e compara: alterar o prompt
sem subir a versão falha o teste. Não impede a mudança — impede a mudança CALADA, que é o que
inviabiliza a investigação depois.

POR QUE O HASH DO CÓDIGO, E NÃO SÓ DO TEXTO. Nem todo prompt é uma constante: `narrativa_certame`
monta o dele numa função, com rubrica e schema embutidos. Hashear apenas as constantes deixaria
justamente os prompts mais elaborados fora da trava. Quando o alvo é chamável, a assinatura é do
código-fonte da função — que muda exatamente quando o prompt muda.

O QUE ISTO NÃO É. Não é controle de qualidade: um prompt pior com versão nova passa. A trava é
de RASTREABILIDADE. Quem julga a qualidade é a catraca de F1.
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
from typing import Any

# Prompts que produzem JUÍZO (não formatação, não extração mecânica). Cada entrada declara onde
# o prompt vive; o hash é recalculado da fonte e conferido pelo teste.
REGISTRO: dict[str, dict[str, str]] = {
    "hermeneutica": {
        "alvo": "tools.eval_hermeneutica:_SISTEMA",
        "versao": "v1",
        "papel": "qualifica a conduta em vício/lícito/omissão — é o prompt que a catraca de F1 mede",
    },
    "narrativa_certame": {
        "alvo": "compliance_agent.editais.narrativa_certame:montar_prompt",
        "versao": "v1",
        "papel": "julga 'quão anômalo no contexto' sobre o índice determinístico",
    },
    "direcionamento": {
        "alvo": "compliance_agent.direcionamento_cerebro:_SYS",
        "versao": "v1",
        "papel": "veredito de direcionamento a partir de edital e ata",
    },
    "subsuncao": {
        "alvo": "compliance_agent.knowledge.subsuncao:SCHEMA_PROMPT",
        "versao": "v1",
        "papel": "estrutura a subsunção (norma, premissas, contra-argumento)",
    },
}


def _fonte(alvo: str) -> str:
    """Texto que representa o prompt: a string, se for constante; o código, se for função."""
    modulo, _, atributo = alvo.partition(":")
    obj = getattr(importlib.import_module(modulo), atributo)
    if isinstance(obj, str):
        return obj
    if callable(obj):
        return inspect.getsource(obj)
    raise TypeError(f"{alvo}: prompt precisa ser str ou chamável, veio {type(obj).__name__}")


def impressao(alvo: str) -> str:
    """SHA-256 (12 hex) da fonte do prompt. Curto de propósito: vai em cada veredito gravado."""
    return hashlib.sha256(_fonte(alvo).encode("utf-8")).hexdigest()[:12]


def assinar(prompt_id: str) -> dict[str, str]:
    """`{prompt_id, prompt_versao, prompt_hash}` — o carimbo que acompanha o veredito.

    Levanta `KeyError` para id desconhecido: prompt de juízo fora do registro é exatamente o
    que esta trava existe para impedir, e devolver um carimbo genérico esconderia isso.
    """
    reg = REGISTRO[prompt_id]
    return {"prompt_id": prompt_id, "prompt_versao": reg["versao"],
            "prompt_hash": impressao(reg["alvo"])}


def carimbar(veredito: dict[str, Any], prompt_id: str) -> dict[str, Any]:
    """Injeta o carimbo no veredito, sem sobrescrever campo já presente."""
    for k, v in assinar(prompt_id).items():
        veredito.setdefault(k, v)
    return veredito


def divergencias(esperado: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Prompts cujo hash atual difere do gravado — insumo da catraca.

    `esperado` mapeia `prompt_id → hash`; sem ele, lê `HASHES`. Alvo que não resolve entra como
    divergência com o motivo, e não como silêncio: prompt renomeado some da trava sem isto.
    """
    ref = HASHES if esperado is None else esperado
    fora = []
    for pid, reg in REGISTRO.items():
        try:
            atual = impressao(reg["alvo"])
        except Exception as exc:  # noqa: BLE001 — alvo movido/renomeado é o caso a denunciar
            fora.append({"prompt_id": pid, "alvo": reg["alvo"], "erro": str(exc)[:120]})
            continue
        if ref.get(pid) != atual:
            fora.append({"prompt_id": pid, "alvo": reg["alvo"], "versao": reg["versao"],
                         "hash_gravado": ref.get(pid, "(ausente)"), "hash_atual": atual})
    return fora


# Hashes aceitos. Mudou o prompt? Suba a `versao` no REGISTRO e o hash aqui, no MESMO commit —
# é o par (versão, hash) que liga uma regressão de F1 à alteração que a produziu.
HASHES: dict[str, str] = {
    "hermeneutica": "300d9347d2af",
    "narrativa_certame": "53ae81196543",
    "direcionamento": "08535f3aff46",
    "subsuncao": "f8dd40a5b1c7",
}
