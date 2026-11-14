# -*- coding: utf-8 -*-
"""`data/territorio.db` — o ÚNICO banco em que este motor escreve.

`compliance.db` e `pcrj.db` são abertos em modo `ro` (URI): escrever neles está proibido (histórico
de corrupção de WAL), e o modo `ro` torna a regra uma garantia do SQLite, não uma promessa do código.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
DATA = Path(os.environ.get("JFN_DATA_DIR") or (_REPO / "data"))
DB = DATA / "territorio.db"

DDL = """
CREATE TABLE IF NOT EXISTS territorio_contrato_estado(
  contrato_id TEXT PRIMARY KEY, fonte TEXT, orgao TEXT, fornecedor_cnpj TEXT, fornecedor_nome TEXT, objeto TEXT,
  valor REAL, vig_ini TEXT, vig_fim TEXT, status TEXT, pago REAL, cod_ibge TEXT, multi INTEGER DEFAULT 0,
  municipios_json TEXT, regiao TEXT, metodo TEXT, confianca TEXT, evidencia TEXT, metodos_json TEXT,
  pago_evidencia TEXT, assinatura TEXT, atualizado_em TEXT);
CREATE INDEX IF NOT EXISTS ix_tce_mun ON territorio_contrato_estado(cod_ibge);
CREATE TABLE IF NOT EXISTS territorio_mun_agg(
  cod_ibge TEXT PRIMARY KEY, nome TEXT, n_em_execucao INTEGER, n_executados INTEGER, valor_contratado REAL,
  valor_em_execucao REAL, pago REAL, n_alertas INTEGER, n_multi INTEGER, atualizado_em TEXT);
CREATE TABLE IF NOT EXISTS territorio_baldes(balde TEXT PRIMARY KEY, n INTEGER, valor REAL, atualizado_em TEXT);
CREATE TABLE IF NOT EXISTS territorio_contrato_pcrj(
  contrato_id TEXT PRIMARY KEY, fonte TEXT, orgao TEXT, ug TEXT, fornecedor_cnpj TEXT, fornecedor_nome TEXT,
  objeto TEXT, valor REAL, vig_ini TEXT, vig_fim TEXT, status TEXT, pago REAL, ap INTEGER, ra TEXT, bairro TEXT,
  multi INTEGER DEFAULT 0, aps_json TEXT, metodo TEXT, confianca TEXT, evidencia TEXT, metodos_json TEXT,
  assinatura TEXT, atualizado_em TEXT);
CREATE INDEX IF NOT EXISTS ix_tcp_ap ON territorio_contrato_pcrj(ap);
CREATE TABLE IF NOT EXISTS territorio_ap_agg(
  ap INTEGER PRIMARY KEY, ra_json TEXT, n_em_execucao INTEGER, n_executados INTEGER, valor_contratado REAL,
  valor_em_execucao REAL, pago REAL, n_alertas INTEGER, n_multi INTEGER, atualizado_em TEXT);
CREATE TABLE IF NOT EXISTS territorio_meta(chave TEXT PRIMARY KEY, valor TEXT);
"""


def agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def abrir(escrita: bool = False) -> sqlite3.Connection:
    """Conexão com `territorio.db`. Leitura falha (OperationalError) se o motor nunca rodou."""
    if escrita:
        DATA.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB, timeout=30)
        c.executescript(DDL)
        # fase 7b: colunas novas em banco já criado (CREATE IF NOT EXISTS não altera tabela existente)
        # fase 12 (14/11/2026): grau de certeza, situação na fonte, assinatura, OBs e série mensal do pago, indício
        est = "territorio_contrato_estado"
        for tabela, col in ((est, "fontes_json TEXT"), (est, "abrangencia TEXT"), ("territorio_contrato_pcrj", "abrangencia TEXT"),
                            (est, "grau TEXT"), (est, "situacao_fonte TEXT"), (est, "data_assinatura TEXT"), (est, "processo TEXT"),
                            (est, "n_obs INTEGER"), (est, "pago_mensal_json TEXT"), (est, "pago_motivo TEXT"), (est, "alerta TEXT")):
            if col.split()[0] not in {r[1] for r in c.execute(f"PRAGMA table_info({tabela})")}:
                c.execute(f"ALTER TABLE {tabela} ADD COLUMN {col}")
    else:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def fonte_ro(nome: str) -> sqlite3.Connection:
    """`compliance.db` / `pcrj.db` SOMENTE-LEITURA."""
    c = sqlite3.connect(f"file:{DATA / nome}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def meta(c: sqlite3.Connection, chave: str, padrao: str | None = None) -> str | None:
    try:
        r = c.execute("SELECT valor FROM territorio_meta WHERE chave=?", (chave,)).fetchone()
    except sqlite3.OperationalError:
        return padrao
    return r[0] if r else padrao


def por_meta(c: sqlite3.Connection, chave: str, valor: str) -> None:
    c.execute("INSERT INTO territorio_meta(chave,valor) VALUES(?,?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
              (chave, valor))
