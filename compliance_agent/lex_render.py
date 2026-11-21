# -*- coding: utf-8 -*-
"""Lex — RENDER do parecer de fornecedor: mérito, seções (_secao_*), parecer_md e render_pdf.

Extraído de lex.py (split 2026-07-06); comportamento idêntico (snapshot-tested).
parecer_md(ctx) sem análise pronta importa lex._analise tardiamente (evita ciclo).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fpdf.enums import XPos, YPos

logger = logging.getLogger(__name__)

from compliance_agent.collectors.arquivos import caminho_db
from compliance_agent.reporting.inteligencia import (
    _mc, _registrar_fonte, _render_parecer_pdf, fmt_cnpj, so_digitos,
)

_BADGE_STATUS = {"CONFIRMADO": "🔴 CONFIRMADO", "INDICIO": "🟡 INDÍCIO",
                 "AFASTADO": "🟢 AFASTADO", "INDISPONIVEL": "⚪ INDISPONÍVEL"}


def _secao_direcionamento(add, direc: dict | None) -> None:
    """§II-F — DIRECIONAMENTO (parecer LLM on-demand sobre o dossiê consolidado das árvores do fornecedor).
    SURFACE do veredito já computado (`tools.sei_direcionamento_llm`). Honesto: indício a verificar, nunca
    acusação; só aparece p/ os top-score efetivamente avaliados (senão a seção é omitida)."""
    if not direc or not (direc.get("grau") or direc.get("resumo")):
        return
    _badge = {"vermelho": "🔴 VERMELHO", "amarelo": "🟡 AMARELO", "verde": "🟢 VERDE",
              "indeterminado": "⚪ INDETERMINADO", "indisponivel": "⚪ INDISPONÍVEL"}
    grau = str(direc.get("grau") or "").lower()
    add("## II-F. DIRECIONAMENTO DE LICITAÇÃO (cérebro on-demand — indício a verificar)")
    add("")
    add("*Avaliação raciocinada (LLM) sobre o **dossiê consolidado** das árvores SEI deste fornecedor: "
        "exigências restritivas + cascata de desclassificações (Súmula TCU 263). Indício a apurar — "
        "presunção de legitimidade dos atos administrativos, NUNCA acusação.*")
    add("")
    add(f"**Grau de direcionamento:** {_badge.get(grau, grau.upper() or '—')} · "
        f"score de triagem {direc.get('score', 0)}/100"
        + (f" · _{direc.get('modelo')}_" if direc.get("modelo") else "")
        + (f" · avaliado {direc.get('avaliado_em')[:10]}" if direc.get("avaliado_em") else ""))
    add("")
    if direc.get("resumo"):
        add(f"> {direc['resumo']}")
        add("")
    if direc.get("raciocinio"):
        add(f"**Raciocínio:** {direc['raciocinio']}")
        add("")
    det = direc.get("detalhe") or {}
    ex = det.get("exigencias_restritivas") or []
    if ex:
        add("**Exigências apontadas como restritivas:**")
        for e in ex[:5]:
            por = (e.get("por_que_restringe") or "")[:160]
            jur = e.get("jurisprudencia") or "—"
            add(f"- {por} _(juris.: {jur})_")
            if e.get("trecho"):
                add(f"  - trecho: “{(e.get('trecho') or '')[:140]}”")
        add("")
    casc = det.get("cascata") or []
    if casc:
        add("**Cascata de julgamento (indício):**")
        add("")
        add("| Licitante | Ordem preço | Situação | Motivo |")
        add("|---|---:|---|---|")
        for c in casc[:8]:
            mot = (c.get("motivo") or "").replace("|", "/")[:60]
            add(f"| {(c.get('licitante') or '?')[:30]} | {c.get('ordem_preco', '?')} | "
                f"{c.get('situacao', '?')} | {mot} |")
        add("")
    if not det.get("dados_suficientes", True):
        add("> ⚠ **Dados insuficientes** no dossiê para um juízo conclusivo — buscar o edital/ata da "
            "licitação (processo de contratação, não o de execução). INDISPONÍVEL ≠ irregular.")
        add("")


_VER_PESQ = {"resolvido": "🟢 RESOLVIDO", "agrava": "🔴 AGRAVA", "inconclusivo": "⚪ INCONCLUSIVO"}


def _secao_pesquisa(add, pesq: dict | None) -> None:
    """§II-G — PESQUISA-INTERNET (Fase 5): o Lex pesquisou as dúvidas (OSINT/web/DOERJ/mídia adversa),
    aprendeu e re-ajustou a análise. SURFACE do que já foi computado (`tools.lex_pesquisa_internet`).
    Honesto: indício a verificar, nunca acusação; INDISPONÍVEL ≠ irregular; cada 'agrava' cita a fonte."""
    if not pesq or not (pesq.get("achados") or pesq.get("resumo")):
        return
    add("## II-G. PESQUISA-INTERNET — dúvidas, aprendizado e re-ajuste (indício a verificar)")
    add("")
    add("*A análise pesquisou as dúvidas abertas na internet (busca web, notícias, Diário Oficial/Querido Diário, "
        "mídia adversa) e re-ajustou a análise. Indício a apurar — presunção de legitimidade, NUNCA acusação; "
        "ausência de registro NÃO é agravante.*")
    add("")
    cab = f"**{pesq.get('n_fontes', 0)} fonte(s)**"
    if pesq.get("modelo"):
        cab += f" · _{pesq['modelo']}_"
    if pesq.get("avaliado_em"):
        cab += f" · pesquisado {str(pesq['avaliado_em'])[:10]}"
    add(cab)
    add("")
    if pesq.get("resumo"):
        add(f"> {pesq['resumo']}")
        add("")
    for a in (pesq.get("achados") or [])[:8]:
        ver = _VER_PESQ.get(str(a.get("veredito") or "").lower(), (a.get("veredito") or "—").upper())
        add(f"- **{ver}** — {a.get('duvida','')}")
        if a.get("nota"):
            add(f"  - {a['nota']}")
        for f in (a.get("fontes") or [])[:3]:
            add(f"  - fonte: {f}")
    add("")
    if pesq.get("reajuste"):
        add(f"**Re-ajuste da análise:** {pesq['reajuste']}")
        add("")


def _secao_padroes_ligados(add, cruzado: str) -> None:
    """§II-G.1 — APRENDIZADO CRUZADO: padrões já apurados em fornecedores LIGADOS (mesmos sócios/veículos).
    SURFACE do bloco já computado (`tools.lex_aprendizado_cruzado`), persistido em lex_pesquisa.cruzado — sem
    recomputar e SEM 2ª chamada LLM. Honesto: indício a VERIFICAR por associação societária, NUNCA culpa por
    associação; presunção de legitimidade; INDISPONÍVEL ≠ irregular."""
    cruzado = (cruzado or "").strip()
    if not cruzado:
        return
    add("## II-G.1. APRENDIZADO CRUZADO — fornecedores ligados (mesmos sócios/veículos)")
    add("")
    add("*Inteligência progressiva cross-fornecedor: o que já foi apurado em empresas IRMÃS (vínculo "
        "societário — mesmos sócios/administradores/veículos) é trazido como CONTEXTO para corroborar ou "
        "CONTRASTAR a análise. **Indício a verificar por associação, nunca culpa por associação;** presunção "
        "de legitimidade; INDISPONÍVEL ≠ irregular.*")
    add("")
    for ln in cruzado.splitlines():
        ln = ln.rstrip()
        if ln:
            add(ln if ln.lstrip().startswith("-") else f"- {ln}")
    add("")


def _secao_investigacao(add, inv: dict, cnpj: str = "") -> None:
    """Renderiza a seção II-E — a investigação de fachada/laranja que o Lex conduziu (motor investigacao_dd).

    Apresenta cada hipótese com status/nível/evidência/fonte/base legal E a cobertura honesta (o que foi
    verificado e o que ficou INDISPONÍVEL) — indício merece apuração, nunca acusação; INDISPONÍVEL ≠ risco zero."""
    add("## II-E. INVESTIGAÇÃO DE DUE DILIGENCE — empresa de fachada / laranja")
    add("")
    add("*Bateria de hipóteses investigativas (cadastro Receita + base de OBs + OSINT). Base legal: controle "
        "externo e fiscalização (CF art. 70-71; LGPD art. 7º,II e 23). **Honesto:** indício merece apuração, "
        "nunca acusação; **INDISPONÍVEL ≠ ausência de risco**; CPF de pessoa física mascarado (LGPD).*")
    add("")
    # Agregado do sweep de benefícios dos sócios/administradores (socio_beneficio) — cruzamento de laranja
    # independente do motor DD; complementa o H-BENEFICIO por-pessoa com a cobertura honesta do universo do QSA.
    try:
        from compliance_agent.reporting import beneficios_view as bv
        _b = bv.por_fornecedor(cnpj) if cnpj else {}
    except Exception:  # noqa: BLE001
        _b = {}
    if _b.get("n_verificados"):
        if _b.get("n_com_beneficio"):
            add(f"> **Benefícios sociais dos sócios/administradores (sweep):** {_b.get('n_pessoas_beneficio', 0)} de "
                f"{_b['n_verificados']} verificados recebem benefício de subsistência — **indício de interposição de "
                f"pessoas (laranja)** a confirmar no contrato social/procuração/SEI (de {_b['total_qsa']} sócios no "
                f"QSA; {_b['n_indisponivel']} ainda INDISPONÍVEL).")
        else:
            add(f"> **Benefícios sociais dos sócios/administradores (sweep):** {_b['n_verificados']} verificado(s), "
                f"nenhum recebe benefício de subsistência (indício de laranja afastado para os verificados; "
                f"{_b['n_indisponivel']} de {_b['total_qsa']} ainda INDISPONÍVEL).")
        add("")
    # Pegada na PREFEITURA do Rio (ContasRio → contasrio_contrato): contexto de esfera municipal com o nº do
    # processo e o link do inteiro teor (CCON). O achado (DD/DIRETA-PCRJ) vive nos estruturais; aqui é o retrato.
    _cp = (inv or {}).get("pcrj_contratos") if isinstance(inv, dict) else None
    if _cp and _cp.get("n"):
        def _brl(v):   # 1234567.89 → 1.234.567,89 (só o número, não a frase)
            return f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        add(f"> **Contratos com a Prefeitura do Rio (ContasRio, {_cp.get('ano_min')}–{_cp.get('ano_max')}):** "
            f"{_cp['n']} contrato(s), {_cp.get('diretas', 0)} por contratação direta; valor atualizado "
            f"R$ {_brl(_cp.get('valor'))}, pago pelo Município R$ {_brl(_cp.get('pago'))}; "
            f"{_cp.get('n_orgaos', 0)} órgão(s): {_cp.get('orgaos', '')[:120]}.")
        for m in (_cp.get("maiores") or [])[:3]:
            proc = m.get("processo") or "processo n/d"
            link = f" — [inteiro teor]({m['url_ccon']})" if m.get("url_ccon") else ""
            add(f">   · {m.get('ano')} · {m.get('orgao', '')[:50]} · {m.get('forma', '')} · {proc}: "
                f"{(m.get('objeto') or '')[:90]}{link}")
        add("")
    if not inv or not isinstance(inv, dict):
        add("> Investigação não disponível para este alvo nesta análise (cadastro/base insuficientes).")
        add("")
        return
    grau = inv.get("grau", "🟢")
    add(f"**Grau da investigação:** {grau} · score {inv.get('score', 0)}/100 · "
        f"{inv.get('n_confirmados', 0)} fato(s) confirmado(s), {inv.get('n_indicios', 0)} indício(s) a apurar.")
    add("")
    add(inv.get("resumo", ""))
    add("")
    hips = inv.get("hipoteses") or []
    if hips:
        for h in hips:
            badge = _BADGE_STATUS.get(h.get("status", ""), h.get("status", ""))
            add(f"### {h.get('codigo', '')} — {h.get('titulo', '')}")
            add(f"- **Status:** {badge}  ·  **Nível:** {h.get('nivel', '—')}")
            add(f"- **Constatação:** {h.get('evidencia', '')}")
            add(f"- **Fonte:** {h.get('fonte', '—')}  ·  **Base legal:** {h.get('base_legal', '—')}")
            add("")
    else:
        add("> Nenhuma hipótese de fachada/laranja se confirmou nas fontes verificáveis nesta varredura.")
        add("")
    cob = inv.get("cobertura") or {}
    if cob:
        itens = "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in cob.items())
        add(f"> **Cobertura da investigação (honestidade):** {itens}.")
        add("")
    _secao_pacote_fachada(add, inv.get("pacote_fachada") or {}, inv.get("veredito_fachada") or {})


def _secao_auditoria_contrato(add, aud: dict) -> None:
    """Renderiza a seção II-E.2 — AUDITORIA DE CONTRATO CONTÍNUO (bateria T01–T22, motor auditoria_contrato).

    Mesma estética da II-E (fachada). Cada teste vira um achado com status/nível/evidência/fonte/base legal;
    fecha com a cobertura honesta do gate T22. Indício ≠ acusação; INDISPONÍVEL ≠ irregular; OB = pagamento."""
    if not aud or not isinstance(aud, dict) or not aud.get("achados"):
        return
    add("## II-E.2. AUDITORIA DE CONTRATO CONTÍNUO — execução financeira e repactuação")
    add("")
    add("*Bateria determinística T01–T22 sobre a execução do contrato (OBs SIAFE + retenções OCR + série de "
        "reajustes/CCT + glosas + planilha/contrato quando houver). **REGRA DE OURO:** só a OB Contabilizado é "
        "pagamento (empenho ≠ liquidação ≠ OB). **Honesto:** indício merece apuração, nunca acusação; "
        "**INDISPONÍVEL ≠ irregular** (presunção de legitimidade); materialidade ≤ R$ 0,02 ignorada.*")
    add("")
    grau = aud.get("grau", "🟢")
    cab = aud.get("contrato") or ""
    add(f"**Grau da auditoria:** {grau} · score {aud.get('score', 0)}/100 · "
        f"{aud.get('n_confirmados', 0)} confirmado(s), {aud.get('n_indicios', 0)} indício(s), "
        f"{aud.get('n_indisponivel', 0)} INDISPONÍVEL"
        f"{f' · contrato {cab}' if cab else ''}.")
    add("")
    add(aud.get("resumo", ""))
    add("")
    # Apresenta primeiro os achados acionáveis (CONFIRMADO/INDÍCIO); os INDISPONÍVEL agrupam no fim (honestidade).
    acion = [a for a in aud["achados"] if a.get("status") in ("CONFIRMADO", "INDICIO")]
    afast = [a for a in aud["achados"] if a.get("status") == "AFASTADO"]
    indisp = [a for a in aud["achados"] if a.get("status") == "INDISPONIVEL"]
    for h in acion + afast:
        badge = _BADGE_STATUS.get(h.get("status", ""), h.get("status", ""))
        add(f"### {h.get('codigo', '')} — {h.get('titulo', '')}")
        add(f"- **Status:** {badge}  ·  **Nível:** {h.get('nivel', '—')}")
        add(f"- **Constatação:** {h.get('evidencia', '')}")
        add(f"- **Fonte:** {h.get('fonte', '—')}  ·  **Base legal:** {h.get('base_legal', '—')}")
        add("")
    if indisp:
        add("### Testes INDISPONÍVEL (sem dado-fonte ou critério — não geram achado)")
        for h in indisp:
            add(f"- **{h.get('codigo', '')}** — {h.get('titulo', '')}: {h.get('evidencia', '')}")
        add("")
    cob = aud.get("cobertura") or {}
    if cob:
        itens = "; ".join(f"{k}: {v}" for k, v in cob.items())
        add(f"> **Cobertura da auditoria (gate T22 — honestidade epistêmica):** {itens}.")
        add("")


def _secao_pacote_fachada(add, pac: dict, veredito: dict) -> None:
    """Renderiza os sinais determinísticos do pacote de fachada (TAC com %/UG, sede/visual, REDE) e o
    veredito raciocinado (gemini/cerebras). Tudo consta do parecer. Degrada honesto: bloco vazio = nada."""
    if not pac:
        return
    # 1. RF-TAC (pagamento fora de contrato) — o achado central, com % e UG
    tac = pac.get("tac") or {}
    if tac.get("codigo") == "RF-TAC":
        add(f"### {tac.get('grau', '🟡')} {tac['titulo']}")
        add(f"- **Status:** {_BADGE_STATUS.get('CONFIRMADO', 'CONFIRMADO')}  ·  **Nível:** {tac.get('nivel', '—')}")
        add(f"- **Constatação:** {tac['descricao']}")
        add(f"- **Fonte:** Ordens bancárias (SIAFE — campo observação)  ·  **Base legal:** {tac['fundamento']}")
        add("")
    # 2. sede / visual
    sede = pac.get("sede") or {}
    if sede.get("cobertura", "").startswith("verificado"):
        bits = []
        if sede.get("sem_negocio_google"):
            bits.append("sem negócio operante no Google na sede declarada")
        if sede.get("residencial"):
            bits.append("endereço classificado como residencial")
        if sede.get("visual_suspeito"):
            bits.append(f"imagem da sede: {sede.get('visual_classe')}")
        if bits:
            add(f"### Sinais de SEDE/FACHADA ({sede.get('status', '')})")
            add(f"- **Constatação:** {'; '.join(bits)}. {(sede.get('evidencia') or '')[:200]}")
            add("- **Fonte:** Google (Geocoding+Address Validation+Places) + inspeção visual de imagem.")
            add("")
    # 4. REDE — comando real + outros veículos do administrador
    try:
        from compliance_agent.rede_fachada import render_rede_md
        linhas_rede = render_rede_md(pac.get("rede") or {})
    except Exception:  # noqa: BLE001
        linhas_rede = []
    if linhas_rede:
        add("### Rede de comando e veículos do administrador (QSA real — dump Receita)")
        for ln in linhas_rede:
            add(ln)
        add("")
    # veredito raciocinado (LLM)
    if veredito.get("disponivel"):
        add("### Veredito raciocinado (IA — gemini/cerebras) sobre os sinais")
        add(f"> **{veredito.get('veredito', '—')}** (confiança {veredito.get('confianca', '—')}). "
            f"{veredito.get('fundamentacao', '')}")
        if veredito.get("base_legal"):
            add(f"> **Base legal:** {veredito['base_legal']}")
        add("> *Síntese de IA sobre sinais determinísticos — indício a apurar, não acusação.*")
        add("")
    elif veredito.get("motivo"):
        add(f"> **Veredito raciocinado (IA):** {veredito['motivo']} — os sinais determinísticos acima "
            "permanecem válidos por si (degradação honesta).")
        add("")


def _secao_responsaveis(sei: list) -> list[str]:
    """Fichas de responsabilidade dos processos SEI do contexto, prontas para o parecer.

    Lê a tabela já materializada por `tools/sei_agentes_sweep.py` em vez de reprocessar texto:
    o parecer é gerado sob orçamento de tempo e não pode depender de varrer o acervo. Falha de
    leitura devolve lista vazia — o parecer declara a lacuna, que é a resposta honesta.
    """
    import sqlite3

    numeros = [s.get("numero_sei", "") for s in (sei or []) if s.get("numero_sei")]
    if not numeros:
        return []
    blocos: list[str] = []
    try:
        con = sqlite3.connect(f"file:{caminho_db()}?mode=ro",
                              uri=True, timeout=15)
        con.row_factory = sqlite3.Row
        for numero in numeros[:6]:
            pasta = "".join(c if c.isalnum() else "_" for c in numero.replace("SEI-", ""))
            linhas = list(con.execute(
                "SELECT nome, papel, id_funcional, cargo, documento FROM agente_processo "
                "WHERE processo = ? ORDER BY papel, nome", (pasta,)))
            if not linhas:
                continue
            bloco = [f"**Processo {numero}**", "",
                     "| Papel | Nome | ID funcional | Cargo |", "|---|---|---|---|"]
            for r in linhas:
                papel = str(r["papel"] or "").replace("_", " ").title()
                bloco.append(f"| {papel} | {r['nome']} | {r['id_funcional'] or '—'} | "
                             f"{(r['cargo'] or '—')[:44]} |")
            blocos.append("\n".join(bloco))
        con.close()
    except sqlite3.Error:
        return []
    return blocos


def parecer_md(ctx: dict, analise: dict | None = None) -> str:
    """Parecer REFERÊNCIA de fornecedor (markdown) — por eixos e em duas camadas (`lex_parecer.montar`).

    20/11/2026: o renderizador antigo (seções II…VII) dizia 🟢 "nenhum indício" e, no mérito, citava como
    relevantes sinais que não entravam no grau; misturava fontes (TFE no contexto × SIAFE) e numerava fora de
    ordem. A montagem agora vive em `lex_parecer` e lê só a base única de fatos (`lex_fatos`)."""
    if analise is None:
        from compliance_agent.lex import _analise  # tardio: evita ciclo com a fachada lex.py
        analise = _analise(ctx)
    from compliance_agent import lex_parecer
    texto = lex_parecer.montar(ctx, analise)
    # GATE DE CITAÇÕES — último instante antes de o texto virar entregável (o PDF também passa
    # por aqui, via render_pdf). Acórdão que não existe no acervo do TCU é suprimido; colegiado
    # errado é corrigido; o que não se confirmou vai declarado na nota ao pé. Nunca derruba a
    # geração: falha do gate degrada para "não conferido", e diz isso na peça.
    from compliance_agent.reporting.gate_citacoes import sanear_parecer
    try:
        return sanear_parecer(texto, contexto="parecer Lex")
    except Exception as e:  # índice corrompido, disco cheio: a peça sai, sem o carimbo
        logging.warning("gate de citações indisponível (%s) — parecer emitido sem conferência", e)
        return texto


_FAIXA_DO_GRAU = {"VERDE": "BAIXO", "AMARELO": "MÉDIO", "VERMELHO": "ALTO"}


def secoes_do_md(md: str) -> tuple[str, list[dict]]:
    """Markdown do parecer → (título, seções {titulo, html}) para o funil da casa (`render_html`). Cada '## '
    vira seção; o que vem antes (metadados da capa) vira a seção de abertura. Nada do texto fica de fora."""
    from compliance_agent.reporting.consolidado import _md_to_html
    titulo, secoes, atual, corpo = "", [], "Identificação do parecer", []
    for ln in md.split("\n"):
        if ln.startswith("# ") and not titulo:
            titulo = ln[2:].strip()
            continue
        if ln.startswith("## "):
            if any(x.strip() for x in corpo):
                secoes.append({"titulo": atual, "html": _md_to_html("\n".join(corpo))})
            atual, corpo = ln[3:].strip(), []
            continue
        corpo.append(ln)
    if any(x.strip() for x in corpo):
        secoes.append({"titulo": atual, "html": _md_to_html("\n".join(corpo))})
    if secoes:   # alinhamento numérico à direita (o conversor marca a coluna; o template não tinha a regra)
        secoes[0]["html"] = "<style>td.num,th.num{text-align:right;white-space:nowrap}</style>" + secoes[0]["html"]
    return titulo, secoes


def _pdf_html(ctx: dict, destino: str, analise: dict, md: str) -> str:
    """PDF pela régua da casa: `render_html` (capa, rating, seções, gate de citações) → `html_to_pdf`."""
    import asyncio
    import concurrent.futures

    from compliance_agent.reporting.render_html import html_to_pdf, render_html
    titulo, secoes = secoes_do_md(md)
    rotulo = analise.get("rotulo") or ""
    try:
        from compliance_agent.lex_parecer import score
        sc = score(analise.get("achados") or [])
    except Exception:  # noqa: BLE001
        sc = 0
    n = len(analise.get("achados") or [])
    html = render_html({
        "titulo": titulo or f"Parecer — {ctx.get('nome', '')}",
        "subtitulo": (f"CNPJ {fmt_cnpj(ctx.get('cnpj', ''))}" if so_digitos(ctx.get("cnpj", ""))
                      else f"Unidade Gestora (UG) {ctx.get('ug', '—')}") + f" · {ctx.get('nome', '')}",
        "classificacao": "CONFIDENCIAL — USO INTERNO · CONTROLE EXTERNO",
        "data": ctx.get("data", ""), "metodologia": "eixos jurídico, financeiro, contábil e de integridade; "
                                                    "instrução TCE-RJ; camadas determinística e subjetiva",
        "score": sc, "faixa": _FAIXA_DO_GRAU.get(rotulo, "BAIXO"), "sem_indice": rotulo not in _FAIXA_DO_GRAU,
        "rotulo_score": "Índice de atenção (soma P×I)",
        "top_flags": [f"Grau {analise.get('emoji', '')} {rotulo}", f"{n} indício(s)"]
                     + [str(a.get("rf")) for a in (analise.get("achados") or [])[:6]],
        "secoes": secoes, "_dados": {"md": md},
        "ressalva": "Indícios para apuração; presunção de legitimidade dos atos administrativos. Pagamento = OB paga "
                    "do SIAFE. Nenhum dado indisponível foi fabricado.",
    })

    def _rodar():
        return asyncio.run(html_to_pdf(html, destino))
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:   # funciona dentro e fora de event loop
        return ex.submit(_rodar).result(timeout=300)


def render_pdf(ctx: dict, destino: str, analise: dict | None = None, md: str | None = None) -> str:
    """PDF do parecer Lex pela régua da casa (`render_html` → `html_to_pdf`); a versão FPDF compacta fica como
    fallback quando o navegador headless não está disponível. `md` opcional reaproveita o parecer de ÓRGÃO."""
    if analise is None:
        from compliance_agent.lex import _analise  # tardio: evita ciclo com a fachada lex.py
        analise = _analise(ctx)
    md = md if md is not None else parecer_md(ctx, analise)
    if os.environ.get("JFN_LEX_PDF_FPDF") != "1":
        try:
            return _pdf_html(ctx, destino, analise, md)
        except Exception as exc:  # noqa: BLE001 — sem Chromium/Playwright: cai no FPDF e diz no log
            logger.warning("PDF do Lex pela régua HTML falhou (%s) — fallback FPDF", str(exc)[:160])
    return _render_pdf_fpdf(ctx, destino, analise, md)


def _render_pdf_fpdf(ctx: dict, destino: str, analise: dict, md: str) -> str:
    from fpdf import FPDF
    rotulo = analise["rotulo"]
    cor = {"VERMELHO": (220, 53, 69), "AMARELO": (255, 150, 0), "VERDE": (40, 167, 69)}.get(rotulo, (90, 90, 90))

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf._fam, pdf._uni = _registrar_fonte(pdf)
    pdf.add_page()

    def _t(s):
        s = s or ""
        # glifos que a DejaVu (Unicode) NÃO possui (emoji de risco, seta ⤴) → equivalentes que ELA possui,
        # senão o fpdf2 emite "missing glyphs" e o PDF entregue mostra tofu. O grau-cor vem da barra colorida.
        if getattr(pdf, "_uni", False):
            return s.replace("🔴", "●").replace("🟡", "●").replace("🟢", "●").replace("⤴", "↗")
        for a, b in (("—", "-"), ("–", "-"), ("·", "-"), ("→", "->"), ("⤴", "->"), ("≥", ">="), ("🟢", ""), ("🟡", ""), ("🔴", "")):
            s = s.replace(a, b)
        return s.encode("latin-1", "replace").decode("latin-1")

    pdf.set_fill_color(20, 30, 50); pdf.set_text_color(255, 255, 255); pdf.set_font(pdf._fam, "B", 15)
    pdf.cell(0, 13, _t("PARECER JURIDICO - CONTROLE EXTERNO"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_font(pdf._fam, "", 9); pdf.set_fill_color(45, 60, 90)
    pdf.cell(0, 7, _t("Avaliação fático-jurídica · Direito Administrativo e Controle Externo (TCU/TCE-RJ)"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.cell(0, 7, _t(f"JFN Intelligence Engine  |  {ctx.get('data','')}"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "B", 14)
    _mc(pdf, 8, _t(ctx.get("nome", "")))
    _ident = f"CNPJ: {fmt_cnpj(ctx.get('cnpj',''))}" if so_digitos(ctx.get("cnpj", "")) else f"Unidade Gestora (UG): {ctx.get('ug','—')}"
    pdf.set_font(pdf._fam, "", 10); pdf.cell(0, 6, _t(_ident), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    pdf.set_fill_color(*cor)
    pdf.set_text_color(0, 0, 0) if rotulo == "AMARELO" else pdf.set_text_color(255, 255, 255)
    pdf.set_font(pdf._fam, "B", 12)
    pdf.cell(0, 9, _t(f"  GRAU DE ATENÇÃO: {rotulo}"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0); pdf.ln(3)
    corpo = md.split("---\n\n", 1)[-1]
    _render_parecer_pdf(pdf, _t, corpo)

    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(destino)
    return destino


