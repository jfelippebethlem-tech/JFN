#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ranking de TAC por unidade — quem paga FORA de contrato regular, e quanto fora da curva está.

POR QUE EXISTE. `detector_tac.tac_por_ug` responde por UMA unidade, dentro do `/orgao`. Ninguém
conseguia ver o **comparativo**, e sem comparativo um percentual não significa nada: 27% é muito?
É pouco? Medido em 2026-08-04, respondendo a essa pergunta pela primeira vez:

    294200 FUNDAÇÃO SAÚDE DO ESTADO DO RJ ....  27,0%  (R$ 2,81 bi de R$ 10,41 bi)
    310100 Secretaria de Transportes .........  15,8%
    370200 Encargos Gerais do Estado ........   10,1%
    296100 FUNDO ESTADUAL DA SAÚDE ..........    2,8%  (R$ 31,65 bi movimentados)
    ... 18 das 22 maiores unidades abaixo de 1% ...

A Fundação Saúde não é "a saúde sendo assim": a OUTRA unidade de saúde, três vezes maior, paga
2,8%. Dentro da própria saúde, a FSERJ está **dez vezes acima**. É a prevalência que decide o eixo
— um número sozinho não sustenta afirmação nenhuma.

CUSTO E DESENHO. O marcador de TAC mora no texto livre da observação da OB e a definição canônica
é a regex de `reporting.detector_tac` — que NÃO se reescreve em SQL, sob pena de duas definições
divergirem em silêncio. Então: UMA passada lendo (ug, valor, observação) e a regex aplicada em
Python, gravando um JSON. A rota lê o JSON; o cálculo nunca acontece dentro do request.

HONESTIDADE. VALOR = OB paga do SIAFE (`ob_orcamentaria_siafe`, régua única `cruzamentos_intel._ob_paga`) —
numerador e denominador. O espelho TFE entra SÓ como texto: a observação da OB (onde o marcador de TAC vive) é
lida da mesma OB no espelho (número + UG); OB do SIAFE sem par no espelho conta como "sem observação". Unidade
sem observação preenchida sai como INDISPONÍVEL, nunca como 0%. O SIAFE da casa cobre 2021+ (antes, só a ALERJ):
2019–2020 ficam fora e cada unidade traz os exercícios que o SIAFE não tem inteiros (`cobertura_siafe`).
Medido em 20/11/2026: o espelho dava 57 unidades acima de R$ 300 mi, mediana 0,3%; ver `docs/untangle`.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SAIDA = REPO / "data" / "tac_ranking_ugs.json"
MIN_VALOR = 300_000_000.0
"""Piso de movimentação para entrar no ranking: abaixo disso o percentual é ruído — uma unidade
que pagou R$ 2 mi, sendo R$ 1 mi por TAC, "lidera" com 50% e não diz nada."""


_TERCEIRO = "length(s.credor) IN (11, 14) AND s.credor NOT GLOB '*[^0-9]*'"
"""Credor TERCEIRO (CNPJ/CPF). O SIAFE lista também o que o espelho não lista: repasse entre unidades (credor = UG
de 6 dígitos — FES→FSERJ R$ 15 bi), folha e precatório (códigos 'CG…'/'EC…'). Medido em 20/11/2026: sem este
corte o universo ia de R$ 135 bi (espelho) a R$ 421 bi e a taxa de TAC caía por diluição em transferência
interna — o ranking compara o que a unidade paga a fornecedor/pessoa, como sempre comparou."""


