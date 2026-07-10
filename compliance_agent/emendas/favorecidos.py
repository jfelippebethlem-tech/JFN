# -*- coding: utf-8 -*-
"""Favorecido FINAL de cada emenda — quem recebeu o dinheiro.

Fluxo (descoberto ao vivo em 2026-07-10; /emendas/documentos NÃO traz favorecido):
  1. GET /emendas/documentos/{codigoEmenda}?pagina=N → lista de documentos por fase
  2. GET /despesas/documentos/{codigoDocumento}      → codigoFavorecido + nomeFavorecido + valor

POR QUE priorizar a fase Pagamento: é o dinheiro que SAIU (regra-mãe OB=verdade);
sem pagamento, o empenho indica o destinatário pretendido. Cap de documentos por
emenda com log — truncamento silencioso é proibido (INDISPONÍVEL ≠ 0).
"""
from __future__ import annotations

import logging
import re
import time

import httpx

from .camara import _HEADERS
from .coletor import _BASE, _chave, parse_brl

logger = logging.getLogger(__name__)
_TIMEOUT = 30


def escolher_documentos(docs: list[dict], cap: int = 25) -> list[dict]:
    """Pagamentos se existirem; senão empenhos. No máximo `cap` (logando corte)."""
    pagamentos = [d for d in docs if d.get("fase") == "Pagamento"]
    escolhidos = pagamentos or [d for d in docs if d.get("fase") == "Empenho"]
    if len(escolhidos) > cap:
        logger.info("emenda com %d docs na fase escolhida; usando os %d primeiros",
                    len(escolhidos), cap)
        escolhidos = escolhidos[:cap]
    return escolhidos


def _limpa_doc(codigo: str) -> str:
    """'06.083.453/0001-05' → dígitos; CPF já vem mascarado do Portal (mantém máscara)."""
    c = (codigo or "").strip()
    if "*" in c:                      # ***.123.456-** → ***123456**
        return re.sub(r"[.\-/]", "", c)
    return re.sub(r"\D", "", c)


def parse_documento_detalhe(codigo_emenda: str, det: dict) -> dict:
    return dict(
        codigo_emenda=codigo_emenda,
        documento_favorecido=_limpa_doc(det.get("codigoFavorecido") or ""),
        nome_favorecido=(det.get("nomeFavorecido") or "").strip(),
        fase=det.get("fase"),
        documento_ref=det.get("documento"),
        valor=parse_brl(det.get("valor")),
    )


def _get(cli: httpx.Client, url: str, params: dict | None = None):
    """GET com tratamento de 429 (espera) e retry de transporte."""
    for i in range(4):
        try:
            r = cli.get(url, params=params)
        except httpx.TransportError:
            time.sleep(10 * (i + 1))
            continue
        if r.status_code == 429:
            time.sleep(30)
            continue
        return r
    return None


def coletar_favorecidos(con, chave: str | None = None, pausa: float = 1.0,
                        max_emendas: int | None = None, cap_docs: int = 25) -> dict:
    """Para cada emenda sem favorecido coletado (maior pago primeiro):
    lista documentos → detalha os escolhidos → grava emenda_favorecidos."""
    chave = chave or _chave()
    if not chave:
        return {"verificado": False, "emendas": 0, "favorecidos": 0, "motivo": "sem chave"}
    pend = [r[0] for r in con.execute(
        """select e.codigo from emendas e
           left join emenda_favorecidos f on f.codigo_emenda = e.codigo
           where f.id is null and (e.pago > 0 or e.empenhado > 0)
           order by e.pago desc, e.empenhado desc""").fetchall()]
    if max_emendas:
        pend = pend[:max_emendas]
    tot = 0
    with httpx.Client(timeout=_TIMEOUT, headers={**_HEADERS, "chave-api-dados": chave}) as cli:
        for cod in pend:
            docs: list[dict] = []
            pagina = 1
            while True:
                r = _get(cli, f"{_BASE}/emendas/documentos/{cod}", {"pagina": pagina})
                if r is None or r.status_code != 200 or not r.json():
                    break
                docs.extend(r.json())
                pagina += 1
                time.sleep(pausa)
            for d in escolher_documentos(docs, cap=cap_docs):
                rd = _get(cli, f"{_BASE}/despesas/documentos/{d['codigoDocumento']}")
                time.sleep(pausa)
                if rd is None or rd.status_code != 200:
                    continue
                row = parse_documento_detalhe(cod, rd.json())
                if not row["documento_favorecido"]:
                    continue
                con.execute(
                    """INSERT OR IGNORE INTO emenda_favorecidos
                         (codigo_emenda, documento_favorecido, nome_favorecido,
                          fase, documento_ref, valor)
                       VALUES (:codigo_emenda,:documento_favorecido,:nome_favorecido,
                               :fase,:documento_ref,:valor)""", row)
                tot += 1
            con.commit()
    return {"verificado": True, "emendas": len(pend), "favorecidos": tot, "motivo": None}
