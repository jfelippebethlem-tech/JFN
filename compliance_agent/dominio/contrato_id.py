# -*- coding: utf-8 -*-
"""Chave do CONTRATO: `(orgao, numero_normalizado, exercicio)` (plano mestre v2, §3.1).

`numero_contrato` é a normalização única do número "N/AAAA" (paridade em `tests/test_dominio_contrato_id.py`
contra `padroes._aditivos_comum.norm_contrato`, `sei.instrumento_assinatura.num_contrato` e
`sei.reuso_documento_execucao.contratos_citados`):
- zeros à esquerda do número saem ("016/2023" e "16/2023" são o MESMO contrato — 13 dos 29 falsos positivos do I5);
- ano com 2 dígitos vira "20AA" (como `norm_contrato`; `num_contrato` o deixava com 2 — divergência documentada);
- espaços em volta da barra saem; o que não é "dígitos/dígitos" devolve `None` (`norm_contrato` levantava erro).

`orgao` não é inventado aqui: vem do chamador (código da UG, CNPJ ou sigla) e só é aparado — código só de dígitos
fica só com os dígitos (UG `080001`, CNPJ sem pontuação). Contrato com ano no número diferente do `exercicio`
informado → `None` (as duas fontes discordam; nenhuma das duas vence calada).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from compliance_agent.dominio.digitos import so_digitos

_RX_NUM = re.compile(r"^\s*0*(\d{1,6})\s*(?:/\s*(\d{4}|\d{2}))?\s*$")


@dataclass(frozen=True)
class ContratoId:
    orgao: str
    numero_normalizado: str   # "N/AAAA"
    exercicio: int

    @property
    def chave(self) -> tuple[str, str, int]:
        return (self.orgao, self.numero_normalizado, self.exercicio)


def numero_contrato(texto, exercicio: int | None = None) -> str | None:
    """'034/2026' → '34/2026'; '34/26' → '34/2026'; '34' com `exercicio=2026` → '34/2026'. Senão `None`."""
    m = _RX_NUM.match(str(texto or ""))
    if not m:
        return None
    n, ano = m.groups()
    if ano is None:
        if exercicio is None:
            return None
        ano = str(int(exercicio))
    elif len(ano) == 2:
        ano = "20" + ano
    if exercicio is not None and int(ano) != int(exercicio):
        return None
    return f"{int(n)}/{ano}"


def normalizar_orgao(orgao) -> str:
    s = re.sub(r"\s+", " ", str(orgao or "")).strip().upper()
    return so_digitos(s) if re.fullmatch(r"[\d.\-/ ]+", s or "x") else s


def contrato_id(orgao, numero, exercicio: int | None = None) -> ContratoId | None:
    """A chave do contrato; `None` se faltar órgão ou o número não for reconhecido."""
    org = normalizar_orgao(orgao)
    num = numero_contrato(numero, exercicio)
    if not org or not num:
        return None
    return ContratoId(org, num, int(num.split("/")[1]))
