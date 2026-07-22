# -*- coding: utf-8 -*-
"""atas_julgamento — coleta as ATAS DE JULGAMENTO/SESSÃO reais do PNCP (onde vivem as PERDEDORAS).

O `/resultados` estruturado do PNCP só devolve o VENCEDOR (ordem=1); as licitantes perdedoras
(inabilitadas/desclassificadas) só existem no texto da ata de sessão / mapa de lances, publicada
como documento (arquivo) da contratação — em geral PDF, com frequência ESCANEADO (sem camada de
texto). Este coletor:

  1. varre certames de modalidade COMPETITIVA (concorrência/pregão/dispensa eletrônica com disputa);
  2. baixa só os documentos cujo título/tipo tem marcador de ATA/JULGAMENTO/SESSÃO/RESULTADO;
  3. extrai o texto (pypdf; se vier vazio = PDF escaneado → fallback OCR PyMuPDF+tesseract-por);
  4. guarda em `ata_documento` só o que tem marcador REAL de ata + ≥2 CNPJs (não boilerplate).

A tabela alimenta `rodizio_grafo.coletar_atas_do_corpus` → `conluio_qsa`/rodízio. Determinístico;
educado com a API (serial + pausa). OCR é CARO (2 vCPU) — gated: 1 doc/certame, poucas páginas,
serial; rodar em sweep de background com `limite` modesto."""
from __future__ import annotations

import asyncio
import logging
import re
import sqlite3

import httpx

from compliance_agent.collectors.pncp import _get_pncp, _parse_id_pncp, _texto_de_pdf

logger = logging.getLogger(__name__)

# título/tipo de documento que sinaliza ata de julgamento (não é edital/TR/DFD)
_RX_ATA_TITULO = re.compile(
    r"\bata\b|julgamento|sess[aã]o|resultado|mapa\s*d?e?\s*lanc|habilita[çc]|classifica[çc]", re.I)
# marcador FORTE no CONTEÚDO (mesma régua do coletor_ata) — evita edital-boilerplate. NÃO usa
# 'inabilitad'/'declarada vencedora' isolados: aparecem no próprio edital ("será inabilitado o
# licitante que…") e gerariam falso positivo. Só frases inequívocas de ata de sessão.
_RX_ATA_CONTEUDO = re.compile(
    r"ata\s+d[ae]\s+(?:sess|reuni|julgamento)|sess[ãa]o\s+p[úu]blica|"
    r"julgamento\s+das?\s+propostas?|mapa\s+de\s+lances|resultado\s+d[ao]\s+julgamento|"
    r"reuni[ãa]o\s+de\s+julgamento|encerrada\s+a\s+sess[ãa]o", re.I)
_RX_CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")

_DDL = """
CREATE TABLE IF NOT EXISTS ata_documento (
    certame       TEXT NOT NULL,
    orgao_cnpj    TEXT,
    titulo        TEXT,
    fonte_texto   TEXT,              -- 'pdf' | 'ocr'
    n_cnpj        INTEGER,
    texto         TEXT,
    coletado_em   TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (certame, titulo)
)"""

# concorrência(4/5) e pregão(6/7) — modalidades com disputa e ata de sessão. Dispensa (8/12)
# raramente publica ata multi-licitante; fica fora p/ não gastar chamadas de /arquivos à toa.
_MODALIDADES_COMPETITIVAS = (4, 5, 6, 7)


def init_schema(con: sqlite3.Connection) -> None:
    con.execute(_DDL)
    con.execute("CREATE INDEX IF NOT EXISTS ix_ata_certame ON ata_documento(certame)")
    con.commit()


def _ocr_pdf(blob: bytes, max_paginas: int = 8, dpi: int = 200) -> str:
    """OCR de PDF escaneado (PyMuPDF renderiza → tesseract-por). CARO — só quando o pypdf falha."""
    try:
        import io

        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        logger.warning("OCR indisponível (dep faltando): %s", exc)
        return ""
    try:
        doc = fitz.open(stream=blob, filetype="pdf")
    except Exception as exc:
        logger.debug("PDF ilegível p/ OCR: %s", exc)
        return ""
    partes = []
    try:
        for pg in doc[:max_paginas]:
            pix = pg.get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            partes.append(pytesseract.image_to_string(img, lang="por"))
    except Exception as exc:
        logger.debug("OCR parcial: %s", exc)
    finally:
        doc.close()
    return "\n".join(partes)


