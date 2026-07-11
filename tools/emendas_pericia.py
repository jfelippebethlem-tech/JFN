#!/usr/bin/env python3
"""Runner: perícia de emendas federais RJ → PDF Kroll + XLSX (+ Telegram opcional).

Uso: .venv/bin/python tools/emendas_pericia.py [--telegram] [--sem-pdf]
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
from compliance_agent.emendas import pericia  # noqa: E402
from compliance_agent.reporting.pericia_fisc_rico import ctx_de_achados_rico as ctx_de_achados  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _brl(v):
    return f"{(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _panorama(con) -> str:
    r = con.execute("""select count(*), sum(empenhado), sum(liquidado), sum(pago),
                              min(ano), max(ano) from emendas""").fetchone()
    pix = con.execute("select count(*) from emendas_pix_planos").fetchone()[0]
    fav = con.execute("select count(distinct documento_favorecido) from emenda_favorecidos").fetchone()[0]
    return (f"<p><b>Base coletada:</b> {r[0]:,} emendas ({r[4]}–{r[5]}, recortes autor-RJ e "
            f"destino-RJ) — R$ {_brl(r[1])} empenhados, R$ {_brl(r[2])} liquidados, "
            f"R$ {_brl(r[3])} pagos (fases sempre separadas). {pix:,} planos de emenda PIX "
            f"(Transferegov) e {fav:,} favorecidos finais distintos.</p>").replace(",", ".")


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
    edb.init_schema(con)
    resultado = pericia.rodar_todas(con, gravar_alertas=True)
    print(json.dumps(resultado["cobertura"], ensure_ascii=False, indent=2))
    print(f"achados: {len(resultado['achados'])}")

    fontes = [
        {"dado": "Emendas (autor/valores 3 fases)", "estado": "REAL",
         "fonte": "API Portal da Transparência /emendas", "data": datetime.now().date().isoformat()},
        {"dado": "Favorecidos finais", "estado": "REAL",
         "fonte": "API Portal /emendas/documentos + /despesas/documentos", "data": datetime.now().date().isoformat()},
        {"dado": "Planos emenda PIX", "estado": "REAL",
         "fonte": "API Transferegov (transferenciasespeciais)", "data": datetime.now().date().isoformat()},
        {"dado": "Roster deputados RJ", "estado": "REAL",
         "fonte": "API Câmara dos Deputados (legs. 56/57)", "data": datetime.now().date().isoformat()},
        {"dado": "QSA/sanções/doações", "estado": "CACHE local",
         "fonte": "dump RFB 2026-05 + CEIS + TSE (compliance.db)", "data": datetime.now().date().isoformat()},
    ]
    ctx = ctx_de_achados(
        "Perícia de Emendas Parlamentares Federais — RJ",
        "Recortes: 46+ deputados federais do RJ (qualquer destino) e emendas com gasto no RJ "
        "(qualquer autor) · Detectores D1–D6",
        resultado, fontes, panorama_html=_panorama(con))

    data = datetime.now().date()
    saidas = []
    x = _xlsx(resultado["achados"], REPO / "reports" / f"emendas_rj_achados_{data}.xlsx")
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
            pdf = await gerar_pdf(ctx, "emendas_rj_pericia")
            saidas.append(Path(pdf))
            print(f"PDF: {pdf}")

    if args.telegram and saidas:
        from compliance_agent.notifications.telegram import enviar_arquivo
        for s in saidas:
            await enviar_arquivo(str(s), caption=f"Perícia emendas RJ — {data}")

    for s in saidas:
        print("saída:", s)


if __name__ == "__main__":
    asyncio.run(main())
