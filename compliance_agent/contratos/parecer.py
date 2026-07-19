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
        "empenhado": f"R$ {_brl(p.get('empenhado'))}",
        "liquidado": f"R$ {_brl(p.get('liquidado'))}",
        "pago": f"R$ {_brl(p.get('pago'))}",
        "n_aditivos": len(dossie.get("aditivos", [])),
        "vigencia": f"{c.get('vigencia_ini') or '?'} a {c.get('vigencia_fim') or '?'}",
    }
    # preserva votos/risco/proveniência por dimensão (antes descartados) + jurisprudência RAG
    fundamentacao = [
        {"dimensao": d["dimensao"], "fatos": d["texto"], "norma": d["norma"],
         "veredito_enxame": d["veredito"], "score": d["score_enxame"],
         "risco": d.get("risco"), "proveniencia": d.get("proveniencia"),
         "votos": d.get("votos", {}),
         "jurisprudencia": _rag(f"{d['dimensao']} {d['norma']}")}
        for d in dimensoes]
    dims = [d["dimensao"] for d in dimensoes]
    return {
        "numero_controle_pncp": c.get("numero_controle_pncp"),
        "relatorio": relatorio, "fundamentacao": fundamentacao,
        "conclusao": conclusao, "score": score, "voto": _voto(conclusao, dims or ["—"]),
        "dimensoes": dims,
        # dossiê preservado p/ as fichas ricas do parecer (aditivos/itens/sinais/pagamentos)
        "aditivos": dossie.get("aditivos", []),
        "itens": dossie.get("itens", []),
        "sinais_fornecedor": dossie.get("sinais_fornecedor", []),
        "pagamentos": p,
    }


_ROTULO_REL = {"controle": "Nº de controle PNCP", "orgao": "Órgão contratante", "fornecedor": "Fornecedor",
               "objeto": "Objeto", "valor_inicial": "Valor inicial", "valor_global": "Valor global (c/ aditivos)",
               "empenhado": "Empenhado", "liquidado": "Liquidado", "pago": "Pago (OB)",
               "n_aditivos": "Nº de aditivos", "vigencia": "Vigência"}


def _ficha_aditivos(aditivos: list) -> str:
    import html as _h
    if not aditivos:
        return "<p class='ind'>Sem termos aditivos registrados no PNCP.</p>"
    linhas = ""
    for a in aditivos:
        vac = a.get("valor_acrescido")
        vac_s = f"R$ {_brl(vac)}" if vac else "—"
        prazo = f"{a.get('prazo_aditado_dias')} dias" if a.get("prazo_aditado_dias") else "—"
        linhas += (f"<tr><td>{_h.escape(str(a.get('numero_termo') or a.get('sequencial_termo') or '—'))}</td>"
                   f"<td>{_h.escape((a.get('objeto') or '')[:180])}</td>"
                   f"<td>{vac_s}</td><td>R$ {_brl(a.get('valor_global'))}</td>"
                   f"<td>{prazo}</td><td>{_h.escape(str(a.get('vigencia_fim') or '—'))}</td>"
                   f"<td>{_h.escape(a.get('fundamento_legal') or '—')}</td></tr>")
    return ("<table><tr><th>Termo</th><th>Objeto</th><th>Acréscimo</th><th>Valor global</th>"
            f"<th>Prazo</th><th>Nova vigência</th><th>Fundamento legal</th></tr>{linhas}</table>")