def _extrair_texto_ata(blob: bytes, com_ocr: bool) -> tuple[str, str]:
    """(texto, fonte). pypdf primeiro; se vier pobre (<400 chars = escaneado) e com_ocr → OCR."""
    txt = _texto_de_pdf(blob)
    if len(txt.strip()) >= 400:
        return txt, "pdf"
    if com_ocr and blob[:4] == b"%PDF":
        ocr = _ocr_pdf(blob)
        if len(ocr.strip()) > len(txt.strip()):
            return ocr, "ocr"
    return txt, "pdf"


async def _certames_pendentes(con, limite: int) -> list[tuple[str, str]]:
    """Certames competitivos com vencedor conhecido e SEM ata coletada ainda.

    PRIORIZAÇÃO (2026-07-22): certames com índice ALTO/EXTREMO primeiro — é onde a família
    certame_ata mais muda a conclusão — e SÓ DEPOIS os recentes. Certame de 2026 recém-publicado
    quase nunca tem ata anexada ainda (yield 0/100 medido); começar pelos quentes rende mais."""
    init_schema(con)
    marc = ",".join("?" * len(_MODALIDADES_COMPETITIVAS))
    rows = con.execute(
        f"SELECT DISTINCT p.certame, p.orgao_cnpj, "
        f"  CASE ci.faixa WHEN 'EXTREMO' THEN 0 WHEN 'ALTO' THEN 1 ELSE 2 END AS prio "
        f"FROM pncp_resultado p LEFT JOIN certame_indice ci ON ci.certame = p.certame "
        f"WHERE p.modalidade IN ({marc}) AND p.ordem_classificacao=1 AND p.certame IS NOT NULL "
        f"AND p.certame NOT IN (SELECT certame FROM ata_documento) "
        f"ORDER BY prio, p.data_pub DESC LIMIT ?", (*_MODALIDADES_COMPETITIVAS, limite)).fetchall()
    return [(r[0], r[1]) for r in rows]


async def coletar_atas_julgamento(con, limite: int = 200, com_ocr: bool = True,
                                  pausa: float = 0.3) -> dict:
    """Baixa e grava as atas de julgamento dos próximos `limite` certames competitivos pendentes.
    Só grava o documento com marcador REAL de ata no conteúdo e ≥2 CNPJs (perdedora possível)."""
    pend = await _certames_pendentes(con, limite)
    tot = {"certames": 0, "com_arquivo_ata": 0, "atas_gravadas": 0, "por_ocr": 0, "sem_perdedora": 0}
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for idp, ocnpj in pend:
            tot["certames"] += 1
            pr = _parse_id_pncp(idp)
            if not pr:
                continue
            cnpj, ano, seq = pr
            meta = await _get_pncp(f"/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos", {})
            arqs = meta if isinstance(meta, list) else (meta or {}).get("data", []) if meta else []
            gravou_algum = False
            for a in (arqs or []):
                tit = a.get("titulo") or ""
                tipo = a.get("tipoDocumentoNome") or ""
                if not (_RX_ATA_TITULO.search(tit) or _RX_ATA_TITULO.search(tipo)):
                    continue
                url = a.get("url") or a.get("uri")
                if not url:
                    continue
                if not gravou_algum:
                    tot["com_arquivo_ata"] += 1
                    gravou_algum = True
                try:
                    d = await client.get(url, headers={"User-Agent": "JFN-Compliance/2.0"})
                    blob = d.content if d.status_code == 200 else b""
                except httpx.HTTPError:
                    blob = b""
                if not blob:
                    continue
                texto, fonte = _extrair_texto_ata(blob, com_ocr)
                if not _RX_ATA_CONTEUDO.search(texto):
                    continue                       # sem marcador real → não é ata (ou OCR falhou)
                n_cnpj = len(set(re.sub(r"\D", "", m.group(0)) for m in _RX_CNPJ.finditer(texto)))
                if n_cnpj < 2:
                    tot["sem_perdedora"] += 1
                    continue                       # <2 CNPJs → sem disputa registrável
                con.execute(
                    "INSERT OR REPLACE INTO ata_documento "
                    "(certame, orgao_cnpj, titulo, fonte_texto, n_cnpj, texto) VALUES (?,?,?,?,?,?)",
                    (idp, ocnpj, tit[:200], fonte, n_cnpj, texto[:400_000]))
                tot["atas_gravadas"] += 1
                if fonte == "ocr":
                    tot["por_ocr"] += 1
                await asyncio.sleep(pausa)
            con.commit()
            await asyncio.sleep(pausa)
    return tot


if __name__ == "__main__":
    import sys

    _lim = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    _con = sqlite3.connect("data/compliance.db", timeout=60)
    _con.execute("PRAGMA busy_timeout=60000")
    _r = asyncio.run(coletar_atas_julgamento(_con, limite=_lim))
    _con.close()
    print(_r)
