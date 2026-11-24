# -*- coding: utf-8 -*-
"""Paridade por REPLAY da O5.3 fatia 1: regra antiga × detector novo do E10 no MESMO universo (só leitura).

Para cada regra portada roda três versões sobre a mesma fonte (o snapshot de 24/11 ou o extrato dele conferido por md5):
  A  o código ANTIGO, como ele roda (sweep_fracionamento_tcerj, sweep_emergencia_recorrente; o lex_fatos por ALVO,
     uma vez por raiz de credor que tem NL na base — o universo onde o Lex pode disparar);
  B  o detector NOVO sem o portão da E9 (todo item 'E'): mede se a régua foi portada fiel (A × B);
  C  o detector NOVO com o veredito real da E9 (`dominio.elegibilidade`, só leitura): o que o E10 grava.
A diferença A × C é classificada pela causa: `falta_de_elegibilidade` (está em B: a E9 cortou), `regra_diferente`
(nem em B: a régua nova decide outra coisa — explicada caso a caso) e `elegibilidade_mudou_o_cluster` (P4: a E9 tirou
processos do lote e o card formou outro cluster). Nada é gravado: a saída é um JSON para o relatório.

    python -m tools.paridade_e10 --fonte <compliance.db só-leitura> --saida paridade.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

from compliance_agent.aplicacao.detectores import contabil_siafe as CS
from compliance_agent.aplicacao.detectores import emergencia_recorrente as P5
from compliance_agent.aplicacao.detectores import fracionamento_objeto as P4
from compliance_agent.aplicacao.estagios import detectar as D

AMOSTRA = 10


def _ro(fonte: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{fonte}?mode=ro&immutable=1", uri=True)


def _todos_e(itens):
    for c in itens:
        c["e9"] = "E"
    return itens


def _e9(pg, did, itens):
    unidade, exige = D.exigencia(did)
    D.anotar(itens, D.vereditos(pg, D.esquema_e9({}), unidade, exige, (c["chave_e9"] for c in itens)))
    return itens


def _soma(vs) -> float:
    return round(sum(float(v or 0) for v in vs), 2)


def _motivos(itens_por_chave, chaves) -> dict:
    return dict(Counter(itens_por_chave.get(k) or "?:SEM_LINHA_E9" for k in chaves).most_common())


# ── P4 ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def paridade_p4(fonte: str, pg) -> dict:
    from tools import sweep_fracionamento_tcerj as S
    t0 = time.monotonic()
    antigo = S.rodar_sweep(S.carregar_grupos(Path(fonte)))
    A = {frozenset(map(str, a["valores"]["processos_cluster"])): a for a in antigo}
    con = _ro(fonte)
    itens = P4.carregar(con).itens
    con.close()
    B = {frozenset(c["processo"] for c in d.entradas["cluster"]): d for d in P4.detectar(_todos_e([dict(c) for c in itens]))}
    gated = _e9(pg, P4.ID, [dict(c) for c in itens])
    ver = {c["processo"]: c["e9"] for c in gated}
    C = {frozenset(c["processo"] for c in d.entradas["cluster"]): d for d in P4.detectar(gated)}
    so_a, so_c = [k for k in A if k not in C], [k for k in C if k not in A]
    classes: dict[str, list] = {"falta_de_elegibilidade": [], "regra_diferente": [],
                                "elegibilidade_mudou_o_cluster": []}
    for k in so_a:
        if any(ver.get(p) != "E" for p in k):
            classes["falta_de_elegibilidade"].append(k)          # algum processo do cluster antigo a E9 não deixa ver
        elif k in B:
            # todos 'E', mas a E9 tirou OUTROS processos do lote: o card (TF-IDF do lote, extração iterativa) recompôs
            classes["elegibilidade_mudou_o_cluster"].append(k)
        else:
            classes["regra_diferente"].append(k)
    novos_c = [k for k in so_c if not any(k & ka for ka in A)]

    def linha_a(k):
        a = A[k]
        return {"unidade": a["unidade"], "exercicio": a["exercicio"], "processos": sorted(k)[:6],
                "n": len(k), "soma": a["valores"]["soma_cluster"], "e9": _motivos(ver, k)}

    return {"segundos": round(time.monotonic() - t0, 1), "A_antigo": len(A), "B_novo_sem_e9": len(B),
            "C_novo_com_e9": len(C), "A_soma": _soma(a["valores"]["soma_cluster"] for a in A.values()),
            "B_soma": _soma(d.valores["soma_cluster"] for d in B.values()),
            "C_soma": _soma(d.valores["soma_cluster"] for d in C.values()),
            "A_igual_B": set(A) == set(B), "A_menos_B": len(set(A) - set(B)), "B_menos_A": len(set(B) - set(A)),
            "iguais_A_C": len(set(A) & set(C)), "so_no_antigo": len(so_a), "so_no_novo": len(so_c),
            "so_no_novo_sem_sobreposicao": len(novos_c),
            "classes": {c: {"n": len(ks), "soma": round(sum(A[k]["valores"]["soma_cluster"] for k in ks), 2),
                            "motivos_e9": dict(Counter(m for k in ks for m, _ in _motivos(ver, k).items()
                                                       if m != "E").most_common()),
                            "amostra": [linha_a(k) for k in sorted(ks, key=lambda k: -A[k]["valores"]["soma_cluster"])
                                        [:AMOSTRA]]}
                        for c, ks in classes.items()},
            "amostra_so_no_novo": [{"grupo": C[k].grupo, "processos": sorted(k)[:6], "soma": C[k].valores["soma_cluster"]}
                                   for k in sorted(so_c, key=lambda k: -C[k].valores["soma_cluster"])[:AMOSTRA]],
            "universo": P4.resumo(gated, list(C.values()))}


# ── P5 ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def paridade_p5(fonte: str, pg) -> dict:
    from compliance_agent.fracionamento_emergencia import agrupar_emergencias
    from tools import sweep_emergencia_recorrente as S
    t0 = time.monotonic()
    con = _ro(fonte)
    A = {f"{g['unidade']}|{g['exercicio']}": g for g in agrupar_emergencias(S.carregar(con), minimo=P5.MINIMO)}
    itens = P5.carregar(con).itens
    con.close()
    B = {d.grupo: d for d in P5.detectar(_todos_e([dict(c) for c in itens]))}
    gated = _e9(pg, P5.ID, [dict(c) for c in itens])
    C = {d.grupo: d for d in P5.detectar(gated)}
    ver_por_grupo: dict[str, Counter] = {}
    for c in gated:
        if c["emergencial"]:
            ver_por_grupo.setdefault(c["grupo"], Counter())[c["e9"] or "?:SEM_LINHA_E9"] += 1
    iguais = [g for g in A if g in C and A[g]["n"] == C[g].valores["n"] and round(A[g]["total"], 2) == C[g].valores["total"]]
    menor = [g for g in A if g in C and g not in iguais]
    so_a = [g for g in A if g not in C]

    def amostra(gs, com_c=False):
        out = []
        for g in sorted(gs, key=lambda g: -A[g]["total"])[:AMOSTRA]:
            x = {"grupo": g, "n_antigo": A[g]["n"], "total_antigo": round(A[g]["total"], 2),
                 "e9_das_emergencias": dict(ver_por_grupo.get(g, {}))}
            if com_c:
                x.update(n_novo=C[g].valores["n"], total_novo=C[g].valores["total"])
            out.append(x)
        return out

    return {"segundos": round(time.monotonic() - t0, 1), "A_antigo": len(A), "B_novo_sem_e9": len(B),
            "C_novo_com_e9": len(C), "A_igual_B": set(A) == set(B) and all(
                A[g]["n"] == B[g].valores["n"] and round(A[g]["total"], 2) == B[g].valores["total"] for g in A),
            "A_total": round(sum(g["total"] for g in A.values()), 2),
            "C_total": round(sum(d.valores["total"] for d in C.values()), 2),
            "iguais_A_C": len(iguais), "grupo_menor_no_novo": len(menor), "so_no_antigo": len(so_a),
            "so_no_novo": len([g for g in C if g not in A]),
            "amostra_grupo_menor": amostra(menor, True), "amostra_so_no_antigo": amostra(so_a),
            "universo": P5.resumo(gated, list(C.values()))}


# ── contábeis (lex_fatos) ───────────────────────────────────────────────────────────────────────────────────────
def _lex_universo(fonte: str) -> tuple[dict, dict, int]:
    """O Lex como ele roda (base_siafe + execucao), uma vez por raiz de credor com NL na base."""
    from compliance_agent import lex_fatos as L
    L.caminho_db = lambda: Path(fonte)
    con = _ro(fonte)
    raizes = sorted({re.sub(r"\D", "", r[0] or "")[:8] for r in con.execute("SELECT DISTINCT credor FROM nl_siafe")} - {""})
    con.close()
    acima, antes = {}, {}
    for r in raizes:
        exe = L.execucao(L.base_siafe(cnpj=r))
        for a in exe["pago_acima_da_nl"]:
            acima[(a["nl"], a["ug"])] = a
        for b in exe["ob_antes_da_nl"]:
            antes[(b["ob"], b["ug"])] = b
    return acima, antes, len(raizes)


def paridade_contabil(fonte: str, pg) -> dict:
    t0 = time.monotonic()
    lex_acima, lex_antes, n_raizes = _lex_universo(fonte)
    con = _ro(fonte)
    carga = CS.carregar(con)
    con.close()
    base = carga.itens
    gated = _e9(pg, CS.PAGO_ACIMA.ID, [dict(c) for c in base])
    ver = {c["chave_e9"]: c["e9"] for c in gated}
    por_nl: dict[str, list] = {}
    for c in gated:
        por_nl.setdefault(c["grupo"], []).append(c)
    out = {"raizes_lex": n_raizes, "contexto": carga.contexto}

    def classificar_nl(grupo) -> str:
        obs = por_nl.get(grupo) or []
        if not obs:
            return "NL_SEM_OB_PAGA_NA_CARGA_NOVA"
        if not all(c["mesmo_credor"] for c in obs):
            return "CREDOR_OB_DIFERENTE_DA_NL (INCERTO)"
        if CS.situacao_nl(obs) != "E":
            return Counter(c["e9"] or "?:SEM_LINHA_E9" for c in obs if c["e9"] != "E").most_common(1)[0][0]
        return "OUTRA"

    # C-PAGO>NL
    A = {f"{nl}|{ug}": a for (nl, ug), a in lex_acima.items()}
    B = {d.chave: d for d in CS.PAGO_ACIMA.detectar(_todos_e([dict(c) for c in base]))}
    C = {d.chave: d for d in CS.PAGO_ACIMA.detectar(gated)}
    so_a = [k for k in A if k not in C]
    cl = Counter(("falta_de_elegibilidade" if k in B else "regra_diferente") + ":" + classificar_nl(k)
                 for k in so_a)
    out["pago_acima"] = {
        "A_antigo": len(A), "B_novo_sem_e9": len(B), "C_novo_com_e9": len(C),
        "A_excedente": round(sum(a["pago"] - a["liquidado"] for a in A.values()), 2),
        "B_excedente": round(sum(d.valores["excedente"] for d in B.values()), 2),
        "C_excedente": round(sum(d.valores["excedente"] for d in C.values()), 2),
        "A_menos_B": len(set(A) - set(B)), "B_menos_A": len(set(B) - set(A)), "iguais_A_C": len(set(A) & set(C)),
        "so_no_antigo": len(so_a), "so_no_novo": len(set(C) - set(A)), "classes_so_no_antigo": dict(cl.most_common()),
        "amostra_so_no_antigo": [{"nl": A[k]["nl"], "ug": A[k]["ug"], "pago": round(A[k]["pago"], 2),
                                  "liquidado": A[k]["liquidado"], "n_ob": len(A[k]["obs"]), "causa": classificar_nl(k),
                                  "e9_das_ob": dict(Counter(c["e9"] or "?" for c in por_nl.get(k, [])))}
                                 for k in sorted(so_a, key=lambda k: -(A[k]["pago"] - A[k]["liquidado"]))[:AMOSTRA]],
        "amostra_B_menos_A": [{"chave": k, **B[k].valores} for k in sorted(set(B) - set(A))[:AMOSTRA]],
        "amostra_A_menos_B": [{"chave": k, "causa": classificar_nl(k)} for k in sorted(set(A) - set(B))[:AMOSTRA]],
        "amostra_C": [{"chave": k, **C[k].valores} for k in sorted(C, key=lambda k: -C[k].valores["excedente"])[:AMOSTRA]],
        "universo": CS.PAGO_ACIMA.resumo(gated, list(C.values()))}

    # C-OB<NL
    idx = {(c["numero_ob"], c["ug"]): c for c in base}
    A = {f"{c['ug']}|{c['numero_ob']}|{c['exercicio']}": b for (ob, ug), b in lex_antes.items()
         if (c := idx.get((ob, ug)))}
    sem_par = len(lex_antes) - len(A)
    B = {d.chave: d for d in CS.OB_ANTES.detectar(_todos_e([dict(c) for c in base]))}
    C = {d.chave: d for d in CS.OB_ANTES.detectar(gated)}
    so_a = [k for k in A if k not in C]
    cl = Counter(("falta_de_elegibilidade:" + (ver.get(k) or "?:SEM_LINHA_E9")) if k in B else "regra_diferente"
                 for k in so_a)
    out["ob_antes"] = {
        "A_antigo": len(lex_antes), "A_sem_par_na_carga_nova": sem_par, "B_novo_sem_e9": len(B),
        "C_novo_com_e9": len(C), "A_menos_B": len(set(A) - set(B)), "B_menos_A": len(set(B) - set(A)),
        "iguais_A_C": len(set(A) & set(C)), "so_no_antigo": len(so_a), "so_no_novo": len(set(C) - set(A)),
        "B_valor": round(sum(d.valores["valor"] for d in B.values()), 2),
        "C_valor": round(sum(d.valores["valor"] for d in C.values()), 2),
        "classes_so_no_antigo": dict(cl.most_common()),
        "amostra_so_no_antigo": [{**A[k], "e9": ver.get(k)} for k in sorted(so_a)[:AMOSTRA]],
        "amostra_B_menos_A": [{"chave": k, **B[k].valores, "mesmo_credor": idx[(B[k].entradas['ob'], B[k].entradas['ug'])]
                               ["mesmo_credor"]} for k in sorted(set(B) - set(A))[:AMOSTRA]],
        "amostra_A_menos_B": [{"chave": k, **A[k]} for k in sorted(set(A) - set(B))[:AMOSTRA]],
        "amostra_C": [{"chave": k, **C[k].valores} for k in sorted(C)[:AMOSTRA]],
        "universo": CS.OB_ANTES.resumo(gated, list(C.values()))}
    out["segundos"] = round(time.monotonic() - t0, 1)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fonte", required=True)
    ap.add_argument("--saida", required=True)
    ap.add_argument("--so", choices=("p4", "p5", "contabil"), action="append")
    a = ap.parse_args(argv)
    pg = D.conectar({})
    res = {}
    try:
        for nome, f in (("p4", paridade_p4), ("p5", paridade_p5), ("contabil", paridade_contabil)):
            if a.so and nome not in a.so:
                continue
            res[nome] = f(a.fonte, pg)
            print(f"paridade {nome}: ok ({res[nome].get('segundos')} s)", file=sys.stderr, flush=True)
    finally:
        pg.close()
    Path(a.saida).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
