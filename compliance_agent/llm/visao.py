"""Fallback de VISÃO entre provedores gratuitos — uma imagem, vários provedores, teto duro.

Ordem: OpenRouter `:free` → NVIDIA NIM → Gemini → Cloudflare Workers AI. Percorre modelo a
modelo e provedor a provedor até um responder; devolve texto e diz QUEM respondeu.

**Custo.** Só o OpenRouter tem garantia ESTRUTURAL de $0: o guard em `_openai_compat_chat_sync`
força `:free`, e modelo pago vira 404 em vez de cobrança. Nos demais a gratuidade é **cota, não
trava** — e a regra da casa é clara: *nenhuma API é "free tier" sem prova; prefira guard-rail
real (kill-switch + teto) a confiar na cota*. Por isso, aqui:

  - `JFN_VISAO_TETO`  — máximo de requisições por processo (padrão 400). Estourou, para.
  - `JFN_VISAO_OFF=1` — kill-switch: desliga a visão inteira sem editar código.
  - `JFN_VISAO_PROVEDORES` — restringe a ordem, ex.: `openrouter` para ficar só no $0 estrutural.

Nunca levanta exceção: falha vira `{"ok": False, "motivo": ...}`, porque visão é enriquecimento
e não pode derrubar a análise que a chamou.
"""
from __future__ import annotations

import base64
import logging
import os

logger = logging.getLogger(__name__)

# Modelos com visão, medidos em 25/07/2026 (não presumidos: a lista veio da API de cada provedor).
OPENROUTER_VISAO = ("google/gemma-4-31b-it:free", "nvidia/nemotron-nano-12b-v2-vl:free",
                    "google/gemma-4-26b-a4b-it:free")
NVIDIA_VISAO = ("nvidia/nemotron-nano-12b-v2-vl", "meta/llama-3.2-11b-vision-instruct",
                "meta/llama-3.2-90b-vision-instruct")
GEMINI_VISAO = ("gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-2.5-flash")
# O `llama-3.2-11b-vision-instruct` do Cloudflare responde 403 até que a conta aceite a Licença
# Comunitária do Llama — aceite jurídico do DONO da conta, não de quem escreve o código. Por isso o
# mistral-small vem primeiro: funciona sem esse aceite (medido em foto real do acervo).
CLOUDFLARE_VISAO = ("@cf/mistralai/mistral-small-3.1-24b-instruct",
                    "@cf/meta/llama-3.2-11b-vision-instruct")

ORDEM_PADRAO = ("openrouter", "nvidia", "gemini", "cloudflare")
_TETO_PADRAO = 400

_gastas = 0


def requisicoes_gastas() -> int:
    """Quantas chamadas de visão este processo já fez — para o chamador reportar custo."""
    return _gastas


def _teto() -> int:
    try:
        return int(os.environ.get("JFN_VISAO_TETO", _TETO_PADRAO))
    except ValueError:
        return _TETO_PADRAO


def _chave(nome: str) -> str:
    return (os.environ.get(nome) or "").strip()


def _mime(img: bytes) -> str:
    return "image/png" if img[:4] == b"\x89PNG" else "image/jpeg"


