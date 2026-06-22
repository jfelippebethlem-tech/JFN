#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sei_depurar_db — DEPURA as fichas SEI do cache de arquivos para o banco.

O sweep SEI (`tools/sei_sweep.py`) lê cada processo e guarda em `data/sei_cache/<id>.json` SÓ a info
relevante: a **ficha** de auditoria (objeto/valores/partes/red_flags/analise/nivel_risco, via nous) + excertos
curtos dos documentos. Este depurador percorre esse cache e **carrega a ficha na tabela `sei_ficha`** do
`compliance.db` — assim o SEI fica QUERYÁVEL e cruzável com as OBs (antes vivia só em arquivo).

- **Só o relevante:** grava os campos da ficha + nº/contagem de docs; NÃO duplica o texto cru dos documentos.
- **Idempotente:** UPSERT por `numero_sei` (re-rodar atualiza, não duplica).
- **VM-safe:** `busy_timeout=30000`, uma transação em lote, sem concorrer com o write-lock dos sweeps.
- **Honesto:** processos bloqueados/sem ficha são contados à parte (não viram linha vazia).

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.sei_depurar_db            # depura tudo (backfill + incremental)
    PYTHONPATH=. .venv/bin/python -m tools.sei_depurar_db --stats    # só mostra o estado, não grava
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "data" / "sei_cache"
DB = REPO / "data" / "compliance.db"

_DDL = """
CREATE TABLE IF NOT EXISTS sei_ficha (
  numero_sei      TEXT PRIMARY KEY,
  objeto          TEXT,
  modalidade      TEXT,
  fundamento_legal TEXT,
  resumo          TEXT,
  analise         TEXT,
  nivel_risco     TEXT,
  situacao        TEXT,   -- situação processual AUTORITATIVA (arquivado/concluido/em andamento/'') — read-time
  relevante       INTEGER,
  valores         TEXT,   -- JSON array
  cnpjs           TEXT,   -- JSON array
  partes          TEXT,   -- JSON array
  datas           TEXT,   -- JSON array
  red_flags       TEXT,   -- JSON array
  documentos      TEXT,   -- JSON array [{tipo,ponto}]
  pericia_contabil TEXT,  -- JSON {achados[],verificar[],conclusao} — perícia contábil de triagem (sweep)
  pericia_juridica TEXT,  -- JSON {achados[],verificar[],conclusao} — perícia jurídica de triagem (sweep)
  n_docs          INTEGER,
  fonte_modelo    TEXT,
  cached_at       TEXT,
  atualizado_em   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_sei_ficha_risco ON sei_ficha(nivel_risco);
CREATE INDEX IF NOT EXISTS ix_sei_ficha_relevante ON sei_ficha(relevante);
"""

_CAMPOS = ("objeto", "modalidade", "fundamento_legal", "resumo", "analise", "nivel_risco", "situacao")
_LISTAS = ("valores", "cnpjs", "partes", "datas", "red_flags", "documentos")


def _conectar() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript(_DDL)
    # migração aditiva: garante a coluna nova em tabelas já existentes (idempotente)
    cols = {r[1] for r in con.execute("PRAGMA table_info(sei_ficha)")}
    if "situacao" not in cols:
        con.execute("ALTER TABLE sei_ficha ADD COLUMN situacao TEXT")
    for _c in ("pericia_contabil", "pericia_juridica"):
        if _c not in cols:
            con.execute(f"ALTER TABLE sei_ficha ADD COLUMN {_c} TEXT")
    return con


def _numero(rec: dict, ficha: dict, fname: str) -> str:
    """Nº SEI canônico: do registro, da ficha, ou derivado do nome do arquivo."""
    n = (rec.get("numero") or ficha.get("numero") or "").strip()
    if n:
        return n
    base = fname.replace("cdp_", "").replace(".json", "")
    return base.replace("SEI_", "SEI-").replace("_", "/") if base.startswith("SEI") else base


