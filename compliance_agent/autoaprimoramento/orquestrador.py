# -*- coding: utf-8 -*-
"""orquestrador — o ciclo: ledger → calibração → fraquezas → candidatos → portão → fila da fonte → monitor → relatório.

`ciclo(dry_run=True)` trabalha numa CÓPIA do ledger em `dryrun/` e não muda nada que a produção lê. O ciclo real só
roda com `JFN_AUTOAPRIMORAMENTO=1` e sem KILL. O ciclo nunca promove a campeão, nunca chama LLM por conta própria
(teto do ciclo = 0; a reexecução por prompt exige um gerador passado por quem chama) e nunca se reagenda."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from . import agentes, calibracao, config, importar, ledger, monitor, portao, reexecucao, registro, selecao


def ciclo(dry_run: bool = True, pastas_agentes: list[Path] | None = None, gerar=None, n_fila: int = 30,
          fontes: dict | None = None) -> dict:
    if config.morto():
        return {"parado": "kill switch ativo"}
    if not dry_run and not config.ligado():
        raise SystemExit("ciclo real recusado: defina JFN_AUTOAPRIMORAMENTO=1 (ou use --dry-run)")
    antigo = os.environ.get("JFN_AUTOAPRIMORAMENTO_DIR")
    if dry_run:
        real, seco = config.banco(), config.dados() / "dryrun"
        seco.mkdir(parents=True, exist_ok=True)
        if real.exists():
            shutil.copy2(real, seco / "auto.db")
        os.environ["JFN_AUTOAPRIMORAMENTO_DIR"] = str(seco)
    try:
        return _ciclo(dry_run, pastas_agentes, gerar, n_fila, fontes or {})
    finally:
        if dry_run:
            if antigo is None:
                os.environ.pop("JFN_AUTOAPRIMORAMENTO_DIR", None)
            else:
                os.environ["JFN_AUTOAPRIMORAMENTO_DIR"] = antigo


def _ciclo(dry_run, pastas_agentes, gerar, n_fila, fontes) -> dict:
    con = ledger.conectar()
    try:
        registro.preparar(con)
        r: dict = {"em": time.strftime("%Y-%m-%dT%H:%M:%S"), "dry_run": dry_run, "pasta": str(config.dados())}
        r["importacao"] = importar.tudo(con, pastas_agentes=pastas_agentes or [], **fontes)
        r["calibracao"] = calibracao.calibrar(con)
        fraq = agentes.pesquisa(con)
        r["fraquezas"] = {"descartes": fraq["descartes"], "armadilhas": fraq["armadilhas"],
                          "nao_classificadas": fraq["nao_classificadas"]}
        valid = ledger.rotulos(con, ("validacao",), com_texto=True)
        campeao = registro.campeao(con)["conteudo"]
        r["candidatos"] = []
        for c in agentes.propor(con, fraq):
            linha = {"chave": c["chave"], "como": c["como"], "armadilha": c["armadilha"], "hipotese": c["hipotese"]}
            if not c["revisao"]["aprovada"]:
                falhas = "; ".join(x["regra"] for x in c["revisao"]["checagens"] if not x["ok"])
                registro.mover(con, c["chave"], "reprovado", f"reprovado na revisão — {falhas}", "revisao")
                linha["status"] = "reprovado (revisão)"
            elif c["como"] == "filtros":
                ver = portao.julgar(reexecucao.por_filtros(valid, campeao, c["conteudo"]))
                linha["status"], linha["portao"] = registro.julgado(con, c["chave"], ver), ver
            elif gerar is not None:
                casos = reexecucao.por_prompt(valid, c["conteudo"], gerar, fontes.get("compliance_db"), campeao=campeao)
                ver = portao.julgar(casos)
                linha["status"], linha["portao"] = registro.julgado(con, c["chave"], ver), ver
            else:
                linha["status"] = "candidato (aguarda reexecução por prompt: teto de LLM do ciclo = 0)"
            r["candidatos"].append(linha)
        db = fontes.get("compliance_db")
        r["cruzamentos_novos"] = selecao.cruzar(con, db)
        fila = selecao.selecionar(con, n_fila, db)
        r["fila_fonte"] = {"itens": len(fila), "aleatorios": sum(1 for x in fila if x["amostra"] == "aleatoria")}
        selecao.marcar_conferidos(con)
        r["monitor"] = {"fonte_perdida": monitor.fonte_perdida(con, db), "deriva": monitor.deriva(con)}
        r["registro"] = [dict(zip(("chave", "status", "motivo"), x)) for x in con.execute(
            "SELECT chave, status, motivo FROM versao ORDER BY n")]
        (config.dados() / "ultimo_ciclo.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str),
                                                          encoding="utf-8")
        (config.dados() / "relatorio.md").write_text(relatorio(con, r, fila), encoding="utf-8")
        return r
    finally:
        con.close()


def reexecutar(chaves: list[str], gerar, max_casos: int | None = None, compliance_db: Path | None = None,
               gerador: str = "injetado") -> dict:
    """Reexecução por prompt de candidatos JÁ registrados (o ciclo só reexecuta o que acabou de propor) e veredito
    do PORTÃO: aprovado → sombra, senão → reprovado. Só no conjunto de VALIDAÇÃO; nunca promove. Reexecução que não
    chegou ao teto de casos (motor fora, cota acabou) não é julgada: o candidato segue `candidato` — falta de
    resposta não refuta a lição."""
    if config.morto():
        return {"parado": "kill switch ativo"}
    if not config.ligado():
        raise SystemExit("reexecução recusada: defina JFN_AUTOAPRIMORAMENTO=1 (ela muda o registro)")
    n_chamadas = [0]
    reexecucao.MOTOR_FORA = None

    def contado(p, s, t):
        n_chamadas[0] += 1
        return gerar(p, s, t)
    con = ledger.conectar()
    try:
        registro.preparar(con)
        campeao = registro.campeao(con)["conteudo"]
        versoes = {}
        for ch in chaves:
            v = registro.ler(con, ch)
            if v is None or v["status"] != "candidato":
                raise ValueError(f"{ch}: só candidato é reexecutado (status {v and v['status']})")
            if v["conteudo"].get("licoes") == campeao.get("licoes"):
                raise ValueError(f"{ch}: não muda lição — é julgado por filtros no ciclo")
            versoes[ch] = v["conteudo"]
        valid = ledger.rotulos(con, ("validacao",), com_texto=True)
        teto = min(max_casos or config.ORCAMENTO["max_casos_reexecucao"], len(valid))
        casos = reexecucao.por_prompt_pareado(valid, campeao, versoes, contado, compliance_db, teto)
        pasta = config.dados() / "reexecucao"
        pasta.mkdir(parents=True, exist_ok=True)
        r = {"em": time.strftime("%Y-%m-%dT%H:%M:%S"), "gerador": gerador, "conjunto": "validacao", "teto": teto,
             "campeao": registro.campeao(con)["chave"], "chamadas_llm": None, "candidatos": []}
        reais = min(teto, sum(int(bool(x["alto_verificado"])) for x in valid))
        for ch, cs in casos.items():
            linha = {"chave": ch, "licoes": versoes[ch]["licoes"], "casos": len(cs)}
            if len(cs) < teto or sum(c["real"] for c in cs) < reais:
                # um alto verdadeiro sem resposta faria a R2 reprovar por falha do motor, não da lição
                linha["status"] = (f"candidato (reexecução incompleta: {len(cs)} de {teto} casos, "
                                   f"{sum(c['real'] for c in cs)} de {reais} altos verdadeiros — não julgado)")
                linha["portao"] = None
            else:
                ver = portao.julgar(cs)
                linha["status"], linha["portao"] = registro.julgado(con, ch, ver), ver
            r["candidatos"].append(linha)
            (pasta / f"{ch}.json").write_text(json.dumps({**linha, "em": r["em"], "gerador": gerador, "detalhe": cs},
                                                         ensure_ascii=False, indent=1), encoding="utf-8")
        r["chamadas_llm"], r["motor_fora"] = n_chamadas[0], reexecucao.MOTOR_FORA
        (pasta / "ultima.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return r
    finally:
        con.close()


def _pct(c: dict | None) -> str:
    if not c or c["n"] < calibracao.N_MINIMO:
        return "INDISPONÍVEL" + (f" (n={c['n']})" if c else "")
    return f"{_v(c['p'] * 100)}% ({c['k']}/{c['n']}; IC 95% {_v(c['lo'] * 100)}–{_v(c['hi'] * 100)}%)"


def _v(x: float, casas: int = 1) -> str:
    return f"{x:.{casas}f}".replace(".", ",")


def _brl(v) -> str:
    return "—" if v is None else f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def relatorio(con, r: dict, fila: list[dict]) -> str:
    cal, val = r["calibracao"], r["calibracao"]["validacao"]
    n2 = con.execute("SELECT COUNT(DISTINCT numero_sei) FROM laudo_versao WHERE nivel_prova=2").fetchone()[0]
    pares = dict(con.execute("SELECT nivel_antes || '→' || nivel_depois, COUNT(*) FROM conferencia GROUP BY 1"))
    L = ["# JFN — Autoaprimoramento da perícia de execução", "",
         f"**Ciclo de {r['em']}** · {'ensaio (--dry-run)' if r['dry_run'] else 'real'} · gerado por "
         "`python -m compliance_agent.autoaprimoramento ciclo` · desenho em `docs/AUTOAPRIMORAMENTO-JFN.md`", "",
         "> Indício interno de controle. Nenhum número aqui é acusação; risco alto só é VERIFICADO com prova primária.", "",
         "## 1. Verdade de chão (ledger)", "",
         "| Item | Quantidade |", "|---|---:|",
         f"| Processos conferidos na fonte primária (nível 2) | {n2} |",
         f"| Pares laudo de volume → Opus sobre o resumo | {pares.get('0→1', 0)} |",
         f"| Pares laudo de volume → fonte primária | {pares.get('0→2', 0)} |",
         f"| Pares Opus sobre o resumo → fonte primária | {pares.get('1→2', 0)} |",
         f"| Indícios descartados na fonte, com o porquê | {r['fraquezas']['descartes']} |", "",
         "## 2. Calibração por motor — P(segue risco alto depois de conferido)", "",
         "| Motor | Faixa alta (nota ≥ 7) | Faixa média (4–6) |", "|---|---|---|"]
    for m, f in sorted(cal["motores_fracos"].items(), key=lambda kv: -(kv[1].get("alta") or {"n": 0})["n"]):
        nome = "**todos os modelos de volume**" if m == calibracao.TODOS else m
        L.append(f"| {nome} | {_pct(f.get('alta'))} | {_pct(f.get('media'))} |")
    L += [f"| **Opus sobre o resumo → fonte primária** | {_pct(cal['opus_resumo'].get('alta'))} | "
          f"{_pct(cal['opus_resumo'].get('media'))} |", ""]
    d = cal.get("fonte_primaria_duas_fases") or {}
    if "p" in d:
        L += [f"**Risco alto de modelo de volume confirmado na FONTE (duas fases):** {_v(d['p'] * 100)}% "
              f"(IC 95% {_v(d['lo'] * 100)}–{_v(d['hi'] * 100)}%) — de {d['fraco_alto_opus_manteve'][1]} altos de volume o "
              f"Opus manteve {d['fraco_alto_opus_manteve'][0]}; a fonte confirmou {d['opus_alto_fonte_confirmou'][0]} de "
              f"{d['opus_alto_fonte_confirmou'][1]} altos do Opus e achou alto em {d['opus_baixo_fonte_achou_alto'][0]} de "
              f"{d['opus_baixo_fonte_achou_alto'][1]} que o Opus tinha baixado.", ""]
    else:
        L += [f"**Duas fases:** INDISPONÍVEL — {d.get('indisponivel', 'sem amostra')}.", ""]
    if val.get("n"):
        L += [f"**Validação (conjunto que não ajustou a tabela, {val['n']} laudos, {val['altos_verdadeiros']} altos "
              f"verdadeiros):** Brier da nota verbalizada {_v(val['brier_verbalizada'], 4)} → calibrada "
              f"{_v(val['brier_calibrada'], 4)} (dizer sempre a taxa-base: {_v(val['brier_taxa_base'], 4)}).", ""]
    L += ["Faixas certificadas para sair como risco alto sem ir à fonte: "
          + (", ".join(c["motor"] for c in cal["certificadas"]) or "**nenhuma**") + ".", "",
          "## 3. Armadilhas (indícios que caíram na fonte primária)", "", "| Armadilha | Processos |", "|---|---:|"]
    L += [f"| {a['nome']} | {a['processos']} |" for a in r["fraquezas"]["armadilhas"]]
    L += ["", "## 4. Candidatos do ciclo e veredito do portão", ""]
    for c in r["candidatos"] or []:
        L.append(f"- `{c['chave']}` ({c['como']}: {c['armadilha']}) — **{c['status']}**")
        for g in (c.get("portao") or {}).get("regras", []):
            L.append(f"  - {'PASSA' if g['ok'] else 'FALHA'} · {g['regra']}: {g['detalhe']}")
    if not r["candidatos"]:
        L.append("Nenhum candidato novo (todas as propostas possíveis já foram tentadas).")
    L += ["", "## 5. Fila da fonte primária (próximas conferências)", "",
          "| Processo | Amostra | Nota | Motor | Pago (SIAFE) | Por quê |", "|---|---|---:|---|---:|---|"]
    for x in sorted(fila, key=lambda x: (x["amostra"] != "dirigida", -(x["pontuacao"] or 0)))[:30]:
        L.append(f"| {x['numero_sei']} | {x['amostra']} | {x['nota']} | {x['motor']} | {_brl(x['valor_pago'])} | "
                 f"{(x['motivo'] or '')[:160]} |")
    L += ["", selecao.roteiro()]
    fp = r["monitor"]["fonte_perdida"]
    L += ["", "## 6. Monitor", "",
          f"- Prova primária regravada por juízo mais fraco: **{len(fp)}** processo(s)" + (f" — {', '.join(fp[:8])}"
                                                                                           + ("…" if len(fp) > 8 else "") if fp else ""),
          f"- Deriva: {r['monitor']['deriva'][0].get('estado')} {r['monitor']['deriva'][0].get('detalhe', '')}",
          f"- Cruzamentos novos (mesmo credor de risco alto confirmado): {r['cruzamentos_novos']}", "",
          "## 7. Registro de versões", "", "| Versão | Status | Motivo |", "|---|---|---|"]
    L += [f"| `{v['chave']}` | {v['status']} | {(v['motivo'] or '')[:140]} |" for v in r["registro"]]
    L += ["", "Fontes: `data/compliance.db` (lex_execucao, ob_orcamentaria_siafe), `data/conferencia_opus.db`, "
              "`data/cruzamento_motores.db`, `data/conferir_85.log`, laudos de agentes na fonte primária.", ""]
    return "\n".join(L)
