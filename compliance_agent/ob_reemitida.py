# -*- coding: utf-8 -*-
"""ob_reemitida — OB "Enviado ao Banco" que o SIAFE REEMITIU e pagou: a primeira não é pagamento.

Decisão de 19/11/2026 (o dono delegou: "você que tem que decidir"). "Enviado ao Banco" segue contando como pago
(a OB está Contabilizada e saiu do Tesouro), EXCETO quando há, em até 10 dias depois, uma OB do MESMO credor, UG,
valor e processo já confirmada ('Processado e Pago' / 'Enviado Manualmente'): é a reemissão da mesma despesa e
somar as duas conta em dobro. Medido em 19/11/2026: 123 OB · R$ 19.653.969,33 com o mesmo processo (608 · R$ 67,44 mi sem exigir o processo) de 33.920 'Enviado ao Banco',
R$ 5,33 bi); ex.: UG 070100, 2021OB01446 R$ 17.461.575,28 em 29/12/2021 → 2021OB01486 em 30/12/2021, mesmo processo.

A tabela `ob_reemitida` (ob, ug) é lida por `cruzamentos_intel._ob_paga` (NOT EXISTS) — sem a tabela, regra antiga.
CLI: python -m compliance_agent.ob_reemitida  (recalcula; derivado `ob_reemitida` da propagação, depois da coleta)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
JANELA_DIAS = 10
_PAGA_CONFIRMADA = ("Processado e Pago", "Enviado Manualmente")


def _j(a: str) -> str:
    return (f"julianday(substr({a}.data_emissao,7,4)||'-'||substr({a}.data_emissao,4,2)||'-'||"
            f"substr({a}.data_emissao,1,2))")


def calcular(con: sqlite3.Connection, janela: int = JANELA_DIAS) -> list[tuple[str, str, float]]:
    """[(numero_ob, ug, valor)] das 'Enviado ao Banco' com reemissão paga no mesmo credor/UG/valor/processo."""
    con.execute("DROP TABLE IF EXISTS temp._env")
    con.execute(f"""CREATE TEMP TABLE _env AS SELECT numero_ob, ug_emitente, credor, valor, processo, {_j('a')} j
        FROM ob_orcamentaria_siafe a WHERE a.status='Contabilizado' AND a.status_envio='Enviado ao Banco'
        AND COALESCE(a.numero_ob,'')<>'' AND COALESCE(a.processo,'')<>'' AND a.valor>0""")
    con.execute("DROP TABLE IF EXISTS temp._pag")
    con.execute(f"""CREATE TEMP TABLE _pag AS SELECT numero_ob, ug_emitente, credor, valor, processo, {_j('b')} j
        FROM ob_orcamentaria_siafe b WHERE b.status='Contabilizado' AND b.status_envio IN (?,?)
        AND (b.credor, b.ug_emitente, b.valor) IN (SELECT credor, ug_emitente, valor FROM temp._env)""", _PAGA_CONFIRMADA)
    con.execute("CREATE INDEX temp._ipag ON _pag(credor, ug_emitente, valor)")
    return con.execute("""SELECT DISTINCT e.numero_ob, e.ug_emitente, e.valor FROM temp._env e WHERE EXISTS (
        SELECT 1 FROM temp._pag p WHERE p.credor=e.credor AND p.ug_emitente=e.ug_emitente AND p.valor=e.valor
        AND p.processo=e.processo AND p.numero_ob<>e.numero_ob AND p.j>e.j AND p.j-e.j<=?)""", (janela,)).fetchall()


def gravar(db: Path | None = None) -> dict:
    db = db or Path(os.environ.get("JFN_DATA_DIR") or RAIZ / "data") / "compliance.db"
    con = sqlite3.connect(str(db), timeout=120)
    try:
        linhas = calcular(con)
        with con:
            con.execute("CREATE TABLE IF NOT EXISTS ob_reemitida (ob TEXT NOT NULL, ug TEXT NOT NULL, valor REAL, "
                        "PRIMARY KEY (ob, ug)) WITHOUT ROWID")
            con.execute("DELETE FROM ob_reemitida")
            con.executemany("INSERT OR IGNORE INTO ob_reemitida VALUES (?,?,?)", linhas)
        return {"ok": True, "n": len(linhas), "valor": round(sum(v for _, _, v in linhas), 2)}
    finally:
        con.close()


if __name__ == "__main__":
    r = gravar(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    print(json.dumps(r, ensure_ascii=False))
    out = RAIZ / "data" / "ob_reemitida.json"
    out.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
