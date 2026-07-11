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
import pathlib
import random
import re
import time

import httpx

# ── Configuração ──────────────────────────────────────────────────────────────

GROQ_API_KEY        = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_API_KEY  = os.environ.get("OPENROUTER_API_KEY", "")
# Preferência explícita de provedor 1º da cascata (nome de _get_provider_order). O default
# antigo "qwen" não existia na lista → era config morta; vazio = ordem padrão (cerebras 1º).
FREE_LLM_PREFER = os.environ.get("FREE_LLM_PREFER", "").lower()

# Qwen via OpenRouter (fallbacks possíveis)
OPENROUTER_MODEL_FAST  = os.environ.get("OPENROUTER_FAST_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
OPENROUTER_MODEL_SMART = os.environ.get("OPENROUTER_SMART_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

# Modelo de CÓDIGO (uncensored, p/ o Hermes codar). Qwen3-Coder = SOTA aberto em código,
# 1M de contexto, alinhamento leve (pouco recusa). APENAS :free (regra do dono). Fallbacks
# não-Venice p/ quando o primário rate-limitar. Env: OPENROUTER_CODER_MODEL.
OPENROUTER_MODEL_CODER = os.environ.get("OPENROUTER_CODER_MODEL", "qwen/qwen3-coder:free")
OPENROUTER_CODER_FALLBACK = [
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "cohere/north-mini-code:free",
    "deepseek/deepseek-r1:free",
]


def _forcar_free(model: str) -> str:
    """GUARD anti-cobrança (regra do dono: SEMPRE `:free`). Qualquer modelo OpenRouter é forçado p/ a
    variante `:free` — assim nunca chama a versão paga. Se a `:free` não existir, o OpenRouter dá 404
    (NÃO cobra); se existir, é grátis. O router 'openrouter/free' (já grátis) passa direto."""
    m = (model or "").strip()
    if m == "openrouter/free" or m.endswith(":free"):
        return m
    return m.split(":", 1)[0] + ":free"

# Modelos Groq (free tier) — usados em groq_chat_async e status_provedores.
# Antes eram referenciados sem definição global (NameError). Configuráveis por env.
GROQ_MODEL_FAST  = os.environ.get("GROQ_MODEL_FAST",  "llama-3.1-8b-instant")
GROQ_MODEL_SMART = os.environ.get("GROQ_MODEL_SMART", "llama-3.3-70b-versatile")


# ── Cliente genérico OpenAI-compatible ────────────────────────────────────────

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


def _groq_key() -> str:
    # Resolve em tempo de execução: cobre .env carregado após o import deste módulo.
    return os.environ.get("GROQ_API_KEY", GROQ_API_KEY)


def groq_available() -> bool:
    return bool(_groq_key())


def groq_chat(prompt: str, system: str = "", smart: bool = False,
              max_tokens: int = 1024) -> str:
    """Envia prompt para Groq (síncrono). Usa llama-3.1-8b por padrão. Com retry."""
    key = _groq_key()
    if not key:
        raise RuntimeError("GROQ_API_KEY não configurada. Obtenha gratuitamente em console.groq.com")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    model = GROQ_MODEL_SMART if smart else GROQ_MODEL_FAST
    # Groq no plano gratuito retorna 429 com frequência — retry/backoff é essencial.
    return _openai_compat_chat_sync_retry(GROQ_BASE, key, model, messages,
                                          max_tokens=max_tokens)


async def groq_chat_async(prompt: str, system: str = "", smart: bool = False,
                          max_tokens: int = 1024) -> str:
    key = _groq_key()
    if not key:
        raise RuntimeError("GROQ_API_KEY não configurada.")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    model = GROQ_MODEL_SMART if smart else GROQ_MODEL_FAST
    return await _openai_compat_chat_retry(GROQ_BASE, key, model, messages,
                                           max_tokens=max_tokens)


# ── OpenRouter (Hermes e outros modelos gratuitos) ────────────────────────────

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/jfn/compliance-agent",
    "X-Title": "JFN Compliance Agent",
}


def _openrouter_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", OPENROUTER_API_KEY)


def openrouter_available() -> bool:
    return bool(_openrouter_key())


def openrouter_chat(prompt: str, system: str = "", smart: bool = False,
                    max_tokens: int = 1024) -> str:
    """
    Envia prompt para OpenRouter usando modelos gratuitos.
    smart=True usa Hermes-3 405B; False usa Gemma-2 9B.
    """
    key = _openrouter_key()
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY não configurada. "
            "Obtenha gratuitamente em openrouter.ai"
        )
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    model = _forcar_free(OPENROUTER_MODEL_SMART if smart else OPENROUTER_MODEL_FAST)
    return _openai_compat_chat_sync_retry(
        OPENROUTER_BASE,
        key,
        model,
        messages,
        max_tokens=max_tokens,
        extra_headers=OPENROUTER_HEADERS,
    )


