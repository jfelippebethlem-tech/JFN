# -*- coding: utf-8 -*-
"""Ingere a Relação de Contratos do ContasRio e os anexos do CCON (capturados na VM-2).

Por que: o ContasRio (Vaadin, CGM) lista TODOS os contratos municipais 2017→hoje com o nº do
processo (SEI ou Processo.rio), a forma de contratação, o empenhado/liquidado/PAGO e o link
"Anexos (Inteiro Teor)" → CCON, que serve o contrato assinado, TR/projeto básico, ofício
"autorizo" e despachos do SEI. É a porta de CONTEÚDO dos processos de compra da Prefeitura
que a pesquisa pública do SEI não abre (12/09/2026).

Origem (Syncthing): ``~/shared-brain/contasrio/contratos_<ano>.csv`` e ``~/shared-brain/ccon.db``.
Destino: ``pcrj.db::contasrio_contrato`` e ``pcrj.db::pcrj_processo_doc`` (tipo ``ccon_<tipo>``,
seq = id do anexo, numero_processo = "Processo do Instrumento").

    python -m tools.contasrio_ingest            # ingere os dois
    python -m tools.contasrio_ingest --stats
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import unicodedata
from pathlib import Path

from compliance_agent.pcrj import db as pcrj_db

CSV_DIR = Path.home() / "shared-brain" / "contasrio"
CCON_DB = Path.home() / "shared-brain" / "ccon.db"
_RX_CONTRATO = re.compile(r"ccon-web/\?contrato=(\d+)")
_RX_CNPJ = re.compile(r"^\s*(\d{11,14})\s*-\s*(.*?)\s*$")
_URL_CCON = "https://siafic-apps-externas.rio.rj.gov.br/ccon-web/?contrato={c}"

COLS = ["favorecido", "orgao", "ug", "tipo_instrumento", "ano", "numero_instrumento", "data_publicacao",
        "objeto", "situacao", "vigencia_ini", "vigencia_fim", "processo", "forma_contratacao", "anexos_html",
        "valor_atualizado", "total_empenhado", "saldo_executar", "total_liquidado", "total_pago"]

DDL = """CREATE TABLE IF NOT EXISTS contasrio_contrato (
    contrato TEXT PRIMARY KEY, favorecido_doc TEXT, favorecido_nome TEXT, orgao TEXT, ug TEXT,
    tipo_instrumento TEXT, ano INTEGER, numero_instrumento TEXT, data_publicacao TEXT, objeto TEXT,
    situacao TEXT, vigencia_ini TEXT, vigencia_fim TEXT, processo TEXT, forma_contratacao TEXT,
    valor_atualizado REAL, total_empenhado REAL, saldo_executar REAL, total_liquidado REAL, total_pago REAL,
    url_ccon TEXT, coletado_em TEXT);
