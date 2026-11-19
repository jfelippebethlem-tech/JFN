"""Silêncio dos avisos automáticos de sistema no Telegram (Yoda).

Dono, 17/11/2026: "o Yoda tá me mandando várias informações sobre sistema que não pedi e nem quero. resolva".
Com `data/telegram_silencio.json` {"ativo": true}, todo aviso AUTOMÁTICO (sem chat_id explícito: ronda, SLO,
contingência, motor, vigias, digest, meta-cognição…) deixa de ir ao Telegram e vai só para
`data/telegram_silenciado.jsonl` (hora, origem, tamanho e o começo do texto, para auditoria). Continuam:
respostas a comandos do dono (chat_id explícito), o código do MFA (envio próprio) e o que for rodado com
JFN_TELEGRAM_PEDIDO=1 (relatório que o dono pediu).
"""
from __future__ import annotations

import contextvars
import inspect
import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DATA = Path(os.environ.get("JFN_DATA_DIR") or Path(__file__).resolve().parents[2] / "data")
# Pedido do dono dentro do jfn.service (relatório/dossiê gerado em asyncio.create_task pelas rotas):
# `PEDIDO.set(True)` no início da tarefa vale só para ela; o processo continua silenciando os avisos.
PEDIDO: contextvars.ContextVar[bool] = contextvars.ContextVar("telegram_pedido", default=False)


def ativo() -> bool:
    try:
        return bool(json.loads((DATA / "telegram_silencio.json").read_text()).get("ativo"))
    except (OSError, ValueError):
        return False


def silenciar(texto: str, origem: str = "") -> bool:
    """True = NÃO enviar (registrado no log). False = pode enviar."""
    if os.environ.get("JFN_TELEGRAM_PEDIDO") == "1" or PEDIDO.get() or not ativo():
        return False
    if not origem:
        mods = [f.frame.f_globals.get("__name__", "") for f in inspect.stack()[1:8]]
        origem = next((m for m in mods if m and not m.startswith(("compliance_agent.notifications", "asyncio"))), "?")
    try:
        with (DATA / "telegram_silenciado.jsonl").open("a") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "origem": origem, "chars": len(texto or ""),
                                "inicio": (texto or "")[:120]}, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.debug("registro de aviso silenciado (origem=%s) não gravado: %s", origem, exc)
    return True
