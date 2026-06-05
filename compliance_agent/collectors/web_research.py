"""
Pesquisa na internet sobre pessoas e CNPJs — investigação aberta (OSINT).

Investiga uma pessoa ou empresa cruzando:
  - DuckDuckGo (busca web, sem API key, sem custo)
  - BrasilAPI (dados cadastrais do CNPJ, sem key)
  - Notícias (DuckDuckGo News)
  - Resumo inteligente com LLM gratuito (Groq/Hermes)

Tudo gratuito e sem chave. Usado para enriquecer OBs de alto valor e
respondendo ao comando /investigar no Telegram.
"""

import asyncio
import re
from datetime import date
from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# Termos que indicam risco quando aparecem associados a uma pessoa/empresa
_TERMOS_RISCO = [
    "fraude", "corrupção", "corrupcao", "lavagem", "propina", "desvio",
    "investigação", "investigacao", "operação", "operacao", "preso",
    "condenado", "improbidade", "superfaturamento", "cartel", "laranja",
    "denúncia", "denuncia", "mpf", "mprj", "polícia federal", "policia federal",
    "tcu", "tce", "inidônea", "inidonea", "sancionada", "bloqueio",
]


# ─── Busca web (DuckDuckGo HTML, sem key) ─────────────────────────────────────

async def buscar_ddg(termo: str, max_resultados: int = 8) -> list[dict]:
    """Busca no DuckDuckGo (endpoint HTML). Retorna [{titulo, url, trecho}]."""
    url = "https://html.duckduckgo.com/html/"
    resultados = []
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.post(url, data={"q": termo}, headers=_HEADERS)
            if r.status_code != 200:
                return []
            soup = BeautifulSoup(r.text, "html.parser")
            for res in soup.select(".result")[:max_resultados]:
                a = res.select_one(".result__a")
                snippet = res.select_one(".result__snippet")
                if not a:
                    continue
                resultados.append({
                    "titulo": a.get_text(strip=True),
                    "url": a.get("href", ""),
                    "trecho": snippet.get_text(strip=True) if snippet else "",
                })
    except Exception:
        pass
    return resultados


async def buscar_noticias(termo: str, max_resultados: int = 6) -> list[dict]:
    """Busca notícias recentes via DuckDuckGo News (sem key)."""
    url = "https://duckduckgo.com/news.js"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            # vqd token necessário — fallback para busca HTML com "notícia"
            r = await client.get(
                "https://duckduckgo.com/",
                params={"q": termo}, headers=_HEADERS,
            )
            m = re.search(r'vqd=["\']?([\d-]+)', r.text)
            if m:
                vqd = m.group(1)
                rn = await client.get(url, params={
                    "q": termo, "vqd": vqd, "l": "br-pt", "noamp": "1",
                }, headers=_HEADERS)
                data = rn.json()
                return [
                    {"titulo": n.get("title", ""), "url": n.get("url", ""),
                     "trecho": n.get("excerpt", ""), "fonte": n.get("source", ""),
                     "data": n.get("date", "")}
                    for n in data.get("results", [])[:max_resultados]
                ]
    except Exception:
        pass
    # Fallback: busca HTML com palavra "notícia"
    return await buscar_ddg(f"{termo} notícia", max_resultados)


# ─── Dados cadastrais do CNPJ (BrasilAPI) ─────────────────────────────────────

async def consultar_cnpj(cnpj: str) -> Optional[dict]:
    """Consulta dados cadastrais do CNPJ na BrasilAPI (sem key)."""
    cnpj_limpo = re.sub(r"\D", "", cnpj)
    if len(cnpj_limpo) != 14:
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}",
                headers=_HEADERS,
            )
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return None


# ─── Investigação completa ────────────────────────────────────────────────────

def _detectar_riscos(textos: list[str]) -> list[str]:
    """Procura termos de risco nos textos coletados."""
    achados = set()
    blob = " ".join(textos).lower()
    for termo in _TERMOS_RISCO:
        if termo in blob:
            achados.add(termo)
    return sorted(achados)