def render_parecer_ctx(parecer: dict) -> dict:
    """ctx p/ reporting.render_html: peça TC completa — relatório, aditivos detalhados, fundamentação
    por dimensão COM o painel das 5 lentes, sinais do fornecedor, conclusão e voto."""
    import html as _h
    r = parecer["relatorio"]
    rel_html = "<table class='ident'>" + "".join(
        f"<tr><th class='k'>{_h.escape(_ROTULO_REL.get(k, k))}</th><td>{_h.escape(str(v))}</td></tr>"
        for k, v in r.items()) + "</table>"

    secoes = [
        {"titulo": "I. Relatório", "html": rel_html},
        {"titulo": "II. Termos aditivos", "html": _ficha_aditivos(parecer.get("aditivos", []))},
    ]

    # sinais do fornecedor (CEIS/emendas/rede) como bloco visível
    sinais = parecer.get("sinais_fornecedor") or []
    if sinais:
        lis = "".join(f"<li>{_h.escape(s)}</li>" for s in sinais)
        secoes.append({"titulo": "III. Sinais cruzados do fornecedor",
                       "html": f"<ul>{lis}</ul><p class='nota'>Sinais objetivos (cadastros públicos); indício ≠ acusação.</p>"})

    # cada dimensão deliberada vira uma FICHA de 7 seções (mesmo padrão-representação de
    # editais/emendas/pcrj — reporting.ficha7); o parecer segue com conclusão e voto próprios
    from compliance_agent.reporting import ficha7
    fund_parts = []
    for i, f in enumerate(parecer["fundamentacao"], 1):
        fund_parts.append(ficha7.ficha_html(i, {
            "titulo": f"{f['dimensao']} — contrato {parecer['numero_controle_pncp']}",
            "superficie": "contratos",
            "ident": [("Contrato (controle PNCP)", _h.escape(str(parecer["numero_controle_pncp"] or "—"))),
                      ("Órgão", _h.escape(str(r.get("orgao") or "—"))),
                      ("Fornecedor", _h.escape(str(r.get("fornecedor") or "—"))),
                      ("Dimensão do achado", _h.escape(f["dimensao"])),
                      ("Risco (funil determinístico)", f"{f.get('risco', '—')}/10")],
            "objeto_html": f"<p>{_h.escape(f['fatos'])}</p>",
            "comparativa_html": None,  # baseline = limiares nomeados de contratos/thoughts.py
            "fundamentacao_html": ficha7.fundamentacao_html(
                dispositivos=[f["norma"]] if f.get("norma") else None,
                rag=f.get("jurisprudencia") or ""),
            "votos": f.get("votos", {}),
            "score_colegiado": f.get("score"),
            "veredito": f.get("veredito_enxame"),
            "risco_det": f.get("risco") or 0,
            "beneficiario_html": (
                f"<p>Fornecedor do contrato: <b>{_h.escape(str(r.get('fornecedor') or '—'))}</b>.</p>"
                + (("<p><b>Sinais cruzados:</b> " + _h.escape("; ".join(map(str, sinais))) + ".</p>") if sinais else "")),
        }))
    n_fund = "IV" if sinais else "III"
    secoes.append({"titulo": f"{n_fund}. Fundamentação e parecer do colegiado",
                   "html": "".join(fund_parts) or "<p>Sem dimensão relevante deliberada (achados abaixo do limiar).</p>"})

    n_concl = "V" if sinais else "IV"
    n_voto = "VI" if sinais else "V"
    secoes.append({"titulo": f"{n_concl}. Conclusão",
                   "html": f"<p class='conclusao {'extremo' if parecer['score']>=7 else 'medio'}'>"
                           f"<b>{_h.escape(parecer['conclusao'].upper())}</b> (score {parecer['score']}/10). "
                           "Indício ≠ acusação; presunção de legitimidade dos atos administrativos.</p>"})
    secoes.append({"titulo": f"{n_voto}. Voto", "html": f"<p>{_h.escape(parecer['voto'])}</p>"})

    faixa = {"indício de irregularidade": "ALTO", "diligência": "MÉDIO", "regular": "BAIXO"}[parecer["conclusao"]]
    return {"titulo": f"Parecer Técnico — Contrato {parecer['numero_controle_pncp']}",
            "subtitulo": "Câmara de análise de contratos (Tribunal de Contas automatizado) · JFN",
            "metodologia": "Dossiê + 6 pensamentos determinísticos + colegiado de 5 lentes + RAG jurisprudência",
            "rotulo_score": "Gravidade do achado de maior escore",
            "score": parecer["score"] * 10, "faixa": faixa, "secoes": secoes,
            "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO", "_dados": parecer}


def gravar_e_aprender(con, parecer: dict) -> None:
    con.execute(
        """insert into contrato_parecer (numero_controle_pncp, conclusao, score, dimensoes_json, parecer_json)
           values (?,?,?,?,?)""",
        (parecer["numero_controle_pncp"], parecer["conclusao"], parecer["score"],
         json.dumps(parecer["dimensoes"], ensure_ascii=False),
         json.dumps(parecer, ensure_ascii=False, default=str)))
    con.commit()
    for f in parecer.get("fundamentacao", []):
        memoria.registrar_veredito(con, f"contrato_{f['dimensao']}",
                                   parecer["relatorio"].get("fornecedor", "")[:60],
                                   parecer["conclusao"], parecer["score"])
