"""
Motor de reconhecimento de padrões de corrupção.

Compara qualquer contexto (contrato, alerta, processo SEI, publicação DOERJ)
contra a base de casos históricos e padrões de fraude conhecidos.

Retorna um score de similaridade + casos associados — sem custo de API Claude.
O resultado enriquece as análises do agente sem chamadas extras.
"""

from __future__ import annotations

import re
from typing import Any

from compliance_agent.knowledge.casos_rj import CASOS_RJ, CasoCorrupcao
from compliance_agent.knowledge.fraudes_licitacao import FRAUDES, FraudePattern, FRAUDES_POR_ID


# ── Pontuação por palavras-chave ──────────────────────────────────────────────

def _score_keywords(texto: str, keywords: list[str]) -> float:
    """
    Calcula fração de palavras-chave encontradas no texto.
    Retorna 0.0–1.0.
    """
    if not keywords or not texto:
        return 0.0
    texto_lower = texto.lower()
    hits = sum(1 for kw in keywords if kw.lower() in texto_lower)
    return hits / len(keywords)


# ── Match de padrões de fraude ────────────────────────────────────────────────

def match_patterns(contexto: dict[str, Any], min_score: float = 0.15) -> list[dict]:
    """
    Verifica um contexto contra todos os padrões de fraude conhecidos.

    contexto: dict com qualquer combinação de:
      objeto, orgao, modalidade, valor, texto, tipo, palavras

    Retorna lista ordenada por score desc, com score >= min_score.
    """
    texto_busca = " ".join(str(v) for v in contexto.values() if v)

    resultados = []
    for fraude in FRAUDES:
        # Score por red_flags
        rf_score = _score_keywords(texto_busca, fraude.red_flags)
        # Score por como_detectar (indicadores textuais)
        det_score = _score_keywords(texto_busca, fraude.como_detectar)
        # Combina com peso maior para red_flags
        score = rf_score * 0.7 + det_score * 0.3

        if score >= min_score:
            resultados.append({
                "pattern_id":  fraude.id,
                "nome":        fraude.nome,
                "categoria":   fraude.categoria,
                "score":       round(score, 3),
                "risco":       fraude.risco,
                "descricao":   fraude.descricao[:200],
                "base_legal":  fraude.base_legal[:2],
                "casos_assoc": fraude.casos_associados,
            })

    return sorted(resultados, key=lambda x: x["score"], reverse=True)


# ── Match de casos históricos ─────────────────────────────────────────────────

def match_casos_historicos(contexto: dict[str, Any], min_score: float = 0.1) -> list[dict]:
    """
    Compara contexto com casos históricos do RJ.
    Útil para o agente dizer: "este padrão é similar ao caso X".
    """
    texto_busca = " ".join(str(v) for v in contexto.values() if v)

    resultados = []
    for caso in CASOS_RJ:
        kw_score  = _score_keywords(texto_busca, caso.palavras_chave)
        pat_score = _score_keywords(texto_busca, caso.padroes)
        org_score = _score_keywords(texto_busca, caso.orgaos_envolvidos)
        score = kw_score * 0.5 + pat_score * 0.3 + org_score * 0.2

        if score >= min_score:
            resultados.append({
                "caso_id":    caso.id,
                "nome":       caso.nome,
                "periodo":    caso.periodo,
                "status":     caso.status,
                "score":      round(score, 3),
                "valor_est":  caso.valor_estimado_reais,
                "descricao":  caso.descricao[:200],
            })

    return sorted(resultados, key=lambda x: x["score"], reverse=True)


# ── Análise completa de um alerta ou contrato ─────────────────────────────────

def analisar_contexto_completo(
    contexto: dict[str, Any],
    max_patterns: int = 5,
    max_casos: int = 3,
) -> dict:
    """
    Análise completa: padrões de fraude + casos históricos similares.

    Retorna:
      {
        "risco_geral": "alto" | "médio" | "baixo",
        "padroes_identificados": [...],
        "casos_similares": [...],
        "resumo": str,          # texto para incluir na resposta do agente
      }
    """
    padroes = match_patterns(contexto)[:max_patterns]
    casos   = match_casos_historicos(contexto)[:max_casos]

    # Calcula risco geral
    if padroes and padroes[0]["score"] >= 0.4 and padroes[0]["risco"] == "alto":
        risco_geral = "alto"
    elif padroes and padroes[0]["score"] >= 0.2:
        risco_geral = "médio"
    else:
        risco_geral = "baixo"

    # Monta resumo textual
    linhas = []
    if padroes:
        linhas.append("**Padrões de fraude detectados:**")
        for p in padroes[:3]:
            linhas.append(
                f"  • [{p['risco'].upper()}] {p['nome']} (score {p['score']:.0%}) — "
                f"{', '.join(p['base_legal'])}"
            )
    if casos:
        linhas.append("**Casos históricos similares:**")
        for c in casos[:2]:
            val = f"R$ {c['valor_est']:,.0f}" if c["valor_est"] else "valor não apurado"
            linhas.append(
                f"  • {c['nome']} ({c['periodo']}) — {c['status']} — {val}"
            )

    resumo = "\n".join(linhas) if linhas else "Nenhum padrão conhecido identificado."

    return {
        "risco_geral":            risco_geral,
        "padroes_identificados":  padroes,
        "casos_similares":        casos,
        "resumo":                 resumo,
    }


# ── Enriquecedor de alerta ────────────────────────────────────────────────────

def enriquecer_alerta(alerta_dict: dict) -> dict:
    """
    Recebe um dict de alerta e adiciona contexto de padrões conhecidos.
    Pode ser chamado após qualquer alerta ser gerado, sem custo de API.
    """
    contexto = {
        "titulo":    alerta_dict.get("titulo", ""),
        "descricao": alerta_dict.get("descricao", ""),
        "tipo":      alerta_dict.get("tipo", ""),
    }
    analise = analisar_contexto_completo(contexto, max_patterns=3, max_casos=2)
    return {
        **alerta_dict,
        "padroes_conhecidos": analise["padroes_identificados"],
        "casos_similares":    analise["casos_similares"],
        "risco_calculado":    analise["risco_geral"],
        "contexto_historico": analise["resumo"],
    }
