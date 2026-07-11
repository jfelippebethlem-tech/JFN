# -*- coding: utf-8 -*-
"""Relatório JURÍDICO de direcionamento de editais — montador DEDICADO (não o genérico).

Cada achado de direcionamento vira uma FICHA de fiscalização completa, no padrão de uma
representação ao Tribunal de Contas:

    I.   Identificação (órgão, modalidade, nº de controle PNCP, nº de processo, objeto, valor)
    II.  Cláusula restritiva (na ÍNTEGRA — sem truncar)
    III. Análise comparativa (peer-diff: quantos editais do mesmo objeto NÃO exigem)
    IV.  Fundamentação jurídica (súmula VERBATIM + acórdãos + dispositivos + teste finalístico)
    V.   Parecer do colegiado (as 5 lentes, cada uma com voto, justificativa e citação legal)
    VI.  Beneficiário (honesto: vínculo edital→contrato quando disponível)
    VII. Conclusão raciocinada

Filosofia (diretriz do dono 2026-07-11): SEM limite de páginas — o PDF carrega TODAS as
informações; o XLSX é apoio, não o único lugar da verdade. Indício ≠ acusação; nada
não-confirmado vira citação definitiva (o aviso `verificar_antes_de_citar` aparece na ficha).

Fonte: clausula_veredito (enxame) + edital_documento/edital_clausula + pcrj_licitacoes
(órgão/modalidade, JOIN 100%) + knowledge.jurisprudencia (súmulas/acórdãos curados).
"""
from __future__ import annotations

import html as _html
import json
import re
from datetime import datetime

from compliance_agent.editais.peer_diff import _SUBTIPO_PARA_TIPO_E7
from compliance_agent.knowledge.jurisprudencia import SUMULAS, fundamentar_clausula

_LENTES_ORDEM = ["proporcionalidade", "jurisprudencia", "competicao", "refutador", "beneficiario"]
_LENTE_ROTULO = {
    "proporcionalidade": "Proporcionalidade",
    "jurisprudencia": "Jurisprudência",
    "competicao": "Impacto na competição",
    "refutador": "Defesa do edital (refutador)",
    "beneficiario": "Beneficiário / captura",
}
_EIXO_ROTULO = {
    "habilitacao_tecnica": "Qualificação técnica",
    "habilitacao_econ_financeira": "Qualificação econômico-financeira",
    "condicao_participacao": "Condição de participação",
}


def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def _moeda(v) -> str:
    try:
        return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "—"


def _data_br(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "")).strftime("%d/%m/%Y")
    except (ValueError, AttributeError):
        return _esc(iso)[:10]


# ── nº de processo administrativo: o texto do edital cita em formatos variados ──
_RE_PROCESSO = [
    re.compile(r"[Pp]rocesso[^A-Za-z0-9]{0,6}(?:administrativo\s*)?n?[ºo°.]?\s*(SEI[-\s]?[\d./-]{6,})", re.I),
    re.compile(r"\b(SEI[-\s]?\d{2,}[.\s/-]\d{4,}[./-]\d{4})\b", re.I),
    re.compile(r"[Pp]rocesso[^A-Za-z0-9]{0,6}n?[ºo°.]?\s*([\d]{2,}[.\s/-]\d{3,}[./-]\d{4})"),
    re.compile(r"EDITAL\s+SIGA\s+(\d{4,})", re.I),
    re.compile(r"(?:PREG[ÃA]O|CONCORR[ÊE]NCIA|DISPENSA)[^\n]{0,40}?n?[ºo°.]?\s*([\d]{2,}/\d{4})", re.I),
]


def _num_processo(texto: str | None) -> str:
    t = texto or ""
    for rx in _RE_PROCESSO:
        m = rx.search(t)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


