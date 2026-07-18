#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Digest DIÁRIO no Yoda: novos processos SEI restritos detectados nos sweeps + resumo dos flags
vermelhos graves. Roda por timer (jfn-digest-diario). Estado em data/digest_estado.json (o que já foi
reportado) → só manda o que é NOVO nos restritos; os flags graves vão sempre (visão de topo).
Uso: .venv/bin/python tools/digest_diario.py            # envia
     .venv/bin/python tools/digest_diario.py --dry      # imprime, não envia
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

REPO = Path("/home/ubuntu/JFN")
sys.path.insert(0, str(REPO))
ESTADO = REPO / "data" / "digest_estado.json"


def _env():
    for ln in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", ln)
        if m:
            os.environ.setdefault(m.group(1), m.group(2).strip().strip('"').strip("'"))


def _estado() -> dict:
    if ESTADO.exists():
        try:
            return json.loads(ESTADO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"reportados": []}


def _salva_estado(st: dict):
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ESTADO)


def montar() -> tuple[str, list[str]]:
    """Monta o texto do digest. Retorna (mensagem, novas_chaves_de_restrito)."""
    from tools import sei_restritos as R
    from tools import flags_graves as F
    hoje = datetime.now().strftime("%d/%m/%Y")
    restr = R.listar(todos=False)
    st = _estado()
    ja = set(st.get("reportados", []))
    def _k(e):
        return re.sub(r"\D", "", e.get("numero", ""))
    novos = [e for e in restr if _k(e) not in ja]

    linhas = [f"🛡️ *Digest de fiscalização — {hoje}*", ""]
    # (1) restritos
    linhas.append(f"🔒 *Processos SEI restritos:* {len(restr)} no total"
                  + (f", *{len(novos)} NOVO(S)* hoje" if novos else " (nenhum novo hoje)"))
    for e in novos[:15]:
        linhas.append(f"  • `{e.get('numero','')}` — {e.get('unidade') or '?'} "
                      f"[{e.get('status','')}] {('existe: '+e['fonte_existencia']) if e.get('fonte_existencia') else ''}")
    # (2) flags graves (topo sempre)
    linhas += ["", "🚩 *Flags vermelhos graves* (visão de topo):", "", F.resumo_texto(markdown=True)]
    # (3) link do painel
    linhas += ["", "📊 Controle completo: /controle no painel."]
    novas_chaves = [_k(e) for e in novos]
    return "\n".join(linhas), novas_chaves


async def _enviar(msg: str):
    _env()
    chat = os.environ.get("TELEGRAM_OWNER_ID", "") or os.environ.get("TELEGRAM_CHAT_ID", "")
    from compliance_agent.notifications.telegram import enviar_mensagem
    return await enviar_mensagem(msg, chat_id=chat)


def main():
    dry = "--dry" in sys.argv[1:]
    msg, novas = montar()
    if dry:
        print(msg)
        print(f"\n[dry] {len(novas)} novos restritos seriam marcados como reportados.")
        return 0
    ok = asyncio.run(_enviar(msg))
    if ok:
        st = _estado()
        st["reportados"] = sorted(set(st.get("reportados", [])) | set(novas))
        st["ultimo_envio"] = datetime.now().isoformat()
        _salva_estado(st)
    print("digest enviado:", bool(ok))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
