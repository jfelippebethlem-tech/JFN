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
import os
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


def _gap(con: sqlite3.Connection, ug: str | None, limite: int, forcar: bool = False) -> list[dict]:
    """Fornecedores com endereço ingerido e ainda SEM verificação geo (ou priorizando uma UG).
    forcar=True (só faz sentido com --ug): inclui também os JÁ verificados, p/ re-rodar com a camada VISUAL."""
    cond_gap = "" if forcar else "ev.cnpj IS NULL AND "
    base = ("SELECT ef.cnpj, ef.endereco, ef.municipio, ef.uf, ef.cep FROM endereco_fornecedor ef "
            "LEFT JOIN endereco_verificacao ev ON ev.cnpj=ef.cnpj "
            f"WHERE {cond_gap}ef.endereco IS NOT NULL AND ef.endereco!=''")
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
    ap.add_argument("--forcar", action="store_true",
                    help="re-verifica os JÁ verificados (com --ug) — p/ rodar a camada VISUAL nova")
    a = ap.parse_args()
    load_dotenv(str(_REPO / ".env"))

    con = sqlite3.connect(str(_DB))
    con.execute(_DDL)
    con.commit()
    alvos = _gap(con, a.ug or None, a.limite, forcar=a.forcar)
    ts = datetime.now().isoformat(timespec="seconds")
    # VISUAL (foto de rua → casebre/baldio): gate honesto. ENDERECO_USAR_IMAGEM = auto|1|0.
    #   auto (default): liga SÓ se houver MAPILLARY_TOKEN (fonte GRÁTIS) — assim o sweep do universo não
    #   queima sozinho o teto pago do Street View. Com '1' força (usa SV de fallback, dentro do cap 9999/31d).
    _flag = os.environ.get("ENDERECO_USAR_IMAGEM", "auto").strip().lower()
    usar_imagem = (bool(os.environ.get("MAPILLARY_TOKEN", "").strip()) if _flag == "auto"
                   else _flag in ("1", "true", "sim", "yes", "on"))
    print(f"[backfill_verif_end] {len(alvos)} fornecedor(es) a verificar (lote)"
          + (f" · UG {a.ug}" if a.ug else "") + (" · VISUAL on" if usar_imagem else ""), flush=True)
    ok = ind = indisp = 0
    import time
    for i, f in enumerate(alvos, 1):
        espera = em_backoff()
        if espera > 0:
            print(f"  ⏸ back-off {espera:.0f}s (respeitando a fonte OSM)", flush=True)
            time.sleep(espera + 1)
        try:
            res = analisar_endereco(f["endereco"], f["municipio"], f["uf"], f["cep"],
                                    usar_overpass=True, usar_imagem=usar_imagem, forcar_update=a.forcar)
        except Exception as e:  # noqa: BLE001
            res = {"status": "INDISPONIVEL", "nivel": "—", "evidencia": f"erro: {str(e)[:60]}", "sinais": {}}
        g = (res.get("sinais") or {}).get("geocode") or {}
        vis = (res.get("sinais") or {}).get("imagem") or {}  # visual (casebre/baldio) quando usar_imagem
        # colunas NOMEADAS (a tabela tem 13 colunas desde a cont.15; o INSERT posicional de 9 quebrava em
        # TODA linha). visual_* preenchidos quando há análise de imagem; NULL caso contrário.
        con.execute("INSERT OR REPLACE INTO endereco_verificacao "
                    "(cnpj,status,nivel,exato,lat,lon,municipio_geo,evidencia,verificado_em,"
                    " visual_classe,visual_conf,visual_fonte,visual_em) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f["cnpj"], res["status"], res.get("nivel", "—"), 1 if g.get("exato") else 0,
                     g.get("lat"), g.get("lon"), g.get("municipio_geo", ""),
                     res.get("evidencia", "")[:500], ts,
                     vis.get("classe") or None, vis.get("confianca") if vis else None,
                     vis.get("fonte") or None, ts if vis.get("ok") else None))
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