def _msgs_openai(img: bytes, prompt: str) -> list[dict]:
    b64 = base64.b64encode(img).decode()
    return [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:{_mime(img)};base64,{b64}"}}]}]


def _via_openai_compat(base: str, chave: str, modelos, img: bytes, prompt: str, max_tokens: int):
    """OpenRouter e NVIDIA falam OpenAI-compat. No OpenRouter o guard de `:free` é aplicado lá dentro."""
    from compliance_agent.llm.free_llm import _openai_compat_chat_sync
    msgs = _msgs_openai(img, prompt)
    for mdl in modelos:
        try:
            txt = _openai_compat_chat_sync(base, chave, mdl, msgs, max_tokens=max_tokens)
            if (txt or "").strip():
                return txt.strip(), mdl
        except Exception as e:  # noqa: BLE001 — provedor fora do ar / cota: tenta o próximo
            logger.debug("visão %s falhou: %s", mdl, str(e)[:120])
    return None, None


def _via_gemini(img: bytes, prompt: str, max_tokens: int):
    """Gemini nativo, pool de chaves. NÃO força JSON — quem quiser JSON pede no prompt.

    (`verificacao_endereco._gemini_vision_sync` faz o mesmo forçando `application/json`, porque
    lá a resposta É um JSON de classificação. Não unifiquei: aquele caminho está em produção e
    funciona; unificar por elegância não é motivo para mexer.)"""
    import httpx
    keys = [k for k in (_chave("GEMINI_API_KEYS") or _chave("GEMINI_API_KEY")).replace(",", " ").split() if k]
    if not keys:
        return None, None
    body = {"contents": [{"role": "user", "parts": [
        {"text": prompt},
        {"inline_data": {"mime_type": _mime(img), "data": base64.b64encode(img).decode()}}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens}}
    for mdl in GEMINI_VISAO:
        for k in keys:
            try:
                r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent",
                               params={"key": k}, json=body, timeout=60)
                if r.status_code in (401, 403, 429):
                    continue                       # chave sem cota: próxima chave
                if r.status_code == 404:
                    break                          # modelo não existe: próximo modelo
                r.raise_for_status()
                partes = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                txt = "".join(p.get("text", "") for p in partes).strip()
                if txt:
                    return txt, mdl
            except Exception as e:  # noqa: BLE001
                logger.debug("visão gemini %s falhou: %s", mdl, str(e)[:120])
    return None, None


def _via_cloudflare(img: bytes, prompt: str, max_tokens: int):
    """Workers AI pelo endpoint OpenAI-compat (`/ai/v1`), não pelo `/ai/run/<modelo>`: o `run` pede
    a imagem como array de bytes e recusa `image_url`."""
    tok, conta = _chave("CLOUDFLARE_API_TOKEN"), _chave("CLOUDFLARE_ACCOUNT_ID")
    if not (tok and conta):
        return None, None
    base = f"https://api.cloudflare.com/client/v4/accounts/{conta}/ai/v1"
    return _via_openai_compat(base, tok, CLOUDFLARE_VISAO, img, prompt, max_tokens)


def descrever(img: bytes, prompt: str, *, max_tokens: int = 300) -> dict:
    """Manda a imagem ao primeiro provedor que responder.

    Devolve `{"ok": True, "texto", "provedor", "modelo"}` ou `{"ok": False, "motivo"}`.
    O motivo é sempre dizível ao usuário — 'teto', 'desligado', 'sem provedor' ou 'todos falharam'
    são estados diferentes, e confundi-los esconde INDISPONÍVEL como se fosse resposta vazia."""
    global _gastas
    if os.environ.get("JFN_VISAO_OFF", "").strip() in ("1", "true", "sim"):
        return {"ok": False, "motivo": "desligado (JFN_VISAO_OFF)"}
    if not img:
        return {"ok": False, "motivo": "sem imagem"}
    if _gastas >= _teto():
        return {"ok": False, "motivo": f"teto de {_teto()} requisições atingido (JFN_VISAO_TETO)"}

    pedidos = [p.strip().lower() for p in
               (os.environ.get("JFN_VISAO_PROVEDORES") or "").replace(",", " ").split() if p.strip()]
    ordem = tuple(p for p in ORDEM_PADRAO if p in pedidos) if pedidos else ORDEM_PADRAO

    tentou = False
    for prov in ordem:
        if prov == "openrouter":
            ch = _chave("OPENROUTER_API_KEY")
            if not ch:
                continue
            from compliance_agent.llm.free_llm import OPENROUTER_BASE
            perna = lambda: _via_openai_compat(OPENROUTER_BASE, ch, OPENROUTER_VISAO,  # noqa: E731
                                               img, prompt, max_tokens)
        elif prov == "nvidia":
            ch = _chave("NVIDIA_API_KEY")
            if not ch:
                continue
            perna = lambda: _via_openai_compat("https://integrate.api.nvidia.com/v1", ch,  # noqa: E731
                                               NVIDIA_VISAO, img, prompt, max_tokens)
        elif prov == "gemini":
            if not (_chave("GEMINI_API_KEYS") or _chave("GEMINI_API_KEY")):
                continue
            perna = lambda: _via_gemini(img, prompt, max_tokens)  # noqa: E731
        else:
            if not _chave("CLOUDFLARE_API_TOKEN"):
                continue
            perna = lambda: _via_cloudflare(img, prompt, max_tokens)  # noqa: E731

        tentou = True
        _gastas += 1
        try:
            txt, mdl = perna()
        except Exception as e:  # noqa: BLE001 — visão é enriquecimento: nunca derruba quem chamou
            logger.debug("visão %s levantou: %s", prov, str(e)[:120])
            continue
        if txt:
            return {"ok": True, "texto": txt, "provedor": prov, "modelo": mdl}

    return {"ok": False, "motivo": "todos os provedores falharam" if tentou else "sem provedor com chave"}
