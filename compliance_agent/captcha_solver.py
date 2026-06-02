"""OCR local para captchas do SEI, sem depender de APIs externas."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import pytesseract
import requests
from PIL import Image, ImageFilter

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

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


def _preprocess(image, *, gray=True, blur=True, threshold=True):
    if gray:
        if len(image.shape) == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if blur:
        image = cv2.medianBlur(image, 3)
    if threshold:
        image = cv2.adaptiveThreshold(
            image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
    return image


def _read_image(source):
    if isinstance(source, (str, Path)):
        p = Path(source)
        if not p.exists():
            raise FileNotFoundError(f"Imagem não encontrada: {source}")
        return cv2.imread(str(p))
    if isinstance(source, np.ndarray):
        return source
    raise TypeError(f"Fonte não suportada: {type(source)}")


def solve_captcha_image(
    image_path,
    *,
    lang: str = "eng",
    config: str = "--psm 7 -c tessedit_char_whitelist=0123456789/abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
) -> str:
    img = _read_image(image_path)
    if img is None:
        return ""
    candidates = []
    candidates = []
    for prep in [
        _preprocess(img.copy(), gray=True, blur=True, threshold=True),
        _preprocess(img.copy(), gray=True, blur=True, threshold=False),
        _preprocess(img.copy(), gray=True, blur=False, threshold=True),
    ]:
        text = pytesseract.image_to_string(prep, lang=lang, config=config)
        text = "".join(ch for ch in text if ch.isalnum()).strip()
        if text:
            candidates.append(text)

    if not candidates:
        return ""
    return max(candidates, key=len)


def solve_captcha_url(
    url: str,
    *,
    lang: str = "eng",
    config: str = "--psm 7 --oem 3",
    session=None,
) -> str:
    data = _download(url, session=session)
    tmp = Path("data/tmp/captcha_current.png")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(data)
    return solve_captcha_image(tmp, lang=lang, config=config)


def solve_captcha_pil(
    pil_image,
    *,
    lang: str = "eng",
    config: str = "--psm 7 --oem 3",
    region: tuple[int, int, int, int] | None = None,
) -> str:
    arr = np.array(pil_image)
    if region is not None:
        x, y, w, h = region
        arr = arr[y:y + h, x:x + w]
    img = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    return solve_captcha_image(img, lang=lang, config=config)
