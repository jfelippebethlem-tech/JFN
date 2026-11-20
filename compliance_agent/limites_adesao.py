# -*- coding: utf-8 -*-
"""limites_adesao — fonte ÚNICA dos limites objetivos de adesão a ata de registro de preços ("carona"),
art. 86 da Lei 14.133/2021. Lidos pelo detector X4 e pela família `padroes/carona_*` (que antes importava o
detector só para ler a norma)."""
from __future__ import annotations

LIMITE_ADESAO_INDIVIDUAL = 0.50   # §4º — cada aderente até 50% do quantitativo registrado do item
LIMITE_TOTAL_ADESOES = 2.0        # §5º — total de adesões até o DOBRO do quantitativo do item
