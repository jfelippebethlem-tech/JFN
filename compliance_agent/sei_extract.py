# -*- coding: utf-8 -*-
"""Extração por schema de processos/editais — JFN 2.0, Onda 5.

Transforma o TEXTO de um edital/TR (SEI bloqueado da VM → usamos PNCP) num registro
estruturado, base para os detectores de direcionamento (R1/R7/R8/R12) e o corpus.

Determinístico (regex/heurística) — livre, testável, sem depender de LLM. Onde o texto
não permite extrair um campo, ele fica vazio (nunca inventa). Pode ser complementado por
LLM (modelo `raciocinio_pesado`) numa evolução, mas o piso honesto é este.
"""
from __future__ import annotations

import re

_CNPJ_RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
_VALOR_RE = re.compile(r"R\$\s*([\d.]+,\d{2})")
_DATA_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")

_MODALIDADES = [
    ("pregão eletrônico", "Pregão eletrônico"), ("pregão", "Pregão"),
    ("concorrência", "Concorrência"), ("inexigibilidade", "Inexigibilidade"),
    ("dispensa", "Dispensa"), ("credenciamento", "Credenciamento"),
    ("registro de preços", "Registro de preços"), ("leilão", "Leilão"),
]
_EXIGENCIAS = [
    ("atestado de capacidade", "atestado de capacidade técnica"),
    ("capital social", "capital social mínimo"),
    ("patrimônio líquido", "patrimônio líquido mínimo"),
    ("índices contábeis", "índices contábeis"),
    ("visita técnica", "visita técnica obrigatória"),
    ("amostra", "apresentação de amostra"),
]


def _num_br(s: str) -> float:
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def extrair(texto: str) -> dict:
    """texto → {objeto, modalidade, fundamento, valor_estimado, exigencias_habilitacao[],
    cnpjs_participantes[], datas[], n_chars, lido}. Campos ausentes ficam vazios (honesto)."""
    txt = texto or ""
    low = txt.lower()

    objeto = ""
    m = re.search(r"objeto[:\s]+([A-Z0-9À-Ú][^\n.;]{12,200})", txt, re.I)
    if m:
        objeto = re.sub(r"\s+", " ", m.group(1)).strip()

    modalidade = next((rot for chave, rot in _MODALIDADES if chave in low), "")

    fundamento = ""
    if "art. 74" in low or "artigo 74" in low or "inexigibil" in low:
        fundamento = "Inexigibilidade (art. 74 Lei 14.133)"
    elif "art. 75" in low or "dispensa" in low:
        fundamento = "Dispensa (art. 75 Lei 14.133)"
    elif "pregão" in low:
        fundamento = "Licitação (Lei 14.133)"

    valores = sorted({_num_br(v) for v in _VALOR_RE.findall(txt)}, reverse=True)
    valor_estimado = valores[0] if valores else 0.0

    exigencias = [rot for chave, rot in _EXIGENCIAS if chave in low]

    cnpjs = sorted({re.sub(r"\D", "", c) for c in _CNPJ_RE.findall(txt) if len(re.sub(r"\D", "", c)) == 14})
    datas = sorted(set(_DATA_RE.findall(txt)))

    return {
        "objeto": objeto,
        "modalidade": modalidade,
        "fundamento": fundamento,
        "valor_estimado": valor_estimado,
        "exigencias_habilitacao": exigencias,
        "cnpjs_participantes": cnpjs[:20],
        "datas": datas[:20],
        "n_chars": len(txt),
        "lido": bool(txt.strip()),
    }