def depurar(stats_only: bool = False) -> dict:
    arquivos = [p for p in CACHE.glob("*.json")
                if "checkpoint" not in p.name and "progress" not in p.name]
    con = _conectar()
    cur = con.cursor()
    com_ficha = bloqueado = sem_ficha = gravados = 0
    for p in arquivos:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — arquivo corrompido/parcial: pula honesto
            continue
        if not isinstance(rec, dict):
            continue
        ficha = rec.get("ficha")
        if not isinstance(ficha, dict) or ficha.get("_erro"):
            # sem ficha real = processo bloqueado/restrito/vazio (não vira linha)
            if rec.get("diagnostico", {}).get("status", "").startswith("bloqueado"):
                bloqueado += 1
            else:
                sem_ficha += 1
            continue
        com_ficha += 1
        if stats_only:
            continue
        numero = _numero(rec, ficha, p.name)
        if not numero:
            continue
        def _scalar(v):  # o modelo às vezes devolve lista/dict onde se espera string → coage (SQLite não binda list/dict)
            if isinstance(v, list):
                return "; ".join(str(x) for x in v if x not in (None, ""))
            if isinstance(v, dict):
                return json.dumps(v, ensure_ascii=False)
            return v if v is not None else ""
        vals = {c: _scalar(ficha.get(c)) for c in _CAMPOS}
        listas = {c: json.dumps(ficha.get(c) or [], ensure_ascii=False) for c in _LISTAS}
        docs = ficha.get("documentos") or []
        # perícias = objetos {achados[],verificar[],conclusao}; persiste como JSON ("" se ausente)
        per_c = json.dumps(ficha.get("pericia_contabil"), ensure_ascii=False) if isinstance(ficha.get("pericia_contabil"), dict) else ""
        per_j = json.dumps(ficha.get("pericia_juridica"), ensure_ascii=False) if isinstance(ficha.get("pericia_juridica"), dict) else ""
        cur.execute(
            """INSERT INTO sei_ficha
               (numero_sei,objeto,modalidade,fundamento_legal,resumo,analise,nivel_risco,situacao,relevante,
                valores,cnpjs,partes,datas,red_flags,documentos,pericia_contabil,pericia_juridica,
                n_docs,fonte_modelo,cached_at,atualizado_em)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
               ON CONFLICT(numero_sei) DO UPDATE SET
                 objeto=excluded.objeto, modalidade=excluded.modalidade,
                 fundamento_legal=excluded.fundamento_legal, resumo=excluded.resumo,
                 analise=excluded.analise, nivel_risco=excluded.nivel_risco, situacao=excluded.situacao,
                 relevante=excluded.relevante,
                 valores=excluded.valores, cnpjs=excluded.cnpjs, partes=excluded.partes,
                 datas=excluded.datas, red_flags=excluded.red_flags, documentos=excluded.documentos,
                 pericia_contabil=excluded.pericia_contabil, pericia_juridica=excluded.pericia_juridica,
                 n_docs=excluded.n_docs, fonte_modelo=excluded.fonte_modelo,
                 cached_at=excluded.cached_at, atualizado_em=datetime('now')""",
            (numero, vals["objeto"], vals["modalidade"], vals["fundamento_legal"], vals["resumo"],
             vals["analise"], vals["nivel_risco"], vals["situacao"], 1 if ficha.get("relevante") else 0,
             listas["valores"], listas["cnpjs"], listas["partes"], listas["datas"],
             listas["red_flags"], listas["documentos"], per_c, per_j, len(docs),
             rec.get("_ficha_modelo") or "", rec.get("_cached_at") or ""))
        gravados += 1
    if not stats_only:
        con.commit()
    total_db = cur.execute("SELECT COUNT(*) FROM sei_ficha").fetchone()[0]
    con.close()
    return {"arquivos": len(arquivos), "com_ficha": com_ficha, "bloqueado": bloqueado,
            "sem_ficha": sem_ficha, "gravados": gravados, "total_no_db": total_db}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stats", action="store_true", help="só conta, não grava")
    a = ap.parse_args()
    r = depurar(stats_only=a.stats)
    print(f"[sei_depurar] arquivos={r['arquivos']} · com_ficha={r['com_ficha']} · "
          f"bloqueado={r['bloqueado']} · sem_ficha={r['sem_ficha']} · "
          f"gravados={r['gravados']} · TOTAL no sei_ficha={r['total_no_db']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
