# -*- coding: utf-8 -*-
"""
backfill_enderecos — garante que TODO CNPJ coletado no JFN tenha um endereço em endereco_fornecedor.

Motivo (achado 2026-06-07): o enriquecedor de sócios (rede_societaria.ingerir) marca o CNPJ como "feito"
(sentinela em socios_fornecedor) mesmo quando a BrasilAPI devolve erro/429, e nesse caso NÃO grava endereço
e NUNCA retenta. Resultado: centenas de CNPJs válidos (inclusive Banco do Brasil) ficaram sem endereço por
falha transitória. Este script ataca DIRETO o gap de endereco_fornecedor, retentando com backoff de 429.

Fonte = credores das OB (ob_orcamentaria_siafe.credor) + favorecidos (ordens_bancarias.favorecido_cpf), 14 díg.
Idempotente e resumível: a cada execução recomputa o gap (CNPJs sem linha em endereco_fornecedor).

Uso: PYTHONPATH=. .venv/bin/python -m tools.backfill_enderecos   (rodar com run_in_background)
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import httpx

from compliance_agent.rede_societaria import _gravar_endereco

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"
_LOG = _REPO / "data" / "backfill_enderecos.log"


def _log(m: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {m}"
    print(line, flush=True)
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _digs(v) -> str:
    return "".join(ch for ch in str(v) if ch.isdigit())


def _gap() -> list[str]:
    con = sqlite3.connect(str(_DB))
    try:
        cnpjs = set()
        for (c,) in con.execute("SELECT DISTINCT credor FROM ob_orcamentaria_siafe WHERE credor IS NOT NULL"):
            d = _digs(c)
            if len(d) == 14:
                cnpjs.add(d)
        try:
            for (c,) in con.execute("SELECT DISTINCT favorecido_cpf FROM ordens_bancarias WHERE favorecido_cpf IS NOT NULL"):
                d = _digs(c)
                if len(d) == 14:
                    cnpjs.add(d)
        except Exception:
            pass
        com_end = {_digs(r[0]) for r in con.execute("SELECT cnpj FROM endereco_fornecedor")}
        return sorted(cnpjs - com_end)
    finally:
        con.close()


async def _fetch(client: httpx.AsyncClient, cnpj: str, tentativas: int = 4) -> dict:
    """BrasilAPI com backoff em 429/5xx. Devolve o dict no formato de buscar_cnpj (com 'raw') ou {}."""
    from compliance_agent.collectors.cnpj import buscar_cnpj
    espera = 2.0
    for _ in range(tentativas):
        r = await buscar_cnpj(cnpj, client=client)
        err = (r or {}).get("error", "")
        if not err:
            return r
        # 429/5xx → backoff e retenta; 404/inválido → desiste
        if "HTTP 429" in err or "HTTP 5" in err or "Timeout" in err or "timeout" in err.lower():
            await asyncio.sleep(espera)
            espera = min(espera * 2, 30)
            continue
        return {}
    return {}


async def main(delay: float = 0.6) -> None:
    gap = _gap()
    _log(f"gap inicial = {len(gap)} CNPJs sem endereço")
    if not gap:
        _log("nada a fazer.")
        return
    con = sqlite3.connect(str(_DB))
    agora = datetime.now().isoformat(timespec="seconds")
    ok = falha = 0
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "JFN-Compliance/1.0"}) as client:
        for i, cnpj in enumerate(gap, 1):
            try:
                r = await _fetch(client, cnpj)
                if r and r.get("raw"):
                    _gravar_endereco(con, cnpj, r, agora)
                    con.commit()
                    ok += 1
                else:
                    falha += 1
            except Exception as e:  # noqa: BLE001
                falha += 1
                _log(f"  {cnpj}: erro {type(e).__name__}: {str(e)[:80]}")
            if i % 50 == 0:
                _log(f"  {i}/{len(gap)} | grav={ok} falha={falha}")
            await asyncio.sleep(delay)
    con.close()
    _log(f"FIM backfill: gravados={ok} falha={falha} de {len(gap)}")


if __name__ == "__main__":
    asyncio.run(main())
