# -*- coding: utf-8 -*-
"""Gradeador epistemológico de flags — CERTO × FORTE × SUSPEITO × NÃO-AFERÍVEL × EXCULPADO.

O dossiê mestre nunca mistura graus de certeza (plano docs/superpowers/plans/2026-07-20-dossie-mestre.md §0):

  A CERTO      fato objetivo com número+fonte+teto legal (só código determinístico produz)
  B FORTE      convergência de ≥2 famílias independentes de indício
  C SUSPEITO   juízo interpretativo (LLM/lentes) — SEMPRE requer confirmação humana/diligência
  D NAO_AFERIVEL  INDISPONÍVEL ≠ 0
  E EXCULPADO  guard anti-FP disparou (dentro do teto, preço regulado, saneamento uniforme…)

Regra dura: LLM NUNCA produz A — o teto de qualquer juízo de IA é C; a promoção C→B exige
corroboração determinística independente; C jamais vira A. A e B podem fundamentar peça;
C só acompanha A/B ou vira diligência.
"""
from __future__ import annotations

GRAUS = ("A", "B", "C", "D", "E")
_ROTULOS = {
    "A": ("FLAG CERTO", "🔴"),
    "B": ("INDÍCIO FORTE", "🟠"),
    "C": ("FLAG SUSPEITO", "🟡"),
    "D": ("NÃO-AFERÍVEL", "❔"),
    "E": ("EXCULPADO", "🟢"),
}


def grau_flag(*, origem: str, teste_status: str | None = None, score: float | None = None,
              familias_convergentes: int = 0, exculpado: bool = False) -> dict:
    """Grada um achado. `origem`: 'deterministico' | 'llm'. `teste_status`: status do teste
    finalístico se houver ('violado'/'dentro_do_teto'/'nao_aferivel'). `score`: âncora 0-1 do
    detector. `familias_convergentes`: nº de famílias INDEPENDENTES que corroboram (além da própria).

    Returns: {grau, rotulo, emoji, pode_fundamentar_peca, motivo}
    """
    if origem not in ("deterministico", "llm"):
        raise ValueError(f"origem desconhecida: {origem!r}")

    if exculpado or teste_status == "dentro_do_teto":
        g, motivo = "E", "guard anti-FP/exculpatória disparou — registrado, sem medida"
    elif origem == "llm":
        # teto de IA é C; convergência com detector determinístico promove a B (nunca a A)
        if score is None:
            g, motivo = "D", "juízo LLM indisponível/sem score — degrada honesto"
        elif familias_convergentes >= 1:
            g, motivo = "B", "juízo interpretativo corroborado por família determinística independente"
        else:
            g, motivo = "C", "juízo interpretativo sem corroboração determinística — requer diligência/humano"
    elif teste_status == "violado":
        g, motivo = "A", "teto legal excedido em aferição objetiva (número + fonte)"
    elif teste_status == "nao_aferivel" and (score is None or score <= 0):
        g, motivo = "D", "sem número aferível nem score de detector — INDISPONÍVEL ≠ 0"
    elif score is not None and score >= 0.85 and familias_convergentes >= 1:
        g, motivo = "B", "âncora forte com convergência de ≥2 famílias independentes"
    elif score is not None and score > 0:
        g, motivo = "C", "indício determinístico isolado abaixo de convergência — tratar como suspeito"
    else:
        g, motivo = "D", "sem base aferível"

    rotulo, emoji = _ROTULOS[g]
    return {"grau": g, "rotulo": rotulo, "emoji": emoji,
            "pode_fundamentar_peca": g in ("A", "B"), "motivo": motivo}
