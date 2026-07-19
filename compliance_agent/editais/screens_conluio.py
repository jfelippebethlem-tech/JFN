# -*- coding: utf-8 -*-
"""Screens ESTATÍSTICOS de conluio sobre `proposta_item` (Task 4.2 da F4 — OCDE/CADE/Huber & Imhof).

Fundamento (docs/BENCHMARKS-EXTERNOS.md §3.3):
  • CV = σ/μ dos lances — baixo = lances anormalmente próximos (coordenação);
  • RD = (b₂−b₁)/média(diferenças entre perdedores) — RD≫1 = vencedor descolado com perdedores
    aglomerados (proposta-cobertura); CV e RD são os 2 preditores dominantes (Huber & Imhof 2019);
  • skewness NEGATIVA — lances de cobertura empurram a massa para cima, cauda para baixo;
  • preços de cobertura — perdedor absurdamente alto sobre vencedor + perdedores aglomerados;
  • vetores de preços unitários com razão constante ±k% entre concorrentes = quase-prova de
    PLANILHA COMPARTILHADA (complementa `sei.conluio_propostas.markup_uniforme`, par-a-par efêmero —
    aqui opera sobre o `proposta_item` PERSISTIDO).

REGRAS DE HONESTIDADE (cláusula absoluta):
  • <3 lances → screen estatístico devolve None = INDISPONÍVEL (nunca 0 — ausente ≠ 0);
  • NUNCA 1 screen só: score_conluio > 0.5 exige ≥2 screens concordantes (OCDE);
  • `confianca` = apuráveis/total — o consumidor vê o quanto do certame era mesmo apurável;
  • screen = INDÍCIO a verificar, nunca prova (Art. 36 Lei 12.529/CADE; Art. 337-F CP).
"""
from __future__ import annotations

import sqlite3
import statistics

from compliance_agent.editais.coletor_propostas import ITEM_LANCE_GLOBAL

# ── Thresholds nomeados — pontos de partida dos benchmarks (§3.3). ⚠️ Calibração LOCAL pendente:
# ARACHNE ensina que score sem calibração vira ruído (§3.1) — recalibrar com desfechos reais RJ
# (vencedor depois sancionado, sobrepreço vs mediana) quando `proposta_item` tiver volume.
CV_BAIXO = 0.05                # CV < 5% = lances anormalmente próximos (Huber & Imhof usam CV baixo como screen nº1)
RD_ALTO = 2.0                  # RD ≥ 2 = gap vencedor↔2º ≥ 2× o espaçamento típico dos perdedores (cobertura)
SKEW_NEG = 0.0                 # skewness < 0 (benchmark cita o SINAL; limiar fino vem da calibração local)
COBERTURA_RAZAO = 1.5          # perdedor ≥ 1.5× o vencedor = preço de cobertura clássico
COBERTURA_AGLOMERADO_CV = 0.10  # perdedores "aglomerados" entre si = CV dos perdedores ≤ 10%
TOL_VETOR = 0.03               # razão constante ±3% item a item = planilha compartilhada (±k% do benchmark)
MIN_LANCES = 3                 # mínimo para estatística de lances (abaixo → INDISPONÍVEL)
MIN_ITENS_COMUNS = 3           # mínimo de itens em comum para comparar vetores unitários
N_SCREENS = 5                  # cv_baixo, rd_alto, skew_negativa, cobertura, planilha_compartilhada


def cv_lances(valores: list[float]) -> float | None:
    """Coeficiente de variação σ/μ dos lances. None se <3 lances (INDISPONÍVEL, não 0)."""
    v = [x for x in (valores or []) if isinstance(x, (int, float)) and x > 0]
    if len(v) < MIN_LANCES:
        return None
    media = statistics.mean(v)
    return statistics.pstdev(v) / media if media else None


