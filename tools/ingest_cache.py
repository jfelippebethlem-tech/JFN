# -*- coding: utf-8 -*-
"""
JFN — ingestão dos caches JSON (data/sei_cache) para o SQLite (data/compliance.db).

Por que existe: o painel lê do banco, mas os dados reais estavam presos em JSON no filesystem
(empresa MGS, 41 contratos SIAFE R$146M, empenhos agregados). Este script popula o banco de forma
idempotente para o painel/relatórios refletirem o que já foi coletado.

HONESTIDADE DE PROVENIÊNCIA: empenhos são valor BRUTO (podem ser cancelados); contratos vêm do
SIAFE; **Ordens Bancárias (OBs) nominais NÃO estão nos caches** — dependem da coleta no SIAFE-Rio 2
(ver SIAFE_AGENT_LOG.md). Portanto a tabela ordens_bancarias permanece vazia até a coleta real.

Uso: python -m tools.ingest_cache
"""
import glob
import json
import os
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("JFN_DATA_DIR", REPO / "data")) / "compliance.db"
CACHE = Path(os.environ.get("JFN_DATA_DIR", REPO / "data")) / "sei_cache"


def _con():
    return sqlite3.connect(str(DB))


def ingest_empresa(con, cons):
    cnpj = (cons.get("cnpj") or "").strip()
    razao = cons.get("razao_social") or ""
    if not cnpj:
        return None
    cur = con.execute("SELECT id FROM empresas WHERE cnpj=?", (cnpj,))
    row = cur.fetchone()
    if row:
        con.execute("UPDATE empresas SET razao_social=?, raw_json=? WHERE id=?",
                    (razao, json.dumps(cons.get("resumo", {}), ensure_ascii=False), row[0]))
        return row[0]
    cur = con.execute(
        "INSERT INTO empresas(cnpj, razao_social, raw_json) VALUES(?,?,?)",
        (cnpj, razao, json.dumps(cons.get("resumo", {}), ensure_ascii=False)))
    return cur.lastrowid


def ingest_contratos(con, empresa_id, contratos_doc):
    rows = contratos_doc.get("contratos", []) if isinstance(contratos_doc, dict) else contratos_doc
    n = 0
    for c in rows:
        numero = str(c.get("numero", "")).strip()
        if not numero:
            continue
        exists = con.execute("SELECT id FROM contratos WHERE numero=? AND empresa_id=?",
                             (numero, empresa_id)).fetchone()
        objeto = f"Aditivos: {c.get('aditivos', 0)} | início {c.get('inicio_estimado','?')}"
        vals = (objeto, empresa_id, c.get("orgao", ""), c.get("valor"), c.get("valor"),
                c.get("situacao", ""), "SIAFE")
        if exists:
            con.execute("""UPDATE contratos SET objeto=?, empresa_id=?, orgao_contrat=?,
                           valor_estimado=?, valor_total=?, status=?, fonte=? WHERE id=?""",
                        (*vals, exists[0]))
        else:
            con.execute("""INSERT INTO contratos(numero, objeto, empresa_id, orgao_contrat,
                           valor_estimado, valor_total, status, fonte) VALUES(?,?,?,?,?,?,?,?)""",
                        (numero, *vals))
        n += 1
    return n


def main():
    if not DB.exists():
        print(f"banco não existe: {DB} — rode init_db primeiro"); return 1
    con = _con()
    total_emp = total_ct = 0
    try:
        for cons_fp in glob.glob(str(CACHE / "*_consolidado.json")):
            cons = json.load(open(cons_fp, encoding="utf-8"))
            eid = ingest_empresa(con, cons)
            if eid is None:
                continue
            total_emp += 1
            # contratos: arquivo dedicado *_contratos_siafe.json com mesmo CNPJ, senão os do consolidado
            ct_files = glob.glob(str(CACHE / "*contratos_siafe.json"))
            ingested = False
            for ctf in ct_files:
                doc = json.load(open(ctf, encoding="utf-8"))
                if (doc.get("cnpj") or "").strip() == cons.get("cnpj"):
                    total_ct += ingest_contratos(con, eid, doc); ingested = True
            if not ingested and cons.get("contratos"):
                total_ct += ingest_contratos(con, eid, {"contratos": cons["contratos"]})
        con.commit()
    finally:
        # contagens finais
        emp = con.execute("SELECT COUNT(*) FROM empresas").fetchone()[0]
        ct = con.execute("SELECT COUNT(*), COALESCE(SUM(valor_total),0) FROM contratos").fetchone()
        ob = con.execute("SELECT COUNT(*) FROM ordens_bancarias").fetchone()[0]
        con.close()
    print("Ingestão concluída:")
    print(f"  empresas: {emp} (novas/atualizadas nesta rodada: {total_emp})")
    print(f"  contratos: {ct[0]} | valor total: R$ {ct[1]:,.2f} (ingeridos: {total_ct})")
    print(f"  ordens_bancarias: {ob}  <- vazio é esperado; OBs nominais dependem da coleta no SIAFE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
