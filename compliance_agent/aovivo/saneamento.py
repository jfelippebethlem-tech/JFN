# -*- coding: utf-8 -*-
"""Saneamento OBRIGATÓRIO de todo texto que sai pelo AO VIVO.

O AO VIVO nunca transmite linha bruta de log; mesmo o texto montado de lista branca passa por aqui:
some com token/chave, e-mail, CPF e URL com query, e corta em 140 caracteres.
"""
from __future__ import annotations

import re

_SUBS = [
    (re.compile(r"https?://\S+\?\S*", re.I), "[url]"),                                   # URL com query
    (re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), "[e-mail]"),                       # e-mail
    (re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"), "[cpf]"),                             # CPF pontuado
    (re.compile(r"(?<![\d/.-])\d{11}(?![\d/.-])"), "[cpf]"),                             # CPF corrido (11 dígitos isolados)
    (re.compile(r"\beyJ[\w-]+\.[\w-]+(?:\.[\w-]+)?"), "[segredo]"),                                # JWT
    # a ordem importa: "Authorization: Bearer <tok>" — sem a regra do esquema ANTES, a de chave=valor
    # consumia só a palavra "Bearer" e o token saía inteiro (pego pelo teste)
    (re.compile(r"\b(?:authorization|proxy-authorization)\b\s*[:=]\s*(?:\w+\s+)?\S+", re.I), "[segredo]"),
    (re.compile(r"\b(?:bearer|basic)\s+\S+", re.I), "[segredo]"),
    (re.compile(r"\b(?:token|apikey|api_key|key|senha|password|passwd|secret|cookie)\b\s*[:=]\s*\S+", re.I), "[segredo]"),
    (re.compile(r"\b(?:sk|pk|ghp|gho|xox[abp]|AIza)[-_A-Za-z0-9]{12,}\b"), "[segredo]"),  # prefixos de chave conhecidos
    (re.compile(r"\b[A-Za-z0-9+/_-]{32,}={0,2}"), "[segredo]"),                          # blob longo (hex/base64/jwt)
]
TETO = 140


def sanear(texto: str | None) -> str:
    t = " ".join(str(texto or "").split())
    for rg, sub in _SUBS:
        t = rg.sub(sub, t)
    return t if len(t) <= TETO else t[:TETO - 1].rstrip() + "…"
