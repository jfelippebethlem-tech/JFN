#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doubt_sender_fachada — envia ao Telegram do dono as DÚVIDAS de fachada que mais importam.

Para cada dúvida de endereço (verificação INDISPONÍVEL/indeterminada) ranqueada pelo R$ recebido em OB,
busca a foto Street View do ponto e manda foto+contexto honesto ao dono, que responde fachada/real/pular
(capturado por `tools/registrar_vereditos_fachada.py`). O veredito humano vira a verdade na DD.

VM-safe: lote bounded, respeita a cota paga do Street View, dedup (não reenvia), `--dry-run` p/ inspecionar.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.doubt_sender_fachada [--limite 15] [--dry-run]
                                   [--exato-apenas] [--min-recebido 0] [--chat <id>]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compliance_agent import fachada_doubt as fd  # noqa: E402

_HERMES_ENV = Path.home() / ".hermes" / ".env"
_JFN_ENV = Path(__file__).resolve().parents[1] / ".env"


def _env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if v:
        return v
    for f in (_JFN_ENV, _HERMES_ENV):
        try:
            m = re.search(rf"^{name}=(.+)$", Path(f).read_text(), re.M)
            if m:
                return m.group(1).strip().strip('"').strip("'")
        except Exception:
            continue
    return ""


def _carregar_env() -> None:
    """Popula o os.environ a partir do .env (setdefault) — `foto_rua` lê GOOGLE_MAPS_KEY/MAPILLARY_TOKEN
    direto do ambiente; rodando como módulo CLI o .env não está carregado (no jfn.service está)."""
    for f in (_JFN_ENV, _HERMES_ENV):
        try:
            for line in Path(f).read_text().splitlines():
                m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.+?)\s*$", line)
                if m and not os.environ.get(m.group(1)):
                    os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")
        except Exception:
            continue


def _enviar_foto(token: str, chat: str, img: bytes, caption: str) -> int | None:
    """sendPhoto; devolve message_id ou None. Detecta PNG (navegador) vs JPEG (API Static)."""
    png = img[:4] == b"\x89PNG"
    nome, mime = ("sede.png", "image/png") if png else ("sede.jpg", "image/jpeg")
    r = httpx.post(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data={"chat_id": chat, "caption": caption[:1024]},
        files={"photo": (nome, img, mime)}, timeout=90)
    j = r.json()
    if not j.get("ok"):
        print(f"   ⚠ Telegram sendPhoto falhou: {r.status_code} {str(j)[:160]}")
        return None
    return j.get("result", {}).get("message_id")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=15, help="máx. de dúvidas a enviar nesta passada")
    ap.add_argument("--min-recebido", type=float, default=0.0, help="só empresas com OB acima deste valor")
    ap.add_argument("--exato-apenas", action="store_true", help="só endereços com número geolocalizado")
    ap.add_argument("--todas", action="store_true",
                    help="não exigir marcador residencial (inclui dúvidas de qualquer perfil)")
    ap.add_argument("--dry-run", action="store_true", help="seleciona e monta a legenda; NÃO envia")
    ap.add_argument("--chat", default="", help="chat_id destino (default: TELEGRAM_CHAT_ID/.env)")
    ap.add_argument("--pausa", type=float, default=1.5, help="pausa entre envios (s)")
    a = ap.parse_args()

    _carregar_env()
    token = _env("TELEGRAM_BOT_TOKEN")
    chat = a.chat or _env("TELEGRAM_CHAT_ID") or "45338178"
    if not a.dry_run and not token:
        print("ERRO: TELEGRAM_BOT_TOKEN ausente (.env/~/.hermes/.env)"); return 2

    con = fd.conectar()
    cands = fd.candidatos(con, limite=a.limite, incluir_aproximado=not a.exato_apenas,
                          min_recebido=a.min_recebido, so_residencial=not a.todas)
    if not cands:
        print("Nenhuma dúvida pendente no critério (todas já enviadas ou sem cobertura).")
        return 0

    print(f"{len(cands)} dúvida(s) selecionada(s) — foto via API Street View Static.")

    enviados = sem_foto = 0
    for c in cands:
        codigo = fd.codigo_de(c["cnpj"])
        end = fd.endereco_completo(c)
        img, fonte, info = fd.foto_rua(end)   # metadata (grátis) → coord/heading → foto Static
        cap = fd.legenda(c, codigo, fonte if img else "—", info)
        loc = f"({info.get('lat'):.4f},{info.get('lon'):.4f})" if info.get("lat") else ""
        cab = (f"[{codigo}] {c.get('razao') or c['cnpj']} — {fd._moeda(c.get('total_recebido'))} — "
               f"{fonte if img else 'SEM FOTO'} {loc}")
        if img is None:
            sem_foto += 1
            print(f"  ✗ {cab} → não envia")
            continue
        if a.dry_run:
            print(f"  • DRY {cab}  pano {info.get('date', '?')} heading={info.get('heading', '—')} "
                  f"({len(img)} bytes)")
            continue
        mid = _enviar_foto(token, chat, img, cap)
        if mid is not None:
            fd.registrar_envio(con, c, codigo, fonte, mid)
            enviados += 1
            print(f"  ✓ {cab}  (msg {mid})")
        time.sleep(a.pausa)

    print(f"\nFIM: enviados={enviados} sem_foto={sem_foto} dry_run={a.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
