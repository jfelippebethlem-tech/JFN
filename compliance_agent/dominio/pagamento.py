# -*- coding: utf-8 -*-
"""Pagamento — INVARIANTE 1 do plano mestre v2 (§3.10): **pago = OB paga do SIAFE.**

- Só a Ordem Bancária do SIAFE (`ob_orcamentaria_siafe`) que passa no predicado canônico é pagamento. Empenho e
  liquidação não são pagamento; o espelho TFE (`ordens_bancarias`) só serve de confronto, nunca de "pago".
- O predicado é o de `compliance_agent.cruzamentos_intel._ob_paga` (fonte única desde 24/09/2026): status
  `Contabilizado`, sem `Erro no Pagamento` no envio, sem `Pagamento Complementar`, sem a 1ª emissão de OB
  reemitida (`ob_reemitida`) e com número de OB. Aqui ele só ganha nome público; a regra não é reescrita.
- A tipologia `natureza_pagamento` / `origem_exercicio` (§4.3) é a O4.6 — fora deste módulo por ora.

PONTE COM O LEGADO: `_ob_paga` consulta o schema pela conexão (PRAGMA), então NÃO é pura. O import fica DENTRO da
função, para `import compliance_agent.dominio` não carregar nada do legado; o par
`compliance_agent.dominio.pagamento -> compliance_agent.cruzamentos_intel` está em `ignore_imports` do
`.importlinter` (e na lista equivalente de `tests/test_dominio_sem_io.py`) — lista que só pode encolher. Sai
quando o predicado migrar para cá como texto SQL puro com as colunas informadas pelo adaptador.
"""
from __future__ import annotations


def ob_paga_sql(con, alias: str = "") -> str:
    """Trecho SQL (WHERE) que seleciona a OB que é pagamento em `ob_orcamentaria_siafe`.
    `alias`: prefixo da tabela na consulta (ex.: "o" → `o.status`). Idêntico a `cruzamentos_intel._ob_paga`."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    return _ob_paga(con, alias)
