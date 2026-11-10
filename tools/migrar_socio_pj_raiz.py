#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""migrar_socio_pj_raiz — leva o sócio PJ das linhas antigas (14 dígitos) para a raiz de 8 dígitos.

POR QUÊ. A Receita passou a publicar o documento do sócio PJ só com a raiz (8 dígitos) no leiaute de
2026-10; até 2026-07 vinha o CNPJ íntegro (14). A ENTRADA já normaliza
(`historico_societario.normalizar_doc_socio`); este script põe o legado no mesmo formato, senão o
primeiro mês novo ingerido faria cada sócio PJ "sair" (14) e "entrar" (8) — falsa troca de controle.

O QUE FAZ, nesta ordem:
  1. exporta TODAS as linhas afetadas (PJ com 14 dígitos) das cinco tabelas para
     `data/backup_socio_pj_14dig_<data>.csv.gz` (tabela, rowid, linha em JSON) — reversível;
  2. converte `socio_snapshot`, `socios_receita`, `socios_reverso` em lotes curtos
     (`UPDATE OR IGNORE`; a linha de 14 que colidiria com uma de 8 já existente é APAGADA);
  3. recalcula `socio_historico` pelo caminho normal (`diff_snapshots`) e `rede_socios_fornecedores`
     pelo `materializar_rede` — as duas são derivadas;
  4. confere: nenhum PJ de 14 dígitos sobra, e os vínculos distintos por mês não mudam.
Idempotente: rodar de novo encontra zero linhas e não altera nada.

O `compliance.db` é compartilhado com sweeps e painel: lotes de 5.000 com commit, espera com recuo
quando a base está ocupada. Rodar de madrugada.

Uso:
  PYTHONPATH=. .venv/bin/python -m tools.migrar_socio_pj_raiz --dry-run   # só conta
  PYTHONPATH=. .venv/bin/python -m tools.migrar_socio_pj_raiz             # migra de verdade
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import sqlite3
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from compliance_agent.osint.historico_societario import _com_espera, diff_snapshots  # noqa: E402

_DB = _REPO / "data" / "compliance.db"
_LOTE = 5000

# documento PJ legado: 14 caracteres, todos dígitos (PF vem mascarado com '*', estrangeiro vazio)
_PJ14 = "length(doc_socio)=14 AND doc_socio NOT GLOB '*[^0-9]*'"
# tabela -> predicado; onde há `ident`, exige também identificador 1
_ALVO = {
    "socio_snapshot": f"ident='1' AND {_PJ14}",
    "socios_receita": f"ident='1' AND {_PJ14}",
    "socios_reverso": _PJ14,
    "socio_historico": _PJ14,            # derivada: recalculada por diff_snapshots
    "rede_socios_fornecedores": _PJ14,   # derivada: recalculada por materializar_rede
}
_CONVERTER = ("socio_snapshot", "socios_receita", "socios_reverso")
_DOC_NORM = f"CASE WHEN {_PJ14} THEN substr(doc_socio,1,8) ELSE doc_socio END"


