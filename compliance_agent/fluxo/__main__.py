# -*- coding: utf-8 -*-
"""CLI do motor de fluxo.

    python -m compliance_agent.fluxo supervisor --no vm1 [--uma-volta] [--isolamento auto|systemd|subprocesso]
    python -m compliance_agent.fluxo saude [--esperados vm1,vm2,itcampo]   # padrão: os nós do yaml
    python -m compliance_agent.fluxo eco <chave>        # enfileira um job E0 de teste (prova ponta a ponta)
    python -m compliance_agent.fluxo agenda sincronizar  # fluxo.agenda ← config/fluxo.yaml (linha nova: ativo=false)
    python -m compliance_agent.fluxo ritmo medir|status  # assinatura: mede e publica em fluxo.metricas / o que o motor lê
O schema: `python -m compliance_agent.fluxo.schema verificar|aplicar`.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from compliance_agent.fluxo import fila, planejador
from compliance_agent.fluxo.supervisor import Supervisor


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m compliance_agent.fluxo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("supervisor")
    s.add_argument("--no", required=True)
    s.add_argument("--uma-volta", action="store_true", help="uma volta, espera os filhos dela e sai")
    s.add_argument("--isolamento", default="auto", choices=("auto", "systemd", "subprocesso"))
    h = sub.add_parser("saude")
    h.add_argument("--esperados", default="")
    e = sub.add_parser("eco")
    e.add_argument("chave")
    ag = sub.add_parser("agenda")
    ag_sub = ag.add_subparsers(dest="acao", required=True)
    sinc = ag_sub.add_parser("sincronizar", help="grava a agenda do yaml; linha nova entra DESLIGADA (O9.0 religa)")
    sinc.add_argument("--grafo", default=None, help="caminho do fluxo.yaml (padrão: config/fluxo.yaml)")
    rt = sub.add_parser("ritmo", help="ritmo da assinatura no PG (fluxo/ritmo.py)")
    rt.add_argument("acao", choices=("medir", "status"))
    rt.add_argument("--no", default="vm1")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if a.cmd == "supervisor":
        sup = Supervisor(no=a.no, isolamento=a.isolamento)
        if a.uma_volta:
            r = sup.uma_volta()
            r["drenados"] = sup.drenar()
            sup.fechar()
            print(json.dumps(r, ensure_ascii=False, default=str))
            return 0
        sup.rodar()
        return 0
    con = fila.conectar()
    try:
        if a.cmd == "saude":
            from compliance_agent.fluxo import grafo
            g = grafo.carregar()
            r = planejador.saude(con, tuple(n for n in a.esperados.split(",") if n) or tuple(g.nos),
                                 g.grafo_planejador(), g.terminais(), g.dividas())
        elif a.cmd == "agenda":
            from compliance_agent.fluxo import grafo
            r = {"esquema": fila.esquema_vigente(),
                 **planejador.sincronizar_agenda(con, grafo.carregar(a.grafo).agenda_linhas())}
        elif a.cmd == "ritmo":
            from compliance_agent.fluxo import ritmo
            if a.acao == "medir":
                r = ritmo.medir_e_publicar(con, a.no)
            else:
                m, idade = ritmo.ler(con)
                r = {"medicao": m, "idade_s": idade,
                     "motivo_por_tarefa": {t: ritmo.motivo(con, t) for t in ("triagem", "conferencia_opus", "canario")}}
        else:
            r = {"id": fila.enfileirar(con, "eco", f"eco:{a.chave}", {"origem": "cli"})}
    finally:
        con.close()
    print(json.dumps(r, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
