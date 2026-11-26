# -*- coding: utf-8 -*-
"""O que os estágios NATIVOS de OCR importam está no lock que a religação instala nos workers (O9.0, 26/11/2026).

O R1 do tools/religar_o90.py instala SÓ o requirements.lock na venv do worker (~/JFN-worker/.venv). O E5 (ocr) e o
E6 (confirmar_ocr) rodam nessa venv — o ensaio O8.5 escondia a falta pondo ~/ocr-reserva/.venv no PYTHONPATH. Medido
em 26/11 na VM-2 e no it-campo, dentro da fatia: `ocr.escolher()` → ExecutorCPU → ModuleNotFoundError 'rapidocr'
(o E5 inteiro cairia em falha transitória/quarentena); o E6 sem zxing-cpp declara o código de barras INDISPONÍVEL.
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PRECISA = {"rapidocr": "E5 ExecutorCPU (tools.sei_ocr_reserva.motor_ocr) e recorte do E6",
           "zxing-cpp": "E6 confirmar_ocr: código de barras nível A"}


def _nomes(arquivo: str) -> set[str]:
    rx = re.compile(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?\s*(?:[=<>!~]=|>|<|\s|$)")
    return {m.group(1).lower() for ln in (RAIZ / arquivo).read_text(encoding="utf-8").splitlines()
            if (m := rx.match(ln.strip())) and not ln.lstrip().startswith(("#", "-"))}


def test_requirements_de_producao_declara_o_ocr_dos_estagios():
    faltam = {p: q for p, q in PRECISA.items() if p not in _nomes("requirements.txt")}
    assert not faltam, f"fora do requirements.txt (o worker não instala): {faltam}"


def test_lock_de_producao_tem_o_ocr_dos_estagios():
    faltam = {p: q for p, q in PRECISA.items() if p not in _nomes("requirements.lock")}
    assert not faltam, f"fora do requirements.lock (o R1 da religação não instala): {faltam}"
