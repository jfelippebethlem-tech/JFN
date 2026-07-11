"""
Consultas gratuitas a fontes jurídicas na internet.

Fontes integradas (todas 100% gratuitas, sem chave de API):
  LexML    — lexml.gov.br/urn  (normas e jurisprudência federais)
  Planalto — www.planalto.gov.br/ccivil_03  (texto integral das leis)
  JusBrasil — busca pública por URL de pesquisa
  TCE-RJ   — portal.tce.rj.gov.br/consultas
  TCU      — pesquisa.apps.tcu.gov.br

Uso principal:
  - Busca o texto integral de um artigo de lei para citar com precisão
  - Busca acórdãos públicos por palavra-chave
  - Complementa a base curada de base_legal.py e jurisprudencia.py
"""

import asyncio
import re

import httpx

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

_TIMEOUT = 20


# ─── LexML — normas e jurisprudência ─────────────────────────────────────────

async def buscar_lexml(termo: str, max_resultados: int = 5) -> list[dict]:
    """
    Busca no LexML (lexml.gov.br) por normas e jurisprudência federais.
    Retorna lista de {titulo, urn, tipo, data, link}.
    """
    url = "https://www.lexml.gov.br/busca/SolrService"
    params = {
        "q": termo,
        "rows": max_resultados,
        "start": 0,
        "wt": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return []
            data = resp.json()
            docs = data.get("response", {}).get("docs", [])
            resultados = []
            for d in docs:
                resultados.append({
                    "titulo": d.get("titulo", ""),
                    "urn": d.get("urn", ""),
                    "tipo": d.get("tipoDocumento", ""),
                    "data": d.get("dataPublicacao", ""),
                    "link": f"https://www.lexml.gov.br/urn/{d.get('urn','')}",
                })
            return resultados
    except Exception:
        return []


async def buscar_lexml_jurisprudencia(termo: str, tribunal: str = "") -> list[dict]:
    """
    Busca jurisprudência no LexML filtrando por tribunal.
    tribunal: "TCU", "STJ", "STF", "TRF" etc.
    """
    q = f"{termo} {tribunal}".strip()
    resultados = await buscar_lexml(q, max_resultados=8)
    # Filtra apenas jurisprudência
    return [r for r in resultados if "jurisprudencia" in r.get("tipo", "").lower()
            or "acordao" in r.get("tipo", "").lower()
            or "sumula" in r.get("titulo", "").lower()]


# ─── Planalto — texto integral das leis ──────────────────────────────────────

_PLANALTO_URLS = {
    "14133": "https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2021/lei/l14133.htm",
    "8666":  "https://www.planalto.gov.br/ccivil_03/leis/l8666cons.htm",
    "8429":  "https://www.planalto.gov.br/ccivil_03/leis/l8429compilado.htm",
    "12846": "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2013/lei/l12846.htm",
    "101":   "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp101.htm",
    "12527": "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2011/lei/l12527.htm",
    "4320":  "https://www.planalto.gov.br/ccivil_03/leis/l4320.htm",
    "10028": "https://www.planalto.gov.br/ccivil_03/leis/l10028.htm",
}


async def buscar_artigo_planalto(lei: str, artigo: str) -> str:
    """
    Busca o texto de um artigo específico no Planalto.
    lei: número da lei ("14133", "8666", "8429", "12846", etc.)
    artigo: número do artigo ("art. 7", "art. 23", etc.)

    Retorna o trecho de texto encontrado ou string vazia.
    """
    url = _PLANALTO_URLS.get(lei.replace(".", "").replace("/", "").replace("-", ""))
    if not url:
        return ""

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS,
                                      follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return ""
            html = resp.text

            # Remove tags HTML para texto limpo
            texto = re.sub(r"<[^>]+>", " ", html)
            texto = re.sub(r"\s+", " ", texto)

            # Localiza o artigo
            art_num = re.sub(r"[^\d]", "", artigo)
            padrao = rf"Art\.?\s*{art_num}[\.\º]?\s"
            match = re.search(padrao, texto, re.IGNORECASE)
            if not match:
                return ""

            inicio = match.start()
            trecho = texto[inicio: inicio + 800].strip()
            return trecho
    except Exception:
        return ""


async def texto_lei_resumido(lei: str) -> str:
    """
    Retorna uma descrição curta sobre uma lei pelo número.
    Usado quando não encontra no Planalto.
    """
    resumos = {
        "14133": "Lei 14.133/2021 — Nova Lei de Licitações e Contratos Administrativos.",
        "8666":  "Lei 8.666/1993 — Lei Geral de Licitações (em vigor subsidiariamente).",
        "8429":  "Lei 8.429/1992 — Lei de Improbidade Administrativa.",
        "12846": "Lei 12.846/2013 — Lei Anticorrupção (responsabilidade objetiva de empresas).",
        "101":   "Lei Complementar 101/2000 — Lei de Responsabilidade Fiscal.",
        "12527": "Lei 12.527/2011 — Lei de Acesso à Informação (LAI).",
        "4320":  "Lei 4.320/1964 — Normas gerais de direito financeiro.",
        "10028": "Lei 10.028/2000 — Crimes contra as finanças públicas.",
    }
    return resumos.get(lei.replace(".", "").replace("/", "").replace("-", ""), "")


# ─── TCU — Jurisprudência Selecionada ────────────────────────────────────────

async def buscar_tcu(termo: str, max_resultados: int = 5) -> list[dict]:
    """
    Busca na API pública de Jurisprudência Selecionada do TCU.
    Retorna lista de {numero, tipo, ementa, link}.
    """
    # API de busca textual do TCU
    api_url = "https://pesquisa.apps.tcu.gov.br/resultado/acordao-completo"
    params = {
        "term": termo,
        "tipo": "ACORDAO_COMPLETO",
        "pageSize": max_resultados,
        "pageNumber": 0,
        "sort": "RELEVANCIA",
        "selecionado": "acordao-completo",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers={
            **_HEADERS,
            "Accept": "application/json",
            "Referer": "https://pesquisa.apps.tcu.gov.br/",
        }) as client:
            resp = await client.get(api_url, params=params)
            if resp.status_code != 200:
                return []
            data = resp.json()
            docs = data.get("content", []) or data.get("results", [])
            resultados = []
            for d in docs:
                num = d.get("numero", "") or d.get("NumAcordao", "")
                ano = d.get("ano", "") or d.get("AnoAcordao", "")
                tipo = d.get("tipo", "Acórdão")
                ementa = (d.get("ementa", "") or d.get("Ementa", ""))[:400]
                resultados.append({
                    "numero": f"Acórdão {num}/{ano}-Plenário" if num else str(d)[:80],
                    "tipo": tipo,
                    "ementa": ementa,
                    "link": f"https://pesquisa.apps.tcu.gov.br/#/documento/acordao-completo"
                            f"/%2520NUMACORDAO%253A{num}%2520ANOACORDAO%253A{ano}",
                })
            return resultados
    except Exception:
        return []


# ─── TCE-RJ — Consulta de acórdãos ───────────────────────────────────────────

async def buscar_tce_rj(termo: str, max_resultados: int = 5) -> list[dict]:
    """
    Busca acórdãos no portal do TCE-RJ (busca textual pública).
    Retorna lista de {numero, ementa, link}.
    """
    url = "https://www1.tce.rj.gov.br/scripts/cgi-bin/owa/portal_tce.cgi"
    params = {
        "PARG": termo,
        "TIPO": "ACORDAO",
        "PESQ": "S",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS,
                                      follow_redirects=True) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return _buscar_tce_rj_fallback(termo)
            html = resp.text
            # Extrai acórdãos via regex simples
            matches = re.findall(
                r'Acórdão\s+n?[oº°]?\s*([\d\.]+/\d{4})[^"]*"([^"]{10,300})"',
                html, re.IGNORECASE
            )
            resultados = []
            for numero, ementa in matches[:max_resultados]:
                resultados.append({
                    "numero": f"Acórdão {numero} TCE-RJ",
                    "ementa": ementa[:300],
                    "link": f"https://www1.tce.rj.gov.br/scripts/cgi-bin/owa/portal_tce.cgi?TIPO=ACORDAO&PARG={numero}",
                })
            return resultados if resultados else _buscar_tce_rj_fallback(termo)
    except Exception:
        return _buscar_tce_rj_fallback(termo)


def _buscar_tce_rj_fallback(termo: str) -> list[dict]:
    """Retorna acórdãos da base local curada quando o portal não responde."""
    from compliance_agent.knowledge.jurisprudencia import buscar_acordaos
    acordaos = buscar_acordaos(texto=termo, orgao="TCE-RJ")[:5]
    return [
        {
            "numero": ac.numero,
            "ementa": ac.ementa[:300],
            "link": "https://www.tce.rj.gov.br/jurisprudencia",
        }
        for ac in acordaos
    ]


# ─── Busca unificada (todas as fontes) ───────────────────────────────────────

async def buscar_juridico(termo: str) -> dict:
    """
    Busca consolidada em todas as fontes jurídicas gratuitas.
    Retorna {leis, tcu, tce_rj, lexml} com os resultados.
    """
    # Executa buscas em paralelo
    resultados_tcu, resultados_tce, resultados_lexml = await asyncio.gather(
        buscar_tcu(termo, max_resultados=3),
        buscar_tce_rj(termo, max_resultados=3),
        buscar_lexml(termo, max_resultados=3),
        return_exceptions=True,
    )

    # Fallback: se o resultado for uma exceção, usa lista vazia
    if isinstance(resultados_tcu, Exception):
        resultados_tcu = []
    if isinstance(resultados_tce, Exception):
        resultados_tce = []
    if isinstance(resultados_lexml, Exception):
        resultados_lexml = []

    # Também busca na base curada local
    from compliance_agent.knowledge.jurisprudencia import buscar_acordaos
    from compliance_agent.knowledge.base_legal import buscar_lei
    acordaos_local = buscar_acordaos(texto=termo)[:3]
    leis_local = buscar_lei(termo)

    return {
        "leis": leis_local,
        "acordaos_locais": [
            {"numero": ac.numero, "orgao": ac.orgao, "ementa": ac.ementa[:250]}
            for ac in acordaos_local
        ],
        "tcu": resultados_tcu,
        "tce_rj": resultados_tce,
        "lexml": resultados_lexml,
    }


def formatar_resultado_juridico(resultado: dict) -> str:
    """
    Formata o resultado de buscar_juridico para envio via Telegram.
    """
    linhas = ["*⚖️ Consulta jurídica:*\n"]

    if resultado.get("leis"):
        linhas.append("*Legislação (base local):*")
        for lei in resultado["leis"][:3]:
            linhas.append(
                f"• *{lei['lei']} art. {lei['artigo']}* — {lei['resumo'][:100]}"
            )

    if resultado.get("acordaos_locais"):
        linhas.append("\n*Jurisprudência (base local):*")
        for ac in resultado["acordaos_locais"]:
            linhas.append(f"• [{ac['orgao']}] {ac['numero']}\n  _{ac['ementa'][:120]}_")

    if resultado.get("tcu"):
        linhas.append("\n*TCU — resultados online:*")
        for r in resultado["tcu"][:2]:
            linhas.append(f"• {r.get('numero','')}\n  _{r.get('ementa','')[:120]}_")

    if resultado.get("tce_rj"):
        linhas.append("\n*TCE-RJ — resultados online:*")
        for r in resultado["tce_rj"][:2]:
            linhas.append(f"• {r.get('numero','')}\n  _{r.get('ementa','')[:120]}_")

    if len(linhas) == 1:
        return "Nenhum resultado jurídico encontrado para esse termo."

    return "\n".join(linhas)
