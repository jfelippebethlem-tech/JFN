#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bot-convidado do Yoda (Telegram) — multiusuário SEGURO para pessoas que NÃO podem mexer no código.

Por que um bot separado (e não liberar no bot admin do Hermes): o Hermes é um agente de código completo
(ferramenta `terminal` = shell). Seu allowlist é binário e `disabled_toolsets` é global — não dá para dar
acesso parcial seguro a um convidado. Este bot é MÍNIMO e estrutural-seguro: ele NÃO tem shell, NÃO executa
código, NÃO acessa arquivos. Só faz chamadas HTTP para a API do JFN (127.0.0.1:8000) em rotas de LEITURA e
devolve o texto formatado. Um convidado jamais alcança o código do ecossistema por aqui.

Segurança:
  - Allowlist própria (TELEGRAM_GUEST_USERS, IDs separados por vírgula). Quem não está na lista é recusado.
  - Token próprio (TELEGRAM_BOT_TOKEN_GUEST) — NUNCA o token do bot admin.
  - Só comandos pré-definidos e read-only. Sem eval, sem subprocess, sem filesystem.

Comandos: /ajuda, /relatorio <empresa|cnpj>, /anomalias [arg], /cartel [captura|<cnpj>].

Rodar:  TELEGRAM_BOT_TOKEN_GUEST=... TELEGRAM_GUEST_USERS=123,456 python tools/guest_bot.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
except Exception:
    pass

import httpx

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN_GUEST", "").strip()
ALLOWED = {u.strip() for u in os.environ.get("TELEGRAM_GUEST_USERS", "").split(",") if u.strip()}
JFN = os.environ.get("JFN_BASE_URL", "http://127.0.0.1:8000")
API = f"https://api.telegram.org/bot{TOKEN}"

AJUDA = (
    "👋 *Assistente JFN (convidado)*\n\n"
    "Comandos disponíveis (somente consulta):\n"
    "• `/relatorio <empresa ou CNPJ>` — resumo de inteligência do fornecedor\n"
    "• `/anomalias [órgão ou fornecedor]` — Ordens Bancárias de maior risco\n"
    "• `/cartel [captura | <CNPJ>]` — indícios de concentração/cartel\n\n"
    "_Tudo é indício para apuração, nunca acusação. Este assistente só lê dados — não altera nada._"
)


def _send(chat_id, texto: str):
    try:
        httpx.post(f"{API}/sendMessage", json={
            "chat_id": chat_id, "text": texto[:4000],
            "parse_mode": "Markdown", "disable_web_page_preview": True}, timeout=20)
    except Exception:
        pass


def _jfn_get(path: str) -> dict:
    try:
        return httpx.get(f"{JFN}{path}", timeout=60).json()
    except Exception as e:
        return {"ok": False, "erro": str(e)[:120]}


def _jfn_post(path: str, body: dict) -> dict:
    try:
        return httpx.post(f"{JFN}{path}", json=body, timeout=120).json()
    except Exception as e:
        return {"ok": False, "erro": str(e)[:120]}


def cmd_relatorio(arg: str) -> str:
    if not arg:
        return "Uso: `/relatorio <empresa ou CNPJ>` (ex.: `/relatorio MGS Clean`)."
    corpo = {"cnpj": arg} if arg.replace(".", "").replace("/", "").replace("-", "").isdigit() else {"empresa": arg}
    r = _jfn_post("/api/relatorio/inteligencia", corpo)
    if r.get("ambiguo"):
        return "🔎 " + r.get("pergunta", "Vários resultados — especifique melhor.")
    if not r.get("ok"):
        return f"Não consegui gerar: {r.get('erro') or r.get('empresa') or 'sem dados'}."
    grau = r.get("grau_lex") or "—"
    return (f"📄 *{r.get('empresa','')}*\nRisco: {r.get('risco','—')} (score {r.get('score','—')}/100) | "
            f"Grau jurídico (Lex): {grau}\n\n{(r.get('resumo') or '')[:1500]}")


