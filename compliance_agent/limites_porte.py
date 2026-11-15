# -*- coding: utf-8 -*-
"""limites_porte — fonte ÚNICA dos tetos de receita bruta anual por porte (Simples Nacional).

LC 123/2006: art. 3º, I (Microempresa, até R$ 360.000,00) e II (Empresa de Pequeno Porte, até
R$ 4.800.000,00); art. 18-A, §1º (MEI, até R$ 81.000,00). O teto é ANUAL: compara-se com a receita (ou o pago)
de UM ano-calendário, nunca com a soma de vários anos.

NUNCA duplicar estes valores em detector — importar daqui. Em 15/11/2026 havia seis cópias (investigacao_dd,
governo_couto_regras, lentes_pcrj, contrato_acima_do_porte, porte_declarado_certame, porte_incompativel)."""
from __future__ import annotations

TETO_MEI = 81_000.00
TETO_ME = 360_000.00
TETO_EPP = 4_800_000.00

# rótulos como aparecem na Receita (porte) e no cadastro do TCE-RJ
TETO_ANUAL_POR_PORTE: dict[str, float] = {
    "Microempresa": TETO_ME,
    "Empresa de Pequeno Porte": TETO_EPP,
}
