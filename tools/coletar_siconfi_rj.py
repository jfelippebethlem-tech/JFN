#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coletor SICONFI (Tesouro Nacional) do Estado do RJ — RGF por Poder, RREO e extrato de entregas.

Para a Comissão de Orçamento da ALERJ (13/11/2026): a LRF por Poder/instituição sai daqui. API pública, gratuita,
sem chave: https://apidatalake.tesouro.gov.br/ords/siconfi/tt/ (testada em 13/11/2026; ver relatório da pesquisa).

  RGF  `co_poder`: E Executivo · L Legislativo (ALERJ e TCE-RJ separados em `instituicao`) · J TJRJ · M MPRJ ·
       D Defensoria. Não existe `co_orgao`. Anexos: 01 pessoal, 02 dívida consolidada, 05 caixa e restos a pagar,
       06 simplificado. Quadrimestral (Q, períodos 1–3).
  RREO só o ente consolidado ("Governo do Estado"). Anexos: 01 balanço orçamentário, 03 RCL, 06 resultados
       primário e nominal. Bimestral (1–6).
  /extrato_entregas — o que cada instituição entregou e quando (semáforo de entregas).

Valores AUTODECLARADOS pelo ente ao SICONFI — a peça diz isso e manda conferir com o RGF publicado.
Grava em data/dadosabertos_rj.db. Período fechado já coletado não é rebaixado; o exercício corrente sempre é.

    python tools/coletar_siconfi_rj.py [--desde 2021] [--forcar]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

BASE = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"
ENTE = 33
DB = Path(__file__).resolve().parents[1] / "data" / "dadosabertos_rj.db"
PODERES = ("E", "L", "J", "M", "D")
ANEXOS_RGF = ("RGF-Anexo 01", "RGF-Anexo 02", "RGF-Anexo 05", "RGF-Anexo 06")
ANEXOS_RREO = ("RREO-Anexo 01", "RREO-Anexo 03", "RREO-Anexo 06")
UA = {"User-Agent": "jfn-coletor-siconfi/1.0"}
_COLS = ("exercicio", "periodo", "periodicidade", "co_poder", "instituicao", "anexo", "rotulo", "coluna",
         "cod_conta", "conta", "valor")

DDL = """
CREATE TABLE IF NOT EXISTS siconfi_rgf (exercicio INT, periodo INT, periodicidade TEXT, co_poder TEXT,
  instituicao TEXT, anexo TEXT, rotulo TEXT, coluna TEXT, cod_conta TEXT, conta TEXT, valor REAL, coletado_em TEXT);
CREATE INDEX IF NOT EXISTS ix_siconfi_rgf ON siconfi_rgf(exercicio, periodo, co_poder, anexo);
CREATE TABLE IF NOT EXISTS siconfi_rreo (exercicio INT, periodo INT, periodicidade TEXT, co_poder TEXT,
  instituicao TEXT, anexo TEXT, rotulo TEXT, coluna TEXT, cod_conta TEXT, conta TEXT, valor REAL, coletado_em TEXT);
CREATE INDEX IF NOT EXISTS ix_siconfi_rreo ON siconfi_rreo(exercicio, periodo, anexo);
CREATE TABLE IF NOT EXISTS siconfi_entregas (exercicio INT, json TEXT, coletado_em TEXT);
CREATE TABLE IF NOT EXISTS siconfi_coleta (relatorio TEXT, exercicio INT, periodo INT, co_poder TEXT, anexo TEXT,
  linhas INT, coletado_em TEXT, PRIMARY KEY (relatorio, exercicio, periodo, co_poder, anexo));
"""


def paginar(h: httpx.Client, endpoint: str, params: dict) -> list[dict]:
    """Todas as páginas (`hasMore`/`offset`). Resposta sem `items` = erro da API (200 com corpo de erro existe)."""
    out, offset = [], 0
    while True:
        r = h.get(f"{BASE}/{endpoint}", params={**params, "offset": offset})
        r.raise_for_status()
        d = r.json()
        if "items" not in d:
            raise ValueError(f"{endpoint}: resposta sem 'items' ({str(d)[:120]})")
        out += d["items"]
        if not d.get("hasMore"):
            return out
        offset += len(d["items"]) or 5000
        time.sleep(0.3)


