# -*- coding: utf-8 -*-
"""python -m compliance_agent.qualidade {regras|inventario|sensores|juiz|estado|doc|base}"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m compliance_agent.qualidade", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("regras", help="resumo das regras e defeitos do registro")
    sub.add_parser("inventario", help="o inventário em números e as dívidas")
    s = sub.add_parser("sensores", help="roda os sensores sobre o dado de produção")
    s.add_argument("--so", nargs="*", help="só estes sensores")
    s.add_argument("--sem-gravar", action="store_true")
    j = sub.add_parser("juiz", help="roda o juiz subjetivo (Claude pela ASSINATURA)")
    j.add_argument("-n", type=int, default=None, help="tamanho da amostra")
    j.add_argument("--so-amostra", action="store_true", help="mostra o que seria julgado, sem chamar o modelo")
    sub.add_parser("estado", help="painel de conformidade (JSON)")
    sub.add_parser("doc", help="regenera docs/REGRAS-DE-QUALIDADE.md")
    b = sub.add_parser("base", help="bases das catracas")
    b.add_argument("--apertar", action="store_true", help="regrava as bases sem nunca subir")
    a = ap.parse_args(argv)

    from compliance_agent.qualidade import regras
    if a.cmd == "regras":
        probs = regras.problemas()
        print(json.dumps(regras.resumo() | {"problemas": probs}, ensure_ascii=False, indent=1))
        return 1 if probs else 0
    if a.cmd == "inventario":
        from compliance_agent.qualidade import detectores, inventario
        print(json.dumps({"superficies": inventario.resumo(), "detectores": detectores.resumo()}, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "sensores":
        from compliance_agent.qualidade import sensores
        quais = {n: sensores.SENSORES[n] for n in a.so} if a.so else None
        est = sensores.rodar(sensores=quais, gravar=not a.sem_gravar)
        for v in est["violacoes"]:
            print(f"[{v['severidade']:10}] {v['regra']} {v['sistema']:10} {v['titulo']}\n             {v['detalhe']}")
        for n, m in est["cegos"].items():
            print(f"[SENSOR CEGO] {n}: {m}")
        print(f"\n{est['total']} violação(ões), {est['bloqueantes']} bloqueante(s), {len(est['cegos'])} sensor(es) cego(s)")
        print(json.dumps({"por_sistema": est["por_sistema"], "por_regra": est["por_regra"]}, ensure_ascii=False))
        return 0
    if a.cmd == "juiz":
        from compliance_agent.qualidade import juiz, sensores
        ctx = sensores.Ctx()
        if a.so_amostra:
            import pathlib
            arq = ctx.dados / "qualidade_juiz_historico.json"
            hist = json.loads(pathlib.Path(arq).read_text(encoding="utf-8")) if arq.exists() else {}
            cands = juiz.candidatas(ctx)
            for c in juiz.amostrar(cands, hist, a.n or juiz.AMOSTRA_PADRAO, ctx.agora):
                print(f"{c.risco:6.1f}  {c.id:50} {c.rotulo[:60]}")
            print(f"({len(cands)} candidatas)")
            return 0
        r = juiz.rodar(ctx, a.n or juiz.AMOSTRA_PADRAO)
        print(json.dumps({k: r[k] for k in r if k != "avaliacoes"}, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "estado":
        from compliance_agent.qualidade import estado
        print(json.dumps(estado.painel(), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "doc":
        from compliance_agent.qualidade import doc
        print(doc.gravar())
        return 0
    if a.cmd == "base":
        from compliance_agent.qualidade import catracas
        if not a.apertar:
            ap.error("use --apertar (a base nunca sobe por ferramenta)")
        for nome, (antes, depois) in catracas.apertar().items():
            print(f"{nome:28} {antes:6} → {depois:6}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
