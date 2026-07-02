"""
Backfill do cadastro de empresas: enriquece os TOP favorecidos por valor.

    .venv/bin/python tools/enriquecer_favorecidos_top.py --top 200 [--sleep 1.0]

Pega os N CNPJs que mais receberam (soma de OB) e ainda não estão em
`empresas`, e enriquece cada um via cnpj_enricher (BrasilAPI grátis →
ReceitaWS fallback), usando a MAIOR OB do favorecido como âncora (assim os
flags de risco do enricher saem com contexto real). Resumível: quem já está
na tabela é pulado — rodar de novo continua de onde parou.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def _main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()

    from sqlalchemy import func
    from compliance_agent.database.models import Empresa, OrdemBancaria, get_session
    from compliance_agent.enrichers.cnpj_enricher import enriquecer_ob_cnpj

    session = get_session()
    ja = {c for (c,) in session.query(Empresa.cnpj).all()}

    top = (session.query(OrdemBancaria.favorecido_cpf,
                         func.sum(OrdemBancaria.valor).label("total"))
           .filter(OrdemBancaria.favorecido_cpf.isnot(None),
                   func.length(OrdemBancaria.favorecido_cpf) == 14)
           .group_by(OrdemBancaria.favorecido_cpf)
           .order_by(func.sum(OrdemBancaria.valor).desc())
           .limit(args.top * 2))

    feitos = erros = 0
    for cnpj, total in top:
        cnpj = re.sub(r"\D", "", str(cnpj or ""))
        if len(cnpj) != 14 or cnpj in ja:
            continue
        if feitos >= args.top:
            break
        ob = (session.query(OrdemBancaria)
              .filter(OrdemBancaria.favorecido_cpf.like(f"%{cnpj}%"))
              .order_by(OrdemBancaria.valor.desc()).first())
        if ob is None:
            continue
        try:
            r = await enriquecer_ob_cnpj(session, ob)
            nome = (r or {}).get("empresa") or "?"
            sit = (r or {}).get("situacao") or "sem dado"
            feitos += 1
            print(f"[{feitos}/{args.top}] {cnpj} {nome[:45]} — {sit} "
                  f"(recebeu R$ {total:,.0f})", flush=True)
        except Exception as e:  # noqa: BLE001
            erros += 1
            print(f"[erro] {cnpj}: {e}", flush=True)
        await asyncio.sleep(args.sleep)

    print(f"\nConcluído: {feitos} enriquecidos, {erros} erros.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
