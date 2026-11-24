# -*- coding: utf-8 -*-
"""Identidade ESTÁVEL do documento dentro do processo (plano mestre v2, §3.1: chave Documento).

Regra (a de `compliance_agent.evidencias.importar_pasta`, centralizada aqui; paridade em
`tests/test_dominio_documento_id.py`):
- `sei:<nº>` quando o título termina no número SEI do documento (`… (86490508)` ou `… 86490508`, 7 a 10 dígitos);
  99,2% dos 518.756 documentos o têm (medido em 23/11/2026);
- `pos:<i>` sem número, com `i` = posição na árvore como o manifest a grava;
- número (ou posição) repetido no mesmo processo vira `sei:N#2`, `sei:N#3`… na ordem da árvore — nunca some.
A versão do conteúdo (sha256) é outra coluna (`evidencias.versoes`), não entra no id.

Divergência conhecida (documentada no teste): `manifesto_norm.numero_sei_do_titulo` e
`reuso_documento_execucao.numero_sei_do_titulo` também aceitam o número no MEIO do título (o primeiro, o último
número solto de 7–10 dígitos em qualquer lugar). Para IDENTIDADE vale só o número no fim — o do meio pode ser
o de outro documento citado ("Despacho sobre a NF 12345678 de …").
"""
from __future__ import annotations

import re
from typing import Iterable

_RX_ID = re.compile(r"(?:^|[\s(])(\d{7,10})\)?\s*$")


def numero_sei(titulo) -> str | None:
    """Número SEI do documento no fim do título; `None` se não houver."""
    m = _RX_ID.search(str(titulo or "").strip())
    return m.group(1) if m else None


def id_base(titulo, posicao) -> str:
    """`sei:<nº>` ou `pos:<posição>` (sem o sufixo de repetição)."""
    n = numero_sei(titulo)
    return f"sei:{n}" if n else f"pos:{posicao}"


def ids_documentos(docs: Iterable[dict]) -> list[str]:
    """Ids dos documentos de UM processo, na ordem dada; entradas que não são dict são puladas (como no
    `evidencias`). Repetição → `#2`, `#3`…"""
    vistos: dict[str, int] = {}
    out: list[str] = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        base = id_base(d.get("titulo", ""), d.get("i"))
        vistos[base] = vistos.get(base, 0) + 1
        out.append(base if vistos[base] == 1 else f"{base}#{vistos[base]}")
    return out


def sem_repeticao(doc_id: str) -> str:
    """`sei:N#2` → `sei:N` (o que entra no hash da árvore)."""
    return str(doc_id).split("#")[0]
