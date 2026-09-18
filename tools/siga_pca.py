#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""siga_pca — Plano de Contratações Anual (PCA) de TODAS as unidades do Estado, extração pública do SIGA.

Fonte (sem API, 12/09/2026): https://www.compras.rj.gov.br/siga/imagens/EXTRACAO_VIGENTE_PCA.zip
(csv ; latin/utf-8 com BOM: PCA;Unidade;Data de Publicação PNCP;ID do PNCP;Código do Item;Descrição do Item;
Quantidade;Vl. Unitário;Vl. Total;PLOA/LOA;Data Desejada;Situação;Ano Vigência PCA). ~14 MB.

Para que serve: o PCA é o que o órgão DISSE que ia contratar no ano. Serviço pago por TAC/emergência que está no
PCA = planejamento existiu e a execução falhou (o "imprevisível" era previsto); que NÃO está = contratação fora do
plano (art. 12, VII e art. 18 Lei 14.133). Materializa `siga_pca_itens`.

Uso: PYTHONPATH=. .venv/bin/python -m tools.siga_pca   (semanal)
"""
from __future__ import annotations

import csv
import io
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

_REPO = Path(__file__).resolve().parents[1]
DB = _REPO / "data" / "compliance.db"
URL = "https://www.compras.rj.gov.br/siga/imagens/EXTRACAO_VIGENTE_PCA.zip"
CACHE = _REPO / "data" / "cache" / "EXTRACAO_VIGENTE_PCA.zip"


def _num(s: str) -> float | None:
    try:
        return float((s or "").replace(".", "").replace(",", ".")) if "," in (s or "") else float(s or "")
    except ValueError:
        return None


def ler_csv(conteudo: bytes) -> list[dict]:
    texto = conteudo.decode("utf-8-sig", errors="replace")
    rd = csv.DictReader(io.StringIO(texto), delimiter=";")
    out = []
    for r in rd:
        out.append({"pca": r.get("PCA"), "unidade": r.get("Unidade"), "publicacao_pncp": r.get("Data de Publicação PNCP"),
                    "id_pncp": r.get("ID do PNCP"), "codigo_item": r.get("Código do Item"), "descricao": r.get("Descrição do Item"),
                    "quantidade": _num(r.get("Quantidade")), "vl_unitario": _num(r.get("Vl. Unitário")), "vl_total": _num(r.get("Vl. Total")),
                    "data_desejada": r.get("Data Desejada"), "situacao": r.get("Situação"), "ano": r.get("Ano Vigência PCA")})
    return out


def materializar(conteudo: bytes | None = None) -> dict:
    if conteudo is None:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        r = httpx.get(URL, headers={"User-Agent": "Mozilla/5.0 (JFN fiscalizacao)"}, timeout=300, follow_redirects=True)
        r.raise_for_status()
        CACHE.write_bytes(r.content)
        conteudo = r.content
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        nome = z.namelist()[0]
        itens = ler_csv(z.read(nome))
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with con:
        con.execute("DROP TABLE IF EXISTS siga_pca_itens_novo")
        con.execute("CREATE TABLE siga_pca_itens_novo (pca TEXT, ug TEXT, unidade TEXT, publicacao_pncp TEXT, id_pncp TEXT, codigo_item TEXT, "
                    "descricao TEXT, quantidade REAL, vl_unitario REAL, vl_total REAL, data_desejada TEXT, situacao TEXT, ano TEXT, visto_em TEXT)")
        con.executemany("INSERT INTO siga_pca_itens_novo VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [(i["pca"], (i["pca"] or "")[:6], i["unidade"], i["publicacao_pncp"], i["id_pncp"], i["codigo_item"], i["descricao"],
                          i["quantidade"], i["vl_unitario"], i["vl_total"], i["data_desejada"], i["situacao"], i["ano"], agora) for i in itens])
        con.executescript("DROP TABLE IF EXISTS siga_pca_itens; ALTER TABLE siga_pca_itens_novo RENAME TO siga_pca_itens; "
                          "CREATE INDEX IF NOT EXISTS ix_pca_ug ON siga_pca_itens(ug);")
    n_un = con.execute("SELECT count(DISTINCT unidade), round(sum(vl_total),2) FROM siga_pca_itens").fetchone()
    con.close()
    return {"itens": len(itens), "unidades": n_un[0], "valor_total": n_un[1]}


def main() -> int:
    r = materializar()
    print(f"[pca] {r['itens']} itens · {r['unidades']} unidades · R$ {r['valor_total']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
