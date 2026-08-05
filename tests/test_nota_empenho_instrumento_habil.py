# -*- coding: utf-8 -*-
"""A nota de empenho SUBSTITUI o termo de contrato nas hipóteses legais.

Art. 95, §1º da Lei 14.133/2021 — e art. 62 da Lei 8.666/93, para fatos até 2023 — permitem
substituir o instrumento de contrato por carta-contrato, **nota de empenho de despesa**,
autorização de compra ou ordem de execução de serviço.

Medido em 2026-08-05: dos **21 processos acusados de "Formalização do contrato" ausente, 9 têm
Nota de Empenho nos autos e nenhum termo de contrato**. Dizer "falta formalização" ali é cobrar a
forma que a própria lei dispensa.

O achado **não some**: a substituição só vale nas hipóteses legais, e conferir o enquadramento é
trabalho do fiscal. Ele passa a dizer o que se vê, aponta a peça e cai de grau.

⚠️ Isto é sobre FORMA do ajuste, não sobre pagamento. Empenho ≠ liquidação ≠ OB — a nota de
empenho vale como instrumento contratual, nunca como prova de que algo foi pago.
"""
from __future__ import annotations

from compliance_agent.processo_360 import _instrumento_habil


def test_nota_de_empenho_pelo_tipo():
    docs = [{"titulo": "Despacho 1", "tipo": "despacho"},
            {"titulo": "Nota de Empenho Original - NE 2024NE00153 (68455597)",
             "tipo": "nota_empenho"}]
    assert _instrumento_habil(docs) == "Nota de Empenho Original - NE 2024NE00153 (68455597)"


def test_nota_de_empenho_pela_fase():
    """O manifesto normalizado às vezes traz a fase e não o tipo — as duas portas valem."""
    docs = [{"titulo": "Recibo nota de empenho (55617015)", "fase": "nota_empenho"}]
    assert _instrumento_habil(docs) == "Recibo nota de empenho (55617015)"


def test_sem_empenho_nao_ha_instrumento_substituto():
    docs = [{"titulo": "Contrato Social (123)", "tipo": "habilitacao"},
            {"titulo": "Ofício 5", "tipo": "oficio"}]
    assert _instrumento_habil(docs) is None


def test_contrato_social_do_licitante_nao_conta():
    """`Contrato Social` é peça de HABILITAÇÃO do licitante, não instrumento do ajuste — sete dos
    21 processos o traziam, e ele não formaliza contratação nenhuma."""
    assert _instrumento_habil([{"titulo": "Anexo CONTRATO SOCIAL (99)", "tipo": "habilitacao"}]) is None
