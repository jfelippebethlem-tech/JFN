from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import pytesseract
import requests
from PIL import Image, ImageFilter

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
TMP = Path("data/tmp/captcha_solver")
TMP.mkdir(parents=True, exist_ok=True)


def _download(url: str, session: Optional[requests.Session] = None) -> bytes:
    sess = session or requests.Session()
    r = sess.get(url, timeout=30)
    r.raise_for_status()
    return r.content


def _save(img: np.ndarray, name: str) -> Path:
    p = TMP / name
    cv2.imwrite(str(p), img)
    return p


def solve_captcha(
    source,
    *,
    lang: str = "eng",
    config: str = "--psm 7 -c tessedit_char_whitelist=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
) -> str:
    """Aceita URL, bytes, Path ou ndarray. Retorna o texto reconhecido."""
    if isinstance(source, (str, Path)):
        p = Path(source)
        if not p.exists():
            raise FileNotFoundError(source)
        img = cv2.imread(str(p))
        base = p.stem
    elif isinstance(source, (bytes, bytearray)):
        img = cv2.imdecode(np.frombuffer(source, np.uint8), cv2.IMREAD_COLOR)
        base = "bytes"
    elif isinstance(source, np.ndarray):
        img = source
        base = "ndarray"
    else:
        raise TypeError(f"Fonte não suportada: {type(source)}")

    if img is None:
        return ""

    candidates: list[str] = []

    # Variante 1: pipeline guloso (Simple-deCAPTCHA-style)
    try:
        img1 = _pipeline_v1(img)
        _save(img1, f"{base}_v1.png")
        t1 = pytesseract.image_to_string(img1, lang=lang, config=config)
        t1 = "".join(ch for ch in t1 if ch.isalnum()).strip()
        if t1:
            candidates.append(t1)
    except Exception:
        pass

    # Variante 2: pipeline otimizado para texto contínuo
    try:
        img2 = _pipeline_v2(img)
        _save(img2, f"{base}_v2.png")
        t2 = pytesseract.image_to_string(img2, lang=lang, config=config)
        t2 = "".join(ch for ch in t2 if ch.isalnum()).strip()
        if t2:
            candidates.append(t2)
    except Exception:
        pass

    # Variante 3: OCR direto, sem pré-processamento
    try:
        img3 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        _save(img3, f"{base}_v3.png")
        t3 = pytesseract.image_to_string(img3, lang=lang, config=config)
        t3 = "".join(ch for ch in t3 if ch.isalnum()).strip()
        if t3:
            candidates.append(t3)
    except Exception:
        pass

    if not candidates:
        return ""
    return max(candidates, key=len)


def solve_captcha_url(url: str, session: Optional[requests.Session] = None) -> str:
    data = _download(url, session=session)
    return solve_captcha(data)


def _pipeline_v1(img: np.ndarray) -> np.ndarray:
    """Pipeline baseada no Simple-deCAPTCHA: resize, Otsu, close, expand, inverte."""
    h, w = img.shape[:2]
    img = cv2.resize(img, (w * 10, h * 10), interpolation=cv2.INTER_LINEAR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = np.ones((2, 2), np.uint8)
    closing = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel)
    bordered = cv2.copyMakeBorder(closing, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    inv = cv2.bitwise_not(bordered)
    return cv2.cvtColor(inv, cv2.COLOR_GRAY2BGR)


def _pipeline_v2(img: np.ndarray) -> np.ndarray:
    """Pipeline otimizada para textos curtos alfanuméricos."""
    small = cv2.resize(img, (220, 80), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if len(small.shape) == 3 else small
    blur = cv2.medianBlur(gray, 3)
    bin_img = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    return cv2.cvtColor(bin_img, cv2.COLOR_GRAY2BGR)