async def openrouter_chat_async(prompt: str, system: str = "", smart: bool = False,
                                max_tokens: int = 1024) -> str:
    key = _openrouter_key()
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY não configurada. "
            "Obtenha gratuitamente em openrouter.ai"
        )
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    model = _forcar_free(OPENROUTER_MODEL_SMART if smart else OPENROUTER_MODEL_FAST)
    return await _openai_compat_chat_retry(
        OPENROUTER_BASE,
        key,
        model,
        messages,
        max_tokens=max_tokens,
        extra_headers=OPENROUTER_HEADERS,
    )


# Coder LOCAL abliterated (100% uncensored — abliteração remove a recusa no peso).
# Roda no Ollama da VM; é a 1ª opção do coder (offline, $0, sem rate-limit). Env:
# OLLAMA_CODER_MODEL / OLLAMA_URL. keep_alive curto p/ não segurar RAM na VM frágil.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_CODER_MODEL = os.environ.get("OLLAMA_CODER_MODEL", "huihui_ai/qwen2.5-coder-abliterate:7b")


async def _ollama_coder_async(messages: list, max_tokens: int) -> "str | None":
    """Tenta o coder abliterated local. Retorna None se o Ollama/modelo não estiver disponível
    (para a cascata cair p/ a API sem quebrar)."""
    try:
        async with httpx.AsyncClient(timeout=180) as cli:
            r = await cli.post(f"{OLLAMA_URL}/api/chat", json={
                "model": OLLAMA_CODER_MODEL, "messages": messages, "stream": False,
                "keep_alive": "30s",
                "options": {"num_predict": max_tokens, "num_thread": 2},
            })
            if r.status_code != 200:
                return None
            return (r.json().get("message", {}).get("content") or "").strip() or None
    except Exception:
        return None


