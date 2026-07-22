# -*- coding: utf-8 -*-
"""Schema do enxame de editais no compliance.db (aditivo)."""
from __future__ import annotations

import sqlite3

from compliance_agent.emendas.db import conectar  # reexport: mesmo helper WAL/row_factory

__all__ = ["conectar", "init_schema", "DDL", "DDL_CERTAME_INDICE", "DDL_CERTAME_JULGAMENTO",
           "salvar_julgamento"]

# Índice de Direcionamento de Certame (Task 4.3 — indice_certame.py); faixas BAIXO/MEDIO/ALTO/EXTREMO
DDL_CERTAME_INDICE = """CREATE TABLE IF NOT EXISTS certame_indice (
    certame TEXT PRIMARY KEY, score REAL, prioridade REAL, faixa TEXT,
    confianca REAL, familias_json TEXT, drivers_json TEXT,
    gerado_em TEXT DEFAULT (datetime('now')))"""

# Resultado da sessão de julgamento (coletor_ata._extrair_resultado) — antes era EFÊMERO (vivia só
# no ctx); persistido, alimenta a família certame_ata do índice ("o que de fato ocorreu no certame").
DDL_CERTAME_JULGAMENTO = """CREATE TABLE IF NOT EXISTS certame_julgamento (
    certame TEXT PRIMARY KEY, processo_sei TEXT, licitantes INTEGER, inabilitados INTEGER,
    vencedor_cnpj TEXT, motivos_json TEXT, trivialidade_json TEXT,
    houve_diligencia INTEGER DEFAULT 0, atualizado_em TEXT DEFAULT (datetime('now')))"""

DDL = [
    """CREATE TABLE IF NOT EXISTS edital_documento (
        numero_controle_pncp TEXT PRIMARY KEY, ano INTEGER, orgao_cnpj TEXT,
        objeto TEXT, material_servico TEXT, valor_estimado REAL,
        texto TEXT, itens_json TEXT, documento_disponivel INTEGER DEFAULT 0,
        coletado_em TEXT DEFAULT (datetime('now')))""",
    """CREATE TABLE IF NOT EXISTS edital_clausula (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero_controle_pncp TEXT NOT NULL REFERENCES edital_documento(numero_controle_pncp),
        eixo TEXT, subtipo TEXT, texto TEXT, parametro_num REAL,
        assinatura TEXT, trecho_fonte TEXT)""",
    "CREATE INDEX IF NOT EXISTS ix_clau_ctrl ON edital_clausula(numero_controle_pncp)",
    "CREATE INDEX IF NOT EXISTS ix_clau_assin ON edital_clausula(assinatura)",
    """CREATE TABLE IF NOT EXISTS edital_cluster (
        id INTEGER PRIMARY KEY AUTOINCREMENT, assinatura_objeto TEXT,
        membros_json TEXT, tamanho INTEGER, avaliavel INTEGER DEFAULT 0,
        criado_em TEXT DEFAULT (datetime('now')))""",
    """CREATE TABLE IF NOT EXISTS clausula_veredito (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        clausula_id INTEGER REFERENCES edital_clausula(id),
        cluster_id INTEGER REFERENCES edital_cluster(id),
        numero_controle_pncp TEXT, raridade REAL, forca_e7 TEXT, sumula TEXT,
        votos_json TEXT, score_final INTEGER, veredito TEXT,
        verificado_em TEXT DEFAULT (datetime('now')))""",
    DDL_CERTAME_INDICE,
    DDL_CERTAME_JULGAMENTO,
]


def salvar_julgamento(con: sqlite3.Connection, certame: str, resultado: dict,
                      *, houve_diligencia: bool = False, processo_sei: str | None = None) -> dict:
    """Persiste o `resultado` do coletor_ata ({licitantes, inabilitados, motivos, vencedor_cnpj})
    já classificando a TRIVIALIDADE dos motivos (motivo_inabilitacao). A diligência conta POR
    LICITANTE (`motivos_det`): saneamento concedido a outro CNPJ não exculpa a inabilitação
    trivial deste (art. 64 §1º — é o padrão dois-pesos do J7). `houve_diligencia` (sessão) segue
    gravado como contexto; fonte antiga sem `motivos_det` cai no comportamento por sessão.
    Retorna o agregado de trivialidade (com `por_licitante` quando a ata atribui CNPJ)."""
    import json

    from compliance_agent.editais.motivo_inabilitacao import classificar, taxa_trivialidade

    motivos = list(resultado.get("motivos") or [])
    det = list(resultado.get("motivos_det") or [])
    if det:
        classif = [classificar(m["motivo"], houve_diligencia=bool(m.get("diligencia")))
                   for m in det]
        agg = taxa_trivialidade(classif)
        agg["por_licitante"] = [{"cnpj": m["cnpj"], "classe": c.get("classe"),
                                 "violacao_saneamento": bool(c.get("violacao_saneamento"))}
                                for m, c in zip(det, classif)]
    else:
        classif = [classificar(m, houve_diligencia=houve_diligencia) for m in motivos]
        agg = taxa_trivialidade(classif)
    con.execute(DDL_CERTAME_JULGAMENTO)
    con.execute(
        "INSERT INTO certame_julgamento (certame, processo_sei, licitantes, inabilitados, "
        "vencedor_cnpj, motivos_json, trivialidade_json, houve_diligencia, atualizado_em) "
        "VALUES (?,?,?,?,?,?,?,?, datetime('now')) ON CONFLICT(certame) DO UPDATE SET "
        "processo_sei=excluded.processo_sei, licitantes=excluded.licitantes, "
        "inabilitados=excluded.inabilitados, vencedor_cnpj=excluded.vencedor_cnpj, "
        "motivos_json=excluded.motivos_json, trivialidade_json=excluded.trivialidade_json, "
        "houve_diligencia=excluded.houve_diligencia, atualizado_em=datetime('now')",
        (certame, processo_sei, resultado.get("licitantes"), resultado.get("inabilitados"),
         resultado.get("vencedor_cnpj"), json.dumps(motivos, ensure_ascii=False),
         json.dumps(agg, ensure_ascii=False), int(houve_diligencia)))
    con.commit()
    return agg


def init_schema(con: sqlite3.Connection) -> None:
    for ddl in DDL:
        con.execute(ddl)
    # migração aditiva: beneficiário na própria linha do veredito (o runner já extrai o vencedor
    # via atas; sem persistir, a seção VI da ficha ficava eternamente "indisponível")
    for col in ("vencedor_doc TEXT", "sinais_json TEXT"):
        try:
            con.execute(f"ALTER TABLE clausula_veredito ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass  # coluna já existe
    con.commit()
