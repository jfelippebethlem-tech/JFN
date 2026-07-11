#!/usr/bin/env python3
"""Alerta incremental no Telegram dos contratos do FUNESBOM recém-coletados COM red flags relevantes.
Cursor evita repetição. Não spamma captura rasa (exige red_flags não-triviais OU valor alto + risco).
Honestidade: indício≠acusação. Roda ao fim de cada lote do supervisor."""
import os
import json
import re
import sqlite3
import pathlib
import httpx
from compliance_agent.envfile import carregar_env

DB = "/home/ubuntu/JFN/data/compliance.db"
FILA = "/home/ubuntu/JFN/data/bombeiros_sei_fila.json"
CURSOR = pathlib.Path("/home/ubuntu/JFN/data/.bombeiros_alerta_cursor.json")
TRIVIAL = re.compile(r"ausênc|ausenc|não há|nao ha|comprovante de pagamento|trecho", re.I)

def main():
    carregar_env()
    tok = os.environ.get("TELEGRAM_BOT_TOKEN"); chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print("[alerta] sem credencial telegram"); return
    fila = {x["sei"]: x for x in json.load(open(FILA))}
    enviados = set(json.loads(CURSOR.read_text())) if CURSOR.exists() else set()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    novos = []
    for ns, obj, rfj, risco in con.execute(
            "SELECT f.numero_sei,f.objeto,f.red_flags,a.nivel_risco FROM sei_ficha f "
            "LEFT JOIN sei_arvore a ON a.numero_sei=f.numero_sei "
            "WHERE f.numero_sei LIKE 'SEI-2700%' AND f.n_docs>0"):
        if ns in enviados or ns not in fila:
            continue
        try: rfs = json.loads(rfj) if rfj else []
        except Exception: rfs = []
        # red flags NÃO-triviais (descarta o viés de 'ausência no trecho')
        fortes = [r for r in rfs if not TRIVIAL.search(str(r))]
        m = fila[ns]; val = m.get("valor") or 0
        relevante = bool(fortes) or (val >= 5_000_000 and (risco or "") in ("alto", "médio", "medio"))
        if relevante:
            novos.append((ns, obj or "", m.get("forn") or "", val, fortes[:2]))
    con.close()
    if not novos:
        print("[alerta] nada novo relevante"); return
    novos.sort(key=lambda x: -x[3])
    linhas = ["🚒 *Bombeiros — novos suspeitos coletados* (_indício≠acusação_)\n"]
    for ns, obj, forn, val, fortes in novos[:8]:
        linhas.append(f"• *{ns}* — R$ {val:,.0f}\n  {forn[:30]} · {obj[:46]}")
        for f in fortes:
            linhas.append(f"  ⚠ {str(f)[:90]}")
    msg = "\n".join(linhas)
    r = httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                   data={"chat_id": chat, "text": msg, "parse_mode": "Markdown"}, timeout=30).json()
    if r.get("ok"):
        enviados |= {n[0] for n in novos}
        CURSOR.write_text(json.dumps(sorted(enviados), ensure_ascii=False))
        print(f"[alerta] enviados {len(novos)} (msg {r.get('result',{}).get('message_id')})")
    else:
        print("[alerta] falha:", r.get("description"))

if __name__ == "__main__":
    main()