def rd_vencedor(valores: list[float]) -> float | None:
    """Relative Distance (Huber & Imhof): (b₂−b₁)/média(diferenças consecutivas entre perdedores),
    lances ordenados ASC (b₁=vencedor). None se <3 lances; None honesto se a média das diferenças
    entre perdedores for 0 (perdedores idênticos — divisão indefinida, não 'infinito inventado')."""
    v = sorted(x for x in (valores or []) if isinstance(x, (int, float)) and x > 0)
    if len(v) < MIN_LANCES:
        return None
    perdedores = v[1:]
    difs = [b - a for a, b in zip(perdedores, perdedores[1:])]
    media_difs = statistics.mean(difs)
    if media_difs == 0:
        return None
    return (v[1] - v[0]) / media_difs


def skewness(valores: list[float]) -> float | None:
    """Assimetria populacional m₃/σ³ dos lances. None se <3 lances ou σ=0 (lances idênticos:
    assimetria indefinida — o CV=0 já captura esse cenário)."""
    v = [x for x in (valores or []) if isinstance(x, (int, float)) and x > 0]
    if len(v) < MIN_LANCES:
        return None
    media = statistics.mean(v)
    sigma = statistics.pstdev(v)
    if sigma == 0:
        return None
    m3 = statistics.mean((x - media) ** 3 for x in v)
    return m3 / sigma ** 3


def precos_cobertura(valores: list[float]) -> bool:
    """Padrão de proposta-cobertura: (a) ≥1 perdedor ≥ COBERTURA_RAZAO× o vencedor E (b) os
    perdedores AGLOMERADOS entre si (CV dos perdedores ≤ COBERTURA_AGLOMERADO_CV) — "todos cobrem
    alto e juntos". Perdedores dispersos = disputa plausível → False. Com <3 lances devolve False;
    a apurabilidade (INDISPONÍVEL) é tratada em `screens()` (n_lances < MIN_LANCES → None)."""
    v = sorted(x for x in (valores or []) if isinstance(x, (int, float)) and x > 0)
    if len(v) < MIN_LANCES:
        return False
    vencedor, perdedores = v[0], v[1:]
    if not any(p >= COBERTURA_RAZAO * vencedor for p in perdedores):
        return False
    media_p = statistics.mean(perdedores)
    cv_p = statistics.pstdev(perdedores) / media_p if media_p else 1.0
    return cv_p <= COBERTURA_AGLOMERADO_CV


def _vetores_unitarios(conn: sqlite3.Connection, certame: str) -> dict[str, dict[int, float]]:
    """{fornecedor_cnpj: {item: valor_unitario}} dos itens unitários persistidos (item != lance global)."""
    rows = conn.execute(
        "SELECT fornecedor_cnpj, item, valor_unitario FROM proposta_item "
        "WHERE certame=? AND item != ? AND valor_unitario IS NOT NULL AND valor_unitario > 0",
        (certame, ITEM_LANCE_GLOBAL)).fetchall()
    por_forn: dict[str, dict[int, float]] = {}
    for cnpj, item, vu in rows:
        por_forn.setdefault(cnpj, {})[item] = vu
    return por_forn


def _comparar_vetores(por_forn: dict[str, dict[int, float]], tol: float) -> tuple[list[dict], int]:
    """(pares com razão ~constante, nº de pares COMPARÁVEIS). Par comparável = ≥MIN_ITENS_COMUNS itens
    em comum; similar = toda razão vu_b/vu_a dentro de ±tol da razão média (planilha compartilhada)."""
    similares: list[dict] = []
    comparaveis = 0
    forns = sorted(por_forn)
    for i, a in enumerate(forns):
        for b in forns[i + 1:]:
            comuns = sorted(set(por_forn[a]) & set(por_forn[b]))
            if len(comuns) < MIN_ITENS_COMUNS:
                continue
            comparaveis += 1
            razoes = [por_forn[b][it] / por_forn[a][it] for it in comuns]
            media = statistics.mean(razoes)
            if media <= 0:
                continue
            desvio_max = max(abs(r / media - 1) for r in razoes)
            if desvio_max <= tol:
                similares.append({"a": a, "b": b, "n_itens": len(comuns),
                                  "razao_media": round(media, 4), "desvio_max": round(desvio_max, 4)})
    return similares, comparaveis


