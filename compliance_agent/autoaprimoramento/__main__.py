# -*- coding: utf-8 -*-
"""CLI: python -m compliance_agent.autoaprimoramento <comando>

  ciclo [--dry-run] [--agentes PASTA ...] [-n 30]   roda o ciclo (real exige JFN_AUTOAPRIMORAMENTO=1)
  reexecutar CHAVE ... [--max-casos 40] [--gerador cascata|assinatura]
                                                    lições candidatas × campeão reexecutado com o MESMO gerador, na
                                                    VALIDAÇÃO, e veredito do portão (exige JFN_AUTOAPRIMORAMENTO=1)
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


def _gerador_assinatura():
    """Claude pela ASSINATURA (backend="cli": sem cair na API paga), dentro dos tetos e da contingência do
    `claude_motor` (tarefa "autoaprimoramento"). Trava ocupada ou prazo: tenta de novo; o resto levanta e o caso
    fica sem resposta (a reexecução incompleta não é julgada)."""
    from compliance_agent import direcionamento_cerebro as dc
    from compliance_agent.llm import claude_motor

    def gerar(prompt, sistema, timeout):
        for _ in range(3):
            r = claude_motor.pensar("autoaprimoramento", prompt, modelo=claude_motor.MODELO_VOLUME, sistema=sistema,
                                    backend="cli", timeout=300.0, espera=900.0)
            if r is not None:
                dc.ultimo_provedor, dc.ultimo_modelo = "claude", r.modelo     # proveniência da linha de sombra
                return r.texto
            if not claude_motor.ultimo_motivo.startswith(("ocupado", "passou do prazo")):
                from . import reexecucao
                reexecucao.MOTOR_FORA = claude_motor.ultimo_motivo[:200]     # para a rodada, não insiste caso a caso
                break
        raise RuntimeError(f"assinatura sem resposta: {claude_motor.ultimo_motivo[:120]}")
    return gerar


def _proximo_candidato() -> list[str]:
    """O candidato reexecutado há mais tempo (ou nunca) — `reexecutar proximo` julga um por noite."""
    con = ledger.conectar()
    try:
        registro.preparar(con)
        cands = [c for (c,) in con.execute("SELECT chave FROM versao WHERE status='candidato' ORDER BY n")]
    finally:
        con.close()
    pasta = config.dados() / "reexecucao"
    idade = {c: (pasta / f"{c}.json").stat().st_mtime if (pasta / f"{c}.json").exists() else 0.0 for c in cands}
    return sorted(cands, key=lambda c: idade[c])[:1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="autoaprimoramento")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("ciclo")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--agentes", nargs="*", default=[])
    c.add_argument("-n", type=int, default=30)
    rx = sub.add_parser("reexecutar")
    rx.add_argument("chaves", nargs="+")
    rx.add_argument("--max-casos", type=int, default=None)
    rx.add_argument("--gerador", choices=("cascata", "assinatura"), default="cascata")
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
    if a.cmd == "reexecutar":
        # cascata: a grátis de volume (gemini free tier → groq → openrouter:free …), a que gravou os laudos que as
        # lições querem corrigir. assinatura: o Claude de volume da perícia (co-motor), só pelo CLI — nunca a API.
        # Nos dois, sem fila do Opus e sem cruzamento (sombra).
        if a.gerador == "assinatura":
            gerar, nome = _gerador_assinatura(), "assinatura (claude_motor backend=cli, modelo de volume)"
        else:
            from compliance_agent.direcionamento_cerebro import gerar_sync
            gerar, nome = gerar_sync, "cascata grátis (direcionamento_cerebro.gerar_sync)"
        chaves = a.chaves
        if chaves == ["proximo"]:          # rodízio noturno: UM candidato por rodada, o reexecutado há mais tempo
            chaves = _proximo_candidato()
            if not chaves:
                print("nenhum candidato para reexecutar")
                return 0
        r = orquestrador.reexecutar(chaves, gerar, a.max_casos, gerador=nome)
        if "parado" in r:
            print(r["parado"])
            return 1
        print(f"reexecução: {r['chamadas_llm']} chamadas de LLM; detalhe em {config.dados()}/reexecucao/")
        if r.get("motor_fora"):
            print(f"  rodada interrompida — motor fora: {r['motor_fora']}")
        for cand in r["candidatos"]:
            print(f"  {cand['chave']} ({cand['casos']} casos): {cand['status']}")
            for g in (cand.get("portao") or {}).get("regras", []):
                print(f"    {'PASSA' if g['ok'] else 'FALHA'} · {g['regra']}: {g['detalhe']}")
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
