#!/usr/bin/env python3
"""Runner: perícia de gastos/contratos da Prefeitura do Rio → PDF Kroll + XLSX.

Uso: .venv/bin/python tools/pcrj_pericia_gastos.py [--telegram] [--sem-pdf]
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from compliance_agent.emendas import db as edb  # noqa: E402
from compliance_agent.pcrj import gastos_db, pericia_gastos  # noqa: E402
from compliance_agent.reporting.pericia_fisc import ctx_de_achados  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _brl(v):
    return f"{(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _panorama(con) -> str:
    d = con.execute("""select count(*), sum(empenhado), sum(liquidado), sum(pago),
                              min(exercicio), max(exercicio) from pcrj_despesa""").fetchone()
    c = con.execute("select count(*), count(distinct fornecedor_documento) from pcrj_contratos").fetchone()
    li = con.execute("select count(*) from pcrj_licitacoes").fetchone()[0]
    return (f"<p><b>Base coletada:</b> despesa por credor {d[4]}–{d[5]} "
            f"({d[0]:,} linhas credor×órgão): R$ {_brl(d[1])} empenhados, "
            f"R$ {_brl(d[2])} liquidados, R$ {_brl(d[3])} pagos. "
            f"{c[0]:,} contratos/empenhos PNCP de {c[1]:,} fornecedores; {li:,} licitações "
            f"municipais. 2024+ sem arquivo aberto de despesa fina (INDISPONÍVEL ≠ 0; "
            f"cobertura recente via PNCP).</p>").replace(",", ".")


def _xlsx(achados: list[dict], destino: Path) -> Path | None:
    try:
        import pandas as pd
        flat = [{**a, "evidencias": json.dumps(a["evidencias"], ensure_ascii=False, default=str)}
                for a in achados]
        pd.DataFrame(flat).to_excel(destino, index=False)
        return destino
    except Exception as e:
        print(f"xlsx INDISPONÍVEL: {e}")
        return None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--sem-pdf", action="store_true")
    args = ap.parse_args()

    con = edb.conectar()
    gastos_db.init_schema(con)
    resultado = pericia_gastos.rodar_todas(con, gravar_alertas=True)
    print(json.dumps(resultado["cobertura"], ensure_ascii=False, indent=2))
    print(f"achados: {len(resultado['achados'])}")

    hoje = datetime.now().date().isoformat()
    fontes = [
        {"dado": "Despesa por credor 2019–2023", "estado": "REAL",
         "fonte": "CGM-Rio, Open_Data_Empenhos (Rio Transparente)", "data": hoje},
        {"dado": "Contratos/empenhos 2024+", "estado": "REAL",
         "fonte": "PNCP consulta v1 (órgãos municipais Rio)", "data": hoje},
        {"dado": "Licitações municipais", "estado": "REAL",
         "fonte": "PNCP contratações por código IBGE 3304557", "data": hoje},
        {"dado": "QSA / idade de CNPJ", "estado": "REAL/CACHE",
         "fonte": "dump RFB 2026-05 + minhareceita.org", "data": hoje},
        {"dado": "Folha municipal (D9)", "estado": "CACHE local",
         "fonte": "contracheque PCRJ (pcrj_folha_pref)", "data": hoje},
    ]
    ctx = ctx_de_achados(
        "Perícia de Gastos e Contratações — Prefeitura do Rio de Janeiro",
        "Despesa por credor (CGM 2019–2023) + contratos/licitações (PNCP 2024+) · "
        "Detectores D7–D10",
        resultado, fontes, panorama_html=_panorama(con))

    data = datetime.now().date()
    saidas = []
    x = _xlsx(resultado["achados"], REPO / "reports" / f"pcrj_gastos_achados_{data}.xlsx")
    if x:
        saidas.append(x)
    if not args.sem_pdf:
        from tools.vm_guard import cleanup_orphans, wait_until_safe
        cleanup_orphans()
        ok, msg = wait_until_safe()
        if not ok:
            print(f"vm_guard: {msg} — PDF adiado")
        else:
            from compliance_agent.reporting.render_html import gerar_pdf
            pdf = await gerar_pdf(ctx, "pcrj_gastos_pericia")
            saidas.append(Path(pdf))
            print(f"PDF: {pdf}")

    if args.telegram and saidas:
        from compliance_agent.notifications.telegram import enviar_arquivo
        for s in saidas:
            await enviar_arquivo(str(s), caption=f"Perícia gastos PCRJ — {data}")

    for s in saidas:
        print("saída:", s)


if __name__ == "__main__":
    asyncio.run(main())
