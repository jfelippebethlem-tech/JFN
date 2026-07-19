# -*- coding: utf-8 -*-
"""Montador RICO de perícia (emendas + gastos PCRJ) — substitui o genérico `ctx_de_achados`.

Cada achado de detector determinístico (D1–D10) vira uma FICHA de fiscalização, no lugar de
uma linha de tabela título+descrição. A ficha traz:

    • Identificação do alvo (favorecido/credor/autor + documento)
    • A EVIDÊNCIA estruturada (o dict `evidencias` — que antes só ia ao XLSX) tabelada e legível
      (valores em R$, percentuais, sinais de fachada com peso/detalhe, contratos-membros do fracionamento…)
    • A DESCRIÇÃO íntegra do achado (sem truncar)

Cada SEÇÃO-detector abre com a fundamentação jurídica comum (dispositivos legais + acórdão/súmula
do TCU/TCE-RJ curados em knowledge.jurisprudencia). Filosofia: sem limite de páginas; o PDF carrega
tudo, o XLSX é apoio. Indício ≠ acusação; empenho ≠ liquidação ≠ pagamento; CPF mascarado (LGPD).
"""
from __future__ import annotations

import html as _html
from datetime import datetime

from compliance_agent.knowledge.jurisprudencia import buscar_acordaos

# ── metadados por detector: rótulo, o que detecta, irregularidade (p/ jurisprudência), dispositivos ──
# `evid` lista os campos do dict `evidencias` a exibir: (chave, rótulo, formato).
_DET_META: dict[str, dict] = {
    # ---- EMENDAS ----
    "d1_pix_impedida": {
        "rotulo": "D1 · Transferência especial (“PIX”) impedida ou sem execução regular",
        "detecta": "Emenda de transferência especial (art. 166-A da CF) com plano de trabalho impedido/rejeitado.",
        "irregularidade": "sem_publicacao_pncp",
        "dispositivos": ["CF art. 166-A e §§", "Portaria Interministerial de transferências especiais"],
        "evid": [("id_plano", "Plano de ação", "s"), ("situacao", "Situação", "s"), ("cnpj", "Beneficiário (CNPJ)", "doc")],
    },
    "d2_concentracao_autor": {
        "rotulo": "D2 · Concentração territorial da carteira de emendas do autor",
        "detecta": "Parcela desproporcional das emendas de um parlamentar destinada a um único ente/território.",
        "irregularidade": "concentracao",
        "dispositivos": ["CF art. 166 §§9º-20", "princípio da impessoalidade (CF art. 37)"],
        "evid": [("autor", "Autor", "s"), ("destino", "Destino", "s"),
                 ("share", "Concentração", "pct"), ("total_autor", "Total empenhado ao destino", "moeda")],
    },
    "d3_favorecido_sancionado": {
        "rotulo": "D3 · Favorecido sancionado (CEIS/CNEP)",
        "detecta": "Beneficiário de emenda inscrito em cadastro de sanção federal (impedimento de contratar).",
        "irregularidade": "empresa_sancionada",
        "dispositivos": ["Lei 14.133/2021 art. 14 e art. 156", "Lei 12.846/2013 (CNEP)"],
        "evid": [("cadastro", "Cadastro de sanção", "s"), ("doc", "Favorecido (doc.)", "doc"),
                 ("match_exato", "Correspondência exata (CPF/CNPJ)", "bool")],
    },
    "d4_favorecido_fantasma": {
        "rotulo": "D4 · Favorecido com sinais de empresa de fachada",
        "detecta": "Beneficiário com indicadores objetivos de inexistência de substância (capital, endereço, porte).",
        "irregularidade": "empresa_laranja",
        "dispositivos": ["Lei 14.133/2021 art. 337-F CP (fraude)", "art. 11 da Lei 8.429/92"],
        "evid": [("cnpj", "Favorecido (CNPJ)", "doc"), ("score", "Escore de fachada", "s"), ("sinais", "Sinais objetivos", "sinais")],
    },
    "d6_empenho_sem_pagamento": {
        "rotulo": "D6 · Empenho sem execução (anúncio sem entrega)",
        "detecta": "Emenda empenhada mas sem liquidação/pagamento — resto a pagar cancelado.",
        "irregularidade": "despesa_sem_dotacao",
        "dispositivos": ["Lei 4.320/64 arts. 58-64", "LRF (LC 101/2000)"],
        "evid": [("empenhado", "Empenhado", "moeda"), ("pago", "Pago (OB)", "moeda"),
                 ("resto_cancelado", "Resto a pagar cancelado", "moeda")],
    },
    # ---- PCRJ GASTOS ----
    "d7_fracionamento": {
        "rotulo": "D7 · Fracionamento de despesa",
        "detecta": "Sucessão de contratações do mesmo objeto/credor num intervalo curto, somando acima do teto de dispensa.",
        "irregularidade": "fracionamento",
        "dispositivos": ["Lei 14.133/2021 art. 75 §1º", "Lei 8.666/93 art. 23 §5º"],
        "evid": [("orgao", "Órgão (doc.)", "doc"), ("fornecedor", "Credor (doc.)", "doc"),
                 ("n_contratos", "Nº de contratações", "s"), ("soma", "Soma no período", "moeda"),
                 ("controles_pncp", "Contratos (controle PNCP)", "lista")],
    },
    "d9_socio_na_folha": {
        "rotulo": "D9 · Sócio de credor na folha do município",
        "detecta": "Sócio de empresa contratada com vínculo (ou homônimo) na folha de pessoal municipal.",
        "irregularidade": "conflito_interesse",
        "dispositivos": ["Lei 14.133/2021 art. 9º", "Lei 8.429/92 art. 11", "Súmula Vinculante 13"],
        "evid": [("socio", "Sócio", "s"), ("credor", "Credor (CNPJ)", "doc"),
                 ("lotacao", "Lotação na folha", "s"), ("match_tipo", "Tipo de correspondência", "s")],
    },
    "d10_rede_concorrentes": {
        "rotulo": "D10 · Acréscimo contratual acima do limite legal",
        "detecta": "Aditivo que eleva o valor do contrato além dos 25%/50% do art. 125.",
        "irregularidade": "superfaturamento",
        "dispositivos": ["Lei 14.133/2021 art. 125", "Lei 8.666/93 art. 65 §1º"],
        "evid": [("controle", "Contrato (controle PNCP)", "s"), ("pct_acrescimo", "Acréscimo", "pct_direto"),
                 ("subtipo", "Subtipo", "s")],
    },
}