def _clausula_integra(texto_edital: str | None, clausula_txt: str, trecho_fonte: str | None) -> str:
    """Recupera a redação ÍNTEGRA da cláusula do texto do edital, ancorando pelo trecho detectado.

    O banco guarda a cláusula truncada em 400 chars; aqui expandimos a partir do edital completo
    (até o fim do parágrafo/item), para o leitor ver a exigência inteira, não um pedaço."""
    ancora = (trecho_fonte or clausula_txt or "").strip()
    edital = texto_edital or ""
    if not ancora or not edital:
        return clausula_txt or ""
    chave = ancora[:60]
    pos = edital.find(chave)
    if pos < 0:
        # tenta uma âncora menor (o trecho pode ter espaços normalizados diferentes)
        chave = re.sub(r"\s+", " ", ancora[:40])
        edital_norm = re.sub(r"\s+", " ", edital)
        pos = edital_norm.find(chave)
        if pos < 0:
            return clausula_txt or ""
        edital = edital_norm
    # do início da âncora até o fim do item (dois \n, ou ~700 chars, o que vier primeiro)
    resto = edital[pos:pos + 900]
    corte = re.search(r"\n\s*\n|\.\s+[0-9]+\.[0-9]", resto)
    trecho = resto[: corte.start()] if corte else resto
    trecho = re.sub(r"\s+", " ", trecho).strip()
    return trecho or clausula_txt or ""


def _fundamentacao(subtipo: str) -> dict:
    """Fundamentação jurídica do subtipo: tenta a chave canônica direta e o mapa curto→canônico."""
    fund = fundamentar_clausula(subtipo) or fundamentar_clausula(_SUBTIPO_PARA_TIPO_E7.get(subtipo, ""))
    return fund or {}


# especificação de produto (químico/físico) que o extrator antigo confundia com "índice contábil"
_RE_PRODUTO = re.compile(
    r"acidez|iodo|saponifica|refra[çc][ãa]o|viscosidade|granulometr|umidade|densidade|pureza|"
    r"per[óo]xido|refrat[óo]metr|brix|mg\s?koh|m2/l|g/l\b|princ[íi]pio\s+ativo|miligrama|"
    r"comprimido|c[áa]psula|ampola|frasco|dosagem", re.I)
_RE_CONTABIL = re.compile(r"liquidez|solv[êe]ncia|endividamento|patrim[ôo]nio\s+l[íi]quido|"
                          r"capital\s+(?:social|circulante)|[íi]ndice\s+de\s+liquidez", re.I)


def _falso_positivo(subtipo: str, clausula: str) -> str:
    """Retorna o motivo se o achado for provável falso positivo de CLASSIFICAÇÃO (não é cláusula de
    habilitação), ou '' se plausível. Guard barato p/ não liderar o relatório com ruído — o dado é do
    extrator antigo; a regex já foi corrigida na origem (coletor_edital), mas os vereditos gravados
    ainda carregam o erro até a próxima re-extração."""
    c = clausula or ""
    # índice contábil de habilitação SEMPRE cita liquidez/solvência/endividamento/patrimônio. Sem nenhum
    # desses termos, "índice" casou uma especificação de produto (acidez, princípio ativo, etc.) → falso positivo.
    if subtipo == "indices_contabeis" and not _RE_CONTABIL.search(c):
        alvo = "especificação de produto" if _RE_PRODUTO.search(c) else "texto sem índice econômico-financeiro"
        return f"classificado como índice contábil, mas a cláusula é {alvo} (sem liquidez/solvência/patrimônio)"
    return ""


