# -*- coding: utf-8 -*-
"""limites_habilitacao — fonte ÚNICA dos tetos de exigência de edital (habilitação e participação).

Os números (Lei 14.133/2021 e súmulas do TCU, conforme o texto verbatim guardado em
`knowledge/catalogo_vicios`):
  · quantitativo de atestado técnico: até 50% da parcela relevante (art. 67 §§1º-2º; Súmula TCU 263);
  · capital social OU patrimônio líquido mínimo: até 10% do valor estimado (art. 69 §§2º e 4º;
    Súmula TCU 275) — também a régua, por analogia, do faturamento mínimo;
  · garantia de proposta: até 1% do valor estimado (art. 58);
  · vigência inicial de serviço/fornecimento contínuo: até 5 anos (art. 106).

Em 20/11/2026 cada número estava escrito em quatro a cinco lugares (teste_finalistico em pontos
percentuais, E1/E7 e `editais/clausulas` em fração, o prompt da narrativa em texto). Percentual é a
unidade daqui porque `x / 100` dá a fração exata (0.1, 0.5, 0.01) e `fração * 100` não (10.000000000000002).

A CITAÇÃO ainda diverge entre os consumidores (teste_finalistico cita "Lei 8.666/93 art. 31 §3º" para
o capital; E1 cita "art. 69 §3º") — unificar a citação muda texto de entregável e depende de conferir o
dispositivo no texto oficial (pendência em docs/untangle/editais.md e detectores.md)."""
from __future__ import annotations

ATESTADO_QUANTITATIVO_MAX_PCT = 50.0
CAPITAL_PL_MAX_PCT = 10.0
GARANTIA_PROPOSTA_MAX_PCT = 1.0
VIGENCIA_CONTINUA_MAX_MESES = 60.0
