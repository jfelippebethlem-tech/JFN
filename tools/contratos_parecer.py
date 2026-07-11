#!/usr/bin/env python3
"""Runner E2E — parecer estilo Tribunal de Contas por contrato da PCRJ.

Coleta aditivos (PNCP termos) → dossiê compartilhado → pensamentos determinísticos
→ câmara (enxame + RAG + memória) → parecer TC em PDF + índice + casos vault.

Uso: tools/contratos_parecer.py [--max-contratos N] [--sem-pdf] [--telegram]
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

from compliance_agent.coleta_lock import coleta_lock  # noqa: E402
from compliance_agent.collectors import pncp, precos  # noqa: E402
from compliance_agent.contratos import db as cd  # noqa: E402
from compliance_agent.contratos import dossie, parecer, thoughts  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _ref_fn(descricao: str):
    """peer + Painel de Preços: hoje só o Painel (peer entra quando houver base de itens)."""
    cs = precos.catmat_por_descricao(descricao, limite=1)
    if not cs:
        return {"disponivel": False}
    return precos.preco_referencia(cs[0]["codigo"])


def _itens_sync(nc: str):
    try:
        return asyncio.run(pncp.buscar_itens(nc))
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-contratos", type=int, default=30)
    ap.add_argument("--sem-pdf", action="store_true")
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()

    con = cd.conectar()
    cd.init_schema(con)
    # contratos (não empenhos) com maior chance de aditivo — tipo Contrato
    alvos = [r[0] for r in con.execute(
        """select numero_controle_pncp from pcrj_contratos
           where tipo like '%ontrato%' order by valor_global desc limit ?""",
        (args.max_contratos,)).fetchall()]
    if not alvos:
        alvos = [r[0] for r in con.execute(
            "select numero_controle_pncp from pcrj_contratos order by valor_global desc limit ?",
            (args.max_contratos,)).fetchall()]

    with coleta_lock():
        for nc in alvos:
            asyncio.run(pncp.coletar_aditivos(con, nc))

    pareceres = []
    for nc in alvos:
        d = dossie.montar_dossie(con, nc, com_rede=True, itens_fn=_itens_sync)
        achados = thoughts.rodar_thoughts(d, ref_fn=_ref_fn)
        if not any(a["risco"] >= parecer.LIMIAR_DELIBERA for a in achados):
            continue
        p = parecer.deliberar(con, d, achados)
        parecer.gravar_e_aprender(con, p)
        pareceres.append(p)
        print(f"{nc}: {p['conclusao']} (score {p['score']}) — dims {p['dimensoes']}", flush=True)

    print(f"\npareceres emitidos: {len(pareceres)} | "
          f"irregularidade: {sum(1 for p in pareceres if p['conclusao'] == 'indício de irregularidade')}",
          flush=True)

    hoje = datetime.now().date()
    saidas = []
    try:
        import pandas as pd
        xlsx = REPO / "reports" / f"contratos_pareceres_{hoje}.xlsx"
        pd.DataFrame([{"controle": p["numero_controle_pncp"], "conclusao": p["conclusao"],
                       "score": p["score"], "dimensoes": ",".join(p["dimensoes"]),
                       "voto": p["voto"]} for p in pareceres]).to_excel(xlsx, index=False)
        saidas.append(xlsx)
    except Exception as e:
        print(f"xlsx INDISPONÍVEL: {e}")

    if not args.sem_pdf and pareceres:
        from tools.vm_guard import cleanup_orphans, wait_until_safe
        cleanup_orphans()
        ok, msg = wait_until_safe()
        if ok:
            from compliance_agent.reporting.render_html import gerar_pdf
            # um PDF por parecer forte (evita PDF gigante); os demais no XLSX
            fortes = [p for p in pareceres if p["score"] >= 5][:20]
            for p in fortes:
                ctx = parecer.render_parecer_ctx(p)
                slug = (p["numero_controle_pncp"] or "s").replace("/", "_").replace("-", "")
                pdf = asyncio.run(gerar_pdf(ctx, f"contrato_parecer_{slug}"))
                saidas.append(Path(pdf))
        else:
            print(f"vm_guard: {msg} — PDF adiado")

    if args.telegram and saidas:
        from compliance_agent.notifications.telegram import enviar_arquivo
        for s in saidas:
            asyncio.run(enviar_arquivo(str(s), caption=f"Pareceres de contratos PCRJ — {hoje}"))

    for p in pareceres:
        if p["conclusao"] == "indício de irregularidade":
            slug = (p["numero_controle_pncp"] or "s").replace("/", "_").replace("-", "")
            nota = REPO.parent / "vault" / "casos" / f"contrato-{slug}.md"
            try:
                nota.write_text(
                    f"---\ntipo: caso\nprojeto: jfn\nseveridade: 🔴 {p['score']}/10\nstatus: aberto\n"
                    f"fonte: câmara de contratos (parecer TC)\natualizado: {hoje}\n---\n\n"
                    f"# Parecer — Contrato {p['numero_controle_pncp']}\n\n"
                    f"**Conclusão:** {p['conclusao']} · **Voto:** {p['voto']}\n\n"
                    f"Dimensões: {', '.join(p['dimensoes'])}\n", encoding="utf-8")
            except Exception:
                pass

    for s in saidas:
        print("saída:", s)


if __name__ == "__main__":
    main()