def _enriquecer(con, v) -> dict:
    """Junta, para um registro de clausula_veredito, TODOS os dados da ficha (nada truncado)."""
    nc = v["numero_controle_pncp"]
    ed = con.execute("SELECT objeto, valor_estimado, texto FROM edital_documento WHERE numero_controle_pncp=?",
                     (nc,)).fetchone()
    lic = con.execute("SELECT orgao_nome, modalidade, valor_estimado, data_abertura, situacao, orgao_cnpj "
                      "FROM pcrj_licitacoes WHERE numero_controle_pncp=?", (nc,)).fetchone()
    cl = con.execute("SELECT eixo, subtipo, texto, trecho_fonte FROM edital_clausula WHERE id=?",
                     (v["clausula_id"],)).fetchone()
    cluster = con.execute("SELECT assinatura_objeto, membros_json, tamanho FROM edital_cluster WHERE id=?",
                          (v["cluster_id"],)).fetchone()

    subtipo = (cl["subtipo"] if cl else "") or ""
    texto_edital = ed["texto"] if ed else ""
    clausula_int = _clausula_integra(texto_edital, cl["texto"] if cl else "", cl["trecho_fonte"] if cl else "")
    membros = json.loads(cluster["membros_json"]) if cluster and cluster["membros_json"] else []

    # editais-pares (os que NÃO têm a cláusula) — mostra objeto+órgão de até 6, honesto sobre o total
    pares = []
    for m in membros:
        if m == nc:
            continue
        p = con.execute("SELECT e.objeto, l.orgao_nome FROM edital_documento e "
                        "LEFT JOIN pcrj_licitacoes l ON l.numero_controle_pncp=e.numero_controle_pncp "
                        "WHERE e.numero_controle_pncp=?", (m,)).fetchone()
        if p:
            pares.append({"controle": m, "objeto": (p["objeto"] or "")[:120], "orgao": p["orgao_nome"] or "—"})

    votos = {}
    try:
        votos = json.loads(v["votos_json"]) if v["votos_json"] else {}
    except (ValueError, TypeError):
        votos = {}

    valor = (lic["valor_estimado"] if lic and lic["valor_estimado"] else
             (ed["valor_estimado"] if ed and ed["valor_estimado"] else None))

    return {
        "controle_pncp": nc,
        "orgao": (lic["orgao_nome"] if lic and lic["orgao_nome"] else "—"),
        "orgao_cnpj": (lic["orgao_cnpj"] if lic else "") or "",
        "modalidade": (lic["modalidade"] if lic and lic["modalidade"] else "—"),
        "processo": _num_processo(texto_edital),
        "objeto": (ed["objeto"] if ed and ed["objeto"] else (cluster["assinatura_objeto"] if cluster else "—")),
        "valor": valor,
        "data_abertura": (lic["data_abertura"] if lic else None),
        "eixo": (cl["eixo"] if cl else "") or "",
        "subtipo": subtipo,
        "clausula": clausula_int,
        "raridade": v["raridade"],
        "forca_e7": v["forca_e7"],
        "sumula_curta": v["sumula"] or "",
        "n_grupo": (cluster["tamanho"] if cluster else len(membros)),
        "pares": pares,
        "fundamentacao": _fundamentacao(subtipo),
        "votos": votos,
        "score": v["score_final"],
        "veredito": v["veredito"],
    }


# ── render de uma ficha ──────────────────────────────────────────────────────

def _tabela_id(d: dict) -> str:
    linhas = [
        ("Órgão contratante", _esc(d["orgao"]) + (f" · CNPJ {_esc(d['orgao_cnpj'])}" if d["orgao_cnpj"] else "")),
        ("Modalidade", _esc(d["modalidade"])),
        ("Nº de controle PNCP", _esc(d["controle_pncp"])),
        ("Nº de processo", _esc(d["processo"]) if d["processo"] else "<span class='ind'>não localizado no texto</span>"),
        ("Objeto", _esc(d["objeto"])),
        ("Valor estimado", _moeda(d["valor"]) if d["valor"] else "<span class='ind'>orçamento sigiloso / não informado</span>"),
        ("Data de abertura", _data_br(d["data_abertura"])),
        ("Natureza da exigência", _esc(_EIXO_ROTULO.get(d["eixo"], d["eixo"] or "—")) + f" · <i>{_esc(d['subtipo'])}</i>"),
    ]
    trs = "".join(f"<tr><th class='k'>{k}</th><td>{v}</td></tr>" for k, v in linhas)
    return f"<table class='ident'>{trs}</table>"


def _bloco_peerdiff(d: dict) -> str:
    pct = int(round((d["raridade"] or 0) * 100))
    html = [
        f"<p>No agrupamento de <b>{d['n_grupo']} editais</b> de objeto semelhante, "
        f"<b>{pct}%</b> dos pares <b>não</b> impõem esta exigência — a cláusula é uma "
        f"<b>anomalia relativa ao grupo</b> (raridade {d['raridade']:.2f}; "
        f"força de restritividade E7: <b>{_esc(d['forca_e7'])}</b>).</p>"]
    if d["pares"]:
        linhas = "".join(
            f"<tr><td>{_esc(p['orgao'])}</td><td>{_esc(p['objeto'])}</td>"
            f"<td class='mono'>{_esc(p['controle'])}</td></tr>" for p in d["pares"][:6])
        extra = (f"<p class='nota'>Mostrando 6 de {len(d['pares'])} editais-pares sem a cláusula; "
                 f"lista completa no XLSX de apoio.</p>") if len(d["pares"]) > 6 else ""
        html.append("<p class='sub'>Editais do mesmo grupo que dispensam a exigência:</p>"
                    "<table><tr><th>Órgão</th><th>Objeto</th><th>Controle PNCP</th></tr>"
                    f"{linhas}</table>{extra}")
    return "".join(html)


