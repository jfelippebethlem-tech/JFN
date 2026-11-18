# -*- coding: utf-8 -*-
"""CLI: python -m compliance_agent.autoaprimoramento <comando>

  ciclo [--dry-run] [--agentes PASTA ...] [-n 30]   roda o ciclo (real exige JFN_AUTOAPRIMORAMENTO=1)
  status                                            versões, campeão, kill, último ciclo
  promover CHAVE --quem NOME                        sombra → campeão (ato humano)
  rollback --quem NOME --motivo TEXTO               volta ao campeão anterior
  matar MOTIVO                                      liga o kill switch (apague data/autoaprimoramento/KILL para religar)
  teste --quem NOME --motivo TEXTO                  mede a calibração no conjunto de TESTE (consulta registrada, com teto)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import calibracao, config, ledger, monitor, orquestrador, registro


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="autoaprimoramento")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("ciclo")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--agentes", nargs="*", default=[])
    c.add_argument("-n", type=int, default=30)
    sub.add_parser("status")
    p = sub.add_parser("promover")
    p.add_argument("chave")
    p.add_argument("--quem", required=True)
    rb = sub.add_parser("rollback")
    rb.add_argument("--quem", required=True)
    rb.add_argument("--motivo", required=True)
    m = sub.add_parser("matar")
    m.add_argument("motivo")
    t = sub.add_parser("teste")
    t.add_argument("--quem", required=True)
    t.add_argument("--motivo", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "ciclo":
        r = orquestrador.ciclo(dry_run=a.dry_run, pastas_agentes=[Path(x) for x in a.agentes], n_fila=a.n)
        if "parado" in r:
            print(r["parado"])
            return 1
        print(f"ciclo {'(ensaio) ' if a.dry_run else ''}ok — relatório em {r['pasta']}/relatorio.md")
        for cand in r["candidatos"]:
            print(f"  {cand['chave']}: {cand['status']}")
        return 0
    if a.cmd == "matar":
        print("KILL em", monitor.matar(a.motivo))
        return 0
    con = ledger.conectar()
    try:
        registro.preparar(con)
        if a.cmd == "status":
            print(json.dumps({"ligado": config.ligado(), "kill": config.morto(), "campeao": (registro.campeao(con) or {}).get("chave"),
                              "versoes": [dict(zip(("chave", "status"), x)) for x in con.execute(
                                  "SELECT chave,status FROM versao ORDER BY n")]}, ensure_ascii=False, indent=1))
        elif a.cmd == "promover":
            registro.promover(con, a.chave, a.quem)
            print("campeão:", a.chave)
        elif a.cmd == "rollback":
            print("campeão de volta:", registro.rollback(con, a.quem, a.motivo))
        elif a.cmd == "teste":
            rot = ledger.consultar_teste(con, a.quem, a.motivo)
            tab = calibracao.tabela(ledger.rotulos(con, ("treino", "validacao")))
            tr = ledger.rotulos(con, ("treino", "validacao"))
            base = sum(x["alto_verificado"] for x in tr) / len(tr) if tr else 0.0
            print(json.dumps(calibracao.avaliar(tab, rot, base), ensure_ascii=False, indent=1))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
