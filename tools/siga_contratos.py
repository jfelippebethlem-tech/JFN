#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""siga_contratos — contratos do Estado no Portal SIGA (compras.rj.gov.br), por CNPJ, sem API.

Descoberto em 12/09/2026: a busca pública de contratos do SIGA é um DataTables que faz POST em
`/Portal-Siga/Contrato/paginate.action` com `cnpjFornecedor` formatado; cada linha traz nº da contratação,
data, processo SEI, órgão, valor, modalidade (ex.: "Dispensa - Especial" = emergência) e os GESTORES/fiscais
do contrato (nomes!); `detalhar.action?idContrato=` dá objeto (com a unidade), situação, fundamento legal e
valores empenhado/liquidado/pago (empenho ≠ pago — só a OB do SIAFE é pago).

O que rende: (1) contratos de TODOS os órgãos do Estado por fornecedor (o registro do TCE-RJ cobre menos);
(2) quem é o gestor/fiscal de cada contrato — cruzável com QSA e folha; (3) emergência por órgão.

Uso: PYTHONPATH=. .venv/bin/python -m tools.siga_contratos [--cnpj 10190061000112 ...] [--tac] [--detalhar]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

_REPO = Path(__file__).resolve().parents[1]
DB = _REPO / "data" / "compliance.db"
BASE = "https://www.compras.rj.gov.br/Portal-Siga"
UA = {"User-Agent": "Mozilla/5.0 (JFN fiscalizacao)"}


def fmt_cnpj(d: str) -> str:
    d = re.sub(r"\D", "", d or "")
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}" if len(d) == 14 else d


def _valor(s: str) -> float | None:
    m = re.search(r"([\d.]+,\d{2})", s or "")
    return float(m.group(1).replace(".", "").replace(",", ".")) if m else None


def parse_linha(row: list, cnpj: str) -> dict:
    """Linha do paginate: [contratacao, data, processo, orgao, valor, ?, modalidade, gestores(<br/>), ?, ?, idContrato, ?]."""
    r = [x if x is not None else "" for x in row] + [""] * 12
    gestores = [g.strip() for g in re.split(r"<br\s*/?>", str(r[7])) if g.strip()]
    return {"id_contrato": str(r[10]).strip(), "cnpj": re.sub(r"\D", "", cnpj), "contratacao": str(r[0]).strip(),
            "data": str(r[1]).strip(), "processo": str(r[2]).strip() or None, "orgao": str(r[3]).strip(),
            "valor": _valor(str(r[4])), "modalidade": str(r[6]).strip(), "gestores": " | ".join(gestores)}


def listar(cnpj: str, client: httpx.Client, por_pagina: int = 100, max_paginas: int = 10) -> list[dict]:
    out, start = [], 0
    for _ in range(max_paginas):
        r = client.post(f"{BASE}/Contrato/paginate.action",
                        data={"draw": 1, "start": start, "length": por_pagina, "orderColumn": 0, "orderDirection": "asc",
                              "cnpjFornecedor": fmt_cnpj(cnpj)}, timeout=90)
        if r.status_code != 200:
            break
        d = r.json()
        rows = d.get("data") or []
        out.extend(parse_linha(x, cnpj) for x in rows if isinstance(x, list))
        start += por_pagina
        if start >= int(d.get("recordsFiltered") or 0) or not rows:
            break
        time.sleep(0.5)
    return out