async def coder_chat_async(prompt: str, system: str = "", max_tokens: int = 4096) -> str:
    """Caminho de CÓDIGO do Hermes — LOCAL abliterated (100% uncensored) primeiro; se
    indisponível, Qwen3-Coder :free (1M ctx) + fallbacks não-Venice. Levanta se tudo falhar."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # 1. Local abliterated (100% uncensored, offline, $0)
    local = await _ollama_coder_async(messages, max_tokens)
    if local:
        return local

    # 2. API OpenRouter :free (fallback)
    key = _openrouter_key()
    if not key:
        raise RuntimeError("Coder local indisponível e OPENROUTER_API_KEY não configurada.")
    ultimo_erro = None
    for model in [OPENROUTER_MODEL_CODER] + OPENROUTER_CODER_FALLBACK:
        try:
            return await _openai_compat_chat_retry(
                OPENROUTER_BASE, key, _forcar_free(model), messages,
                max_tokens=max_tokens, extra_headers=OPENROUTER_HEADERS, max_retries=1,
            )
        except Exception as e:
            ultimo_erro = e
            await asyncio.sleep(2)
    raise RuntimeError(f"coder_chat_async: todos os modelos :free falharam ({ultimo_erro}).")


# ── Cerebras (gpt-oss-120b / zai-glm-4.7) — OpenAI-compat, inferência ULTRARRÁPIDA (~0,04s) ──
# Modelo de RACIOCÍNIO: precisa max_tokens ALTO (o raciocínio consome tokens; com pouco, content vem vazio).
CEREBRAS_BASE = os.environ.get("CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1")
CEREBRAS_MODEL_FAST = os.environ.get("CEREBRAS_MODEL_FAST", "gpt-oss-120b")
CEREBRAS_MODEL_SMART = os.environ.get("CEREBRAS_MODEL_SMART", "gpt-oss-120b")


def _cerebras_key() -> str:
    return os.environ.get("CEREBRAS_API_KEY", "")


def cerebras_available() -> bool:
    return bool(_cerebras_key())


def _cerebras_msgs(prompt: str, system: str) -> list:
    m = []
    if system:
        m.append({"role": "system", "content": system})
    m.append({"role": "user", "content": prompt})
    return m


def cerebras_chat(prompt: str, system: str = "", smart: bool = False, max_tokens: int = 1024) -> str:
    key = _cerebras_key()
    if not key:
        raise RuntimeError("CEREBRAS_API_KEY não configurada (Cerebras).")
    model = CEREBRAS_MODEL_SMART if smart else CEREBRAS_MODEL_FAST
    return _openai_compat_chat_sync_retry(
        CEREBRAS_BASE, key, model, _cerebras_msgs(prompt, system), max_tokens=max(max_tokens, 2048))


async def cerebras_chat_async(prompt: str, system: str = "", smart: bool = False, max_tokens: int = 1024) -> str:
    key = _cerebras_key()
    if not key:
        raise RuntimeError("CEREBRAS_API_KEY não configurada (Cerebras).")
    model = CEREBRAS_MODEL_SMART if smart else CEREBRAS_MODEL_FAST
    return await _openai_compat_chat_retry(
        CEREBRAS_BASE, key, model, _cerebras_msgs(prompt, system), max_tokens=max(max_tokens, 2048))


# ── Cloudflare Workers AI (OpenAI-compat) — ÚLTIMO recurso no pool ─────────────
# Free: 10k Neurons/dia (reseta 00:00 UTC). Acima disso SÓ cobra no plano Workers Paid;
# no plano Free, trava (não cobra). 70B gasta rápido → rede de segurança, NÃO p/ volume.
CLOUDFLARE_MODEL = os.environ.get("CLOUDFLARE_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")

def _cloudflare_creds() -> tuple[str, str]:
    return os.environ.get("CLOUDFLARE_API_KEY", ""), os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")

def cloudflare_available() -> bool:
    k, a = _cloudflare_creds()
    return bool(k and a and _cap_ok("cloudflare"))

def _cloudflare_base() -> str:
    _, acc = _cloudflare_creds()
    return f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/v1"

def _cf_msgs(prompt: str, system: str) -> list:
    m = [{"role": "system", "content": system}] if system else []
    m.append({"role": "user", "content": prompt})
    return m

def cloudflare_chat(prompt: str, system: str = "", smart: bool = False, max_tokens: int = 1024) -> str:
    key, acc = _cloudflare_creds()
    if not (key and acc):
        raise RuntimeError("CLOUDFLARE_API_KEY/ACCOUNT_ID não configurados.")
    r = _openai_compat_chat_sync_retry(_cloudflare_base(), key, CLOUDFLARE_MODEL, _cf_msgs(prompt, system), max_tokens=max_tokens)
    _cap_inc("cloudflare")
    return r

async def cloudflare_chat_async(prompt: str, system: str = "", smart: bool = False, max_tokens: int = 1024) -> str:
    key, acc = _cloudflare_creds()
    if not (key and acc):
        raise RuntimeError("CLOUDFLARE_API_KEY/ACCOUNT_ID não configurados.")
    r = await _openai_compat_chat_retry(_cloudflare_base(), key, CLOUDFLARE_MODEL, _cf_msgs(prompt, system), max_tokens=max_tokens)
    _cap_inc("cloudflare")
    return r


# ── GitHub Models (OpenAI-compat) — ÚLTIMO recurso (free, rate-limit baixo) ────
# PAT com permissão "Models". Llama 70B no pool; DeepSeek-R1 (deepseek/deepseek-r1) disponível
# p/ raciocínio sob demanda via GITHUB_MODELS_MODEL. Free → rede de segurança, não p/ volume.
GITHUB_MODELS_BASE = "https://models.github.ai/inference"
GITHUB_MODELS_MODEL = os.environ.get("GITHUB_MODELS_MODEL", "meta/llama-3.3-70b-instruct")

def _github_models_key() -> str:
    return os.environ.get("GITHUB_MODELS_TOKEN", "")

def github_models_available() -> bool:
    return bool(_github_models_key() and _cap_ok("github_models"))

def github_models_chat(prompt: str, system: str = "", smart: bool = False, max_tokens: int = 1024) -> str:
    key = _github_models_key()
    if not key:
        raise RuntimeError("GITHUB_MODELS_TOKEN não configurado.")
    r = _openai_compat_chat_sync_retry(GITHUB_MODELS_BASE, key, GITHUB_MODELS_MODEL, _cf_msgs(prompt, system), max_tokens=max_tokens)
    _cap_inc("github_models")
    return r

async def github_models_chat_async(prompt: str, system: str = "", smart: bool = False, max_tokens: int = 1024) -> str:
    key = _github_models_key()
    if not key:
        raise RuntimeError("GITHUB_MODELS_TOKEN não configurado.")
    r = await _openai_compat_chat_retry(GITHUB_MODELS_BASE, key, GITHUB_MODELS_MODEL, _cf_msgs(prompt, system), max_tokens=max_tokens)
    _cap_inc("github_models")
    return r


# ── Provedores diretos extras (free permanente) — ÚLTIMO recurso, data-driven ──
# OpenAI-compat. Ativam SÓ quando a chave existe no .env (senão são pulados). Override de modelo por *_MODEL.
# (base_url, modelo_default, [envs_da_chave], env_do_modelo)
_EXTRA = {
    "sambanova":   ("https://api.sambanova.ai/v1",          "Meta-Llama-3.3-70B-Instruct", ["SAMBANOVA_API_KEY"],            "SAMBANOVA_MODEL"),
    "nvidia":      ("https://integrate.api.nvidia.com/v1",  "meta/llama-3.3-70b-instruct", ["NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY"], "NVIDIA_MODEL"),
    "zai":         (os.environ.get("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4"), "glm-4.5-flash", ["ZAI_API_KEY", "ZHIPU_API_KEY"], "ZAI_MODEL"),
    "siliconflow": ("https://api.siliconflow.com/v1",       "Qwen/Qwen3-8B",               ["SILICONFLOW_API_KEY"],          "SILICONFLOW_MODEL"),
    "cohere":      ("https://api.cohere.ai/compatibility/v1", "command-r-08-2024",         ["COHERE_API_KEY"],               "COHERE_MODEL"),
    # BazaarLink: gateway com modelos PAGOS no catálogo → fixar 'auto:free' (só roteia grátis). NUNCA outro modelo.
    "bazaarlink":  ("https://bazaarlink.ai/api/v1",           "auto:free",                  ["BAZAARLINK_API_KEY"],           "BAZAARLINK_MODEL"),
    # Wisdom Gate: sandbox grátis (one-api) — SEM cartão do dono (billing é da conta deles). DeepSeek-R1 default.
    "wisdomgate":  ("https://wisdom-gate.juheapi.com/v1",     "deepseek-r1",                ["WISDOMGATE_API_KEY"],           "WISDOMGATE_MODEL"),
    # OfoxAI: OpenRouter-style com modelos PAGOS no catálogo → fixar ':free' (guard força :free). Nunca pago.
    "ofox":        ("https://api.ofox.ai/v1",                 "z-ai/glm-4.7-flash:free",    ["OFOX_API_KEY"],                 "OFOX_MODEL"),
    # Routeway: OpenRouter-style; catálogo tem pagos → guard força ':free' (llama-3.3-70b-instruct:free).
    "routeway":    ("https://api.routeway.ai/v1",             "llama-3.3-70b-instruct:free", ["ROUTEWAY_API_KEY"],            "ROUTEWAY_MODEL"),
    # Mistral (tier Experiment ~1B tok/mês): small default; Codestral (coding) via MISTRAL_MODEL=codestral-latest.
    "mistral":     ("https://api.mistral.ai/v1",              "mistral-small-latest",       ["MISTRAL_API_KEY"],              "MISTRAL_MODEL"),
}

# Guard-rail de CUSTO (§4.1): provedores que COBRAM acima do free → cap mensal de requisições
# server-side (conservador, bem abaixo do teto free). Ao atingir, o provedor é PULADO no mês.
# Persistido em data/.llm_month_cap.json (reset automático por mês).
# Cap mensal por provedor (req/mês), tunado ao free de cada um — guarda zero-cobrança + respeita o limite free.
# Override por env CAP_<PROVEDOR> (ex.: CAP_COHERE=2000). 0/negativo = sem cap.
_MONTH_CAP = {
    "sambanova":     600,    # ~20 req/dia
    "nvidia":        1500,   # créditos free + cota diária
    "zai":           5000,   # GLM-Flash generoso
    "siliconflow":   5000,   # modelos free sem limite rígido
    "cohere":        1000,   # trial free rate-limited
    "cloudflare":    1500,   # 10k neurons/dia (≈ conservador p/ 70B)
    "github_models": 3000,   # rate-limit baixo
    "bazaarlink":    3000,   # 150 req/dia free (auto:free)
    "wisdomgate":    3000,   # sandbox grátis (cap conservador)
    "ofox":          3000,   # gateway :free
    "routeway":      3000,   # gateway :free
    "mistral":       8000,   # tier Experiment ~1B tok/mes
}
_MONTH_CAP = {k: int(os.environ.get(f"CAP_{k.upper()}", v)) for k, v in _MONTH_CAP.items()}
_MONTH_CAP = {k: v for k, v in _MONTH_CAP.items() if v > 0}
_CAP_FILE = pathlib.Path("/home/ubuntu/JFN/data/.llm_month_cap.json")

def _mes_atual() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y%m")

def _cap_load() -> dict:
    try:
        return json.loads(_CAP_FILE.read_text())
    except Exception:
        return {}

def _cap_count(name: str) -> int:
    return int((_cap_load().get(_mes_atual()) or {}).get(name, 0))

def _cap_inc(name: str) -> None:
    if name not in _MONTH_CAP:
        return
    d = _cap_load(); m = _mes_atual()
    d = {m: d.get(m, {})}  # só o mês corrente (limpa meses velhos)
    d[m][name] = d[m].get(name, 0) + 1
    try:
        _CAP_FILE.write_text(json.dumps(d))
    except Exception:
        pass

def _cap_ok(name: str) -> bool:
    cap = _MONTH_CAP.get(name)
    return cap is None or _cap_count(name) < cap

def _envk(*names: str) -> str:
    for n in names:
        v = os.environ.get(n, "")
        if v:
            return v
    return ""

def extra_available(name: str) -> bool:
    spec = _EXTRA.get(name)
    return bool(spec and _envk(*spec[2]) and _cap_ok(name))  # cap mensal (§4.1) impede cobrança

def _extra_cfg(name: str):
    base, dmodel, keys, menv = _EXTRA[name]
    model = os.environ.get(menv, dmodel)
    if name == "bazaarlink" and not model.endswith(":free") and model != "auto:free":
        model = "auto:free"  # guard anti-cobrança: catálogo tem modelos PAGOS; só roteia grátis
    if name == "ofox" and not model.endswith(":free"):
        model = "z-ai/glm-4.7-flash:free"  # guard anti-cobrança: só modelos :free
    if name == "routeway" and not model.endswith(":free"):
        model = "llama-3.3-70b-instruct:free"  # guard anti-cobrança: só :free
    return base, _envk(*keys), model

def extra_chat(name: str, prompt: str, system: str = "", max_tokens: int = 1024) -> str:
    base, key, model = _extra_cfg(name)
    if not key:
        raise RuntimeError(f"{name}: chave ausente")
    r = _openai_compat_chat_sync_retry(base, key, model, _cf_msgs(prompt, system), max_tokens=max_tokens)
    _cap_inc(name)  # conta p/ o cap mensal (provedores que cobram acima do free)
    return r

async def extra_chat_async(name: str, prompt: str, system: str = "", max_tokens: int = 1024) -> str:
    base, key, model = _extra_cfg(name)
    if not key:
        raise RuntimeError(f"{name}: chave ausente")
    r = await _openai_compat_chat_retry(base, key, model, _cf_msgs(prompt, system), max_tokens=max_tokens)
    _cap_inc(name)
    return r


# ── Gemini no pool (rotação do pool de chaves do JFN via direcionamento_cerebro) ──
# Qualidade alta: entra no pool free_llm para REDUNDÂNCIA (todas as IAs têm gemini também).
# Import local p/ evitar import circular.
def gemini_available() -> bool:
    try:
        from compliance_agent.direcionamento_cerebro import _gemini_keys
        return bool(_gemini_keys())
    except Exception:  # noqa: BLE001
        return False


def _gemini_msgs(prompt: str, system: str) -> list:
    return ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]


async def gemini_chat_async(prompt: str, system: str = "", smart: bool = False, max_tokens: int = 1024) -> str:
    from compliance_agent.direcionamento_cerebro import gerar_gemini
    # max_tokens propagado (antes era descartado: Hermes pedia 8000 e o default 4096 truncava o
    # raciocínio longo quando a cascata caía no Gemini). `smart` segue sem efeito aqui (modelo é
    # escolhido pela cascata interna do gerar_gemini).
    return await gerar_gemini(_gemini_msgs(prompt, system), max_tokens=max(max_tokens, 1024))


def gemini_chat(prompt: str, system: str = "", smart: bool = False, max_tokens: int = 1024) -> str:
    import asyncio
    try:
        return asyncio.run(gemini_chat_async(prompt, system=system, smart=smart, max_tokens=max_tokens))
    except RuntimeError:  # já há event loop rodando → roda em thread isolada
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            return ex.submit(lambda: asyncio.run(gemini_chat_async(prompt, system=system))).result()


async def qwen_chat_async(prompt: str, system: str = "", smart: bool = False,
                          max_tokens: int = 1024) -> str:
    """Qwen como provedor PRIMÁRIO (via OpenRouter, evitando o 429 recorrente do Groq).

    Antes era importado em hermes_agent.py mas não existia (ImportError a cada chamada,
    mascarado pelo fallback). Aqui roteia para o modelo Qwen do OpenRouter; se OpenRouter/Qwen
    falhar, cai para o melhor provedor livre disponível (Ollama/Groq/OpenRouter).
    """
    try:
        if openrouter_available():
            return await openrouter_chat_async(prompt, system=system, smart=smart, max_tokens=max_tokens)
    except Exception:
        pass
    return await best_free_chat_async(prompt, system=system, smart=smart)


# ── Interface unificada (escolhe o melhor disponível) ─────────────────────────

# ── Cooldown + classificação de erro (aprendido do LiteLLM router) ────────────
# Tira do pool, por N s, o provedor que acabou de falhar — evita gastar o 1º slot
# num provedor morto/limitado (429) a cada request. Memória EM PROCESSO (vale dentro
# de um lote do sweep; reinício zera). Curto p/ transitório, longo p/ chave ruim.
_COOLDOWN: dict[str, float] = {}      # provider -> deadline (monotonic)
_COOLDOWN_MOTIVO: dict[str, str] = {}

def _classificar_erro(exc: Exception) -> tuple[str, float]:
    """(motivo, segundos_de_cooldown) por TIPO de erro — em vez de tratar tudo igual."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    s = (str(exc) or "").lower()
    if status == 429 or "429" in s or "rate limit" in s or "quota" in s or "too many requests" in s:
        return ("rate-limit", 45.0)
    if status in (401, 403) or "unauthor" in s or "invalid api key" in s or "invalid_api_key" in s \
            or "forbidden" in s or "permission" in s:
        return ("auth", 1800.0)          # chave ruim/sem permissão → pula 30min (retry é inútil)
    if "timeout" in s or "timed out" in s or "connect" in s or "connection" in s:
        return ("timeout", 20.0)
    if status in (500, 502, 503, 504) or "server error" in s or "overload" in s or "503" in s:
        return ("server", 30.0)
    return ("erro", 15.0)