CREATE INDEX IF NOT EXISTS ix_contasrio_contrato_proc ON contasrio_contrato(processo);
CREATE INDEX IF NOT EXISTS ix_contasrio_contrato_fav ON contasrio_contrato(favorecido_doc);"""


def slug_tipo(tipo: str | None) -> str:
    """'TERMO DE REFERÊNCIA' → 'ccon_termo_de_referencia' (ASCII, estável para filtros)."""
    t = unicodedata.normalize("NFKD", (tipo or "anexo").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return "ccon_" + re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def brl(s: str | None) -> float | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def parse_linha(r: list[str]) -> dict | None:
    """Uma linha do CSV (latin-1, ';') → dict pronto para a tabela; None para TOTAL/curta."""
    if len(r) < 19 or r[0].strip() == "TOTAL":
        return None
    d = dict(zip(COLS, (x.strip() for x in r[:19])))
    # o id do CCON é o próprio "Número do Instrumento"; contratos antigos só têm o link do SIGA (sem CCON)
    m = _RX_CONTRATO.search(d["anexos_html"])
    d["contrato"] = m.group(1) if m else d["numero_instrumento"]
    if not d["contrato"]:
        return None
    mf = _RX_CNPJ.match(d["favorecido"])
    d["favorecido_doc"] = mf.group(1) if mf else None
    d["favorecido_nome"] = mf.group(2) if mf else d["favorecido"]
    d["ano"] = int(d["ano"]) if d["ano"].isdigit() else None
    for k in ("valor_atualizado", "total_empenhado", "saldo_executar", "total_liquidado", "total_pago"):
        d[k] = brl(d[k])
    d["url_ccon"] = _URL_CCON.format(c=d["contrato"]) if m else None
    return d


def ingerir_contratos(csv_dir: Path | None = None, db_path=None) -> dict:
    csv_dir = Path(csv_dir or CSV_DIR)
    arqs = sorted(csv_dir.glob("contratos_*.csv"))
    if not arqs:
        return {"erro": f"nenhum CSV em {csv_dir} (VM-2 exportou?)"}
    pcrj_db.inicializar(db_path)
    con = pcrj_db.conectar(db_path)
    con.executescript(DDL)
    n = 0
    try:
        for arq in arqs:
            with open(arq, encoding="latin-1", newline="") as f:
                rows = list(csv.reader(f, delimiter=";"))
            for r in rows[1:]:
                d = parse_linha(r)
                if not d:
                    continue
                con.execute(
                    "INSERT OR REPLACE INTO contasrio_contrato (contrato, favorecido_doc, favorecido_nome, orgao, ug, "
                    "tipo_instrumento, ano, numero_instrumento, data_publicacao, objeto, situacao, vigencia_ini, "
                    "vigencia_fim, processo, forma_contratacao, valor_atualizado, total_empenhado, saldo_executar, "
                    "total_liquidado, total_pago, url_ccon, coletado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                    "datetime('now','localtime'))",
                    tuple(d[k] for k in ("contrato", "favorecido_doc", "favorecido_nome", "orgao", "ug", "tipo_instrumento",
                                         "ano", "numero_instrumento", "data_publicacao", "objeto", "situacao", "vigencia_ini",
                                         "vigencia_fim", "processo", "forma_contratacao", "valor_atualizado", "total_empenhado",
                                         "saldo_executar", "total_liquidado", "total_pago", "url_ccon")))
                n += 1
        con.commit()
        total = con.execute("SELECT count(*) FROM contasrio_contrato").fetchone()[0]
    finally:
        con.close()
    return {"arquivos": len(arqs), "linhas": n, "total": total}


def ingerir_anexos(origem: Path | None = None, db_path=None) -> dict:
    """``ccon.db::ccon_anexo`` → ``pcrj_processo_doc`` ligado ao processo do contrato."""
    origem = Path(origem or CCON_DB)
    if not origem.exists():
        return {"documentos": 0, "motivo": f"{origem} ainda não chegou da VM-2"}
    src = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
    try:
        rows = src.execute("SELECT contrato, anexo_id, tipo, descricao, arquivo, texto, capturado_em FROM ccon_anexo "
                           "WHERE texto IS NOT NULL AND length(texto) > 0").fetchall()
    finally:
        src.close()
    pcrj_db.inicializar(db_path)
    con = pcrj_db.conectar(db_path)
    con.executescript(DDL)
    n = sem_processo = 0
    try:
        procs = dict(con.execute("SELECT contrato, processo FROM contasrio_contrato"))
        for contrato, aid, tipo, desc, arq, texto, em in rows:
            numero = (procs.get(contrato) or "").strip() or f"CCON-{contrato}"
            sem_processo += numero.startswith("CCON-")
            con.execute(
                "INSERT INTO pcrj_processo_doc (numero_processo, seq, tipo, titulo, texto, url, coletado_em) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(numero_processo, seq) DO UPDATE SET texto=excluded.texto, "
                "titulo=excluded.titulo, coletado_em=excluded.coletado_em",
                (numero, int(aid), slug_tipo(tipo),
                 f"{desc or ''} · {arq or ''} · contrato {contrato}"[:400], texto, _URL_CCON.format(c=contrato), em))
            n += 1
        con.commit()
    finally:
        con.close()
    return {"documentos": n, "sem_processo": sem_processo}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    import json
    if a.stats:
        print("CSVs:", [p.name for p in sorted(CSV_DIR.glob("contratos_*.csv"))], "| ccon.db:", CCON_DB.exists())
        return
    print(json.dumps(ingerir_contratos(db_path=a.db), ensure_ascii=False))
    print(json.dumps(ingerir_anexos(db_path=a.db), ensure_ascii=False))


if __name__ == "__main__":
    main()
