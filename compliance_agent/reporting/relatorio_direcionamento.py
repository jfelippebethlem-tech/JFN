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
import sqlite3
from datetime import datetime

from compliance_agent.editais.indice_certame import _matriz_sv as _matriz_sv_certame
from compliance_agent.editais.peer_diff import _SUBTIPO_PARA_TIPO_E7
from compliance_agent.editais.teste_finalistico import avaliar as _teste_exec
from compliance_agent.knowledge.jurisprudencia import fundamentar_clausula, obter_sumula

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
        "teste_exec": _teste_exec(subtipo, clausula_int, valor),
        "votos": votos,
        "vencedor": (v["vencedor_doc"] if "vencedor_doc" in v.keys() else None) or "",
        "sinais_beneficiario": (json.loads(v["sinais_json"])
                                if "sinais_json" in v.keys() and v["sinais_json"] else []),
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
    if d["raridade"] is None:
        # fallback absoluto (cluster < 3): comparação entre pares INDISPONÍVEL ≠ raridade zero
        html = [
            f"<p>O agrupamento deste objeto reúne apenas <b>{d['n_grupo']} edital(is)</b> — "
            "insuficiente para comparação entre pares (peer-diff). O indício repousa na "
            f"<b>força absoluta do catálogo E7</b> (tier <b>{_esc(d['forca_e7'])}</b>): a exigência "
            "pertence à classe reconhecida pela jurisprudência como restritiva em si, "
            "independentemente do comportamento dos pares.</p>"]
        return "".join(html)
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
    # teste finalístico EXECUTADO (número da cláusula vs teto legal) — objetivo, antes do colegiado
    te = d.get("teste_exec")
    if te and te["status"] != "nao_aferivel":
        cls = "violado" if te["status"] == "violado" else "conforme"
        rotulo = ("Aferição objetiva: exigência EXCEDE o teto legal" if te["status"] == "violado"
                  else "Aferição objetiva: exigência dentro do teto legal")
        partes.append(f"<p class='teste-exec {cls}'><b>{rotulo}.</b> {_esc(te['motivo'])}.</p>")
    # súmulas com texto verbatim (match normalizado — qualquer grafia de "Súmula TCU nº 263")
    for nome in f.get("sumulas", []):
        s = obter_sumula(nome)
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
    # redação-conforme (redline): a alternativa LÍCITA que saneia a cláusula — dá objeto à diligência
    red = _REDACAO_CONFORME.get(_SUBTIPO_PARA_TIPO_E7.get(d["subtipo"], d["subtipo"]))
    if red:
        partes.append("<div class='redline'><b>Redação conforme sugerida</b> (parâmetro para a diligência — "
                      f"a cláusula deixa de ser restritiva se reescrita nestes termos): <i>“{_esc(red)}”</i></div>")
    return "".join(partes)


