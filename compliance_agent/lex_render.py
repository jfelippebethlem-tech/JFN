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

from compliance_agent.reporting.inteligencia import (
    _mc, _registrar_fonte, _render_parecer_pdf, fmt_cnpj, moeda, so_digitos,
)
from compliance_agent.lex_redflags import (
    _RF, _anatomia, _eh_servico_continuo, _elemento_subjetivo, _fmt_proc,
)

def _analise_merito(ctx: dict, analise: dict) -> str:
    """Prosa de mérito (parecer raciocinado), adaptada aos dados — natureza, concentração, dispensas, síntese."""
    p = ctx.get("pagamentos") or {}
    emp = (ctx.get("enriq", {}).get("dados") or {}).get("empresa") or {}
    achados = analise.get("achados", [])
    continuo = _eh_servico_continuo([emp.get("cnae_principal"), emp.get("atividade"), ctx.get("nome")])
    total = p.get("total_geral", 0) or 0
    nob, norg = p.get("n_geral", 0), len(p.get("por_orgao_geral", {}))
    L = []
    try:
        from compliance_agent.lex_base_empirica import contexto_empirico_md
        _emp = contexto_empirico_md(ctx.get("cnpj"))
        if _emp:
            L.append(_emp)
    except Exception as exc:
        logger.warning("contexto empírico do Lex indisponível p/ %s (seção some do parecer): %s", ctx.get("cnpj"), exc)
    natureza = ("prestadora de **serviços contínuos** (limpeza/conservação/vigilância/mão de obra)"
                if continuo else "fornecedora do Estado")
    L.append(
        f"Trata-se de empresa {natureza}, com exposição de **R$ {moeda(total)}** em {nob} ordens bancárias "
        f"junto a {norg} órgão(s) no período. " + (
            "Para esse segmento, a presença em múltiplos órgãos — cada um com contrato próprio, em regra por pregão "
            "e com vigência de até 10 anos (arts. 106-107 da Lei 14.133/2021) — é a **estrutura ordinária do "
            "mercado** e não evidencia, por si só, irregularidade." if continuo else
            "A pulverização entre órgãos, isoladamente, não indica irregularidade."))
    hhi = p.get("hhi", {})
    if hhi.get("top_share", 0):
        L.append(
            f"A concentração (HHI) é **{hhi.get('indice')}** ({hhi.get('nivel')}), com o maior órgão respondendo por "
            f"**{hhi.get('top_share')}%** do valor pago. " + (
                "Concentração elevada num único contratante, ainda que possa decorrer de mérito técnico, recomenda "
                "conferir a competitividade dos certames e a isonomia (art. 37 CF/88; art. 5º Lei 14.133)."
                if hhi.get("top_share", 0) >= 50 else
                "O grau é compatível com atuação difusa, sem alerta específico de captura."))
    tcerj = analise.get("tcerj") or {}
    if tcerj.get("n_diretas_dispensa"):
        L.append(
            f"O TCE-RJ registra **{tcerj.get('n_diretas_dispensa')} contratação(ões) por dispensa/inexigibilidade**. " + (
                "Em serviços contínuos, a dispensa emergencial costuma cobrir o intervalo entre o fim de um contrato e "
                "a conclusão de novo pregão — regular quando justificada e temporária. O exame deve focar a reiteração "
                "do **mesmo objeto/local** sob o teto, que aí sim configuraria fracionamento (art. 75 §1º Lei 14.133)."
                if continuo else
                "Cabe verificar o enquadramento legal de cada uma e eventual sucessão do mesmo objeto sob o teto."))
    graves = [a for a in achados if a.get("grav", 0) >= 3]
    L.append(
        (f"Em síntese, convergem **{len(achados)} indício(s)**, {len(graves)} de maior gravidade, sustentando a "
         f"classificação **{analise.get('rotulo')}**. " if achados
         else "Em síntese, não há indícios relevantes nos dados disponíveis. ") +
        "Reitere-se que os apontamentos são **indícios** sob **presunção de legitimidade** dos atos administrativos "
        "(o ônus de provar o vício recai sobre quem o invoca — Meirelles); a confirmação depende de diligência "
        "documental nos processos SEI (edital/TR, pesquisa de preços, atestos) e de contraditório. Este parecer **não** "
        "constitui juízo de irregularidade, improbidade ou crime.")
    return "\n\n".join(L)


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
    add("*O Lex pesquisou as dúvidas abertas na internet (busca web, notícias, Diário Oficial/Querido Diário, "
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
    add("*Bateria de hipóteses investigativas (cadastro Receita + base JFN/OBs + OSINT). Base legal: controle "
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


def parecer_md(ctx: dict, analise: dict | None = None) -> str:
    if analise is None:
        from compliance_agent.lex import _analise  # tardio: evita ciclo com a fachada lex.py
        analise = _analise(ctx)
    cnpj = analise["cnpj"]
    sei = analise["sei"]
    leituras = analise["leituras"]
    achados = analise["achados"]
    emoji, rotulo, just = analise["emoji"], analise["rotulo"], analise["just"]
    tcerj = analise.get("tcerj") or {}
    cartel = analise.get("cartel") or {}
    cruzado = analise.get("cruzado") or {}
    exculpatorio = analise.get("exculpatorio") or []
    destinatarios = analise.get("destinatarios") or []
    # 1º item exculpatório por RF (p/ III-B refletir o rebaixamento a 'monitoramento' quando a defesa sobrevive).
    _exc_por_rf = {}
    for _e in exculpatorio:
        _exc_por_rf.setdefault(_e.get("rf"), _e)
    p = ctx.get("pagamentos") or {}
    lidos = [l for l in leituras if l.get("lido")]
    L = []
    add = L.append

    add(f"# PARECER JURÍDICO PRELIMINAR — {ctx.get('nome','')}")
    add("### Lex · Avaliação fático-jurídica de contratação, licitação e pagamentos")
    add("")
    add("*Tomada de contas preliminar — Direito Administrativo e Controle Externo (TCU/TCE-RJ)*")
    add("")
    add(f"**CNPJ:** {fmt_cnpj(cnpj)}  |  **Data:** {ctx.get('data','')}  |  **Analista:** Agente Lex (JFN)")
    classif = "COM Achado" if achados else "SEM Achado"
    add(f"**Classificação (modelo CGE-RJ — Decreto 47.408/2020):** Nota Técnica **{classif}**.")
    add(f"**Grau de atenção:** {emoji} **{rotulo}** — {just}.")
    add("")
    add("---")
    add("")

    # I. Identificação
    add("## I. IDENTIFICAÇÃO")
    add("")
    add(f"- **Fornecedor:** {ctx.get('nome','')} (CNPJ {fmt_cnpj(cnpj)})")
    if p.get("tem_dados"):
        add(f"- **Exposição:** R$ {moeda(p['total_geral'])} em {p['n_geral']} OBs, {len(p.get('por_orgao_geral',{}))} órgãos, "
            f"exercícios {', '.join(map(str, p.get('anos', [])))}")
    add(f"- **Processos SEI vinculados (origem das OBs):** {len(sei)} identificado(s) na base correlacionada (SIAFE); "
        f"**{len(lidos)} lido(s) na íntegra** nesta análise.")
    add("")

    # II. Fatos
    add("## II. FATOS — processos administrativos")
    add("")
    if sei:
        add("Cada Ordem Bancária remete a um processo SEI (DFD → ETP → TR/edital → contrato → empenho → liquidação → OB). "
            "Processos vinculados a este fornecedor:")
        add("")
        add("| Processo SEI | Nº de OBs | Valor pago (R$) |")
        add("|---|---:|---:|")
        for s in sei[:25]:
            add(f"| {s.get('numero_sei')} | {s.get('n_obs')} | {moeda(s.get('total'))} |")
        add("")
    else:
        add("> Ainda não há processos SEI correlacionados a este CNPJ na base. **Diligência:** rodar a coleta SIAFE "
            "(tela OB Orçamentária) e a correlação para puxar os processos.")
        add("")

    # II-B. Leitura da íntegra
    add("## II-B. LEITURA DOS PROCESSOS SEI (íntegra)")
    add("")
    if lidos:
        add(f"Lex abriu e leu o inteiro teor de **{len(lidos)} processo(s)** no sistema SEI-RJ (pesquisa pública), "
            "extraindo objeto, modalidade, documentos, partes (CNPJs) e valores:")
        add("")
        for l in lidos:
            add(f"### Processo {l.get('numero')}")
            if l.get("tipo"):
                add(f"- **Tipo/título:** {l['tipo']}")
            if l.get("objeto"):
                add(f"- **Objeto (lido):** {l['objeto']}")
            add(f"- **Modalidade/fundamento aparente:** {l.get('modalidade','—')}")
            add(f"- **Documentos no processo:** {l.get('n_docs',0)} (lidos na íntegra: {l.get('n_docs_lidos',0)})")
            if l.get("cnpjs"):
                add(f"- **CNPJs no processo:** {', '.join(l['cnpjs'][:6])}")
            if l.get("valores"):
                add(f"- **Valores citados:** {', '.join(l['valores'][:6])}")
            add(f"- **OBs deste processo:** {l.get('n_obs','—')} (R$ {moeda(l.get('total'))})")
            add("")
    else:
        nao = [l for l in leituras if not l.get("lido")]
        if nao:
            motivos = "; ".join(f"{l.get('numero')}: {l.get('erro') or 'sem texto'}" for l in nao[:5])
            add(f"> A leitura automática não retornou o inteiro teor nesta execução ({motivos}). Causas comuns: "
                "CAPTCHA não resolvido pelo OCR, processo restrito/sigiloso, ou Chrome de leitura (9222) indisponível. "
                "**Diligência:** reexecutar a leitura (o cache é preenchido) ou abrir manualmente.")
        else:
            add("> Não houve leitura de íntegra nesta execução (sem processos correlacionados ou leitura desabilitada).")
        add("")

    # II-C. Contratos e compras diretas no TCE-RJ (Dados Abertos — independe do SEI/WAF)
    add("## II-C. CONTRATOS E COMPRAS DIRETAS — TCE-RJ (Dados Abertos)")
    add("")
    if tcerj.get("n_contratos") or tcerj.get("n_compras_diretas"):
        add(f"A base de **Dados Abertos do TCE-RJ** (controle externo) registra, para este fornecedor, "
            f"**{tcerj.get('n_contratos',0)} contrato(s)** (R$ {moeda(tcerj.get('soma_contratos',0))}) e "
            f"**{tcerj.get('n_compras_diretas',0)} compra(s) direta(s)** (R$ {moeda(tcerj.get('soma_compras',0))}), "
            f"dos quais **{tcerj.get('n_diretas_dispensa',0)} por dispensa/inexigibilidade**. Esta fonte é oficial e "
            "não depende da leitura do SEI.")
        add("")
        if tcerj.get("contratos"):
            add("**Contratos formais (maiores por valor):**")
            add("")
            add("| Processo | Ano | Objeto | Critério | Valor contrato (R$) | Unidade |")
            add("|---|---:|---|---|---:|---|")
            for c in tcerj["contratos"][:12]:
                obj = (c.get("objeto") or "").strip()
                obj = (obj[:55] + "…") if len(obj) > 55 else (obj or "—")
                add(f"| {_fmt_proc(c.get('processo',''))} | {c.get('ano_processo','')} | {obj} | "
                    f"{c.get('criterio_julgamento') or '—'} | {moeda(c.get('valor_contrato'))} | "
                    f"{(c.get('unidade') or '')[:30]} |")
            add("")
        if tcerj.get("compras"):
            add("**Compras diretas (dispensa/inexigibilidade — fundamento legal citado):**")
            add("")
            add("| Processo | Ano | Objeto | Afastamento | Enquadramento legal | Valor (R$) |")
            add("|---|---:|---|---|---|---:|")
            for c in tcerj["compras"][:12]:
                obj = (c.get("objeto") or "").strip()
                obj = (obj[:45] + "…") if len(obj) > 45 else (obj or "—")
                enq = (c.get("enquadramento_legal") or "").strip()
                enq = (enq[:55] + "…") if len(enq) > 55 else (enq or "—")
                add(f"| {_fmt_proc(c.get('processo',''))} | {c.get('ano_processo','')} | {obj} | "
                    f"{c.get('afastamento') or '—'} | {enq} | {moeda(c.get('valor'))} |")
            add("")
    else:
        add("> Não há contratos nem compras diretas deste CNPJ na base de Dados Abertos do TCE-RJ. Isso pode "
            "ocorrer quando a contratação é municipal, federal, ou ainda não publicada — **diligência:** confirmar "
            "no PNCP e no próprio processo SEI.")
        add("")

    # II-D. Rede fornecedor↔órgão (Onda 3 — indício de rodízio/cartel)
    vz = cartel.get("vizinhos") or []
    if vz:
        add("## II-D. REDE FORNECEDOR–ÓRGÃO (indício de rodízio/cartel)")
        add("")
        add(f"O favorecido atua em **{cartel.get('n_orgaos',0)} órgão(s)**. Outros fornecedores **não-ubíquos** "
            "(excluídas utilities/tributos) que atuam nos **mesmos** órgãos — co-ocorrência estreita é indício de "
            "rodízio/cartel (bid rigging, art. 36 Lei 12.529) a **verificar** (sócios, endereços, datas de proposta):")
        add("")
        add("| Fornecedor co-ocorrente | Órgãos em comum | Footprint total | Valor nesses órgãos (R$) |")
        add("|---|---:|---:|---:|")
        for v in vz[:8]:
            add(f"| {(v.get('nome') or '')[:40]} | {v.get('orgaos_comuns')} | {v.get('footprint_total')} | "
                f"{moeda(v.get('valor_nos_orgaos'))} |")
        add("")
        add("> Co-ocorrência **não prova** conluio (podem ser do mesmo ramo legítimo). É ponto de diligência: "
            "cruzar quadro societário (QSA), endereços e a cronologia das propostas nas licitações comuns.")
        add("")
        # cruzamento por sócio (Onda 4) — quando há QSA ingerido
        match = cruzado.get("co_ocorrencia_com_socio_comum") or []
        if match:
            add("**⚠ Indício forte — co-ocorrência COM sócio em comum (QSA):**")
            add("")
            add("| Fornecedor | Órgãos em comum | Sócio(s) compartilhado(s) |")
            add("|---|---:|---|")
            for m in match[:6]:
                add(f"| {(m.get('nome') or '')[:38]} | {m.get('orgaos_comuns')} | {(m.get('socios_comuns') or '')[:50]} |")
            add("")
            add("> Compartilhar sócio **e** atuar nos mesmos órgãos eleva o indício (possível cartel/laranja/"
                "empresas-irmãs — art. 337-F CP; art. 36 Lei 12.529). Diligência: confirmar no contrato social e nas atas.")
            add("")

    # II-E. Investigação de Due Diligence (fachada/laranja) — o Lex apresenta a investigação que conduziu.
    inv = analise.get("investigacao") or {}
    _secao_investigacao(add, inv, cnpj=so_digitos(ctx.get("cnpj", "")))

    # II-E.2. Auditoria de contrato contínuo (bateria T01–T22) — só renderiza se houver acervo de contrato.
    _secao_auditoria_contrato(add, analise.get("auditoria_contrato") or {})

    # II-F. Direcionamento de licitação (parecer LLM on-demand) — SURFACE do veredito dos top-score.
    _secao_direcionamento(add, analise.get("direcionamento"))

    # II-G. Pesquisa-internet (Fase 5) — dúvidas pesquisadas, aprendizado e re-ajuste (SURFACE).
    _secao_pesquisa(add, analise.get("pesquisa"))

    # II-G.1. Aprendizado cruzado — padrões em fornecedores ligados (mesmos sócios/veículos), SURFACE.
    _secao_padroes_ligados(add, (analise.get("pesquisa") or {}).get("cruzado") or "")

    # III. Matriz de Achados + análise por red flag
    add("## III. MATRIZ DE ACHADOS (anatomia do achado de auditoria)")
    add("")
    add("*Modelo TCU/ISSAI/CGU: **critério × condição → causa → efeito**, com evidência e recomendação "
        "(ver `docs/PESQUISA-DIREITO-ADMIN-CGE.md`).*")
    add("")
    if achados:
        add("| # | Critério (norma) | Condição (situação) | Causa provável | Efeito potencial | Recomendação |")
        add("|---|---|---|---|---|---|")
        for an in (_anatomia(a) for a in achados):
            cond = an["condicao"].replace("**", "").replace("|", "/")
            cond = (cond[:90] + "…") if len(cond) > 90 else cond
            crit = (an["criterio"][:55] + "…") if len(an["criterio"]) > 55 else an["criterio"]
            add(f"| {an['rf']} | {crit} | {cond} | {an['causa']} | {an['efeito']} | {an['recomendacao']} |")
        add("")
        add("> **Evidência** de todos os achados: Ordens Bancárias (SIAFE/TFE) e contratos/compras diretas do "
            "TCE-RJ (Dados Abertos); quando lida, a íntegra do processo SEI. **Conclusão:** os itens acima são "
            "**indícios** que sustentam a classificação como Nota Técnica COM Achado, sujeitos a contraditório.")
    else:
        add("> **Nota Técnica SEM Achado** — não há indício que sustente um achado. Mantém-se a presunção de "
            "regularidade dos atos administrativos.")
    add("")

    # III-B. Detalhe por indício
    add("## III-B. DETALHAMENTO DOS INDÍCIOS (red flags do controle externo)")
    add("")
    if analise.get("tem_leitura_doc"):
        add("*Indícios marcados abaixo combinam os dados financeiros (OBs) com a **leitura do inteiro teor** dos processos.*")
        add("")
    # Os indícios DD/* (fachada/laranja) são apresentados na seção II-E (não duplicar aqui).
    achados_rf = [a for a in achados if not str(a.get("rf", "")).startswith("DD/")]
    if achados_rf:
        for a in achados_rf:
            nome, fund = _RF.get(a["rf"], (a["rf"], ""))
            add(f"### {a['rf']} — {nome}")
            add(f"- **Observação:** {a['obs']}")
            add(f"- **Fundamento:** {fund}")
            # Análise discursiva (onde no documento + por quê o mecanismo), ancorada no trecho real do SEI.
            if a.get("analise"):
                add(f"- **Análise (onde e por quê):** {a['analise']}")
                if a.get("trecho"):
                    add(f"  > _Trecho do processo {a.get('numero_proc','')}:_ «{a['trecho'][:300]}»")
            add("- **Diligência sugerida:** confrontar com edital (especificações), pesquisa de preços, mapa de "
                "licitantes/sócios, atestos e aditivos do processo SEI.")
            # Encaminhamento por severidade (o que FAZER com este indício) — dirige a ação, não só descreve.
            # Respeita o passo exculpatório: achado cuja defesa inocente SOBREVIVE → rebaixado a monitoramento.
            g = a.get("grav", 0)
            _exc = _exc_por_rf.get(a.get("rf"))
            if _exc and _exc.get("sobrevive"):
                add(f"- **Encaminhamento:** gravidade {g}/5 — a explicação inocente mais plausível **não foi "
                    "refutada** pelos dados (ver passo exculpatório); rebaixado a **monitoramento**, não representação.")
            elif g >= 3:
                add(f"- **⤴ Encaminhamento:** indício relevante (gravidade {g}/5) — cabe **requerimento** ao órgão "
                    "exigindo a justificativa documental; persistindo a dúvida, representação ao TCE-RJ/MP-RJ.")
            else:
                add(f"- **Encaminhamento:** gravidade {g}/5 — manter em diligência/monitoramento; reavaliar com mais dados.")
            add("")
    elif any(str(a.get("rf", "")).startswith("DD/") for a in achados):
        add("Nenhum indício a partir dos dados financeiros/documentais; os achados desta análise são de "
            "**fachada/laranja** e estão detalhados na seção II-E (Investigação de Due Diligence).")
        add("")
    else:
        add("Nenhum indício automático disparou a partir dos dados financeiros nem da leitura documental disponível. "
            "Mantém-se a presunção de regularidade.")
        add("")

    # IV. Matriz P×I
    add("## IV. MATRIZ DE RISCO (P × I — metodologia TCU)")
    add("")
    add("| Indício | P (1-5) | I (1-5) | Score | Faixa |")
    add("|---|---:|---:|---:|---|")
    for a in achados:
        nome = _RF.get(a["rf"], (a["rf"], ""))[0]
        pp = min(5, 2 + a["grav"] // 2); ii = a["grav"]
        sc = pp * ii
        faixa = "Baixo" if sc <= 4 else "Médio" if sc <= 9 else "Alto" if sc <= 14 else "Extremo"
        add(f"| {a['rf']} {nome} | {pp} | {ii} | {sc} | {faixa} |")
    if not achados:
        add("| — | — | — | — | — |")
    add("")

    # III-C. Triagem por indicadores de risco de fraude (lex_indicadores_fraude)
    try:
        from compliance_agent import lex_indicadores_fraude as _lif
        _sinais = _lif.sinais_do_contexto(ctx, analise)
        add(_lif.parecer_indicadores_md(_lif.triagem(_sinais)))
        add("")
    except Exception as exc:
        logger.warning("triagem de indicadores de fraude falhou (seção III-C some do parecer): %s", exc)

    # IV-B. Análise de mérito (parecer raciocinado)
    add("## IV-B. ANÁLISE DE MÉRITO")
    add("")
    add(_analise_merito(ctx, analise))
    add("")

    # IV-D. Defesa contra si mesmo (passo exculpatório obrigatório) — protege a credibilidade do parecer.
    add("## IV-D. DEFESA CONTRA SI MESMO — PASSO EXCULPATÓRIO")
    add("")
    add("*Para cada indício, a **explicação inocente mais plausível** e se os dados a refutam. Achado cuja "
        "defesa **não é refutada** pelos dados fica apenas como **monitoramento** — não representação "
        "(presunção de legitimidade; a dúvida sobre a economicidade favorece o gestor).*")
    add("")
    if exculpatorio:
        add("| Indício | Explicação inocente mais plausível | Os dados refutam? | Encaminhamento |")
        add("|---|---|---|---|")
        for e in exculpatorio:
            nome = _RF.get(e.get("rf"), (e.get("rf"), ""))[0]
            defesa = (e.get("defesa") or "").replace("|", "/")
            defesa = (defesa[:120] + "…") if len(defesa) > 120 else defesa
            refuta = "**Sim** — defesa afastada" if not e.get("sobrevive") else "Não — defesa plausível"
            enc = "monitoramento" if e.get("sobrevive") else "representação"
            add(f"| {e.get('rf')} {nome} | {defesa} | {refuta} | **{enc}** |")
        add("")
        _monit = [e for e in exculpatorio if e.get("sobrevive")]
        if _monit:
            add(f"> **{len(_monit)} indício(s)** tiveram a explicação inocente considerada **plausível** (não "
                "refutada pelos dados) e foram **rebaixados a monitoramento**, não representação. "
                "Isso preserva a credibilidade do parecer: indício ≠ acusação.")
        else:
            add("> Em todos os indícios os **dados refutam** a explicação inocente (convergência/cruzamento "
                "confirmatório) — sustentam encaminhamento, não mero monitoramento.")
    else:
        add("> Sem indícios a submeter ao passo exculpatório — presunção de regularidade mantida.")
    add("")

    # IV-B-bis. Triagem ilegalidade × improbidade (elemento subjetivo) — doutrina §5.1 / Lei 14.230/2021.
    # Conservador: separa o que é controle de contas (a maioria) do que TOCA improbidade (só com sinal de dolo).
    if achados:
        add("### Triagem: ilegalidade × improbidade (elemento subjetivo)")
        add("")
        add("*Doutrina (Garcia & Pacheco Alves; Medina Osório): **ilegalidade é o gênero; improbidade é a espécie "
            "qualificada pelo DOLO**. Pós-Lei 14.230/2021 não há improbidade culposa; o art. 10 exige **dano efetivo "
            "comprovado** (não in re ipsa); o art. 11 é rol taxativo. O Lex aponta INDÍCIO a apurar — não afirma dolo.*")
        add("")
        add("| Indício | Elemento subjetivo (triagem) | Encaminhamento doutrinário |")
        add("|---|---|---|")
        _n_dolo = 0
        for a in achados:
            rf = a.get("rf", "")
            nome = _RF.get(rf, (rf, ""))[0]
            classe, _ = _elemento_subjetivo(a)
            if classe.startswith("dolo"):
                _n_dolo += 1
                enc = "improbidade (MP-RJ) — *a apurar dolo + dano efetivo*"
            else:
                enc = "**controle de contas (TCE-RJ)** — não improbidade"
            add(f"| {rf} {nome} | {classe} | {enc} |")
        add("")
        if _n_dolo == 0:
            add("> **Nenhum indício com sinal de dolo.** Pela cláusula-mãe e pela Lei 14.230/2021, o conjunto é "
                "**ilegalidade/irregularidade a apurar em controle de contas (TCE-RJ)** — NÃO improbidade. "
                "Presunção de legitimidade; a dúvida sobre a economicidade favorece o gestor.")
        else:
            add(f"> {_n_dolo} indício(s) com **sinal de elemento subjetivo** (apurar dolo + dano antes de cogitar "
                "improbidade); os demais são controle de contas. Indício ≠ acusação.")
        add("")

    # IV-C. Proposta preliminar de sanção administrativa (dosimetria — lex_sancoes)
    # CALIBRAGEM (auditoria 2026-06-18): a dosimetria só incide sobre achados cuja
    # defesa foi REFUTADA pelos dados (representação). Achados rebaixados a
    # monitoramento (explicação inocente plausível) NÃO entram na base de sanção —
    # senão um parecer 🟡 de indícios fracos projeta multa grave (ex.: R$27 mi sem
    # dolo nem dano efetivo), violando indício≠acusação e a doutrina (sanção exige
    # convergência + materialidade/dolo, não indício estatístico isolado).
    try:
        from compliance_agent import lex_sancoes
        _monit_rfs = {e.get("rf") for e in (exculpatorio or []) if e.get("sobrevive")}
        _achados_sancao = [a for a in achados if a.get("rf") not in _monit_rfs]
        if _achados_sancao:
            _valor_sancao = (ctx.get("pagamentos") or {}).get("total_geral") or 0
            _prop_sancao = lex_sancoes.sugerir_sancoes(_achados_sancao, valor_contrato=_valor_sancao, regime="14133")
            add(lex_sancoes.parecer_sancionatorio_md(_prop_sancao))
            add("")
        else:
            add("## IV-C. Proposta preliminar de sanção administrativa")
            add("")
            add("> **Não se propõe sanção nesta fase.** Todos os indícios tiveram a explicação inocente "
                "considerada **plausível** (passo exculpatório) e permanecem como **monitoramento**, não "
                "representação. Sanção administrativa pressupõe achado com defesa **afastada pelos dados** e, "
                "para multa, **dano efetivo mensurado** ou **dolo indiciado** — ausentes aqui. Indício ≠ acusação.")
            add("")
    except Exception as exc:
        logger.warning("seção IV-C (sanção) falhou e some do parecer: %s", exc)

    # V. Conclusão
    add("## V. CONCLUSÃO — GRAU DE ATENÇÃO")
    add("")
    add(f"**{emoji} {rotulo}.** {just[0].upper()+just[1:]}.")
    add("")

    # VI. Recomendações
    add("## VI. RECOMENDAÇÕES DE ENCAMINHAMENTO")
    add("")
    # Destinatário recomendado por tipo/família de achado (conluio→MP+CADE · débito→TCE/TCU · improbidade/penal→MP · PAR→CGU/CGE).
    if destinatarios:
        add("**Destinatário recomendado** (derivado das famílias dos achados presentes):")
        add("")
        add("| Destinatário | Fundamento / tipo de achado |")
        add("|---|---|")
        for d in destinatarios:
            add(f"| **{d.get('destinatario')}** | {d.get('motivo')} |")
        add("")
        add("> O roteamento acima segue o enquadramento do playbook (conluio/cartel → MP + CADE; débito/cautelar → "
            "TCE-RJ/TCU; improbidade/penal → MP; PAR anticorrupção → CGU/CGE) e **não** antecipa juízo de mérito — "
            "o encaminhamento concreto observa o passo exculpatório (seção IV-D).")
        add("")
    else:
        add("> **Destinatário recomendado:** nenhum encaminhamento específico — sem achado que indique competência "
            "de controle externo, MP, CADE ou CGE (presunção de regularidade).")
        add("")
    add("- **Diligência documental:** confrontar, nos processos SEI, o edital/TR (especificações), a pesquisa "
        "de preços (cesta — Acórdão 1875/2021-TCU), o mapa de licitantes (sócios/endereços) e os atestos/medições.")
    add("- **Controle externo:** havendo indício de dano, representar ao **TCE-RJ** (jurisdição sobre a despesa estadual).")
    add("- **Demais órgãos:** ciência ao **MP-RJ** (improbidade) e ao **CADE** (conluio/bid rigging, Lei 12.529) se cabível; "
        "PAR (Lei 12.846) e ciência à **CGE-RJ** (controle interno).")
    add("  > Cautela na qualificação de improbidade (Lei 8.429/92 pós-Lei 14.230/2021): exige-se **dolo** nos "
        "arts. 9/10/11 (**STF Tema 1199, ARE 843989/PR**) e, no **art. 10**, **dano efetivo** — fim do dano presumido "
        "(**STJ REsp 1.929.685/TO**, 1ª T., 2024). O Lex aponta o indício; a tipificação é do MP-RJ/Judiciário.")
    add("  > Esfera penal (referência, não imputação): desvios podem tangenciar **CP arts. 312 (peculato), 316 "
        "(concussão), 317 (corrupção passiva), 333 (corrupção ativa)** e os crimes licitatórios da **Lei 14.133, "
        "arts. 337-E a 337-P**. Dispensa/inexigibilidade irregular hoje é **art. 337-E CP** (ex-art. 89/8.666 — "
        "*continuidade típica*, STJ REsp 2.069.436, não abolitio). Confirmar conduta e dolo antes de qualquer juízo.")
    add("  > Base normativa estadual (RJ): Lei 14.133 regulamentada pelo **Decreto 47.680/2021** + **Resoluções "
        "SEPLAG 179/180/2023** e **PGE 4.937/2023**; controle interno na **CGE-RJ** (Lei 7.989/2018); o rito de "
        "Tomada de Contas é a **Deliberação TCE-RJ 279/2017**, cujo **art. 7º** exige apenas *elementos que indiquem* "
        "— o mesmo limiar de **indício** deste parecer.")
    add("")

    # VII. Ressalvas
    add("## VII. RESSALVAS")
    add("")
    add("> 1. Os apontamentos são **INDÍCIOS**, sujeitos a contraditório e ampla defesa. "
        "2. Vigora a **presunção de legitimidade** dos atos administrativos (dúvida sobre economicidade favorece o gestor — "
        "TCE-RJ, Proc. 101.922-9/12). 3. Lex **não afirma crime, improbidade ou dolo** — competência do TCE-RJ, MP-RJ e "
        "Judiciário. 4. Conclusões limitadas aos dados/documentos analisados; lacunas geram **diligência**, não condenação. "
        "5. A leitura automática do SEI extrai texto público; trechos podem faltar por OCR/restrição — sempre confirmar na fonte.")
    add("")
    add(f"_Parecer gerado automaticamente pelo Agente Lex (JFN) em {ctx.get('data','')}. "
        "Base jurídica: docs/LEX-BASE-JURIDICA.md + docs/PESQUISA-DIREITO-ADMIN-DOUTRINA-RJ.md "
        "(doutrina, improbidade pós-14.230, controle e RJ — CERJ arts. 122-123). Não substitui parecer jurídico formal._")
    return "\n".join(L)


def render_pdf(ctx: dict, destino: str, analise: dict | None = None, md: str | None = None) -> str:
    """PDF do parecer Lex — mesma estética do JFN (capa azul + texto corrido). `md` opcional permite
    reaproveitar a estética para o parecer de ÓRGÃO (sem recomputar o fornecedor)."""
    from fpdf import FPDF
    if analise is None:
        from compliance_agent.lex import _analise  # tardio: evita ciclo com a fachada lex.py
        analise = _analise(ctx)
    md = md if md is not None else parecer_md(ctx, analise)
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
    pdf.cell(0, 13, _t("PARECER JURÍDICO — AGENTE LEX"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
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