def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def _moeda(v) -> str:
    try:
        return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return _esc(v)


def _fmt(valor, formato: str) -> str:
    if valor is None:
        return "<span class='ind'>—</span>"
    if formato == "moeda":
        return _moeda(valor)
    if formato == "pct":  # fração 0-1
        try:
            return f"{float(valor) * 100:.1f}%"
        except (TypeError, ValueError):
            return _esc(valor)
    if formato == "pct_direto":  # já em %
        try:
            return f"{float(valor):.1f}%"
        except (TypeError, ValueError):
            return _esc(valor)
    if formato == "bool":
        return "sim" if valor else "não"
    if formato == "doc":
        d = "".join(ch for ch in str(valor) if ch.isdigit())
        if len(d) == 14:
            return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
        if len(d) == 11:  # CPF mascarado (LGPD)
            return f"***.{d[3:6]}.{d[6:9]}-**"
        return _esc(valor)
    if formato == "lista":
        itens = valor if isinstance(valor, list) else [valor]
        lis = "".join(f"<li class='mono'>{_esc(x)}</li>" for x in itens)
        return f"<ul class='compact'>{lis}</ul>"
    if formato == "sinais":  # lista de {id, peso, detalhe}
        if not isinstance(valor, list):
            return _esc(valor)
        rows = "".join(
            f"<tr><td>{_esc(s.get('id'))}</td><td class='vc'>{_esc(s.get('peso'))}</td>"
            f"<td>{_esc(s.get('detalhe'))}</td></tr>" for s in valor)
        return ("<table class='sinais'><tr><th>Sinal</th><th>Peso</th><th>Detalhe</th></tr>"
                f"{rows}</table>")
    return _esc(valor)


