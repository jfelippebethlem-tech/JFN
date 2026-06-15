# -*- coding: utf-8 -*-
"""
MFA via Telegram — fluxo CODIFICADO e robusto (não depende de IA esperta na hora).

Quando um login (SIAFE/SEI) bate na tela de MFA, este módulo:
  1. ENVIA o pedido ao Mestre Jorge no Telegram (sendMessage; NÃO compete com o long-poll do gateway do Yoda);
  2. CAPTURA a resposta dele PASSIVAMENTE lendo o `state.db` do Yoda (role=user, source telegram, após o pedido)
     — sem 2º bot, sem conflito getUpdates (lição §9 do projeto);
  3. extrai o código (4–8 dígitos) e o devolve, gravando também em `data/sei_cache/.mfa_code`
     (auditoria + fallback manual via SSH).

Duas fontes, a 1ª que aparecer vence: (a) captura passiva do Telegram; (b) arquivo `.mfa_code`
(o dono/operador pode escrever direto por SSH). Assim funciona mesmo se a captura passiva falhar.

Uso programático:
    from compliance_agent.mfa_telegram import pedir_codigo_mfa
    codigo = pedir_codigo_mfa("SIAFE", timeout_s=300)   # bloqueia até o dono responder ou estourar o timeout

CLI (teste do envio + captura, sem login):
    python -m compliance_agent.mfa_telegram --pedir SIAFE
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from compliance_agent.fachada_doubt import _texto_resposta, mensagens_novas_telegram
from compliance_agent.siafe_coord import notificar

_REPO = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("JFN_DATA_DIR", _REPO / "data")) / "sei_cache"
CODE_FILE = DATA / ".mfa_code"

# Código MFA = 4–8 chars alfanuméricos. O SIAFE-Rio usa token ALFANUMÉRICO (ex.: "8UvDWguB"); outros
# sistemas usam só dígitos. \b para não casar pedaços de blocos maiores (CNPJ, valores).
_CODE_RE = re.compile(r"\b([A-Za-z0-9]{4,8})\b")


def extrair_codigo(texto: str) -> str | None:
    """Extrai o código MFA do texto livre do dono, limpando quote/prefixo. None se não houver.

    Aceita (a) código puramente NUMÉRICO 4–8 díg; (b) token ALFANUMÉRICO MISTO (≥1 letra E ≥1 dígito,
    ex.: SIAFE "8UvDWguB"). Rejeita palavras comuns ("respondido", "obrigado") p/ não capturar lixo.
    """
    t = _texto_resposta(texto or "")
    for m in _CODE_RE.finditer(t):
        tok = m.group(1)
        if tok.isdigit():
            return tok
        if any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok):
            return tok
    return None


def _ler_arquivo_codigo() -> str | None:
    """Lê um código posto manualmente em .mfa_code (fallback SSH/operador)."""
    try:
        if CODE_FILE.exists():
            c = (CODE_FILE.read_text(encoding="utf-8") or "").strip()
            return extrair_codigo(c) or (c if c.isdigit() and 4 <= len(c) <= 8 else None)
    except Exception:
        pass
    return None


def pedir_codigo_mfa(sistema: str = "SIAFE", timeout_s: int = 300, poll_s: int = 5,
                     state_db=None, *, _agora=time.time, _sleep=time.sleep) -> str | None:
    """
    Pede o código MFA ao dono no Telegram e captura a resposta. Retorna o código (str) ou None (timeout).

    - Envia 1 pedido (e re-pings discretos a cada ~90s).
    - Captura passiva do state.db do Yoda + fallback no arquivo .mfa_code.
    - `_agora`/`_sleep` são injetáveis para teste (não dorme de verdade nos testes).
    """
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        if CODE_FILE.exists():
            CODE_FILE.unlink()  # descarta código velho — só vale o desta rodada
    except Exception:
        pass

    desde = _agora()
    notificar(
        f"🔐 {sistema} — o login precisa do código MFA.\n\n"
        "Responda AQUI com o código (4 a 8 dígitos) que chegou no seu e-mail/app autenticador.\n"
        f"Aguardo até ~{max(1, timeout_s // 60)} min; se passar, é só repetir o login.")

    deadline = desde + timeout_s
    visto = desde
    prox_ping = desde + 90
    while _agora() < deadline:
        # (a) fallback manual/SSH
        cod = _ler_arquivo_codigo()
        if cod:
            notificar(f"✅ Código recebido — autenticando no {sistema}.")
            return cod
        # (b) captura passiva do Telegram (state.db do Yoda) — só mensagens APÓS o pedido
        try:
            for ts, texto in mensagens_novas_telegram(visto, state_db=state_db):
                visto = max(visto, ts)
                cod = extrair_codigo(texto)
                if cod:
                    try:
                        CODE_FILE.write_text(cod, encoding="utf-8")
                    except Exception:
                        pass
                    notificar(f"✅ Código recebido — autenticando no {sistema}.")
                    return cod
        except Exception:
            pass
        if _agora() >= prox_ping:
            notificar(f"⏳ Ainda aguardo o código do {sistema} (4–8 dígitos).")
            prox_ping = _agora() + 90
        _sleep(poll_s)

    notificar(f"⌛ Não recebi o código do {sistema} a tempo. Quando puder, repetimos o login.")
    return None


if __name__ == "__main__":
    import sys

    from compliance_agent.envfile import carregar_env
    carregar_env()
    sistema = "SIAFE"
    if "--pedir" in sys.argv:
        i = sys.argv.index("--pedir")
        if i + 1 < len(sys.argv):
            sistema = sys.argv[i + 1]
    print(f"[mfa] pedindo código {sistema} ao dono no Telegram (timeout 300s)…")
    c = pedir_codigo_mfa(sistema, timeout_s=300)
    print(f"[mfa] resultado: {c!r}")