def vetores_unitarios_similares(conn: sqlite3.Connection, certame: str, tol: float = TOL_VETOR) -> list[dict]:
    """Pares de fornecedores do MESMO certame cujos preços unitários item-a-item guardam razão
    ~constante (±tol, ≥3 itens em comum) — a assinatura da PLANILHA COMPARTILHADA (§3.3: vetores
    iguais ±k% = quase-prova). Razão 1.0 constante = preços idênticos (também dispara)."""
    similares, _ = _comparar_vetores(_vetores_unitarios(conn, certame), tol)
    return similares


def _lances_do_certame(conn: sqlite3.Connection, certame: str) -> list[float]:
    """Um lance TOTAL por fornecedor: preferir o lance global da ata (item=0); senão a soma dos
    valor_total dos itens — mas SÓ se TODOS os itens do fornecedor têm valor_total literal (soma
    parcial subestimaria o lance e distorceria os screens; ausente ≠ 0)."""
    rows = conn.execute(
        "SELECT fornecedor_cnpj, item, valor_total FROM proposta_item WHERE certame=?",
        (certame,)).fetchall()
    globais: dict[str, float] = {}
    itens: dict[str, list] = {}
    for cnpj, item, vt in rows:
        if item == ITEM_LANCE_GLOBAL:
            if vt is not None and vt > 0:
                globais[cnpj] = vt
        else:
            itens.setdefault(cnpj, []).append(vt)
    lances = dict(globais)
    for cnpj, vts in itens.items():
        if cnpj in lances:
            continue  # lance global da ata prevalece
        if all(v is not None and v > 0 for v in vts):
            lances[cnpj] = sum(vts)
    return list(lances.values())


def screens(conn: sqlite3.Connection, certame: str) -> dict:
    """Agrega os 5 screens do certame. score_conluio = disparados/apuráveis, com a REGRA OCDE de
    decisão: score > 0.5 exige ≥2 screens concordantes (1 screen só fica capado em 0.5).
    confianca = apuráveis/N_SCREENS. Screen inapurável fica None no dict (INDISPONÍVEL ≠ 0)."""
    valores = _lances_do_certame(conn, certame)
    n = len(valores)
    cv = cv_lances(valores)
    rd = rd_vencedor(valores)
    skew = skewness(valores)
    cobertura = precos_cobertura(valores) if n >= MIN_LANCES else None
    pares, comparaveis = _comparar_vetores(_vetores_unitarios(conn, certame), TOL_VETOR)

    # (apurável?, disparou?) por screen — RD inapurável (perdedores idênticos → None) não conta
    # como apurável: melhor perder um screen que inventar um infinito.
    grade = {
        "cv_baixo": (cv is not None, cv is not None and cv < CV_BAIXO),
        "rd_alto": (rd is not None, rd is not None and rd >= RD_ALTO),
        "skew_negativa": (skew is not None, skew is not None and skew < SKEW_NEG),
        "cobertura": (cobertura is not None, bool(cobertura)),
        "planilha_compartilhada": (comparaveis > 0, len(pares) > 0),
    }
    apuraveis = sum(1 for ap, _ in grade.values() if ap)
    flags = [nome for nome, (_, disp) in grade.items() if disp]
    bruto = len(flags) / apuraveis if apuraveis else 0.0
    score = bruto if len(flags) >= 2 else min(bruto, 0.5)  # REGRA: nunca 1 screen só acima de 0.5
    return {
        "certame": certame,
        "n_lances": n,
        "cv": round(cv, 4) if cv is not None else None,
        "rd": round(rd, 4) if rd is not None else None,
        "skew": round(skew, 4) if skew is not None else None,
        "cobertura": cobertura,
        "planilha_compartilhada": pares,
        "flags": flags,
        "score_conluio": round(score, 3),
        "confianca": round(apuraveis / N_SCREENS, 2),
        "_nota": ("Screens estatísticos = INDÍCIO a verificar, nunca prova (presunção de legitimidade). "
                  "Regra OCDE: ≥2 concordantes p/ suspeita; thresholds iniciais dos benchmarks "
                  "(BENCHMARKS-EXTERNOS §3.3) — calibração local pendente."),
    }
