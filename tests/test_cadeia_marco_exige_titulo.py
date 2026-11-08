# -*- coding: utf-8 -*-
"""O `tipo` do arquivador sozinho elegia o marco — e errava 79% das vezes.

`_marco` casa por `tipo` **OU** por título. Para a cadeia orçamentária isso basta para o tipo
sozinho decidir, e ele mente. Medido em 2026-08-05 nos **24 achados de cadeia do acervo: 19 (79%)
apontavam como peça “fora de ordem” um documento que não é da fase alegada**:

  · 6 × "Planilha de Controle de Faturamento"  tipada **pagamento**
  · 4 × "Correspondência Interna - NI/NA"      tipada **liquidação**
  · 1 × "Documento Trabalhista"                tipada **liquidação**
  · 1 × "Declaração NÃO RETENÇÃO INSS"         tipada **contrato**

Planilha de faturamento é controle interno de cobrança — e **empenho ≠ liquidação ≠ OB**. A
acusação aqui é de inversão da ordem legal da despesa (arts. 60, 62 e 63 da Lei 4.320/1964): não
se sustenta sobre a etiqueta do arquivador. É a mesma dupla concordância que o A1 da triagem já
exige, e que faltava justamente onde a imputação é mais séria.
"""
from __future__ import annotations

import pytest

from compliance_agent.cadeia_processo import _marco


@pytest.mark.parametrize("titulo,tipo", [
    ("Planilha de Controle de Faturamento - Junho/2026", "ordem_bancaria"),
    ("Planilha FATURAMENTO SEGUNDA QUINZENA DE FEVEREIRO", "ordem_bancaria"),
    ("Correspondência Interna - NI 2871/2026", "liquidacao"),
    ("Correspondência Interna - NA 187", "liquidacao"),
    ("Documento Trabalhista (133321411)", "liquidacao"),
])
def test_etiqueta_sem_marca_do_ato_no_titulo_nao_e_marco(titulo, tipo):
    assert _marco({"titulo": titulo, "tipo": tipo}) is None


@pytest.mark.parametrize("titulo,tipo,esperado", [
    ("Nota de Empenho Original - NE 2024NE00153", "nota_empenho", "empenho"),
    ("Anexo 2024OB28436 - INSS", "ordem_bancaria", "pagamento"),
    ("Nota de Liquidação 2024NL00321", "liquidacao", "liquidacao"),
    ("Ordem Bancária 2025OB01122", "outro", "pagamento"),
])
def test_marca_do_ato_no_titulo_continua_valendo(titulo, tipo, esperado):
    """A correção não pode desarmar o achado verdadeiro: com o nome da peça ou o número SIAFE
    (20XXNE/NL/OB) no título, o marco vale — inclusive quando o `tipo` não ajuda."""
    assert _marco({"titulo": titulo, "tipo": tipo}) == esperado


def test_contrato_e_parecer_seguem_pelas_proprias_guardas():
    """A exigência de título é só da cadeia orçamentária: contrato e parecer já têm guardas
    próprias (`_RE_NAO_CONTRATO`, anexo-não-é-ato, parecer técnico ≠ jurídico)."""
    assert _marco({"titulo": "Termo de Contrato 38/2023", "tipo": "contrato"}) == "contrato"
    assert _marco({"titulo": "Parecer Jurídico 462", "tipo": "parecer_juridico"}) == "parecer_juridico"
