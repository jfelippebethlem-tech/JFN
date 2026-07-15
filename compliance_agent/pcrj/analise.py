# -*- coding: utf-8 -*-
"""Integração da captação municipal aos motores de análise JÁ existentes.

Este é o elo que o dono pediu: o que se capta da Prefeitura (edital/processo/ata,
vindo do D.O. Rio ou dos PDFs da CCPAR) tem que ser analisado pelos mesmos motores
que já operam sobre o Estado — para aprender processos administrativos, licitações,
hipóteses de direcionamento e crimes licitatórios.

Dado o TEXTO de um edital + metadados, roda em cima dele:
  (i)   E1–E7 (cláusula-a-cláusula)   → detectores/coletor_edital + detectores.rodar_edital
  (ii)  direcionamento determinístico  → direcionamento_sinais.analisar_direcionamento_det
  (iii) parecer jurídico (red flags)   → lex_analise_conteudo.analisar_texto_edital
  (iv)  hipóteses de fraude/crime      → knowledge.pattern_engine.analisar_contexto_completo

Determinístico por padrão (``usar_llm=False``): sem custo de API, VM-safe, offline.
Honestidade preservada: cada motor devolve ``nao_avaliavel``/``indeterminado`` quando
falta dado — nunca 0; indício ≠ acusação.
"""
from __future__ import annotations

from typing import Optional

from ..detectores import rodar_edital
from ..detectores.coletor_edital import montar_ctx_de_sei
from ..direcionamento_sinais import analisar_direcionamento_det
from ..lex_analise_conteudo import analisar_texto_edital
from ..knowledge.pattern_engine import analisar_contexto_completo


def montar_leitura(texto: str, numero: str = "", *, valor: Optional[float] = None,
                   doc_titulo: str = "Edital", url: str = "") -> dict:
    """Embrulha texto avulso no formato ``leitura`` que os motores SEI consomem."""
    return {
        "numero": numero, "texto": "",
        "documentos": [{"url": url}] if url else [],
        "conteudo_documentos": [{"doc": doc_titulo, "conteudo": texto}],
        "valores": [f"R$ {valor:.2f}"] if valor else [],
        "cnpjs": [],
    }


def _grau_para_score(grau: str) -> float:
    return {"vermelho": 0.85, "amarelo": 0.5, "verde": 0.1}.get(grau, 0.0)


def analisar_edital(texto: str, *, numero: str = "", orgao: str = "",
                    modalidade: str = "", valor: Optional[float] = None,
                    objeto: str = "", ata: str = "", usar_llm: bool = False) -> dict:
    """Roda os 4 motores sobre o texto de um edital municipal e consolida.

    Retorna ``{numero, orgao, valor, detectores, direcionamento, lex, fraude, resumo}``.
    Cada motor é tolerante a dado faltante (não inventa). Nunca levanta por edital ruim:
    isola falhas de motor em ``{"erro": ...}`` para não derrubar os outros.
    """
    resultado: dict = {"numero": numero, "orgao": orgao, "valor": valor, "objeto": objeto}

    # (i) E1–E7 cláusula-a-cláusula
    try:
        leitura = montar_leitura(texto, numero, valor=valor)
        ctx = montar_ctx_de_sei(leitura, usar_llm=usar_llm)
        dets = rodar_edital(numero or "municipal", contexto=ctx)
        dl = [d.to_dict() for d in dets]
        resultado["detectores"] = {
            "todos": dl,
            "confirmados": [d for d in dl if d.get("status") == "confirmado"],
            "n_clausulas": len(ctx.get("clausulas_edital", [])),
        }
    except Exception as e:  # motor não pode derrubar a captação
        resultado["detectores"] = {"erro": f"{type(e).__name__}: {e}"}

    # (ii) direcionamento determinístico
    try:
        combinado = texto + (("\n\n" + ata) if ata else "")
        resultado["direcionamento"] = analisar_direcionamento_det(combinado)
    except Exception as e:
        resultado["direcionamento"] = {"erro": f"{type(e).__name__}: {e}"}

    # (iii) parecer jurídico Lex (red flags sobre o texto)
    try:
        resultado["lex"] = analisar_texto_edital(texto, numero=numero)
    except Exception as e:
        resultado["lex"] = {"erro": f"{type(e).__name__}: {e}"}

    # (iv) hipóteses de fraude/crime licitatório
    try:
        resultado["fraude"] = analisar_contexto_completo({
            "objeto": objeto, "orgao": orgao, "modalidade": modalidade,
            "valor": valor, "texto": texto,
        })
    except Exception as e:
        resultado["fraude"] = {"erro": f"{type(e).__name__}: {e}"}

    resultado["resumo"] = _consolidar(resultado)
    return resultado


def _consolidar(r: dict) -> dict:
    """Agrega os 4 motores num veredito de triagem (indício, não acusação)."""
    scores, sinais = [], []
    d = r.get("direcionamento", {})
    if isinstance(d, dict) and d.get("dados_suficientes"):
        scores.append(_grau_para_score(d.get("grau_det", "")))
        if d.get("cascata"):
            sinais.append("cascata de inabilitações")
        for c in d.get("clausulas", [])[:5]:
            sinais.append(f"cláusula restritiva: {c.get('tipo')}")
    det = r.get("detectores", {})
    if isinstance(det, dict) and det.get("confirmados"):
        for c in det["confirmados"]:
            scores.append(c.get("score", 0.0))
            sinais.append(f"detector {c.get('detector')}")
    fr = r.get("fraude", {})
    if isinstance(fr, dict) and fr.get("padroes_identificados"):
        for p in fr["padroes_identificados"][:5]:
            scores.append(p.get("score", 0.0))
            sinais.append(f"hipótese: {p.get('pattern_id')}")
    lex = r.get("lex", {})
    if isinstance(lex, dict):
        for a in lex.get("achados", [])[:5]:
            sinais.append(f"Lex {a.get('rf')}")

    score = max(scores) if scores else 0.0
    faixa = "🔴 alto" if score >= 0.7 else "🟡 médio" if score >= 0.35 else "🟢 baixo"
    return {
        "score": round(score, 2), "faixa": faixa,
        "n_sinais": len(sinais), "sinais": sinais[:20],
        "ressalva": "Triagem por indícios determinísticos; indício ≠ acusação. "
                    "Campo ausente ⇒ não-avaliável (nunca 0).",
    }