async def investigar(alvo: str, cnpj: str = "") -> dict:
    """
    Investiga uma pessoa ou empresa na internet.
    Retorna dossiê: dados cadastrais, web, notícias, riscos detectados, resumo.
    """
    dossie = {
        "alvo": alvo,
        "cnpj": cnpj,
        "cadastro": None,
        "web": [],
        "noticias": [],
        "riscos_detectados": [],
        "resumo": "",
    }

    # 1. Cadastro do CNPJ (se for empresa)
    if cnpj:
        dossie["cadastro"] = await consultar_cnpj(cnpj)
        await asyncio.sleep(0.3)

    # 2. Busca web + notícias em paralelo
    termo_busca = f'"{alvo}"'
    web, noticias = await asyncio.gather(
        buscar_ddg(termo_busca, 8),
        buscar_noticias(alvo, 6),
    )
    dossie["web"] = web
    dossie["noticias"] = noticias

    # 3. Detecta termos de risco
    textos = (
        [r.get("titulo", "") + " " + r.get("trecho", "") for r in web]
        + [n.get("titulo", "") + " " + n.get("trecho", "") for n in noticias]
    )
    dossie["riscos_detectados"] = _detectar_riscos(textos)

    # 4. Resumo com LLM gratuito
    dossie["resumo"] = await _resumir_dossie(dossie)
    return dossie


async def _resumir_dossie(dossie: dict) -> str:
    """Pede ao LLM um resumo investigativo do que foi coletado."""
    try:
        from compliance_agent.llm.free_llm import (
            groq_chat_async, groq_available,
            openrouter_chat_async, openrouter_available,
        )
    except Exception:
        return ""

    cad = dossie.get("cadastro") or {}
    cad_txt = ""
    if cad:
        cad_txt = (
            f"Razão social: {cad.get('razao_social','')}; "
            f"Situação: {cad.get('descricao_situacao_cadastral','')}; "
            f"Abertura: {cad.get('data_inicio_atividade','')}; "
            f"CNAE: {cad.get('cnae_fiscal_descricao','')}; "
            f"Capital: {cad.get('capital_social','')}; "
            f"Sócios: {', '.join(s.get('nome_socio','') for s in cad.get('qsa', [])[:5])}"
        )

    web_txt = "\n".join(
        f"- {r['titulo']}: {r['trecho'][:150]}" for r in dossie["web"][:6]
    )
    not_txt = "\n".join(
        f"- {n['titulo']}: {n.get('trecho','')[:150]}" for n in dossie["noticias"][:5]
    )

    system = (
        "Você é um investigador de compliance público. Escreva um resumo "
        "investigativo CURTO (máx 800 caracteres) sobre o alvo, destacando "
        "qualquer sinal de risco, irregularidade ou conexão suspeita. "
        "Se não houver nada relevante, diga que nada relevante foi encontrado. "
        "Não invente — use só o que foi coletado."
    )
    prompt = (
        f"ALVO: {dossie['alvo']}\n"
        f"CADASTRO: {cad_txt or 'N/D'}\n"
        f"RISCOS NOS TEXTOS: {', '.join(dossie['riscos_detectados']) or 'nenhum'}\n\n"
        f"RESULTADOS WEB:\n{web_txt or 'nada'}\n\n"
        f"NOTÍCIAS:\n{not_txt or 'nada'}\n\n"
        "Faça o resumo investigativo."
    )
    try:
        if groq_available():
            return await groq_chat_async(prompt, system=system, smart=True)
        if openrouter_available():
            return await openrouter_chat_async(prompt, system=system, smart=True)
    except Exception:
        pass
    # Fallback sem LLM
    if dossie["riscos_detectados"]:
        return ("⚠️ Termos de risco encontrados: "
                + ", ".join(dossie["riscos_detectados"]))
    return "Nada de risco evidente encontrado na busca web."


