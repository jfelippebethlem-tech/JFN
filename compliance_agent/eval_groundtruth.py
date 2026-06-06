# -*- coding: utf-8 -*-
"""
Onda 3 — Avaliação do motor contra GROUND-TRUTH do TCE-RJ (penalidades_tcerj).

Pergunta honesta: os órgãos que o motor do JFN aponta como mais arriscados (concentração/captura e score médio de
anomalia) **coincidem** com os órgãos que o TCE-RJ efetivamente **puniu** (multas/condenações)?

Limitação assumida: `penalidades_tcerj` **não traz CNPJ** — só `orgao` (nome) e `processo` (nº TCE, não SEI). Logo
a avaliação é a **nível de ÓRGÃO**, casando o nome do órgão punido com a UG das Ordens Bancárias (match por nome
normalizado). É um sinal aproximado, não um rótulo por contrato. Mede AUC de "score do órgão" como preditor de
"órgão foi punido" — um teste de calibração do motor, não prova de irregularidade.

CLI:
    python -m compliance_agent.eval_groundtruth
"""
from __future__ import annotations

import json
import re
import unicodedata

from compliance_agent.duckdb_util import conectar


def _norm(s: str) -> str:
    """Normaliza nome de órgão p/ casar entre fontes: maiúsculas, sem acento, abreviações comuns expandidas."""
    s = (s or "").upper()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"\b(SEC|SECR)\b", "SECRETARIA", s)
    s = re.sub(r"\bEST\b", "ESTADO", s)
    s = re.sub(r"\bFUND\b", "FUNDO", s)
    s = re.sub(r"\bESP\b", "ESPECIAL", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


_STOP = {"DE", "DO", "DA", "DOS", "DAS", "E", "ESTADO", "SECRETARIA", "FUNDO", "ESPECIAL", "EM", "DO RJ"}


def _tokens(s: str) -> set:
    return {t for t in _norm(s).split() if t not in _STOP and len(t) >= 4}


def avaliar() -> dict:
    con = conectar()
    try:
        # 1) métricas por UG (DuckDB): total pago, captura (top share), score médio de anomalia, taxa de redflag
        ugs = con.execute("""
            WITH forn AS (
                SELECT ug_codigo, ANY_VALUE(ug_nome) ug_nome, favorecido_cpf, SUM(valor) tot
                FROM db.ordens_bancarias WHERE valor>0 GROUP BY ug_codigo, favorecido_cpf
            ), cap AS (
                SELECT ug_codigo, ANY_VALUE(ug_nome) ug_nome, SUM(tot) total, MAX(tot) topv, COUNT(*) nf
                FROM forn GROUP BY ug_codigo
            ), sc AS (
                SELECT o.ug_codigo, AVG(a.score) score_medio, COUNT(*) n_ob,
                       SUM(a.score * o.valor) / NULLIF(SUM(o.valor),0) score_ponderado
                FROM db.ordens_bancarias o JOIN db.ob_anomaly a ON a.ob_id=o.id
                GROUP BY o.ug_codigo
            )
            SELECT cap.ug_codigo, cap.ug_nome, cap.total, cap.topv/cap.total AS top_share, cap.nf,
                   COALESCE(sc.score_medio,0) score_medio, COALESCE(sc.score_ponderado,0) score_ponderado
            FROM cap LEFT JOIN sc USING (ug_codigo)
            WHERE cap.total > 0
        """).fetchall()

        # 2) órgãos punidos pelo TCE-RJ
        punidos = con.execute("""
            SELECT orgao, COUNT(*) n_pen, SUM(valor) val_pen
            FROM db.penalidades_tcerj WHERE orgao IS NOT NULL AND orgao!='' GROUP BY orgao
        """).fetchall()
    finally:
        con.close()

    pun_tokens = [( _tokens(o), o, n, v) for o, n, v in punidos]

    rows = []
    for ug, ugn, total, top_share, nf, score_medio, score_pond in ugs:
        tks = _tokens(ugn or "")
        punido = 0
        match_nome = ""
        if tks:
            for ptk, pnome, pn, pv in pun_tokens:
                inter = tks & ptk
                # casa se compartilham >=2 tokens significativos (ou 1 token raro e específico)
                if len(inter) >= 2:
                    punido = 1
                    match_nome = pnome
                    break
        rows.append({"ug": ug, "ug_nome": ugn, "total": float(total),
                     "top_share": round((top_share or 0) * 100, 1), "n_fornecedores": nf,
                     "score_medio": round(score_medio or 0, 4),
                     "score_ponderado": round(score_pond or 0, 4), "punido": punido, "match_tce": match_nome})

    n_pun = sum(r["punido"] for r in rows)
    resultado = {"n_ugs": len(rows), "n_orgaos_punidos_tce": len(punidos),
                 "n_ugs_casadas_punidas": n_pun}

    # 3) AUC: o score do órgão prediz "foi punido"? (precisa de variação nas duas classes)
    if 0 < n_pun < len(rows):
        try:
            from sklearn.metrics import roc_auc_score
            y = [r["punido"] for r in rows]
            resultado["auc_top_share"] = round(roc_auc_score(y, [r["top_share"] for r in rows]), 3)
            resultado["auc_score_medio"] = round(roc_auc_score(y, [r["score_medio"] for r in rows]), 3)
            resultado["auc_score_ponderado"] = round(roc_auc_score(y, [r["score_ponderado"] for r in rows]), 3)
            resultado["auc_total_pago"] = round(roc_auc_score(y, [r["total"] for r in rows]), 3)
        except Exception as exc:  # noqa: BLE001
            resultado["auc_erro"] = str(exc)[:120]

    # 4) ranking: UGs de maior risco pelo motor, marcando quais o TCE puniu (precisão no topo)
    top = sorted(rows, key=lambda r: (r["score_medio"], r["top_share"]), reverse=True)[:20]
    resultado["top20_por_score"] = [{"ug": r["ug"], "ug_nome": r["ug_nome"], "score_medio": r["score_medio"],
                                     "top_share": r["top_share"], "punido_tce": bool(r["punido"])} for r in top]
    resultado["precisao_top20"] = round(sum(r["punido"] for r in top) / len(top), 2) if top else 0
    resultado["nota"] = ("Avaliação a nível de ÓRGÃO (penalidades sem CNPJ); match por nome normalizado. "
                         "AUC>0.5 indica que o motor ranqueia órgãos punidos acima da média — sinal de calibração, "
                         "não prova de irregularidade.")
    return resultado


if __name__ == "__main__":
    print(json.dumps(avaliar(), ensure_ascii=False, indent=2, default=str))
