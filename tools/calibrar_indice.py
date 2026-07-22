# -*- coding: utf-8 -*-
"""Calibração LOCAL do Índice de Direcionamento contra desfechos verificáveis do RJ.

A docstring do `editais/indice_certame` avisa: "pesos = ponto de partida dos benchmarks;
ARACHNE ensina que score sem calibração local vira ruído". Este relatório READ-ONLY cruza
o `certame_indice` com desfechos que a própria base já conhece — SEM circularidade barata:
o desfecho "vencedor veio a ser sancionado DEPOIS do certame" não alimenta o score (a família
fraude_cadastral só olha sanção vigente ANTES/na publicação), então serve de proxy honesto.

Desfechos usados (proxy de "certame problemático"):
  A. vencedor sancionado APÓS a data de publicação (sanção futura — não entra no score);
  B. vencedor com fantasma_score ALTO (entra no score via fraude_cadastral — reportado em
     separado, NÃO usado na AUC principal, para não medir o eco do próprio índice);
  C. certame com caso de fiscalização promovido (tabela caso, tipos != direcionamento).

Saídas: reports/calibracao_indice.md (+ .json) — distribuição de score por desfecho,
AUC (ordenação) por par, contribuição média por família e recomendação de pesos
(só documenta; NUNCA altera pesos automaticamente).

Uso:  PYTHONPATH=. .venv/bin/python -m tools.calibrar_indice
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DB = RAIZ / "data" / "compliance.db"
OUT_MD = RAIZ / "reports" / "calibracao_indice.md"
OUT_JSON = RAIZ / "reports" / "calibracao_indice.json"


def _auc(pos: list[float], neg: list[float]) -> float | None:
    """AUC por ranking (Mann-Whitney): P(score_problemático > score_limpo). None se lado vazio."""
    if not pos or not neg:
        return None
    wins = ties = 0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1
            elif p == n:
                ties += 1
    return round((wins + ties / 2) / (len(pos) * len(neg)), 3)


def coletar(db_path: str | Path = DB) -> dict:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        idx = {r["certame"]: dict(r) for r in con.execute(
            "SELECT certame, score, faixa, confianca, familias_json FROM certame_indice")}
        # vencedor + data de publicação por certame (ordem 1 = vencedor)
        venc = {}
        for r in con.execute(
                "SELECT certame, fornecedor_cnpj, MIN(data_pub) AS data_pub FROM pncp_resultado "
                "WHERE ordem_classificacao=1 AND fornecedor_cnpj IS NOT NULL GROUP BY certame"):
            venc[r["certame"]] = (r["fornecedor_cnpj"], r["data_pub"])
        # A. sanção INICIADA depois da publicação (não entra no score → proxy independente)
        sanc_pos = set()
        for c, (cnpj, dpub) in venc.items():
            if c not in idx or not dpub:
                continue
            hit = con.execute(
                "SELECT 1 FROM sancoes_federais WHERE "
                "REPLACE(REPLACE(REPLACE(cpf_cnpj,'.',''),'/',''),'-','')=? AND data_inicio>? "
                "LIMIT 1", (cnpj, dpub)).fetchone()
            if hit:
                sanc_pos.add(c)
        # B. fantasma alto (ecoa o score — reportar em separado)
        fant = {r[0] for r in con.execute(
            "SELECT DISTINCT p.certame FROM pncp_resultado p JOIN fantasma_score f "
            "ON f.cnpj=p.fornecedor_cnpj WHERE p.ordem_classificacao=1 AND f.score>=60")}
        # C. certame citado em caso promovido (fora do tipo 'direcionamento', que é o próprio índice)
        casos = {r[0] for r in con.execute(
            "SELECT DISTINCT alvo FROM caso WHERE tipo_achado!='direcionamento'") if r[0] in idx}
        # contribuição por família (entre os apuráveis)
        fam_contrib: dict[str, list[float]] = {}
        for d in idx.values():
            for nome, f in (json.loads(d["familias_json"] or "{}")).items():
                if isinstance(f, dict) and f.get("apuravel"):
                    pior = max((x.get("valor", 0) for x in f.get("flags", [])), default=0.0)
                    fam_contrib.setdefault(nome, []).append(pior)
        return {"idx": idx, "sanc_pos": sanc_pos, "fant": fant, "casos": casos,
                "fam_contrib": fam_contrib}
    finally:
        con.close()


def relatorio(db_path: str | Path = DB) -> dict:
    d = coletar(db_path)
    idx = d["idx"]
    scores = {c: (v["score"] or 0.0) for c, v in idx.items()}

    def _lados(grupo: set) -> tuple[list, list]:
        pos = [s for c, s in scores.items() if c in grupo]
        neg = [s for c, s in scores.items() if c not in grupo]
        return pos, neg

    res: dict = {"n_certames": len(idx)}
    for nome, grupo in (("sancao_posterior", d["sanc_pos"]), ("caso_promovido", d["casos"]),
                        ("fantasma_alto_eco", d["fant"])):
        pos, neg = _lados(grupo)
        res[nome] = {"n_pos": len(pos), "auc": _auc(pos, neg),
                     "media_pos": round(sum(pos) / len(pos), 1) if pos else None,
                     "media_neg": round(sum(neg) / len(neg), 1) if neg else None}
    res["familias"] = {k: {"n_apuravel": len(v), "media": round(sum(v) / len(v), 3)}
                       for k, v in sorted(d["fam_contrib"].items())}
    return res


def main() -> int:
    res = relatorio()
    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    ln = ["# Calibração do Índice de Direcionamento — desfechos RJ", "",
          f"Universo: **{res['n_certames']}** certames com índice persistido.", "",
          "| Desfecho (proxy) | n | AUC (ordenação) | média score c/ desfecho | média sem |",
          "|---|---|---|---|---|"]
    rotulo = {"sancao_posterior": "Vencedor sancionado APÓS o certame (independente do score)",
              "caso_promovido": "Caso de fiscalização promovido (≠ direcionamento)",
              "fantasma_alto_eco": "Vencedor fantasma ≥60 (ECO do score — só contexto)"}
    for k, r in res.items():
        if k in rotulo:
            ln.append(f"| {rotulo[k]} | {r['n_pos']} | {r['auc'] if r['auc'] is not None else 'INDISPONÍVEL'} "
                      f"| {r['media_pos'] if r['media_pos'] is not None else '—'} | {r['media_neg'] or '—'} |")
    ln += ["", "## Contribuição por família (entre os certames onde a família é apurável)", "",
           "| Família | n apurável | valor médio |", "|---|---|---|"]
    for k, f in res["familias"].items():
        ln.append(f"| {k} | {f['n_apuravel']} | {f['media']} |")
    ln += ["", "## Leitura e recomendação", "",
           "- AUC ~0,5 = o score NÃO separa o desfecho; >0,65 = ordenação útil; a leitura vale por",
           "  desfecho, e amostras pequenas (n<10) são INDISPONÍVEL na prática — não conclusão.",
           "- **Nenhum peso é alterado automaticamente.** Ajuste de `_PESOS_FAMILIA` só com AUC",
           "  consistente em ≥2 desfechos independentes e n adequado, documentado aqui.",
           "- Famílias com n apurável baixo (conluio/preço/execução) precisam de COLETA, não de peso:",
           "  proposta_item (lances) e ponte compra→contrato mudam a cobertura, o peso não."]
    OUT_MD.write_text("\n".join(ln))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"\nrelatório: {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
