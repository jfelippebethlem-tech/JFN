# -*- coding: utf-8 -*-
"""Cruzamento INTELIGENTE: sócio/administrador de fornecedor que também está na FOLHA do Estado (conflito de
pessoal / incompatibilidade). Reusa os CPFs já RESOLVIDOS (socio_beneficio.cpf_resolvido) e cruza com
`registros_folha`. Servidor/terceirizado que é sócio de empresa contratada pelo mesmo aparelho estatal é
indício de **conflito de interesse / incompatibilidade** (CF art. 37; Lei 8.429/92 art. 11; Lei 14.133 art. 9º).

Honestidade: indício, nunca acusação (pode ser homonímia de CPF resolvido por ponte probabilística, ou vínculo
lícito a confirmar). CPF nunca sai (LGPD); resolvido só ~5% dos sócios → cobertura limitada, INDISPONÍVEL ≠ ausência.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_DB = Path("data") / "compliance.db"


def _con(db_path):
    return sqlite3.connect(f"file:{Path(db_path or _DB)}?mode=ro", uri=True)


def _vazio() -> dict:
    return {"n_resolvidos": 0, "n_na_folha": 0, "itens": []}


def por_cnpjs(cnpjs, db_path: str | Path | None = None) -> dict:
    """Sócios/admin (com CPF resolvido) de um conjunto de fornecedores que constam na folha do Estado."""
    cnpjs = [str(c) for c in cnpjs if c]
    if not cnpjs:
        return _vazio()
    ph = ",".join("?" * len(cnpjs))
    try:
        con = _con(db_path)
        try:
            n_res = con.execute(
                f"""SELECT COUNT(*) FROM (SELECT DISTINCT s.socio_nome_norm, s.socio_doc
                      FROM socios_fornecedor s JOIN socio_beneficio b
                        ON b.socio_nome_norm=s.socio_nome_norm AND b.socio_doc=s.socio_doc
                     WHERE s.cnpj IN ({ph}) AND b.resolvido=1 AND length(b.cpf_resolvido)=11)""",
                cnpjs).fetchone()[0]
            rows = con.execute(
                f"""SELECT s.cnpj, s.razao, s.socio_nome, s.qualificacao,
                          f.orgao_nome, f.cargo, f.vinculo, MAX(f.competencia)
                     FROM socios_fornecedor s
                     JOIN socio_beneficio b ON b.socio_nome_norm=s.socio_nome_norm AND b.socio_doc=s.socio_doc
                     JOIN registros_folha f ON f.cpf=b.cpf_resolvido
                    WHERE s.cnpj IN ({ph}) AND b.resolvido=1 AND length(b.cpf_resolvido)=11
                    GROUP BY s.cnpj, s.socio_nome_norm, f.orgao_nome, f.cargo, f.vinculo""",
                cnpjs).fetchall()
        finally:
            con.close()
    except Exception:  # noqa: BLE001 — tabela ausente / DB indisponível → vazio honesto
        return _vazio()
    itens = [{"cnpj": r[0], "razao": r[1], "nome": r[2], "papel": r[3] or "", "orgao": r[4] or "",
              "cargo": r[5] or "", "vinculo": r[6] or "", "competencia": r[7] or ""} for r in rows]
    return {"n_resolvidos": n_res, "n_na_folha": len({(i["cnpj"], i["nome"]) for i in itens}), "itens": itens}


def por_fornecedor(cnpj: str, db_path: str | Path | None = None) -> dict:
    return por_cnpjs([cnpj], db_path=db_path)


def leitura(agg: dict, escopo: str = "deste fornecedor") -> str:
    """Conclusão honesta sobre o conflito de pessoal (indício, nunca acusação)."""
    nres = agg.get("n_resolvidos", 0)
    nf = agg.get("n_na_folha", 0)
    if nres == 0:
        return ("Nenhum sócio/administrador com **CPF resolvido** disponível para cruzar com a folha "
                f"{escopo} (resolução de CPF cobre ~5% do QSA) — **INDISPONÍVEL**, não ausência de conflito.")
    if nf == 0:
        return (f"Dos **{nres}** sócios/administradores com CPF resolvido {escopo}, **nenhum** consta na folha do "
                "Estado — indício de conflito de pessoal **AFASTADO** para os resolvidos (os demais, com CPF não "
                "resolvido, seguem **INDISPONÍVEL**).")
    return (f"**Indício de conflito de pessoal:** **{nf}** de {nres} sócios/administradores com CPF resolvido "
            f"{escopo} constam na **folha do Estado** (servidor/terceirizado/bolsista). Ser sócio/gestor de empresa "
            "contratada pelo poder público e simultaneamente integrar sua folha é **indício** de conflito de "
            "interesse/incompatibilidade (CF art. 37; Lei 8.429/92 art. 11; Lei 14.133 art. 9º) — confirmar a "
            "identidade (CPF resolvido por ponte) e a natureza do vínculo. **Indício, não prova.**")
