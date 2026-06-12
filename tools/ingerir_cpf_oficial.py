# -*- coding: utf-8 -*-
"""Ingestor de CPF de FONTE OFICIAL/ADMISSÍVEL (Receita/JUCERJA/TSE via requisição do Deputado, ou contrato
social do SEI). Recebe pares (nome, CPF), VALIDA o dígito verificador e — quando há a máscara do QSA — CONFIRMA
contra ela (anti-homônimo, `resolucao_cpf.confirmar_cpf`). Grava em `sei_cpf` (já é fonte do resolver), com a
`fonte` registrada. Pronto para o dado chegar; a resolução de sócios vai a ~100% e é juridicamente admissível.

Entrada: CSV com cabeçalho contendo colunas `nome` e `cpf` (e, opcional, `doc_mascarado` p/ confirmar 1:1).
Honesto: só grava CPF com DV válido; se vier `doc_mascarado`, só grava se confirmar (middle6 bate) — senão
descarta como possível homônimo. NUNCA de base de vazamento (prova ilícita) — só fonte oficial/pública.
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

from compliance_agent.resolucao_cpf import confirmar_cpf
from compliance_agent.sei.extrair_cpf import validar_cpf

_DB = Path("data") / "compliance.db"


def _norm(s: str) -> str:
    s = (s or "").upper().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)


def _digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def ingerir(pares, fonte: str, db_path: str | Path | None = None) -> dict:
    """pares: iterável de dicts {nome, cpf[, doc_mascarado]}. Grava os válidos/confirmados em sei_cpf.
    Retorna {recebidos, gravados, rejeitados_dv, rejeitados_homonimo}."""
    con = sqlite3.connect(Path(db_path or _DB))
    try:
        con.execute(
            """CREATE TABLE IF NOT EXISTS sei_cpf (cpf TEXT NOT NULL, nome TEXT, nome_norm TEXT, middle6 TEXT,
               numero_sei TEXT, contexto TEXT, extraido_em TEXT, PRIMARY KEY (cpf, numero_sei))""")
        rec = grav = rej_dv = rej_homo = 0
        for p in pares:
            rec += 1
            nome = (p.get("nome") or "").strip()
            cpf = _digitos(p.get("cpf"))
            doc = (p.get("doc_mascarado") or "").strip()
            if not validar_cpf(cpf):
                rej_dv += 1
                continue
            if doc:  # confirma 1:1 contra a máscara do QSA (anti-homônimo)
                conf = confirmar_cpf(nome, cpf, doc)
                if not conf["confirmado"]:
                    rej_homo += 1
                    continue
            cur = con.execute(
                "INSERT OR IGNORE INTO sei_cpf (cpf,nome,nome_norm,middle6,numero_sei,contexto,extraido_em) "
                "VALUES (?,?,?,?,?,?,?)",
                (cpf, nome, _norm(nome), cpf[3:9], f"OFICIAL:{fonte}", "ingestão oficial (requisição/admissível)",
                 datetime.now().isoformat(timespec="seconds")))
            grav += cur.rowcount or 0
        con.commit()
        total = con.execute("SELECT COUNT(DISTINCT cpf) FROM sei_cpf").fetchone()[0]
        return {"recebidos": rec, "gravados": grav, "rejeitados_dv": rej_dv,
                "rejeitados_homonimo": rej_homo, "total_sei_cpf_distintos": total}
    finally:
        con.close()


def ingerir_csv(caminho: str, fonte: str, db_path: str | Path | None = None) -> dict:
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    # normaliza nomes de coluna (nome/cpf/doc_mascarado em qualquer caixa)
    def g(r, *ks):
        for k in r:
            if k and k.strip().lower() in ks:
                return r[k]
        return ""
    pares = [{"nome": g(r, "nome", "nome_socio", "socio"), "cpf": g(r, "cpf", "cpf_socio"),
              "doc_mascarado": g(r, "doc_mascarado", "cpf_mascarado", "socio_doc")} for r in rows]
    return ingerir(pares, fonte=fonte, db_path=db_path)


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingere CPF de fonte OFICIAL (requisição) → resolver (admissível)")
    ap.add_argument("csv", help="CSV com colunas nome,cpf[,doc_mascarado]")
    ap.add_argument("--fonte", required=True, help="rótulo da fonte oficial (ex.: receita-ric-2026, jucerja-of-123)")
    a = ap.parse_args()
    r = ingerir_csv(a.csv, fonte=a.fonte)
    print(f"[ingerir_cpf_oficial] recebidos={r['recebidos']} gravados={r['gravados']} "
          f"rej_DV={r['rejeitados_dv']} rej_homônimo={r['rejeitados_homonimo']} | sei_cpf distintos={r['total_sei_cpf_distintos']}")


if __name__ == "__main__":
    main()