# redação alternativa lícita por tipo de cláusula (padrão redline: cláusula atual → proposta + fundamento).
# Determinística, curada com a mesma âncora do INDICE_CLAUSULA — nada inventado por LLM.
_REDACAO_CONFORME = {
    "capital_patrimonio": ("Exige-se capital social mínimo OU patrimônio líquido mínimo de até 10% (dez por "
                           "cento) do valor estimado da contratação, admitida, em alternativa, a prestação de "
                           "garantia, vedada a exigência cumulativa (Súmula TCU 275; Lei 14.133/2021 art. 69)"),
    "atestado_quantitativo": ("Atestado(s) de capacidade técnica que comprovem execução anterior de até 50% "
                              "(cinquenta por cento) do quantitativo licitado, restrito às parcelas de maior "
                              "relevância e valor significativo, admitido o somatório de atestados "
                              "(Súmula TCU 263)"),
    "atestado_identico": ("Admite-se o somatório de atestados para comprovação dos quantitativos mínimos, "
                          "vedada a exigência de atestado único de objeto idêntico sem motivação técnica "
                          "expressa (Súmula TCU 263; Acórdão TCU 1.153/2024)"),
    "garantia_proposta": ("Garantia de manutenção de proposta de até 1% (um por cento) do valor estimado, "
                          "não cumulável com exigência de capital ou patrimônio líquido mínimo "
                          "(Lei 14.133/2021 art. 58 §1º; Súmula TCU 275)"),
    "marca_dirigida": ("Indicação de marca exclusivamente como referência de qualidade, acrescida da "
                       "expressão 'ou equivalente/similar ou de melhor qualidade', salvo padronização "
                       "previamente justificada nos autos (Súmula TCU 270; Lei 14.133/2021 art. 41 I)"),
    "visita_tecnica": ("Visita técnica facultativa, substituível por declaração formal do licitante de pleno "
                       "conhecimento das condições do local; obrigatoriedade somente mediante justificativa "
                       "de imprescindibilidade nos autos (Súmula TCE-RJ nº 01; Lei 14.133/2021 art. 63 III)"),
    "vinculo_profissional": ("Comprovação de disponibilidade do profissional por declaração de compromisso "
                             "de contratação futura, vedada a exigência de vínculo empregatício prévio "
                             "(Súmula TCE-RJ nº 10; Súmula TCU 272)"),
    "recorte_geografico": ("Vedada distinção quanto à sede, domicílio ou local de fabricação como condição "
                           "de habilitação ou pontuação (Lei 14.133/2021 art. 9º I 'b'); a localização pode "
                           "figurar apenas como critério de desempate legalmente previsto"),
    "recorte_temporal": ("Prazo de apresentação de amostra/documentos proporcional à complexidade do objeto "
                         "e suficiente para licitante que não seja o atual prestador (Acórdão TCU 871/2023)"),
    "amostra_poc": ("Amostra ou prova de conceito exigida apenas do licitante provisoriamente classificado "
                    "em primeiro lugar, nunca de todos os licitantes como condição de participação "
                    "(Lei 14.133/2021 arts. 17 §3º e 42)"),
    "indices_contabeis": ("Índices contábeis usuais de mercado (liquidez geral/corrente), com justificativa "
                          "nos autos e vedada fórmula que inclua rentabilidade ou lucratividade "
                          "(Súmula TCU 289; Lei 14.133/2021 art. 69)"),
}


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


def _matriz_risco(d: dict) -> str:
    """Matriz Severidade × Verossimilhança (5×5) — escala explícita, cálculo determinístico.

    Severidade = dano potencial à competição (tier E7; +1 se o teste objetivo confirmou violação).
    Verossimilhança = robustez do indício (escore do colegiado; teto 3 sem peer-diff)."""
    sev = {"forte": 4, "medio": 3}.get(d["forca_e7"], 2)
    te = d.get("teste_exec")
    if te and te["status"] == "violado":
        sev = min(5, sev + 1)
    ver = 5 if d["score"] >= 9 else 4 if d["score"] >= 7 else 3 if d["score"] >= 4 else 2
    if d["raridade"] is None:
        ver = min(ver, 3)  # sem comparação entre pares, a verossimilhança não passa de "possível"
    prod = sev * ver
    nivel, acao = (("CRÍTICO 🔴", "representação com pedido de suspensão cautelar do certame")
                   if prod >= 16 else
                   ("ALTO 🟠", "diligência prioritária ao órgão; minuta de representação preparada")
                   if prod >= 10 else
                   ("MÉDIO 🟡", "diligência ordinária; reavaliar com a resposta do órgão")
                   if prod >= 5 else
                   ("BAIXO 🟢", "monitoramento; sem medida imediata"))
    return ("<div class='matriz'><b>Matriz de risco (Severidade × Verossimilhança, escala 1–5 cada; "
            f"produto 1–25):</b> severidade <b>{sev}/5</b> × verossimilhança <b>{ver}/5</b> = "
            f"<b>{prod}/25 — {nivel}</b>. Ação recomendada: {acao}. "
            "<span class='nota'>Régua: 1–4 baixo · 5–9 médio · 10–15 alto · 16–25 crítico.</span></div>")


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
    return (_matriz_risco(d) +
            f"<p class='conclusao {cor}'><b>Veredito do colegiado: {_esc(verd)} — escore {d['score']}/10.</b> "
            f"{txt} <i>Indício não é acusação; presume-se a legitimidade do ato administrativo até prova em contrário.</i></p>")


