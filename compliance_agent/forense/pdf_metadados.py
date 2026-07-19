# -*- coding: utf-8 -*-
"""Forense de PDF — metadados como "digital compartilhada" entre propostas concorrentes.

FUNDAMENTO: o robô ADELE (TCU) usa "mesmo IP entre licitantes" como sinal de conluio. Nosso proxy
PÚBLICO (sem log de plataforma) são os METADADOS dos PDFs das propostas: concorrentes "independentes"
cujos arquivos carregam o MESMO Author/Producer, ou foram criados no MESMO minuto, sugerem origem única
(mesma máquina/escritório). Alimenta o card J5 (digitais compartilhadas) — aqui só a camada de EXTRAÇÃO
e agrupamento determinístico; o juízo (âncora/score) fica no detector.

HONESTIDADE JFN (lição OCR no-op): dependência ausente NUNCA degrada em silêncio. Sem fitz (PyMuPDF)
e sem pypdf em runtime, `metadados_pdf` retorna None E loga warning "extrator de metadados INDISPONÍVEL".
Guard anti-FP: Producer genérico (Microsoft Print To PDF, iText, wkhtmltopdf, ...) é universal — sozinho
(sem Author) NÃO agrupa; só agrupa se o Author também bater não-vazio.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict

log = logging.getLogger(__name__)

# Producers/geradores GENÉRICOS (universais de mercado): coincidência SÓ deles não indica origem comum.
# Comparação por substring case-insensitive sobre o producer normalizado.
_PRODUCERS_GENERICOS = (
    "microsoft: print to pdf", "microsoft print to pdf", "microsoft word", "microsoft office",
    "itext", "wkhtmltopdf", "libreoffice", "openoffice", "ghostscript", "skia", "chromium", "chrome",
    "adobe", "acrobat", "distiller", "pdflatex", "reportlab", "foxit", "nitro", "wps",
    "google docs", "pdfcreator", "pymupdf", "mupdf", "cairo",
)


def _importar(nome: str):
    """Importa uma lib opcional; ausente → None (o chamador decide como degradar, sempre com warning)."""
    try:
        return __import__(nome)
    except Exception:  # noqa: BLE001 — lib ausente/quebrada = indisponível, nunca fatal aqui
        return None


def metadados_pdf(path) -> dict | None:
    """Extrai {author, producer, creator, creation, moddate} de um PDF (strings, '' se ausente).

    Extrator: fitz (PyMuPDF) preferido — já é a lib de OCR do repo —, pypdf como fallback.
    Retorna None se: (a) NENHUM extrator importável em runtime (warning "INDISPONÍVEL", nunca
    silencioso); ou (b) o arquivo não pôde ser lido como PDF (warning com o motivo)."""
    fitz = _importar("fitz")
    if fitz is not None:
        try:
            with fitz.open(str(path)) as doc:
                m = doc.metadata or {}
            return {
                "author": str(m.get("author") or "").strip(),
                "producer": str(m.get("producer") or "").strip(),
                "creator": str(m.get("creator") or "").strip(),
                "creation": str(m.get("creationDate") or "").strip(),
                "moddate": str(m.get("modDate") or "").strip(),
            }
        except Exception as e:  # noqa: BLE001 — PDF ilegível p/ fitz: tenta pypdf antes de desistir
            log.warning("pdf_metadados: fitz falhou em %s (%s) — tentando pypdf", path, str(e)[:80])

    pypdf = _importar("pypdf")
    if pypdf is not None:
        try:
            info = pypdf.PdfReader(str(path)).metadata or {}

            def _g(chave: str) -> str:
                return str(info.get(chave) or "").strip()

            return {
                "author": _g("/Author"),
                "producer": _g("/Producer"),
                "creator": _g("/Creator"),
                "creation": _g("/CreationDate"),
                "moddate": _g("/ModDate"),
            }
        except Exception as e:  # noqa: BLE001 — arquivo ilegível: degrada explícito
            log.warning("pdf_metadados: pypdf falhou em %s (%s) — metadados NÃO extraídos", path, str(e)[:80])
            return None

    if fitz is None:
        log.warning(
            "pdf_metadados: extrator de metadados INDISPONÍVEL (nem fitz/PyMuPDF nem pypdf importáveis) — "
            "%s NÃO avaliado; instale `uv pip install pymupdf` ou `pypdf`", path,
        )
    return None


def _producer_generico(producer_norm: str) -> bool:
    """True se o producer (normalizado lower/strip) é um gerador universal de mercado."""
    return any(t in producer_norm for t in _PRODUCERS_GENERICOS)


def _minuto_criacao(creation: str) -> str:
    """Chave YYYYMMDDHHMM (minuto de criação) a partir de 'D:20260719154530...' ou ISO. '' se indeterminável."""
    digitos = re.sub(r"\D", "", str(creation or ""))
    return digitos[:12] if len(digitos) >= 12 else ""


def mesma_origem(paths: list[str]) -> list[dict]:
    """Agrupa PDFs que compartilham origem provável: mesmo (producer+author) OU criação no MESMO minuto.

    Retorna [{grupo: [paths], campo_comum: 'producer+author'|'criacao_minuto', valor: str}].
    Guards anti-FP:
      • producer vazio nunca agrupa;
      • producer GENÉRICO (`_PRODUCERS_GENERICOS`) só agrupa se o author TAMBÉM bater não-vazio;
      • minuto de criação exige data completa (>=12 dígitos).
    PDFs sem metadados extraíveis (lib ausente/arquivo ilegível) ficam de fora — a indisponibilidade
    já foi logada por `metadados_pdf` (nunca silenciosa)."""
    metas: dict[str, dict] = {}
    for p in paths or []:
        m = metadados_pdf(p)
        if m is not None:
            metas[str(p)] = m

    grupos: list[dict] = []

    # 1) mesmo producer+author
    por_chave: dict[tuple, list[str]] = defaultdict(list)
    for p, m in metas.items():
        prod = m["producer"].strip().lower()
        auth = m["author"].strip().lower()
        if not prod:
            continue
        if _producer_generico(prod) and not auth:
            continue  # guard anti-FP: gerador universal sem autor não indica origem comum
        por_chave[(prod, auth)].append(p)
    for (prod, auth), ps in sorted(por_chave.items()):
        if len(ps) >= 2:
            grupos.append({"grupo": sorted(ps), "campo_comum": "producer+author", "valor": f"{prod}|{auth}"})

    # 2) criação no mesmo minuto
    por_minuto: dict[str, list[str]] = defaultdict(list)
    for p, m in metas.items():
        chave = _minuto_criacao(m["creation"])
        if chave:
            por_minuto[chave].append(p)
    for chave, ps in sorted(por_minuto.items()):
        if len(ps) >= 2:
            grupos.append({"grupo": sorted(ps), "campo_comum": "criacao_minuto", "valor": chave})

    return grupos
