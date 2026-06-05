"""
Indexador do dump público de CNPJ da Receita Federal do Brasil.

Fonte: https://dadosabertos.rfb.gov.br/CNPJ/
Atualizado mensalmente pelo Ministério da Fazenda.

Uso típico
----------
# 1. Baixar e indexar (uma vez por mês, ~10 min):
asyncio.run(baixar_e_indexar())

# 2. Buscar empresas de um sócio pelo nome:
empresas = buscar_empresas_por_nome_socio("EDUARDO DA SILVA AZEVEDO")

# 3. Verificar se sócio está em outras empresas (rede societária):
rede = expandir_por_nome(nome, max_nivel=2)
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
import re
import sqlite3
import zipfile
from datetime import date
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://dadosabertos.rfb.gov.br/CNPJ/dados_abertos_cnpj/"
_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "cnpj_socios.db"
_TIMEOUT = 120

# Quantidade de arquivos Socios (0–9) — a RF divide em 10 partes
_N_PARTES = 10


def _get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _criar_tabelas(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS socios (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            cnpj        TEXT NOT NULL,
            tipo_socio  TEXT,
            nome        TEXT NOT NULL,
            cpf_cnpj    TEXT,
            qualificacao TEXT,
            data_entrada TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_socios_nome   ON socios (nome);
        CREATE INDEX IF NOT EXISTS idx_socios_cnpj   ON socios (cnpj);
        CREATE INDEX IF NOT EXISTS idx_socios_cpfcnpj ON socios (cpf_cnpj);
        CREATE TABLE IF NOT EXISTS meta (
            chave TEXT PRIMARY KEY,
            valor TEXT
        );
    """)
    conn.commit()


def _mes_atual() -> str:
    """Retorna o período mais recente disponível no formato YYYY-MM."""
    hoje = date.today()
    return f"{hoje.year}-{hoje.month:02d}"


async def _baixar_zip(url: str, client: httpx.AsyncClient) -> Optional[bytes]:
    try:
        r = await client.get(url, timeout=_TIMEOUT, follow_redirects=True)
        if r.status_code == 200:
            return r.content
        logger.warning("HTTP %d para %s", r.status_code, url)
        return None
    except Exception as exc:
        logger.warning("Erro baixando %s: %s", url, exc)
        return None


def _processar_zip_socios(conteudo: bytes, conn: sqlite3.Connection, batch_size: int = 5000) -> int:
    """Lê um ZIP de sócios da RF e insere no SQLite. Retorna número de registros inseridos."""
    total = 0
    with zipfile.ZipFile(io.BytesIO(conteudo)) as zf:
        for nome_arquivo in zf.namelist():
            if not nome_arquivo.endswith((".csv", ".txt", "")):
                continue
            with zf.open(nome_arquivo) as f:
                # Arquivo da RF: separado por ";" sem cabeçalho
                # Colunas: CNPJ_BASICO;ID_TIPO_SOCIO;NOME_SOCIO;CNPJ_CPF_SOCIO;QUALIFICACAO;DATA_ENTRADA;PAIS;REPRESENTANTE;NOME_REPR;QUALIF_REPR;FAIXA_ETARIA
                reader = csv.reader(
                    io.TextIOWrapper(f, encoding="latin-1", errors="replace"),
                    delimiter=";",
                )
                batch = []
                for row in reader:
                    if len(row) < 4:
                        continue
                    cnpj_base = row[0].strip().zfill(8)
                    tipo = row[1].strip() if len(row) > 1 else ""
                    nome = (row[2].strip() or "").upper()
                    cpf_cnpj = row[3].strip() if len(row) > 3 else ""
                    qualif = row[4].strip() if len(row) > 4 else ""
                    dt_entrada = row[5].strip() if len(row) > 5 else ""
                    if not nome:
                        continue
                    batch.append((cnpj_base, tipo, nome, cpf_cnpj, qualif, dt_entrada))
                    if len(batch) >= batch_size:
                        conn.executemany(
                            "INSERT INTO socios (cnpj,tipo_socio,nome,cpf_cnpj,qualificacao,data_entrada) VALUES (?,?,?,?,?,?)",
                            batch,
                        )
                        total += len(batch)
                        batch = []
                if batch:
                    conn.executemany(
                        "INSERT INTO socios (cnpj,tipo_socio,nome,cpf_cnpj,qualificacao,data_entrada) VALUES (?,?,?,?,?,?)",
                        batch,
                    )
                    total += len(batch)
    conn.commit()
    return total


