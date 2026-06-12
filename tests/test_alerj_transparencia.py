# -*- coding: utf-8 -*-
"""Testes do parser de pagamentos da Transparência ALERJ (determinístico, sem rede)."""
from __future__ import annotations

from compliance_agent.collectors import alerj_transparencia as A


TXT = """
                              Ordem cronológica de pagamentos realizados - Abril/2026
   Programa de Trabalho        Natureza Despesa    Credor        Nota de Empenho   Nota de Liquidação   Emissão NL    Ordem Bancária   Despesas Pagas
   1010100112201352462 - Manutenção
                                339039      AGÊNCIA NACIONAL DE PROPAGANDA LTDA   2025NE00611   2026NL00765   01/04/2026   Retenção   Retenção   R$ 685,44
   1010100112201352462 - Manutenção
                                339039      VINIL GESTAO E FACILITIES LTDA        2026NE00290   2026NL00900   03/04/2026   2026OB1234 04/04/2026   R$ 42.914,10
   linha lixo sem padrão de pagamento aqui
"""


def test_parseia_pagamentos_e_mes():
    r = A.parsear_pagamentos(TXT)
    assert r["mes_ano"] == "Abril/2026"
    assert r["n"] == 2
    cred = {i["credor"] for i in r["itens"]}
    assert "AGÊNCIA NACIONAL DE PROPAGANDA LTDA" in cred
    vinil = next(i for i in r["itens"] if "VINIL" in i["credor"])
    assert vinil["valor"] == 42914.10
    assert vinil["empenho"] == "2026NE00290"
    assert vinil["natureza"] == "339039"
    assert vinil["data"] == "03/04/2026"


def test_ignora_linha_sem_padrao():
    r = A.parsear_pagamentos(TXT)
    assert all("lixo" not in i["credor"].lower() for i in r["itens"])


def test_texto_vazio_honesto():
    r = A.parsear_pagamentos("")
    assert r["n"] == 0 and r["mes_ano"] is None