def cmd_anomalias(arg: str) -> str:
    q = "/api/anomalias?top=8"
    if arg:
        chave = "fornecedor" if not arg.isdigit() else "orgao"
        q += f"&{chave}={httpx.QueryParams({'x': arg})['x']}"
    r = _jfn_get(q)
    if not r.get("ok") or not r.get("itens"):
        return "Sem anomalias para esse filtro (ou o detector ainda não rodou)."
    linhas = ["🚨 *OBs de maior risco* (indício, não acusação):"]
    for it in r["itens"][:8]:
        linhas.append(f"• R$ {it.get('valor',0):,.0f} — {(it.get('fornecedor') or '')[:30]} "
                      f"(score {it.get('score')}) — {it.get('regras') or '—'}")
    return "\n".join(linhas)


def cmd_cartel(arg: str) -> str:
    if arg and not arg.lower().startswith("captura"):
        cnpj = arg
        r = _jfn_get(f"/api/cartel?modo=vizinhanca&cnpj={cnpj}&top=8")
        d = r.get("dados", {})
        viz = d.get("vizinhos", [])
        if not viz:
            return "Sem co-ocorrência relevante para esse CNPJ."
        linhas = [f"🕸️ *Rede* — atua em {d.get('n_orgaos',0)} órgãos. Co-ocorrentes (indício a verificar):"]
        for v in viz[:8]:
            linhas.append(f"• {(v.get('nome') or '')[:32]} — {v.get('orgaos_comuns')} órgãos em comum")
        return "\n".join(linhas)
    r = _jfn_get("/api/cartel?modo=captura&top=8")
    dados = r.get("dados", [])
    if not dados:
        return "Sem dados de captura no momento."
    linhas = ["🏛️ *Órgãos mais concentrados* (indício de captura, a verificar):"]
    for d in dados[:8]:
        linhas.append(f"• {(d.get('ug_nome') or '')[:30]} — top {d.get('top_share')}% p/ {(d.get('top_fornecedor') or '')[:24]}")
    return "\n".join(linhas)


def tratar(texto: str) -> str:
    texto = (texto or "").strip()
    low = texto.lower()
    if low.startswith("/relatorio"):
        return cmd_relatorio(texto[len("/relatorio"):].strip())
    if low.startswith("/anomalias"):
        return cmd_anomalias(texto[len("/anomalias"):].strip())
    if low.startswith("/cartel"):
        return cmd_cartel(texto[len("/cartel"):].strip())
    return AJUDA


def main():
    if not TOKEN:
        print("ERRO: defina TELEGRAM_BOT_TOKEN_GUEST (token de um bot SEPARADO, criado no @BotFather).")
        sys.exit(1)
    if not ALLOWED:
        print("AVISO: TELEGRAM_GUEST_USERS vazio — ninguém será atendido. Defina os IDs permitidos.")
    print(f"Bot-convidado no ar. Usuários permitidos: {sorted(ALLOWED) or '(nenhum)'}")
    offset = 0
    while True:
        try:
            r = httpx.get(f"{API}/getUpdates", params={"offset": offset, "timeout": 50}, timeout=60).json()
        except Exception:
            time.sleep(3); continue
        for upd in r.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message") or {}
            chat = msg.get("chat", {}).get("id")
            uid = str(msg.get("from", {}).get("id", ""))
            texto = msg.get("text", "")
            if not chat or not texto:
                continue
            if uid not in ALLOWED:
                _send(chat, "⛔ Acesso restrito. Peça ao Mestre Jorge para autorizar seu usuário.")
                continue
            try:
                _send(chat, tratar(texto))
            except Exception as e:  # noqa: BLE001
                _send(chat, f"Erro ao processar: {str(e)[:100]}")


if __name__ == "__main__":
    main()
