# -*- coding: utf-8 -*-
"""Comissão de Orçamento, Finanças, Fiscalização Financeira e Controle (ALERJ) — dados da sub-aba.

Pedido do dono (13/11/2026): "liste órgão a órgão os problemas encontrados por fornecedores de cada um deles",
para as contas do Governo do Estado, TJRJ, Defensoria, MPRJ e TCE-RJ (e ALERJ).

ÓRGÃO = o órgão orçamentário dono da UG no cadastro do TFE (`ug_para_orgao`: maior fatia do empenho; 01 ALERJ,
02 TCE-RJ, 03 TJRJ, 10 MPRJ, 11 Defensoria). Só sem cadastro cai nos dois primeiros dígitos da UG. Nome do órgão pelo cadastro do portal de
dados abertos (`data/dadosabertos_rj.db`, `da_despesa`).

O que entra como PROBLEMA (nada aqui é acusação — indício a apurar, presunção de legitimidade):
  · perícia de fornecedor (`pericia_fornecedor`) 🔴/🟡 — cada achado INDÍCIO/CONFIRMADO com a evidência;
  · situação da duplicidade por competência (`resolucao_duplicidade`): afastadas, pendentes de NF, indeterminadas;
  · achados CONFIRMADOS dos detectores do órgão (`achados.db`, `achado_detector`, processo = CNPJ).
Valor = só OB Contabilizado do SIAFE (`total_pago` da perícia). Empenho nunca é "pago".
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DB = RAIZ / "data" / "compliance.db"
DB_ACHADOS = RAIZ / "data" / "achados.db"
DB_ABERTOS = RAIZ / "data" / "dadosabertos_rj.db"

# Instituições cujas contas a Comissão examina além do Executivo (ordem de exibição).
INSTITUICOES = {"01": "ALERJ", "02": "TCE-RJ", "03": "TJRJ", "10": "MPRJ", "11": "Defensoria Pública (DPRJ)"}
PODER = {"01": "Legislativo", "02": "Legislativo (controle externo)", "03": "Judiciário", "10": "Ministério Público",
         "11": "Defensoria Pública"}

_CACHE: dict = {}
_TTL = 600


def _ro(caminho: Path) -> sqlite3.Connection | None:
    if not caminho.exists():
        return None
    c = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def nomes_orgao(con_abertos: sqlite3.Connection | None) -> dict[str, str]:
    """órgão (2 dígitos) → nome do exercício mais recente publicado."""
    if con_abertos is None:
        return {}
    try:
        # o nome do exercício MAIS RECENTE em que o órgão aparece (órgão extinto/renomeado fica com o último nome)
        rows = con_abertos.execute(
            "SELECT orgao, nome_orgao, substr(posicao,4)||substr(posicao,1,2) k FROM da_despesa "
            "WHERE COALESCE(nome_orgao,'')<>'' GROUP BY orgao, nome_orgao").fetchall()
    except sqlite3.OperationalError:
        return {}
    out: dict[str, tuple] = {}
    for o, n, k in rows:
        if o and (o not in out or k > out[o][1]):
            out[str(o)] = (n.strip(), k)
    return {o: v[0] for o, v in out.items()}


def ug_para_orgao(con_abertos: sqlite3.Connection | None) -> dict[str, str]:
    """UG → órgão orçamentário, pelo cadastro do TFE: o órgão onde está a MAIOR parte do empenho da UG.

    Medido 13/11/2026: "órgão = 2 primeiros dígitos da UG" erra a administração indireta (044100 DER-RJ,
    045200 EMOP, 043400 AGETRANSP começam com 04, mas são de outro órgão). Crédito descentralizado de outro órgão
    não muda o dono da UG: vale a maior fatia."""
    if con_abertos is None:
        return {}
    try:
        rows = con_abertos.execute("SELECT ug, orgao, SUM(ABS(COALESCE(valor_empenhado,0))) v FROM da_despesa "
                                   "GROUP BY ug, orgao").fetchall()
    except sqlite3.OperationalError:
        return {}
    melhor: dict[str, tuple] = {}
    for ug, o, v in rows:
        if ug and o and (ug not in melhor or v > melhor[ug][1]):
            melhor[str(ug)] = (str(o), v or 0)
    return {u: x[0] for u, x in melhor.items()}


def _resolucoes(con: sqlite3.Connection) -> dict[tuple, Counter]:
    out: dict[tuple, Counter] = defaultdict(Counter)
    try:
        for cnpj, ug, v in con.execute("SELECT cnpj, ug, veredito FROM resolucao_duplicidade"):
            out[(cnpj, str(ug))][v] += 1
    except sqlite3.OperationalError:
        pass
    return out


def _detectores(con_ach: sqlite3.Connection | None) -> dict[tuple, list[dict]]:
    out: dict[tuple, list[dict]] = defaultdict(list)
    if con_ach is None:
        return out
    import re
    try:
        from compliance_agent.detectores import REGISTRO
        from compliance_agent.detectores.c_fachada import _MAPA_C
    except ImportError:
        REGISTRO, _MAPA_C = {}, {}
    try:
        for ug, cnpj, det, score, motivo in con_ach.execute(
                "SELECT ug, processo, detector, score, motivo FROM achado_detector WHERE status='confirmado'"):
            # "confirmado" no achados.db = a régua do detector disparou — é INDÍCIO. Só a hipótese de fachada que o
            # próprio motivo diz CONFIRMADO (ex.: "H-SITUACAO (CONFIRMADO/ALTO)") sobe para CONFIRMADO.
            m = re.match(r"(H-[A-Z-]+)\s*\((\w+)/(\w+)\)", motivo or "")
            if m and m.group(1) in _MAPA_C:
                titulo = _MAPA_C[m.group(1)][1]
                status = "CONFIRMADO" if m.group(2).upper() == "CONFIRMADO" else "INDICIO"
            else:
                d = REGISTRO.get(det)
                titulo = getattr(d, "nome", "") or f"Detector {det}"
                status = "INDICIO"
            out[(str(cnpj), str(ug))].append({"codigo": det, "status": status, "titulo": titulo,
                                              "evidencia": (motivo or "")[:300], "score": score,
                                              "fonte": "detector"})
    except sqlite3.OperationalError:
        pass
    return out


def _achados_da_pericia(aj: str) -> list[dict]:
    try:
        ach = json.loads(aj or "[]")
    except ValueError:
        return []
    return [{"codigo": a.get("codigo"), "status": a.get("status"), "titulo": a.get("titulo"),
             "evidencia": (a.get("evidencia") or "")[:400]}
            for a in ach if a.get("status") in ("INDICIO", "CONFIRMADO")]


def _doc(cnpj: str) -> tuple[str, str]:
    """(tipo, documento exibível). Pessoa física (11 dígitos) sai com CPF MASCARADO — LGPD/regra da casa."""
    from compliance_agent.osint.vinculos import mascarar_cpf
    d = "".join(ch for ch in str(cnpj or "") if ch.isdigit())
    return ("CPF", mascarar_cpf(d)) if len(d) == 11 else ("CNPJ", d or str(cnpj or ""))


def _grau_da_linha(grau: str, extras: list[dict]) -> str:
    """Grau exibido = o MAIOR entre a perícia e os achados de detector (a linha não pode dizer 🟢 ao lado de 🔴)."""
    if grau == "🔴" or any(x.get("status") == "CONFIRMADO" for x in extras):
        return "🔴"
    if grau == "🟡" or extras:
        return "🟡"
    return grau


def montar(limite_por_orgao: int = 40, orgao: str = "") -> dict:
    """Órgão a órgão: resumo + fornecedores com problema (maior valor pago primeiro). `orgao` = só esse órgão
    (a tela abre 15 por órgão e busca o resto sob demanda — 42 órgãos × 60 linhas travavam o painel)."""
    chave = ("montar", limite_por_orgao, orgao)
    if chave in _CACHE and time.time() - _CACHE[chave][0] < _TTL:
        return _CACHE[chave][1]
    con, con_ach, con_ab = _ro(DB), _ro(DB_ACHADOS), _ro(DB_ABERTOS)
    if con is None:
        return {"ok": False, "erro": "compliance.db ausente"}
    try:
        nomes = nomes_orgao(con_ab)
        dono = ug_para_orgao(con_ab)
        resol = _resolucoes(con)
        dets = _detectores(con_ach)
        org: dict[str, dict] = {}
        vistos: set[tuple] = set()
        for r in con.execute("SELECT cnpj, ug, favorecido, grau, score, total_pago, n_obs, achados_json "
                             "FROM pericia_fornecedor"):
            ug = str(r["ug"])
            o = dono.get(ug, ug[:2])
            d = org.setdefault(o, {"orgao": o, "nome": INSTITUICOES.get(o) or nomes.get(o) or f"Órgão {o}",
                                   "nome_oficial": nomes.get(o, ""), "poder": PODER.get(o, "Executivo"),
                                   "instituicao_da_comissao": o in INSTITUICOES, "ugs": set(),
                                   "fornecedores": 0, "total_pago": 0.0, "graus": Counter(),
                                   "valor_com_problema": 0.0, "problemas": []})
            d["ugs"].add(ug)
            d["fornecedores"] += 1
            d["total_pago"] += r["total_pago"] or 0
            d["graus"][r["grau"]] += 1
            extra = dets.get((r["cnpj"], ug), [])
            vistos.add((r["cnpj"], ug))
            if r["grau"] in ("🔴", "🟡") or extra:
                rs = resol.get((r["cnpj"], ug))
                d["valor_com_problema"] += r["total_pago"] or 0
                tipo, doc = _doc(r["cnpj"])
                d["problemas"].append({
                    "cnpj": doc, "tipo_doc": tipo, "fornecedor": r["favorecido"], "ug": ug,
                    "grau": _grau_da_linha(r["grau"], extra),
                    "score": r["score"], "total_pago": round(r["total_pago"] or 0, 2), "n_obs": r["n_obs"],
                    "achados": _achados_da_pericia(r["achados_json"]) + extra,
                    "duplicidade": dict(rs) if rs else None})
        # fornecedor só com achado de detector (sem par na perícia)
        for (cnpj, ug), lst in dets.items():
            if (cnpj, ug) in vistos or not ug or len(ug) < 2:
                continue
            o = dono.get(ug, ug[:2])
            d = org.setdefault(o, {"orgao": o, "nome": INSTITUICOES.get(o) or nomes.get(o) or f"Órgão {o}",
                                   "nome_oficial": nomes.get(o, ""), "poder": PODER.get(o, "Executivo"),
                                   "instituicao_da_comissao": o in INSTITUICOES, "ugs": set(), "fornecedores": 0,
                                   "total_pago": 0.0, "graus": Counter(), "valor_com_problema": 0.0,
                                   "problemas": []})
            d["ugs"].add(ug)
            tipo, doc = _doc(cnpj)
            d["problemas"].append({"cnpj": doc, "tipo_doc": tipo, "fornecedor": "", "ug": ug,
                                   "grau": "🔴" if any(x["status"] == "CONFIRMADO" for x in lst) else "🟡",
                                   "score": max((x.get("score") or 0) for x in lst), "total_pago": 0.0, "n_obs": 0,
                                   "achados": lst, "duplicidade": None})
        saida = []
        for d in org.values():
            if orgao and d["orgao"] != orgao:
                continue
            d["problemas"].sort(key=lambda p: (-(p["grau"] == "🔴"), -(p["total_pago"] or 0)))
            d["n_problemas"] = len(d["problemas"])
            d["problemas"] = d["problemas"][:limite_por_orgao]
            d["ugs"] = sorted(d["ugs"])
            d["graus"] = dict(d["graus"])
            d["total_pago"] = round(d["total_pago"], 2)
            d["valor_com_problema"] = round(d["valor_com_problema"], 2)
            saida.append(d)
        ordem_inst = list(INSTITUICOES)
        saida.sort(key=lambda d: (0 if d["instituicao_da_comissao"] else 1,
                                  ordem_inst.index(d["orgao"]) if d["orgao"] in INSTITUICOES else 0,
                                  -d["valor_com_problema"]))
        res = {"ok": True, "gerado_em": time.strftime("%Y-%m-%d %H:%M:%S"), "orgaos": saida,
               "totais": {"orgaos": len(saida), "fornecedores_com_problema": sum(d["n_problemas"] for d in saida),
                          "valor_com_problema": round(sum(d["valor_com_problema"] for d in saida), 2)},
               "ressalva": ("Indício não é acusação; presunção de legitimidade. Valor = OB Contabilizado no SIAFE "
                            "(empenho não é pago). 🟡 = um ou mais indícios determinados a apurar; 🔴 = fato "
                            "confirmado. Duplicidade por competência só se confirma pela nota fiscal.")}
        _CACHE[chave] = (time.time(), res)
        return res
    finally:
        for c in (con, con_ach, con_ab):
            if c is not None:
                c.close()