def _bloco_beneficiario(d: dict) -> str:
    """Seção VI honesta: vencedor REAL quando a ata foi lida (coletor_ata → runner), senão declara
    a indisponibilidade — nunca finge que ausência de dado é ausência de favorecimento."""
    if d.get("vencedor"):
        sinais = d.get("sinais_beneficiario") or []
        sin_html = ("<p><b>Sinais de risco do vencedor:</b> " + _esc("; ".join(sinais)) + ".</p>"
                    if sinais else
                    "<p class='nota'>Sem sinal de risco societário/sancionatório mapeado para o vencedor "
                    "na base atual — o que não exaure a diligência.</p>")
        return (f"<p>Vencedor do certame (ata de julgamento): <b>{_esc(d['vencedor'])}</b>. "
                "A restritividade da cláusula deve ser lida em conjunto com o resultado: exigência rara "
                "que converge para o vencedor identificado fortalece o indício de direcionamento.</p>"
                + sin_html)
    return ("<p class='ind'>Vínculo edital→contrato/fornecedor vencedor indisponível nesta base "
            "(ata de julgamento ainda não lida para este certame). "
            "A lente de beneficiário votou sem sinal de captura — logo, o indício repousa na "
            "restritividade da cláusula, não no favorecimento a fornecedor identificado.</p>")


# ── Contexto do certame (Índice de Direcionamento — certame_indice, Task 4.5) ──

_FAMILIA_ROTULO = {
    "transparencia": "Transparência",
    "competicao": "Competição",
    "conluio": "Conluio",
    "fraude_cadastral": "Fraude cadastral",
    "preco": "Preço",
    "execucao": "Execução",
}


def _g(row, k):
    """Acesso tolerante a coluna ausente (sqlite3.Row → IndexError; dict → KeyError):
    `narrativa_json` é migração aditiva e pode não existir na linha."""
    try:
        return row[k]
    except (KeyError, IndexError):
        return None


def _cor_barra(valor: float) -> str:
    return ("#b3261e" if valor >= 0.75 else "#c77700" if valor >= 0.5
            else "#b8a300" if valor >= 0.25 else "#2e7d32")


def _linha_indice_certame(con, nc: str):
    """Linha de `certame_indice` do certame, ou None (tabela ausente, sem linha ou linha
    sem score — ex.: criada só pela narrativa). Aditivo: sem índice, o relatório sai
    byte-idêntico ao de antes."""
    try:
        row = con.execute("SELECT * FROM certame_indice WHERE certame=?", (nc,)).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None or row["score"] is None:
        return None
    return row


