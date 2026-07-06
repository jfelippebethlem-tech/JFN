#!/usr/bin/env python3
"""Watcher do canal jfn-core <- jfn-agent-2. Quando a VM-2 escreve em
~/shared-brain/_handoff/from-vm2/*.md, avisa no Telegram do dono (via bot do Hermes).
Cursor evita repetir. Roda por systemd user timer (1/min)."""
import os, sys, json, pathlib
sys.path.insert(0, "/home/ubuntu/JFN")
from compliance_agent.envfile import carregar_env

INBOX = pathlib.Path.home() / "shared-brain/_handoff/from-vm2"
CURSOR = pathlib.Path.home() / "shared-brain/_handoff/.core_seen.json"

def main():
    if not INBOX.exists():
        return
    carregar_env()
    tok = os.environ.get("TELEGRAM_BOT_TOKEN"); chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return
    import httpx
    seen = set(json.loads(CURSOR.read_text())) if CURSOR.exists() else set()
    novos = sorted(f for f in INBOX.glob("*.md")
                   if f.name not in (".keep",) and f.stat().st_mtime > 0 and str(f.name) not in seen)
    for f in novos:
        body = f.read_text(errors="ignore")[:3000]
        msg = f"📨 *VM-2 → jfn-core* (`{f.name}`)\n\n{body}"
        r = httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                       data={"chat_id": chat, "text": msg[:4000], "parse_mode": "Markdown"}, timeout=20).json()
        if not r.get("ok"):
            httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                       data={"chat_id": chat, "text": f"VM-2 -> core: {f.name}\n\n{body[:3500]}"}, timeout=20)
        seen.add(f.name)
    if novos:
        CURSOR.write_text(json.dumps(sorted(seen), ensure_ascii=False))
        print(f"[handoff_watcher] avisei {len(novos)}")

if __name__ == "__main__":
    main()