def _existe(con: sqlite3.Connection, t: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone() is not None


def contar(con: sqlite3.Connection) -> dict[str, int]:
    """Linhas de sócio PJ com documento de 14 dígitos, por tabela (ausente → omitida)."""
    return {t: con.execute(f"SELECT COUNT(*) FROM {t} WHERE {p}").fetchone()[0]
            for t, p in _ALVO.items() if _existe(con, t)}


def vinculos_por_mes(con: sqlite3.Connection) -> dict:
    """Vínculos distintos (raiz, doc normalizado, nome) — por mês na série, total nas fotos.

    É o invariante da migração: trocar 14 por 8 dígitos não pode criar nem sumir vínculo.
    """
    out: dict = {}
    if _existe(con, "socio_snapshot"):
        out["socio_snapshot"] = dict(con.execute(
            f"SELECT fonte_mes, COUNT(DISTINCT cnpj_basico||'|'||{_DOC_NORM}||'|'||nome_norm) "
            "FROM socio_snapshot GROUP BY fonte_mes").fetchall())
    for t in ("socios_receita", "socios_reverso", "socio_historico"):
        if _existe(con, t):
            out[t] = con.execute(
                f"SELECT COUNT(DISTINCT cnpj_basico||'|'||{_DOC_NORM}||'|'||nome_norm) FROM {t}"
            ).fetchone()[0]
    return out


def exportar(con: sqlite3.Connection, destino: Path) -> dict[str, int]:
    """Backup das linhas afetadas de cada tabela: (tabela, rowid, linha JSON), gzip."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    n: dict[str, int] = {}
    with gzip.open(destino, "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tabela", "rowid", "linha_json"])
        for t, p in _ALVO.items():
            if not _existe(con, t):
                continue
            cur = con.execute(f"SELECT rowid, * FROM {t} WHERE {p}")
            cols = [d[0] for d in cur.description][1:]
            n[t] = 0
            for row in cur:
                w.writerow([t, row[0], json.dumps(dict(zip(cols, row[1:])), ensure_ascii=False)])
                n[t] += 1
    return n


def _converter_tabela(con: sqlite3.Connection, t: str) -> dict[str, int]:
    rowids = [r[0] for r in con.execute(f"SELECT rowid FROM {t} WHERE {_ALVO[t]}")]
    upd = apag = 0
    for i in range(0, len(rowids), _LOTE):
        lote = rowids[i:i + _LOTE]
        marc = ",".join("?" * len(lote))

        def _um_lote():
            try:
                a = con.execute(f"UPDATE OR IGNORE {t} SET doc_socio=substr(doc_socio,1,8) "
                                f"WHERE rowid IN ({marc}) AND {_ALVO[t]}", lote).rowcount
                # o que sobrou com 14 colidiu com uma linha de 8 já existente: é duplicata
                b = con.execute(f"DELETE FROM {t} WHERE rowid IN ({marc}) AND {_ALVO[t]}",
                                lote).rowcount
                con.commit()
                return a, b
            except Exception:
                con.rollback()
                raise
        a, b = _com_espera(_um_lote, rotulo=f"migração {t}")
        upd += a
        apag += b
    return {"atualizadas": upd, "apagadas_colisao": apag}


def migrar(con: sqlite3.Connection, backup: Path) -> dict:
    """Backup → conversão em lotes → derivadas recalculadas. Devolve contagens por tabela."""
    out: dict = {"backup": str(backup), "exportadas": exportar(con, backup)}
    for t in _CONVERTER:
        if _existe(con, t):
            out[t] = _converter_tabela(con, t)
            print(f"[migrar] {t}: {out[t]}", flush=True)
    if _existe(con, "socio_snapshot"):
        r = diff_snapshots(con)
        out["socio_historico"] = {k: r.get(k) for k in ("n_vinculos", "n_ativos", "n_sairam")}
        print(f"[migrar] socio_historico recalculado: {out['socio_historico']}", flush=True)
    if _existe(con, "socios_receita") and _existe(con, "ordens_bancarias"):
        from tools.socios_dump_sweep import materializar_rede
        materializar_rede(con)
        out["rede_socios_fornecedores"] = "rematerializada"
    return out


def _conectar() -> sqlite3.Connection:
    con = sqlite3.connect(str(_DB), timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    return con


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="só conta; não escreve nada")
    a = ap.parse_args(argv)
    con = _conectar()
    try:
        antes = contar(con)
        print(f"[migrar] PJ com 14 dígitos: {antes}", flush=True)
        vinc_antes = vinculos_por_mes(con)
        print(f"[migrar] vínculos distintos (normalizados) ANTES: {vinc_antes}", flush=True)
        if a.dry_run:
            return 0
        if not any(antes.values()):
            print("[migrar] nada a migrar (idempotente)", flush=True)
            return 0
        bkp = _REPO / "data" / f"backup_socio_pj_14dig_{dt.date.today().isoformat()}.csv.gz"
        r = migrar(con, bkp)
        print(f"[migrar] resultado: {r}", flush=True)
        depois = contar(con)
        vinc_depois = vinculos_por_mes(con)
        print(f"[migrar] PJ com 14 dígitos DEPOIS: {depois}", flush=True)
        print(f"[migrar] vínculos distintos DEPOIS: {vinc_depois}", flush=True)
        ok = not any(depois.values()) and vinc_depois == vinc_antes
        print(f"[migrar] CONFERENCIA={'OK' if ok else 'FALHOU'}", flush=True)
        return 0 if ok else 1
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
