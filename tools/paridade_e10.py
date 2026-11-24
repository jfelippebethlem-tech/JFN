# -*- coding: utf-8 -*-
"""Paridade por REPLAY da O5.3 (fatias 1 e 2): regra antiga × detector novo do E10 no MESMO universo (só leitura).

Para cada regra portada roda três versões sobre a mesma fonte (o snapshot de 24/11 ou o extrato dele conferido por md5):
  A  o código ANTIGO, como ele roda (sweep_fracionamento_tcerj, sweep_emergencia_recorrente; o lex_fatos por ALVO,
     uma vez por raiz de credor que tem NL na base — o universo onde o Lex pode disparar);
  B  o detector NOVO sem o portão da E9 (todo item 'E'): mede se a régua foi portada fiel (A × B);
  C  o detector NOVO com o veredito real da E9 (`dominio.elegibilidade`, só leitura): o que o E10 grava.
A diferença A × C é classificada pela causa: `falta_de_elegibilidade` (está em B: a E9 cortou), `regra_diferente`
(nem em B: a régua nova decide outra coisa — explicada caso a caso) e `elegibilidade_mudou_o_cluster` (P4: a E9 tirou
processos do lote e o card formou outro cluster). Nada é gravado: a saída é um JSON para o relatório.

    python -m tools.paridade_e10 --fonte <compliance.db só-leitura> --saida paridade.json [--so p4 --so cp4 ...]

Fatia 2 (`cp4`, `couto`, `sede`, `fusoes`, `pericia`): candidato ao P4 pelo SIAFE × a triagem do fracionamento_siafe
(e o D07 × a tabela gravada); D01/D02/D05/D09/D10/D16/D20 × governo_couto_regras com o corte da lente Couto — nas
regras de OB há um B' com o pago ANTIGO (status + devolução abatida) para separar "régua portada" de "predicado do
pago canônico"; D17 × P5 com o mínimo da lente (3); fusões D03/D04/D13/D14/D15/D18/D06 × o detector de fornecedor
existente (sobreposição por raiz de CNPJ); peneira do pericia_sweep × veredito `fornecedor` da E9 por raiz.
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


# ── fatia 2 ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _dig(x) -> str:
    return re.sub(r"\D", "", str(x or ""))


def _comparar(A: dict, B: dict, C: dict, valor, amostra_a=None) -> dict:
    """A, B, C: chave → objeto; `valor(obj)` → R$ (ou None). Diferença A × C classificada por B (E9 × régua)."""
    so_a, so_c = sorted(set(A) - set(C), key=str), sorted(set(C) - set(A), key=str)

    def soma(d):
        return round(sum(float(valor(x) or 0) for x in d.values()), 2)
    fe = [k for k in so_a if k in B]
    rd = [k for k in so_a if k not in B]
    am = amostra_a or (lambda k: {"chave": str(k)})
    return {"A_antigo": len(A), "B_novo_sem_e9": len(B), "C_novo_com_e9": len(C), "A_soma": soma(A),
            "B_soma": soma(B), "C_soma": soma(C), "A_igual_B": set(A) == set(B),
            "A_menos_B": len(set(A) - set(B)), "B_menos_A": len(set(B) - set(A)), "iguais_A_C": len(set(A) & set(C)),
            "so_no_antigo": len(so_a), "so_no_novo": len(so_c),
            "falta_de_elegibilidade": len(fe), "regra_diferente": len(rd),
            "amostra_falta_de_elegibilidade": [am(k) for k in fe[:AMOSTRA]],
            "amostra_A_menos_B": [am(k) for k in sorted(set(A) - set(B), key=str)[:AMOSTRA]],
            "amostra_B_menos_A": [{"chave": str(k)} for k in sorted(set(B) - set(A), key=str)[:AMOSTRA]],
            "amostra_so_no_novo": [{"chave": str(k)} for k in so_c[:AMOSTRA]]}


def _tres(det, con, pg, ex=None, anotar_e9=True):
    carga = det.carregar(con, ex)
    b = det.detectar(_todos_e([dict(c) for c in carga.itens]), carga.contexto)
    gated = _e9(pg, det.ID, [dict(c) for c in carga.itens]) if anotar_e9 else None
    c = det.detectar(gated, carga.contexto) if gated is not None else []
    return carga, b, c, gated


def paridade_cp4(fonte: str, pg) -> dict:
    from compliance_agent.aplicacao.detectores import candidato_p4_siafe as CP
    from compliance_agent.fracionamento_siafe import triagem
    t0 = time.monotonic()
    con = _ro(fonte)
    A = {}
    for ex in CP._exercicios(con, None):
        for x in triagem(con, exercicio=ex)["candidatos"]:
            A[f"{ex}|{x['ug_emitente']}|{x['credor']}"] = x
    con.row_factory = None
    carga, b, c, gated = _tres(CP, con, pg)
    B, C = {d.chave: d for d in b}, {d.chave: d for d in c}
    ver = Counter(x.get("e9") or "?:SEM_LINHA_E9" for x in gated if x["grupo"] in set(A) - set(C))
    out = _comparar(A, B, C, lambda x: x["soma"] if isinstance(x, dict) else x.valores["soma"],
                    lambda k: {"grupo": k, "n_obs": A[k]["n_obs"], "n_processos": A[k]["n_processos"],
                               "soma": A[k]["soma"]})
    out["processos_iguais_A_B"] = all(set(map(str, A[k]["processos"])) <= set(B[k].valores["processos"])
                                      for k in set(A) & set(B))
    out["motivos_e9_das_ob_cortadas"] = dict(ver.most_common())
    out["universo"] = {**carga.contexto, **CP.resumo(gated, c)}
    out["estado_dos_disparos"] = dict(Counter(d.estado for d in c))
    # D07 → P4: a tabela gravada do sweep (siafe_fracionamento) × candidato_p4 recalculado no mesmo exercício
    from compliance_agent.governo_couto import INICIO
    ano = int(con.execute("SELECT max(exercicio) FROM siafe_fracionamento").fetchone()[0])
    d07 = {f"{ano}|{ug}|{cr}": (pr, soma) for ug, cr, pr, soma in con.execute(
        "SELECT ug_emitente, credor, primeira_ob, soma FROM siafe_fracionamento WHERE exercicio = ?", (ano,))
        if (pr or "") >= INICIO}
    novo = {k: d for k, d in B.items() if k.startswith(f"{ano}|") and (d.valores["primeira_ob"] or "") >= INICIO}
    novo_c = {k: d for k, d in C.items() if k in novo}
    out["d07"] = {"exercicio": ano, **_comparar(d07, novo, novo_c, lambda x: x[1] if isinstance(x, tuple)
                                                 else x.valores["soma"]),
                  "gerado_em_da_tabela": con.execute("SELECT min(gerado_em), max(gerado_em) FROM siafe_fracionamento "
                                                     "WHERE exercicio = ?", (ano,)).fetchone()}
    con.close()
    out["segundos"] = round(time.monotonic() - t0, 1)
    return out


def _ctx_antigo(fonte: str, tmp: str):
    from compliance_agent import governo_couto_regras as GC
    return GC.Ctx(Path(fonte), receita=None, tse=None, dir_tmp=Path(tmp))


def paridade_couto(fonte: str, pg, tmp: str) -> dict:
    from compliance_agent import governo_couto_regras as GC
    from compliance_agent.aplicacao.detectores import troca_gestao as T
    t0 = time.monotonic()
    c = _ctx_antigo(fonte, tmp)
    con = _ro(fonte)
    out: dict = {"janelas_antigo": {"G0": GC.G0, "GFIM": c.GFIM, "G1": c.G1, "B0": c.B0, "B1": c.B1}}
    out["janelas_novo"] = T.janelas(con)
    try:
        old = {"D05": GC.d05(c), "D10": GC.d10(c), "D20": GC.d20(c), "D16": GC.d16(c)}
        old.update(GC.d01_02_17(c))
        old.update(GC.d08_09(c))
    finally:
        c.fechar()
    out["fora_da_conta_antigo_D01"] = old["D01"]["fora_da_conta"]

    def regra(nome, det_cls, A, chave_nova, valor_a, valor_n, pago=True):
        r = {}
        dets = {"B": det_cls(pago="canonico")}
        if pago:
            dets["Bp"] = det_cls(pago="antigo")
        carga, b, cc, gated = _tres(dets["B"], con, pg)
        B, C = {chave_nova(d): d for d in b}, {chave_nova(d): d for d in cc}
        r.update(_comparar(A, B, C, lambda x: valor_a(x) if isinstance(x, dict) else valor_n(x)))
        if pago:
            cp = dets["Bp"].carregar(con)
            bp = dets["Bp"].detectar(_todos_e([dict(x) for x in cp.itens]), cp.contexto)
            Bp = {chave_nova(d): d for d in bp}
            r["Bp_pago_antigo"] = {"n": len(Bp), "soma": round(sum(float(valor_n(d) or 0) for d in Bp.values()), 2),
                                   "A_igual_Bp": set(A) == set(Bp), "A_menos_Bp": sorted(map(str, set(A) - set(Bp)))[:AMOSTRA],
                                   "Bp_menos_A": sorted(map(str, set(Bp) - set(A)))[:AMOSTRA],
                                   "Bp_menos_B_predicado_canonico": len(set(Bp) - set(B)),
                                   "B_menos_Bp": len(set(B) - set(Bp))}
        r["universo"] = {**{k: v for k, v in carga.contexto.items() if not isinstance(v, (list, dict)) or k == "fora"},
                         **dets["B"].resumo(gated, cc)}
        r["motivos_e9_so_no_antigo"] = dict(Counter(
            x.get("e9") or "?:SEM_LINHA_E9" for x in gated
            if (x.get("grupo") in {str(k).split("|")[0] for k in set(A) - set(C)} or x.get("chave_e9") in set(A) - set(C))
            and x.get("e9") != "E").most_common(8))
        r["amostra_C"] = [{"chave": k, **{a: v for a, v in d.valores.items() if not isinstance(v, (list, dict))}}
                          for k, d in sorted(C.items(), key=lambda kv: -float(valor_n(kv[1]) or 0))[:AMOSTRA]]
        out[nome] = r

    regra("D05", T._Concentracao, {f"{x['ug']}|{x['cnpj']}": x for x in old["D05"]["casos"]},
          lambda d: d.chave, lambda x: x["pago_ob"], lambda d: d.valores["pago_ob"])
    regra("D09", T._PicoVespera, {x["cnpj"]: x for x in old["D09"]["casos"]}, lambda d: d.chave,
          lambda x: x["pago_semana"], lambda d: d.valores["pago_semana"])
    regra("D10", T._CredorEstreante, {x["cnpj"]: x for x in old["D10"]["casos"] if x["rotulo"] == "estreia"},
          lambda d: d.chave, lambda x: x["pago_ob"], lambda d: d.valores["pago_ob"])
    regra("D20", T._ObAnulada, {str(x["ug"]): x for x in old["D20"]["top_ugs"]}, lambda d: d.chave,
          lambda x: x["valor"], lambda d: d.valores["valor"])
    out["D20"]["totais_antigo"] = {k: old["D20"][k] for k in ("n", "valor", "n_ano_anterior", "valor_ano_anterior")}
    out["D20"]["nota"] = "A do D20 = as 10 maiores UG do antigo (top_ugs); os totais comparam o universo inteiro"
    regra("D01", T._DiretaSalto, {str(x["unidade"]): x for x in old["D01"]["casos"]}, lambda d: d.chave,
          lambda x: x["valor_direta"], lambda d: d.valores["valor_direta"], pago=False)
    regra("D02", T._EmergencialIncumbente, {str(x["processo"]): x for x in old["D02"]["casos"]},
          lambda d: d.processo, lambda x: x["valor_contrato"], lambda d: d.valores["valor_contrato"], pago=False)
    regra("D16", T._TacAceleracao, {GC.norm_nome(x["fornecedor"]): x for x in old["D16"]["casos"]},
          lambda d: d.chave, lambda x: x["valor"], lambda d: d.valores["valor_tac"], pago=False)
    out["D16"]["taxa_antigo"] = {k: old["D16"].get(k) for k in ("valor_dia_pre", "valor_dia_gestao", "variacao_dia")}
    # D17 → P5 com o mínimo da lente (3) no exercício do fim da coleta
    ano = int(out["janelas_novo"]["gfim"][:4])
    A17 = {f"{g['unidade']}|{g['exercicio']}": g for g in old["D17"]["casos"]}
    minimo, P5.MINIMO = P5.MINIMO, 3
    try:
        itens = P5.carregar(con, ano).itens
        B17 = {d.grupo: d for d in P5.detectar(_todos_e([dict(x) for x in itens]))}
        g17 = _e9(pg, P5.ID, [dict(x) for x in itens])
        C17 = {d.grupo: d for d in P5.detectar(g17)}
    finally:
        P5.MINIMO = minimo
    r17 = _comparar(A17, B17, C17, lambda x: x["total"] if isinstance(x, dict) else x.valores["total"])
    r17["grupos_iguais_com_n_diferente"] = [
        {"grupo": k, "n_antigo_itens": A17[k]["n"], "n_p5_processos": B17[k].valores["n"],
         "total_antigo": round(A17[k]["total"], 2), "total_p5": B17[k].valores["total"]}
        for k in sorted(set(A17) & set(B17), key=lambda k: -A17[k]["total"]) if A17[k]["n"] != B17[k].valores["n"]
    ][:AMOSTRA]
    out["D17_P5"] = r17
    con.close()
    out["segundos"] = round(time.monotonic() - t0, 1)
    return out


def _raizes(obj, out=None) -> set:
    """Raízes (8 dígitos) de todo CNPJ citado num resultado (recursivo): campo de 14 dígitos ou `cnpj_basico`."""
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("cnpj_basico", "raiz") and len(_dig(v)) == 8:
                out.add(_dig(v))
            else:
                _raizes(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _raizes(v, out)
    elif isinstance(obj, str) and len(_dig(obj)) == 14 and re.fullmatch(r"[\d./-]+", obj.strip()):
        out.add(_dig(obj)[:8])
    return out


def paridade_fusoes(fonte: str, pg, tmp: str, tse: str | None) -> dict:
    from compliance_agent import cruzamentos_intel as CI
    from compliance_agent import governo_couto_regras as GC
    from compliance_agent.aplicacao.detectores import sede_fachada as SF
    from tools import porte_incompativel as PI
    t0 = time.monotonic()
    c = GC.Ctx(Path(fonte), receita=None, tse=Path(tse) if tse else None, dir_tmp=Path(tmp))
    out = {}
    try:
        old = {k: f(c) for k, f in (("D03", GC.d03), ("D04", GC.d04), ("D13", GC.d13), ("D14", GC.d14),
                                    ("D15", GC.d15), ("D18", GC.d18), ("D06", GC.d06))}
    finally:
        c.fechar()
    con = _ro(fonte)
    alvo = {}
    for nome, f in (("intel.empresa_fenix", lambda: CI.empresa_fenix(fonte, limite=None)),
                    ("intel.capital_incompativel", lambda: CI.capital_incompativel(fonte)
                     if hasattr(CI, "capital_incompativel") else None),
                    ("tools.porte_incompativel", lambda: PI.incompativeis(con)),
                    ("intel.socio_servidor", lambda: CI.socio_servidor(fonte, limite=100000)),
                    ("intel.sancionadas_contratadas", lambda: CI.sancionadas_contratadas(fonte)),
                    ("intel.ranking_fantasmas", lambda: CI.ranking_fantasmas(fonte, limite=100000))):
        t1 = time.monotonic()
        try:
            r = f()
            alvo[nome] = {"raizes": _raizes(r) if r is not None else None, "segundos": round(time.monotonic() - t1, 1)}
        except (sqlite3.Error, KeyError, TypeError, ValueError, AttributeError) as e:   # alvo que não roda no extrato
            alvo[nome] = {"raizes": None, "erro": f"{type(e).__name__}: {str(e)[:200]}"}
            print(f"fusões: {nome} não rodou no extrato — {e}", file=sys.stderr, flush=True)
    sede = SF.carregar(con)
    alvo["e10.c_sede_fachada"] = {"raizes": {d.chave[:8] for d in SF.detectar(_todos_e(sede.itens))}}
    mapa = {"D03": ["intel.empresa_fenix", "intel.capital_incompativel"], "D04": ["tools.porte_incompativel"],
            "D13": ["intel.socio_servidor"], "D14": ["intel.sancionadas_contratadas"], "D15": [],
            "D18": ["intel.ranking_fantasmas", "e10.c_sede_fachada"]}
    for d, alvos in mapa.items():
        a = old[d]
        ra = {_dig(x.get("cnpj") or x.get("cnpj_basico"))[:8] for x in a.get("casos") or []} - {""}
        r = {"antigo_n": a.get("n"), "antigo_raizes": len(ra), "indisponivel": a.get("indisponivel")}
        uniao = set()
        for t in alvos:
            rt = alvo[t]["raizes"]
            if rt is None:
                r[t] = {"erro": alvo[t].get("erro") or "indisponível"}
                continue
            uniao |= rt
            r[t] = {"alvo_raizes": len(rt), "cobertas": len(ra & rt), "so_no_antigo": len(ra - rt),
                    "amostra_so_no_antigo": sorted(ra - rt)[:AMOSTRA]}
        r["cobertura_pela_uniao"] = round(len(ra & uniao) / len(ra), 4) if ra and alvos else None
        out[d] = r
    out["alvos"] = {k: {kk: (len(vv) if isinstance(vv, set) else vv) for kk, vv in v.items()} for k, v in alvo.items()}
    # D06 → X1: o mesmo universo (aditivo PNCP na gestão, Executivo estadual) avaliado pelo X1 por contrato
    from compliance_agent.detectores.x1_crescimento_aditivo import X1CrescimentoAditivo
    adit: dict = {}
    for cn, termo, obj, acr, dt, org, vi in con.execute(
            "SELECT a.numero_controle_pncp, a.numero_termo, a.objeto, a.valor_acrescido, a.data_assinatura, "
            "p.orgao_nome, p.valor_inicial FROM contrato_aditivo a JOIN pcrj_contratos p "
            "ON p.numero_controle_pncp = a.numero_controle_pncp WHERE a.data_assinatura >= ?", (GC.G0,)):
        if vi and GC._executivo_estadual_rj(cn, org):
            adit.setdefault(cn, {"valor_inicial": vi, "aditivos": []})["aditivos"].append(
                {"tipo": "valor" if (acr or 0) else "prazo", "valor": float(acr or 0), "descricao_objeto": obj or "",
                 "justificativa": obj or "", "data": str(dt)[:10]})
    x1 = X1CrescimentoAditivo()
    estouro = {cn for cn, ctx in adit.items()
               if (x1.avaliar({"processo": cn, **ctx}).valores or {}).get("estouro_teto")}
    d06 = {x["contrato"] for x in old["D06"]["casos"]}
    out["D06_X1"] = {"antigo_n": len(d06), "contratos_no_universo": len(adit), "x1_estouro": len(estouro),
                     "cobertos": len(d06 & estouro), "so_no_d06": sorted(d06 - estouro)[:AMOSTRA],
                     "so_no_x1": sorted(estouro - d06)[:AMOSTRA], "criterio_antigo": old["D06"]["criterio"][:300]}
    con.close()
    out["segundos"] = round(time.monotonic() - t0, 1)
    return out


def paridade_pericia(fonte: str, pg) -> dict:
    """A peneira do pericia_sweep (credor não contratual / ente público, sem a natureza da Receita) × o veredito
    `fornecedor` da E9 por raiz, no universo do sweep (pares credor × UG com ≥ 6 OB contabilizadas)."""
    from compliance_agent.pericia_sweep import _fora_da_bateria
    t0 = time.monotonic()
    con = _ro(fonte)
    # ob-qualquer-status: reproduz o universo do pericia_sweep como ele roda (status contabilizado por LIKE)
    pares = con.execute("SELECT credor, ug_emitente, COUNT(*) n, MAX(nome_credor), SUM(valor) FROM ob_orcamentaria_siafe "
                        "WHERE credor IS NOT NULL AND credor != '' AND lower(status) LIKE 'contabiliz%' "
                        "GROUP BY credor, ug_emitente HAVING n >= 6").fetchall()
    con.close()
    raizes = sorted({_dig(p[0])[:8] if len(_dig(p[0])) == 14 else _dig(p[0]) for p in pares} - {""})
    esq = D.esquema_e9({})
    e9: dict = {}
    for k, v, n in pg.execute(f'SELECT credor_raiz, split_part(exiges ->> \'fornecedor\', \':\', 1), count(*) FROM "{esq}".'
                              "elegibilidade WHERE unidade = 'ob_siafe' AND versao = %s AND credor_raiz = ANY(%s) "
                              "GROUP BY 1, 2", (D.E9.VERSAO, raizes)):
        e9.setdefault(k, Counter())[v] += n
    tab = Counter()
    valor = Counter()
    amostra: dict = {}
    for cr, ug, n, nome, v in pares:
        d = _dig(cr)
        r = d[:8] if len(d) == 14 else d
        fora = _fora_da_bateria(cr, nome or "")
        maj = e9[r].most_common(1)[0][0] if r in e9 else "SEM_LINHA_E9"
        chave = f"{'fora' if fora else 'dentro'}×{maj}"
        tab[chave] += 1
        valor[chave] += float(v or 0)
        if len(amostra.setdefault(chave, [])) < AMOSTRA:
            amostra[chave].append({"ug": ug, "nome": (nome or "")[:50], "valor": round(float(v or 0), 2)})
    return {"pares": len(pares), "tabela": dict(tab.most_common()), "valor": {k: round(x, 2) for k, x in valor.items()},
            "amostra_divergentes": {k: v for k, v in amostra.items() if k in ("dentro×I", "fora×E")},
            "segundos": round(time.monotonic() - t0, 1)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fonte", required=True)
    ap.add_argument("--saida", required=True)
    ap.add_argument("--so", choices=("p4", "p5", "contabil", "cp4", "couto", "fusoes", "pericia"), action="append")
    ap.add_argument("--tmp", default="/tmp", help="diretório da base de trabalho do governo_couto_regras (fatia 2)")
    ap.add_argument("--tse", help="doacao_tse.db só-leitura (D15); sem ele o D15 sai INDISPONÍVEL")
    a = ap.parse_args(argv)
    pg = D.conectar({})
    res = {}
    try:
        for nome, f in (("p4", paridade_p4), ("p5", paridade_p5), ("contabil", paridade_contabil),
                        ("cp4", paridade_cp4), ("couto", lambda fo, pg: paridade_couto(fo, pg, a.tmp)),
                        ("fusoes", lambda fo, pg: paridade_fusoes(fo, pg, a.tmp, a.tse)),
                        ("pericia", paridade_pericia)):
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
