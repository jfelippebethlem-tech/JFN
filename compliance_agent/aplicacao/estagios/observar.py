# -*- coding: utf-8 -*-
"""E18 `observar` — sensores contínuos → `fluxo.metricas`, julgados pelos SLOs (plano mestre v2 §3.2 E18, §9 O8.1).

Entrada: `observar` (payload {} ou {"grupos": [...], "forcar": bool}). Saída e efeito: as linhas de UMA coleta dos
sensores do nó em `fluxo.metricas(no, nome, valor, quando, rotulos)`, cada uma com o estado honesto contra
config/slos.yaml (SAUDAVEL/DEGRADADO/ATRASADO/BLOQUEADO/INDISPONIVEL — sensor sem dado grava NaN + INDISPONIVEL, nunca
0 nem "ok"). Os sensores moram em `compliance_agent/fluxo/sensores.py`; este módulo é só o contrato do estágio:
  · handler idempotente pela posse (`chave#ficha` = etiqueta `coleta`): reexecutar o mesmo job (outra ficha) é OUTRA
    coleta — série temporal, não estado;
  · efeito conferido em outra leitura do PG: as linhas com a etiqueta desta coleta existem e são exatamente as
    declaradas (> 0);
  · recursos `cpu_leve`, em todos os nós; volta `vm1`/`vm2`;
  · evento `observar/metricas` (a automelhoria da O8.4 consome).
Absorve os 14 vigias (ronda, painel_vigia, guardiao, keepalive, handoff_watcher, vm_guard, automelhoria_geral,
pipelines_slo…): mapa vigia → sensor → aposentadoria na O9 em ~/vault/refatoracao/vigias-para-sensores.md.

CLI (a rotina `observar_<nó>` do config/fluxo.yaml roda `coletar`; INATIVA até a O9.0):
    python -m compliance_agent.aplicacao.estagios.observar coletar --no vm1 [--grupo psi ...] [--forcar]
    python -m compliance_agent.aplicacao.estagios.observar medir --no itcampo --grupo psi --grupo disco > m.json
    python -m compliance_agent.aplicacao.estagios.observar gravar --medidas m.json    # nó sem psycopg: outro grava
    python -m compliance_agent.aplicacao.estagios.observar quadro                     # estado por SLO (só leitura)
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from compliance_agent.aplicacao.estagios import Contexto, Estagio
from compliance_agent.fluxo import fila
from compliance_agent.fluxo.fila import Resultado

TIPO = "observar"


def _handler(payload: dict, ctx: Contexto) -> Resultado:
    """Uma coleta dos sensores do nó. A etiqueta `coleta` deriva da chave + ficha."""
    from compliance_agent.fluxo import sensores
    con = fila.conectar()
    try:
        r = sensores.coletar(con, ctx.no, grupos=payload.get("grupos") or None, forcar=bool(payload.get("forcar")),
                             coleta=f"{ctx.chave}#{ctx.ficha}")
    finally:
        con.close()
    return Resultado(efeito={"coleta": r["coleta"], "gravadas": r["gravadas"], "pulados": r["pulados"]},
                     eventos=[{"fonte": "observar", "tipo": "metricas", "chave": r["coleta"]}])


def _efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    """Relê o PG: as linhas com a etiqueta desta coleta existem e são exatamente as declaradas (> 0)."""
    from compliance_agent.fluxo import sensores
    declaradas = int(resultado.efeito.get("gravadas") or 0)
    con = fila.conectar()
    try:
        n = sensores.contar_coleta(con, str(resultado.efeito.get("coleta") or ""))
    finally:
        con.close()
    return declaradas > 0 and n == declaradas


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["cpu_leve"], prioridade=25,
                  volta={"nos": ["vm1", "vm2"]})


def quadro(estado: dict) -> str:
    """Quadro de texto do estado por SLO (o mesmo julgamento de /api/sistema/slos). Puro."""
    linhas = [f"estado global: {estado['estado']} — {estado['motivo']}",
              "contagem: " + " · ".join(f"{k} {v}" for k, v in estado["contagem"].items()), ""]
    for i in sorted(estado["itens"], key=lambda x: (x["slo"], str(x.get("no")))):
        v = "—" if i.get("valor") is None else f"{i['valor']:g}"
        linhas.append(f"{i['estado']:<12} {i['slo']:<26} {str(i.get('no') or '-'):<8} {v:>12} {i['unidade']:<9} "
                      f"{str(i.get('motivo') or '')[:110]}")
    return "\n".join(linhas)


def _rodar_contrato(no: str, payload: dict) -> tuple[Resultado, bool]:
    """Handler + efeito pelo contrato, fora do motor (a rotina legado:observar_* até o grafo agendar tipo nativo):
    posse sintética `observar:<nó>` com ficha = epoch em ms (única por execução)."""
    ctx = Contexto(no=no, tipo=TIPO, chave=f"{TIPO}:{no}", ficha=int(time.time() * 1000), tentativa=1)
    r = ESTAGIO.handler(payload, ctx)
    return r, ESTAGIO.efeito(payload, ctx, r)


def main(argv: list[str] | None = None) -> int:
    from compliance_agent.fluxo import sensores as S
    ap = argparse.ArgumentParser(prog="python -m compliance_agent.aplicacao.estagios.observar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome in ("coletar", "medir"):
        c = sub.add_parser(nome)
        c.add_argument("--no", required=True, choices=S.NOS_FLUXO)
        c.add_argument("--grupo", action="append", choices=sorted(S.GRUPOS), default=None)
        c.add_argument("--forcar", action="store_true", help="ignora o espaçamento dos sensores caros")
    g = sub.add_parser("gravar")
    g.add_argument("--medidas", required=True, help="JSON de `medir` (nó sem psycopg)")
    q = sub.add_parser("quadro")
    q.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "medir":                      # sem PG: só o que não depende dele (o PG completa a tendência ao gravar)
        m = S.medir(None, a.no, S.carregar_slos(), grupos=a.grupo, forcar=a.forcar)
        print(json.dumps(m, ensure_ascii=False, default=str))
        return 0
    if a.cmd == "coletar":
        r, ok = _rodar_contrato(a.no, {"grupos": a.grupo or [], "forcar": a.forcar})
        print(json.dumps(r.efeito, ensure_ascii=False, default=str))
        if not ok:
            print(f"observar: efeito NÃO conferido (coleta {r.efeito.get('coleta')})", file=sys.stderr)
            return 1
        # a linha que a rotina legado:observar_* confere no log (efeito.log_contem) — só sai depois da recontagem
        print(f"observar: {r.efeito['gravadas']} linha(s) conferida(s) em fluxo.metricas (coleta {r.efeito['coleta']})")
        return 0
    slos = S.carregar_slos()
    con = fila.conectar()
    try:
        if a.cmd == "gravar":
            with open(a.medidas, encoding="utf-8") as f:
                m = json.load(f)
            r = S.gravar_medidas(con, m, slos)
            print(json.dumps(r, ensure_ascii=False, default=str))
            if r["conferidas"] != r["gravadas"] or not r["gravadas"]:
                print(f"observar: efeito NÃO conferido ({r['conferidas']} de {r['gravadas']})", file=sys.stderr)
                return 1
            print(f"observar: {r['conferidas']} linha(s) conferida(s) em fluxo.metricas (coleta {r['coleta']})")
            return 0
        est = S.estado_slos(S.ler_ultimos(con, slos), slos)
    finally:
        con.close()
    print(json.dumps(est, ensure_ascii=False, indent=1, default=str) if a.json else quadro(est))
    return 0


if __name__ == "__main__":
    sys.exit(main())