async def baixar_e_indexar(periodo: Optional[str] = None, force: bool = False) -> dict:
    """
    Baixa os arquivos Socios do dump da RF e popula o banco SQLite local.

    Parâmetros
    ----------
    periodo : "YYYY-MM" (padrão: mês corrente)
    force   : se True, re-indexa mesmo se já houver dados do período

    Retorno
    -------
    dict com "ok", "periodo", "registros_inseridos", "db_path"
    """
    if periodo is None:
        periodo = _mes_atual()

    conn = _get_conn()
    _criar_tabelas(conn)

    # Verifica se já indexou este período
    row = conn.execute("SELECT valor FROM meta WHERE chave=?", ("periodo_indexado",)).fetchone()
    if row and row[0] == periodo and not force:
        logger.info("Dump %s já indexado. Use force=True para re-indexar.", periodo)
        n = conn.execute("SELECT COUNT(*) FROM socios").fetchone()[0]
        return {"ok": True, "periodo": periodo, "ja_indexado": True, "total_registros": n, "db_path": str(_DB_PATH)}

    # Limpa dados anteriores
    conn.execute("DELETE FROM socios")
    conn.execute("DELETE FROM meta WHERE chave='periodo_indexado'")
    conn.commit()

    base = f"{_BASE_URL}{periodo}/"
    total_inseridos = 0
    erros = []

    async with httpx.AsyncClient() as client:
        for i in range(_N_PARTES):
            url = f"{base}Socios{i}.zip"
            logger.info("Baixando %s …", url)
            conteudo = await _baixar_zip(url, client)
            if conteudo is None:
                erros.append(url)
                continue
            n = _processar_zip_socios(conteudo, conn)
            total_inseridos += n
            logger.info("  → %d registros (acumulado %d)", n, total_inseridos)

    if total_inseridos > 0:
        conn.execute(
            "INSERT OR REPLACE INTO meta (chave,valor) VALUES ('periodo_indexado',?)",
            (periodo,),
        )
        conn.commit()

    conn.close()
    return {
        "ok": total_inseridos > 0 or not erros,
        "periodo": periodo,
        "registros_inseridos": total_inseridos,
        "db_path": str(_DB_PATH),
        "erros": erros if erros else None,
    }


def buscar_empresas_por_nome_socio(nome: str, limit: int = 50) -> list[dict]:
    """
    Busca empresas em que uma pessoa (pelo nome) figura como sócia.

    Usa o banco local gerado por `baixar_e_indexar()`.
    Retorna lista vazia se o banco não existir ainda.
    """
    if not _DB_PATH.exists():
        logger.warning("Banco local não existe. Rode baixar_e_indexar() primeiro.")
        return []
    nome_upper = nome.strip().upper()
    conn = _get_conn()
    rows = conn.execute(
        """SELECT cnpj, tipo_socio, nome, cpf_cnpj, qualificacao, data_entrada
           FROM socios
           WHERE nome LIKE ?
           LIMIT ?""",
        (f"%{nome_upper}%", limit),
    ).fetchall()
    conn.close()
    return [
        {
            "cnpj_base": r[0],
            "tipo_socio": r[1],
            "nome": r[2],
            "cpf_cnpj": r[3],
            "qualificacao": r[4],
            "data_entrada": r[5],
        }
        for r in rows
    ]


def buscar_empresas_por_cpf_parcial(cpf_parcial: str, limit: int = 50) -> list[dict]:
    """
    Busca empresas por trecho do CPF/CNPJ do sócio.

    Os CPFs no dump da RF vêm parcialmente mascarados (***XXX.XX**).
    Use os 6 dígitos centrais para localizar correspondências.

    Exemplo: buscar_empresas_por_cpf_parcial("67759")
    """
    if not _DB_PATH.exists():
        logger.warning("Banco local não existe. Rode baixar_e_indexar() primeiro.")
        return []
    conn = _get_conn()
    rows = conn.execute(
        """SELECT cnpj, tipo_socio, nome, cpf_cnpj, qualificacao, data_entrada
           FROM socios
           WHERE cpf_cnpj LIKE ?
           LIMIT ?""",
        (f"%{cpf_parcial.strip()}%", limit),
    ).fetchall()
    conn.close()
    return [
        {
            "cnpj_base": r[0],
            "tipo_socio": r[1],
            "nome": r[2],
            "cpf_cnpj": r[3],
            "qualificacao": r[4],
            "data_entrada": r[5],
        }
        for r in rows
    ]


def status_banco() -> dict:
    """Retorna informações sobre o banco local de sócios."""
    if not _DB_PATH.exists():
        return {"existe": False, "db_path": str(_DB_PATH)}
    conn = _get_conn()
    n = conn.execute("SELECT COUNT(*) FROM socios").fetchone()[0]
    periodo = conn.execute("SELECT valor FROM meta WHERE chave='periodo_indexado'").fetchone()
    size_mb = _DB_PATH.stat().st_size / 1024 / 1024
    conn.close()
    return {
        "existe": True,
        "db_path": str(_DB_PATH),
        "total_registros": n,
        "periodo_indexado": periodo[0] if periodo else None,
        "tamanho_mb": round(size_mb, 1),
    }
