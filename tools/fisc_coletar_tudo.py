#!/usr/bin/env python3
"""Orquestrador único da coleta de fiscalização — emendas + PCRJ, 2021→hoje.

Roda TUDO em ordem, sob o lock de coleta (1 escritor por vez → nunca 'database
is locked'), com checkpoint retomável em cada etapa. VM-safe: httpx puro, PNCP
por semestre, ContasRio em streaming.

Uso: .venv/bin/python tools/fisc_coletar_tudo.py [--desde 2021] [--pausa 0.9]
Etapas (pule com --pular emendas,favorecidos,pcrj_csv,pncp):
  1. roster Câmara + emendas <desde>..ano-atual (recortes RJ)
  2. favorecidos finais das emendas
  3. ContasRio: despesa por credor + contratos <desde>..2023 (limite da fonte)
  4. PNCP: contratos + licitações municipais, por semestre, 2023→hoje
"""
import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from compliance_agent.coleta_lock import coleta_lock  # noqa: E402
from compliance_agent.collectors import pncp  # noqa: E402
from compliance_agent.emendas import camara, coletor, favorecidos  # noqa: E402
from compliance_agent.emendas import db as edb  # noqa: E402
from compliance_agent.pcrj import contasrio, gastos_db  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pcrj_gastos_coletar import gravar_contratos, gravar_licitacoes  # noqa: E402

CONTASRIO_ULTIMO_ANO = 2023   # a fonte de dados abertos da CGM cobre até 2023


def _log(msg):
    print(msg, flush=True)


def _semestres(desde: int, ate: date):
    """[(AAAAMMDD, AAAAMMDD)] por semestre, de <desde> até hoje."""
    janelas = []
    for ano in range(desde, ate.year + 1):
        for ini, fim in (("0101", "0630"), ("0701", "1231")):
            di = date(ano, int(ini[:2]), int(ini[2:]))
            if di > ate:
                continue
            df = min(date(ano, int(fim[:2]), int(fim[2:])), ate)
            janelas.append((f"{ano}{ini}", df.strftime("%Y%m%d")))
    return janelas


async def _pncp(con, desde: int):
    hoje = date.today()
    pncp_desde = max(desde, 2023)   # PNCP só tem cobertura densa a partir de 2023
    total_c = total_l = 0
    for di, df in _semestres(pncp_desde, hoje):
        rc = await pncp.coletar_contratos_pcrj(di, df)
        if rc["verificado"]:
            total_c += gravar_contratos(con, rc["itens"])
        rl = await pncp.coletar_contratacoes_municipio_rio(di, df)
        if rl["verificado"]:
            total_l += gravar_licitacoes(con, rl["itens"])
        _log(f"  PNCP {di[:6]}: +{len(rc.get('itens', []))} contratos, "
             f"+{len(rl.get('itens', []))} licitações")
    # órgãos municipais descobertos → contratos de cada um
    outros = [r[0] for r in con.execute(
        "select distinct orgao_cnpj from pcrj_licitacoes "
        "where orgao_cnpj is not null and orgao_cnpj != ?", (pncp.CNPJ_PCRJ,))]
    for cnpj in outros:
        for di, df in _semestres(pncp_desde, hoje):
            rc = await pncp.coletar_contratos_pcrj(di, df, cnpj_orgao=cnpj)
            if rc["verificado"] and rc["itens"]:
                total_c += gravar_contratos(con, rc["itens"])
    _log(f"  PNCP total: {total_c} contratos, {total_l} licitações "
         f"({len(outros)} órgãos municipais extras)")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=2021)
    ap.add_argument("--pausa", type=float, default=0.9)
    ap.add_argument("--pular", default="", help="csv: emendas,favorecidos,pcrj_csv,pncp")
    args = ap.parse_args()
    pular = {p.strip() for p in args.pular.split(",") if p.strip()}
    anos = list(range(args.desde, date.today().year + 1))

    with coleta_lock():          # 1 escritor por vez — fim do 'database is locked'
        con = edb.conectar()
        edb.init_schema(con)
        gastos_db.init_schema(con)

        if "emendas" not in pular:
            r = camara.listar_deputados_rj()
            if r["verificado"]:
                _log(f"[1/4] roster: {camara.gravar_roster(con, r['deputados'])} deputados")
            else:
                # roster é só refresh; se já houver roster no DB, a coleta segue
                n_roster = con.execute("select count(*) from deputados_federais_rj").fetchone()[0]
                if n_roster == 0:
                    _log(f"INDISPONÍVEL roster e DB vazio: {r['motivo']}")
                    sys.exit(2)
                _log(f"[1/4] roster: refresh falhou ({r['motivo']}) — usando {n_roster} já no DB")
            for ano in anos:
                res = coletor.coletar_ano(con, ano, pausa=args.pausa)
                _log(f"  emendas {ano}: {res}")

        if "favorecidos" not in pular:
            rf = favorecidos.coletar_favorecidos(con, pausa=args.pausa)
            _log(f"[2/4] favorecidos: {rf}")

        if "pcrj_csv" not in pular:
            anos_csv = [a for a in anos if a <= CONTASRIO_ULTIMO_ANO]
            rc = contasrio.coletar_exercicios(con, anos_csv, familias=("Empenhos", "Contratos"))
            _log(f"[3/4] ContasRio: {rc.get('resultado', rc)}")

        if "pncp" not in pular:
            _log("[4/4] PNCP municipal por semestre…")
            await _pncp(con, args.desde)

    _log("coleta 2021→hoje concluída.")


if __name__ == "__main__":
    asyncio.run(main())
