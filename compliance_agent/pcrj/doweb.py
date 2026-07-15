# -*- coding: utf-8 -*-
"""Coletor do Diário Oficial do Município do Rio (``doweb.rio.rj.gov.br``).

Fonte C do harvester (backbone). A busca do D.O. Rio é um **Elasticsearch aberto**
(índice ``multidiarios_prod``), sem captcha e sem login — endpoint descoberto no
bundle da SPA ``/buscanova/``:

    GET /busca/busca/buscar/query/{pagina}/?1=1&q={termo}

Cada hit traz ``conteudo`` (texto do ato), ``data``, ``pdf_id``, ``diario_id``,
``pagina``. Daqui extraímos o **número de processo administrativo** (que a imprensa
costuma omitir), classificamos o tipo do ato e persistimos em ``pcrj_doe_materia``.

Uso (CLI):
    python -m compliance_agent.pcrj.doweb "Complexo Hospitalar Souza Aguiar" --ano-min 2021 --paginas 5

VM-safe: síncrono, serial, com pausa entre páginas. Nenhum serviço pago.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from . import db

BASE = "https://doweb.rio.rj.gov.br"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# ── Extração de nº de processo (municipal Rio: SIGA legado + SEI.RIO novo) ──
# Tolerante de propósito: é campo de INDÍCIO; o texto bruto fica guardado junto.
_RE_PROCESSO = [
    re.compile(r"\b\d{2,3}\.?\d{3}\.?\d{5,6}\s*/\s*\d{4}\s*-?\s*\d{0,2}\b"),   # 000.900.048716/2026-91 (SEI.RIO)
    re.compile(r"\b\d{2}/\d{2}/\d{3}\.\d{3}/\d{4}\b"),                          # 09/61/000.285/2023 (SIGA c/ subórgão)
    re.compile(r"\b\d{2}/\d{3}\.\d{3}/\d{4}\b"),                                # 09/002.991/2022 (SIGA)
    re.compile(r"\b[A-Z]{2,5}(?:-[A-Z]{2,5})?\s*\d{4}\s*/\s*\d{3,6}\b"),        # SMS-PRO 2025/13348 · CCP-PRO-2025/00060
    re.compile(r"\bSEI[-\s]?\d{6}\s*/\s*\d{6}\s*/\s*\d{4}\b", re.I),            # SEI-080001/028693/2023
    re.compile(r"\b\d{2}\s*/\s*\d{5,6}\s*/\s*\d{4}\b"),                         # 08/003668/2025 (SIGA sem ponto)
]

_TIPOS = [
    ("homologacao",      re.compile(r"homolog", re.I)),  # homologa/homologo/homologação/homologado
    ("extrato_contrato", re.compile(r"extrato.{0,30}contrato|termo de contrato", re.I)),
    ("ppp",              re.compile(r"parceria p[úu]blico|\bPPP\b|concess[ãa]o|CCPAR", re.I)),
    ("edital",           re.compile(r"\bedital\b|concorr[êe]ncia|preg[ãa]o|licita", re.I)),
]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def extrair_processos(texto: str) -> list[str]:
    """Números de processo administrativo achados no texto (deduplicados, ordem estável)."""
    achados: list[str] = []
    for rx in _RE_PROCESSO:
        for m in rx.finditer(texto or ""):
            n = re.sub(r"\s+", "", m.group(0))
            if n not in achados:
                achados.append(n)
    # descarta submatches (ex.: '61/000.285/2023' contido em '09/61/000.285/2023')
    return [n for n in achados if not any(n != o and n in o for o in achados)]


def classificar(texto: str) -> str:
    for tipo, rx in _TIPOS:
        if rx.search(texto or ""):
            return tipo
    return "outro"


def _url_materia(diario_id: str) -> str:
    """Link estável para a edição (download) — página fica no campo próprio."""
    return f"{BASE}/portal/edicoes/download/{diario_id}"


def buscar(termo: str, *, pagina: int = 0, exata: bool = True,
           anos: Optional[list[int]] = None,
           client: Optional[httpx.Client] = None) -> dict:
    """Uma página de resultados do Elasticsearch do D.O. Rio.

    Retorna ``{"total": int, "hits": [ {id,diario_id,pdf_id,pagina,data,ano,texto} ]}``.
    ``exata`` envolve o termo em aspas (frase exata) — evita o OR ruidoso.
    ``anos`` restringe pelo filtro nativo ``/y:2025,2024`` (padrão da própria busca).
    """
    q = f'"{termo}"' if exata else termo
    q = q.replace(":", " ")  # ':' é sintaxe de filtro no ES do doweb — neutraliza
    filtro = f"/y:{','.join(str(a) for a in anos)}" if anos else ""
    own = client is None
    cli = client or httpx.Client(headers={"User-Agent": UA}, timeout=40, follow_redirects=True)
    try:
        r = cli.get(f"{BASE}/busca/busca/buscar/query/{pagina}{filtro}/",
                    params={"1": "1", "q": q})
        r.raise_for_status()
        data = r.json()
    finally:
        if own:
            cli.close()
    hits = []
    for h in data.get("hits", {}).get("hits", []):
        src = h.get("_source", {}) or {}
        hits.append({
            "id": h.get("_id"),
            "diario_id": str(src.get("diario_id") or ""),
            "pdf_id": str(src.get("pdf_id") or ""),
            "pagina": src.get("pagina"),
            "data": src.get("data") or "",
            "ano": int(src.get("year") or 0) or None,
            "texto": src.get("conteudo") or "",
            "score": h.get("_score"),
        })
    total = data.get("hits", {}).get("total")
    if isinstance(total, dict):  # ES7+ pode devolver {"value":N}
        total = total.get("value")
    return {"total": total, "hits": hits}


def coletar_termo(termo: str, *, ano_min: int = 2021, max_paginas: int = 5,
                  exata: bool = True, anos: Optional[list[int]] = None,
                  pausa: float = 1.0, db_path=None) -> dict:
    """Varre N páginas de um termo, filtra por ``ano >= ano_min`` e persiste em ``pcrj_doe_materia``.

    Serial e com pausa entre páginas (VM 2 vCPU). Idempotente (UPSERT por id_materia).
    ``anos`` (opcional) usa o filtro nativo do D.O. para restringir a busca no servidor.
    Retorna resumo: {termo, paginas, gravadas, com_processo, processos, por_tipo}.
    """
    db.inicializar(db_path)
    con = db.conectar(db_path)
    gravadas = 0
    processos_todos: list[str] = []
    por_tipo: dict[str, int] = {}
    client = httpx.Client(headers={"User-Agent": UA}, timeout=40, follow_redirects=True)
    try:
        for p in range(max_paginas):
            res = buscar(termo, pagina=p, exata=exata, anos=anos, client=client)
            if not res["hits"]:
                break
            for hit in res["hits"]:
                if hit["ano"] and hit["ano"] < ano_min:
                    continue
                procs = extrair_processos(hit["texto"])
                tipo = classificar(hit["texto"])
                por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
                processos_todos.extend(procs)
                con.execute(
                    """INSERT INTO pcrj_doe_materia
                       (id_materia,diario_id,pdf_id,pagina,data,ano,termo_busca,orgao,tipo,processos,texto,url,coletado_em)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id_materia) DO UPDATE SET
                         tipo=excluded.tipo, processos=excluded.processos,
                         texto=excluded.texto, termo_busca=excluded.termo_busca,
                         coletado_em=excluded.coletado_em""",
                    (hit["id"], hit["diario_id"], hit["pdf_id"], hit["pagina"],
                     hit["data"], hit["ano"], termo, None, tipo,
                     json.dumps(procs, ensure_ascii=False), hit["texto"],
                     _url_materia(hit["diario_id"]), _now()),
                )
                gravadas += 1
            con.commit()
            time.sleep(pausa)
    finally:
        client.close()
        con.close()
    procs_unicos = list(dict.fromkeys(processos_todos))
    return {
        "termo": termo, "ano_min": ano_min, "paginas": max_paginas,
        "gravadas": gravadas, "com_processo": sum(1 for _ in procs_unicos),
        "processos": procs_unicos, "por_tipo": por_tipo,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Coletor do D.O. Rio (doweb) — busca por termo.")
    ap.add_argument("termo", help="termo de busca (frase exata por padrão)")
    ap.add_argument("--ano-min", type=int, default=2021)
    ap.add_argument("--paginas", type=int, default=5)
    ap.add_argument("--anos", default=None, help="filtro nativo por ano no servidor, ex.: 2025,2024")
    ap.add_argument("--nao-exata", action="store_true", help="busca OR (mais ruído)")
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    anos = [int(x) for x in a.anos.split(",")] if a.anos else None
    r = coletar_termo(a.termo, ano_min=a.ano_min, max_paginas=a.paginas,
                      exata=not a.nao_exata, anos=anos, db_path=a.db)
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
