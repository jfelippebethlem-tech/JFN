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

import re
import sqlite3
from datetime import datetime, timezone

from . import db

# Raízes de CNPJ "guarda-chuva" (override forte)
_ROOTS = {
    "42498600": "estadual-rj",   # ESTADO DO RIO DE JANEIRO
    "42498733": "municipal-rio",  # MUNICIPIO DE RIO DE JANEIRO
}

# Ordem importa: municipal e estadual-RJ ANTES de federal
# (ex.: "MINISTÉRIO PÚBLICO DO ESTADO DO RIO" é estadual, não federal).
_MUNICIPAL_RIO = re.compile(
    r"MUNIC[IÍ]PIO\s+D[EO]\s+RIO DE JANEIRO|PREFEITURA\b.*RIO DE JANEIRO|"
    r"C[ÂA]MARA MUNICIPAL\b.*RIO DE JANEIRO|MUNIC[IÍ]PIO DO RIO DE JANEIRO", re.I)
_ESTADUAL_RJ = re.compile(
    r"ESTADO DO RIO DE JANEIRO|GOVERNO DO ESTADO\b.*RIO|SECRETARIA DE ESTADO|"
    r"ASSEMBLEIA LEGISLATIVA\b.*RIO|MINIST[ÉE]RIO P[UÚ]BLICO DO ESTADO DO RIO|"
    r"TRIBUNAL DE CONTAS DO ESTADO", re.I)
_FEDERAL = re.compile(
    r"MINIST[ÉE]RIO\b|COMANDO DA (MARINHA|EX[ÉE]RCITO|AERON[ÁA]UTICA)|"
    r"UNIVERSIDADE FEDERAL|INSTITUTO FEDERAL|HOSPITAL FEDERAL|\bBNDES\b|"
    r"OSWALDO CRUZ|FIOCRUZ|FIOTEC|UNI[ÃA]O\b|AG[ÊE]NCIA NACIONAL|"
    r"CAIXA ECON[ÔO]MICA|BANCO CENTRAL|BANCO DO BRASIL|POL[IÍ]CIA FEDERAL|"
    r"RECEITA FEDERAL|ADVOCACIA[- ]GERAL DA UNI[ÃA]O|TRIBUNAL REGIONAL|"
    r"SUPERIOR TRIBUNAL|CASA DA MOEDA|COL[ÉE]GIO PEDRO II|\bFURNAS\b|"
    r"CENTRAIS EL[ÉE]TRICAS|ELETROBRAS|COMISS[ÃA]O NACIONAL|"
    r"COMPANHIA DE PESQUISA DE RECURSOS MINERAIS|SERVI[ÇC]O GEOL[ÓO]GICO|"
    r"PETR[ÓO]LEO BRASILEIRO|PETROBRAS|EMPRESA BRASILEIRA|CORREIOS|SERPRO|"
    r"DATAPREV|INSTITUTO NACIONAL|FUNDA[ÇC][ÃA]O NACIONAL|CONSELHO NACIONAL|"
    r"AG[ÊE]NCIA ESPACIAL|IND[ÚU]STRIAS NUCLEARES|INSTITUTO BRASILEIRO|"
    r"DEPARTAMENTO NACIONAL|SUPERINTEND[ÊE]NCIA (FEDERAL|NACIONAL)", re.I)

ESFERAS = ("federal", "estadual-rj", "municipal-rio", "indefinido")


def classificar_esfera(orgao_nome: str = "", orgao_cnpj: str = "") -> str:
    """Deriva a esfera de um órgão pelo CNPJ (raiz guarda-chuva) e pelo nome.

    Retorna uma de :data:`ESFERAS`. ``"indefinido"`` quando não há sinal seguro.
    """
    raiz = re.sub(r"\D", "", orgao_cnpj or "")[:8]
    if raiz in _ROOTS:
        return _ROOTS[raiz]
    if raiz.startswith("00394"):   # base CNPJ da União
        return "federal"
    nome = orgao_nome or ""
    if _MUNICIPAL_RIO.search(nome):
        return "municipal-rio"
    if _ESTADUAL_RJ.search(nome):
        return "estadual-rj"
    if _FEDERAL.search(nome):
        return "federal"
    return "indefinido"


_SCHEMA_MAPA = """
CREATE TABLE IF NOT EXISTS pcrj_orgao_esfera (
    orgao_cnpj   TEXT PRIMARY KEY,
    orgao_nome   TEXT,
    esfera       TEXT,           -- federal | estadual-rj | municipal-rio | indefinido
    n_registros  INTEGER,
    classificado_em TEXT
);
CREATE INDEX IF NOT EXISTS ix_orgao_esfera ON pcrj_orgao_esfera(esfera);
"""


def construir_mapa(compliance_db: str = "data/compliance.db", db_path=None) -> dict:
    """Lê os órgãos distintos da compliance.db (SÓ leitura) e materializa o mapa
    órgão→esfera em ``pcrj.db`` (``pcrj_orgao_esfera``). Não escreve na compliance.db.
    """
    con = db.conectar(db_path)
    con.executescript(_SCHEMA_MAPA)
    # leitura da fonte (read-only) — junta órgãos de licitações e contratos
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


def esfera_do_cnpj(orgao_cnpj: str, db_path=None) -> str:
    """Consulta o mapa materializado; cai no classificador se o órgão não estiver mapeado."""
    con = db.conectar(db_path)
    try:
        row = con.execute("SELECT esfera FROM pcrj_orgao_esfera WHERE orgao_cnpj=?",
                          (orgao_cnpj,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        con.close()
    return row["esfera"] if row else classificar_esfera("", orgao_cnpj)


if __name__ == "__main__":
    import json
    print(json.dumps(construir_mapa(), ensure_ascii=False, indent=2))
