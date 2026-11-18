# -*- coding: utf-8 -*-
"""agentes — Pesquisa → Hipótese → Código → Revisão. Só escrevem em `candidatos/`; nenhum aprova nada.

Por padrão são DETERMINÍSTICOS (teto de LLM do ciclo = 0): a Pesquisa lê o ledger, a Hipótese é um molde
falsificável, o Código monta a versão a partir da taxonomia e a Revisão é uma lista de checagens. A redação de
armadilha NOVA (descartes que a taxonomia não explica) sai como proposta em arquivo — entra na taxonomia por commit
revisado, e na produção só pelo portão."""
from __future__ import annotations

import json
import re
import time

from . import armadilhas, calibracao, config, ledger, registro

MIN_PROCESSOS_LICAO = 3      # a lição nasce de pelo menos 3 processos conferidos na fonte (nunca de um caso só)
_RE_ACUSA = re.compile(r"fraud|crime|corrup|desvi[oa]|culpad|superfatur|il[ií]cit", re.I)
_RE_INJECAO = re.compile(r"ignor[ea]|desconsider[ea] as regras|responda sempre|nota (0|zero) sempre", re.I)


def pesquisa(con) -> dict:
    """Relatório de fraquezas (só treino+validação; o teste não entra)."""
    visiveis = ("treino", "validacao")
    desc = [{"numero_sei": ns, "armadilha": a, "porque": p, "texto": t} for ns, a, p, t in con.execute(
        "SELECT numero_sei, armadilha, porque, texto FROM indicio_conferido WHERE desfecho='descartado'")
        if ledger.conjunto_de(ns) in visiveis]
    por: dict[str, set] = {}
    for d in desc:
        por.setdefault(d["armadilha"], set()).add(d["numero_sei"])
    cal = calibracao.carregar() or {}
    motores = [{"motor": m, **f["alta"]} for m, f in (cal.get("motores_fracos") or {}).items()
               if "alta" in f and f["alta"]["n"] >= calibracao.N_MINIMO]
    r = {"gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "descartes": len(desc), "confirmados": con.execute(
             "SELECT COUNT(*) FROM indicio_conferido WHERE desfecho='confirmado'").fetchone()[0],
         "armadilhas": sorted(({"id": a, "nome": armadilhas.POR_ID[a]["nome"] if a in armadilhas.POR_ID else a,
                                "processos": len(ps), "tem_filtro": bool(a in armadilhas.POR_ID and
                                                                         armadilhas.POR_ID[a]["indicio"])}
                               for a, ps in por.items()), key=lambda x: -x["processos"]),
         "nao_classificadas": armadilhas.candidatas(desc),
         "motores_alto": sorted(motores, key=lambda x: x["p"]),
         "validacao": cal.get("validacao"), "fonte_primaria_duas_fases": cal.get("fonte_primaria_duas_fases")}
    (config.dados() / "relatorio_fraquezas.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return r


def hipotese(arm: dict, como: str) -> str:
    alvo = "o padrão de indício dela rebaixar o laudo fraco" if como == "filtros" else "a lição dela entrar no prompt"
    g = config.PORTAO
    return (f"Se {alvo} — armadilha '{arm['nome']}', medida em {arm['processos']} processos conferidos na fonte —, os "
            f"falsos riscos altos caem pelo menos {g['melhora_minima'] * 100:.0f}% no conjunto de validação sem perder "
            f"nenhum risco alto verdadeiro. REFUTADA se: perder um alto verdadeiro, a queda não passar no McNemar exato "
            f"(p ≤ {g['p_mcnemar']}), ou a melhora não aparecer nas duas metades do conjunto.")


def revisar(con, conteudo: dict, fraquezas: dict) -> dict:
    """Checagens determinísticas da proposta. Reprovada aqui nem chega ao portão."""
    suporte = {a["id"]: a["processos"] for a in fraquezas["armadilhas"]}
    ativos = (conteudo.get("licoes") or []) + (conteudo.get("filtros") or [])
    licoes = [armadilhas.POR_ID[i]["licao"] for i in conteudo.get("licoes") or [] if i in armadilhas.POR_ID]
    c = [("taxonomia", all(i in armadilhas.POR_ID for i in ativos), "todo id está na taxonomia"),
         ("suporte", all(suporte.get(i, 0) >= MIN_PROCESSOS_LICAO for i in ativos),
          f"cada armadilha tem ≥ {MIN_PROCESSOS_LICAO} processos conferidos na fonte"),
         ("teto", len(conteudo.get("licoes") or []) <= config.ORCAMENTO["max_licoes_ativas"],
          f"no máximo {config.ORCAMENTO['max_licoes_ativas']} lições ativas"),
         ("tamanho", all(len(x) <= 320 for x in licoes), "lição com até 320 caracteres"),
         ("neutralidade", not any(_RE_ACUSA.search(x) for x in licoes), "lição sem termo acusatório"),
         ("instrução", not any(_RE_INJECAO.search(x) for x in licoes), "lição não manda ignorar regra nem fixa nota")]
    return {"aprovada": all(ok for _, ok, _ in c), "checagens": [{"item": a, "ok": bool(b), "regra": d} for a, b, d in c]}


def propor(con, fraquezas: dict, max_candidatos: int | None = None) -> list[dict]:
    """Código: uma versão candidata por armadilha mais frequente ainda não tentada (filtro quando ela tem padrão de
    indício — dá para medir sem LLM —, e lição no prompt). Grava candidatos/<chave>/ e registra como 'candidato'."""
    registro.preparar(con)
    base = registro.campeao(con)["conteudo"]
    teto = max_candidatos or config.ORCAMENTO["max_candidatos_ciclo"]
    out = []
    for arm in fraquezas["armadilhas"]:
        if len(out) >= teto:
            break
        if arm["id"] not in armadilhas.POR_ID or arm["processos"] < MIN_PROCESSOS_LICAO:
            continue
        for como in (("filtros",) if arm["tem_filtro"] else ()) + ("licoes",):
            if len(out) >= teto or arm["id"] in base.get(como, []):
                continue
            conteudo = {**base, como: sorted(set(base.get(como, [])) | {arm["id"]}),
                        "nota": f"{como}: + {arm['id']}"}
            antes = con.execute("SELECT COUNT(*) FROM versao").fetchone()[0]
            chave = registro.registrar(con, conteudo, f"agentes: armadilha {arm['id']} ({arm['processos']} processos)")
            if con.execute("SELECT COUNT(*) FROM versao").fetchone()[0] == antes:
                continue                                      # já tentada (aprovada ou reprovada): não repete
            hip, rev = hipotese(arm, como), revisar(con, conteudo, fraquezas)
            pasta = config.candidatos() / chave
            pasta.mkdir(parents=True, exist_ok=True)
            (pasta / "versao.json").write_text(json.dumps(conteudo, ensure_ascii=False, indent=1), encoding="utf-8")
            (pasta / "hipotese.md").write_text(f"# {chave}\n\n{hip}\n\nLição: {armadilhas.POR_ID[arm['id']]['licao']}\n",
                                               encoding="utf-8")
            (pasta / "revisao.json").write_text(json.dumps(rev, ensure_ascii=False, indent=1), encoding="utf-8")
            out.append({"chave": chave, "como": como, "armadilha": arm["id"], "conteudo": conteudo, "hipotese": hip,
                        "revisao": rev})
    for cand in fraquezas.get("nao_classificadas") or []:
        p = config.candidatos() / "armadilhas_novas"
        p.mkdir(parents=True, exist_ok=True)
        (p / f"proposta_{'_'.join(cand['termos'])}.md").write_text(
            f"# Armadilha candidata: {' + '.join(cand['termos'])}\n\n{cand['processos']} processos conferidos na fonte "
            "com descartes que a taxonomia não explica.\n\nExemplos do porquê:\n"
            + "\n".join(f"- {e}" for e in cand["exemplos"])
            + "\n\nPara virar armadilha: nome, regex do porquê, lição (≤ 320 caracteres, sem termo acusatório) em "
              "`compliance_agent/autoaprimoramento/armadilhas.py`, com teste de controle positivo e negativo.\n",
            encoding="utf-8")
    return out