def formatar_dossie_telegram(dossie: dict) -> str:
    """Formata o dossiê para envio no Telegram."""
    linhas = [f"🔎 *Investigação: {dossie['alvo']}*\n"]

    cad = dossie.get("cadastro")
    if cad:
        sit = cad.get("descricao_situacao_cadastral", "")
        emoji = "🔴" if sit.upper() in ("BAIXADA", "SUSPENSA", "INAPTA") else "🟢"
        linhas.append(
            f"{emoji} *{cad.get('razao_social','')}*\n"
            f"  Situação: {sit}\n"
            f"  Abertura: {cad.get('data_inicio_atividade','')}\n"
            f"  Atividade: {cad.get('cnae_fiscal_descricao','')[:60]}\n"
            f"  Capital: R$ {cad.get('capital_social','?')}"
        )
        socios = cad.get("qsa", [])
        if socios:
            nomes = ", ".join(s.get("nome_socio", "") for s in socios[:4])
            linhas.append(f"  Sócios: {nomes}")

    if dossie["riscos_detectados"]:
        linhas.append(f"\n🚨 *Termos de risco:* {', '.join(dossie['riscos_detectados'])}")

    if dossie["resumo"]:
        linhas.append(f"\n📋 *Análise:*\n{dossie['resumo'][:900]}")

    if dossie["noticias"]:
        linhas.append("\n📰 *Notícias:*")
        for n in dossie["noticias"][:3]:
            linhas.append(f"• {n['titulo'][:80]}")

    return "\n".join(linhas)


# ─── Investigação automática de OBs de alto valor ─────────────────────────────

async def investigar_obs_alto_valor(session, target_date: date = None,
                                    valor_minimo: float = 500_000.0,
                                    max_alvos: int = 5) -> list[dict]:
    """
    Investiga na internet os favorecidos de OBs de altíssimo valor do dia.
    Gera alertas quando encontra termos de risco.
    """
    from compliance_agent.database.models import OrdemBancaria, Alerta

    target_date = target_date or date.today()
    obs = (
        session.query(OrdemBancaria)
        .filter(
            OrdemBancaria.data_emissao == target_date,
            OrdemBancaria.valor >= valor_minimo,
            OrdemBancaria.favorecido_nome.isnot(None),
        )
        .order_by(OrdemBancaria.valor.desc())
        .limit(max_alvos)
        .all()
    )

    alertas = []
    for ob in obs:
        nome = (ob.favorecido_nome or "").strip()
        if not nome:
            continue
        cnpj = re.sub(r"\D", "", str(ob.favorecido_cpf or ""))
        dossie = await investigar(nome, cnpj if len(cnpj) == 14 else "")
        await asyncio.sleep(1.0)

        if dossie["riscos_detectados"]:
            titulo = f"[WEB] Risco em investigação aberta — {nome}"[:300]
            existe = session.query(Alerta).filter_by(titulo=titulo).first()
            if not existe:
                session.add(Alerta(
                    tipo="investigacao_web",
                    severidade="alta",
                    titulo=titulo,
                    descricao=(
                        f"OB {ob.numero_ob} (R$ {ob.valor:,.2f}) para '{nome}'. "
                        f"Busca na internet encontrou termos de risco: "
                        f"{', '.join(dossie['riscos_detectados'])}. "
                        f"Resumo: {dossie['resumo'][:400]}"
                    ),
                    evidencias=str([n.get("url") for n in dossie["noticias"][:5]]),
                    data_referencia=target_date,
                    ordem_bancaria_id=ob.id,
                ))
                alertas.append({"ob": ob.numero_ob, "favorecido": nome,
                                "riscos": dossie["riscos_detectados"]})

        # Aprende o perfil
        try:
            from compliance_agent.llm.memoria import registrar_entidade
            registrar_entidade(nome, {
                "riscos_web": dossie["riscos_detectados"],
                "investigado_em": [target_date.isoformat()],
            }, session=session)
        except Exception:
            pass

    session.commit()
    return alertas
