"""
Clientes para LLMs gratuitos compatíveis com a API OpenAI.

Provedores suportados:
  - Groq          : llama-3.1-8b-instant, llama-3.3-70b-versatile, mixtral-8x7b
                    Grátis com limite de taxa. Chave em: https://console.groq.com
  - OpenRouter    : acesso gratuito a Hermes-3, Gemma-2, Mistral e outros modelos
                    Grátis (modelos ":free"). Chave em: https://openrouter.ai
  - Ollama        : roda 100% local, offline, sem custo. Ver compliance_agent/llm/local.py

Hierarquia de uso no LLMRouter:
  1. Ollama        — local, sem internet, sem conta
  2. Groq          — cloud grátis, muito rápido, precisa de chave
  3. OpenRouter    — cloud grátis, modelos maiores (Hermes 405B!), precisa de chave
  4. Claude        — apenas para análises complexas que realmente precisam

Configure as chaves no .env:
  GROQ_API_KEY=gsk_...
  OPENROUTER_API_KEY=sk-or-...
  FREE_LLM_PREFER=groq          # groq | openrouter | ollama (qual usar primeiro)
"""

import asyncio
import json
import os
import random
import re
import time
from typing import Optional

import httpx

# ── Configuração ──────────────────────────────────────────────────────────────

GROQ_API_KEY        = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_API_KEY  = os.environ.get("OPENROUTER_API_KEY", "")
FREE_LLM_PREFER     = os.environ.get("FREE_LLM_PREFER", "groq").lower()

# Modelos padrão por provedor
GROQ_MODEL_FAST     = "llama-3.1-8b-instant"          # rápido, gratuito
GROQ_MODEL_SMART    = "llama-3.3-70b-versatile"        # mais capaz, gratuito

# Hermes-3 (NousResearch) 405B — completamente gratuito via OpenRouter
OPENROUTER_MODEL_FAST  = os.environ.get("OPENROUTER_FAST_MODEL",  "google/gemma-2-9b-it:free")
OPENROUTER_MODEL_SMART = os.environ.get("OPENROUTER_SMART_MODEL", "nousresearch/hermes-3-llama-3.1-405b:free")


# ── Cliente genérico OpenAI-compatible ────────────────────────────────────────

async def _openai_compat_chat(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    max_tokens: int = 1024,
    extra_headers: dict | None = None,
) -> str:
    """
    Envia uma requisição para qualquer endpoint OpenAI-compatible.
    Retorna o conteúdo da resposta como string.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _openai_compat_chat_sync(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    max_tokens: int = 1024,
    extra_headers: dict | None = None,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# ── Retry helpers para OpenRouter (trata 429 e erros transitórios) ───────────

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _sleep_backoff(attempt: int, base: float = 2.0, cap: float = 120.0) -> None:
    delay = min(cap, base * (2 ** attempt)) + random.uniform(0, 1)
    time.sleep(delay)


def _openai_compat_chat_sync_retry(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    max_tokens: int = 1024,
    extra_headers: dict | None = None,
    max_retries: int = 4,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code in _RETRYABLE_STATUS:
                    last_exc = RuntimeError(
                        f"Retryable status {resp.status_code} from {base_url}"
                    )
                    _sleep_backoff(attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, RuntimeError) as e:
            last_exc = e
            if attempt < max_retries:
                _sleep_backoff(attempt)
            else:
                raise last_exc
    raise last_exc  # type: ignore[misc]


async def _openai_compat_chat_retry(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    max_tokens: int = 1024,
    extra_headers: dict | None = None,
    max_retries: int = 4,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code in _RETRYABLE_STATUS:
                    last_exc = RuntimeError(
                        f"Retryable status {resp.status_code} from {base_url}"
                    )
                    await asyncio.sleep(min(120.0, 2.0 * (2 ** attempt)) + random.uniform(0, 1))
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, RuntimeError) as e:
            last_exc = e
            if attempt < max_retries:
                await asyncio.sleep(min(120.0, 2.0 * (2 ** attempt)) + random.uniform(0, 1))
            else:
                raise last_exc
    raise last_exc  # type: ignore[misc]


# ── Groq ──────────────────────────────────────────────────────────────────────

GROQ_BASE = "https://api.groq.com/openai/v1"


def groq_available() -> bool:
    return bool(GROQ_API_KEY)


def groq_chat(prompt: str, system: str = "", smart: bool = False) -> str:
    """Envia prompt para Groq (síncrono). Usa llama-3.1-8b por padrão."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY não configurada. Obtenha gratuitamente em console.groq.com")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    model = GROQ_MODEL_SMART if smart else GROQ_MODEL_FAST
    return _openai_compat_chat_sync(GROQ_BASE, GROQ_API_KEY, model, messages)


