# -*- coding: utf-8 -*-
"""Gate de NEUTRALIDADE dos entregáveis — regra dura do dono: nenhum documento enviado pode
carregar sigla ou menção interna (o produto é uma peça de controle externo, não da ferramenta).

Centraliza o que estava embutido em tools/dossie_master.py. Termos proibidos por PALAVRA isolada
(\b) para não casar substrings legítimas ("Alexandre" contém "lex", "Complexo" contém "lex").

Uso:
  termos = termos_proibidos(texto)          # lista dos que apareceram (vazia = limpo)
  garantir_neutro(texto)                    # levanta AssertionError se sujo (para PDFs prontos)
  ctx = neutralizar_ctx(ctx)                # remove chaves internas de um ctx de render (defensivo)
"""
from __future__ import annotations

import re

# nomes internos que JAMAIS podem chegar ao dono num entregável
_PROIBIDOS = ("jfn", "yoda", "itkava", "iterj", "hermes", "massare", "jfelippe")
_RE_PROIBIDOS = re.compile(r"\b(" + "|".join(_PROIBIDOS) + r")\b", re.I)
_RE_LEX = re.compile(r"\bLex\b")  # "Lex" isolado (o agente) — mas não "Alexandre/Complexo/flex"


def termos_proibidos(texto: str) -> list[str]:
    """Lista (sem repetição, ordem estável) dos termos internos presentes no texto. Vazia = limpo."""
    t = texto or ""
    achados = {m.group(0).lower() for m in _RE_PROIBIDOS.finditer(t)}
    ordenados = [p for p in _PROIBIDOS if p in achados]
    if _RE_LEX.search(t):
        ordenados.append("Lex")
    return ordenados


def garantir_neutro(texto: str, contexto: str = "entregável") -> None:
    """Levanta AssertionError se o texto contiver termo interno. Use no PDF/HTML final."""
    bad = termos_proibidos(texto)
    if bad:
        raise AssertionError(f"{contexto} contém termo interno proibido: {bad}")


def neutralizar_ctx(ctx: dict) -> dict:
    """Defesa em profundidade: zera o rótulo do analista se vier com nome interno (o footer da casa
    já é 'Controle Externo'), sem alterar dados de terceiros. Não muta o original."""
    out = dict(ctx)
    analista = out.get("analista") or ""
    if termos_proibidos(analista):
        out["analista"] = "Controle Externo (automatizado)"
    return out
