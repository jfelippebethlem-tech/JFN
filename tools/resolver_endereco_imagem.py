# -*- coding: utf-8 -*-
"""resolver_endereco_imagem — RESOLVE os endereços INDISPONÍVEL por análise de IMAGEM (satélite/rua) + VLM.

Quando o OSM tem a rua mas não o número (maioria no BR), o `endereco_verificacao` fica INDISPONÍVEL.
Este passo pega esses casos (com coordenada do logradouro) e classifica o LOCAL por imagem: satélite Esri
(grátis, sem chave) ou Google Street View (se houver `GOOGLE_MAPS_KEY`, mais preciso) → VLM (Gemini pool).
Atualiza o veredito: terreno_baldio / barraco / casa / comercial… → status INDÍCIO ou AFASTADO.

HONESTO: o satélite usa a coord do logradouro (±~100m) → veredito do ENTORNO/quadra, não do lote exato;
ótimo p/ flagrar rural/baldio/aberto e confirmar comercial, mais fraco p/ lote-a-lote em área mista — aí o
Street View (chave) resolve. Indício ≠ acusação; confirmar in loco. Idempotente/resumível (só os ainda sem visual).

Uso: PYTHONPATH=. .venv/bin/python -m tools.resolver_endereco_imagem [--limite N] [--ug UG] [--pausa S]
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from compliance_agent.verificacao_endereco import classificar_local_por_imagem

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"


def _garante_colunas(con: sqlite3.Connection) -> None:
    cols = {r[1] for r in con.execute("PRAGMA table_info(endereco_verificacao)")}
    for c, t in (("visual_classe", "TEXT"), ("visual_conf", "REAL"), ("visual_fonte", "TEXT"),
                 ("visual_em", "TEXT")):
        if c not in cols:
            con.execute(f"ALTER TABLE endereco_verificacao ADD COLUMN {c} {t}")
    con.commit()


def _gap(con: sqlite3.Connection, ug: str | None, limite: int) -> list[tuple]:
    q = ("SELECT ev.cnpj, ev.lat, ev.lon FROM endereco_verificacao ev "
         "WHERE ev.status='INDISPONIVEL' AND ev.lat IS NOT NULL AND ev.visual_classe IS NULL")
    params: list = []
    if ug:
        q += (" AND ev.cnpj IN (SELECT DISTINCT replace(replace(replace(favorecido_cpf,'.',''),'-',''),'/','') "
              "FROM ordens_bancarias WHERE ug_codigo=?)")
        params.append(str(ug))
    if limite > 0:
        q += " LIMIT ?"
        params.append(limite)
    return con.execute(q, params).fetchall()


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve INDISPONÍVEL por imagem (satélite/rua + VLM)")
    ap.add_argument("--limite", type=int, default=200, help="máximo por execução (lote)")
    ap.add_argument("--ug", default="", help="priorizar fornecedores desta UG")
    ap.add_argument("--pausa", type=float, default=0.4, help="pausa entre alvos (s)")
    a = ap.parse_args()
    load_dotenv(str(_REPO / ".env"))

    con = sqlite3.connect(str(_DB))
    _garante_colunas(con)
    alvos = _gap(con, a.ug or None, a.limite)
    ts = datetime.now().isoformat(timespec="seconds")
    print(f"[resolver_img] {len(alvos)} endereço(s) INDISPONÍVEL a resolver por imagem"
          + (f" · UG {a.ug}" if a.ug else ""), flush=True)
    ind = afa = inc = 0
    for i, (cnpj, lat, lon) in enumerate(alvos, 1):
        try:
            r = classificar_local_por_imagem(lat, lon)
        except Exception as e:  # noqa: BLE001
            r = {"ok": False, "status": "INDISPONIVEL", "evidencia": f"erro: {str(e)[:50]}"}
        classe = r.get("classe", "") or ""
        # grava o veredito visual; sobe o status só quando a imagem deu um resultado conclusivo
        novo_status = r["status"] if r.get("ok") and r["status"] in ("INDICIO", "AFASTADO") else "INDISPONIVEL"
        con.execute(
            "UPDATE endereco_verificacao SET status=?, nivel=?, evidencia=?, "
            "visual_classe=?, visual_conf=?, visual_fonte=?, visual_em=? WHERE cnpj=?",
            (novo_status, r.get("nivel", "—"), (r.get("evidencia", "") or "")[:500],
             classe or "indeterminado", float(r.get("confianca") or 0), r.get("fonte", ""), ts, cnpj))
        con.commit()
        if novo_status == "INDICIO":
            ind += 1
            print(f"  → INDÍCIO {classe} (conf {r.get('confianca'):.0%}) cnpj {cnpj}", flush=True)
        elif novo_status == "AFASTADO":
            afa += 1
        else:
            inc += 1
        if i % 25 == 0:
            print(f"  {i}/{len(alvos)} | indício={ind} afastado={afa} inconclusivo={inc}", flush=True)
        time.sleep(a.pausa)
    con.close()
    print(f"[resolver_img] FIM: {len(alvos)} processados · {ind} indício visual · {afa} afastados · "
          f"{inc} inconclusivos", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
