# -*- coding: utf-8 -*-
"""OCR dos contratos do Município que vieram como PDF de imagem (estado PDF_IMAGEM).

Medido em 2026-09-02: 35% dos contratos que o Município publica no PNCP são PDF escaneado,
sem camada de texto — publicados, porém não pesquisáveis. Sem OCR eles ficam fora de toda
análise, e "não achei irregularidade" num documento que nunca foi lido é conclusão falsa.

Reusa ``_ocr_pdf`` de collectors.atas_julgamento (PyMuPDF + tesseract-por). Uma definição,
dois usuários — não se copia a função.

CARO: OCR é pesado nesta VM de 2 vCPU. Single-pass, lote pequeno, guarda de carga no chamador.
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone

import httpx

from compliance_agent.collectors.atas_julgamento import _ocr_pdf
from compliance_agent.collectors.pncp import processos_sei_no_texto

logger = logging.getLogger(__name__)
DB = "data/compliance.db"
# mesmo piso do sweep: abaixo disso o OCR não produziu texto utilizável (uma definição só
# faria sentido num módulo comum; aqui o valor é importado para não divergir)
from tools.sweep_integra_contratos_pcrj import MIN_CHARS_TEXTO  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=5)
    ap.add_argument("--segundos", type=int, default=240)
    ap.add_argument("--paginas", type=int, default=8, help="páginas por PDF (OCR é caro)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    con = sqlite3.connect(DB)
    try:
        con.execute("ALTER TABLE contrato_integra ADD COLUMN fonte_texto VARCHAR")
    except sqlite3.OperationalError:
        pass  # coluna já existe — o ALTER do sqlite não tem IF NOT EXISTS
    try:
        alvos = con.execute(
            """SELECT numero_controle_pncp, fornecedor_nome, url
               FROM contrato_integra
               WHERE estado = 'PDF_IMAGEM' AND url IS NOT NULL
                 AND (fonte_texto IS NULL OR fonte_texto <> 'ocr')
               ORDER BY CAST(valor_global AS REAL) DESC
               LIMIT ?""", [a.limite]).fetchall()
        logger.info("%d PDF(s) de imagem nesta passada", len(alvos))
        t0, ok = time.monotonic(), 0
        with httpx.Client(timeout=180, follow_redirects=True,
                          headers={"User-Agent": "JFN-Compliance/2.0"}) as cli:
            for numero, fornecedor, url in alvos:
                if time.monotonic() - t0 > a.segundos:
                    logger.info("teto de tempo — encerrando a passada")
                    break
                try:
                    blob = cli.get(url).content
                except httpx.HTTPError as exc:
                    logger.warning("  %s: download falhou: %s", numero, exc)
                    continue
                texto = _ocr_pdf(blob, max_paginas=a.paginas)
                seis = processos_sei_no_texto(texto)
                # estado só muda se o OCR de fato produziu texto — senão continua PDF_IMAGEM,
                # que é a verdade: baixado, tentado, ilegível.
                estado = "TEXTO_OK" if len(texto) >= MIN_CHARS_TEXTO else "PDF_IMAGEM"
                con.execute(
                    """UPDATE contrato_integra
                       SET texto = ?, n_chars = ?, processos_sei = ?, estado = ?,
                           fonte_texto = 'ocr', coletado_em = ?
                       WHERE numero_controle_pncp = ?""",
                    [texto, len(texto), json.dumps(seis), estado,
                     datetime.now(timezone.utc).isoformat(), numero])
                con.commit()
                if estado == "TEXTO_OK":
                    ok += 1
                logger.info("  %s  %-26s %7d chars  %-11s SEI=%s",
                            numero, (fornecedor or "")[:26], len(texto), estado, seis or "—")
        por = dict(con.execute(
            "SELECT estado, count(*) FROM contrato_integra GROUP BY 1").fetchall())
        logger.info("\npassada: %d recuperado(s) pelo OCR · acervo: %s", ok, por)
    finally:
        con.close()


if __name__ == "__main__":
    main()