async def groq_chat_async(prompt: str, system: str = "", smart: bool = False) -> str:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY não configurada.")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    model = GROQ_MODEL_SMART if smart else GROQ_MODEL_FAST
    return await _openai_compat_chat(GROQ_BASE, GROQ_API_KEY, model, messages)


# ── OpenRouter (Hermes e outros modelos gratuitos) ────────────────────────────

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/jfn/compliance-agent",
    "X-Title": "JFN Compliance Agent",
}


def openrouter_available() -> bool:
    return bool(OPENROUTER_API_KEY)


def openrouter_chat(prompt: str, system: str = "", smart: bool = False) -> str:
    """
    Envia prompt para OpenRouter usando modelos gratuitos.
    smart=True usa Hermes-3 405B; False usa Gemma-2 9B.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY não configurada. "
            "Obtenha gratuitamente em openrouter.ai"
        )
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    model = OPENROUTER_MODEL_SMART if smart else OPENROUTER_MODEL_FAST
    return _openai_compat_chat_sync_retry(
        OPENROUTER_BASE,
        OPENROUTER_API_KEY,
        model,
        messages,
        extra_headers=OPENROUTER_HEADERS,
    )


async def openrouter_chat_async(prompt: str, system: str = "", smart: bool = False) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY não configurada. "
            "Obtenha gratuitamente em openrouter.ai"
        )
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    model = OPENROUTER_MODEL_SMART if smart else OPENROUTER_MODEL_FAST
    return await _openai_compat_chat_retry(
        OPENROUTER_BASE,
        OPENROUTER_API_KEY,
        model,
        messages,
        extra_headers=OPENROUTER_HEADERS,
    )


# ── Interface unificada (escolhe o melhor disponível) ─────────────────────────

def best_free_chat(
    prompt: str,
    system: str = "",
    smart: bool = False,
    fallback: str = "",
) -> str:
    """
    Tenta provedores gratuitos em ordem de preferência.
    Ordem padrão: Ollama → Groq → OpenRouter.
    Configura com FREE_LLM_PREFER=groq|openrouter|ollama.

    Se nenhum disponível e fallback fornecido, retorna fallback.
    Raises RuntimeError se tudo falhar e sem fallback.
    """
    # Import local here to avoid circular imports
    from compliance_agent.llm import local as _ollama

    order = _get_provider_order()

    last_error: Exception | None = None
    for provider in order:
        try:
            if provider == "ollama" and _ollama.is_available():
                return _ollama.chat(prompt, system=system)
            elif provider == "groq" and groq_available():
                return groq_chat(prompt, system=system, smart=smart)
            elif provider == "openrouter" and openrouter_available():
                return openrouter_chat(prompt, system=system, smart=smart)
        except Exception as e:
            last_error = e
            continue

    if fallback:
        return fallback
    raise RuntimeError(
        f"Nenhum LLM gratuito disponível. Último erro: {last_error}. "
        "Configure GROQ_API_KEY ou OPENROUTER_API_KEY no .env, "
        "ou instale Ollama em ollama.com."
    )


async def best_free_chat_async(
    prompt: str,
    system: str = "",
    smart: bool = False,
    fallback: str = "",
) -> str:
    from compliance_agent.llm import local as _ollama

    order = _get_provider_order()

    last_error: Exception | None = None
    for provider in order:
        try:
            if provider == "ollama" and _ollama.is_available():
                return _ollama.chat(prompt, system=system)
            elif provider == "groq" and groq_available():
                return await groq_chat_async(prompt, system=system, smart=smart)
            elif provider == "openrouter" and openrouter_available():
                return await openrouter_chat_async(prompt, system=system, smart=smart)
        except Exception as e:
            last_error = e
            continue

    if fallback:
        return fallback
    raise RuntimeError(f"Nenhum LLM gratuito disponível. Último erro: {last_error}.")


def _get_provider_order() -> list[str]:
    """Returns provider priority list based on FREE_LLM_PREFER."""
    all_providers = ["ollama", "groq", "openrouter"]
    prefer = FREE_LLM_PREFER.strip().lower()
    if prefer in all_providers:
        return [prefer] + [p for p in all_providers if p != prefer]
    return all_providers


# ── Helpers de alto nível (sem async — para uso no motor de regras) ───────────

def classificar_contrato(objeto: str, categorias: list[str]) -> str:
    """Classifica objeto de contrato em uma categoria. Sem custo Claude."""
    prompt = (
        f"Classifique o objeto abaixo em UMA das categorias: {' | '.join(categorias)}\n"
        "Responda APENAS com o nome da categoria, sem explicações.\n\n"
        f"Objeto: {objeto[:300]}"
    )
    try:
        resultado = best_free_chat(prompt, fallback=categorias[0])
        resultado = resultado.strip().lower()
        for cat in categorias:
            if cat.lower() in resultado:
                return cat
        return categorias[0]
    except Exception:
        return categorias[0]


def resumir_doerj(texto: str, max_palavras: int = 80) -> str:
    """Resume publicação do DOERJ. Sem custo Claude."""
    prompt = (
        f"Resuma em no máximo {max_palavras} palavras em português, "
        "focando em nomes de pessoas, empresas, valores e irregularidades:\n\n"
        f"{texto[:1500]}"
    )
    try:
        return best_free_chat(prompt, fallback=texto[:300] + "...")
    except Exception:
        return texto[:300] + "..."


def extrair_entidades_texto(texto: str) -> dict:
    """Extrai entidades nomeadas. Sem custo Claude."""
    prompt = (
        "Extraia do texto:\n"
        "- nomes de pessoas\n- empresas/órgãos\n- valores monetários\n"
        "- CPFs (formato 000.000.000-00)\n- CNPJs\n"
        "Responda em JSON com chaves: pessoas, empresas, valores, cpfs, cnpjs\n\n"
        f"Texto: {texto[:1500]}\n\nJSON:"
    )
    try:
        resultado = best_free_chat(prompt, fallback="{}")
        match = re.search(r"\{.*\}", resultado, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return {"pessoas": [], "empresas": [], "valores": [], "cpfs": [], "cnpjs": []}


def analisar_red_flags_contrato(objeto: str, orgao: str, valor: float) -> list[str]:
    """
    Analisa texto de contrato em busca de red flags de fraude.
    Usa LLM gratuito para análise de linguagem.
    """
    from compliance_agent.knowledge.fraudes_licitacao import TODOS_RED_FLAGS

    # Primeiro: análise local por palavras-chave (sem LLM, zero custo)
    texto_lower = (objeto + " " + orgao).lower()
    flags_locais = [
        f"🚩 [{pattern_id}] '{flag}'"
        for flag, pattern_id in TODOS_RED_FLAGS
        if flag in texto_lower
    ]

    # Depois: análise semântica via LLM gratuito
    if not best_free_chat.__module__:
        return flags_locais

    prompt = (
        "Analise este contrato público e liste sinais de alerta de fraude ou irregularidade.\n"
        "Seja breve: máximo 5 itens. Se não houver, responda 'Nenhum sinal identificado'.\n\n"
        f"Órgão: {orgao}\nObjeto: {objeto[:300]}\nValor: R$ {valor:,.2f}"
    )
    try:
        llm_flags = best_free_chat(prompt, fallback="")
        if llm_flags and "nenhum" not in llm_flags.lower():
            flags_locais.append(f"🤖 Análise LLM: {llm_flags[:300]}")
    except Exception:
        pass

    return flags_locais


def status_provedores() -> dict:
    """Retorna status de todos os provedores de LLM gratuito."""
    from compliance_agent.llm import local as _ollama
    return {
        "ollama": {
            "disponivel": _ollama.is_available(),
            "modelo": os.environ.get("OLLAMA_MODEL", "llama3.2:3b"),
            "custo": "zero (local)",
        },
        "groq": {
            "disponivel": groq_available(),
            "modelo_fast": GROQ_MODEL_FAST,
            "modelo_smart": GROQ_MODEL_SMART,
            "custo": "gratuito (com limites de taxa)",
            "obter_chave": "https://console.groq.com",
        },
        "openrouter": {
            "disponivel": openrouter_available(),
            "modelo_fast": OPENROUTER_MODEL_FAST,
            "modelo_smart": OPENROUTER_MODEL_SMART,
            "destaque": "Hermes-3 405B disponível gratuitamente",
            "custo": "gratuito (modelos :free)",
            "obter_chave": "https://openrouter.ai",
        },
        "preferencia": FREE_LLM_PREFER,
        "ordem_fallback": _get_provider_order(),
    }
