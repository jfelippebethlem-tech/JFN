# -*- coding: utf-8 -*-
"""Separa, na íntegra baixada, o que é DESTE processo do que veio de outro.

O QUE ACONTECEU. A pasta `data/sei_arquivo/080001_000744_2024/` (R$ 51,6 milhões, repasse do
Fundo Estadual de Saúde para nove Fundos Municipais) tinha 35 documentos. A leitura da árvore
— o cache CDP — tinha 10, todos corretos. Os outros 25 vieram do arquivamento da ÍNTEGRA, e
eram de quinze processos diferentes: um despacho da Secretaria de Educação sobre controle de
frequência de colégio, correspondências de recursos humanos, assinaturas de merendeira, de
Subtenente PM e da Vice-Diretora do ILE/UERJ.

O dossiê gerado atribuía tudo isso ao processo de saúde — inclusive os RESPONSÁVEIS, que é o
que `agente_processo` usa para responder "quem responde por este processo".

E o dado para separar já estava lá, sem uso: o manifest da íntegra guarda, em `contexto`, o
número do processo de cada documento ("Recursos Humanos: Controle de Frequência Nº
SEI-030001/006436/2026").

A REGRA QUE NÃO PODE SER INVERTIDA. Documento sem número no contexto **fica**. Ausência de dado
não é prova de que o documento é alheio, e descartá-lo trocaria contaminação por perda
silenciosa — que é pior, porque some sem deixar rastro.
"""
from __future__ import annotations

import re

# O SEI escreve o número com barra ou com ponto conforme a tela que gerou o texto.
_RE_NUMERO = re.compile(r"SEI[-\s]?(\d{6})[/.](\d{6})[/.](\d{4})", re.IGNORECASE)


def numero_do_contexto(contexto: str | None) -> str | None:
    """`"... Nº SEI-030001/006436/2026"` → `"030001/006436/2026"`. `None` se não houver."""
    m = _RE_NUMERO.search(str(contexto or ""))
    return f"{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else None


def separar_alheios(documentos, numero_do_processo: str) -> dict:
    """`{"proprios": [...], "alheios": [...], "sem_numero": n, "por_processo_alheio": {...}}`.

    `por_processo_alheio` existe para o conserto ser possível: saber que sobrou documento de
    fora não basta — é preciso saber de QUAL processo, para devolvê-lo ao lugar certo em vez de
    simplesmente apagar.
    """
    alvo = str(numero_do_processo or "").replace("_", "/").replace("SEI-", "")
    proprios, alheios, sem_numero = [], [], 0
    por_processo: dict[str, int] = {}
    for doc in documentos or []:
        numero = numero_do_contexto((doc or {}).get("contexto"))
        if numero is None:
            sem_numero += 1
            proprios.append(doc)          # sem dado, o documento FICA
        elif numero == alvo:
            proprios.append(doc)
        else:
            alheios.append(doc)
            por_processo[numero] = por_processo.get(numero, 0) + 1
    return {"proprios": proprios, "alheios": alheios, "sem_numero": sem_numero,
            "por_processo_alheio": por_processo}
