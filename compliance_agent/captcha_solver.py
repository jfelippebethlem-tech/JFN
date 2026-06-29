"""OCR local para captchas do SEI, sem depender de APIs externas."""
from __future__ import annotations

import ipaddress
import os
import platform
import shutil
import socket
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import cv2
import numpy as np
import pytesseract
import requests


def _resolver_tesseract() -> Optional[str]:
    """Localiza o binário do Tesseract em qualquer SO.

    Ordem: variável TESSERACT_CMD > caminho padrão do Windows > PATH (Linux/Mac).
    Em Linux/Docker o Tesseract fica no PATH (apt install tesseract-ocr), então
    não forçamos nenhum caminho fixo.
    """
    override = os.environ.get("TESSERACT_CMD")
    if override and Path(override).exists():
        return override
    if platform.system() == "Windows":
        base = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        win = Path(base) / "Tesseract-OCR" / "tesseract.exe"
        if win.exists():
            return str(win)
    return shutil.which("tesseract")


_tess = _resolver_tesseract()
if _tess:
    pytesseract.pytesseract.tesseract_cmd = _tess

TMP = Path("data/tmp/captcha_solver")
TMP.mkdir(parents=True, exist_ok=True)


_MAX_CAPTCHA_BYTES = 5 * 1024 * 1024  # 5 MB — captcha é imagem pequena


def _url_segura(url: str) -> None:
    """Guard anti-SSRF: só http(s) e host que NÃO resolva p/ IP interno/metadata.

    O captcha vem de um link da página do SEI (confiável), mas validamos mesmo
    assim — defesa em profundidade contra redirecionamento p/ rede interna /
    169.254.169.254 (metadata cloud). Levanta ValueError se inseguro.
    """
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError(f"esquema de URL não permitido: {p.scheme!r}")
    host = p.hostname
    if not host:
        raise ValueError("URL sem host")
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror as e:
        raise ValueError(f"host não resolve: {host}") from e
    for fam, _t, _p, _c, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError(f"host resolve p/ IP interno ({ip}) — bloqueado (SSRF)")


def _download(url: str, session: Optional[requests.Session] = None) -> bytes:
    _url_segura(url)
    sess = session or requests.Session()
    # redirects no default (preserva o login SEI, que pode redirecionar a imagem do captcha);
    # o guard valida a URL inicial — defesa principal contra SSRF direto.
    r = sess.get(url, timeout=30, stream=True)
    r.raise_for_status()
    chunks, total = [], 0
    for ch in r.iter_content(8192):
        total += len(ch)
        if total > _MAX_CAPTCHA_BYTES:
            raise ValueError("captcha excede tamanho máximo")
        chunks.append(ch)
    return b"".join(chunks)


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
