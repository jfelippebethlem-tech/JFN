# -*- coding: utf-8 -*-
"""Orquestrador do enxame: dispara as lentes, sintetiza com desempate adversarial.

Controle de fluxo determinístico; LLM só dentro das lentes. Síntese:
  base = mediana dos votos VÁLIDOS; na faixa limítrofe [4,6], o voto do
  refutador puxa para baixo (presunção de legitimidade — empate a favor do réu).
"""
from __future__ import annotations

import statistics

from compliance_agent.enxame import lentes

LENTES = [
    ("proporcionalidade", lentes.lente_proporcionalidade),
    ("jurisprudencia", lentes.lente_jurisprudencia),
    ("competicao", lentes.lente_competicao),
    ("refutador", lentes.lente_refutador),
    ("beneficiario", lentes.lente_beneficiario),
]

_BANDA_LIMITROFE = (4, 6)


def _veredito(score: int) -> str:
    if score >= 7:
        return "direcionamento"
    if score >= 4:
        return "indício fraco"
    return "normal"


def avaliar(dossie: dict, gerar=None) -> dict:
    votos = {}
    for nome, fn in LENTES:
        votos[nome] = fn(dossie, gerar=gerar)
    validos = [v["voto"] for v in votos.values() if v.get("voto") is not None]
    if not validos:
        return {"score_final": 0, "veredito": "nao_avaliavel",
                "motivo": "todas as lentes indisponíveis (INDISPONÍVEL ≠ 0)", "votos": votos}
    base = statistics.median(validos)
    ref = votos.get("refutador", {}).get("voto")
    # REFUTADOR COMO GATE (presunção de legitimidade): se o advogado do edital
    # CONSEGUIU defendê-lo (voto baixo), a exigência é lícita — o score não pode
    # ficar alto por maioria enviesada. Teto = refutador + 1.
    if ref is not None and ref <= 3:
        base = min(base, ref + 1)
    # desempate na faixa limítrofe também pende para o cético
    elif _BANDA_LIMITROFE[0] <= base <= _BANDA_LIMITROFE[1] and ref is not None and ref < base:
        base = ref
    score = int(round(base))
    return {"score_final": score, "veredito": _veredito(score), "votos": votos}
