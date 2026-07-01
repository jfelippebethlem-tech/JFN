"""
Motor de risco — agrega achados num rating defensável (matriz TCU P×I).

Recebe os Achados determinísticos de ``indicadores.py`` e produz um veredito:
  - risco_score  : 0–100
  - classificacao: crítico | alto | médio | baixo
  - posição na matriz Probabilidade × Impacto (padrão TCU, já usado nos relatórios)
  - fundamentação legal consolidada (dedup das bases legais dos achados)
  - confiança agregada

Nenhuma IA participa do veredito. Isso importa porque o output vira peça de
fiscalização (ofício ao TCE-RJ, requerimento de CPI): precisa ser reproduzível
e explicável campo a campo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from compliance_agent.nucleo.indicadores import Achado


# Peso de severidade → contribuição de "impacto".
_PESO_SEVERIDADE = {"alta": 3.0, "média": 1.6, "baixa": 0.8}


@dataclass
class Veredito:
    risco_score: float                 # 0–100
    classificacao: str                 # crítico | alto | médio | baixo
    probabilidade: int                 # 1–5 (eixo TCU)
    impacto: int                       # 1–5 (eixo TCU)
    confianca: float                   # 0–1 (média ponderada das confianças)
    achados: list[Achado] = field(default_factory=list)
    base_legal: list[str] = field(default_factory=list)
    resumo: str = ""


def _escala_1a5(x: float, cortes: tuple[float, float, float, float]) -> int:
    """Mapeia um valor contínuo em 1–5 conforme cortes crescentes."""
    for i, c in enumerate(cortes):
        if x < c:
            return i + 1
    return 5


def pontuar(achados: list[Achado], valor_contrato: float | None = None) -> Veredito:
    """
    Consolida achados num Veredito.

    Probabilidade (eixo TCU) cresce com a soma ponderada de severidade×confiança
    dos achados — muitos indícios sólidos = mais provável a irregularidade.
    Impacto cresce com a severidade máxima e com o valor financeiro em jogo.
    """
    if not achados:
        return Veredito(
            risco_score=0.0, classificacao="baixo", probabilidade=1, impacto=1,
            confianca=0.0, achados=[], base_legal=[],
            resumo="Nenhum indicador de irregularidade disparou.",
        )

    # Probabilidade: soma ponderada (severidade × confiança), saturando.
    carga = sum(_PESO_SEVERIDADE.get(a.severidade, 1.0) * a.confianca for a in achados)
    probabilidade = _escala_1a5(carga, (0.8, 2.0, 4.0, 6.5))

    # Impacto: severidade máxima + valor financeiro.
    sev_max = max(_PESO_SEVERIDADE.get(a.severidade, 1.0) for a in achados)
    imp_base = _escala_1a5(sev_max, (1.0, 1.6, 2.4, 3.0))
    if valor_contrato:
        imp_valor = _escala_1a5(valor_contrato,
                                (100_000, 1_000_000, 10_000_000, 50_000_000))
        impacto = max(imp_base, imp_valor)
    else:
        impacto = imp_base

    # Score 0–100 a partir da posição na matriz 5×5 (25 → 100).
    risco_score = round((probabilidade * impacto) / 25 * 100, 1)

    if risco_score >= 72:
        classificacao = "crítico"
    elif risco_score >= 48:
        classificacao = "alto"
    elif risco_score >= 24:
        classificacao = "médio"
    else:
        classificacao = "baixo"

    # Confiança agregada: média ponderada pela severidade.
    peso_total = sum(_PESO_SEVERIDADE.get(a.severidade, 1.0) for a in achados)
    confianca = round(
        sum(_PESO_SEVERIDADE.get(a.severidade, 1.0) * a.confianca for a in achados)
        / peso_total, 3
    ) if peso_total else 0.0

    # Base legal consolidada (dedup preservando ordem).
    vistos: set[str] = set()
    base_legal: list[str] = []
    for a in achados:
        for b in a.base_legal:
            if b not in vistos:
                vistos.add(b)
                base_legal.append(b)

    titulos = ", ".join(dict.fromkeys(a.titulo for a in achados))
    resumo = (f"Risco {classificacao.upper()} ({risco_score:.0f}/100; "
              f"P{probabilidade}×I{impacto} na matriz TCU). "
              f"{len(achados)} indicador(es): {titulos}.")

    return Veredito(
        risco_score=risco_score, classificacao=classificacao,
        probabilidade=probabilidade, impacto=impacto, confianca=confianca,
        achados=achados, base_legal=base_legal, resumo=resumo,
    )
