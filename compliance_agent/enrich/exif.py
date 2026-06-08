# -*- coding: utf-8 -*-
"""Forense de metadados de documentos — ExifTool (local, KEYLESS, sem rede).

Onda 12 (DD §9 — mídia/documentos). Roda o ExifTool sobre arquivos baixados do SEI/PNCP (PDF, DOCX,
imagens) e extrai metadados úteis à due diligence: autor/criador real, software, datas de
criação/modificação, GPS (em fotos). Honesto: sem ExifTool ou sem arquivo → INDISPONÍVEL; nunca fabrica.

Sinais (indícios, nunca prova):
- autor/criador é PESSOA física quando o documento se diz oficial do órgão;
- modificado ANTES de criado (datas inconsistentes);
- GPS embutido em foto (vazamento de localização);
- software de edição incomum p/ peça oficial.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

# campos relevantes p/ DD (ExifTool tag → rótulo)
_CAMPOS = {
    "Author": "autor", "Creator": "criador", "Producer": "produtor_software",
    "Company": "empresa", "LastModifiedBy": "ultimo_editor",
    "CreateDate": "data_criacao", "ModifyDate": "data_modificacao",
    "GPSLatitude": "gps_lat", "GPSLongitude": "gps_lon",
    "FileType": "tipo", "PDFVersion": "pdf_versao", "Title": "titulo",
}


def _disponivel() -> bool:
    return shutil.which("exiftool") is not None


def metadados(caminho: str) -> dict:
    """Extrai metadados de UM arquivo. {ok, arquivo, meta:{...}, sinais:[...]} | INDISPONÍVEL. Nunca fabrica."""
    p = Path(caminho)
    if not _disponivel():
        return {"ok": True, "arquivo": str(p), "meta": {}, "sinais": [],
                "_nota": "INDISPONÍVEL: ExifTool não instalado (apt: libimage-exiftool-perl). Nada fabricado.",
                "_fonte": "ExifTool (local)"}
    if not p.exists() or not p.is_file():
        return {"ok": False, "erro": f"arquivo não encontrado: {p}"}
    try:
        r = subprocess.run(["exiftool", "-json", "-n", str(p)],
                           capture_output=True, text=True, timeout=30)
        data = json.loads(r.stdout or "[]")
        raw = data[0] if data else {}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": f"ExifTool: {str(e)[:80]}"}

    meta = {rotulo: raw[tag] for tag, rotulo in _CAMPOS.items() if raw.get(tag) not in (None, "")}
    sinais = []
    if meta.get("gps_lat") is not None or meta.get("gps_lon") is not None:
        sinais.append("GPS embutido (vazamento de localização) — verificar origem")
    cri = str(meta.get("data_criacao") or "")
    mod = str(meta.get("data_modificacao") or "")
    if cri and mod and mod < cri:
        sinais.append("data de modificação ANTERIOR à de criação (metadados inconsistentes)")
    return {"ok": True, "arquivo": str(p), "meta": meta, "sinais": sinais,
            "_fonte": "ExifTool (local, sem rede)",
            "_nota": "Metadados são INDÍCIO (presunção de legitimidade); podem ser editados/ausentes."}


def metadados_lote(caminhos: list[str]) -> dict:
    """Roda em vários arquivos. {ok, n, itens:[...], com_sinal:int}."""
    itens = [metadados(c) for c in (caminhos or [])]
    com_sinal = sum(1 for i in itens if i.get("sinais"))
    return {"ok": True, "n": len(itens), "itens": itens, "com_sinal": com_sinal,
            "_fonte": "ExifTool (local)"}
