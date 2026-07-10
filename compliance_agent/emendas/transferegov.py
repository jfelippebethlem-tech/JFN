# -*- coding: utf-8 -*-
"""Planos de ação das emendas PIX (transferências especiais, art. 166-A CF).

Fonte: API PostgREST pública do Transferegov (sem chave):
  https://api.transferegov.gestao.gov.br/transferenciasespeciais/plano_acao_especial
Filtro server-side: ?uf_beneficiario_plano_acao=eq.RJ — só o RJ trafega.

POR QUE guardar payload_json integral: a API expõe dezenas de colunas (banco,
conta, datas, valores por natureza) que os detectores futuros podem precisar;
não perder campo por schema enxuto.
"""
from __future__ import annotations

import json
import time

import httpx

from .camara import _HEADERS

_BASE = "https://api.transferegov.gestao.gov.br/transferenciasespeciais"
_TIMEOUT = 40
_LOTE = 500


def parse_plano(item: dict) -> dict:
    return dict(
        id_plano=item.get("id_plano_acao"),
        codigo_plano=item.get("codigo_plano_acao"),
        ano=item.get("ano_plano_acao"),
        cnpj_beneficiario=item.get("cnpj_beneficiario_plano_acao"),
        nome_beneficiario=item.get("nome_beneficiario_plano_acao"),
        uf=item.get("uf_beneficiario_plano_acao"),
        municipio=item.get("municipio_beneficiario_plano_acao"),
        situacao=item.get("situacao_plano_acao"),
        valor_custeio=item.get("valor_custeio_plano_acao"),
        valor_investimento=item.get("valor_investimento_plano_acao"),
        payload_json=json.dumps(item, ensure_ascii=False, sort_keys=True),
    )


def coletar_planos_rj(con, pausa: float = 0.5) -> dict:
    """Pagina limit/offset até vazio; upsert em emendas_pix_planos."""
    total = 0
    offset = 0
    try:
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as cli:
            while True:
                r = cli.get(f"{_BASE}/plano_acao_especial", params={
                    "uf_beneficiario_plano_acao": "eq.RJ",
                    "limit": _LOTE, "offset": offset})
                if r.status_code != 200:
                    return {"verificado": False, "planos": total,
                            "motivo": f"HTTP {r.status_code} no offset {offset}"}
                lote = r.json()
                if not lote:
                    break
                for item in lote:
                    row = parse_plano(item)
                    if row["id_plano"] is None:
                        continue
                    cols = list(row)
                    sets = ",".join(f"{c}=excluded.{c}" for c in cols if c != "id_plano")
                    con.execute(
                        f"INSERT INTO emendas_pix_planos ({','.join(cols)}) "
                        f"VALUES ({','.join(':' + c for c in cols)}) "
                        f"ON CONFLICT(id_plano) DO UPDATE SET {sets}", row)
                    total += 1
                con.commit()
                offset += _LOTE
                time.sleep(pausa)
    except httpx.TransportError as e:
        return {"verificado": False, "planos": total, "motivo": f"transporte: {e}"}
    return {"verificado": True, "planos": total, "motivo": None}