def _tabela_evid(ev: dict, campos: list[tuple]) -> str:
    if not ev:
        return ""
    linhas = []
    for chave, rotulo, formato in campos:
        if chave in ev and ev[chave] is not None:
            linhas.append(f"<tr><th class='k'>{_esc(rotulo)}</th><td>{_fmt(ev[chave], formato)}</td></tr>")
    # campos extras não mapeados (transparência — nada fica escondido)
    mapeados = {c[0] for c in campos}
    for k, v in ev.items():
        if k not in mapeados and v not in (None, "", [], {}):
            linhas.append(f"<tr><th class='k'>{_esc(k)}</th><td>{_fmt(v, 'auto')}</td></tr>")
    return f"<table class='ident'>{''.join(linhas)}</table>" if linhas else ""


def _fundamentacao_html(meta: dict) -> str:
    disp = meta.get("dispositivos") or []
    partes = []
    if disp:
        partes.append(f"<p><b>Base normativa:</b> {_esc('; '.join(disp))}.</p>")
    acs = buscar_acordaos(tipo_irregularidade=meta.get("irregularidade", ""))[:2]
    for ac in acs:
        partes.append(f"<div class='acordao'><b>{_esc(ac.orgao)} — {_esc(ac.numero)}.</b> "
                      f"{_esc(ac.tema)}. <i>{_esc(ac.ementa)}</i></div>")
    return "".join(partes)


def _icone(risco: int) -> str:
    return "🔴" if risco >= 8 else "🟡" if risco >= 5 else "🟢"


def _ficha7_de_achado(n: int, a: dict, meta: dict, superficie: str) -> str:
    """Adaptador: achado de detector deliberado pelo colegiado → ficha de 7 seções (ficha7).
    Usado quando `deliberar_achados` anotou votos; sem votos, vale a ficha rica de sempre."""
    from compliance_agent.reporting import ficha7
    ev = a.get("evidencias") or {}
    alvo = ev.get("cnpj") or ev.get("doc") or ev.get("fornecedor") or ev.get("credor") or ""
    ident = [("Detector", _esc(meta.get("rotulo", a.get("detector", "")))),
             ("Alvo/documento", _fmt(alvo, "doc") if alvo else "<span class='ind'>não identificado</span>"),
             ("Gravidade (detector)", f"{a.get('risco', 0)}/10")]
    if a.get("codigo_emenda"):
        ident.append(("Código da emenda", _esc(a["codigo_emenda"])))
    beneficiario = None
    if alvo:
        sinais = ev.get("sinais") or []
        beneficiario = (f"<p>Beneficiário/alvo do achado: <b>{_fmt(alvo, 'doc')}</b>.</p>"
                        + (f"<p><b>Sinais objetivos:</b> {_esc('; '.join(map(str, sinais)))}.</p>" if sinais else ""))
    d = {
        "titulo": a.get("titulo", ""), "superficie": superficie,
        "ident": ident,
        "objeto_html": (f"<p>{_esc(a.get('descricao', ''))}</p>"
                        + _tabela_evid(ev, meta.get("evid", []))),
        "comparativa_html": None,  # detector determinístico: régua explícita, sem base de pares
        "fundamentacao_html": ficha7.fundamentacao_html(
            dispositivos=meta.get("dispositivos"), irregularidade=meta.get("irregularidade", "")),
        "votos": a.get("votos") or {},
        "score_colegiado": a.get("score_colegiado"),
        "veredito": a.get("veredito"),
        "risco_det": a.get("risco", 0),
        "beneficiario_html": beneficiario,
    }
    return ficha7.ficha_html(n, d)


