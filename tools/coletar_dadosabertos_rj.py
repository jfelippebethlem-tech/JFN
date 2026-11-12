#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coletor do Portal de Dados Abertos do RJ (CKAN dadosabertos.rj.gov.br): TFE Despesa e TFE Receita.

O portal publica o TFE (Transparência Fiscal, espelho do SIAFE-Rio) em CSV e — ao contrário de
tfe.fazenda.rj.gov.br — responde a IP de datacenter. É AGREGADO: posição acumulada do exercício por
UO/UG/fonte/função/programa/elemento (despesa) e por rubrica/UG/fonte (receita). NÃO tem OB nem
favorecido: serve para orçamento por órgão (dotação, empenhado, liquidado, pago, RP), nunca para
"quanto foi pago a quem" — isso segue no SIAFE (ob_orcamentaria_siafe).

Grava em base PRÓPRIA (data/dadosabertos_rj.db) para não disputar escrita com o compliance.db.
Idempotente: cada recurso é regravado inteiro (DELETE por recurso + INSERT) só se o sha256 mudou.

    python tools/coletar_dadosabertos_rj.py [--forcar]
"""
import argparse
import csv
import hashlib
import io
import json
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

import httpx

API = "https://dadosabertos.rj.gov.br/api/3/action/package_show?id="
PACOTES = {"tfe-despesa": "da_despesa", "tfe-receita": "da_receita"}
DB = Path(__file__).resolve().parents[1] / "data" / "dadosabertos_rj.db"
UA = {"User-Agent": "jfn-coletor-dados-abertos/1.0"}


def coluna(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def numero(v: str):
    v = (v or "").strip()
    if not v:
        return None
    if "," in v:
        v = v.replace(".", "").replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def ler_csv(raw: bytes) -> tuple[str, list[str], list[list[str]]]:
    """Pula o preâmbulo (5 linhas: governo/secretaria/…/período) e devolve (período, cabeçalho, linhas).
    Há campos entre aspas com quebra de linha dentro — por isso csv.reader, nunca split por linha."""
    txt = raw.decode("latin1")
    partes = txt.split("\n", 5)
    if len(partes) < 6:
        raise ValueError("CSV sem preâmbulo esperado")
    periodo = partes[4].strip()
    linhas = list(csv.reader(io.StringIO(partes[5]), delimiter=";"))
    cab = linhas[0]
    corpo = [ln for ln in linhas[1:] if len(ln) == len(cab)]
    descartadas = len(linhas) - 1 - len(corpo)
    if descartadas:
        print(f"    aviso: {descartadas} linha(s) com nº de colunas diferente do cabeçalho descartadas")
    return periodo, cab, corpo


def garantir(c, tabela: str, cab: list[str]):
    cols = [coluna(h) for h in cab]
    defs = ", ".join(f'"{x}" {"REAL" if x.startswith("valor") else "TEXT"}' for x in cols)
    c.execute(f'CREATE TABLE IF NOT EXISTS {tabela} (recurso_id TEXT, arquivo TEXT, {defs})')
    existentes = {r[1] for r in c.execute(f"PRAGMA table_info({tabela})")}
    for x in cols:
        if x not in existentes:
            c.execute(f'ALTER TABLE {tabela} ADD COLUMN "{x}" {"REAL" if x.startswith("valor") else "TEXT"}')
    c.execute(f"CREATE INDEX IF NOT EXISTS ix_{tabela}_ug ON {tabela}(ug, posicao)")
    return cols


def rodar(forcar: bool = False) -> dict:
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB, timeout=120)
    c.execute("""CREATE TABLE IF NOT EXISTS da_recurso (recurso_id TEXT PRIMARY KEY, pacote TEXT, arquivo TEXT,
        url TEXT, periodo TEXT, sha256 TEXT, linhas INTEGER, modificado_portal TEXT, coletado_em TEXT)""")
    res = {"baixados": 0, "inalterados": 0, "linhas": 0, "erros": []}
    with httpx.Client(timeout=300, headers=UA, follow_redirects=True) as h:
        for pacote, tabela in PACOTES.items():
            meta = h.get(API + pacote).json()["result"]
            for r in meta["resources"]:
                rid, nome, url = r["id"], r.get("name") or "", r["url"]
                try:
                    raw = h.get(url).content
                    sha = hashlib.sha256(raw).hexdigest()
                    ant = c.execute("SELECT sha256 FROM da_recurso WHERE recurso_id=?", (rid,)).fetchone()
                    if ant and ant[0] == sha and not forcar:
                        res["inalterados"] += 1
                        continue
                    # O portal publica 2019 e 2021 DUAS vezes (recursos distintos, bytes idênticos): carregar os
                    # dois dobrava esses exercícios em qualquer soma. Cópia byte a byte de outro recurso = 0 linhas.
                    copia = c.execute("SELECT recurso_id FROM da_recurso WHERE sha256=? AND recurso_id<>? AND linhas>0",
                                      (sha, rid)).fetchone()
                    if copia:
                        c.execute(f"DELETE FROM {tabela} WHERE recurso_id=?", (rid,))
                        c.execute("INSERT OR REPLACE INTO da_recurso VALUES (?,?,?,?,?,?,?,?,?)",
                                  (rid, pacote, nome, url, f"cópia de {copia[0]}", sha, 0,
                                   r.get("last_modified") or r.get("created"), time.strftime("%Y-%m-%d %H:%M:%S")))
                        c.commit()
                        print(f"  {pacote}/{nome}: cópia idêntica de {copia[0][:8]} — ignorada")
                        continue
                    periodo, cab, corpo = ler_csv(raw)
                    cols = garantir(c, tabela, cab)
                    val = [i for i, x in enumerate(cols) if x.startswith("valor")]
                    lote = [[rid, nome] + [numero(v) if i in val else v.strip() for i, v in enumerate(ln)]
                            for ln in corpo]
                    ph = ", ".join("?" * (len(cols) + 2))
                    nomes = ", ".join(["recurso_id", "arquivo"] + [f'"{x}"' for x in cols])
                    c.execute(f"DELETE FROM {tabela} WHERE recurso_id=?", (rid,))
                    c.executemany(f"INSERT INTO {tabela} ({nomes}) VALUES ({ph})", lote)
                    c.execute("INSERT OR REPLACE INTO da_recurso VALUES (?,?,?,?,?,?,?,?,?)",
                              (rid, pacote, nome, url, periodo, sha, len(lote),
                               r.get("last_modified") or r.get("created"), time.strftime("%Y-%m-%d %H:%M:%S")))
                    c.commit()
                    res["baixados"] += 1
                    res["linhas"] += len(lote)
                    print(f"  {pacote}/{nome}: {len(lote)} linhas · {periodo}")
                except Exception as e:  # noqa: BLE001 — um recurso ruim não derruba os outros; fica no relatório
                    c.rollback()
                    res["erros"].append(f"{pacote}/{nome}: {type(e).__name__}: {e}")
                    print(f"  ERRO {pacote}/{nome}: {e}")
    criar_visoes(c)
    c.close()
    return res


# Modalidades intraorçamentárias (o Estado pagando a si mesmo: contribuição patronal ao Rioprevidência etc.).
# Somadas com o resto, contam o mesmo real duas vezes — as trajetórias CONSOLIDADAS as excluem.
_INTRA_DESP = "('91','93','94','95','96')"

VISOES = f"""
DROP VIEW IF EXISTS v_receita;
-- RECEITA, 2024 em diante: o CSV do portal REPETE a mesma linha sob as fontes x00 (500/600/700/800 — ICMS de
-- R$ 48,07 bi aparece 4× rotulado como "SUS", "RPPS"…), defeito do arquivo, não dado. Medido em 12/11/2026:
-- 3.351 linhas / R$ 327 bi → 989 distintas / R$ 106 bi. Dedup pelo sufixo da fonte + natureza + UG + valores.
-- Consequência: em 2024+ o GRUPO da fonte (1º dígito) da receita NÃO é confiável; o total e a natureza são.
CREATE VIEW v_receita AS
SELECT CAST(substr(posicao,4) AS INT) ano, posicao, categoria_economica, nome_categoria_economica,
       receita_por_fonte origem, nome_receita_por_fonte nome_origem, rubrica, nome_rubrica, sub_alinea,
       nome_sub_alinea, orgao, nome_orgao, ug, nome_ug, fonte_de_recursos fonte,
       valor_previsao_inicial previsao_inicial, valor_previsao_atualizada previsao_atualizada,
       valor_receita_realizada realizada