def _bloco_indice_certame(row) -> str:
    """Seção VIII da ficha — o CERTAME como um todo (Índice de Direcionamento 0-100,
    6 famílias com máximo por flag), complementando a ficha, que é da CLÁUSULA.
    Recebe a linha de `certame_indice` (sqlite3.Row ou dict)."""
    familias = json.loads(_g(row, "familias_json") or "{}")
    drivers = json.loads(_g(row, "drivers_json") or "[]")
    score = float(_g(row, "score") or 0.0)
    faixa = _g(row, "faixa") or "BAIXO"
    confianca = float(_g(row, "confianca") or 0.0)

    partes = ["<h4>VIII. Contexto do certame — Índice de Direcionamento</h4>",
              f"<p>O <b>certame como um todo</b> (não apenas a cláusula desta ficha) apresenta "
              f"Índice de Direcionamento <b>{score:.1f}/100 — faixa {_esc(faixa)}</b> "
              f"(confiança {confianca:.2f} = famílias apuráveis / 6; "
              f"família INDISPONÍVEL não pontua nem zera).</p>"]

    linhas = []
    for fam, d in familias.items():
        rot = _esc(_FAMILIA_ROTULO.get(fam, fam))
        if not d.get("apuravel"):
            linhas.append(f"<tr><td>{rot}</td><td class='vc'><span class='ind'>INDISPONÍVEL</span></td>"
                          f"<td class='nota'>{_esc(d.get('nota') or 'fonte não coletada')}</td></tr>")
            continue
        val = float(d.get("valor") or 0.0)
        pct = int(round(val * 100))
        barra = ("<span style='display:inline-block;width:100px;height:9px;background:#e8e8e8;"
                 "vertical-align:middle;'><span style='display:block;height:9px;"
                 f"width:{pct}px;background:{_cor_barra(val)};'></span></span> {pct}%")
        top = max(d.get("flags") or [], key=lambda f: f.get("valor", 0), default=None)
        ev = _esc(top["evidencia"]) if top else "—"
        linhas.append(f"<tr><td>{rot}</td><td class='vc'>{barra}</td><td>{ev}</td></tr>")
    partes.append("<table><tr><th>Família</th><th>Intensidade</th><th>Evidência (flag máximo)</th></tr>"
                  + "".join(linhas) + "</table>")

    if drivers:
        itens = "".join(
            f"<li><b>{_esc(_FAMILIA_ROTULO.get(d['familia'], d['familia']))} · {_esc(d['flag'])}</b> "
            f"({d['valor']:.2f}) — {_esc(d['evidencia'])}</li>" for d in drivers)
        partes.append(f"<p class='sub'>Drivers do índice (família ≥ 0,50):</p><ul>{itens}</ul>")

    m = _matriz_sv_certame(faixa, confianca, len(drivers))
    partes.append("<div class='matriz'><b>Matriz de risco do certame (Severidade × Verossimilhança, "
                  f"escala 1–5 cada; produto 1–25):</b> severidade <b>{m['severidade']}/5</b> × "
                  f"verossimilhança <b>{m['verossimilhanca']}/5</b> = <b>{m['produto']}/25 — "
                  f"{_esc(m['nivel'])}</b>. Ação recomendada: {_esc(m['acao'])}. "
                  f"<span class='nota'>Régua: {_esc(m['regua'])}.</span></div>")

    raw = _g(row, "narrativa_json")
    if raw:
        try:
            nar = json.loads(raw)
        except (TypeError, ValueError):
            nar = None
        if nar and nar.get("paragrafo"):
            tese = f"<b>{_esc(nar['tese'])}.</b> " if nar.get("tese") else ""
            partes.append(f"<blockquote class='clausula'>{tese}{_esc(nar['paragrafo'])}</blockquote>")

    partes.append("<p class='nota'>Índice contextual de PRIORIZAÇÃO interna: indício ≠ acusação; "
                  "presume-se a legitimidade do certame. INDISPONÍVEL ≠ 0.</p>")
    return "".join(partes)


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
        "<h4>VI. Beneficiário</h4>", _bloco_beneficiario(d),
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
    # revisão de sanidade: separa cláusulas de habilitação REAIS dos falsos positivos de classificação;
    # e a AFERIÇÃO OBJETIVA rebaixa achado cuja exigência está DENTRO do teto legal (lícita em abstrato)
    dados_quentes, descartados, rebaixados = [], [], []
    for d in _todos_quentes:
        motivo = _falso_positivo(d["subtipo"], d["clausula"])
        if motivo:
            d["_motivo_descarte"] = motivo
            descartados.append(d)
            continue
        te = d.get("teste_exec")
        if te and te["status"] == "dentro_do_teto":
            d["_motivo_rebaixe"] = te["motivo"]
            rebaixados.append(d)
            continue
        dados_quentes.append(d)

    secoes = []

    # 1. Sumário executivo + índice navegável
    _partes_desc = []
    if descartados:
        _partes_desc.append(f"<b>{len(descartados)}</b> descartados na revisão de sanidade (classificação equivocada)")
    if rebaixados:
        _partes_desc.append(f"<b>{len(rebaixados)}</b> rebaixados pela aferição objetiva "
                            "(exigência dentro do teto legal)")
    _extra_desc = (f" Destes, {' e '.join(_partes_desc)} — ver anexos; "
                   f"<b>{len(dados_quentes)}</b> seguem para ficha completa." if _partes_desc else "")
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

    # 3..N. Fichas completas (uma seção por achado quente, com quebra de página).
    # Seção VIII (aditiva): contexto do CERTAME via certame_indice — só quando a linha
    # existe; sem índice persistido o relatório sai byte-idêntico ao de antes.
    for i, d in enumerate(dados_quentes, 1):
        html_ficha = _ficha_html(i, d)
        row_ic = _linha_indice_certame(con, d["controle_pncp"])
        if row_ic is not None:
            html_ficha = (html_ficha[:-len("</div>")]
                          + _bloco_indice_certame(row_ic) + "</div>")
        secoes.append({"titulo": f"{i + 2}. Achado nº {i} — {d['orgao']}",
                       "html": html_ficha, "page_break": True})

    # anexo: cauda (indício fraco + normal) — TODOS, sem truncar silenciosamente
    def _linha_anexo(v):
        nc = v["numero_controle_pncp"]
        cl = con.execute("SELECT subtipo FROM edital_clausula WHERE id=?", (v["clausula_id"],)).fetchone()
        lic = con.execute("SELECT orgao_nome FROM pcrj_licitacoes WHERE numero_controle_pncp=?", (nc,)).fetchone()
        rar = f"{v['raridade']:.2f}" if v["raridade"] is not None else "s/ pares"
        return (f"<tr><td>{_esc(lic['orgao_nome'] if lic else '—')}</td>"
                f"<td><i>{_esc(cl['subtipo'] if cl else '—')}</i></td>"
                f"<td class='mono'>{_esc(nc)}</td><td>{rar}</td>"
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

    # rebaixados pela aferição objetiva (transparência: exigência lícita em abstrato, mantida à vista)
    if rebaixados:
        linhas = "".join(
            f"<tr><td>{_esc(d['orgao'])}</td><td>{_esc((d['objeto'] or '')[:60])}</td>"
            f"<td><i>{_esc(d['subtipo'])}</i></td><td class='vc'>{d['score']}/10</td>"
            f"<td>{_esc(d['_motivo_rebaixe'])}</td></tr>" for d in rebaixados)
        secoes.append({"titulo": f"{len(dados_quentes) + (4 if descartados else 3)}. Rebaixados pela aferição "
                                 f"objetiva ({len(rebaixados)})",
                       "html": ("<p class='nota'>Cláusulas com escore alto do colegiado cujo número exigido, "
                                "medido contra o teto da jurisprudência, está <b>dentro do limite lícito</b> — "
                                "a restritividade em abstrato não se confirma. Permanecem registradas para "
                                "acompanhamento (o contexto do certame ainda pode revelar direcionamento).</p>"
                                "<table><tr><th>Órgão</th><th>Objeto</th><th>Exigência</th><th>Escore</th>"
                                f"<th>Aferição objetiva</th></tr>{linhas}</table>"),
                       "page_break": True})

    cauda = fracos + normais
    if cauda:
        linhas = "".join(_linha_anexo(v) for v in cauda)
        _n_anexo = len(dados_quentes) + 3 + (1 if descartados else 0) + (1 if rebaixados else 0)
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
