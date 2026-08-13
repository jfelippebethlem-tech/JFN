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
    fonte = inspect.getsource(extrair_interpretativo)
    assert 'FREE_LLM_PREFER' in fonte and '"nous"' in fonte, (
        "sem o padrão, o provedor vira acidente do ambiente — e o acidente custou 12×")


def test_o_ambiente_ainda_manda_quando_declarado():
    """`setdefault` e não atribuição: quem exporta outro provedor de propósito continua no comando."""
    assert "setdefault" in inspect.getsource(extrair_interpretativo)
