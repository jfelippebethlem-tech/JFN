# -*- coding: utf-8 -*-
"""
LEX — Agente de avaliação jurídica (Direito Administrativo / Controle Externo).

Emite um PARECER fático-jurídico (tomada de contas) sobre a contratação/licitação/pagamentos de um
fornecedor. Lex agora **LÊ A ÍNTEGRA** de cada processo SEI correlacionado (via o leitor do JFN —
Chrome 9222 + OCR de CAPTCHA; fallback no portal público httpx) e cruza o **texto real** dos documentos
(edital, TR, contrato, despachos) com os red flags do controle externo (TCU/TCE-RJ). Classifica o grau de
atenção (🟢 verde / 🟡 amarelo / 🔴 vermelho), com fundamento legal. Base: `docs/LEX-BASE-JURIDICA.md`.

Princípio (cláusula de honestidade): aponta INDÍCIOS a verificar, sob presunção de legitimidade dos atos
administrativos; NUNCA afirma crime/improbidade/dolo (compete ao TCE-RJ/MP-RJ/Judiciário, após contraditório).

É o 3º documento do `/relatorio` (junto do PDF de inteligência e da planilha). Mesma estética do JFN.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from compliance_agent.reporting.inteligencia import (
    _REPORTS, _mc, _registrar_fonte, _render_parecer_pdf, _slug, fmt_cnpj, moeda, so_digitos,
)

# Leitura da íntegra do SEI: liga/desliga, quantos processos ler e orçamento de tempo (s).
_LER_SEI = os.environ.get("JFN_LEX_LER_SEI", "1") != "0"
_MAX_SEI = int(os.environ.get("JFN_LEX_MAX_SEI", "3"))
_SEI_BUDGET = float(os.environ.get("JFN_LEX_SEI_BUDGET", "120"))

# Red flags (resumo operacional; detalhe em docs/LEX-BASE-JURIDICA.md)
_RF = {
    "R2": ("Fracionamento de despesa", "Art. 75 §1º Lei 14.133/2021; Art. 23 §§1º-5º Lei 8.666/93"),
    "R3": ("Pesquisa de preços frágil / possível sobrepreço", "Art. 23 Lei 14.133; Acórdão 1875/2021-TCU (cesta de preços)"),
    "R4": ("Sobrepreço / superfaturamento (valores fora de referência)", "Art. 11 III Lei 14.133; Acórdão 2622/2013-TCU (BDI)"),
    "R5": ("Inexigibilidade/dispensa possivelmente indevida", "Art. 74 Lei 14.133 / Art. 25 Lei 8.666; art. 337-E CP"),
    "R7": ("Restrição de competitividade", "Art. 9º I Lei 14.133; Art. 3º §1º Lei 8.666"),
    "R8": ("Concentração de fornecedor / risco de captura (bid rigging)", "Art. 37 CF/88; Art. 36 §3º I 'd' Lei 12.529; ACFE/OCDE"),
    "R9": ("Aditivos sucessivos acima dos limites", "Arts. 125-126 Lei 14.133; Art. 65 §1º Lei 8.666"),
    "R10": ("Liquidação irregular / pagamento atípico (estornos)", "Arts. 62-63 Lei 4.320/64; Decreto 93.872/86 art. 38"),
    "R12": ("Planejamento de fachada (DFD/ETP/TR genéricos)", "Art. 5º e Art. 18 Lei 14.133"),
}


# Anatomia do achado (modelo TCU/ISSAI/CGU — ver docs/PESQUISA-DIREITO-ADMIN-CGE.md):
# critério × condição → causa → efeito, com evidência e recomendação. Causa/efeito/recomendação por red flag.
_MATRIZ = {
    "R2": ("possível divisão da despesa para fugir da modalidade/teto de dispensa",
           "elisão do dever de licitar; restrição à competição e risco de sobrepreço",
           "consolidar a demanda e licitar; apurar o planejamento (DFD/ETP)"),
    "R3": ("instrução deficiente do valor estimado (sem cesta de preços)",
           "risco de sobrepreço não detectado na contratação",
           "exigir pesquisa/cesta de preços (Acórdão 1875/2021-TCU)"),
    "R4": ("ausência de referência de mercado / BDI fora de parâmetro",
           "potencial dano ao erário por preço acima do mercado",
           "recompor preços e, se confirmado, glosar a diferença"),
    "R5": ("enquadramento possivelmente indevido de contratação direta",
           "afastamento da licitação sem amparo legal robusto",
           "verificar a fundamentação (art. 74/75 Lei 14.133); se indevida, anular"),
    "R7": ("especificação/habilitação restritiva ou direcionada",
           "redução da competitividade; possível direcionamento",
           "revisar o edital; admitir 'ou equivalente' (art. 9º Lei 14.133)"),
    "R8": ("baixa rotatividade/captura de fornecedor por um órgão",
           "risco de cartel/sobrepreço e dependência do prestador",
           "ampliar a competição; cruzar sócios/endereços dos licitantes"),
    "R9": ("execução além do valor contratado (aditivos sucessivos)",
           "elisão do limite de aditivo (25%/50%) e burla à licitação",
           "auditar os aditivos e os limites (arts. 125-126 Lei 14.133)"),
    "R10": ("falha de liquidação/regularização (estornos, OB R$ 0,00)",
            "risco de pagamento sem liquidação regular",
            "conferir ateste e NL (arts. 62-63 Lei 4.320/64)"),
    "R12": ("planejamento de fachada (DFD/ETP/TR genéricos) ou crescimento sem lastro",
            "contratação sem planejamento real; sobre/subdimensionamento",
            "exigir ETP robusto e justificativa da demanda (art. 18 Lei 14.133)"),
}


def _fmt_proc(s: str) -> str:
    """Encurta nº de processo concatenado (a base TCE-RJ às vezes junta vários numa célula)."""
    s = (s or "").strip()
    partes = [p.strip() for p in s.split(",") if p.strip()]
    if len(partes) <= 1:
        return s or "—"
    return f"{partes[0]} (+{len(partes)-1})"


def _anatomia(a: dict) -> dict:
    """Decompõe um indício na anatomia do achado de auditoria (critério/condição/causa/efeito/recomendação)."""
    nome, criterio = _RF.get(a["rf"], (a["rf"], "—"))
    causa, efeito, recom = _MATRIZ.get(a["rf"], ("a apurar", "a apurar", "diligência documental"))
    return {"rf": a["rf"], "nome": nome, "criterio": criterio, "condicao": a["obs"],
            "causa": causa, "efeito": efeito, "recomendacao": recom, "grav": a["grav"]}


def _sei_do_fornecedor(cnpj: str) -> list[dict]:
    try:
        from compliance_agent.correlacao_sei import processos_de_fornecedor
        return processos_de_fornecedor(cnpj)
    except Exception:
        return []


def _contratos_tcerj(cnpj: str) -> list[dict]:
    """Contratos + compras diretas do TCE-RJ Dados Abertos (objeto/critério/valores/dispensa). Fonte que
    NÃO depende do SEI (WAF) — traz o texto oficial do controle externo direto da API pública."""
    try:
        from compliance_agent.collectors.tcerj_aberto import contratos_de_fornecedor
        return contratos_de_fornecedor(cnpj, limite=100)
    except Exception:
        return []


# ── Leitura da ÍNTEGRA dos processos SEI ──────────────────────────────────────

def _run_coro(factory):
    """Roda uma corrotina com segurança, mesmo dentro de um event loop (FastAPI)."""
    import asyncio
    import concurrent.futures
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            return ex.submit(lambda: asyncio.run(factory())).result()
    return asyncio.run(factory())


def _ler_integra_sei(numero: str) -> dict:
    """Lê a íntegra de UM processo SEI (Chrome 9222 + OCR; fallback portal httpx). Cacheia 24h."""
    res = {}
    try:
        from compliance_agent.collectors import sei_cdp
        res = _run_coro(lambda: sei_cdp.ler_processo_sei_via_chrome(numero, usar_cache=True)) or {}
        if not res.get("erro") and (res.get("texto") or res.get("conteudo_documentos")):
            return res
    except Exception as exc:  # noqa: BLE001
        res = {"numero": numero, "erro": f"cdp: {str(exc)[:120]}"}
    # fallback: portal público httpx (metadados + documentos)
    try:
        from compliance_agent.collectors import sei_portal
        meta = _run_coro(lambda: sei_portal.buscar_processo(numero, usar_cache=True)) or {}
        if not meta.get("erro"):
            meta.setdefault("texto", "")
            meta.setdefault("conteudo_documentos", [])
            return meta
    except Exception:
        pass
    return res or {"numero": numero, "erro": "indisponível"}


_WAF_MARCADORES = ("web page blocked", "url you requested has been blocked", "attack id",
                   "página não encontrada", "pagina nao encontrada", "acesso negado")


def _bloqueio_rede(integra: dict) -> str:
    """Detecta página de WAF/erro (o IP da VM é barrado no SEI-RJ). Retorna motivo ou ''."""
    amostra = ((integra.get("texto", "") or "") + " " + (integra.get("title", "") or "")).lower()
    if any(m in amostra for m in _WAF_MARCADORES):
        return ("bloqueio de rede (WAF) — o IP de saída da VM (GCP) não é autorizado pelo SEI-RJ; "
                "ler de um IP permitido/proxy ou preencher o cache externamente")
    return ""


def _texto_integra(integra: dict) -> str:
    if _bloqueio_rede(integra):
        return ""  # página de bloqueio não é conteúdo de processo
    txt = integra.get("texto", "") or ""
    for d in integra.get("conteudo_documentos", []) or []:
        txt += "\n" + (d.get("conteudo", "") or "")
    return txt


def _modalidade(low: str) -> str:
    for chave, rotulo in [
        ("pregão eletrônico", "Pregão eletrônico"), ("pregão", "Pregão"),
        ("concorrência", "Concorrência"), ("inexigibilidade", "Inexigibilidade"),
        ("dispensa de licitação", "Dispensa de licitação"), ("dispensa", "Dispensa"),
        ("credenciamento", "Credenciamento"), ("adesão", "Adesão a ata (carona)"),
        ("registro de preços", "Registro de preços"),
    ]:
        if chave in low:
            return rotulo
    return "—"


def _analisar_conteudo_sei(integra: dict) -> tuple[list, dict]:
    """Red flags a partir do TEXTO REAL do processo. Retorna (achados, resumo)."""
    txt = _texto_integra(integra)
    low = txt.lower()
    achados: list[dict] = []
    modal = _modalidade(low)

    objeto = ""
    m = re.search(r"objeto[:\s]+([A-Z0-9À-Ú][^\n.;]{15,180})", txt, re.I)
    if m:
        objeto = m.group(1).strip()

    if txt.strip():
        # R5 — contratação direta sem prova robusta de exclusividade/singularidade
        if "dispensa" in low or "inexigibil" in low:
            tem_just = any(k in low for k in [
                "exclusividade", "singular", "notória especialização", "notoria especializacao",
                "inviabilidade de competição", "inviabilidade de competicao", "art. 74", "artigo 74",
            ])
            achados.append({"rf": "R5", "grav": 2 if tem_just else 3,
                            "obs": f"O processo registra **{modal if modal != '—' else 'contratação direta'}**" +
                                   ("." if tem_just else
                                    " — no texto lido **não localizei** prova robusta de exclusividade/singularidade "
                                    "(art. 74 Lei 14.133/Art. 25 Lei 8.666).")})
        # R3 — sem pesquisa/cesta de preços visível
        if any(k in low for k in ["edital", "contrato", "termo de referência", "termo de referencia"]) and \
           not any(k in low for k in ["pesquisa de preç", "cesta de preç", "mapa de preç", "cotaç", "orçament"]):
            achados.append({"rf": "R3", "grav": 2,
                            "obs": "No texto lido **não localizei** pesquisa/cesta de preços (Acórdão 1875/2021-TCU) — "
                                   "verificar a instrução do ETP/valor estimado."})
        # R9 — aditivos
        n_adit = low.count("termo aditivo") + low.count("aditamento")
        if n_adit >= 2:
            achados.append({"rf": "R9", "grav": 2,
                            "obs": f"{n_adit} menções a termo aditivo/aditamento no processo — verificar se a soma "
                                   "respeita os limites de 25%/50% (arts. 125-126 Lei 14.133)."})
        # R7 — restrição/direcionamento por especificação
        if any(k in low for k in ["atestado de capacidade", "marca", "modelo "]) and "ou equivalente" not in low:
            achados.append({"rf": "R7", "grav": 2,
                            "obs": "Há exigências de habilitação/especificação (atestado/marca) sem a cláusula "
                                   "'ou equivalente' visível — verificar restrição à competitividade (art. 9º Lei 14.133)."})

    resumo = {
        "numero": integra.get("numero", ""),
        "objeto": objeto,
        "modalidade": modal,
        "tipo": integra.get("tipo", "") or integra.get("title", ""),
        "n_docs": len(integra.get("documentos", []) or []),
        "n_docs_lidos": len(integra.get("conteudo_documentos", []) or []),
        "cnpjs": (integra.get("cnpjs", []) or [])[:8],
        "valores": (integra.get("valores", []) or [])[:8],
        "url": integra.get("url", ""),
        "lido": bool(txt.strip()),
        "de_cache": bool(integra.get("_de_cache") or integra.get("_cached_at")),
        "erro": integra.get("erro", "") or _bloqueio_rede(integra),
    }
    return achados, resumo


def _merge_achados(lst: list[dict]) -> list[dict]:
    """Funde achados por red flag (mantém maior gravidade, concatena observações)."""
    por: dict = {}
    for a in lst:
        k = a["rf"]
        if k not in por:
            por[k] = dict(a)
        else:
            if a["grav"] > por[k]["grav"]:
                por[k]["grav"] = a["grav"]
            if a["obs"] not in por[k]["obs"]:
                por[k]["obs"] += " " + a["obs"]
    return sorted(por.values(), key=lambda x: -x["grav"])


# ── Análise dos contratos/compras do TCE-RJ (Dados Abertos — não depende do SEI) ──

def _analisar_contratos_tcerj(itens: list[dict]) -> tuple[list, dict]:
    """Red flags a partir dos contratos/compras diretas oficiais do TCE-RJ. Retorna (achados, resumo).

    Esta é a fonte que CONTORNA o bloqueio de WAF do SEI: traz objeto, critério de julgamento, valores e —
    sobretudo — o **EnquadramentoLegal** das compras diretas (dispensa/inexigibilidade) direto da API pública."""
    achados: list[dict] = []
    contratos = [i for i in itens if i.get("_tipo") == "contrato"]
    compras = [i for i in itens if i.get("_tipo") == "compra_direta"]

    soma_contr = sum(c.get("valor_contrato") or 0 for c in contratos)
    soma_compras = sum(c.get("valor") or 0 for c in compras)

    # R5 — contratações diretas (dispensa/inexigibilidade) registradas no TCE-RJ
    diretas = [c for c in compras if any(
        k in ((c.get("afastamento") or "") + " " + (c.get("enquadramento_legal") or "")).lower()
        for k in ["dispensa", "inexigibil"])]
    if diretas:
        total_d = sum(c.get("valor") or 0 for c in diretas)
        grav = 3 if len(diretas) >= 5 else 2
        achados.append({"rf": "R5", "grav": grav,
                        "obs": f"O TCE-RJ registra **{len(diretas)} contratação(ões) direta(s)** (dispensa/"
                               f"inexigibilidade) deste fornecedor, somando R$ {moeda(total_d)} — verificar o "
                               "enquadramento legal e a regularidade da fundamentação (art. 74/75 Lei 14.133/Art. 24-25 Lei 8.666)."})

    # R2 — fracionamento: muitas compras diretas no MESMO ano e MESMA unidade (indício de divisão de despesa)
    from collections import Counter
    ano_unid = Counter((c.get("ano_processo"), (c.get("unidade") or "")[:40]) for c in diretas)
    repet = [(k, n) for k, n in ano_unid.items() if n >= 3]
    if repet:
        pior = max(repet, key=lambda x: x[1])
        achados.append({"rf": "R2", "grav": 3,
                        "obs": f"{pior[1]} contratações diretas no mesmo exercício ({pior[0][0]}) e na mesma unidade "
                               f"(**{pior[0][1]}**) — possível **fracionamento de despesa** para se manter abaixo do "
                               "teto de dispensa (art. 75 §1º Lei 14.133)."})

    # R9 — execução acima do contratado (valor pago > contrato + 25%, limite de aditivo)
    for c in contratos:
        vc, vp = c.get("valor_contrato") or 0, c.get("valor_pago") or 0
        if vc > 0 and vp > vc * 1.25:
            achados.append({"rf": "R9", "grav": 2,
                            "obs": f"Contrato {c.get('processo')}: pago R$ {moeda(vp)} sobre valor contratado "
                                   f"R$ {moeda(vc)} (+{((vp-vc)/vc*100):.0f}%) — verificar aditivos e o limite de "
                                   "25%/50% (arts. 125-126 Lei 14.133)."})
            break  # um exemplo basta para o indício

    resumo = {
        "n_contratos": len(contratos), "soma_contratos": soma_contr,
        "n_compras_diretas": len(compras), "soma_compras": soma_compras,
        "n_diretas_dispensa": len(diretas),
        "contratos": contratos[:15], "compras": compras[:15],
    }
    return achados, resumo


# ── Detecção data-driven (carteira de pagamentos) ─────────────────────────────

def _detectar(ctx: dict) -> list[dict]:
    """Indícios a partir dos dados financeiros (OBs). Cada item: {rf, obs, grav(1-5)}."""
    p = ctx.get("pagamentos") or {}
    achados = []
    if not p.get("tem_dados"):
        return achados
    hhi = p.get("hhi", {})
    top = hhi.get("top_share", 0) or 0
    org_top = next(iter(p.get("por_orgao_geral", {})), "—")
    if top >= 60:
        achados.append({"rf": "R8", "grav": 4,
                        "obs": f"{top:.1f}% do valor pago concentrado em um único órgão (**{org_top}**) — "
                               "concentração extrema para um prestador de serviços."})
    elif top >= 40:
        achados.append({"rf": "R8", "grav": 3, "obs": f"Concentração relevante ({top:.1f}%) em **{org_top}**."})
    anos = p.get("anos", [])
    if len(anos) >= 2:
        t0 = p["por_ano"][anos[0]]["total"] or 0
        t1 = p["por_ano"][anos[-1]]["total"] or 0
        if t0 > 0 and t1 > t0 * 3:
            achados.append({"rf": "R12", "grav": 3,
                            "obs": f"Crescimento abrupto dos pagamentos de R$ {moeda(t0)} ({anos[0]}) para "
                                   f"R$ {moeda(t1)} ({anos[-1]}) — {((t1-t0)/t0*100):+.0f}%."})
    zeros = sum(1 for a in anos for ln in p["por_ano"][a]["linhas"] if ln["valor"] == 0)
    if zeros >= 3:
        achados.append({"rf": "R10", "grav": 2,
                        "obs": f"{zeros} ordens bancárias de valor R$ 0,00 (estornos/regularizações) — verificar a regularidade da liquidação."})
    if (p.get("total_geral") or 0) >= 50_000_000 and len(p.get("por_orgao_geral", {})) >= 6:
        achados.append({"rf": "R2", "grav": 2,
                        "obs": f"Volume expressivo (R$ {moeda(p['total_geral'])}) pulverizado em {len(p['por_orgao_geral'])} órgãos — "
                               "verificar se há fracionamento ou contratações por dispensa abaixo do teto."})
    if ctx.get("risco") == "ALTO":
        achados.append({"rf": "R8", "grav": 2, "obs": f"Rating de risco corporativo ALTO (score {ctx.get('score')}/100) — diligência sobre quadro societário/vínculos."})
    return achados


def _grau(achados: list) -> tuple:
    """(emoji, rótulo, justificativa) conforme convergência + gravidade dos indícios."""
    n = len(achados)
    gmax = max((a["grav"] for a in achados), default=0)
    if n >= 3 and gmax >= 4:
        return "🔴", "VERMELHO", "convergência de 3+ indícios, ao menos um grave — recomenda-se controle externo"
    if n >= 1 and (gmax >= 4 or n >= 2):
        return "🟡", "AMARELO", "indícios pontuais a esclarecer mediante diligência"
    if n >= 1:
        return "🟡", "AMARELO", "indício isolado de baixa gravidade"
    return "🟢", "VERDE", "sem indícios relevantes nos dados disponíveis — presunção de regularidade mantida"


def _analise(ctx: dict, ler_sei: bool | None = None) -> dict:
    """Computa TODA a análise UMA vez (lê o SEI uma vez) e devolve o dossiê para md/pdf."""
    cnpj = ctx.get("cnpj", "")
    sei = _sei_do_fornecedor(cnpj)
    ach_dados = _detectar(ctx)

    # Onda 2 — contratos/compras do TCE-RJ (não dependem do SEI/WAF)
    itens_tcerj = _contratos_tcerj(cnpj)
    ach_tcerj, resumo_tcerj = _analisar_contratos_tcerj(itens_tcerj)

    leituras: list[dict] = []
    ach_doc: list[dict] = []
    fazer_leitura = _LER_SEI if ler_sei is None else ler_sei
    if fazer_leitura and sei:
        t0 = time.monotonic()
        for s in sei[:_MAX_SEI]:
            if time.monotonic() - t0 > _SEI_BUDGET:
                break
            integra = _ler_integra_sei(s.get("numero_sei", ""))
            ach, resumo = _analisar_conteudo_sei(integra)
            resumo["n_obs"] = s.get("n_obs")
            resumo["total"] = s.get("total")
            leituras.append(resumo)
            ach_doc.extend(ach)

    achados = _merge_achados(ach_dados + ach_doc + ach_tcerj)
    emoji, rotulo, just = _grau(achados)
    return {"cnpj": cnpj, "sei": sei, "leituras": leituras, "achados": achados,
            "tem_leitura_doc": bool(ach_doc), "tcerj": resumo_tcerj,
            "emoji": emoji, "rotulo": rotulo, "just": just}


def parecer_md(ctx: dict, analise: dict | None = None) -> str:
    if analise is None:
        analise = _analise(ctx)
    cnpj = analise["cnpj"]
    sei = analise["sei"]
    leituras = analise["leituras"]
    achados = analise["achados"]
    emoji, rotulo, just = analise["emoji"], analise["rotulo"], analise["just"]
    tcerj = analise.get("tcerj") or {}
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
    if achados:
        for a in achados:
            nome, fund = _RF.get(a["rf"], (a["rf"], ""))
            add(f"### {a['rf']} — {nome}")
            add(f"- **Observação:** {a['obs']}")
            add(f"- **Fundamento:** {fund}")
            add("- **Contraponto (presunção de regularidade):** o fato pode ter explicação legítima (objeto técnico, "
                "demanda concentrada por competência institucional). Não há, aqui, juízo de irregularidade.")
            add("- **Diligência sugerida:** confrontar com edital (especificações), pesquisa de preços, mapa de "
                "licitantes/sócios, atestos e aditivos do processo SEI.")
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

    # V. Conclusão
    add("## V. CONCLUSÃO — GRAU DE ATENÇÃO")
    add("")
    add(f"**{emoji} {rotulo}.** {just[0].upper()+just[1:]}.")
    add("")

    # VI. Recomendações
    add("## VI. RECOMENDAÇÕES DE ENCAMINHAMENTO")
    add("")
    add("- **Diligência documental:** confrontar, nos processos SEI, o edital/TR (especificações), a pesquisa "
        "de preços (cesta — Acórdão 1875/2021-TCU), o mapa de licitantes (sócios/endereços) e os atestos/medições.")
    add("- **Controle externo:** havendo indício de dano, representar ao **TCE-RJ** (jurisdição sobre a despesa estadual).")
    add("- **Demais órgãos:** ciência ao **MP-RJ** (improbidade) e ao **CADE** (conluio/bid rigging, Lei 12.529) se cabível; "
        "PAR (Lei 12.846) e ciência à **CGE-RJ** (controle interno).")
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
        "Base jurídica: docs/LEX-BASE-JURIDICA.md. Não substitui parecer jurídico formal._")
    return "\n".join(L)


def render_pdf(ctx: dict, destino: str, analise: dict | None = None) -> str:
    """PDF do parecer Lex — mesma estética do JFN (capa azul + texto corrido)."""
    from fpdf import FPDF
    if analise is None:
        analise = _analise(ctx)
    md = parecer_md(ctx, analise)
    rotulo = analise["rotulo"]
    cor = {"VERMELHO": (220, 53, 69), "AMARELO": (255, 150, 0), "VERDE": (40, 167, 69)}.get(rotulo, (90, 90, 90))

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf._fam, pdf._uni = _registrar_fonte(pdf)
    pdf.add_page()

    def _t(s):
        s = s or ""
        if getattr(pdf, "_uni", False):
            return s
        for a, b in (("—", "-"), ("–", "-"), ("·", "-"), ("→", "->"), ("≥", ">="), ("🟢", ""), ("🟡", ""), ("🔴", "")):
            s = s.replace(a, b)
        return s.encode("latin-1", "replace").decode("latin-1")

    pdf.set_fill_color(20, 30, 50); pdf.set_text_color(255, 255, 255); pdf.set_font(pdf._fam, "B", 15)
    pdf.cell(0, 13, _t("PARECER JURÍDICO — AGENTE LEX"), fill=True, ln=True, align="C")
    pdf.set_font(pdf._fam, "", 9); pdf.set_fill_color(45, 60, 90)
    pdf.cell(0, 7, _t("Avaliação fático-jurídica · Direito Administrativo e Controle Externo (TCU/TCE-RJ)"), fill=True, ln=True, align="C")
    pdf.cell(0, 7, _t(f"JFN Intelligence Engine  |  {ctx.get('data','')}"), fill=True, ln=True, align="C")
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "B", 14)
    _mc(pdf, 8, _t(ctx.get("nome", "")))
    pdf.set_font(pdf._fam, "", 10); pdf.cell(0, 6, _t(f"CNPJ: {fmt_cnpj(ctx.get('cnpj',''))}"), ln=True)
    pdf.ln(2)
    pdf.set_fill_color(*cor)
    pdf.set_text_color(0, 0, 0) if rotulo == "AMARELO" else pdf.set_text_color(255, 255, 255)
    pdf.set_font(pdf._fam, "B", 12)
    pdf.cell(0, 9, _t(f"  GRAU DE ATENÇÃO: {rotulo}"), fill=True, ln=True)
    pdf.set_text_color(0, 0, 0); pdf.ln(3)
    corpo = md.split("---\n\n", 1)[-1]
    _render_parecer_pdf(pdf, _t, corpo)

    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(destino)
    return destino


def gerar(ctx: dict, salvar: bool = True, ler_sei: bool | None = None) -> dict:
    """Gera o parecer Lex (md + pdf). Lê a íntegra do SEI UMA vez. Retorna {ok, grau, n_indicios, n_sei_lidos, path_lex_pdf, path_lex_md}."""
    analise = _analise(ctx, ler_sei=ler_sei)
    n_lidos = sum(1 for l in analise["leituras"] if l.get("lido"))
    out = {"ok": True, "grau": analise["rotulo"], "n_indicios": len(analise["achados"]),
           "n_sei": len(analise["sei"]), "n_sei_lidos": n_lidos, "path_lex_pdf": "", "path_lex_md": ""}
    if salvar:
        base = f"parecer_lex_{_slug(ctx.get('nome','')) or so_digitos(ctx.get('cnpj',''))}_{ctx.get('data','')}"
        md_path = _REPORTS / f"{base}.md"
        md_path.write_text(parecer_md(ctx, analise), encoding="utf-8")
        out["path_lex_md"] = str(md_path)
        try:
            out["path_lex_pdf"] = render_pdf(ctx, str(_REPORTS / f"{base}.pdf"), analise)
        except Exception as exc:  # noqa: BLE001
            out["_pdf_erro"] = str(exc)[:160]
    return out
