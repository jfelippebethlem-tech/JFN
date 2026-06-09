#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ronda automática do JFN — checa o serviço e os alertas, loga e (se configurado) notifica.

Roda via systemd timer (jfn-ronda.timer) a cada N minutos, INDEPENDENTE de sessão do Claude.
O que faz a cada passagem:
  1. Confere se o serviço systemd `jfn.service` está ativo; se não, tenta reiniciar.
  2. Consulta a API local: /api/hermes/estado e /api/compliance/alerts.
  3. Sempre grava uma linha em data/ronda.log.
  4. Notifica via Telegram SOMENTE em eventos (serviço caiu, API muda, novos alertas, llm fora)
     e SOMENTE se TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID estiverem preenchidos de verdade no .env.

Uso manual:  python tools/ronda.py            (uma passagem)
             python tools/ronda.py --test     (força uma notificação de teste)
"""
import os
import sys
import json
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("JFN_DATA_DIR", REPO / "data"))
DATA.mkdir(parents=True, exist_ok=True)
LOG = DATA / "ronda.log"
STATE = DATA / "ronda_state.json"
BASE = os.environ.get("JFN_BASE_URL", "http://127.0.0.1:8000")
SERVICE = os.environ.get("JFN_SERVICE", "jfn.service")

# carrega .env (token Telegram etc.) — systemd não herda o ambiente do shell
try:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
except Exception:
    pass


def agora():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def log(linha: str):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{agora()}] {linha}\n")


def http_json(path: str, timeout: int = 10):
    url = BASE + path
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def telegram_cfg():
    tok = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    # ignora placeholders do .env.example
    if not tok or not chat or tok.upper().startswith("SEU_") or chat.upper().startswith("SEU_"):
        return None
    return tok, chat


def notificar(texto: str) -> bool:
    cfg = telegram_cfg()
    if not cfg:
        log("NOTIFY pulado (Telegram não configurado): " + texto.replace("\n", " | "))
        return False
    tok, chat = cfg
    try:
        data = urllib.parse.urlencode({
            "chat_id": chat, "text": texto,
            "parse_mode": "HTML", "disable_web_page_preview": "true",
        }).encode()
        url = f"https://api.telegram.org/bot{tok}/sendMessage"
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15) as r:
            ok = json.loads(r.read().decode()).get("ok", False)
        log(("NOTIFY enviado" if ok else "NOTIFY falhou") + ": " + texto.replace("\n", " | "))
        return ok
    except Exception as e:
        log(f"NOTIFY erro {type(e).__name__}: {e}")
        return False


def servico_ativo() -> bool:
    try:
        out = subprocess.run(["systemctl", "--user", "is-active", SERVICE],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() == "active"
    except Exception:
        return False


def reiniciar_servico():
    try:
        subprocess.run(["systemctl", "--user", "restart", SERVICE], timeout=30)
    except Exception as e:
        log(f"restart erro: {e}")


def carregar_estado() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def salvar_estado(d: dict):
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    if "--test" in sys.argv:
        ok = notificar("🟢 <b>JFN ronda</b> — teste de notificação. Telegram OK.")
        print("teste enviado:", ok); return

    prev = carregar_estado()
    eventos = []  # mensagens de alerta a notificar

    # 1) serviço
    ativo = servico_ativo()
    if not ativo:
        log(f"⚠ serviço {SERVICE} NÃO ativo — tentando reiniciar")
        reiniciar_servico()
        import time; time.sleep(8)
        ativo = servico_ativo()
        eventos.append(f"🔴 Serviço <b>{SERVICE}</b> estava fora — reinício "
                       + ("OK ✅" if ativo else "FALHOU ❌"))

    # 2) API / estado
    estado, api_ok = None, False
    try:
        estado = http_json("/api/hermes/estado")
        api_ok = True
    except Exception as e:
        log(f"⚠ API /estado não respondeu: {type(e).__name__}: {e}")
    # debounce: a API pisca por ~10s sob carga do DB; só alerta se ficou fora em 2 rondas SEGUIDAS
    api_fails = 0 if api_ok else int(prev.get("api_fails", 0) or 0) + 1
    if api_fails == 2:
        eventos.append("🔴 API do JFN (8000) <b>não responde</b> há 2 rondas seguidas.")

    if api_ok:
        n_alertas = int(estado.get("n_alertas", 0) or 0)
        if not estado.get("llm_ok", True) and prev.get("llm_ok", True):
            eventos.append("🟡 LLM do agente ficou <b>indisponível</b> (llm_ok=false).")
        try:
            alerts = http_json("/api/compliance/alerts")
            n_alertas_lista = len(alerts) if isinstance(alerts, list) else int(alerts.get("total", 0))
        except Exception:
            n_alertas_lista = int(prev.get("n_alertas_lista", 0) or 0)
    else:
        # API fora: PRESERVA a contagem anterior — senão, ao voltar, 0→2 vira "2 novos alertas" falso
        n_alertas = int(prev.get("n_alertas", 0) or 0)
        n_alertas_lista = int(prev.get("n_alertas_lista", 0) or 0)

    # 3) novos alertas — só quando há monitoramento CONTÍNUO (api ok agora E na ronda anterior),
    #    evitando o falso positivo do flapping (recuperação da API não é "novo alerta")
    novos = max(n_alertas, n_alertas_lista) - max(int(prev.get("n_alertas", 0) or 0), int(prev.get("n_alertas_lista", 0) or 0))
    if novos > 0 and api_ok and prev.get("api_ok", False):
        eventos.append(f"🚨 <b>{novos} novo(s) alerta(s)</b> de compliance no JFN "
                       f"(total agora: {max(n_alertas, n_alertas_lista)}).")

    # 4) log + notificação
    status = (f"serviço={'ativo' if ativo else 'FORA'} api={'ok' if api_ok else 'FORA'} "
              f"alertas={max(n_alertas, n_alertas_lista)} eventos={len(eventos)}")
    log(status)

    if eventos:
        notificar("🛡️ <b>JFN — ronda</b>\n" + "\n".join(eventos)
                  + f"\n<code>{agora()}</code>")

    salvar_estado({
        "ativo": ativo, "api_ok": api_ok, "api_fails": api_fails,
        "llm_ok": bool(estado.get("llm_ok", True)) if api_ok else prev.get("llm_ok", True),
        "n_alertas": n_alertas, "n_alertas_lista": n_alertas_lista,
        "ultima_ronda": agora(),
    })
    print(status)


if __name__ == "__main__":
    main()
