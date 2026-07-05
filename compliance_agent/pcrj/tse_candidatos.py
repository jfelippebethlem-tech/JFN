# -*- coding: utf-8 -*-
"""Cruza os servidores da Câmara/Prefeitura com CANDIDATURAS eleitorais (TSE dados abertos).

ESCOPO (decisão do dono): SOMENTE o **estado do Rio de Janeiro e seus 92 municípios** —
nunca outros estados. Por isso usamos exclusivamente o CSV do estado (`*_RJ.csv`), jamais
o `*_BRASIL.csv`, e ainda filtramos `SG_UF == 'RJ'` por segurança. O arquivo do RJ traz
TODOS os candidatos em qualquer MUNICÍPIO fluminense — cobrindo o caso "foi candidato em
OUTRA cidade" (Niterói, Belford Roxo, São Gonçalo...) dentro do RJ. O CPF vem mascarado
nos dados abertos → o casamento é por NOME normalizado (indício, não prova).

Colunas (posicionais no CSV latin-1 ';'): 2 ANO · 10 SG_UF · 12 NM_UE(município) ·
14 DS_CARGO · 17 NM_CANDIDATO · 18 NM_URNA · 23 DS_SITUACAO · 26 SG_PARTIDO.

Flag `outra_cidade` = município da candidatura ≠ RIO DE JANEIRO.
"""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timezone

import requests
import urllib3

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj.nomes import normalizar

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_{ano}.zip"
# Municipais (NM_UE = município → habilita "outra cidade") + gerais (candidatura em si).
ANOS_PADRAO = [2024, 2020, 2016, 2022, 2018]
_C = {"ano": 2, "uf": 10, "munic": 12, "cargo": 14, "nome": 17,
      "urna": 18, "situacao": 23, "partido": 26}
_RIO = "RIO DE JANEIRO"


def _nomes_servidores(con) -> set[str]:
    """Conjunto de nomes normalizados dos servidores da Câmara (universo dos 'nomeados')."""
    return {r[0] for r in con.execute(
        "SELECT DISTINCT nome_norm FROM pcrj_camara_servidores WHERE nome_norm<>''")}


def _processar_ano(ano: int, alvos: set[str], con, uf_arquivo: str = "RJ") -> int:
    """Baixa o zip do ano, streama o CSV do estado, filtra pelos nomes-alvo e grava. Retorna nº."""
    try:
        r = requests.get(_URL.format(ano=ano), verify=False, timeout=300)
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"  [{ano}] ERRO download: {exc}", flush=True)
        return 0
    n = 0
    agora = datetime.now(timezone.utc).isoformat()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        suf = f"_{uf_arquivo}.csv".lower()
        alvo_csv = next((nm for nm in z.namelist() if nm.lower().endswith(suf)), None)
        if not alvo_csv:
            print(f"  [{ano}] sem CSV _{uf_arquivo}", flush=True)
            return 0
        with z.open(alvo_csv) as fh:
            texto = io.TextIOWrapper(fh, encoding="latin-1", newline="")
            leitor = csv.reader(texto, delimiter=";")
            next(leitor, None)  # header
            for row in leitor:
                if len(row) <= _C["partido"]:
                    continue
                if (row[_C["uf"]] or "").strip().upper() != "RJ":
                    continue                    # fronteira RJ-only (defensivo; o arquivo já é do RJ)
                nn = normalizar(row[_C["nome"]])
                if nn not in alvos:
                    continue
                munic = (row[_C["munic"]] or "").strip().upper()
                con.execute(
                    """INSERT OR IGNORE INTO tse_candidatura
                       (nome_norm,nome_tse,nome_urna,ano,cargo,municipio,uf,partido,
                        situacao,outra_cidade,coletado_em)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (nn, row[_C["nome"]].strip(), row[_C["urna"]].strip(),
                     int(row[_C["ano"]] or ano), row[_C["cargo"]].strip(), munic,
                     row[_C["uf"]].strip(), row[_C["partido"]].strip(),
                     row[_C["situacao"]].strip(), 1 if munic and munic != _RIO else 0, agora))
                n += 1
    con.commit()
    return n


def coletar(anos: list[int] | None = None, db_path=None) -> dict:
    _db.inicializar(db_path)
    con = _db.conectar(db_path)
    alvos = _nomes_servidores(con)
    total = 0
    try:
        for ano in (anos or ANOS_PADRAO):
            k = _processar_ano(ano, alvos, con)
            total += k
            print(f"  [{ano}] {k} candidaturas casadas", flush=True)
        distintos = con.execute(
            "SELECT COUNT(DISTINCT nome_norm) n FROM tse_candidatura").fetchone()["n"]
        outra = con.execute(
            "SELECT COUNT(DISTINCT nome_norm) n FROM tse_candidatura WHERE outra_cidade=1").fetchone()["n"]
    finally:
        con.close()
    return {"servidores_alvo": len(alvos), "candidaturas": total,
            "pessoas_candidatas": distintos, "candidatas_outra_cidade": outra}


if __name__ == "__main__":
    print(coletar())
