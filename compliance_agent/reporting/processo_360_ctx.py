# -*- coding: utf-8 -*-
"""ctx de renderização do Avaliador de Processo 360 → reporting.render_html.gerar_pdf.

Sete seções no espírito da ficha7 (identificação → linha do tempo → achados → acatamento →
juízo por documento → honestidade da cobertura → conclusão/escalada). A seção de honestidade
é OBRIGATÓRIA: lacuna de captura nunca se apresenta como vício do processo.
"""
from __future__ import annotations

import html as _h

from compliance_agent.sei import fases

_GRAV_EMOJI = {"critica": "🔴", "alta": "🟠", "media": "🟡", "baixa": "🟢"}


def _vereditos_persistidos(numero_sei: str, db=None) -> dict | None:
    """Vereditos por documento já pagos (doc_veredito) — o PDF os mostra mesmo sem --com-llm.

    UM documento, UM juízo. `doc_veredito` acumula uma linha por rubrica: em 2026-08-02, 50 dos
    57 processos tinham veredito de 2 ou 3 rubricas (407 pares numero_sei/doc_i repetidos). Sem
    filtro, o entregável repetia o mesmo despacho e exibia as rubricas v1/v2 — que o próprio
    `doc_juizo` declara erradas. Fica a avaliação da rubrica MAIS NOVA (numérica: v10 > v9) e,
    no empate, a mais recente.
    """
    import json
    import sqlite3
    from pathlib import Path
    db = Path(db) if db else Path(__file__).resolve().parents[2] / "data" / "compliance.db"
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "select veredito_json from doc_veredito d where numero_sei=? and d.id = ("
                "  select x.id from doc_veredito x"
                "   where x.numero_sei = d.numero_sei and x.doc_i = d.doc_i"
                "   order by cast(x.rubrica_versao as integer) desc, x.avaliado_em desc, x.id desc"
                "   limit 1) order by d.doc_i",
                (numero_sei,)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    if not rows:
        return None
    return {"vereditos": [json.loads(r[0]) for r in rows], "fonte": "doc_veredito (cache)"}


def _tab(linhas: list[tuple[str, str]]) -> str:
    return "<table class='ident'>" + "".join(
        f"<tr><th class='k'>{_h.escape(k)}</th><td>{v}</td></tr>" for k, v in linhas) + "</table>"


