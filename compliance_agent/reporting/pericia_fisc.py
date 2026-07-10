# -*- coding: utf-8 -*-
"""Montagem de contexto Kroll p/ relatórios de perícia (emendas + gastos PCRJ).

Compartilhado pelos runners tools/emendas_pericia.py e tools/pcrj_pericia_gastos.py:
achados (lista dos detectores) → ctx do reporting.render_html.gerar_pdf.
"""
from __future__ import annotations

import html as _html
from datetime import datetime


def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def tabela_html(rows: list[dict], cols: list[tuple[str, str]]) -> str:
    """cols = [(chave, cabeçalho)]."""
    th = "".join(f"<th>{_esc(h)}</th>" for _, h in cols)
    trs = []
    for r in rows:
        tds = "".join(f"<td>{_esc(r.get(k))}</td>" for k, _ in cols)
        trs.append(f"<tr>{tds}</tr>")
    return f"<table><tr>{th}</tr>{''.join(trs)}</table>"


def _faixa(score: int) -> str:
    return ("EXTREMO" if score >= 90 else "ALTO" if score >= 70
            else "MÉDIO" if score >= 50 else "BAIXO")


_RISCO_ICONE = [(8, "🔴"), (5, "🟡"), (0, "🟢")]


def _icone(risco: int) -> str:
    return next(i for lim, i in _RISCO_ICONE if risco >= lim)


def ctx_de_achados(titulo: str, subtitulo: str, resultado: dict,
                   fontes: list[dict], panorama_html: str = "",
                   max_por_detector: int = 25) -> dict:
    """resultado = {"achados", "cobertura"} de rodar_todas()."""
    achados, cobertura = resultado["achados"], resultado["cobertura"]
    score = min(100, max((a["risco"] for a in achados), default=0) * 10)
    contagem: dict[str, int] = {}
    for a in achados:
        contagem[a["detector"]] = contagem.get(a["detector"], 0) + 1

    secoes = []
    resumo = (
        f"<p><b>{len(achados)}</b> achado(s) no total — "
        f"{sum(1 for a in achados if a['risco'] >= 8)} de risco alto (≥8), "
        f"{sum(1 for a in achados if 5 <= a['risco'] < 8)} médio (5–7), "
        f"{sum(1 for a in achados if a['risco'] < 5)} baixo (&lt;5). "
        f"Escala de risco: 0–10, explícita em cada achado; <b>indício ≠ acusação</b>.</p>")
    resumo += tabela_html(
        [{"detector": d, "n": n} for d, n in sorted(contagem.items())],
        [("detector", "Detector"), ("n", "Achados")])
    if panorama_html:
        resumo += panorama_html
    secoes.append({"titulo": "1. Sumário executivo", "html": resumo})

    def _ordem(det: str):
        dig = "".join(c for c in det.split("_")[0] if c.isdigit())
        return (int(dig) if dig else 99, det)

    for i, det in enumerate(sorted({a["detector"] for a in achados}, key=_ordem), start=2):
        do_det = [a for a in achados if a["detector"] == det][:max_por_detector]
        linhas = [{"risco": f"{_icone(a['risco'])} {a['risco']}/10",
                   "titulo": a["titulo"], "descricao": a["descricao"]} for a in do_det]
        corte = ""
        total_det = contagem[det]
        if total_det > max_por_detector:
            corte = (f"<p class='nota'>Exibindo {max_por_detector} de {total_det} — "
                     f"lista completa no XLSX de apoio (sem truncamento silencioso).</p>")
        secoes.append({"titulo": f"{i}. {det}",
                       "html": tabela_html(linhas, [("risco", "Risco"),
                                                    ("titulo", "Achado"),
                                                    ("descricao", "Descrição e fontes")]) + corte})

    cob = tabela_html([{"d": d, "s": s} for d, s in cobertura.items()],
                      [("d", "Detector"), ("s", "Estado")])
    secoes.append({"titulo": f"{len(secoes) + 1}. Cobertura da perícia",
                   "html": cob + "<p class='nota'>Detector com ERRO = INDISPONÍVEL "
                                 "(não significa zero achados).</p>"})
    secoes.append({
        "titulo": f"{len(secoes) + 1}. Metodologia e referências normativas",
        "html": ("<p>Detectores determinísticos (código auditável, sem LLM) sobre fontes "
                 "públicas primárias. Empenho ≠ liquidação ≠ pagamento (só a ordem "
                 "bancária/OB é dinheiro que saiu). Match por NOME normalizado é indício "
                 "fraco (homônimo possível) e vem sinalizado; match por CPF/CNPJ é forte. "
                 "CPF sempre mascarado (LGPD).</p>"
                 "<p><b>Referências:</b> CF art. 166 §§9º-20 e art. 166-A (transferências "
                 "especiais); Lei 14.133/2021 arts. 75 (dispensa), 94 (publicação no PNCP) "
                 "e 125 (limite de aditivos); LC 131/2009 (transparência); "
                 "Lei 12.527/2011 (LAI); LGPD (Lei 13.709/2018).</p>")})

    top = [a["titulo"][:60] for a in achados[:4] if a["risco"] >= 7]
    return {
        "titulo": titulo,
        "subtitulo": subtitulo,
        "score": score, "faixa": _faixa(score),
        "top_flags": top,
        "secoes": secoes,
        "proveniencia": fontes,
        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "_dados": {"achados": achados, "cobertura": cobertura},
    }
