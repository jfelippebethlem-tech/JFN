#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera um .txt com (1) RESUMO do que foi feito + (2) cópia legível da sessão (mensagens user/assistant, sem o
ruído dos tool-outputs gigantes) e envia ao Mestre Jorge pelo Telegram (bot admin, sendDocument).

NÃO usa IA — só lê o transcript .jsonl da sessão e chama a API do Telegram.
    python tools/enviar_sessao_telegram.py <transcript.jsonl> [resumo.txt]
"""
import json
import re
import sys
from pathlib import Path

import httpx

HERMES_ENV = Path("/home/jfelippebethlem/.hermes/.env")


def _key(name: str) -> str:
    try:
        m = re.search(rf"^{name}=(.+)$", HERMES_ENV.read_text(), re.M)
        return m.group(1).strip().strip('"').strip("'") if m else ""
    except Exception:
        return ""


def _texto_de(content) -> str:
    """Extrai texto legível de um campo content (string ou lista de blocos)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        partes = []
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text":
                partes.append(b.get("text", ""))
            elif t == "tool_use":
                nome = b.get("name", "tool")
                partes.append(f"[ferramenta: {nome}]")
            elif t == "tool_result":
                partes.append("[resultado de ferramenta omitido]")
        return "\n".join(p for p in partes if p)
    return ""


def extrair_conversa(jsonl: Path) -> str:
    linhas = []
    for raw in jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            o = json.loads(raw)
        except Exception:
            continue
        msg = o.get("message") or {}
        role = msg.get("role") or o.get("type")
        if role not in ("user", "assistant"):
            continue
        txt = _texto_de(msg.get("content", "")).strip()
        # pula mensagens que são só resultado de ferramenta / system reminders longos
        if not txt or txt == "[resultado de ferramenta omitido]":
            continue
        if txt.startswith("[ferramenta:") and len(txt) < 40:
            continue
        quem = "🧑 MESTRE" if role == "user" else "🤖 CLAUDE"
        linhas.append(f"\n{'='*70}\n{quem}\n{'='*70}\n{txt}")
    return "\n".join(linhas)


def main():
    jsonl = Path(sys.argv[1])
    resumo_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    resumo = resumo_path.read_text(encoding="utf-8") if resumo_path and resumo_path.exists() else "(sem resumo)"

    conversa = extrair_conversa(jsonl)
    out = (f"SESSÃO JFN — {jsonl.stem}\n{'#'*70}\nRESUMO DO QUE FOI FEITO\n{'#'*70}\n\n{resumo}\n\n\n"
           f"{'#'*70}\nTRANSCRIÇÃO DA SESSÃO (mensagens; tool-outputs omitidos)\n{'#'*70}\n{conversa}\n")
    dest = Path("/home/jfelippebethlem/JFN/data/sessao_jfn_2026-06-06.txt")
    dest.write_text(out, encoding="utf-8")
    print(f"txt gerado: {dest} ({dest.stat().st_size/1024:.0f} KB)")

    token = _key("TELEGRAM_BOT_TOKEN")
    chat = "45338178"  # Mestre Jorge (allowed_users do Hermes)
    if not token:
        print("ERRO: TELEGRAM_BOT_TOKEN não encontrado em ~/.hermes/.env"); sys.exit(1)
    with open(dest, "rb") as f:
        r = httpx.post(f"https://api.telegram.org/bot{token}/sendDocument",
                       data={"chat_id": chat,
                             "caption": "📄 Sessão JFN 2026-06-06 — resumo + transcrição completa."},
                       files={"document": ("sessao_jfn_2026-06-06.txt", f, "text/plain")}, timeout=120)
    ok = r.json().get("ok", False)
    print("Telegram sendDocument:", r.status_code, "ok=" + str(ok))
    if not ok:
        print(r.text[:300])


if __name__ == "__main__":
    main()
