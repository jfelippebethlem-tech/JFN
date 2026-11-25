"""OCR local para captchas do SEI, sem depender de APIs externas."""
from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import pytesseract
import requests

from compliance_agent.adaptadores import rede_segura


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


def _download(url: str, session: Optional[requests.Session] = None) -> bytes:
    """Baixa o captcha pelo cliente seguro único (O0.4): allowlist do SEI, IP fixado e redirect
    seguido à mão (≤ 3 saltos), cada salto revalidado — antes, o guard só olhava a URL inicial e
    um 302 para 169.254.169.254 passava. A sessão do chamador (cookies do SEI) é preservada."""
    r = rede_segura.obter(url, "sei", sessao=session, timeout=30, max_bytes=_MAX_CAPTCHA_BYTES)
    r.raise_for_status()
    return r.content


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


def _ddddocr_ler(image_path) -> str:
    """OCR por rede neural local (ddddocr, ONNX) — offline, sem API e sem custo.

    MEDIDO em 30/08/2026 nos captchas reais de `prefeitura.sei.rio` (180x50, 6 caracteres
    alfanuméricos de caixa mista, riscados por 2-3 retas e ruído sal-e-pimenta):

    | motor      | resultado |
    |------------|-----------|
    | tesseract  | 3 de 9 vieram VAZIOS; nenhuma leitura foi aceita pelo servidor em ~15 tentativas ("Código de confirmação inválido 1.") |
    | ddddocr    | 9 de 9 devolveram 6 caracteres plausíveis; conferidos 2 contra gabarito visual: `2ZZPDP` -> `2ZzPDP` (6/6 caracteres, diverge só a caixa de um) e `27cA2y` -> `27cA2y` (exato) |

    Por isso o ddddocr vem PRIMEIRO e o tesseract fica de reserva — ele continua servindo
    captchas simples, para os quais foi calibrado.

    Devolve "" se a biblioteca não estiver instalada, o que mantém o tesseract como caminho."""
    try:
        import ddddocr
    except ImportError:
        return ""
    # Exceções ESPECÍFICAS, nunca genérica. CONFERIDO na biblioteca, não presumido: as classes
    # de erro do pybind do onnxruntime herdam de `Exception` DIRETO — não de `RuntimeError` —,
    # então capturá-las exige nomeá-las. OSError cobre arquivo ausente/ilegível e ValueError
    # cobre bytes que não são imagem. Qualquer outra coisa é defeito nosso e deve subir, em vez
    # de virar "captcha ilegível" silencioso.
    try:
        from onnxruntime.capi import onnxruntime_pybind11_state as _ort
        erros_ort = (_ort.Fail, _ort.InvalidArgument, _ort.RuntimeException, _ort.NoSuchFile)
    except (ImportError, AttributeError):
        erros_ort = ()
    try:
        dados = Path(image_path).read_bytes() if not isinstance(image_path, bytes) else image_path
        return (ddddocr.DdddOcr(show_ad=False).classification(dados) or "").strip()
    except (OSError, ValueError, *erros_ort):
        return ""


def solve_captcha_image(
    image_path,
    *,
    lang: str = "eng",
    config: str = "--psm 7 -c tessedit_char_whitelist=0123456789/abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
) -> str:
    texto = _ddddocr_ler(image_path)
    if texto:
        return texto
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


def solve_captcha_data_uri(
    data_uri: str,
    *,
    lang: str = "eng",
    config: str = "--psm 7 --oem 3",
) -> str:
    """Resolve captcha embutido como `data:image/...;base64,...` no atributo src da <img>.

    O SEI da Prefeitura do Rio (`prefeitura.sei.rio`) serve o captcha assim — não há URL de
    imagem para baixar. `solve_captcha_url` rejeita isso no cliente seguro ("esquema de URL não
    permitido: 'data'"), e o chamador engolia a exceção: **o OCR nunca chegava a rodar** nessa
    instância. Medido em 30/08/2026.

    A guarda de `rede_segura` continua valendo para tudo que é URL de rede — aqui não há
    requisição alguma, os bytes já vieram no DOM."""
    import base64

    if not data_uri.startswith("data:"):
        raise ValueError("não é data URI")
    cabeca, _, corpo = data_uri.partition(",")
    if not corpo:
        return ""
    dados = base64.b64decode(corpo) if "base64" in cabeca else corpo.encode()
    tmp = Path("data/tmp/captcha_current.png")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(dados)
    return solve_captcha_image(tmp, lang=lang, config=config)


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


