# -*- coding: utf-8 -*-
"""
BENCHMARK das IAs do ecossistema (Claude baseline × IAs fracas).

Loop de 5 passos (docs/IAS-ECOSSISTEMA-BENCHMARK.md):
  1) GABARITO: Claude roda cada função 1x  -> data/benchmark_ias_gold.json
  2) REAL: rodar nas IAs fracas (Gemini/Qwen/nous) e capturar a saída
  3) COMPARAR: pontuar candidato × gold -> data/benchmark_ias.csv
  4) MELHORAR: ajustar instrução e re-rodar
  5) DIA A DIA: tarefa crítica -> modelo forte; simples -> barato

Este módulo é o arcabouço: carrega o gold, verifica deterministicamente o que dá (T5/SQL),
registra pontuações e monta o painel. As tarefas de juízo (T1/T2/T6) são pontuadas pela rubrica
(manual ou por um juiz-LLM) usando o `criterio_sucesso` do gold.

CLI:
    python -m compliance_agent.benchmark_ias --gold              # mostra o gabarito
    python -m compliance_agent.benchmark_ias --verificar-sql "SELECT ..."   # checa T5 contra o banco
    python -m compliance_agent.benchmark_ias --registrar Qwen T2 2.5 "resumiu ok, faltou aviso"
    python -m compliance_agent.benchmark_ias --painel           # tabela modelo × tarefa
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
from datetime import datetime

_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_GOLD = os.path.join(_BASE, "data", "benchmark_ias_gold.json")
_CSV = os.path.join(_BASE, "data", "benchmark_ias.csv")
_DB = os.environ.get("JFN_DB", os.path.join(_BASE, "data", "compliance.db"))


def carregar_gold() -> dict:
    with open(_GOLD, encoding="utf-8") as f:
        return json.load(f)


def gold_de(tarefa_id: str) -> dict:
    for t in carregar_gold().get("tarefas", []):
        if t["id"] == tarefa_id:
            return t
    return {}


def verificar_sql_concentracao(sql_candidato: str) -> dict:
    """T5: roda o SQL candidato e compara o nº de grupos com o gold (regra de concentração)."""
    g = gold_de("T5").get("gold", {})
    con = sqlite3.connect(_DB)
    try:
        try:
            n_cand = len(con.execute(sql_candidato).fetchall())
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "erro": f"SQL candidato falhou: {str(exc)[:120]}"}
        n_gold = len(con.execute(g["sql"]).fetchall())
    finally:
        con.close()
    dif = abs(n_cand - n_gold) / max(n_gold, 1)
    return {"ok": True, "n_candidato": n_cand, "n_gold": n_gold,
            "dentro_5pct": dif <= 0.05, "score": 3.0 if dif <= 0.05 else (2.0 if dif <= 0.20 else 1.0)}


def registrar(modelo: str, tarefa: str, score: float, notas: str = "") -> None:
    novo = not os.path.exists(_CSV)
    with open(_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if novo:
            w.writerow(["data", "modelo", "tarefa", "score", "notas"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), modelo, tarefa, score, notas])


def painel() -> None:
    if not os.path.exists(_CSV):
        print("(sem registros ainda — rode o Passo 2/3 e registre)"); return
    linhas = list(csv.DictReader(open(_CSV, encoding="utf-8")))
    modelos = sorted({l["modelo"] for l in linhas})
    tarefas = sorted({l["tarefa"] for l in linhas})
    print("tarefa\\modelo |", " | ".join(modelos))
    for t in tarefas:
        row = []
        for m in modelos:
            scs = [float(l["score"]) for l in linhas if l["modelo"] == m and l["tarefa"] == t]
            row.append(f"{sum(scs)/len(scs):.1f}" if scs else "-")
        print(f"  {t:10s} |", " | ".join(row))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Benchmark das IAs do ecossistema (Claude × fracas).")
    ap.add_argument("--gold", action="store_true")
    ap.add_argument("--verificar-sql", type=str, default=None)
    ap.add_argument("--registrar", nargs=4, metavar=("MODELO", "TAREFA", "SCORE", "NOTAS"), default=None)
    ap.add_argument("--painel", action="store_true")
    a = ap.parse_args()
    if a.gold:
        print(json.dumps(carregar_gold(), ensure_ascii=False, indent=2))
    if a.verificar_sql:
        print(json.dumps(verificar_sql_concentracao(a.verificar_sql), ensure_ascii=False, indent=2))
    if a.registrar:
        registrar(a.registrar[0], a.registrar[1], float(a.registrar[2]), a.registrar[3])
        print("registrado.")
    if a.painel:
        painel()