def _bloco_fundamentacao(d: dict) -> str:
    f = d["fundamentacao"]
    if not f:
        return ("<p class='ind'>Sem âncora jurisprudencial mapeada para este subtipo — "
                "a análise repousa nos votos do colegiado e no princípio da competitividade "
                "(art. 9º, I, da Lei 14.133/2021).</p>")
    partes = []
    # súmulas com texto verbatim
    for nome in f.get("sumulas", []):
        chave = nome.replace("Súmula ", "").strip()  # "Súmula TCU 275" → "TCU 275"
        s = SUMULAS.get(chave)
        if s:
            obs = f" <span class='nota'>({_esc(s['obs'])})</span>" if s.get("obs") else ""
            partes.append(f"<div class='sumula'><b>{_esc(s['numero'])} ({_esc(s['orgao'])}) — {_esc(s['tema'])}.</b> "
                          f"<i>“{_esc(s['texto'])}”</i>{obs}</div>")
        else:
            partes.append(f"<div class='sumula'><b>{_esc(nome)}.</b></div>")
    # acórdãos (ementa curada)
    for ac in f.get("acordaos", []):
        partes.append(f"<div class='acordao'><b>{_esc(ac.orgao)} — {_esc(ac.numero)}.</b> "
                      f"{_esc(ac.tema)}. <i>{_esc(ac.ementa)}</i></div>")
    # dispositivos + teste finalístico
    disp = f.get("dispositivos_legais") or []
    if disp:
        partes.append(f"<p><b>Dispositivos legais:</b> {_esc('; '.join(disp))}.</p>")
    if f.get("teste_finalistico"):
        partes.append(f"<p class='teste'><b>Teste de legalidade:</b> {_esc(f['teste_finalistico'])}.</p>")
    if f.get("verificar_antes_de_citar"):
        partes.append("<p class='aviso'>⚠️ Parte das âncoras deste subtipo ainda depende de conferência "
                      "no verbatim primário (pesquisa.apps.tcu.gov.br) antes de citação em peça definitiva.</p>")
    return "".join(partes)


def _bloco_colegiado(d: dict) -> str:
    votos = d["votos"]
    linhas = []
    for lente in _LENTES_ORDEM:
        v = votos.get(lente) or {}
        voto = v.get("voto")
        just = v.get("justificativa") or ""
        cit = v.get("citacao") or ""
        if voto is None:
            badge = "<span class='ind'>INDISPONÍVEL</span>"
        else:
            cls = "alto" if voto >= 7 else "medio" if voto >= 4 else "baixo"
            badge = f"<span class='voto {cls}'>{voto}/10</span>"
        gate = " <span class='gate'>· voto-gate</span>" if lente == "refutador" else ""
        cit_html = f"<div class='cit'>{_esc(cit)}</div>" if cit else ""
        linhas.append(f"<tr><td class='lente'>{_esc(_LENTE_ROTULO[lente])}{gate}</td>"
                      f"<td class='vc'>{badge}</td>"
                      f"<td>{_esc(just)}{cit_html}</td></tr>")
    nota = ("<p class='nota'>O <b>refutador</b> é voto-gate: se defende a cláusula (voto ≤3), o colegiado "
            "rebaixa o escore (presunção de legitimidade). Voto INDISPONÍVEL não conta (≠ 0). "
            "Escore final = mediana dos votos válidos.</p>")
    return ("<table class='colegiado'><tr><th>Lente</th><th>Voto</th><th>Fundamento</th></tr>"
            f"{''.join(linhas)}</table>{nota}")


