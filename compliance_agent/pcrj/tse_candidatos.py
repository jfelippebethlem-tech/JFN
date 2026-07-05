# -*- coding: utf-8 -*-
"""Cruza os servidores da Câmara/Prefeitura com CANDIDATURAS eleitorais (TSE dados abertos).

ESCOPO (decisão do dono): SOMENTE o **estado do Rio de Janeiro e seus 92 municípios** —
nunca outros estados. Por isso usamos exclusivamente o CSV do estado (`*_RJ.csv`), jamais
o `*_BRASIL.csv`, e ainda filtramos `SG_UF == 'RJ'` por segurança. O arquivo do RJ traz
TODOS os candidatos em qualquer MUNICÍPIO fluminense — cobrindo o caso "foi candidato em
OUTRA cidade" (Niterói, Belford Roxo, São Gonçalo...) dentro do RJ. O CPF vem mascarado
nos dados abertos → o casamento é por NOME normalizado (indício, não prova).

Colunas mapeadas por CABEÇALHO (não posição): o layout do TSE MUDA entre anos
(2016 usa códigos numéricos onde 2024 traz descrições) — mapear por nome é robusto.
Capturamos, além do município/cargo/partido: SG_UF_NASCIMENTO (naturalidade — "de onde a
pessoa é", preenchido ~99% mesmo em 2024; título/CPF vêm redigidos por LGPD) e
DS_SIT_TOT_TURNO (resultado: ELEITO/SUPLENTE/NÃO ELEITO → sinal forte "eleito em outra cidade").

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
from compliance_agent.pcrj.origem import uf_do_titulo

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_{ano}.zip"
# Municipais (NM_UE = município → habilita "outra cidade") + gerais (candidatura em si).
ANOS_PADRAO = [2024, 2020, 2016, 2022, 2018]
_RIO = "RIO DE JANEIRO"

# valores "vazios/redigidos" do TSE que não devem virar dado
_NULOS = {"", "#NULO", "#NE", "-1", "-3", "-4", "NÃO DIVULGÁVEL", "NAO DIVULGAVEL",
          "NÃO INFORMADO", "#NULO#"}


def _limpo(v: str) -> str:
    v = (v or "").strip()
    return "" if v.upper() in _NULOS else v


def _idx(header: list[str]) -> dict:
    """Mapa nome-da-coluna → índice (robusto entre anos)."""
    return {c.strip().upper(): i for i, c in enumerate(header)}


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
            header = next(leitor, None)
            if not header:
                return 0
            ix = _idx(header)
            c_uf = ix.get("SG_UF")
            c_nome = ix.get("NM_CANDIDATO")
            c_munic = ix.get("NM_UE")
            if c_uf is None or c_nome is None or c_munic is None:
                print(f"  [{ano}] cabeçalho inesperado — pulando", flush=True)
                return 0
            c_urna = ix.get("NM_URNA_CANDIDATO", ix.get("NM_URNA"))
            c_cargo = ix.get("DS_CARGO")
            c_part = ix.get("SG_PARTIDO")
            c_sit = ix.get("DS_SITUACAO_CANDIDATURA", ix.get("DS_SITUACAO"))
            c_nasc = ix.get("SG_UF_NASCIMENTO")
            c_munnasc = ix.get("NM_MUNICIPIO_NASCIMENTO")   # existe em anos antigos (2016)
            c_titulo = ix.get("NR_TITULO_ELEITORAL_CANDIDATO")  # anos que não redigem
            c_res = ix.get("DS_SIT_TOT_TURNO")
            c_anoele = ix.get("ANO_ELEICAO")

            def cell(row, i):
                return row[i] if (i is not None and i < len(row)) else ""

            for row in leitor:
                if len(row) <= c_munic or len(row) <= c_nome or len(row) <= c_uf:
                    continue
                if (row[c_uf] or "").strip().upper() != "RJ":
                    continue                    # fronteira RJ-only (defensivo; o arquivo já é do RJ)
                nn = normalizar(row[c_nome])
                if nn not in alvos:
                    continue
                munic = (cell(row, c_munic) or "").strip().upper()
                resultado = _limpo(cell(row, c_res))
                ru = resultado.upper()
                eleito = 1 if ("ELEIT" in ru and "NÃO" not in ru and "NAO" not in ru) else 0
                try:
                    ano_ele = int(cell(row, c_anoele) or ano)
                except ValueError:
                    ano_ele = ano
                uf_alist = uf_do_titulo(cell(row, c_titulo))
                con.execute(
                    """INSERT OR IGNORE INTO tse_candidatura
                       (nome_norm,nome_tse,nome_urna,ano,cargo,municipio,uf,partido,
                        situacao,outra_cidade,uf_nascimento,resultado,eleito,
                        municipio_nascimento,uf_alistamento,coletado_em)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (nn, cell(row, c_nome).strip(), cell(row, c_urna).strip(),
                     ano_ele, cell(row, c_cargo).strip(), munic, cell(row, c_uf).strip(),
                     cell(row, c_part).strip(), _limpo(cell(row, c_sit)),
                     1 if munic and munic != _RIO else 0,
                     _limpo(cell(row, c_nasc)), resultado, eleito,
                     _limpo(cell(row, c_munnasc)), uf_alist, agora))
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
        eleitos_fora = con.execute(
            "SELECT COUNT(DISTINCT nome_norm) n FROM tse_candidatura "
            "WHERE outra_cidade=1 AND eleito=1").fetchone()["n"]
    finally:
        con.close()
    return {"servidores_alvo": len(alvos), "candidaturas": total,
            "pessoas_candidatas": distintos, "candidatas_outra_cidade": outra,
            "eleitas_outra_cidade": eleitos_fora}


if __name__ == "__main__":
    print(coletar())
