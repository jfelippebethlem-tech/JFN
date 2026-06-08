# -*- coding: utf-8 -*-
"""Extrai a tabela de ITENS com PREÇO UNITÁRIO de um documento de licitação (homologação/ata/contrato).

Onda 5. Camadas com confiança decrescente — sempre devolve (itens, método, confiança):
  1) tabela PDF estruturada (pdfplumber)        — método 'tabela', conf 0.9   [exige bytes de PDF]
  2) LLM sobre o texto (quando há texto)         — método 'llm_texto', conf 0.8
  3) visão/OCR sobre páginas renderizadas        — método 'visao', conf 0.7    [PDF escaneado]
HONESTO: confiança baixa / sem tabela → ([], 'falha', 0.0). NUNCA chuta número.
⚠️ O mapa de colunas (camada 1) e o prompt (camada 2) ficam genéricos até um EXEMPLO real travar o parser
(SPEC §8). Por isso o piloto (Onda B) salva amostras p/ calibrar.
"""
from __future__ import annotations

import io
import re

ITEM_SCHEMA = ["item", "descricao", "marca", "unidade", "quantidade",
               "valor_unitario", "valor_total", "fornecedor", "cnpj"]

_COLMAP = {  # cabeçalho (normalizado) → campo do schema
    "descricao": "descricao", "especificacao": "descricao", "objeto": "descricao", "item": "item",
    "marca": "marca", "unidade": "unidade", "und": "unidade", "qtd": "quantidade", "quantidade": "quantidade",
    "valor unitario": "valor_unitario", "preco unitario": "valor_unitario", "vl unit": "valor_unitario",
    "unitario": "valor_unitario", "valor total": "valor_total", "preco total": "valor_total",
    "total": "valor_total", "fornecedor": "fornecedor", "cnpj": "cnpj",
}


def _num_br(s) -> float | None:
    """'1.234,56' / 'R$ 1.234,56' -> 1234.56."""
    if s is None:
        return None
    s = re.sub(r"[^\d,.-]", "", str(s)).replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _norm_cab(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def _plausivel(itens: list[dict]) -> bool:
    if not itens:
        return False
    ok = [i for i in itens if i.get("descricao") and i.get("valor_unitario") is not None]
    return len(ok) >= max(1, int(0.6 * len(itens)))


def _norm(itens: list[dict]) -> list[dict]:
    out = []
    for i in itens:
        i = {k: i.get(k) for k in ITEM_SCHEMA if k in i} or i
        i["valor_unitario"] = _num_br(i.get("valor_unitario"))
        i["valor_total"] = _num_br(i.get("valor_total"))
        i["quantidade"] = _num_br(i.get("quantidade"))
        out.append(i)
    return out


def _camada_tabela_pdf(pdf_bytes: bytes) -> list[dict]:
    """pdfplumber: extrai tabelas e mapeia colunas → schema. Genérico até calibração (SPEC §8)."""
    try:
        import pdfplumber
    except Exception:  # noqa: BLE001
        return []
    itens: list[dict] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                for tab in (page.extract_tables() or []):
                    if not tab or len(tab) < 2:
                        continue
                    cab = [_norm_cab(c or "") for c in tab[0]]
                    idx = {j: _COLMAP[c] for j, c in enumerate(cab) if c in _COLMAP}
                    if "valor_unitario" not in idx.values() or "descricao" not in idx.values():
                        continue
                    for linha in tab[1:]:
                        reg = {}
                        for j, val in enumerate(linha):
                            if j in idx:
                                reg[idx[j]] = val
                        if reg.get("descricao") or reg.get("valor_unitario"):
                            itens.append(reg)
    except Exception:  # noqa: BLE001
        return []
    return itens


def _texto_pdf(pdf_bytes: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception:  # noqa: BLE001
        return ""


def _camada_llm_texto(texto: str, gerar) -> list[dict]:
    prompt = ('Extraia a tabela de itens (preço unitário) deste documento de licitação como JSON: lista de '
              '{"item","descricao","marca","unidade","quantidade","valor_unitario","valor_total","fornecedor","cnpj"}. '
              'Números em formato brasileiro. Se NÃO houver tabela de preços, responda [].\n\nTEXTO:\n' + (texto or "")[:12000])
    import json
    try:
        raw = (gerar(prompt) or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def extrair_itens(conteudo, *, gerar=None, ver_imagem=None) -> tuple[list[dict], str, float]:
    """`conteudo` = bytes de PDF OU texto (str). Devolve (itens, metodo, confianca). Honesto: ([],'falha',0)."""
    pdf_bytes = conteudo if isinstance(conteudo, (bytes, bytearray)) else None
    texto = conteudo if isinstance(conteudo, str) else ""

    if pdf_bytes:
        itens = _camada_tabela_pdf(pdf_bytes)
        if _plausivel(itens):
            return _norm(itens), "tabela", 0.9
        texto = texto or _texto_pdf(pdf_bytes)

    if texto.strip() and gerar:
        itens = _camada_llm_texto(texto, gerar)
        if _plausivel(itens):
            return _norm(itens), "llm_texto", 0.8

    if pdf_bytes and ver_imagem:
        try:
            itens = ver_imagem(pdf_bytes)  # hook de visão/OCR (renderiza página → modelo)
            if _plausivel(itens):
                return _norm(itens), "visao", 0.7
        except Exception:  # noqa: BLE001
            pass

    return [], "falha", 0.0
