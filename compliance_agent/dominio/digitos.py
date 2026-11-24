# -*- coding: utf-8 -*-
"""Dígitos, DV e máscara — UM `so_digitos` (plano mestre v2, §3.1: chave Pessoa).

Não duplica nada: reexporta `compliance_agent.cpf_cnpj`, que já é a fonte única do módulo 11 e da máscara PAD-04
(e só importa `re`). `so_digitos` é o nome canônico de `cpf_cnpj.digitos`.

Semântica (a de `cpf_cnpj.digitos`, conferida por paridade em `tests/test_dominio_digitos.py` contra as 17 cópias):
- `re.sub(r"\\D", "", str(v or ""))`: `None` e `""` viram `""`; qualquer objeto é aceito via `str()`;
- dígito é o `\\d` do `re` em `str` (categoria Unicode Nd): `"１２"` (largura total) e `"١٢"` (arábico-índico) ficam;
  `"²"` (sobrescrito, categoria No) sai — as cópias com `str.isdigit()` o mantinham (divergência documentada);
- valor falso não-string (`0`, `0.0`, `False`) vira `""` (é o `v or ""`). Nenhum CPF/CNPJ/processo é o inteiro 0.
"""
from __future__ import annotations

from compliance_agent.cpf_cnpj import (  # noqa: F401 — reexportação é o propósito do módulo
    cnpj_valido,
    cpf_valido,
    digitos as so_digitos,
    mascarar_cpf,
    mascarar_cpf_no_texto,
    mascarar_doc,
)

__all__ = ["so_digitos", "cpf_valido", "cnpj_valido", "mascarar_cpf", "mascarar_doc", "mascarar_cpf_no_texto"]
