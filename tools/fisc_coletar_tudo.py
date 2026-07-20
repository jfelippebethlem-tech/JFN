#!/usr/bin/env python3
"""Orquestrador único da coleta de fiscalização — emendas + PCRJ, 2021→hoje.

Roda TUDO em ordem, sob o lock de coleta (1 escritor por vez → nunca 'database
is locked'), com checkpoint retomável em cada etapa. VM-safe: httpx puro, PNCP
por semestre, ContasRio em streaming.

Uso: .venv/bin/python tools/fisc_coletar_tudo.py [--desde 2021] [--pausa 0.9] [--incremental]
Etapas (pule com --pular emendas,pix,favorecidos,pcrj_csv,pncp):
  1. roster Câmara + emendas <desde>..ano-atual (recortes RJ)
  2. planos das emendas PIX (Transferegov, UF=RJ)
  3. favorecidos finais das emendas
  4. ContasRio: despesa por credor + contratos <desde>..2023 (limite da fonte)
  5. PNCP: contratos + licitações municipais, por semestre, 2023→hoje

--incremental (p/ timer semanal): só o ano corrente nas emendas (reseta o
checkpoint do ano p/ pegar emendas novas), PIX completo (barato), favorecidos
pendentes, PNCP só o semestre corrente; pula ContasRio (fonte para em 2023).
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
from compliance_agent.emendas import camara, coletor, favorecidos, transferegov  # noqa: E402
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
    ap.add_argument("--incremental", action="store_true")
    ap.add_argument("--pular", default="", help="csv: emendas,pix,favorecidos,pcrj_csv,pncp")
    args = ap.parse_args()
    pular = {p.strip() for p in args.pular.split(",") if p.strip()}
    ano_atual = date.today().year
    if args.incremental:
        anos = [ano_atual]
        pular.add("pcrj_csv")            # fonte CGM para em 2023 — nada novo p/ puxar
        # o checkpoint marca o ano como concluído; p/ pegar emendas NOVAS do ano
        # corrente, reanda o ano do zero (upsert só atualiza/insere)
        ck = coletor._ckpt_load()
        if str(ano_atual) in ck:
            del ck[str(ano_atual)]
            coletor._ckpt_save(ck)
    else:
        anos = list(range(args.desde, ano_atual + 1))

    with coleta_lock():          # 1 escritor por vez — fim do 'database is locked'
        con = edb.conectar()
        # o timer de segunda 05:40 convive com escritores matinais longos (cerebro_sync 06:25,
        # metacognição 06:50); 60s de busy_timeout não seguram — 5 min seguram (falha real 2026-07-20)
        con.execute("PRAGMA busy_timeout=300000")
        edb.init_schema(con)
        gastos_db.init_schema(con)

        if "emendas" not in pular:
            r = camara.listar_deputados_rj()
            if r["verificado"]:
                _log(f"[1/5] roster: {camara.gravar_roster(con, r['deputados'])} deputados")
            else:
                # roster é só refresh; se já houver roster no DB, a coleta segue
                n_roster = con.execute("select count(*) from deputados_federais_rj").fetchone()[0]
                if n_roster == 0:
                    _log(f"INDISPONÍVEL roster e DB vazio: {r['motivo']}")
                    sys.exit(2)
                _log(f"[1/5] roster: refresh falhou ({r['motivo']}) — usando {n_roster} já no DB")
            for ano in anos:
                res = coletor.coletar_ano(con, ano, pausa=args.pausa)
                _log(f"  emendas {ano}: {res}")

        if "pix" not in pular:
            rpix = transferegov.coletar_planos_rj(con)
            _log(f"[2/5] emendas PIX (Transferegov): {rpix}")

        if "favorecidos" not in pular:
            # 3h de teto: sobra folga p/ ContasRio+PNCP dentro do TimeoutStartSec=4h do systemd
            rf = favorecidos.coletar_favorecidos(con, pausa=args.pausa, orcamento_s=3 * 3600)
            _log(f"[3/5] favorecidos: {rf}")

        if "pcrj_csv" not in pular:
            anos_csv = [a for a in anos if a <= CONTASRIO_ULTIMO_ANO]
            rc = contasrio.coletar_exercicios(con, anos_csv, familias=("Empenhos", "Contratos"))
            _log(f"[4/5] ContasRio: {rc.get('resultado', rc)}")

        if "pncp" not in pular:
            _log("[5/5] PNCP municipal por semestre…")
            desde_pncp = ano_atual if args.incremental else args.desde
            await _pncp(con, desde_pncp)

    _log("coleta 2021→hoje concluída.")


if __name__ == "__main__":
    asyncio.run(main())
