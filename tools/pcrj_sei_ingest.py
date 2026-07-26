# -*- coding: utf-8 -*-
"""Ingere as capturas do SEI-PCRJ (VM-2) no acervo do JFN.

A VM-2 varre o SEI da Prefeitura (prefeitura.sei.rio), captura os processos PÚBLICOS
(nº + Unidade + Data) e sincroniza o SQLite via Syncthing para
``~/shared-brain/sei_pcrj.db``. Este ingester fecha o wiring: lê esse banco e popula
``pcrj.db::pcrj_processo`` (tri-estado `disponivel`), tornando as capturas consultáveis
e cruzáveis com os atos do D.O. (``pcrj_doe_materia``). Idempotente (UPSERT por número).

    python -m tools.pcrj_sei_ingest            # ingere
    python -m tools.pcrj_sei_ingest --stats    # só mostra o que há para ingerir
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

from compliance_agent.pcrj import db as pcrj_db

ORIGEM = Path.home() / "shared-brain" / "sei_pcrj.db"
_RE_UNIDADE = re.compile(r"Unidade:\s*([^\s|]+)")
_RE_DATA = re.compile(r"Data:\s*(\d{2}/\d{2}/\d{4})")


def _parse(texto: str) -> tuple[str | None, str | None]:
    """texto 'nº<proc> Unidade: X Data: Y' → (orgao, data). None se ausente."""
    u = _RE_UNIDADE.search(texto or "")
    d = _RE_DATA.search(texto or "")
    return (u.group(1) if u else None), (d.group(1) if d else None)


def ingerir(origem: Path | None = None, db_path=None) -> dict:
    origem = Path(origem or ORIGEM)
    if not origem.exists():
        return {"erro": f"origem não encontrada: {origem} (VM-2 já sincronizou?)"}
    pcrj_db.inicializar(db_path)
    con = pcrj_db.conectar(db_path)
    src = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
    ingeridos = publicos = 0
    try:
        rows = src.execute(
            "SELECT numero, disponivel, texto, capturado_em FROM sei_pcrj_processo").fetchall()
        for numero, disp, texto, em in rows:
            orgao, data = _parse(texto or "")
            con.execute(
                "INSERT INTO pcrj_processo (numero_processo, sistema, interessado, assunto, "
                "orgao, andamento_json, disponivel, coletado_em) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(numero_processo) DO UPDATE SET disponivel=excluded.disponivel, "
                "orgao=COALESCE(excluded.orgao, pcrj_processo.orgao), "
                "assunto=COALESCE(excluded.assunto, pcrj_processo.assunto), "
                "coletado_em=excluded.coletado_em",
                (numero, "SEI.RIO", None, (f"Data {data}" if data else None),
                 orgao, None, disp, em))
            ingeridos += 1
            publicos += 1 if disp else 0
        con.commit()
    finally:
        src.close()
        con.close()
    return {"origem": str(origem), "ingeridos": ingeridos, "publicos": publicos}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    if a.stats:
        if not ORIGEM.exists():
            print(f"origem ausente: {ORIGEM}")
            return
        c = sqlite3.connect(f"file:{ORIGEM}?mode=ro", uri=True)
        n, pub = c.execute(
            "SELECT count(*), coalesce(sum(disponivel),0) FROM sei_pcrj_processo").fetchone()
        print(f"a ingerir: {n} processos ({pub} públicos) de {ORIGEM}")
        return
    import json
    print(json.dumps(ingerir(db_path=a.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
