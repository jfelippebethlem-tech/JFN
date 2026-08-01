#!/usr/bin/env python3
"""CLI do Avaliador de Processo 360 — o processo como um todo, fase a fase, despacho a despacho.

Uso:
  tools/processo_360.py --numero SEI-070026/000410/2021 [--com-llm] [--pdf] [--gravar]
  tools/processo_360.py --lote N [--gravar]      # N maiores processos do acervo por nº de docs
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

REPO = Path(__file__).resolve().parent.parent


def _imprimir(out: dict) -> None:
    if out.get("status") != "OK":
        print(f"{out.get('numero_sei')}: INDISPONÍVEL — {out.get('motivo')}")
        return
    print(f"== {out['numero_sei']} · score {out['score100']}/100 ({out['faixa']}) · "
          f"grau {out['grau']['grau']} · peça: {out['escalada'].get('peca')}")
    print(f"   fases: {out['fases']}")
    print(f"   acatamento: {out['acatamento'].get('veredito')} · suficiência: "
          f"{out['acatamento']['suficiencia']['veredito']}")
    for a in out["achados"][:10]:
        print(f"   - [{a.get('gravidade') or a.get('grau')}] {a['origem']}: {(a.get('diz') or '')[:100]}")
    cob = out["cobertura"]
    print(f"   cobertura: íntegra={cob['captura_integra']} · rodados={len(cob['detectores_rodados'])} "
          f"· indisponíveis={len(cob['indisponiveis'])}")
    if isinstance(out.get("llm"), dict):
        print(f"   llm: {out['llm'].get('n_selecionados')} docs julgados, "
              f"{out['llm'].get('problematicos')} problemáticos")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--numero")
    ap.add_argument("--lote", type=int)
    ap.add_argument("--com-llm", action="store_true")
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--gravar", action="store_true")
    ap.add_argument("--json", action="store_true", help="despeja o dict completo em JSON")
    args = ap.parse_args()

    from compliance_agent import processo_360

    alvos: list[str] = []
    if args.numero:
        alvos = [args.numero]
    elif args.lote:
        base = REPO / "data" / "sei_arquivo"
        tam = []
        for mf in base.glob("*/manifest.json"):
            try:
                man = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                continue
            tam.append((len(man.get("docs") or []), str(man.get("processo") or mf.parent.name)))
        alvos = [p for _, p in sorted(tam, reverse=True)[:args.lote]]
    else:
        print("informe --numero ou --lote N", file=sys.stderr)
        return 2

    for numero in alvos:
        out = processo_360.avaliar(numero, com_llm=args.com_llm)
        _imprimir(out)
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        if args.gravar and out.get("status") == "OK":
            processo_360.gravar(out)
            print("   ✔ gravado em processo_avaliacao")
        if args.pdf and out.get("status") == "OK":
            from tools.vm_guard import wait_until_safe
            ok, msg = wait_until_safe()
            if not ok:
                print(f"   vm_guard: {msg} — PDF adiado")
                continue
            from compliance_agent.reporting.processo_360_ctx import render_processo_ctx
            from compliance_agent.reporting.render_html import gerar_pdf
            slug = "".join(ch if ch.isalnum() else "_" for ch in out["numero_sei"]).strip("_")
            pdf = asyncio.run(gerar_pdf(render_processo_ctx(out), f"processo_{slug}"))
            print(f"   📄 {pdf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
