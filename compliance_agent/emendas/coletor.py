# -*- coding: utf-8 -*-
"""Coleta paginada de /api-de-dados/emendas (Portal da Transparência).

POR QUE baixar o ano INTEIRO e filtrar client-side: a API não filtra por UF de
autor nem de destino; o volume (~10k emendas/ano, ~15/página) cabe em ~10 min
a 60 req/min. Checkpoint por (ano, página) permite retomar sem repetir.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import httpx

from . import db as edb
from .camara import norm_nome

_BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"
_REPO = Path(__file__).resolve().parent.parent.parent
_CKPT = _REPO / "data" / "emendas_checkpoint.json"
_TIMEOUT = 30

# nome por extenso (como vem em "<NOME> (UF)") → sigla
_UF_NOME_SIGLA = {
    "ACRE": "AC", "ALAGOAS": "AL", "AMAPA": "AP", "AMAZONAS": "AM", "BAHIA": "BA",
    "CEARA": "CE", "DISTRITO FEDERAL": "DF", "ESPIRITO SANTO": "ES", "GOIAS": "GO",
    "MARANHAO": "MA", "MATO GROSSO": "MT", "MATO GROSSO DO SUL": "MS", "MINAS GERAIS": "MG",
    "PARA": "PA", "PARAIBA": "PB", "PARANA": "PR", "PERNAMBUCO": "PE", "PIAUI": "PI",
    "RIO DE JANEIRO": "RJ", "RIO GRANDE DO NORTE": "RN", "RIO GRANDE DO SUL": "RS",
    "RONDONIA": "RO", "RORAIMA": "RR", "SANTA CATARINA": "SC", "SAO PAULO": "SP",
    "SERGIPE": "SE", "TOCANTINS": "TO",
}


def parse_brl(v) -> float:
    if not v:
        return 0.0
    s = re.sub(r"[R$\s]", "", str(v))
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def e_pix(tipo: str) -> int:
    return 1 if "especia" in (tipo or "").lower() else 0


def _uf_destino(localidade: str) -> str | None:
    loc = norm_nome(localidade or "")
    m = re.search(r"-\s*([A-Z]{2})$", loc)            # "DUAS BARRAS - RJ"
    if m:
        return m.group(1)
    if loc.endswith("(UF)"):                          # "RIO DE JANEIRO (UF)"
        return _UF_NOME_SIGLA.get(loc[:-4].strip())
    return None


def classificar_recorte(emenda: dict, roster_norm: set[str]) -> str | None:
    autor = norm_nome(emenda.get("nomeAutor") or "")
    # autor pode vir com sufixo "(EX-PARLAMENTAR ...)" — compara o prefixo antes do parêntese
    autor_base = autor.split("(")[0].strip()
    autor_rj = autor_base in roster_norm
    destino_rj = _uf_destino(emenda.get("localidadeDoGasto") or "") == "RJ"
    if autor_rj and destino_rj:
        return "AMBOS"
    if autor_rj:
        return "AUTOR_RJ"
    if destino_rj:
        return "DESTINO_RJ"
    return None


def _chave() -> str:
    return (os.environ.get("PORTAL_TRANSPARENCIA_KEY", "")
            or os.environ.get("TRANSPARENCIA_API_KEY", "")).strip()


def _ckpt_load() -> dict:
    try:
        return json.loads(_CKPT.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _ckpt_save(d: dict) -> None:
    tmp = _CKPT.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), "utf-8")
    os.replace(tmp, _CKPT)          # escrita atômica — lição rotas-split


def _row_de_api(e: dict, recorte: str) -> dict:
    loc = e.get("localidadeDoGasto") or ""
    return dict(
        codigo=e["codigoEmenda"], ano=int(e["ano"]),
        autor_raw=e.get("nomeAutor"),
        autor_norm=norm_nome((e.get("nomeAutor") or "").split("(")[0]),
        autor_id_camara=None, tipo=e.get("tipoEmenda"), e_pix=e_pix(e.get("tipoEmenda") or ""),
        funcao=e.get("funcao"), subfuncao=e.get("subfuncao"),
        localidade_gasto=loc, uf_destino=_uf_destino(loc), municipio_destino_ibge=None,
        empenhado=parse_brl(e.get("valorEmpenhado")), liquidado=parse_brl(e.get("valorLiquidado")),
        pago=parse_brl(e.get("valorPago")), resto_inscrito=parse_brl(e.get("valorRestoInscrito")),
        resto_cancelado=parse_brl(e.get("valorRestoCancelado")),
        resto_pago=parse_brl(e.get("valorRestoPago")),
        recorte=recorte, fonte="portal_transparencia")


def coletar_ano(con, ano: int, chave: str | None = None, pausa: float = 1.0) -> dict:
    """Retorna {"verificado", "paginas", "retidas", "motivo"}. Retoma do checkpoint."""
    chave = chave or _chave()
    if not chave:
        return {"verificado": False, "paginas": 0, "retidas": 0,
                "motivo": "sem PORTAL_TRANSPARENCIA_KEY"}
    roster = {r[0] for r in con.execute("select nome_norm from deputados_federais_rj")}
    if not roster:
        return {"verificado": False, "paginas": 0, "retidas": 0,
                "motivo": "roster vazio — rode camara primeiro"}
    ck = _ckpt_load()
    pagina = int(ck.get(str(ano), 0)) + 1
    retidas = 0
    from .camara import _HEADERS  # UA obrigatório — CDNs gov derrubam python-httpx
    with httpx.Client(timeout=_TIMEOUT,
                      headers={**_HEADERS, "chave-api-dados": chave}) as cli:
        while True:
            try:
                r = cli.get(f"{_BASE}/emendas", params={"ano": ano, "pagina": pagina})
            except httpx.TransportError:
                time.sleep(15)
                continue
            if r.status_code == 429:                 # rate limit: espera e repete a página
                time.sleep(30)
                continue
            if r.status_code != 200:
                return {"verificado": False, "paginas": pagina - 1, "retidas": retidas,
                        "motivo": f"HTTP {r.status_code} na página {pagina}"}
            lote = r.json()
            if not lote:
                break
            for e in lote:
                rec = classificar_recorte(e, roster)
                if rec:
                    edb.upsert_emenda(con, _row_de_api(e, rec))
                    retidas += 1
            con.commit()
            ck[str(ano)] = pagina
            _ckpt_save(ck)
            pagina += 1
            time.sleep(pausa)                        # ≤60 req/min
    return {"verificado": True, "paginas": pagina - 1, "retidas": retidas, "motivo": None}
