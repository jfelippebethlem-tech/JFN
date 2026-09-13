# -*- coding: utf-8 -*-
"""Colhe pares *código verificador + CRC* de documentos do SEI da Prefeitura do Rio no D.O. Rio.

Por que: a pesquisa pública do ``prefeitura.sei.rio`` lista a árvore do processo mas NÃO abre
documento algum (nenhuma linha traz checkbox de "Gerar PDF" — medido em 12/09/2026 em 7
processos de compra). A única porta pública para a ÍNTEGRA é a *Conferência de Autenticidade*
(``controlador_externo.php?acao=documento_conferir``), que exige o par verificador+CRC do
rodapé do documento. O D.O. Rio publica esse par em despachos ("utilizando como número de
referência o código verificador N e o código CRC X") — e o Elasticsearch do doweb é aberto.

Saída: tabela ``sei_pcrj_crc_par`` em ``pcrj.db`` e o arquivo
``~/shared-brain/sei_pcrj_crc_pares.txt`` (Syncthing → VM-2, que baixa as íntegras com
``sei_pcrj_conferir.py`` e devolve ``sei_pcrj_documento`` no ``sei_pcrj.db``).

    python -m tools.pcrj_sei_crc_harvest --anos 2026 2025 --max-paginas 60
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from compliance_agent.pcrj import db as pcrj_db
from compliance_agent.pcrj import doweb

SAIDA = Path.home() / "shared-brain" / "sei_pcrj_crc_pares.txt"
TERMO = "código CRC"

_RE_PAR = re.compile(
    r"c[óo]digo\s+verificador\s*:?\s*(?:n[ºo°.]?\s*)?(\d{6,8})\s*(?:,|e)?\s*(?:o\s+)?c[óo]digo\s+CRC\s*:?\s*(?:n[ºo°.]?\s*)?([0-9A-F]{8})\b",
    re.I)
_RE_PROC = re.compile(r"\b(\d{6}\.\d{6}/20\d{2}-\d{2})\b")


def extrair_pares(texto: str, janela: int = 1500) -> list[dict]:
    """Pares (verificador, crc) do texto + o nº de processo SEI mais próximo ANTES do par
    (ou None) e um trecho de contexto. Um mesmo par aparece uma vez só."""
    vistos: set[tuple[str, str]] = set()
    saida = []
    for m in _RE_PAR.finditer(texto or ""):
        chave = (m.group(1), m.group(2).upper())
        if chave in vistos:
            continue
        vistos.add(chave)
        antes = texto[max(0, m.start() - janela):m.start()]
        procs = _RE_PROC.findall(antes)
        saida.append({"verificador": chave[0], "crc": chave[1],
                      "processo": procs[-1] if procs else None,
                      "contexto": re.sub(r"\s+", " ", texto[max(0, m.start() - 300):m.end()]).strip()})
    return saida


def _garantir(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS sei_pcrj_crc_par (
        verificador TEXT NOT NULL, crc TEXT NOT NULL, processo TEXT,
        data_doe TEXT, diario_id TEXT, pagina TEXT, contexto TEXT,
        coletado_em TEXT, PRIMARY KEY (verificador, crc))""")


def colher(anos: list[int], max_paginas: int = 60, db_path=None) -> dict:
    pcrj_db.inicializar(db_path)
    con = pcrj_db.conectar(db_path)
    _garantir(con)
    agora = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    novos = hits = 0
    try:
        for ano in anos:
            for pagina in range(1, max_paginas + 1):
                res = doweb.buscar(TERMO, pagina=pagina, anos=[ano])
                if not res["hits"]:
                    break
                for h in res["hits"]:
                    hits += 1
                    for p in extrair_pares(h["texto"]):
                        cur = con.execute(
                            "INSERT OR IGNORE INTO sei_pcrj_crc_par VALUES (?,?,?,?,?,?,?,?)",
                            (p["verificador"], p["crc"], p["processo"], h["data"],
                             h["diario_id"], str(h["pagina"] or ""), p["contexto"], agora))
                        novos += cur.rowcount
                con.commit()
        total = con.execute("SELECT count(*) FROM sei_pcrj_crc_par").fetchone()[0]
        exportados = exportar(con)
    finally:
        con.close()
    return {"anos": anos, "hits": hits, "novos": novos, "total": total, "exportados": exportados}


# Os PRÓPRIOS documentos baixados (CCON, conferência) trazem no rodapé o par de outros documentos (e o seu):
# 113 pares novos na primeira mineração (13/09). Cada par novo = mais um documento + assinantes.
CORPORA = (
    (Path.home() / "shared-brain" / "ccon.db", "ccon_anexo", "texto"),
    (Path.home() / "shared-brain" / "sei_pcrj.db", "sei_pcrj_documento", "texto"),
    (Path(__file__).resolve().parents[1] / "data" / "pcrj.db", "pcrj_processo_doc", "texto"),
)


def colher_dos_corpora(db_path=None, corpora=CORPORA) -> dict:
    """Minera pares verificador+CRC nos textos já capturados e grava em sei_pcrj_crc_par (origem=corpus)."""
    pcrj_db.inicializar(db_path)
    con = pcrj_db.conectar(db_path)
    _garantir(con)
    agora = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    novos = 0
    try:
        for db, tab, col in corpora:
            if not Path(db).exists():
                continue
            src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                if not src.execute("SELECT 1 FROM sqlite_master WHERE name=?", (tab,)).fetchone():
                    continue
                for (texto,) in src.execute(f"SELECT {col} FROM {tab} WHERE {col} IS NOT NULL"):
                    for p in extrair_pares(texto):
                        cur = con.execute(
                            "INSERT OR IGNORE INTO sei_pcrj_crc_par VALUES (?,?,?,?,?,?,?,?)",
                            (p["verificador"], p["crc"], p["processo"], None, f"corpus:{tab}", None, p["contexto"], agora))
                        novos += cur.rowcount
            except sqlite3.Error:
                continue
            finally:
                src.close()
        con.commit()
        total = con.execute("SELECT count(*) FROM sei_pcrj_crc_par").fetchone()[0]
        exportados = exportar(con)
    finally:
        con.close()
    return {"novos": novos, "total": total, "exportados": exportados}


def exportar(con: sqlite3.Connection, destino: Path | None = None) -> int:
    """Lista `verificador<TAB>crc<TAB>processo` para a VM-2 (Syncthing)."""
    destino = destino or SAIDA
    rows = con.execute(
        "SELECT verificador, crc, coalesce(processo,'') FROM sei_pcrj_crc_par ORDER BY data_doe DESC").fetchall()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("".join(f"{v}\t{c}\t{p}\n" for v, c, p in rows), encoding="utf-8")
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--anos", nargs="+", type=int, default=[2026, 2025])
    ap.add_argument("--max-paginas", type=int, default=60)
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    import json
    print(json.dumps(colher(a.anos, a.max_paginas, a.db), ensure_ascii=False))
    print(json.dumps(colher_dos_corpora(a.db), ensure_ascii=False))


if __name__ == "__main__":
    main()
