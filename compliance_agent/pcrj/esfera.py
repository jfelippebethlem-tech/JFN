# -*- coding: utf-8 -*-
"""Classificação por ESFERA (federal / estadual-RJ / municipal-Rio).

A correção do dono: o PNCP NÃO se "limpa" — serve os dois níveis (Estado e
Prefeitura do Rio) e a presença de um fornecedor no federal/estadual é sinal, não
ruído. Aqui a esfera vira uma **dimensão de consulta**, não um corte destrutivo.

Design seguro: NÃO altera a ``compliance.db`` (hub live). O classificador é função
pura; o mapa órgão→esfera é materializado em ``pcrj.db`` (``pcrj_orgao_esfera``),
lido por ATTACH/JOIN quando os motores precisam filtrar por esfera. Honestidade:
órgão não reconhecido = ``"indefinido"`` (nunca chuta).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import db

# 19/11/2026 (dono: "esquece a parte federal" / "tem que ser do RJ"): a decisão de esfera mora em
# ``compliance_agent/esfera_orgao.py`` (raiz CNPJ → natureza jurídica da Receita + UF da sede → nome só
# com marca do RJ). Aqui só se traduz para o vocabulário histórico deste módulo. As regex de nome que
# viviam aqui casavam "SECRETARIA DE ESTADO"/"TRIBUNAL DE CONTAS DO ESTADO" de qualquer estado e
# testavam estadual antes de federal (UNIRIO e conselhos regionais saíam "estadual-rj").
from compliance_agent import esfera_orgao as _eo

_ROOTS = _eo.RAIZES_RJ   # compat: quem importava as raízes daqui

ESFERAS = ("federal", "estadual-rj", "municipal-rio", "municipal-outro", "outro-estado", "indefinido")
_DO_CANONICO = {"outro-municipio": "municipal-outro"}


def classificar_esfera(orgao_nome: str = "", orgao_cnpj: str = "") -> str:
    """Esfera do órgão (vocabulário de :data:`ESFERAS`) — delega a ``esfera_orgao``.

    ``"indefinido"`` quando não há sinal seguro; ``"outro-estado"`` = órgão estadual de outra UF.
    """
    e = _eo.esfera(orgao_cnpj or "", orgao_nome or "")
    return _DO_CANONICO.get(e, e)


_SCHEMA_MAPA = """
CREATE TABLE IF NOT EXISTS pcrj_orgao_esfera (
    orgao_cnpj   TEXT PRIMARY KEY,
    orgao_nome   TEXT,
    esfera       TEXT,           -- federal | estadual-rj | municipal-rio | municipal-outro | outro-estado | indefinido
    n_registros  INTEGER,
    classificado_em TEXT
);
CREATE INDEX IF NOT EXISTS ix_orgao_esfera ON pcrj_orgao_esfera(esfera);
"""


def construir_mapa(compliance_db=db.COMPLIANCE_DB, db_path=None) -> dict:
    """Lê os órgãos distintos da compliance.db (SÓ leitura) e materializa o mapa
    órgão→esfera em ``pcrj.db`` (``pcrj_orgao_esfera``). Não escreve na compliance.db.
    """
    con = db.conectar(db_path)
    con.executescript(_SCHEMA_MAPA)
    src = sqlite3.connect(f"file:{compliance_db}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    orgaos: dict[str, list] = {}
    for tabela in ("pcrj_licitacoes", "pcrj_contratos"):
        try:
            rows = src.execute(
                f"SELECT orgao_cnpj, orgao_nome, COUNT(*) n FROM {tabela} "
                f"WHERE orgao_cnpj IS NOT NULL GROUP BY orgao_cnpj, orgao_nome").fetchall()
        except sqlite3.OperationalError:
            continue
        for r in rows:
            cnpj = r["orgao_cnpj"]
            if cnpj not in orgaos:
                orgaos[cnpj] = [r["orgao_nome"], 0]
            orgaos[cnpj][1] += r["n"]
            if not orgaos[cnpj][0]:
                orgaos[cnpj][0] = r["orgao_nome"]
    src.close()

    agora = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    contagem: dict[str, int] = {}
    for cnpj, (nome, n) in orgaos.items():
        esf = classificar_esfera(nome, cnpj)
        contagem[esf] = contagem.get(esf, 0) + 1
        con.execute(
            "INSERT INTO pcrj_orgao_esfera (orgao_cnpj,orgao_nome,esfera,n_registros,classificado_em) "
            "VALUES (?,?,?,?,?) ON CONFLICT(orgao_cnpj) DO UPDATE SET "
            "orgao_nome=excluded.orgao_nome, esfera=excluded.esfera, "
            "n_registros=excluded.n_registros, classificado_em=excluded.classificado_em",
            (cnpj, nome, esf, n, agora))
    con.commit()
    con.close()
    return {"orgaos": len(orgaos), "por_esfera": contagem}


if __name__ == "__main__":
    import json
    print(json.dumps(construir_mapa(), ensure_ascii=False, indent=2))
