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

# ANTES da Lei 14.133 (exercícios < 2021) o teto é o da Lei 8.666/1993, art. 24, I e II (10% do limite do convite
# do art. 23). Sem esta tabela, `limite_dispensa(2019)` devolvia o teto de 2026 (R$ 65.492,11 — 3,7× o legal) e
# contaminava todo detector que roda sobre o SIAFE 1 (2016–2023). Mantida FORA de `LIMITES` de propósito: `LIMITES`
# é a régua da 14.133 (P4 trata exercício anterior a ela como não avaliável) e a catraca de teto copiado lê só ela.
# 2018 é ano partido (Decreto 9.412 vigora 30 dias após 19/06/2018); usa-se o teto MAIOR, que erra para menos achado.
# 2021–2023 a Administração ainda podia optar pela 8.666 (art. 191 da 14.133, até 30/12/2023); a régua devolve o teto
# da 14.133 (maior), sem saber a lei do edital — quem tiver o processo deve ler a lei escolhida.
LIMITES_8666: dict[int, dict] = {
    **{a: {"obras": 15000.00, "compras": 8000.00,
           "ato": "Lei 8.666/1993, art. 24, I e II (redação da Lei 9.648/1998)"} for a in range(1998, 2018)},
    **{a: {"obras": 33000.00, "compras": 17600.00,
           "ato": "Lei 8.666/1993, art. 24, I e II, c/c Decreto 9.412, de 18/06/2018"} for a in range(2018, 2021)},
}


def _info(ano: int) -> dict:
    ano = int(ano)
    if ano < min(LIMITES) and ano in LIMITES_8666:
        return LIMITES_8666[ano]
    return LIMITES.get(ano) or LIMITES[max(LIMITES)]


def limite_dispensa(ano: int, tipo: str = "compras", *, duplicado: bool = False) -> float:
    """Limite do exercício (R$). `tipo`: 'compras' (art. 75-II) ou 'obras' (art. 75-I).
    Ano anterior à 14.133 → teto da Lei 8.666 (`LIMITES_8666`); ano posterior à tabela → o mais recente conhecido
    (atualizar a tabela quando sair decreto).

    `duplicado=True` aplica o **art. 75, §2º**: "Os valores referidos nos incisos I e II do caput serão
    DUPLICADOS para compras, obras e serviços contratados por CONSÓRCIO PÚBLICO ou por AUTARQUIA ou
    FUNDAÇÃO qualificadas como AGÊNCIAS EXECUTIVAS." Sem isso, o teto aplicado a esses entes é METADE do
    legal — e o detector acusa fracionamento onde a lei não vê nenhum. (Na 8.666, art. 24 §1º, 20% para
    consórcio público, empresa pública, sociedade de economia mista e agência executiva — o mesmo dobro.)"""
    info = _info(ano)
    return info[tipo] * 2 if duplicado else info[tipo]


def ato_normativo(ano: int) -> str:
    """Decreto/lei que fixa o limite do exercício — para citação em relatório."""
    info = _info(ano)
    return info["ato"]
