# -*- coding: utf-8 -*-
"""
Ponte /claude no Telegram -> Claude Code headless na VM.

Como funciona:
  - escuta mensagens via Telegram (long polling, so 'requests', sem libs pesadas);
  - quando chega '/claude <texto>', roda: claude -p "<texto>"  (modo headless);
  - devolve a resposta no chat.

Requisitos na VM:
  - Claude Code instalado e LOGADO uma vez (claude login / API key).
  - Um token de bot SO para isso (CLAUDE_BOT_TOKEN) — um 2o bot do BotFather,
    para nao conflitar com o Yoda (o Telegram so deixa 1 poller por token).
  - Variaveis (em ~/.hermes/claude-bridge.env ou ambiente):
       CLAUDE_BOT_TOKEN=...        (token do 2o bot)
       CLAUDE_ALLOWED_USERS=45338178   (seu id; separado por virgula)

Roda como servico systemd (ver instalacao). Sob demanda: so responde a /claude.
"""
import os, sys, time, json, subprocess, urllib.parse, urllib.request

def env(k, d=None):
    v = os.environ.get(k)
    if v: return v
    p = os.path.expanduser("~/.hermes/claude-bridge.env")
    if os.path.exists(p):
        for ln in open(p, encoding="utf-8", errors="replace"):
            ln = ln.strip()
            if ln.startswith(k + "="):
                return ln.split("=", 1)[1].strip()
    return d

TOKEN = env("CLAUDE_BOT_TOKEN")
ALLOWED = {x.strip() for x in (env("CLAUDE_ALLOWED_USERS", "") or "").split(",") if x.strip()}
API = "https://api.telegram.org/bot%s/" % (TOKEN or "")
TIMEOUT_CLAUDE = 180  # seg por pergunta

def api(method, **params):
    data = urllib.parse.urlencode(params).encode()
    try:
        return json.load(urllib.request.urlopen(API + method, data=data, timeout=70))
    except Exception as e:
        print("api err", method, str(e)[:80], flush=True)
        return {}

def send(chat, text):
    # Telegram limita ~4096 chars
    for i in range(0, len(text) or 1, 3500):
        api("sendMessage", chat_id=chat, text=(text[i:i+3500] or "(vazio)"))

def rodar_claude(prompt):
    try:
        r = subprocess.run(["claude", "-p", prompt],
                           capture_output=True, text=True, timeout=TIMEOUT_CLAUDE)
        out = (r.stdout or "").strip() or (r.stderr or "").strip()
        return out or "(sem saida)"
    except FileNotFoundError:
        return "Claude Code nao encontrado na VM. Instale e logue (claude login)."
    except subprocess.TimeoutExpired:
        return "Demorou demais (timeout). Tente uma pergunta mais simples."
    except Exception as e:
        return "Erro: %s" % str(e)[:200]

def main():
    if not TOKEN:
        print("FALTA CLAUDE_BOT_TOKEN (em ~/.hermes/claude-bridge.env)"); sys.exit(1)
    print("Ponte /claude no ar. Aguardando comandos...", flush=True)
    offset = 0
    while True:
        upd = api("getUpdates", offset=offset, timeout=50)
        for u in upd.get("result", []):
            offset = u["update_id"] + 1
            msg = u.get("message") or u.get("edited_message") or {}
            chat = (msg.get("chat") or {}).get("id")
            uid = str((msg.get("from") or {}).get("id", ""))
            text = (msg.get("text") or "").strip()
            if not chat or not text:
                continue
            if ALLOWED and uid not in ALLOWED:
                send(chat, "Acesso negado."); continue
            if text.startswith("/claude"):
                pergunta = text[len("/claude"):].strip()
                if not pergunta:
                    send(chat, "Use: /claude <sua pergunta para o Claude>")
                    continue
                send(chat, "Pensando com o Claude...")
                send(chat, rodar_claude(pergunta))
            elif text in ("/start", "/help"):
                send(chat, "Mande: /claude <sua pergunta> que eu rodo o Claude Code aqui na VM.")
        time.sleep(1)

if __name__ == "__main__":
    main()
