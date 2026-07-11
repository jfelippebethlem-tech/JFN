# -*- coding: utf-8 -*-
"""A câmara delibera → parecer estilo Tribunal de Contas.

Para cada achado relevante (risco ≥ 5), roda o enxame-núcleo com RAG
(fundamentação) e MEMÓRIA (não re-acusar refutado); a conclusão agrega os
vereditos. Saída nas 4 seções clássicas: relatório, fundamentação, conclusão, voto.
"""
from __future__ import annotations

import json

from compliance_agent.enxame import memoria, orquestrador

LIMIAR_DELIBERA = 5


def _brl(v) -> str:
    return f"{(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _rag(pergunta: str) -> str:
    try:
        from tools.hermes_rag import consultar
        hits = consultar(pergunta, k=3)
        return " | ".join((h.get("texto") or h.get("trecho") or "")[:180] for h in hits[:2]) if hits else ""
    except Exception:
        return ""


def _deliberar_achado(con, dossie: dict, achado: dict, gerar=None) -> dict:
    """Monta o dossiê-da-lente (com RAG+memória) e chama o enxame."""
    forn = (dossie.get("contrato") or {}).get("fornecedor_documento") or ""
    dl = {
        "objeto": (dossie.get("contrato") or {}).get("objeto", ""),
        "clausula": {"subtipo": achado["dimensao"], "texto": achado["texto"],
                     "sumula": achado.get("norma")},
        "irmaos_sem_clausula": [],
        "vencedor_doc": forn,
        "sinais_beneficiario": dossie.get("sinais_fornecedor") or [],
        "rag_ctx": _rag(f"{achado['dimensao']} {achado.get('norma', '')} Lei 14.133"),
        "memoria_ctx": memoria.contexto_memoria(con, f"contrato_{achado['dimensao']}", forn),
    }
    return orquestrador.avaliar(dl, gerar=gerar)


def _conclusao(score: int) -> str:
    if score >= 7:
        return "indício de irregularidade"
    if score >= 4:
        return "diligência"
    return "regular"


def _voto(conclusao: str, dims: list[str]) -> str:
    if conclusao == "indício de irregularidade":
        return ("Pela representação ao TCM-RJ e/ou instauração de tomada de contas, dado o(s) "
                f"indício(s) em {', '.join(dims)}. Presunção de legitimidade; indício ≠ acusação.")
    if conclusao == "diligência":
        return ("Pela BAIXA EM DILIGÊNCIA: requisitar ao órgão a justificativa técnica e os "
                f"documentos de suporte quanto a {', '.join(dims)} antes de qualquer juízo.")
    return "Pela regularidade, sem prejuízo de reexame se sobrevierem fatos novos."


def deliberar(con, dossie: dict, achados: list[dict], gerar=None) -> dict:
    c = dossie.get("contrato", {})
    relevantes = [a for a in achados if a["risco"] >= LIMIAR_DELIBERA]
    dimensoes = []
    score = 0
    for a in relevantes:
        v = _deliberar_achado(con, dossie, a, gerar=gerar)
        dimensoes.append({**a, "veredito": v.get("veredito"), "score_enxame": v.get("score_final"),
                          "votos": v.get("votos", {})})
        score = max(score, v.get("score_final") or 0)
    conclusao = _conclusao(score)
    p = dossie.get("pagamentos", {})
    relatorio = {
        "controle": c.get("numero_controle_pncp"),
        "orgao": c.get("orgao_nome") or c.get("orgao_cnpj"),
        "fornecedor": f"{c.get('fornecedor_nome') or ''} ({c.get('fornecedor_documento') or ''})",
        "objeto": c.get("objeto"),
        "valor_inicial": f"R$ {_brl(c.get('valor_inicial'))}",
        "valor_global": f"R$ {_brl(c.get('valor_global'))}",
        "pago": f"R$ {_brl(p.get('pago'))}",
        "n_aditivos": len(dossie.get("aditivos", [])),
        "vigencia": f"{c.get('vigencia_ini') or '?'} a {c.get('vigencia_fim') or '?'}",
    }
    fundamentacao = [
        {"dimensao": d["dimensao"], "fatos": d["texto"], "norma": d["norma"],
         "veredito_enxame": d["veredito"], "score": d["score_enxame"],
         "jurisprudencia": _rag(f"{d['dimensao']} {d['norma']}")}
        for d in dimensoes]
    dims = [d["dimensao"] for d in dimensoes]
    return {
        "numero_controle_pncp": c.get("numero_controle_pncp"),
        "relatorio": relatorio, "fundamentacao": fundamentacao,
        "conclusao": conclusao, "score": score, "voto": _voto(conclusao, dims or ["—"]),
        "dimensoes": dims,
    }


def render_parecer_ctx(parecer: dict) -> dict:
    """ctx p/ reporting.render_html: as 4 seções como seções do relatório Kroll."""
    import html as _h
    r = parecer["relatorio"]
    rel_html = "<table>" + "".join(
        f"<tr><th>{_h.escape(k)}</th><td>{_h.escape(str(v))}</td></tr>" for k, v in r.items()) + "</table>"
    fund_html = ""
    for f in parecer["fundamentacao"]:
        fund_html += (f"<p><b>{_h.escape(f['dimensao'])}</b> — {_h.escape(f['fatos'])}<br>"
                      f"<i>Norma:</i> {_h.escape(f['norma'])} · <i>Enxame:</i> "
                      f"{_h.escape(str(f.get('veredito_enxame') or f.get('veredito')))} ({f.get('score', '?')}/10)"
                      + (f"<br><i>Jurisprudência:</i> {_h.escape(f['jurisprudencia'][:300])}" if f.get('jurisprudencia') else "")
                      + "</p>")
    faixa = {"indício de irregularidade": "ALTO", "diligência": "MÉDIO", "regular": "BAIXO"}[parecer["conclusao"]]
    secoes = [
        {"titulo": "I. Relatório", "html": rel_html},
        {"titulo": "II. Fundamentação", "html": fund_html or "<p>Sem dimensão relevante.</p>"},
        {"titulo": "III. Conclusão", "html": f"<p><b>{_h.escape(parecer['conclusao'].upper())}</b> "
                                             f"(score {parecer['score']}/10). Indício ≠ acusação; presunção de legitimidade.</p>"},
        {"titulo": "IV. Voto", "html": f"<p>{_h.escape(parecer['voto'])}</p>"},
    ]
    return {"titulo": f"Parecer Técnico — Contrato {parecer['numero_controle_pncp']}",
            "subtitulo": "Câmara de análise de contratos (Tribunal de Contas automatizado) · JFN",
            "score": parecer["score"] * 10, "faixa": faixa, "secoes": secoes,
            "classificacao": "CONFIDENCIAL — USO INTERNO", "_dados": parecer}


def gravar_e_aprender(con, parecer: dict) -> None:
    con.execute(
        """insert into contrato_parecer (numero_controle_pncp, conclusao, score, dimensoes_json, parecer_json)
           values (?,?,?,?,?)""",
        (parecer["numero_controle_pncp"], parecer["conclusao"], parecer["score"],
         json.dumps(parecer["dimensoes"], ensure_ascii=False),
         json.dumps(parecer, ensure_ascii=False, default=str)))
    con.commit()
    forn = ""
    for f in parecer.get("fundamentacao", []):
        memoria.registrar_veredito(con, f"contrato_{f['dimensao']}",
                                   parecer["relatorio"].get("fornecedor", "")[:60],
                                   parecer["conclusao"], parecer["score"])
