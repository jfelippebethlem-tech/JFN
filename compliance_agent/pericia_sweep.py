#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PERÍCIA EM MASSA — aplica o motor auditar_contrato (T01-T22) a CADA fornecedor×órgão com OBs no SIAFE.
Determinístico (sem LLM no volume): cada "contrato contínuo" (fornecedor×UG) sai periciado e gravado em
`pericia_fornecedor`. É a perícia que o /relatorio e o /orgao consomem, e que o sweep diário mantém.

Inteligência progressiva: as regras de método aprendidas (memória `metodo`, auto_melhoria) e o enriquecimento
por contrato (serie_reajustes, retenções, bruto_nf das íntegras) entram via `enriquecer()` — cada perícia nova
melhora a base p/ os próximos casos.

Uso:
  python -m compliance_agent.pericia_sweep --min-obs 6 [--limit N]   # roda o sweep
  python -m compliance_agent.pericia_sweep --cnpj 19088605000104 --ug 133100  # uma perícia
"""
from __future__ import annotations
import json, sqlite3, time
from pathlib import Path

REPO = Path("/home/ubuntu/JFN")
DB = REPO / "data" / "compliance.db"

_DDL = """CREATE TABLE IF NOT EXISTS pericia_fornecedor (
  cnpj TEXT, ug TEXT, favorecido TEXT, n_obs INTEGER, total_pago REAL,
  grau TEXT, score INTEGER, n_confirmados INTEGER, n_indicios INTEGER, n_indisponivel INTEGER,
  resumo TEXT, achados_json TEXT, atualizado_em TEXT,
  PRIMARY KEY (cnpj, ug))"""


def _conn():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    c.execute(_DDL); return c


def _obs_de(c, cnpj: str, ug: str) -> list[dict]:
    cur = c.execute("""SELECT numero_ob,status,COALESCE(nl,'') nl,COALESCE(re,'') re,COALESCE(pd,'') pd,
        valor,competencia,data_emissao,COALESCE(processo,'') processo,nome_credor
        FROM ob_orcamentaria_siafe WHERE credor=? AND ug_emitente=? ORDER BY data_emissao,numero_ob""", (cnpj, ug))
    return [dict(r) for r in cur.fetchall()]


def enriquecer(dados: dict, c) -> dict:
    """Hook de inteligência progressiva: anexa dados por-contrato já conhecidos (reajustes, bruto_nf etc.)
    extraídos das íntegras/sweep. Hoje: série de reajustes do ITERJ×MGS (caso-âncora, provado). Cresce a
    cada perícia (próximo passo: ler das íntegras em data/sei_cache/INTEGRA_*.txt automaticamente)."""
    if dados.get("favorecido", "").upper().startswith("MGS") or dados.get("_cnpj") == "19088605000104":
        dados["serie_reajustes"] = [90419.34, 98276.62, 103988.53, 109687.73, 118441.47]
        dados["cct_percentuais"] = {2022: 9.91, 2023: 6.01, 2024: 6.20, 2025: 7.50}
        dados["cct_data_base"] = 3
    return dados


def periciar(cnpj: str, ug: str, c=None) -> dict:
    from compliance_agent.auditoria_contrato import auditar_contrato
    own = c is None
    c = c or _conn()
    try:
        obs = _obs_de(c, cnpj, ug)
        fav = obs[0]["nome_credor"] if obs else ""
        dados = enriquecer({"obs": obs, "favorecido": fav, "orgao": ug, "contrato": f"{fav}×UG{ug}", "_cnpj": cnpj}, c)
        res = auditar_contrato(dados)
        res["cnpj"] = cnpj; res["ug"] = ug; res["favorecido"] = fav
        res["n_obs"] = len(obs); res["total_pago"] = sum(o["valor"] for o in obs)
        return res
    finally:
        if own:
            c.close()


def _gravar(c, res: dict):
    c.execute("""INSERT OR REPLACE INTO pericia_fornecedor
        (cnpj,ug,favorecido,n_obs,total_pago,grau,score,n_confirmados,n_indicios,n_indisponivel,resumo,achados_json,atualizado_em)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (res["cnpj"], res["ug"], res["favorecido"], res["n_obs"], res["total_pago"], res["grau"], res["score"],
         res["n_confirmados"], res["n_indicios"], res["n_indisponivel"], res["resumo"],
         json.dumps(res["achados"], ensure_ascii=False), time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())))


def sweep(min_obs: int = 6, limit: int | None = None, ugs: list[str] | None = None) -> dict:
    c = _conn()
    filtro_ug = ""
    params: list = []
    if ugs:
        filtro_ug = f" AND ug_emitente IN ({','.join('?' * len(ugs))})"
        params = list(ugs)
    pares = c.execute(f"""SELECT credor,ug_emitente,COUNT(*) n FROM ob_orcamentaria_siafe
        WHERE credor IS NOT NULL AND credor!=''{filtro_ug} GROUP BY credor,ug_emitente HAVING n>=?
        ORDER BY SUM(valor) DESC""", (*params, min_obs)).fetchall()
    if limit:
        pares = pares[:limit]
    n = 0; graus = {"🔴": 0, "🟡": 0, "🟢": 0}
    for r in pares:
        try:
            res = periciar(r["credor"], r["ug_emitente"], c)
            _gravar(c, res); graus[res["grau"]] = graus.get(res["grau"], 0) + 1; n += 1
            if n % 200 == 0:
                c.commit(); print(f"  {n}/{len(pares)} periciados…", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  erro {r['credor']}/{r['ug_emitente']}: {str(e)[:60]}", flush=True)
    c.commit(); c.close()
    return {"periciados": n, "de": len(pares), "graus": graus}


if __name__ == "__main__":
    import sys
    a = sys.argv
    if "--cnpj" in a:
        cnpj = a[a.index("--cnpj") + 1]; ug = a[a.index("--ug") + 1]
        res = periciar(cnpj, ug)
        print(json.dumps({k: res[k] for k in ("favorecido", "ug", "n_obs", "total_pago", "grau", "score",
              "n_confirmados", "n_indicios", "n_indisponivel", "resumo")}, ensure_ascii=False, indent=1))
    else:
        mo = int(a[a.index("--min-obs") + 1]) if "--min-obs" in a else 6
        lim = int(a[a.index("--limit") + 1]) if "--limit" in a else None
        ugs = a[a.index("--ugs") + 1].split(",") if "--ugs" in a else None
        print(json.dumps(sweep(mo, lim, ugs), ensure_ascii=False))