def _feito(c, rel, ex, per, poder, anexo) -> bool:
    return bool(c.execute("SELECT 1 FROM siconfi_coleta WHERE relatorio=? AND exercicio=? AND periodo=? AND co_poder=? "
                          "AND anexo=? AND linhas>0", (rel, ex, per, poder, anexo)).fetchone())


def gravar(c, tabela: str, rel: str, ex: int, per: int, poder: str, anexo: str, itens: list[dict]) -> None:
    agora = datetime.now().isoformat(timespec="seconds")
    c.execute(f"DELETE FROM {tabela} WHERE exercicio=? AND periodo=? AND co_poder=? AND anexo=?",  # noqa: S608
              (ex, per, poder, anexo))
    c.executemany(f"INSERT INTO {tabela} VALUES ({','.join('?' * (len(_COLS) + 1))})",  # noqa: S608
                  [tuple(i.get(k) if k != "co_poder" else (i.get(k) or poder) for k in _COLS) + (agora,)
                   for i in itens])
    c.execute("INSERT OR REPLACE INTO siconfi_coleta VALUES (?,?,?,?,?,?,?)", (rel, ex, per, poder, anexo, len(itens),
                                                                              agora))
    c.commit()


def rodar(desde: int = 2021, forcar: bool = False) -> dict:
    ano = datetime.now().year
    c = sqlite3.connect(DB, timeout=120)
    c.executescript(DDL)
    res = {"chamadas": 0, "gravados": 0, "vazios": 0, "pulados": 0, "erros": []}
    with httpx.Client(timeout=90, headers=UA) as h:
        for ex in range(desde, ano + 1):
            corrente = ex >= ano - 1          # o ano anterior ainda recebe retificação no início do ano
            for per in (1, 2, 3):
                for poder in PODERES:
                    for anexo in ANEXOS_RGF:
                        if not forcar and not corrente and _feito(c, "RGF", ex, per, poder, anexo):
                            res["pulados"] += 1
                            continue
                        try:
                            itens = paginar(h, "rgf", {"an_exercicio": ex, "in_periodicidade": "Q", "nr_periodo": per,
                                                       "co_tipo_demonstrativo": "RGF", "no_anexo": anexo,
                                                       "co_esfera": "E", "co_poder": poder, "id_ente": ENTE})
                            res["chamadas"] += 1
                            if itens:
                                gravar(c, "siconfi_rgf", "RGF", ex, per, poder, anexo, itens)
                                res["gravados"] += len(itens)
                            else:
                                res["vazios"] += 1
                        except (httpx.HTTPError, ValueError) as e:
                            res["erros"].append(f"RGF {ex}/{per} {poder} {anexo}: {e}"[:200])
                        time.sleep(0.3)
            for per in range(1, 7):
                for anexo in ANEXOS_RREO:
                    if not forcar and not corrente and _feito(c, "RREO", ex, per, "E", anexo):
                        res["pulados"] += 1
                        continue
                    try:
                        itens = paginar(h, "rreo", {"an_exercicio": ex, "nr_periodo": per,
                                                    "co_tipo_demonstrativo": "RREO", "no_anexo": anexo,
                                                    "co_esfera": "E", "id_ente": ENTE})
                        res["chamadas"] += 1
                        if itens:
                            gravar(c, "siconfi_rreo", "RREO", ex, per, "E", anexo, itens)
                            res["gravados"] += len(itens)
                        else:
                            res["vazios"] += 1
                    except (httpx.HTTPError, ValueError) as e:
                        res["erros"].append(f"RREO {ex}/{per} {anexo}: {e}"[:200])
                    time.sleep(0.3)
            try:
                ent = paginar(h, "extrato_entregas", {"id_ente": ENTE, "an_referencia": ex})
                c.execute("DELETE FROM siconfi_entregas WHERE exercicio=?", (ex,))
                c.execute("INSERT INTO siconfi_entregas VALUES (?,?,?)",
                          (ex, json.dumps(ent, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))
                c.commit()
            except (httpx.HTTPError, ValueError) as e:
                res["erros"].append(f"entregas {ex}: {e}"[:200])
    c.close()
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=2021)
    ap.add_argument("--forcar", action="store_true")
    a = ap.parse_args()
    out = rodar(a.desde, a.forcar)
    print(json.dumps({k: (v[:10] if isinstance(v, list) else v) for k, v in out.items()}, ensure_ascii=False))
    sys.exit(1 if out["erros"] and not out["gravados"] else 0)