FROM da_receita WHERE CAST(substr(posicao,4) AS INT) < 2024
UNION ALL
SELECT CAST(substr(posicao,4) AS INT), posicao, categoria_economica, nome_categoria_economica,
       receita_por_fonte, nome_receita_por_fonte, rubrica, nome_rubrica, sub_alinea, nome_sub_alinea,
       orgao, nome_orgao, ug, nome_ug, 'x' || substr(fonte_de_recursos,2),
       MAX(valor_previsao_inicial), MAX(valor_previsao_atualizada), MAX(valor_receita_realizada)
FROM da_receita WHERE CAST(substr(posicao,4) AS INT) >= 2024
GROUP BY posicao, sub_alinea, ug, substr(fonte_de_recursos,2), valor_receita_realizada, valor_previsao_inicial;

DROP VIEW IF EXISTS v_traj_receita_ano;
CREATE VIEW v_traj_receita_ano AS
SELECT ano, MAX(posicao) posicao,
  SUM(CASE WHEN categoria_economica NOT IN ('7','8') THEN previsao_inicial END) previsao_inicial,
  SUM(CASE WHEN categoria_economica NOT IN ('7','8') THEN previsao_atualizada END) previsao_atualizada,
  SUM(CASE WHEN categoria_economica NOT IN ('7','8') THEN realizada END) realizada_liquida,
  SUM(CASE WHEN categoria_economica = '9' THEN realizada END) deducoes,
  SUM(CASE WHEN categoria_economica IN ('1','2') THEN realizada END) realizada_bruta,
  SUM(CASE WHEN categoria_economica IN ('7','8') THEN realizada END) intraorcamentaria
