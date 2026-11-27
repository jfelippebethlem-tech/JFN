# -*- coding: utf-8 -*-
"""Máscara REVERSÍVEL de CPF e conta bancária — fonte única (plano mestre v2 §3.11: "CPF e conta bancária são
mascarados antes de qualquer envio").

Veio de `leitura_integral.py` (24/11/2026: era a única máscara reversível da casa; lá continua reexportada, com o
comportamento idêntico). Diferente de `cpf_cnpj.mascarar_cpf` (PAD-04, `***.456.789-**`, IRREVERSÍVEL, para
exibição): aqui o CPF vira `[CPF_n]`, o mapa fica LOCAL e `desmascarar` reconstrói o texto na volta.

  mascarar(texto)                CPF no formato de 11 dígitos (com ou sem pontuação, SEM conferir DV — vazar é pior
                                 que sobrar) e conta/agência após a palavra-chave viram marcadores;
  mascarar(texto, mapa, estrito=True)
                                 o mesmo + CPF com ESPAÇO como separador (`123 456 789 09`), só se o DV confere
                                 (sem DV, espaço entre grupos de dígitos é comum demais para mascarar às cegas);
  cpfs_expostos(texto)           quantos CPFs com DV válido sobraram (padrão de `tools/scan_pii.py`, aceitando
                                 também espaço) — o gateway recusa o envio se > 0 (falha-fechado);
  desmascarar(texto, mapa)       volta.

Mapa compartilhado: passar o MESMO `mapa` a várias chamadas numera os marcadores em sequência e repete o marcador
do mesmo valor (o mapa é mutado). Mesmo texto na mesma ordem ⇒ mesmos marcadores (determinístico).
"""
from __future__ import annotations

import re

from compliance_agent.dominio.digitos import cpf_valido

_RE_CPF = re.compile(r"(?<![\d./])\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?![\d/])")
_RE_CONTA = re.compile(r"(?i)\b(c/c|conta(?:\s+corrente)?|ag[êe]ncia|ag\.)(\s*(?:n[º°o.]*)?\s*:?\s*)(\d[\d.\-xX]{2,})")
# separadores com espaço (OCR, digitação): só mascarado com DV válido
_RE_CPF_ESPACO = re.compile(r"(?<![\d./])\d{3}[.\s]\d{3}[.\s]\d{3}[-\s]\d{2}(?![\d/])")
# o de tools/scan_pii.py (11 crus ou ###.###.###-##) aceitando também espaço como separador
_RE_CPF_EXPOSTO = re.compile(r"(?<![\d.\-/])(\d{3}[.\s]?\d{3}[.\s]?\d{3}[-\s]?\d{2})(?![\d\-/])")


def mascarar(texto: str, mapa: dict | None = None, *, estrito: bool = False) -> tuple[str, dict]:
    mapa = {} if mapa is None else mapa
    rev: dict[str, str] = {v: k for k, v in mapa.items()}

    def marca(tipo: str, original: str) -> str:
        if original not in rev:
            rev[original] = f"[{tipo}_{sum(1 for k in mapa if k.startswith('[' + tipo)) + 1}]"
            mapa[rev[original]] = original
        return rev[original]

    t = _RE_CPF.sub(lambda m: marca("CPF", m[0]), texto)
    if estrito:
        t = _RE_CPF_ESPACO.sub(lambda m: marca("CPF", m[0]) if cpf_valido(m[0]) else m[0], t)
        # 27/11/2026: separador MISTURADO (espaço numa posição, nada na outra) — o detector acusa e a máscara não
        # cobria; o gateway barrava (certo) e o processo nunca era lido. Estrito = nada sobra que o detector conte.
        t = _RE_CPF_EXPOSTO.sub(lambda m: marca("CPF", m[0]) if cpf_valido(m[1]) else m[0], t)
    t = _RE_CONTA.sub(lambda m: m[1] + m[2] + marca("CONTA", m[3]), t)
    return t, mapa


def desmascarar(texto: str, mapa: dict) -> str:
    for k, v in mapa.items():
        texto = texto.replace(k, v)
    return texto


def cpfs_expostos(texto: str) -> int:
    return sum(1 for m in _RE_CPF_EXPOSTO.finditer(texto or "") if cpf_valido(m[1]))
