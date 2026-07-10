#!/usr/bin/env python3
"""Runner: contratos + licitações municipais Rio via PNCP → compliance.db.

Uso: .venv/bin/python tools/pcrj_gastos_coletar.py [--ini AAAAMMDD] [--fim AAAAMMDD]
Janela padrão: ano corrente até hoje. Idempotente (upsert por numero_controle_pncp).
"""
import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compliance_agent.collectors import pncp  # noqa: E402
from compliance_agent.emendas import db as edb  # noqa: E402
from compliance_agent.pcrj import gastos_db  # noqa: E402


def gravar_contratos(con, itens: list[dict]) -> int:
    n = 0
    for it in itens:
        if not it.get("numero_controle_pncp"):
            continue
        cols = list(it)
        sets = ",".join(f"{c}=excluded.{c}" for c in cols if c != "numero_controle_pncp")
        con.execute(
            f"INSERT INTO pcrj_contratos ({','.join(cols)}) "
            f"VALUES ({','.join(':' + c for c in cols)}) "
            f"ON CONFLICT(numero_controle_pncp) DO UPDATE SET {sets}", it)
        n += 1
    con.commit()
    return n


def gravar_licitacoes(con, itens: list[dict]) -> int:
    n = 0
    for it in itens:
        row = {
            "numero_controle_pncp": it.get("id_pncp"),
            "ano": int(it["data_abertura"][:4]) if it.get("data_abertura") else None,
            "modalidade": it.get("modalidade"),
            "objeto": it.get("objeto"),
            "valor_estimado": it.get("valor"),
            "situacao": it.get("situacao"),
            "data_abertura": it.get("data_abertura"),
            "orgao_cnpj": it.get("orgao_cnpj"),
            "orgao_nome": it.get("orgao"),
            "amparo": None,
            "fonte": "pncp",
        }
        if not row["numero_controle_pncp"]:
            continue
        cols = list(row)
        sets = ",".join(f"{c}=excluded.{c}" for c in cols if c != "numero_controle_pncp")
        con.execute(
            f"INSERT INTO pcrj_licitacoes ({','.join(cols)}) "
            f"VALUES ({','.join(':' + c for c in cols)}) "
            f"ON CONFLICT(numero_controle_pncp) DO UPDATE SET {sets}", row)
        n += 1
    con.commit()
    return n


async def main():
    ap = argparse.ArgumentParser()
    hoje = date.today()
    ap.add_argument("--ini", default=f"{hoje.year}0101")
    ap.add_argument("--fim", default=hoje.strftime("%Y%m%d"))
    args = ap.parse_args()

    from compliance_agent.coleta_lock import coleta_lock
    with coleta_lock():          # serializa com os demais coletores do compliance.db
        con = edb.conectar()
        gastos_db.init_schema(con)

        rc = await pncp.coletar_contratos_pcrj(args.ini, args.fim)
        if not rc["verificado"]:
            print(f"contratos INDISPONÍVEL: {rc['motivo']}")
            sys.exit(2)
        print(f"contratos PCRJ: {gravar_contratos(con, rc['itens'])} gravados", flush=True)

        rl = await pncp.coletar_contratacoes_municipio_rio(args.ini, args.fim)
        if not rl["verificado"]:
            print(f"licitações INDISPONÍVEL: {rl['motivo']}")
            sys.exit(2)
        print(f"licitações município Rio: {gravar_licitacoes(con, rl['itens'])} gravadas", flush=True)

        # órgãos municipais descobertos nas licitações (COMLURB, RioSaúde, secretarias
        # com CNPJ próprio…) → contratos de cada um, sem lista manual
        outros = [r[0] for r in con.execute(
            "select distinct orgao_cnpj from pcrj_licitacoes "
            "where orgao_cnpj is not null and orgao_cnpj != ?", (pncp.CNPJ_PCRJ,))]
        for cnpj in outros:
            rc2 = await pncp.coletar_contratos_pcrj(args.ini, args.fim, cnpj_orgao=cnpj)
            if rc2["verificado"] and rc2["itens"]:
                print(f"contratos {cnpj}: {gravar_contratos(con, rc2['itens'])}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
