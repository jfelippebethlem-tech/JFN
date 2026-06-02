from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import pytesseract
import requests
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


def _preprocess(
    image: np.ndarray,
    *,
    gray: bool = True,
    blur: bool = True,
    threshold: bool = True,
) -> np.ndarray:
    if gray:
        if len(image.shape) == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if blur:
        image = cv2.medianBlur(image, 3)
    if threshold:
        image = cv2.adaptiveThreshold(
            image,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11,
            2,
        )
    return image


def solve_captcha_image(
    image_path: str | Path,
    *,
    lang: str = "eng",
    config: str = "--psm 7 --oem 3",
) -> str:
    img = cv2.imread(str(image_path))
    if img is None:
        raise FileNotFoundError(f"Imagem não encontrada: {image_path}")

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
    session: Optional[requests.Session] = None,
) -> str:
    sess = session or requests.Session()
    resp = sess.get(url, timeout=30)
    resp.raise_for_status()
    tmp = Path("data/tmp/captcha_current.png")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(resp.content)
    return solve_captcha_image(tmp, lang=lang, config=config)


def solve_captcha_pil(
    pil_image,
    *,
    lang: str = "eng",
    config: str = "--psm 7 --oem 3",
) -> str:
    img = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    return solve_captcha_image(img, lang=lang, config=config)
