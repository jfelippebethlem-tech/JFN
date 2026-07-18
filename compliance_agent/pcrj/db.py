# -*- coding: utf-8 -*-
"""Banco DEDICADO do módulo PCRJ (``data/pcrj.db``).

Isola o módulo novo da ``compliance.db`` de 1,2G (não arrisca o hub durante o
desenvolvimento). O cruzamento com OB/despesa, quando existir, é feito por
``ATTACH DATABASE`` na hora da consulta — não por escrita na base grande.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "pcrj.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pcrj_camara_servidores (
    nome          TEXT NOT NULL,
    nome_norm     TEXT NOT NULL,
    vinculo       TEXT,
    simbolo       TEXT,
    cargo         TEXT,
    lotacao       TEXT,
    gabinete_num  INTEGER,          -- Nº do Gabinete Parlamentar (se a lotação for gabinete)
    tipo_lotacao  TEXT,             -- gabinete_parlamentar | administrativo | outro
    ano_ingresso  INTEGER,
    data1         TEXT,             -- data do ato (verbatim da fonte)
    data2         TEXT,             -- data de publicação/exercício (verbatim)
    doc_num       TEXT,
    coletado_em   TEXT,
    PRIMARY KEY (nome_norm, cargo, lotacao, ano_ingresso, doc_num)
);
CREATE INDEX IF NOT EXISTS ix_camara_nomenorm ON pcrj_camara_servidores(nome_norm);
CREATE INDEX IF NOT EXISTS ix_camara_gab ON pcrj_camara_servidores(gabinete_num);

CREATE TABLE IF NOT EXISTS pcrj_gabinetes (
    gabinete_num  INTEGER PRIMARY KEY,
    vereador      TEXT,              -- efetivo (suplente em exercício, senão titular) — retrocompat
    vereador_norm TEXT,
    titular       TEXT,              -- vereador titular do gabinete (legislatura atual)
    suplente      TEXT,              -- suplente em exercício, se houver
    coletado_em   TEXT
);

CREATE TABLE IF NOT EXISTS pcrj_prefeitura_consulta (
    nome_norm     TEXT NOT NULL,    -- nome consultado (da Câmara)
    encontrado    INTEGER,          -- 1=achou algum vínculo, 0=nada, NULL=erro/indisponível
    nome_pcrj     TEXT,             -- nome retornado pela Prefeitura (verbatim)
    orgao         TEXT,
    cargo         TEXT,
    vinculo       TEXT,
    remuneracao   TEXT,
    confianca     TEXT,             -- exato | exato_cargo | homonimo_possivel | indisponivel
    bruto         TEXT,             -- json cru do retorno (proveniência)
    consultado_em TEXT,
    PRIMARY KEY (nome_norm, nome_pcrj, orgao, cargo)
);

CREATE TABLE IF NOT EXISTS tse_candidatura (
    nome_norm     TEXT NOT NULL,    -- nome normalizado do servidor casado
    nome_tse      TEXT,             -- NM_CANDIDATO (verbatim)
    nome_urna     TEXT,
    ano           INTEGER,
    cargo         TEXT,
    municipio     TEXT,             -- NM_UE (unidade eleitoral; município na eleição municipal)
    uf            TEXT,
    partido       TEXT,
    situacao      TEXT,
    outra_cidade  INTEGER,          -- 1 se município ≠ RIO DE JANEIRO
    uf_nascimento TEXT,             -- SG_UF_NASCIMENTO (naturalidade; '' se redigido/LGPD)
    resultado     TEXT,             -- DS_SIT_TOT_TURNO (ELEITO POR QP/MÉDIA/QP, SUPLENTE, NÃO ELEITO…)
    eleito        INTEGER,          -- 1 se DS_SIT_TOT_TURNO indica ELEITO (não suplente)
    coletado_em   TEXT,
    PRIMARY KEY (nome_norm, ano, cargo, municipio, partido)
);
CREATE INDEX IF NOT EXISTS ix_tse_nomenorm ON tse_candidatura(nome_norm);

CREATE TABLE IF NOT EXISTS pcrj_filiado (
    nome_norm     TEXT NOT NULL,    -- nome normalizado do filiado casado com servidor/candidato
    nome          TEXT,             -- nome verbatim do filiado
    municipio     TEXT,             -- município do domicílio eleitoral (cidade de origem!)
    uf            TEXT,
    partido       TEXT,
    titulo        TEXT,             -- nº de inscrição (título) — dígitos 9-10 = UF de alistamento
    data_filiacao TEXT,
    situacao      TEXT,
    fonte         TEXT,             -- brasilio | ...
    coletado_em   TEXT,
    PRIMARY KEY (nome_norm, partido, municipio)
);
CREATE INDEX IF NOT EXISTS ix_filiado_nomenorm ON pcrj_filiado(nome_norm);

CREATE TABLE IF NOT EXISTS pcrj_comissionado_candidato (
    nome_norm     TEXT NOT NULL,
    nome_pcrj     TEXT,
    cargo_pcrj    TEXT,             -- cargo na Prefeitura (comissionado: ESPECIAL/DAS/DAI)
    orgao_pcrj    TEXT,
    admissao      TEXT,
    exoneracao    TEXT,
    matricula     TEXT,
    cand_cidade   TEXT,             -- município da candidatura (TSE)
    cand_ano      INTEGER,
    cand_cargo    TEXT,
    coletado_em   TEXT,
    PRIMARY KEY (nome_norm, orgao_pcrj, cargo_pcrj, admissao)
);
CREATE INDEX IF NOT EXISTS ix_comcand_nome ON pcrj_comissionado_candidato(nome_norm);

CREATE TABLE IF NOT EXISTS pcrj_vinculo_cruzado (
    nome_norm     TEXT NOT NULL,
    nome_camara   TEXT,
    gabinetes     TEXT,             -- lista de gabinetes/lotações na Câmara
    cargos_camara TEXT,
    nome_pcrj     TEXT,
    orgao_pcrj    TEXT,
    cargo_pcrj    TEXT,
    confianca     TEXT,
    observacao    TEXT,
    gerado_em     TEXT,
    PRIMARY KEY (nome_norm, orgao_pcrj, cargo_pcrj)
);

-- ── Harvester de licitações municipais (Saúde + PPPs, 2021+) ──────────────
-- Fontes: A=PNCP  B=ContasRio  C=D.O. Rio(doweb)  D=SEI-Pref(SIGA/SEI.RIO)  E=CCPAR
CREATE TABLE IF NOT EXISTS pcrj_doe_materia (   -- ato bruto do Diário Oficial (proveniência)
    id_materia    TEXT PRIMARY KEY,             -- {diario_id}_{pagina} (id do Elasticsearch)
    diario_id     TEXT,
    pdf_id        TEXT,
    pagina        INTEGER,
    data          TEXT,                          -- verbatim da fonte
    ano           INTEGER,
    termo_busca   TEXT,                          -- termo que trouxe a matéria
    orgao         TEXT,                          -- inferido do texto (se possível)
    tipo          TEXT,                          -- edital|homologacao|extrato_contrato|ppp|outro (heurístico)
    processos     TEXT,                          -- json: nºs de processo extraídos do texto
    texto         TEXT,
    url           TEXT,                          -- link imprimível da matéria
    coletado_em   TEXT
);
CREATE INDEX IF NOT EXISTS ix_doe_ano  ON pcrj_doe_materia(ano);
CREATE INDEX IF NOT EXISTS ix_doe_tipo ON pcrj_doe_materia(tipo);

CREATE TABLE IF NOT EXISTS pcrj_processo (      -- processo administrativo (SIGA/SEI municipal)
    numero_processo TEXT PRIMARY KEY,
    sistema         TEXT,                        -- siga | seirio
    interessado     TEXT,
    assunto         TEXT,
    orgao           TEXT,
    andamento_json  TEXT,                        -- tramitação
    disponivel      INTEGER,                     -- 1 achou / 0 nada / NULL indisponível (tri-estado)
    coletado_em     TEXT
);

CREATE TABLE IF NOT EXISTS pcrj_processo_doc (  -- documentos do processo (inteiro teor público)
    numero_processo TEXT,
    seq             INTEGER,
    tipo            TEXT,
    titulo          TEXT,
    texto           TEXT,
    url             TEXT,
    coletado_em     TEXT,
    PRIMARY KEY (numero_processo, seq)
);

CREATE TABLE IF NOT EXISTS pcrj_ppp (           -- projeto de PPP/concessão (CCPAR)
    slug              TEXT PRIMARY KEY,
    nome              TEXT,
    orgao_gestor      TEXT,
    objeto            TEXT,
    modalidade        TEXT,
    fase              TEXT,
    valor_investimento REAL,
    contraprestacao   REAL,
    prazo_anos        INTEGER,
    vencedor          TEXT,
    numero_processo   TEXT,
    datas_json        TEXT,
    docs_json         TEXT,
    coletado_em       TEXT
);
"""


def conectar(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Abre a conexão com PRAGMAs VM-safe (WAL + busy_timeout) — padrão dos writers da casa."""
    p = Path(db_path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.row_factory = sqlite3.Row
    return con


def inicializar(db_path: Path | str | None = None) -> None:
    """Cria o schema se não existir (idempotente)."""
    con = conectar(db_path)
    try:
        con.executescript(_SCHEMA)
        # migrações idempotentes (colunas novas em tabela pré-existente)
        cols = {r[1] for r in con.execute("PRAGMA table_info(tse_candidatura)")}
        for nome, ddl in (("uf_nascimento", "TEXT"), ("resultado", "TEXT"),
                          ("eleito", "INTEGER"), ("municipio_nascimento", "TEXT"),
                          ("uf_alistamento", "TEXT")):
            if nome not in cols:
                con.execute(f"ALTER TABLE tse_candidatura ADD COLUMN {nome} {ddl}")
        con.commit()
    finally:
        con.close()
