# -*- coding: utf-8 -*-
"""Captura a ÍNTEGRA dos contratos do Município do Rio pelo PNCP.

Por que o PNCP: a pesquisa pública do SEI municipal indexa um único tipo de processo (cadastro
de representação de PJ). Contratação e execução NÃO estão lá — medido em 2026-09-02 com controle
positivo na mesma execução: 0/9 protocolos de contratação, 1/1 no controle. Ver
``vault/aprendizados/indice-publico-sei-rio-nao-cobre-contratacao.md``.

O PNCP publica o PDF ASSINADO do contrato, e é dele que sai o nº do processo SEI.RIO — com
procedência muito melhor que raspar o campo `objeto` do registro.

Ordem por VALOR, nunca por posição na tabela: corte por posição já produziu ficha dizendo
"não consta OB" com 30 OBs nos autos.

Single-pass: processa um lote e termina. Sem laço que se relance.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import sqlite3

from compliance_agent.collectors.pncp import baixar_arquivos_contrato, processos_sei_no_texto

logger = logging.getLogger(__name__)

DB = "data/compliance.db"
CNPJ_MUNICIPIO = "42498733000148"

DDL = """
CREATE TABLE IF NOT EXISTS contrato_integra (
    numero_controle_pncp VARCHAR PRIMARY KEY,
    orgao_cnpj      VARCHAR,
    ano             VARCHAR,
    seq             VARCHAR,
    fornecedor_nome VARCHAR,
    valor_global    DOUBLE,
    titulo          VARCHAR,
    url             VARCHAR,
    n_chars         INTEGER,
    texto           VARCHAR,
    processos_sei   VARCHAR,   -- JSON: nºs SEI.RIO citados no documento assinado
    estado          VARCHAR,   -- TEXTO_OK | PDF_IMAGEM | SEM_ARQUIVO
    coletado_em     TIMESTAMP
)
"""

# PDF escaneado devolve só quebras de linha. Sem este piso, 11 caracteres de '\n' contam como
# "contrato capturado" — e documento em branco tratado como lido já custou caro nesta casa.
# O piso é frouxo de propósito: serve para separar imagem de texto, não para julgar conteúdo.
MIN_CHARS_TEXTO = 200


def classificar(n_chars: int, teve_arquivo: bool) -> str:
    if not teve_arquivo:
        return "SEM_ARQUIVO"
    return "TEXTO_OK" if n_chars >= MIN_CHARS_TEXTO else "PDF_IMAGEM"


def _parse_controle(numero: str) -> tuple[str, str, str] | None:
    """'42498733000148-2-000708/2026' -> (cnpj, ano, seq-sem-zeros). None se não casar."""
    try:
        esq, ano = numero.split("/")
        cnpj, _tipo, seq = esq.split("-")
    except ValueError:
        return None
    return cnpj, ano, str(int(seq))


def _pendentes(con, limite: int) -> list[tuple]:
    return con.execute(
        """
        SELECT c.numero_controle_pncp, c.fornecedor_nome,
               CAST(c.valor_global AS REAL) v   -- 0 nas linhas deslocadas; elas caem no fim
        FROM pcrj_contratos c
        LEFT JOIN contrato_integra i
               ON i.numero_controle_pncp = c.numero_controle_pncp
        WHERE c.orgao_cnpj = ?
          AND c.numero_controle_pncp GLOB '*-*-*/[0-9][0-9][0-9][0-9]'
          AND i.numero_controle_pncp IS NULL
        ORDER BY v DESC
        LIMIT ?
        """,
        [CNPJ_MUNICIPIO, limite],
    ).fetchall()


async def _uma(con, numero: str, fornecedor: str | None, valor) -> int:
    partes = _parse_controle(numero)
    if not partes:
        logger.warning("numero_controle_pncp fora do formato: %s", numero)
        return 0
    cnpj, ano, seq = partes
    arquivos = await baixar_arquivos_contrato(cnpj, ano, seq)
    if not arquivos:
        # grava a AUSÊNCIA: sem isso o sweep repete o mesmo contrato para sempre, e
        # "sem arquivo publicado" é fato — não é o mesmo que "ainda não tentei".
        con.execute(
            "INSERT OR REPLACE INTO contrato_integra VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [numero, cnpj, ano, seq, fornecedor, valor, None, None, 0, None,
             "[]", classificar(0, False), datetime.now(timezone.utc).isoformat()],
        )
        con.commit()
        return 0
    melhor = max(arquivos, key=lambda a: a["n_chars"])
    seis = processos_sei_no_texto(melhor["texto"])
    con.execute(
        "INSERT OR REPLACE INTO contrato_integra VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [numero, cnpj, ano, seq, fornecedor, valor, melhor["titulo"], melhor["url"],
         melhor["n_chars"], melhor["texto"], json.dumps(seis),
         classificar(melhor["n_chars"], True), datetime.now(timezone.utc).isoformat()],
    )
    con.commit()
    return melhor["n_chars"]


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=10, help="contratos por passada")
    ap.add_argument("--segundos", type=int, default=240, help="teto de tempo desta passada")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # sqlite3 nativo, não DuckDB: `pcrj_contratos` tem linhas de outros entes com colunas
    # DESLOCADAS (valor_global contendo razão social) e o scanner do DuckDB falha ao LER a
    # coluna, antes de qualquer cast. A tipagem dinâmica do sqlite3 lê sem tropeçar — e ainda
    # suporta o INSERT OR REPLACE que o scanner não implementa. A origem do deslocamento é
    # dívida separada, não corrigida aqui.
    con = sqlite3.connect(DB)
    try:
        con.execute(DDL)
        alvos = _pendentes(con, a.limite)
        logger.info("%d contrato(s) pendente(s) nesta passada", len(alvos))
        t0, com_texto, com_sei = time.monotonic(), 0, 0
        for numero, fornecedor, valor in alvos:
            if time.monotonic() - t0 > a.segundos:
                logger.info("teto de tempo atingido — encerrando a passada")
                break
            n = await _uma(con, numero, fornecedor, valor)
            seis = json.loads(con.execute(
                "SELECT processos_sei FROM contrato_integra WHERE numero_controle_pncp = ?",
                [numero]).fetchone()[0] or "[]")
            if n >= MIN_CHARS_TEXTO:
                com_texto += 1
            if seis:
                com_sei += 1
            logger.info("  %s  %-26s %8d chars  SEI=%s",
                        numero, (fornecedor or "")[:26], n, seis or "—")
        con.commit()
        total = con.execute("SELECT count(*) FROM contrato_integra").fetchone()[0]
        # o placar diz o que FOI LIDO, não o que foi baixado: PDF de imagem não é captura
        por_estado = dict(con.execute(
            "SELECT estado, count(*) FROM contrato_integra GROUP BY 1").fetchall())
        logger.info("\npassada: %d com texto util, %d citando processo SEI", com_texto, com_sei)
        logger.info("acervo %d: %s", total, por_estado)
    finally:
        con.close()


if __name__ == "__main__":
    asyncio.run(main())
