# -*- coding: utf-8 -*-
"""O sweep do SEI é do nous — e a regra da casa tem motivo medido.

Rodei este loop inteiro com `FREE_LLM_PREFER=openrouter`, por escolha minha, contra o que o
`CLAUDE.md` manda para VOLUME de SEI. Medido no mesmo processo, mesmo prompt, na mesma janela:

| provedor | tempo | resposta |
|---|---:|---:|
| nous (`stepfun:free`) | **45,7 s** | 2.114 chars, JSON limpo |
| openrouter | **536,2 s** | 567 chars, embrulhado em cerca ```json |

**12× mais lento, resposta mais pobre.** A regra da casa não era preferência de estilo: era a
medição que eu não tinha feito. Antes disso eu já havia culpado o tamanho do prompt e o
paralelismo — o custo era fixo por chamada, e dependia de QUAL provedor.

Este teste guarda o padrão para que a escolha não volte a ser acidental.
"""
from __future__ import annotations

import inspect

from tools.sei_leitura_dupla import extrair_interpretativo


def test_o_padrao_e_o_provedor_do_sweep_de_sei():
    """Desde f5a75b32 (13/08) o padrão não é uma variável de ambiente: `FREE_LLM_PREFER=nous` nunca
    significou nada, porque o nous não é provedor do free_llm — é função própria (`tools/sei_ficha`).
    O que o teste guarda é o DESENHO: nous direto por padrão, cadeia curta só como queda."""
    fonte = inspect.getsource(extrair_interpretativo)
    assert "_gerar_nous()" in fonte and "_gerar_cadeia_curta()" in fonte, (
        "sem o padrão explícito, o provedor vira acidente do ambiente — e o acidente custou 12×")
    assert fonte.index("_gerar_nous()") < fonte.index("_gerar_cadeia_curta()")   # nous ANTES da cadeia


def test_quem_injeta_gerar_continua_no_comando():
    """`gerar=` explícito ignora o padrão: quem quer outro provedor de propósito segue mandando."""
    chamadas = []

    def falso(prompt, *a, **k):
        chamadas.append(prompt)
        return "{}"

    extrair_interpretativo("texto", "SEI-000000/000000/2026", gerar=falso)
    assert chamadas, "gerar= injetado não foi usado"
