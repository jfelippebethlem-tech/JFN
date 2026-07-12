#!/usr/bin/env python3
"""Runner: perícias de benefício assistencial × quadro de pessoal do Rio → PDFs (+ Telegram).

Documentos (todos com a NATUREZA DO VÍNCULO explícita — nomeado × efetivo × requisitado ×
aposentado/pensionista × estágio × não informado — pedido do dono 2026-07-11):
  camara      — Câmara Municipal: nomeados (fichas) e servidores × benefício + convergência + suplência
  prefeitura  — Prefeitura: nomeados (fichas), pensionistas e servidores × benefício
  consolidado — documento único Câmara+Prefeitura (visão geral + anexo de certeza MÉDIA)
  socios      — sócios de fornecedores × benefício (com o total pago à empresa via OB SIAFE)

Uso: .venv/bin/python tools/pericia_beneficios_run.py [--doc camara|prefeitura|consolidado|socios|todos] [--telegram]
"""
import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_CAPTION = {
    "camara": "Perícia CÂMARA — nomeados e servidores × benefício (natureza do vínculo explícita)",
    "prefeitura": "Perícia PREFEITURA — nomeados, servidores e pensionistas × benefício",
    "consolidado": "Perícia CONSOLIDADA Câmara+Prefeitura × benefício (com anexo de certeza MÉDIA)",
    "socios": "Perícia SÓCIOS de fornecedores × benefício (com total pago via OB SIAFE)",
}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default="todos",
                    choices=["camara", "prefeitura", "consolidado", "socios", "todos"])
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()
    docs = ["camara", "prefeitura", "consolidado", "socios"] if args.doc == "todos" else [args.doc]

    from tools.vm_guard import cleanup_orphans, wait_until_safe
    cleanup_orphans()
    ok, msg = wait_until_safe()
    if not ok:
        print(f"vm_guard: {msg} — geração adiada")
        return

    saidas: dict[str, str] = {}
    if "camara" in docs or "prefeitura" in docs:
        from compliance_agent.pcrj import pericia_pcrj
        pdfs = await pericia_pcrj.gerar_pdfs()   # uma análise só para os dois documentos
        for k in ("camara", "prefeitura"):
            if k in docs:
                saidas[k] = pdfs[k]
    if "consolidado" in docs:
        from compliance_agent.pcrj import pericia_beneficios
        saidas["consolidado"] = await pericia_beneficios.gerar_pdf()
    if "socios" in docs:
        from compliance_agent.pcrj import pericia_socios_beneficio
        saidas["socios"] = await pericia_socios_beneficio.gerar_pdf()

    if args.telegram and saidas:
        from compliance_agent.notifications.telegram import enviar_arquivo
        for k, path in saidas.items():
            await enviar_arquivo(str(path), caption=f"{_CAPTION[k]} — {date.today()}")

    for k, path in saidas.items():
        print(f"saída [{k}]: {path}")


if __name__ == "__main__":
    asyncio.run(main())
