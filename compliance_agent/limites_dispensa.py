# -*- coding: utf-8 -*-
"""limites_dispensa — fonte ÚNICA dos limites de dispensa de licitação (Lei 14.133/2021,
art. 75, I — obras/serviços de engenharia — e II — compras e demais serviços), ano a ano.

Valores verificados VERBATIM no texto dos decretos no Planalto (conferência 2026-07-17;
numérico e por extenso conferem). Atualização anual por IPCA-E (art. 182). Cadeia:
10.922/2021 → 11.317/2022 → 11.871/2023 → 12.343/2024 → 12.807/2025 (cada um revoga o
anterior e vigora a partir de 1º/01 do ano seguinte).

NUNCA duplicar esta tabela em detector — importar daqui (as cópias divergentes em
p4_fracionamento e cruzamentos_intel foram o motivo deste módulo)."""
from __future__ import annotations

LIMITES: dict[int, dict] = {
    2021: {"obras": 100000.00, "compras": 50000.00,
           "ato": "Lei 14.133/2021, art. 75 (texto original, vigente 01/04-31/12/2021)"},
    2022: {"obras": 108040.82, "compras": 54020.41, "ato": "Decreto 10.922, de 30/12/2021"},
    2023: {"obras": 114416.65, "compras": 57208.33, "ato": "Decreto 11.317, de 29/12/2022"},
    2024: {"obras": 119812.02, "compras": 59906.02, "ato": "Decreto 11.871, de 29/12/2023"},
    2025: {"obras": 125451.15, "compras": 62725.59, "ato": "Decreto 12.343, de 30/12/2024"},
    2026: {"obras": 130984.20, "compras": 65492.11, "ato": "Decreto 12.807, de 29/12/2025"},
}


def limite_dispensa(ano: int, tipo: str = "compras") -> float:
    """Limite do exercício (R$). `tipo`: 'compras' (art. 75-II) ou 'obras' (art. 75-I).
    Ano fora da tabela → o mais recente conhecido (atualizar a tabela quando sair decreto)."""
    info = LIMITES.get(int(ano)) or LIMITES[max(LIMITES)]
    return info[tipo]


def ato_normativo(ano: int) -> str:
    """Decreto/lei que fixa o limite do exercício — para citação em relatório."""
    info = LIMITES.get(int(ano)) or LIMITES[max(LIMITES)]
    return info["ato"]
