# -*- coding: utf-8 -*-
"""Coletor de RECEITA mensal do Estado do RJ (TFE — Transparência Fiscal), via Dados Abertos (CKAN).

Pedido do dono: avaliar se o governo segue a LOA (previsto × realizado) e comparar receita × despesa.
Fonte (grátis, sem chave): https://dadosabertos.rj.gov.br dataset `tfe-receita` → 1 CSV mensal 2016→atual,
por Poder / Categoria Econômica / Fonte / Rubrica / Alínea / Órgão / UG, com 4 valores:
  Previsão Inicial (LOA) · Previsão Atualizada · Receita a Realizar · Receita Realizada (arrecadado).

Honesto: o CSV tem preâmbulo (5 linhas) antes do cabeçalho; encoding latin-1; números sem separador decimal
(tratados como reais inteiros — VERIFICAR unidade contra um total conhecido antes de afirmar valor). Idempotente.
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
from pathlib import Path

import httpx

_REPO = Path(__file__).resolve().parent.parent.parent
_DB = _REPO / "data" / "compliance.db"
_CACHE = _REPO / "data" / "tfe_cache"
_CKAN = "https://dadosabertos.rj.gov.br/api/3/action/package_show"
_PKG = "tfe-receita"

# índice de coluna → campo (cabeçalho na 6ª linha; 27 colunas)
_COLS = {0: "competencia", 1: "poder_cod", 2: "poder", 3: "cat_econ_cod", 4: "cat_econ",
         5: "fonte_cod", 6: "fonte", 17: "orgao_cod", 18: "orgao", 19: "ug_cod", 20: "ug",
         21: "fonte_rec_cod", 22: "fonte_rec",
         23: "previsao_inicial", 24: "previsao_atualizada", 25: "a_realizar", 26: "realizada"}
_VALOR_COLS = ("previsao_inicial", "previsao_atualizada", "a_realizar", "realizada")


def _num(s: str) -> float:
    s = re.sub(r"[^\d,.-]", "", str(s or "")).replace(".", "").replace(",", ".")
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def url_recurso() -> str:
    d = httpx.get(_CKAN, params={"id": _PKG}, timeout=30).json()["result"]
    return d["resources"][0]["url"]


def baixar(force: bool = False) -> Path:
    """Baixa o CSV p/ cache (regenerável). Retorna o caminho."""
    _CACHE.mkdir(parents=True, exist_ok=True)
    fp = _CACHE / "tfe_receita.csv"
    if fp.exists() and not force and fp.stat().st_size > 1000:
        return fp
    url = url_recurso()
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        with open(fp, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    return fp


def parsear(caminho: Path | None = None, limite: int | None = None):
    """Gera dicts de receita (pula o preâmbulo de 5 linhas; latin-1; csv ';'). competencia=MM/YYYY → ano/mes."""
    fp = caminho or (_CACHE / "tfe_receita.csv")
    with open(fp, encoding="latin-1") as f:
        linhas = f.read().splitlines()
    # acha o cabeçalho real (linha que começa com "Posição")
    h = next((i for i, l in enumerate(linhas) if l.lower().startswith('"posi') or l.lower().startswith("posi")), 5)
    n = 0
    for l in linhas[h + 1:]:
        if not l.strip():
            continue
        row = next(csv.reader(io.StringIO(l), delimiter=";"), [])
        if len(row) < 27:
            continue
        reg = {campo: row[i] for i, campo in _COLS.items()}
        comp = (reg.get("competencia") or "").strip()
        m = re.match(r"(\d{1,2})/(\d{4})", comp)
        reg["mes"] = int(m.group(1)) if m else 0
        reg["ano"] = int(m.group(2)) if m else 0
        for c in _VALOR_COLS:
            reg[c] = _num(reg.get(c))
        yield reg
        n += 1
        if limite and n >= limite:
            break


def _criar_tabela(con):
    con.execute("""CREATE TABLE IF NOT EXISTS receitas (
        competencia TEXT, ano INTEGER, mes INTEGER, poder TEXT, cat_econ TEXT, fonte TEXT,
        orgao_cod TEXT, orgao TEXT, ug_cod TEXT, ug TEXT, fonte_rec TEXT,
        previsao_inicial REAL, previsao_atualizada REAL, a_realizar REAL, realizada REAL,
        chave TEXT PRIMARY KEY)""")


def ingerir(caminho: Path | None = None, limite: int | None = None) -> dict:
    """Ingere na tabela `receitas` (idempotente por chave natural). Retorna {n, anos}."""
    con = sqlite3.connect(str(_DB))
    _criar_tabela(con)
    n = 0
    anos = set()
    for reg in parsear(caminho, limite):
        chave = "|".join(str(reg.get(k, "")) for k in
                         ("competencia", "orgao_cod", "ug_cod", "fonte", "cat_econ", "fonte_rec"))
        con.execute(
            "INSERT OR REPLACE INTO receitas (competencia,ano,mes,poder,cat_econ,fonte,orgao_cod,orgao,"
            "ug_cod,ug,fonte_rec,previsao_inicial,previsao_atualizada,a_realizar,realizada,chave) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (reg["competencia"], reg["ano"], reg["mes"], reg.get("poder"), reg.get("cat_econ"),
             reg.get("fonte"), reg.get("orgao_cod"), reg.get("orgao"), reg.get("ug_cod"), reg.get("ug"),
             reg.get("fonte_rec"), reg["previsao_inicial"], reg["previsao_atualizada"], reg["a_realizar"],
             reg["realizada"], chave))
        n += 1
        anos.add(reg["ano"])
    con.commit()
    con.close()
    return {"n": n, "anos": sorted(a for a in anos if a)}
