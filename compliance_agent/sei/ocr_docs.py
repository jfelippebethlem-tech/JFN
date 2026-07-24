# -*- coding: utf-8 -*-
"""OCR de documentos DIGITALIZADOS do SEI (scan PDF / imagem) — helper STANDALONE.

Por que existe
--------------
Documentos do SEI podem ser DIGITALIZADOS (PDF-imagem / scan). Esses NÃO têm texto
extraível: a leitura via ``innerText`` do browser (ou via extração nativa de PDF) volta
vazia. Este módulo lê esses casos por OCR — degradando HONESTO: se a lib/binário de OCR
não estiver disponível, retorna "" e loga um aviso (NUNCA inventa texto).

Estratégia (LEVE — VM 2 vCPU / 7,8 GB / sem swap)
------------------------------------------------
1. PDF: extrai o texto NATIVO primeiro (PyMuPDF/``fitz`` se instalado; senão pdfminer.six).
   Se o texto for vazio/ínfimo (heurística ``eh_escaneado``) → é SCAN → renderiza as
   páginas em imagem (PyMuPDF, ou poppler ``pdftoppm`` via subprocess) e roda OCR
   (pytesseract). Limita a ``MAX_PAGINAS_OCR`` páginas para não estourar memória/CPU.
2. Imagem (png/jpg/...): OCR direto (pytesseract).

Lazy-import das libs PESADAS (fitz/pytesseract/cv2) DENTRO das funções: se faltar lib, o
``import compliance_agent.sei.ocr_docs`` continua funcionando (degrada na chamada).

Dependências
------------
- pytesseract + binário ``tesseract`` (apt install tesseract-ocr tesseract-ocr-por) — OCR.
- pdfminer.six (extração nativa) OU PyMuPDF/``fitz`` (extração + render, mais rápido).
- Para renderizar scan→imagem sem fitz: poppler-utils (``pdftoppm``) + Pillow.
- opcional: opencv-python-headless + numpy (pré-processamento, melhora OCR de scan ruim).
NÃO usar torch/easyocr (pesado demais p/ esta VM).

PONTO DE WIRING (NÃO feito aqui — só documentado)
------------------------------------------------
Em ``tools/sei_reader.py::ler_processo``, no loop ``for doc in dump["documentos"]`` que
monta ``conteudo_documentos`` (~linha 216), quando o ``innerText`` do doc vier vazio/curto
(``not t or len(t) <= 50``) o doc é provavelmente um SCAN. Wiring sugerido:

    from compliance_agent.sei.ocr_docs import ocr_documento
    ...
    if not t or len(t) <= 50:
        # baixar o PDF/imagem do doc (mesma sessão/cookies do Playwright) e dar OCR
        pdf_bytes = await _baixar_doc(pg, doc["url"])   # helper a criar no sei_reader
        texto_ocr = ocr_documento(pdf_bytes)             # síncrono; rode em executor se preciso
        if texto_ocr:
            docs_txt.append({"doc": (doc.get("texto") or "")[:80],
                             "conteudo": texto_ocr, "_ocr": True})

(OCR é síncrono e CPU-bound; num contexto async convém envolver em
``loop.run_in_executor`` para não bloquear o event loop.)
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, Union

log = logging.getLogger(__name__)

Fonte = Union[str, Path, bytes]

# Limite de páginas para OCR (proteção de CPU/memória nesta VM sem swap).
# CONTROLE POR ORÇAMENTO DE TEMPO (não por nº de páginas). O OCR de scan roda página a
# página, acumula cada uma, e PARA LIMPO quando o orçamento acaba — declarando quantas
# páginas ficaram. Sem acoplamento cap×timeout (a fonte de erro do design antigo): um
# único botão (OCR_BUDGET_S) manda, nada é perdido, nada é cancelado no meio. O cap de
# páginas vira só uma trava de segurança anti-runaway (memória já é bounded pelo page-a-page).
OCR_BUDGET_S = int(os.environ.get("OCR_BUDGET_S", "300"))
MAX_PAGINAS_OCR = int(os.environ.get("MAX_PAGINAS_OCR", "300"))   # trava anti-runaway
# Abaixo de ~40 chars úteis por página, consideramos a página um scan (sem texto nativo).
MIN_CHARS_POR_PAGINA = 40
# Abaixo disso o OCR da página é "fraco" e vale reconferir sem pré-processamento.
_MIN_OCR_UTIL = 60


def eh_escaneado(texto_extraido: str, n_paginas: int) -> bool:
    """Heurística HONESTA: o documento parece um scan (sem texto nativo)?

    Considera scan quando a densidade de caracteres ÚTEIS por página fica abaixo de
    ``MIN_CHARS_POR_PAGINA``. Texto vazio/só-espaço → scan. ``n_paginas`` é saneado para
    >= 1 (evita divisão por zero e trata "documento de página única").
    """
    n = max(int(n_paginas or 0), 1)
    uteis = len((texto_extraido or "").strip())
    return (uteis / n) < MIN_CHARS_POR_PAGINA


# --------------------------------------------------------------------------- #
# Infra interna (lazy-import das libs pesadas)
# --------------------------------------------------------------------------- #
def _carregar_bytes(fonte: Fonte) -> tuple[Optional[bytes], Optional[str]]:
    """Normaliza ``fonte`` para (bytes, sufixo). Sufixo só quando vem de caminho."""
    if isinstance(fonte, bytes):
        return fonte, None
    if isinstance(fonte, (str, Path)):
        p = Path(fonte)
        if not p.exists():
            log.warning("ocr_documento: arquivo não encontrado: %s", fonte)
            return None, None
        return p.read_bytes(), p.suffix.lower()
    log.warning("ocr_documento: tipo de fonte não suportado: %s", type(fonte))
    return None, None


def _eh_pdf(dados: bytes, sufixo: Optional[str]) -> bool:
    if sufixo == ".pdf":
        return True
    if sufixo in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}:
        return False
    # Sem sufixo confiável (bytes): assina pelo magic number do PDF.
    return dados[:5] == b"%PDF-"


def _tesseract_ok() -> bool:
    """pytesseract importável E binário tesseract no PATH?"""
    try:
        import pytesseract  # noqa: F401
    except Exception as exc:  # pragma: no cover - ambiente sem a lib
        log.warning("ocr_documento: pytesseract indisponível (%s) — OCR desabilitado", exc)
        return False
    if shutil.which("tesseract") is None:
        log.warning("ocr_documento: binário 'tesseract' não está no PATH — OCR desabilitado")
        return False
    return True


def _preprocess_para_ocr(img):
    """Pré-processa imagem (grayscale + threshold adaptativo) p/ melhorar OCR de scan.

    Reusa a ideia do ``compliance_agent/captcha_solver.py``. Se opencv/numpy faltarem,
    devolve a imagem original (OCR ainda funciona, só menos robusto).
    """
    try:
        import cv2
        import numpy as np
    except Exception:
        return img
    arr = np.array(img)
    if arr.ndim == 3:
        arr = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    arr = cv2.adaptiveThreshold(
        arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
    )
    return arr


def _ocr_pil(img, lang: str) -> str:
    """OCR de UMA imagem PIL/ndarray via pytesseract (assume _tesseract_ok já checado).

    O pré-processamento AJUDA em scan sujo e ATRAPALHA em scan claro: numa NF real
    (2480×3508) o threshold adaptativo levou 2.272 caracteres a ZERO. Por isso o
    resultado é o MELHOR DOS DOIS — mesmo idioma de `ocr_documento`, que já devolve
    "ocr or texto_nativo". A 2ª passada só roda quando a 1ª veio fraca, então o
    custo extra é pago apenas nos casos em que o pré-processamento falhou.
    """
    import pytesseract

    alvo = _preprocess_para_ocr(img)
    try:
        saida = pytesseract.image_to_string(alvo, lang=lang) or ""
        if len(saida.strip()) < _MIN_OCR_UTIL and alvo is not img:
            cru = pytesseract.image_to_string(img, lang=lang) or ""
            if len(cru.strip()) > len(saida.strip()):
                log.debug("ocr: pré-processamento piorou (%d → %d chars) — usando original",
                          len(saida.strip()), len(cru.strip()))
                return cru
        return saida
    except pytesseract.TesseractError as exc:
        # ex.: traineddata do idioma ausente → tenta o default ('eng') uma vez.
        if lang != "eng":
            log.warning("ocr_documento: idioma '%s' falhou (%s) — tentando 'eng'", lang, exc)
            try:
                return pytesseract.image_to_string(alvo) or ""
            except Exception as exc2:  # pragma: no cover
                log.warning("ocr_documento: OCR falhou também em 'eng' (%s)", exc2)
                return ""
        log.warning("ocr_documento: OCR falhou (%s)", exc)
        return ""


# --------------------------------------------------------------------------- #
# Extração de PDF
# --------------------------------------------------------------------------- #
def _texto_nativo_pdf(dados: bytes) -> tuple[str, int]:
    """Texto NATIVO do PDF + nº de páginas. Tenta fitz; cai p/ pdfminer; senão ('', 0)."""
    # 1) PyMuPDF / fitz (rápido) — opcional.
    try:
        import fitz  # PyMuPDF

        with fitz.open(stream=dados, filetype="pdf") as doc:
            n = doc.page_count
            partes = [doc.load_page(i).get_text() or "" for i in range(n)]
        return "\n".join(partes), n
    except ImportError as exc:
        log.warning("PyMuPDF (fitz) ausente — extração de texto PDF degrada silenciosamente: %s", exc)
    except Exception as exc:
        log.warning("ocr_documento: fitz falhou ao ler PDF (%s) — tentando pdfminer", exc)

    # 2) pdfminer.six (puro Python) — fallback.
    try:
        from io import BytesIO

        from pdfminer.high_level import extract_text
        from pdfminer.pdfpage import PDFPage

        texto = extract_text(BytesIO(dados)) or ""
        n = sum(1 for _ in PDFPage.get_pages(BytesIO(dados)))
        return texto, max(n, 1)
    except ImportError:
        log.warning("ocr_documento: nem fitz nem pdfminer disponíveis — sem extração nativa de PDF")
        return "", 0
    except Exception as exc:
        log.warning("ocr_documento: pdfminer falhou ao ler PDF (%s)", exc)
        return "", 0


def _iter_paginas_pdf(dados: bytes, max_paginas: int):
    """Rende as páginas UMA POR VEZ (memória bounded). fitz preferido; se faltar,
    cai para _render_paginas_pdf (lista) e itera sobre ela (mesma cobertura)."""
    try:
        import fitz
        from PIL import Image
        with fitz.open(stream=dados, filetype="pdf") as doc:
            for i in range(min(doc.page_count, max_paginas)):
                pix = doc.load_page(i).get_pixmap(dpi=200)
                yield Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return
    except ImportError:
        pass
    except (RuntimeError, ValueError, OSError, TypeError) as exc:
        log.warning("ocr_documento: render página-a-página via fitz falhou (%s) — poppler", exc)
    yield from _render_paginas_pdf(dados, max_paginas)


def _render_paginas_pdf(dados: bytes, max_paginas: int):
    """Renderiza páginas do PDF em imagens PIL. Tenta fitz; cai p/ poppler (pdftoppm).

    Retorna lista de imagens PIL (vazia se não houver como renderizar).
    """
    imagens = []

    # 1) fitz: render direto em pixmap → PIL.
    try:
        import fitz
        from PIL import Image

        with fitz.open(stream=dados, filetype="pdf") as doc:
            for i in range(min(doc.page_count, max_paginas)):
                pix = doc.load_page(i).get_pixmap(dpi=200)
                imagens.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        return imagens
    except ImportError as exc:
        log.warning("PyMuPDF (fitz) ausente — rasterização p/ OCR degrada silenciosamente: %s", exc)
    except Exception as exc:
        log.warning("ocr_documento: render via fitz falhou (%s) — tentando poppler", exc)

    # 2) poppler: pdftoppm via subprocess + Pillow.
    if shutil.which("pdftoppm") is None:
        log.warning(
            "ocr_documento: scan detectado mas sem renderizador "
            "(instale PyMuPDF OU poppler-utils) — OCR de PDF-imagem indisponível"
        )
        return imagens
    try:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "in.pdf"
            pdf_path.write_bytes(dados)
            prefixo = Path(tmp) / "pg"
            subprocess.run(
                ["pdftoppm", "-r", "200", "-png", "-l", str(max_paginas),
                 str(pdf_path), str(prefixo)],
                check=True, capture_output=True, timeout=120,
            )
            for png in sorted(Path(tmp).glob("pg*.png")):
                imagens.append(Image.open(png).convert("RGB"))
        return imagens
    except Exception as exc:
        log.warning("ocr_documento: render via poppler falhou (%s)", exc)
        return imagens


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #
def ocr_documento(fonte: Fonte, *, tipo: Optional[str] = None, lang: str = "por") -> str:
    """Lê um documento do SEI (PDF ou imagem), usando OCR quando for um SCAN.

    Parâmetros
    ----------
    fonte : str | Path | bytes
        Caminho de arquivo OU bytes do documento (PDF ou imagem).
    tipo : {"pdf", "imagem", None}, opcional
        Força o tratamento. ``None`` → detecta por sufixo/magic number.
    lang : str
        Idioma do tesseract (default "por"; cai p/ "eng" se o traineddata faltar).

    Retorno
    -------
    str
        Texto extraído (nativo OU via OCR). DEGRADA HONESTO: "" se a fonte for inválida ou
        se as libs de OCR estiverem indisponíveis (e loga o motivo). NUNCA inventa texto.
    """
    dados, sufixo = _carregar_bytes(fonte)
    if not dados:
        return ""

    if tipo == "imagem":
        eh_pdf = False
    elif tipo == "pdf":
        eh_pdf = True
    else:
        eh_pdf = _eh_pdf(dados, sufixo)

    # --- Caminho IMAGEM: OCR direto ---
    if not eh_pdf:
        if not _tesseract_ok():
            return ""
        try:
            from io import BytesIO

            from PIL import Image

            img = Image.open(BytesIO(dados))
        except Exception as exc:
            log.warning("ocr_documento: não consegui abrir a imagem (%s)", exc)
            return ""
        return _ocr_pil(img, lang).strip()

    # --- Caminho PDF: texto nativo primeiro ---
    texto, n_pag = _texto_nativo_pdf(dados)
    if texto.strip() and not eh_escaneado(texto, n_pag):
        return texto.strip()

    # Vazio/ínfimo → provável SCAN → render + OCR.
    if not _tesseract_ok():
        return texto.strip()  # sem OCR: devolve o pouco que houver (honesto)

    partes, n_feitas = _ocr_ate_orcamento(
        _iter_paginas_pdf(dados, MAX_PAGINAS_OCR), lang, OCR_BUDGET_S)
    if not partes:
        return texto.strip()
    ocr = _texto_ocr_com_ressalva(partes, n_pag, n_feitas)
    # Devolve o melhor dos dois: o OCR, ou o texto nativo se o OCR vier vazio.
    return ocr or texto.strip()


def _ocr_ate_orcamento(imagens, lang: str, budget_s: int):
    """OCR das páginas (iterável de imagens PIL) até o ORÇAMENTO DE TEMPO acabar.
    Para LIMPO ENTRE páginas — nunca no meio de uma, então nada é perdido nem cancelado.
    Sempre faz ao menos a 1ª página (para não devolver vazio por orçamento zero).
    Retorna (lista de textos, nº de páginas feitas)."""
    partes, n = [], 0
    t0 = time.monotonic()
    for img in imagens:
        if n and time.monotonic() - t0 > budget_s:
            break
        partes.append(_ocr_pil(img, lang))
        n += 1
    return partes, n


def _texto_ocr_com_ressalva(partes: list, n_pag: int, n_feitas: int) -> str:
    """Junta o OCR das páginas FEITAS e, se sobraram páginas (por tempo/trava), DECLARA
    quantas ficaram — INDISPONÍVEL ≠ 0, nunca some com página em silêncio. A ressalva
    depende só de 'quantas fiz vs total', não do PORQUÊ parei (tempo ou trava)."""
    ocr = "\n".join(p for p in partes if p).strip()
    if ocr and n_pag and n_feitas < n_pag:
        ocr += (f"\n\n[⚠️ OCR PARCIAL: transcritas {n_feitas} de {n_pag} páginas deste "
                "documento escaneado (limite de tempo de processamento). As demais NÃO "
                "foram lidas; reprocessar com OCR_BUDGET_S maior se necessário.]")
    return ocr