def ctx_de_achados_rico(titulo: str, subtitulo: str, resultado: dict, fontes: list[dict],
                        panorama_html: str = "", classificacao: str = "CONFIDENCIAL — CONTROLE EXTERNO",
                        limiar_corpo: int = 5, superficie: str = "emendas") -> dict:
    """resultado = {"achados", "cobertura"}. Ficha rica por achado, agrupada por detector; achado
    DELIBERADO pelo colegiado (ficha7.deliberar_achados anotou votos) sai na ficha de 7 seções.

    limiar_corpo: risco mínimo p/ a ficha ir ao CORPO; abaixo, vai à tabela-anexo (todos comparecem)."""
    achados = resultado["achados"]
    cobertura = resultado.get("cobertura", {})
    score = min(100, max((a["risco"] for a in achados), default=0) * 10)

    quentes = [a for a in achados if a["risco"] >= limiar_corpo]
    cauda = [a for a in achados if a["risco"] < limiar_corpo]

    secoes = []

    # 1. Sumário executivo + índice
    contagem: dict[str, int] = {}
    for a in achados:
        contagem[a["detector"]] = contagem.get(a["detector"], 0) + 1
    resumo = [
        f"<p><b>{len(achados)}</b> indício(s) no total — "
        f"<b>{sum(1 for a in achados if a['risco'] >= 8)}</b> de gravidade alta (≥8), "
        f"<b>{sum(1 for a in achados if 5 <= a['risco'] < 8)}</b> média (5–7), "
        f"<b>{sum(1 for a in achados if a['risco'] < 5)}</b> baixa (&lt;5). "
        f"Escala 0–10, explícita em cada ficha. <b>Indício ≠ acusação.</b></p>"]
    idx = "".join(
        f"<tr><td>{_esc(_DET_META.get(d, {}).get('rotulo', d))}</td><td class='vc'>{n}</td></tr>"
        for d, n in sorted(contagem.items()))
    resumo.append("<table><tr><th>Detector</th><th>Indícios</th></tr>" + idx + "</table>")
    if panorama_html:
        resumo.append(panorama_html)
    secoes.append({"titulo": "1. Sumário executivo", "html": "".join(resumo)})

    # 2. Metodologia
    secoes.append({"titulo": "2. Metodologia e limites", "html": (
        "<p>Detectores <b>determinísticos</b> (código auditável, sem LLM) sobre fontes públicas primárias. "
        "<b>Empenho ≠ liquidação ≠ pagamento</b> — só a Ordem Bancária é dinheiro que saiu do erário. "
        "Correspondência por CPF/CNPJ é indício forte; por NOME é indício fraco (homônimo possível) e vem "
        "sinalizada. CPF de pessoa física é mascarado (LGPD). Cada indício traz a evidência que o sustenta "
        "e a base normativa; presume-se a legitimidade do ato até prova em contrário.</p>")})

    # 3..N. Uma seção por detector (fundamentação comum + fichas)
    def _ordem(det: str):
        dig = "".join(c for c in det.split("_")[0] if c.isdigit())
        return (int(dig) if dig else 99, det)

    # Ficha completa para os N mais graves de cada detector; o restante vira TABELA rica (todos
    # comparecem — nada some — mas o relatório fica navegável em vez de repetir centenas de fichas iguais).
    max_fichas = 15
    n_sec = 3
    for det in sorted({a["detector"] for a in quentes}, key=_ordem):
        meta = _DET_META.get(det, {"rotulo": det, "detecta": "", "evid": []})
        do_det = sorted([a for a in quentes if a["detector"] == det], key=lambda a: -a["risco"])
        cab = [f"<p class='det-desc'>{_esc(meta.get('detecta', ''))}</p>", _fundamentacao_html(meta)]
        com_ficha = do_det[:max_fichas]
        fichas = []
        for i, a in enumerate(com_ficha, 1):
            if a.get("votos") or a.get("score_colegiado") is not None:
                fichas.append(_ficha7_de_achado(i, a, meta, superficie))
                continue
            fichas.append("".join([
                "<div class='ficha'>",
                f"<h4>{_icone(a['risco'])} {_esc(a['titulo'])} — gravidade {a['risco']}/10</h4>",
                f"<p>{_esc(a['descricao'])}</p>",
                _tabela_evid(a.get("evidencias") or {}, meta.get("evid", [])),
                "</div>",
            ]))
        # o restante do detector: tabela rica (título + gravidade + descrição resumida), todos presentes
        resto = do_det[max_fichas:]
        tab_resto = ""
        if resto:
            linhas = "".join(
                f"<tr><td class='vc'>{_icone(a['risco'])} {a['risco']}/10</td>"
                f"<td>{_esc(a['titulo'])}</td><td>{_esc(a['descricao'][:220])}…</td></tr>" for a in resto)
            tab_resto = (f"<p class='sub'>Demais {len(resto)} indícios deste detector "
                         f"(ficha completa acima nos {len(com_ficha)} de maior gravidade; evidência integral no XLSX):</p>"
                         "<table><tr><th>Gravidade</th><th>Indício</th><th>Descrição</th></tr>"
                         f"{linhas}</table>")
        secoes.append({"titulo": f"{n_sec}. {meta['rotulo']} ({len(do_det)})",
                       "html": "".join(cab) + "".join(fichas) + tab_resto, "page_break": True})
        n_sec += 1

    # anexo: cauda (baixa gravidade) — todos, sem truncar
    if cauda:
        linhas = "".join(
            f"<tr><td>{_esc(_DET_META.get(a['detector'], {}).get('rotulo', a['detector'])[:40])}</td>"
            f"<td>{_esc(a['titulo'][:80])}</td><td class='vc'>{a['risco']}/10</td></tr>"
            for a in sorted(cauda, key=lambda a: -a["risco"]))
        secoes.append({"titulo": f"{n_sec}. Anexo — indícios de baixa gravidade ({len(cauda)})",
                       "html": ("<p class='nota'>Listados na íntegra; evidência completa por indício no XLSX de apoio.</p>"
                                "<table><tr><th>Detector</th><th>Indício</th><th>Gravidade</th></tr>"
                                f"{linhas}</table>"), "page_break": True})
        n_sec += 1

    # cobertura
    cob = "".join(f"<tr><td>{_esc(_DET_META.get(d, {}).get('rotulo', d))}</td><td>{_esc(s)}</td></tr>"
                  for d, s in cobertura.items())
    secoes.append({"titulo": f"{n_sec}. Cobertura da perícia", "html": (
        f"<table><tr><th>Detector</th><th>Estado</th></tr>{cob}</table>"
        "<p class='nota'>Detector com ERRO = INDISPONÍVEL (não significa zero indícios).</p>")})

    faixa = ("EXTREMO" if score >= 90 else "ALTO" if score >= 70 else "MÉDIO" if score >= 50 else "BAIXO")
    top = [f"{_DET_META.get(a['detector'], {}).get('rotulo', a['detector']).split('·')[-1].strip()[:30]}"
           for a in sorted(quentes, key=lambda a: -a["risco"])[:4]]

    return {
        "titulo": titulo, "subtitulo": subtitulo, "classificacao": classificacao,
        "metodologia": "Detectores determinísticos + jurisprudência TCU/TCE-RJ",
        "analista": "Controle Externo (automatizado)",
        "score": score, "faixa": faixa, "top_flags": top, "rotulo_score": "Gravidade do maior indício",
        "secoes": secoes, "proveniencia": fontes,
        "ressalva": ("Peça de diligência do controle externo: indícios para apuração, jamais acusação. "
                     "Empenho não é pagamento; presume-se a legitimidade dos atos administrativos. "
                     "Nenhum dado indisponível foi fabricado."),
        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "_dados": {"achados": achados, "cobertura": cobertura},
    }