def _bloco_conclusao(d: dict) -> str:
    verd = d["veredito"]
    cor = "extremo" if d["score"] >= 9 else "alto" if d["score"] >= 7 else "medio"
    txt = {
        "direcionamento": ("Os elementos convergem para <b>indício de direcionamento</b>: exigência rara no "
                           "grupo, com força restritiva reconhecida pela jurisprudência e reprovada pela maioria "
                           "das lentes. Recomenda-se diligência junto ao órgão para exame da motivação técnica "
                           "da cláusula e do efeito concreto sobre a competitividade do certame."),
        "indício fraco": ("Há <b>indício fraco</b>: a cláusula destoa do grupo, mas o colegiado não convergiu para "
                          "restritividade — pode haver justificativa técnica legítima. Fica registrado para "
                          "acompanhamento, sem recomendação de medida imediata."),
    }.get(verd, "Cláusula dentro do padrão do grupo — sem indício relevante de direcionamento.")
    return (f"<p class='conclusao {cor}'><b>Veredito do colegiado: {_esc(verd)} — escore {d['score']}/10.</b> "
            f"{txt} <i>Indício não é acusação; presume-se a legitimidade do ato administrativo até prova em contrário.</i></p>")


def _ficha_html(n: int, d: dict) -> str:
    return "".join([
        "<div class='ficha'>",
        f"<h3>Achado nº {n} — Direcionamento por {_esc(d['subtipo'])} · escore {d['score']}/10</h3>",
        "<h4>I. Identificação</h4>", _tabela_id(d),
        "<h4>II. Cláusula restritiva (íntegra)</h4>",
        f"<blockquote class='clausula'>{_esc(d['clausula'])}</blockquote>",
        "<h4>III. Análise comparativa (peer-diff)</h4>", _bloco_peerdiff(d),
        "<h4>IV. Fundamentação jurídica</h4>", _bloco_fundamentacao(d),
        "<h4>V. Parecer do colegiado (5 lentes)</h4>", _bloco_colegiado(d),
        "<h4>VI. Beneficiário</h4>",
        "<p class='ind'>Vínculo edital→contrato/fornecedor vencedor indisponível nesta base "
        "(chave PNCP entre editais e contratos não pareável na coleta atual). "
        "A lente de beneficiário votou sem sinal de captura — logo, o indício repousa na "
        "restritividade da cláusula, não no favorecimento a fornecedor identificado.</p>",
        "<h4>VII. Conclusão</h4>", _bloco_conclusao(d),
        "</div>",
    ])


# ── montador do contexto completo ────────────────────────────────────────────

