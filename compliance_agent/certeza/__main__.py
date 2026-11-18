# -*- coding: utf-8 -*-
"""CLI da certeza.

    python -m compliance_agent.certeza ciclo            # o que o despachante roda (grava data/certeza/estado.json)
    python -m compliance_agent.certeza estado           # resumo do último ciclo
    python -m compliance_agent.certeza fato <id>        # versões de um fato + como citar
    python -m compliance_agent.certeza citar <trecho>   # lista os fatos cujo id contém o trecho, prontos para colar
    python -m compliance_agent.certeza grafo            # auditoria do grafo agora (só leitura)
    python -m compliance_agent.certeza gatilhos [--aplicar]   # DDL dos gatilhos de faixa (aplicar exige JFN_CERTEZA_GATILHOS=1)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime

from . import citacoes, config, fatos, grafo, orquestrador, portoes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="certeza", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ciclo")
    sub.add_parser("estado")
    sub.add_parser("grafo")
    sub.add_parser("fato").add_argument("id")
    sub.add_parser("citar").add_argument("trecho")
    g = sub.add_parser("gatilhos")
    g.add_argument("--aplicar", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "ciclo":
        est = orquestrador.ciclo()
        print(json.dumps({"resumo": est["resumo"], "ciclo": {k: v for k, v in est["ciclo"].items() if k != "extracao"},
                          "extracao": {k: v for k, v in est["ciclo"]["extracao"].items() if k not in ("mudancas", "recusas")}},
                         ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "estado":
        est = orquestrador.ler_estado()
        print(json.dumps(est.get("resumo") or est, ensure_ascii=False, indent=1))
        return 0 if est.get("ok") else 1
    if a.cmd == "grafo":
        from compliance_agent import propagacao
        r = grafo.auditar(estado_prop=propagacao.estado())
        print(json.dumps({"resumo": r["resumo"], "achados": r["achados"], "indisponiveis": r["indisponiveis"]}, ensure_ascii=False, indent=1))
        return 0
    if a.cmd in ("fato", "citar"):
        con = fatos.conectar()
        try:
            if a.cmd == "fato":
                hist = fatos.historico(con, a.id)
                if not hist:
                    print(f"fato {a.id!r} não está no registro", file=sys.stderr)
                    return 1
                for h in hist:
                    print(f"v{h['id']} · {datetime.fromtimestamp(h['registrado_em']):%Y-%m-%d %H:%M} · "
                          f"{fatos.formatar(h['valor'], h['unidade'])} · {h['estado']} · nível {h['nivel_prova']} · {h['produtor']}")
                print("fonte:", hist[-1]["fonte"], "\nconsulta:", hist[-1]["consulta"], "\ncitar:", citacoes.citar(hist[-1]))
            else:
                for f in fatos.vigentes(con):
                    if a.trecho.lower() in (f["fato_id"] + " " + (f["rotulo"] or "")).lower() and f["valor"] is not None:
                        print(f"{f['rotulo']}\n    {citacoes.citar(f)}")
        finally:
            con.close()
        return 0
    if a.cmd == "gatilhos":
        from compliance_agent import propagacao
        ddl = [d for cid, c in (propagacao.carregar().get("contratos") or {}).items() for d in portoes.ddl_gatilhos(cid, c)]
        print(";\n".join(ddl) + ";")
        if a.aplicar:
            if not config.ligado("GATILHOS"):
                print("NÃO aplicado: exige JFN_CERTEZA_GATILHOS=1 (decisão do dono — muda o comportamento de quem escreve)", file=sys.stderr)
                return 2
            con = sqlite3.connect(config.REPO / "data" / "compliance.db", timeout=60)
            try:
                for d in ddl:
                    con.execute(d)
                con.commit()
            finally:
                con.close()
            print(f"{len(ddl)} gatilho(s) instalado(s)", file=sys.stderr)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