def _em_cooldown(provider: str) -> bool:
    return _COOLDOWN.get(provider, 0.0) > time.monotonic()

def _marcar_cooldown(provider: str, exc: Exception) -> tuple[str, float]:
    motivo, dur = _classificar_erro(exc)
    _COOLDOWN[provider] = time.monotonic() + dur
    _COOLDOWN_MOTIVO[provider] = motivo
    return motivo, dur

def _limpar_cooldown(provider: str) -> None:
    _COOLDOWN.pop(provider, None)
    _COOLDOWN_MOTIVO.pop(provider, None)

def cooldowns_ativos() -> dict[str, str]:
    """Diagnóstico: {provedor: 'motivo (Ns)'} dos que estão em cooldown agora."""
    now = time.monotonic()
    return {p: f"{_COOLDOWN_MOTIVO.get(p,'?')} ({t-now:.0f}s)" for p, t in _COOLDOWN.items() if t > now}


_TRACE_DB = pathlib.Path(__file__).resolve().parents[2] / "data" / "llm_trace.db"


def _trace(provider: str, ok: bool, ms: int, erro: str = "") -> None:
    """Telemetria LOCAL mínima da cadeia (só metadados — nunca prompt/resposta; sigilo por design).

    Veredito Langfuse 2026-07-07: self-host (Postgres+ClickHouse+Redis+S3) inviável na VM 2vCPU;
    cloud grátis mandaria conteúdo de investigação p/ terceiro → cherry-pick do conceito, local.
    Consulta: sqlite3 data/llm_trace.db 'SELECT provedor, ok, COUNT(*), AVG(ms) FROM llm_trace GROUP BY 1,2'.
    """
    import sqlite3
    try:
        con = sqlite3.connect(_TRACE_DB, timeout=2)
        con.execute("CREATE TABLE IF NOT EXISTS llm_trace("
                    "ts TEXT DEFAULT (datetime('now')), provedor TEXT, ok INT, ms INT, erro TEXT)")
        con.execute("INSERT INTO llm_trace(provedor, ok, ms, erro) VALUES(?,?,?,?)",
                    (provider, int(ok), ms, erro[:200]))
        con.commit()
        con.close()
    except (sqlite3.Error, OSError):
        pass  # telemetria NUNCA derruba a cadeia


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
        if _em_cooldown(provider):      # provedor que falhou há pouco → pula (não gasta slot)
            continue
        _ini = time.monotonic()
        try:
            resp = None
            if provider == "cerebras" and cerebras_available():
                resp = cerebras_chat(prompt, system=system, smart=smart)
            elif provider == "gemini" and gemini_available():
                resp = gemini_chat(prompt, system=system, smart=smart)
            elif provider == "ollama" and _ollama.is_available():
                resp = _ollama.chat(prompt, system=system)
            elif provider == "groq" and groq_available():
                resp = groq_chat(prompt, system=system, smart=smart)
            elif provider == "openrouter" and openrouter_available():
                resp = openrouter_chat(prompt, system=system, smart=smart)
            elif provider == "cloudflare" and cloudflare_available():
                resp = cloudflare_chat(prompt, system=system, smart=smart)
            elif provider == "github_models" and github_models_available():
                resp = github_models_chat(prompt, system=system, smart=smart)
            elif provider in _EXTRA and extra_available(provider):
                resp = extra_chat(provider, prompt, system=system)
            if resp is not None and str(resp).strip():
                _limpar_cooldown(provider)   # voltou a responder → reabilita
                _trace(provider, True, int((time.monotonic() - _ini) * 1000))
                return resp
            if resp is not None:  # "" = contrato de erro do local.chat — NÃO é resposta; segue a cadeia
                _trace(provider, False, int((time.monotonic() - _ini) * 1000), "resposta vazia")
        except Exception as e:
            last_error = e
            _trace(provider, False, int((time.monotonic() - _ini) * 1000), f"{type(e).__name__}: {e}")
            _marcar_cooldown(provider, e)     # cooldown por TIPO de erro
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
        if _em_cooldown(provider):      # provedor que falhou há pouco → pula
            continue
        _ini = time.monotonic()
        try:
            resp = None
            if provider == "cerebras" and cerebras_available():
                resp = await cerebras_chat_async(prompt, system=system, smart=smart)
            elif provider == "gemini" and gemini_available():
                resp = await gemini_chat_async(prompt, system=system, smart=smart)
            elif provider == "ollama" and _ollama.is_available():
                resp = _ollama.chat(prompt, system=system)
            elif provider == "groq" and groq_available():
                resp = await groq_chat_async(prompt, system=system, smart=smart)
            elif provider == "openrouter" and openrouter_available():
                resp = await openrouter_chat_async(prompt, system=system, smart=smart)
            elif provider == "cloudflare" and cloudflare_available():
                resp = await cloudflare_chat_async(prompt, system=system, smart=smart)
            elif provider == "github_models" and github_models_available():
                resp = await github_models_chat_async(prompt, system=system, smart=smart)
            elif provider in _EXTRA and extra_available(provider):
                resp = await extra_chat_async(provider, prompt, system=system)
            if resp is not None and str(resp).strip():
                _limpar_cooldown(provider)
                _trace(provider, True, int((time.monotonic() - _ini) * 1000))
                return resp
            if resp is not None:  # "" = contrato de erro do local.chat — NÃO é resposta; segue a cadeia
                _trace(provider, False, int((time.monotonic() - _ini) * 1000), "resposta vazia")
        except Exception as e:
            last_error = e
            _trace(provider, False, int((time.monotonic() - _ini) * 1000), f"{type(e).__name__}: {e}")
            _marcar_cooldown(provider, e)
            continue

    if fallback:
        return fallback
    raise RuntimeError(f"Nenhum LLM gratuito disponível. Último erro: {last_error}.")


def _get_provider_order() -> list[str]:
    """Returns provider priority list based on FREE_LLM_PREFER."""
    # Cerebras 1º (ultrarrápido/grátis, ideal p/ volume do sweep); GEMINI no pool p/ redundância+qualidade
    # (fallback forte); ollama (local) só se instalado; depois groq/openrouter.
    # cloudflare/github_models/extras por ÚLTIMO: free com cap/rate-limit baixo → rede de segurança, não p/ volume
    all_providers = ["cerebras", "gemini", "ollama", "groq", "openrouter", "cloudflare", "github_models",
                     "sambanova", "nvidia", "zai", "siliconflow", "cohere", "bazaarlink", "wisdomgate", "ofox", "routeway", "mistral"]
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

    # Depois: análise semântica via LLM gratuito (só se houver provedor disponível)
    from compliance_agent.llm import local as _ollama
    if not (groq_available() or openrouter_available() or _ollama.is_available()):
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