FROM v_receita GROUP BY ano;

DROP VIEW IF EXISTS v_traj_receita_origem;
CREATE VIEW v_traj_receita_origem AS
SELECT ano, origem, nome_origem, SUM(realizada) realizada FROM v_receita
WHERE categoria_economica IN ('1','2') GROUP BY ano, origem;

DROP VIEW IF EXISTS v_traj_despesa_ano;
CREATE VIEW v_traj_despesa_ano AS
SELECT CAST(substr(posicao,4) AS INT) ano, MAX(posicao) posicao,
  SUM(valor_dotacao_inicial) dotacao_inicial, SUM(valor_dotado_atual) dotacao_atual,
  SUM(valor_empenhado) empenhado, SUM(valor_liquidado) liquidado, SUM(valor_pago) pago,
  SUM(valor_rp_pago) rp_pago, SUM(valor_total_desembolsado) desembolsado, SUM(valor_rp_a_pagar) rp_a_pagar,
  SUM(CASE WHEN modalidade_aplicacao IN {_INTRA_DESP} THEN valor_empenhado END) empenhado_intra,
  SUM(CASE WHEN modalidade_aplicacao NOT IN {_INTRA_DESP} THEN valor_empenhado END) empenhado_consolidado,
  SUM(CASE WHEN modalidade_aplicacao NOT IN {_INTRA_DESP} THEN valor_pago END) pago_consolidado
FROM da_despesa GROUP BY 1;

DROP VIEW IF EXISTS v_traj_despesa_funcao;
CREATE VIEW v_traj_despesa_funcao AS
SELECT CAST(substr(posicao,4) AS INT) ano, funcao, nome_funcao, SUM(valor_dotacao_inicial) dotacao_inicial,
  SUM(valor_empenhado) empenhado, SUM(valor_pago) pago
FROM da_despesa WHERE modalidade_aplicacao NOT IN {_INTRA_DESP} GROUP BY 1, funcao;

DROP VIEW IF EXISTS v_traj_despesa_orgao;
CREATE VIEW v_traj_despesa_orgao AS
SELECT CAST(substr(posicao,4) AS INT) ano, orgao, MAX(nome_orgao) nome_orgao, SUM(valor_dotacao_inicial) dotacao_inicial,
  SUM(valor_empenhado) empenhado, SUM(valor_pago) pago
FROM da_despesa WHERE modalidade_aplicacao NOT IN {_INTRA_DESP} GROUP BY 1, orgao;

DROP VIEW IF EXISTS v_traj_despesa_grupo;
-- 2016: aposentadorias (elemento 01, R$ 10,80 bi) e pensões (03, R$ 3,28 bi) vieram no grupo 3; de 2017 em diante
-- no grupo 1. Sem normalizar, "pessoal" cresce +105% real 2016→2024 por reclassificação. Elementos 01/03 → grupo 1.
CREATE VIEW v_traj_despesa_grupo AS
SELECT CAST(substr(posicao,4) AS INT) ano,
  CASE WHEN substr(elemento_de_despesa,5,2) IN ('01','03') THEN '1' ELSE grupo END grupo,
  MAX(nome_grupo) nome_grupo, SUM(valor_empenhado) empenhado, SUM(valor_pago) pago
FROM da_despesa WHERE modalidade_aplicacao NOT IN {_INTRA_DESP}
GROUP BY 1, CASE WHEN substr(elemento_de_despesa,5,2) IN ('01','03') THEN '1' ELSE grupo END;
"""


def criar_visoes(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='da_receita'").fetchone() or \
       not c.execute("SELECT 1 FROM sqlite_master WHERE name='da_despesa'").fetchone():
        return
    c.executescript(VISOES)
    c.commit()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--forcar", action="store_true", help="regrava mesmo com sha igual")
    out = rodar(ap.parse_args().forcar)
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(1 if out["erros"] else 0)