def render_processo_ctx(out: dict) -> dict:
    ac = out.get("acatamento") or {}
    suf = ac.get("suficiencia") or {}
    esc = out.get("escalada") or {}
    cob = out.get("cobertura") or {}

    secoes = [{"titulo": "I. Identificação do processo", "html": _tab([
        ("Processo (SEI)", _h.escape(out["numero_sei"])),
        ("Modalidade declarada", _h.escape(out.get("modalidade") or "—")),
        ("Ato principal aferido", _h.escape(out.get("ato_principal") or "—")),
        ("CNPJ do maior favorecido", _h.escape(out.get("cnpj_vencedor") or "não identificado")),
        ("Versão do avaliador", _h.escape(out.get("versao", ""))),
    ])}]

    fases_html = "<table><tr><th>Fase</th><th>Documentos</th></tr>" + "".join(
        f"<tr><td>{_h.escape(fases.FASES.get(f, f))}</td><td>{n}</td></tr>"
        for f, n in (out.get("fases") or {}).items()) + "</table>"
    cadeia = out.get("cadeia") or {}
    tem_a1 = any(str(a.get("codigo") or "").startswith("A1") for a in out.get("achados") or [])
    if tem_a1:
        # sem contradição aparente: a cadeia por data pode sair "verde" enquanto a perícia A1
        # (por posição na árvore) aponta a inversão — o leitor vê UMA mensagem coerente
        fases_html += ("<p class='nota'>Ordem dos marcos: <b>inversão apontada pela perícia A1</b> "
                       "(contrato antes do parecer — ver seção III); o relógio da cadeia por data "
                       "não a contradiz, apenas não a alcança.</p>")
    else:
        fases_html += (f"<p class='nota'>Ordem dos marcos: <b>{_h.escape(str(cadeia.get('grau', '—')))}</b> — "
                       f"{_h.escape(str(cadeia.get('resumo') or ''))[:400]}</p>")
    secoes.append({"titulo": "II. Linha do tempo por fase", "html": fases_html})

    if out.get("achados"):
        linhas = "".join(
            f"<tr><td>{_GRAV_EMOJI.get(str(a.get('gravidade')), '·')} "
            f"{_h.escape(str(a.get('gravidade') or a.get('grau') or '—'))}</td>"
            f"<td>{_h.escape(str(a.get('origem')))}</td>"
            f"<td>{_h.escape(str(a.get('diz') or ''))[:400]}</td></tr>"
            for a in out["achados"])
        ach_html = f"<table><tr><th>Gravidade</th><th>Régua</th><th>Achado</th></tr>{linhas}</table>"
    else:
        ach_html = "<p>Nenhum achado nas réguas determinísticas.</p>"
    secoes.append({"titulo": "III. Achados (réguas determinísticas)", "html": ach_html})

    secoes.append({"titulo": "IV. Pareceres — acatamento e suficiência do emissor", "html": _tab([
        ("Acatamento (art. 53 / LINDB art. 22)", _h.escape(str(ac.get("veredito") or "—"))),
        ("Suficiência do emissor", _h.escape(
            f"{suf.get('veredito', '—')} — emissores: {', '.join(suf.get('emissores') or []) or '—'} "
            f"(máx nível {suf.get('max_nivel', '—')} / exigido {suf.get('exigido', '—')} "
            f"para o ato '{suf.get('ato', '—')}')")),
    ]) + f"<p class='nota'>{_h.escape(str(ac.get('leitura') or ''))[:500]}</p>"})

    llm = out.get("llm")
    if not (isinstance(llm, dict) and llm.get("vereditos")):
        llm = _vereditos_persistidos(out["numero_sei"]) or llm
    if isinstance(llm, dict) and llm.get("vereditos"):
        linhas = "".join(
            f"<tr><td>{_h.escape(str(v.get('tipo')))}</td>"
            f"<td>{v.get('escala') if v.get('escala') is not None else '—'}</td>"
            f"<td>{_h.escape(((v.get('grau') or {}).get('grau')) or '—')}</td>"
            f"<td>{_h.escape(str(v.get('trecho_literal') or v.get('aviso') or ''))[:220]}</td></tr>"
            for v in llm["vereditos"])
        secoes.append({"titulo": "V. Juízo por documento (rubrica fechada; grau máximo C)",
                       "html": "<table><tr><th>Tipo</th><th>Escala</th><th>Grau</th>"
                               f"<th>Trecho literal / aviso</th></tr>{linhas}</table>"
                               "<p class='nota'>Escala: 1 regular · 2 frágil · 3 viciado. Juízo de IA "
                               "sem corroboração determinística nunca fundamenta peça (teto C).</p>"})

    lp, lc = out.get("lacunas_processo") or [], out.get("lacunas_captura") or []
    hon = ""
    if lp:
        hon += ("<p><b>Lacunas do PROCESSO</b> (captura íntegra — a ausência pesa contra os autos):</p><ul>"
                + "".join(f"<li>{_GRAV_EMOJI.get(str(x.get('gravidade')), '·')} "
                          f"{_h.escape(str(x.get('falta')))}</li>" for x in lp) + "</ul>")
    if lc:
        hon += ("<p><b>Lacunas de CAPTURA</b> (trabalho NOSSO — não capturado ≠ inexistente):</p><ul>"
                + "".join(f"<li>{_h.escape(str(x.get('falta')))}</li>" for x in lc) + "</ul>")
    hon += (f"<p class='nota'>Cobertura: captura íntegra = <b>{cob.get('captura_integra')}</b> · "
            f"{len(cob.get('detectores_rodados') or [])} régua(s) rodada(s) · indisponíveis: "
            f"{_h.escape('; '.join(cob.get('indisponiveis') or []) or 'nenhum')[:400]}. "
            "INDISPONÍVEL ≠ 0.</p>")
    secoes.append({"titulo": "VI. Honestidade da cobertura (lacunas e indisponibilidades)", "html": hon})

    sv = out.get("matriz_sv") or {}
    secoes.append({"titulo": "VII. Conclusão e escalada", "html": _tab([
        ("Score do processo (fila de apuração, não veredito)",
         f"{out.get('score100')}/100 — faixa {out.get('faixa')}"),
        ("Grau probatório", _h.escape(f"{out['grau']['grau']} — {out['grau'].get('motivo', '')}")),
        ("Matriz S×V", f"S{sv.get('severidade')} × V{sv.get('verossimilhanca')} = {sv.get('produto')}"),
        ("Peça recomendada", _h.escape(str(esc.get("peca") or esc.get("acao") or "—"))),
    ]) + "<p class='conclusao'>Indício ≠ acusação; presume-se a legitimidade dos atos administrativos.</p>"})

    # cartão de capa: destaques = os achados mais graves (o template render_html espera top_flags;
    # vazio deixava "Destaques:" órfão no PDF — teste-como-humano 2026-08-01)
    ordem_grav = {"critica": 0, "alto": 1, "alta": 1, "media": 2, "medio": 2}
    top_flags = [str(a.get("diz") or "")[:70] for a in sorted(
        out.get("achados") or [], key=lambda a: ordem_grav.get(str(a.get("gravidade") or a.get("grau")), 9))][:3]
    return {"top_flags": top_flags,
            "titulo": f"Avaliação 360 — Processo {out['numero_sei']}",
            "subtitulo": "O processo como um todo: cada fase e cada despacho que importam · JFN",
            "metodologia": ("manifesto normalizado + fases/lacunas + cadeia de marcos + perícia A1-A5 "
                            "+ detectores P/E/J/C/X + acatamento com suficiência do emissor + "
                            "score de convergência (spec §7.2) + rubricas fechadas por documento"),
            "rotulo_score": "Convergência de indícios do processo",
            "score": out.get("score100", 0), "faixa": out.get("faixa", "BAIXO"),
            "secoes": secoes, "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO", "_dados": out}