def parse_detalhe(html: str) -> dict:
    from bs4 import BeautifulSoup
    txt = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    rotulos = ("Unidade:", "Fornecedor:", "CPF/CNPJ:", "Situação da Contratação:", "Tipo de Aquisição:", "Contratação:",
               "Data de Vigência da Contratação:", "Data de publicação D.O:", "Valor Total Original da Contratação:",
               "Valor Total Corrente da Contratação:", "Valor Total Recebido da Contratação:", "Valor Total Empenhado:",
               "Valor Total Liquidado:", "Valor Total Pago:", "Licitação:", "Processo(s):", "Fundamento Legal:",
               "Objeto da Contratação:", "Gestor(es) da Contratação:", "Arquivos Anexos:", "Item ")
    fim = r"(?=\s*(?:" + "|".join(re.escape(r) for r in rotulos) + r")|$)"

    def campo(rotulo):
        m = re.search(re.escape(rotulo) + r"\s*(.+?)" + fim, txt)
        return m.group(1).strip() if m else None
    return {"objeto": campo("Objeto da Contratação:"), "situacao": campo("Situação da Contratação:"),
            "tipo": campo("Tipo de Aquisição:"), "fundamento": campo("Fundamento Legal:"),
            "vigencia": campo("Data de Vigência da Contratação:"),
            "valor_empenhado": _valor(campo("Valor Total Empenhado:") or ""),
            "valor_pago_siga": _valor(campo("Valor Total Pago:") or "")}


def materializar(cnpjs: list[str], detalhar: bool = False) -> dict:
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    con.execute("CREATE TABLE IF NOT EXISTS siga_contratos (id_contrato TEXT PRIMARY KEY, cnpj TEXT, contratacao TEXT, data TEXT, "
                "processo TEXT, orgao TEXT, valor REAL, modalidade TEXT, gestores TEXT, objeto TEXT, situacao TEXT, tipo TEXT, "
                "fundamento TEXT, vigencia TEXT, valor_empenhado REAL, valor_pago_siga REAL, visto_em TEXT)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_siga_cnpj ON siga_contratos(cnpj)")
    con.commit()
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n_linhas = n_det = 0
    with httpx.Client(headers=UA, follow_redirects=True) as client:
        for cnpj in cnpjs:
            try:
                linhas = listar(cnpj, client)
            except (httpx.HTTPError, ValueError) as exc:
                print(f"[siga] {cnpj}: {exc}", flush=True)
                continue
            with con:
                for l in linhas:
                    con.execute("INSERT INTO siga_contratos (id_contrato,cnpj,contratacao,data,processo,orgao,valor,modalidade,gestores,visto_em) "
                                "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id_contrato) DO UPDATE SET gestores=excluded.gestores, visto_em=excluded.visto_em",
                                (l["id_contrato"], l["cnpj"], l["contratacao"], l["data"], l["processo"], l["orgao"], l["valor"], l["modalidade"], l["gestores"], agora))
            n_linhas += len(linhas)
            if detalhar:
                pend = [r[0] for r in con.execute("SELECT id_contrato FROM siga_contratos WHERE cnpj=? AND objeto IS NULL", (re.sub(r"\D", "", cnpj),))]
                for idc in pend:
                    try:
                        h = client.get(f"{BASE}/Contrato/detalhar.action", params={"idContrato": idc}, timeout=90).text
                        d = parse_detalhe(h)
                    except (httpx.HTTPError, ValueError) as exc:
                        print(f"[siga] detalhe {idc}: {exc}", flush=True)
                        continue
                    with con:
                        con.execute("UPDATE siga_contratos SET objeto=?, situacao=?, tipo=?, fundamento=?, vigencia=?, valor_empenhado=?, valor_pago_siga=? WHERE id_contrato=?",
                                    (d["objeto"], d["situacao"], d["tipo"], d["fundamento"], d["vigencia"], d["valor_empenhado"], d["valor_pago_siga"], idc))
                    n_det += 1
                    time.sleep(0.4)
            time.sleep(0.5)
    con.close()
    return {"cnpjs": len(cnpjs), "contratos": n_linhas, "detalhados": n_det}


def cnpjs_tac() -> list[str]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute("SELECT DISTINCT cnpj FROM doerj_tac_sinal WHERE cnpj IS NOT NULL")]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cnpj", action="append", default=[])
    ap.add_argument("--tac", action="store_true", help="todos os fornecedores de TAC com CNPJ resolvido")
    ap.add_argument("--detalhar", action="store_true")
    a = ap.parse_args()
    alvos = a.cnpj + (cnpjs_tac() if a.tac else [])
    r = materializar(alvos, detalhar=a.detalhar)
    print(f"[siga] {r['cnpjs']} CNPJs → {r['contratos']} contratos ({r['detalhados']} detalhados)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
