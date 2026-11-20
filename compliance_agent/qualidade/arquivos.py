# -*- coding: utf-8 -*-
"""Onde as regras de qualidade guardam o que medem (`JFN_DADOS` ou `<repo>/data`) e como gravam: troca atômica
(`.tmp` + replace), para que o painel nunca leia uma fotografia pela metade."""
from __future__ import annotations

import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def dados() -> Path:
    return Path(os.environ.get("JFN_DADOS") or REPO / "data")


def gravar_json(caminho: Path, obj, indent: int | None = 1) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")
    tmp.replace(caminho)