def montar_ctx(con, limiar_corpo: int = 7) -> dict:
    """Lê clausula_veredito, enriquece e monta o ctx do relatório jurídico completo.

    limiar_corpo: escore mínimo para a ficha completa ir ao CORPO; abaixo disso, vai à tabela-anexo
    (sem truncar — todos comparecem, o corpo é só a triagem dos casos quentes)."""
    vereditos = con.execute(
        "SELECT * FROM clausula_veredito ORDER BY score_final DESC, raridade DESC").fetchall()
    n_total = len(vereditos)
    quentes = [v for v in vereditos if (v["score_final"] or 0) >= limiar_corpo]
    fracos = [v for v in vereditos if 4 <= (v["score_final"] or 0) < limiar_corpo]
    normais = [v for v in vereditos if (v["score_final"] or 0) < 4]

    _todos_quentes = [_enriquecer(con, v) for v in quentes]
    # revisão de sanidade: separa cláusulas de habilitação REAIS dos falsos positivos de classificação
    dados_quentes, descartados = [], []
    for d in _todos_quentes:
        motivo = _falso_positivo(d["subtipo"], d["clausula"])
        if motivo:
            d["_motivo_descarte"] = motivo
            descartados.append(d)
        else:
            dados_quentes.append(d)

    secoes = []

    # 1. Sumário executivo + índice navegável
    _extra_desc = (f" Destes, <b>{len(descartados)}</b> foram <b>descartados na revisão de sanidade</b> "
                   f"(classificação equivocada — ver anexo) e <b>{len(dados_quentes)}</b> seguem para ficha completa."
                   if descartados else "")
    resumo = [
        f"<p>Foram submetidas ao colegiado de cinco lentes <b>{n_total}</b> cláusulas raras "
        f"(triadas por <i>peer-diff</i> entre editais de objeto semelhante). Resultado: "
        f"<b>{len(quentes)}</b> com escore de direcionamento (≥ {limiar_corpo}), "
        f"<b>{len(fracos)}</b> com indício fraco e <b>{len(normais)}</b> dentro do padrão.{_extra_desc}</p>",
        "<p><b>Indício ≠ acusação.</b> Direcionamento é anomalia RELATIVA ao grupo, não juízo sobre o mérito "
        "do gestor; cada ficha traz a fundamentação e a ressalva de legitimidade.</p>",
    ]
    if dados_quentes:
        idx = "".join(
            f"<tr><td>{i}</td><td>{_esc(d['orgao'])}</td><td>{_esc((d['objeto'] or '')[:70])}</td>"
            f"<td><i>{_esc(d['subtipo'])}</i></td><td>{_esc(d['sumula_curta'] or '—')}</td>"
            f"<td class='vc'><span class='voto {'alto' if d['score']>=7 else 'medio'}'>{d['score']}/10</span></td></tr>"
            for i, d in enumerate(dados_quentes, 1))
        resumo.append("<p class='sub'>Índice dos achados de direcionamento (ficha completa adiante):</p>"
                      "<table><tr><th>#</th><th>Órgão</th><th>Objeto</th><th>Exigência</th>"
                      f"<th>Súmula</th><th>Escore</th></tr>{idx}</table>")
    secoes.append({"titulo": "1. Sumário executivo", "html": "".join(resumo)})

    # 2. Metodologia
    secoes.append({"titulo": "2. Metodologia e limites da análise", "html": (
        "<p>O motor compara editais de <b>objeto semelhante</b> (agrupamento semântico) e isola, por "
        "<i>peer-diff</i>, a exigência de habilitação que <b>só um</b> ou poucos editais do grupo impõem — "
        "a raridade relativa é o primeiro filtro de restritividade. As cláusulas raras sobem a um "
        "<b>colegiado de cinco lentes</b> independentes (proporcionalidade, jurisprudência, impacto na "
        "competição, defesa do edital e beneficiário), cada uma fundamentando o voto em súmulas e "
        "dispositivos legais. O <b>refutador</b> é voto-gate a favor da legitimidade. O escore final é a "
        "mediana dos votos válidos.</p>"
        "<p><b>Limites honestos:</b> (a) o vínculo entre o edital e o fornecedor vencedor não é pareável na "
        "coleta atual — não se afirma favorecimento a empresa; (b) súmulas marcadas exibem aviso quando a "
        "âncora ainda depende de conferência no verbatim primário; (c) valores podem constar como sigilosos. "
        "Empenho ≠ liquidação ≠ pagamento; nada indisponível foi fabricado.</p>")})

    # 3..N. Fichas completas (uma seção por achado quente, com quebra de página)
    for i, d in enumerate(dados_quentes, 1):
        secoes.append({"titulo": f"{i + 2}. Achado nº {i} — {d['orgao']}",
                       "html": _ficha_html(i, d), "page_break": True})

    # anexo: cauda (indício fraco + normal) — TODOS, sem truncar silenciosamente
    def _linha_anexo(v):
        nc = v["numero_controle_pncp"]
        cl = con.execute("SELECT subtipo FROM edital_clausula WHERE id=?", (v["clausula_id"],)).fetchone()
        lic = con.execute("SELECT orgao_nome FROM pcrj_licitacoes WHERE numero_controle_pncp=?", (nc,)).fetchone()
        return (f"<tr><td>{_esc(lic['orgao_nome'] if lic else '—')}</td>"
                f"<td><i>{_esc(cl['subtipo'] if cl else '—')}</i></td>"
                f"<td class='mono'>{_esc(nc)}</td><td>{v['raridade']:.2f}</td>"
                f"<td>{_esc(v['veredito'])}</td><td class='vc'>{v['score_final']}/10</td></tr>")

    # seção de descartados na revisão de sanidade (transparência — não some com o falso positivo)
    if descartados:
        linhas = "".join(
            f"<tr><td>{_esc(d['orgao'])}</td><td>{_esc((d['objeto'] or '')[:60])}</td>"
            f"<td><i>{_esc(d['subtipo'])}</i></td><td class='vc'>{d['score']}/10</td>"
            f"<td>{_esc(d['_motivo_descarte'])}</td></tr>" for d in descartados)
        secoes.append({"titulo": f"{len(dados_quentes) + 3}. Descartados na revisão de sanidade ({len(descartados)})",
                       "html": ("<p class='nota'>Cláusulas com escore alto do colegiado que a revisão determinística "
                                "identificou como <b>falso positivo de classificação</b> — a exigência apontada não é, "
                                "de fato, cláusula de habilitação (ex.: especificação técnica de produto lida como "
                                "índice contábil). Mantidas à vista para auditoria; corrigidas na origem para as "
                                "próximas extrações.</p>"
                                "<table><tr><th>Órgão</th><th>Objeto</th><th>Classificação</th><th>Escore</th>"
                                f"<th>Motivo do descarte</th></tr>{linhas}</table>"),
                       "page_break": True})

    cauda = fracos + normais
    if cauda:
        linhas = "".join(_linha_anexo(v) for v in cauda)
        _n_anexo = len(dados_quentes) + (4 if descartados else 3)
        secoes.append({"titulo": f"{_n_anexo}. Anexo — demais cláusulas avaliadas ({len(cauda)})",
                       "html": ("<p class='nota'>Cláusulas com escore abaixo do limiar de direcionamento — "
                                "listadas na íntegra (sem truncamento); detalhamento por lente no XLSX de apoio.</p>"
                                "<table><tr><th>Órgão</th><th>Exigência</th><th>Controle PNCP</th>"
                                f"<th>Raridade</th><th>Veredito</th><th>Escore</th></tr>{linhas}</table>"),
                       "page_break": True})

    score_capa = min(100, (max((d["score"] for d in dados_quentes), default=0)) * 10)
    faixa = ("EXTREMO" if score_capa >= 90 else "ALTO" if score_capa >= 70
             else "MÉDIO" if score_capa >= 50 else "BAIXO")
    top = [f"{d['orgao'][:28]} · {d['subtipo']}" for d in dados_quentes[:4]]

    fontes = [
        {"dado": "Editais (texto íntegro + itens)", "estado": "REAL", "fonte": "PNCP — baixar_documentos",
         "data": datetime.now().date().isoformat()},
        {"dado": "Órgão / modalidade / valor", "estado": "REAL", "fonte": "PNCP — pcrj_licitacoes (JOIN)",
         "data": datetime.now().date().isoformat()},
        {"dado": "Agrupamento por objeto", "estado": "REAL", "fonte": "Embeddings semânticos (Cohere)",
         "data": datetime.now().date().isoformat()},
        {"dado": "Classificação da cláusula + súmulas", "estado": "REAL",
         "fonte": "Motor E7 + jurisprudência TCU/TCE-RJ curada + colegiado de 5 lentes",
         "data": datetime.now().date().isoformat()},
    ]

    return {
        "titulo": "Fiscalização de Direcionamento em Editais — Estado e Município do Rio de Janeiro",
        "subtitulo": ("Representação técnica — comparação cláusula-a-cláusula (peer-diff) entre editais de "
                      "objeto semelhante, submetida a colegiado de cinco lentes"),
        "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO",
        "metodologia": "Peer-diff + colegiado de 5 lentes + jurisprudência TCU/TCE-RJ (Lei 14.133/2021)",
        "analista": "Controle Externo (automatizado)",
        "score": score_capa, "faixa": faixa, "top_flags": top,
        "secoes": secoes, "proveniencia": fontes,
        "ressalva": ("Peça de diligência do controle externo: indícios de restritividade para apuração, "
                     "jamais acusação. Presume-se a legitimidade dos atos administrativos. O vínculo com o "
                     "fornecedor vencedor não integra esta base; nenhum dado indisponível foi fabricado."),
        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "_dados": {"n_total": n_total, "quentes": len(quentes), "controles": [d["controle_pncp"] for d in dados_quentes]},
    }