def medir(db: str | Path | None = None, *, min_valor: float = MIN_VALOR) -> dict:
    from compliance_agent.cruzamentos_intel import _ob_paga
    from compliance_agent.reporting.cobertura_siafe import ANO_EMISSAO_SIAFE, estados_dos_pares
    from compliance_agent.reporting.detector_tac import _RX_TAC
    from compliance_agent.ugs import nome_canonico

    caminho = Path(db or os.environ.get("JFN_DB") or REPO / "data" / "compliance.db")
    if not caminho.exists():
        return {"ok": False, "indisponivel": True, "motivo": "compliance.db ausente"}

    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        if not {r[1] for r in con.execute("PRAGMA table_info(ob_orcamentaria_siafe)")}:
            return {"ok": True, "indisponivel": True,
                    "motivo": "`ob_orcamentaria_siafe` ausente — sem a fonte de pagamento não há o que somar"}
        cols = {r[1] for r in con.execute("PRAGMA table_info(ordens_bancarias)")}
        if "observacao" not in cols:
            return {"ok": True, "indisponivel": True,
                    "motivo": "coluna `observacao` do espelho ausente — o marcador de TAC só existe nela"}
        acc: dict[str, dict] = {}
        anos: dict[str, set] = {}
        # valor do SIAFE; do espelho, só o TEXTO da mesma OB (número + UG) — e o nome da UG, que o SIAFE não traz
        for ug, valor, ano, texto, nome in con.execute(
                f"SELECT s.ug_emitente, s.valor, {ANO_EMISSAO_SIAFE.replace('data_emissao', 's.data_emissao')}, "
                "(SELECT t.observacao FROM ordens_bancarias t WHERE t.numero_ob=s.numero_ob "
                " AND t.ug_codigo=s.ug_emitente LIMIT 1), "
                "(SELECT t.ug_nome FROM ordens_bancarias t WHERE t.numero_ob=s.numero_ob "
                " AND t.ug_codigo=s.ug_emitente LIMIT 1) "
                f"FROM ob_orcamentaria_siafe s WHERE {_ob_paga(con, 's')} AND {_TERCEIRO}"):
            d = acc.setdefault(str(ug or "?"), {"nome": "", "n": 0, "n_tac": 0,
                                                "total": 0.0, "total_tac": 0.0, "sem_obs": 0})
            anos.setdefault(str(ug or "?"), set()).add(str(ano))
            if nome and not d["nome"]:
                d["nome"] = str(nome)
            v = float(valor or 0)
            d["n"] += 1
            d["total"] += v
            if not texto:
                d["sem_obs"] += 1
            elif _RX_TAC.search(str(texto)):
                d["n_tac"] += 1
                d["total_tac"] += v
        # UG que o espelho conhece de 2021 em diante e o SIAFE da casa nunca leu: fora do ranking, DITO (não é 0%)
        lidas = set(acc)
        fora = sorted({str(u) for (u,) in con.execute(
            "SELECT DISTINCT ug_codigo FROM ordens_bancarias WHERE substr(data_emissao,1,4)>='2021'")} - lidas)
    finally:
        con.close()

    grandes = {ug: d for ug, d in acc.items() if d["total"] >= min_valor}
    est = estados_dos_pares({(ug, a) for ug in grandes for a in anos.get(ug, ())}, db=caminho)
    linhas = []
    for ug, d in grandes.items():
        com_obs = d["n"] - d["sem_obs"]
        incompletos = {a: e["rotulo"] for (u, a), e in est.items() if u == ug and e["rotulo"] != "VERIFICADO"}
        linhas.append({
            "ug": ug, "nome": d["nome"] or nome_canonico(ug, ""),
            "n": d["n"], "n_tac": d["n_tac"],
            "total": round(d["total"], 2), "total_tac": round(d["total_tac"], 2),
            "pct": round(100 * d["total_tac"] / d["total"], 1) if d["total"] else None,
            # INDISPONÍVEL ≠ 0%: unidade sem observação preenchida não "paga 0% por TAC" — ela
            # simplesmente não tem o campo em que o marcador vive.
            "cobertura": (f"verificado ({com_obs}/{d['n']} OBs com observação)"
                          if com_obs else "INDISPONIVEL (nenhuma OB com observação)"),
            # exercício que o SIAFE da casa não tem inteiro: PARCIAL (piso) ou INDISPONÍVEL — o % é do que foi lido
            "cobertura_siafe": incompletos or "VERIFICADO",
        })
    linhas.sort(key=lambda x: (x["pct"] or 0), reverse=True)
    medianas = sorted(x["pct"] for x in linhas if x["pct"] is not None)
    mediana = medianas[len(medianas) // 2] if medianas else None
    return {
        "ok": True, "indisponivel": False,
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "min_valor": min_valor,
        "fonte_valor": "SIAFE (ob_orcamentaria_siafe, régua _ob_paga, credor CNPJ/CPF)",
        "unidades": linhas,
        "mediana_pct": mediana,
        "ugs_fora_do_siafe": fora,
        "nota": ("Valor = OB paga do SIAFE (régua _ob_paga) a credor terceiro (CNPJ/CPF — fora repasse entre "
                 "unidades, folha e precatório); a observação, onde o marcador de TAC vive, é lida "
                 "da mesma OB no espelho TFE (número + UG) — OB sem par no espelho conta como sem observação. "
                 "O SIAFE da casa cobre 2021+: 2019–2020 ficam fora; `cobertura_siafe` de cada unidade lista "
                 "os exercícios PARCIAIS/INDISPONÍVEIS e `ugs_fora_do_siafe` as unidades nunca lidas "
                 "(INDISPONÍVEL ≠ 0%). A régua é COMPARATIVA: um percentual sozinho não sustenta afirmação — "
                 "o que informa é a distância para as outras unidades, sobretudo para as do mesmo setor."),
    }


def main() -> int:
    from compliance_agent.reporting.intel_base import moeda

    r = medir()
    SAIDA.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    if not r.get("ok") or r.get("indisponivel"):
        print(f"INDISPONÍVEL: {r.get('motivo')}")
        return 0
    print(f"{len(r['unidades'])} unidades acima de R$ {moeda(MIN_VALOR/1e6)} mi · "
          f"mediana {r['mediana_pct']}% · gravado em {SAIDA}")
    for u in r["unidades"][:6]:
        print(f"   {u['ug']} {str(u['nome'])[:36]:36s} {u['pct']:5.1f}%  "
              f"R$ {moeda(u['total_tac']/1e6)} mi de R$ {moeda(u['total']/1e6)} mi")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    raise SystemExit(main())
