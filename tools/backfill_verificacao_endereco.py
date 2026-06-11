# -*- coding: utf-8 -*-
"""backfill_verificacao_endereco — avalia a REALIDADE do endereço de TODA fornecedora, incrementalmente.

Sobre o `endereco_fornecedor` (que o `backfill_enderecos` mantém), roda `verificacao_endereco.analisar_endereco`
(geocode-match + edificação/baldio) e grava o veredito em `endereco_verificacao`. Idempotente e resumível:
cada execução pega só quem ainda não foi verificado (ou cujo cache expirou) e processa um LOTE limitado.

POR QUE em lotes diários (cron) e não um sweep único: Nominatim/Overpass públicos têm cota (≤1 req/s); um
lote educado por dia cobre toda a base ao longo do tempo sem flood nem risco de bloqueio do IP da VM. Respeita
o back-off (429/5xx) do módulo. HONESTO: 'logradouro existe mas nº não geolocalizado' = INDISPONÍVEL (não
baldio); cobertura do OSM é incompleta; indício ≠ acusação.

Uso: PYTHONPATH=. .venv/bin/python -m tools.backfill_verificacao_endereco [--limite N] [--ug UG] [--pausa S]
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from compliance_agent.verificacao_endereco import analisar_endereco, em_backoff

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"

_DDL = """CREATE TABLE IF NOT EXISTS endereco_verificacao (
  cnpj TEXT PRIMARY KEY, status TEXT, nivel TEXT, exato INTEGER,
  lat REAL, lon REAL, municipio_geo TEXT, evidencia TEXT, verificado_em TEXT)"""


def _gap(con: sqlite3.Connection, ug: str | None, limite: int) -> list[dict]:
    """Fornecedores com endereço ingerido e ainda SEM verificação geo (ou priorizando uma UG)."""
    base = ("SELECT ef.cnpj, ef.endereco, ef.municipio, ef.uf, ef.cep FROM endereco_fornecedor ef "
            "LEFT JOIN endereco_verificacao ev ON ev.cnpj=ef.cnpj "
            "WHERE ev.cnpj IS NULL AND ef.endereco IS NOT NULL AND ef.endereco!=''")
    params: list = []
    if ug:
        base += (" AND ef.cnpj IN (SELECT DISTINCT replace(replace(replace(favorecido_cpf,'.',''),'-',''),'/','') "
                 "FROM ordens_bancarias WHERE ug_codigo=?)")
        params.append(str(ug))
    if limite > 0:
        base += " LIMIT ?"
        params.append(limite)
    return [{"cnpj": r[0], "endereco": r[1], "municipio": r[2], "uf": r[3], "cep": r[4]}
            for r in con.execute(base, params).fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill incremental da verificação de endereço (geo/baldio)")
    ap.add_argument("--limite", type=int, default=400, help="máximo de fornecedores por execução (lote diário)")
    ap.add_argument("--ug", default="", help="priorizar fornecedores desta UG")
    ap.add_argument("--pausa", type=float, default=0.3, help="pausa extra entre alvos (s)")
    a = ap.parse_args()
    load_dotenv(str(_REPO / ".env"))

    con = sqlite3.connect(str(_DB))
    con.execute(_DDL)
    con.commit()
    alvos = _gap(con, a.ug or None, a.limite)
    ts = datetime.now().isoformat(timespec="seconds")
    print(f"[backfill_verif_end] {len(alvos)} fornecedor(es) a verificar (lote)"
          + (f" · UG {a.ug}" if a.ug else ""), flush=True)
    ok = ind = indisp = 0
    import time
    for i, f in enumerate(alvos, 1):
        espera = em_backoff()
        if espera > 0:
            print(f"  ⏸ back-off {espera:.0f}s (respeitando a fonte OSM)", flush=True)
            time.sleep(espera + 1)
        try:
            res = analisar_endereco(f["endereco"], f["municipio"], f["uf"], f["cep"], usar_overpass=True)
        except Exception as e:  # noqa: BLE001
            res = {"status": "INDISPONIVEL", "nivel": "—", "evidencia": f"erro: {str(e)[:60]}", "sinais": {}}
        g = (res.get("sinais") or {}).get("geocode") or {}
        con.execute("INSERT OR REPLACE INTO endereco_verificacao VALUES (?,?,?,?,?,?,?,?,?)",
                    (f["cnpj"], res["status"], res.get("nivel", "—"), 1 if g.get("exato") else 0,
                     g.get("lat"), g.get("lon"), g.get("municipio_geo", ""),
                     res.get("evidencia", "")[:500], ts))
        con.commit()
        if res["status"] == "INDICIO":
            ind += 1
        elif res["status"] == "INDISPONIVEL":
            indisp += 1
        else:
            ok += 1
        if i % 50 == 0:
            print(f"  {i}/{len(alvos)} | indício={ind} afastado={ok} indisp={indisp}", flush=True)
        time.sleep(a.pausa)
    con.close()
    print(f"[backfill_verif_end] FIM lote: {len(alvos)} verificados · {ind} com indício de endereço · "
          f"{ok} afastados · {indisp} indisponíveis", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
