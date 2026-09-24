# -*- coding: utf-8 -*-
"""Consulta SOB DEMANDA de processo SEI da Prefeitura (VM-2) — o que a pesquisa pública do SEI.RIO mostra.

Canal (Syncthing, um escritor por pasta — o sync já apagou arquivo com dois escritores):
  ~/shared-brain/sei_pcrj_consulta/pedidos/<slug>.req   ← escrito SÓ pela VM-1 (conteúdo: o número)
  ~/shared-brain/sei_pcrj_consulta/respostas/<slug>.json ← escrito SÓ por aqui

Para cada pedido sem resposta (ou com resposta de mais de 1 dia): a mesma captura do sweep (`capturar`, captcha
por ddddocr) → árvore (documentos: nº, tipo, data, unidade), andamentos e assinaturas. Também grava na base
local (`gravar_arvore`) para o sync normal levar à VM-1. Um navegador por vez (flock), no máximo N pedidos por
rodada, nice. Roda por timer a cada 2 min.

    python sei_pcrj_consulta.py [--max 3]
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/home/ubuntu/sei-pcrj")
import sei_pcrj_sweep as S  # noqa: E402

BASE = Path("/home/ubuntu/shared-brain/sei_pcrj_consulta")
PED, RESP = BASE / "pedidos", BASE / "respostas"
VALIDADE_S = 86_400


def slug(numero: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", numero.strip()).strip("_")


def pendentes(maxn: int) -> list[str]:
    out = []
    for p in sorted(PED.glob("*.req"), key=lambda x: x.stat().st_mtime):
        r = RESP / (p.stem + ".json")
        if not r.exists() or r.stat().st_mtime < p.stat().st_mtime or time.time() - r.stat().st_mtime > VALIDADE_S:
            n = p.read_text(encoding="utf-8").strip()
            if n:
                out.append(n)
        if len(out) >= maxn:
            break
    return out


def gravar(numero: str, r: dict) -> None:
    RESP.mkdir(parents=True, exist_ok=True)
    arv = r.get("arvore") or {}
    doc = {"numero": numero, "consultado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "encontrado": bool(r.get("disponivel")), "erro": r.get("erro"),
           "tipo_processo": arv.get("tipo_processo"), "n_registros": arv.get("n_registros"),
           "documentos": arv.get("docs") or [], "andamentos": arv.get("andamentos") or [],
           "assinaturas": arv.get("assinaturas") or [], "fonte": "pesquisa pública SEI.RIO (prefeitura.sei.rio)"}
    tmp = RESP / (slug(numero) + ".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    tmp.replace(RESP / (slug(numero) + ".json"))
    if arv.get("docs"):
        try:
            con = S._db()
            S.gravar_arvore(con, numero, arv)
            con.commit()
            con.close()
        except Exception as e:  # noqa: BLE001 — a resposta já foi entregue; a base local é bônus
            print(f"{numero}: árvore não gravada na base local ({type(e).__name__})")


async def rodar(nums: list[str]) -> None:
    async def fn(pg):
        for n in nums:
            try:
                r = await S.capturar(pg, n, max_captchas=40)
            except Exception as e:  # noqa: BLE001 — um pedido ruim não derruba os outros
                r = {"disponivel": 0, "erro": f"{type(e).__name__}: {str(e)[:120]}"}
            gravar(n, r)
            print(f"{datetime.now():%H:%M:%S} {n}: {'ok' if r.get('disponivel') else 'sem resultado'} "
                  f"({len((r.get('arvore') or {}).get('docs') or [])} docs)")
    await S._com_browser(fn)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=3)
    a = ap.parse_args()
    PED.mkdir(parents=True, exist_ok=True)
    lock = open("/tmp/sei-pcrj-consulta.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    nums = pendentes(a.max)
    if nums:
        asyncio.run(rodar(nums))


if __name__ == "__main__":
    main()
