"""
Telegram notification module for the compliance system.

Sends daily summaries, urgent alerts, and report files via Telegram Bot API
using httpx directly (no python-telegram-bot dependency required).
"""

import os
from datetime import date
from pathlib import Path
from typing import Union

import httpx

BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")

# Telegram Bot API base URL, built from token at import time.
# Will be updated dynamically when BOT_TOKEN is set.
def _base_url() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    if not token:
        return ""
    return f"https://api.telegram.org/bot{token}"


async def enviar_mensagem(
    texto: str,
    chat_id: str = "",
    parse_mode: str = "Markdown",
) -> dict:
    """
    Send a text message to a Telegram chat.

    Args:
        texto:      Message text (Markdown supported).
        chat_id:    Target chat ID. Falls back to TELEGRAM_CHAT_ID env var.
        parse_mode: Telegram parse mode ("Markdown" or "HTML").

    Returns:
        Telegram API response dict.
    """
    target = chat_id or os.environ.get("TELEGRAM_CHAT_ID", CHAT_ID)
    base = _base_url()
    if not base or not target:
        return {"ok": False, "error": "BOT_TOKEN ou CHAT_ID não configurado"}

    # Telegram Markdown v1 has limits — truncate if too long
    max_len = 4096
    if len(texto) > max_len:
        texto = texto[: max_len - 3] + "..."

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base}/sendMessage",
                json={
                    "chat_id": target,
                    "text": texto,
                    "parse_mode": parse_mode,
                },
            )
            return resp.json()
    except httpx.TimeoutException:
        return {"ok": False, "error": "timeout"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def enviar_arquivo(
    path: Union[str, Path],
    caption: str = "",
    chat_id: str = "",
) -> dict:
    """
    Send a file to a Telegram chat as a document.

    Args:
        path:    Path to the file to send.
        caption: Optional caption text.
        chat_id: Target chat ID. Falls back to TELEGRAM_CHAT_ID env var.

    Returns:
        Telegram API response dict.
    """
    target = chat_id or os.environ.get("TELEGRAM_CHAT_ID", CHAT_ID)
    base = _base_url()
    if not base or not target:
        return {"ok": False, "error": "BOT_TOKEN ou CHAT_ID não configurado"}

    file_path = Path(path)
    if not file_path.exists():
        return {"ok": False, "error": f"Arquivo não encontrado: {path}"}

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            with open(file_path, "rb") as f:
                resp = await client.post(
                    f"{base}/sendDocument",
                    data={"chat_id": target, "caption": caption[:1024] if caption else ""},
                    files={"document": (file_path.name, f, "application/octet-stream")},
                )
            return resp.json()
    except httpx.TimeoutException:
        return {"ok": False, "error": "timeout ao enviar arquivo"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def enviar_resumo_diario(report: dict) -> dict:
    """
    Send a nicely formatted daily summary report to Telegram.

    Args:
        report: Daily report dict from scheduler (contains doerj and alertas stats).

    Returns:
        Telegram API response dict.
    """
    hoje = report.get("data", str(date.today()))
    doerj = report.get("doerj", {})
    alertas = report.get("alertas", {})

    alta = alertas.get("alta", 0)
    media = alertas.get("media", 0)
    baixa = alertas.get("baixa", 0)
    total_alertas = alertas.get("total", 0)

    # Determine status emoji based on alert severity
    if alta > 0:
        status_emoji = "🔴"
        status_text = "ATENÇÃO ALTA"
    elif media > 0:
        status_emoji = "🟡"
        status_text = "ATENÇÃO MÉDIA"
    else:
        status_emoji = "🟢"
        status_text = "NORMAL"

    # Build message
    linhas = [
        f"{status_emoji} *JFN Compliance — {hoje}*",
        f"Status: *{status_text}*",
        "",
        "*📰 DOERJ do dia:*",
        f"  • Total publicações: {doerj.get('total_publicacoes', 0)}",
        f"  • Nomeações: {doerj.get('nomeacoes', 0)}",
        f"  • Contratos: {doerj.get('contratos', 0)}",
        f"  • Licitações: {doerj.get('licitacoes', 0)}",
        "",
        "*🚨 Alertas gerados:*",
        f"  🔴 Alta severidade: *{alta}*",
        f"  🟡 Média severidade: *{media}*",
        f"  🟢 Baixa severidade: *{baixa}*",
        f"  Total: {total_alertas}",
    ]

    # Top 3 alert titles
    alertas_detalhe = report.get("alertas_detalhe", [])
    alerta_alta = [a for a in alertas_detalhe if a.get("severidade") == "alta"]
    if alerta_alta:
        linhas.append("")
        linhas.append("*🔝 Top alertas (alta):*")
        for a in alerta_alta[:3]:
            titulo = a.get("titulo", "")[:80]
            linhas.append(f"  • {titulo}")

    texto = "\n".join(linhas)
    return await enviar_mensagem(texto)


async def enviar_alerta_urgente(
    titulo: str,
    descricao: str,
    severidade: str = "alta",
) -> dict:
    """
    Send an urgent alert notification to Telegram.

    Args:
        titulo:     Alert title.
        descricao:  Alert description.
        severidade: "alta" or "média".

    Returns:
        Telegram API response dict.
    """
    emoji = "🚨" if severidade == "alta" else "⚠️"
    sev_upper = severidade.upper()

    texto = (
        f"{emoji} *ALERTA {sev_upper}*\n"
        f"\n"
        f"*{titulo[:200]}*\n"
        f"\n"
        f"{descricao[:800]}"
    )
    return await enviar_mensagem(texto)


async def testar_conexao(chat_id: str = "") -> bool:
    """
    Send a test message to verify Telegram bot configuration.

    Returns:
        True if the message was sent successfully.
    """
    resp = await enviar_mensagem(
        "✅ *JFN Compliance* — conexão Telegram OK!",
        chat_id=chat_id,
    )
    return resp.get("ok", False) is True
