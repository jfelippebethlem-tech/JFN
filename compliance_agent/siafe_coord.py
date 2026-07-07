# -*- coding: utf-8 -*-
"""
Coordenação de sessão única do SIAFE entre o COLETOR (JFN) e o MESTRE JORGE, via Telegram.

O SIAFE só permite UMA sessão por usuário. Se o coletor logar, derruba o navegador do Jorge; se o Jorge
logar, derruba o coletor. Em vez de esperar um tempo fixo, o coletor **pergunta ao Jorge no Telegram** e
aguarda ele liberar.

Como funciona (sem brigar com o long-poll do gateway do Yoda):
  - O coletor NÃO lê o Telegram (o gateway do Yoda é o dono do long-poll). Ele só **envia** mensagens.
  - Quem recebe a resposta do Jorge é o **Yoda**, que escreve o arquivo-flag `siafe_coord.json` com o estado.
  - O coletor lê esse flag. Estados: "livre" (pode coletar) | "ocupado" (Jorge está usando — aguardar).

Yoda deve, ao receber mensagens do Jorge, escrever o flag (instruções na memória do Yoda):
  - "siafe livre" / "liberei o siafe" / "terminei o siafe" / "pode usar o siafe"  -> {"siafe":"livre"}
  - "siafe ocupado" / "vou usar o siafe" / "estou no siafe"                        -> {"siafe":"ocupado"}
"""
from __future__ import annotations

import logging
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_FLAG = _REPO / "data" / "sei_cache" / "siafe_coord.json"
CHAT_ID = "45338178"


logger = logging.getLogger(__name__)


def _token() -> str:
    # token do bot: ~/.hermes/.env (Yoda) ou .env do JFN
    for env in (Path.home() / ".hermes" / ".env", _REPO / ".env"):
        try:
            for ln in env.read_text(encoding="utf-8-sig").splitlines():
                if ln.strip().startswith("TELEGRAM_BOT_TOKEN="):
                    return ln.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception as exc:
            logger.debug("%s sem token legível: %s", env, exc)
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def notificar(texto: str) -> bool:
    """Envia uma mensagem ao Mestre Jorge no Telegram (best-effort)."""
    tok = _token()
    if not tok:
        return False
    try:
        data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": texto}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception:
        return False


def set_status(estado: str, msg: str = ""):
    """Escreve o flag (usado pelo Yoda ao receber o aviso do Jorge, e pelo coletor para 'coletor_rodando')."""
    _FLAG.parent.mkdir(parents=True, exist_ok=True)
    _FLAG.write_text(json.dumps({"siafe": estado, "msg": msg, "ts": int(time.time())},
                                ensure_ascii=False), encoding="utf-8")


def get_status() -> str:
    """Estado atual: 'livre' (default) | 'ocupado' | 'coletor_rodando'."""
    try:
        return json.loads(_FLAG.read_text(encoding="utf-8")).get("siafe", "livre")
    except Exception:
        return "livre"


def aguardar_liberacao(motivo: str, timeout_total_s: int = 6 * 3600, poll_s: int = 60,
                       reping_s: int = 1800, _sleep=None) -> bool:
    """
    Pergunta ao Jorge no Telegram e aguarda ele liberar o SIAFE (flag 'livre').
    Retorna True quando liberado; False se estourar `timeout_total_s` (fallback).
    `_sleep` é injetável para teste.
    """
    import time as _t
    sleep = _sleep or _t.sleep
    notificar(
        "🛰️ JFN — varredura do SIAFE\n\n"
        f"Conflito de sessão: {motivo}.\n"
        "O SIAFE só deixa 1 sessão por vez. Me avise aqui quando puder liberar:\n"
        "• responda *siafe livre* (ou 'terminei o siafe') que eu retomo na hora;\n"
        "• ou *siafe ocupado* se ainda vai usar — eu continuo aguardando.\n"
        "Vou guardando o progresso; nada se perde.")
    inicio = _t.time() if hasattr(_t, "time") else 0
    prox_ping = inicio + reping_s
    # marca que estamos aguardando o Jorge
    try:
        set_status("ocupado", motivo)
    except Exception as exc:
        logger.debug("set_status('ocupado') falhou: %s", exc)
    while True:
        try:
            agora = _t.time()
        except Exception:
            agora = inicio + poll_s
        if get_status() == "livre":
            notificar("✅ SIAFE liberado — retomando a varredura agora. Obrigado, Mestre Jorge.")
            return True
        if agora - inicio >= timeout_total_s:
            notificar("⌛ Não tive retorno sobre o SIAFE; vou tentar uma rodada mesmo assim.")
            return False
        if agora >= prox_ping:
            notificar("⏳ Ainda preciso do SIAFE quando você puder. Responda *siafe livre* que eu retomo.")
            prox_ping = agora + reping_s
        sleep(poll_s)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in ("livre", "ocupado", "coletor_rodando"):
        set_status(sys.argv[1], " ".join(sys.argv[2:]))
        print(f"flag SIAFE = {sys.argv[1]}")
    else:
        print(f"status atual: {get_status()}")
