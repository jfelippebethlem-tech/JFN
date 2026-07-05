# -*- coding: utf-8 -*-
"""Ingere FILIADOS partidários (Brasil.IO) casados com servidores/candidatos do RJ.

Filiação dá a CIDADE DE ORIGEM (domicílio eleitoral) mesmo de quem NUNCA foi candidato —
amplia a cobertura do detector de fantasma além do TSE consulta_cand.

Fonte: Brasil.IO dataset ``eleicoes-brasil`` tabela ``filiados`` (nominal: nome, município,
partido, título, data). API v1 exige TOKEN (grátis, em brasil.io/auth/tokens-api/) — desde
2020. Guardar em ``BRASILIO_API_TOKEN`` no .env (nunca em código/git). O dado do Brasil.IO é
de 2018, mas domicílio eleitoral é estável → serve como sinal de ORIGEM (indício, não prova).

Estratégia VM-safe: filtra a API por UF=RJ e pagina; casa por NOME normalizado contra o
universo de alvos (servidores da Câmara + nomes já vistos). Throttle entre páginas.

CLI: PYTHONPATH=. .venv/bin/python -m compliance_agent.pcrj.filiados_brasilio
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import requests

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj.nomes import normalizar

_API = "https://api.brasil.io/v1/dataset/eleicoes-brasil/filiados/data/"
# nomes possíveis das colunas (o schema do Brasil.IO usa nomes longos)
_C_NOME = ("nome_do_filiado", "nome", "nome_filiado")
_C_MUNIC = ("nome_do_municipio", "municipio", "nome_municipio")
_C_PART = ("nome_do_partido", "sigla_do_partido", "partido", "sigla_partido")
_C_TITULO = ("numero_da_inscricao", "titulo_eleitoral", "titulo")
_C_DATA = ("data_filiacao", "data_da_filiacao")
_C_SIT = ("situacao_do_registro", "situacao")


def _token() -> str:
    from compliance_agent.envfile import carregar_env
    carregar_env()
    return (os.environ.get("BRASILIO_API_TOKEN") or "").strip()


def _pick(d: dict, chaves: tuple) -> str:
    for k in chaves:
        if d.get(k):
            return str(d[k]).strip()
    return ""


def _alvos(con) -> set[str]:
    """Universo de nomes normalizados a casar (servidores Câmara + candidatos já vistos)."""
    alvos = {r[0] for r in con.execute(
        "SELECT DISTINCT nome_norm FROM pcrj_camara_servidores WHERE nome_norm<>''")}
    for tab in ("tse_candidatura", "pcrj_comissionado_candidato", "pcrj_prefeitura_consulta"):
        try:
            alvos |= {r[0] for r in con.execute(
                f"SELECT DISTINCT nome_norm FROM {tab} WHERE nome_norm<>''")}
        except Exception:
            pass
    return alvos


def coletar(uf: str = "RJ", pausa: float = 0.5, db_path=None, max_paginas: int = 100000) -> dict:
    tok = _token()
    if not tok:
        return {"erro": "BRASILIO_API_TOKEN ausente no .env (gere em brasil.io/auth/tokens-api/)"}
    _db.inicializar(db_path)
    con = _db.conectar(db_path)
    alvos = _alvos(con)
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Token {tok}",
                         "User-Agent": "JFN-Compliance/1.0"})
    agora = datetime.now(timezone.utc).isoformat()
    url = _API
    params = {"uf": uf}
    n_lidos = n_casados = pag = 0
    try:
        while url and pag < max_paginas:
            r = sess.get(url, params=params if pag == 0 else None, timeout=120)
            if r.status_code == 401:
                return {"erro": "token inválido/expirado (401)"}
            if r.status_code == 429:          # rate limit — espera e tenta de novo
                time.sleep(5)
                continue
            r.raise_for_status()
            j = r.json()
            for row in j.get("results", []):
                n_lidos += 1
                nn = normalizar(_pick(row, _C_NOME))
                if not nn or nn not in alvos:
                    continue
                con.execute(
                    """INSERT OR REPLACE INTO pcrj_filiado
                       (nome_norm,nome,municipio,uf,partido,titulo,data_filiacao,
                        situacao,fonte,coletado_em)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (nn, _pick(row, _C_NOME), _pick(row, _C_MUNIC).upper(), uf,
                     _pick(row, _C_PART), _pick(row, _C_TITULO), _pick(row, _C_DATA),
                     _pick(row, _C_SIT), "brasilio", agora))
                n_casados += 1
            con.commit()
            url = j.get("next")
            pag += 1
            if pag % 20 == 0:
                print(f"  página {pag}: {n_lidos} lidos, {n_casados} casados", flush=True)
            time.sleep(pausa)
    finally:
        con.close()
    return {"paginas": pag, "lidos": n_lidos, "casados": n_casados}


def coletar_arquivo(caminho: str, uf: str = "RJ", db_path=None) -> dict:
    """Ingere de um ARQUIVO LOCAL (CSV ou CSV.gz) baixado do Brasil.IO — sem API/token.
    Use quando o dono baixar 'BAIXAR DADOS COMPLETOS EM CSV' (via login Google do próprio dono).
    Streama linha a linha (arquivo é grande), filtra UF=RJ e casa por nome com os alvos."""
    import csv
    import gzip
    import io as _io
    from pathlib import Path
    p = Path(caminho)
    if not p.exists():
        return {"erro": f"arquivo não encontrado: {caminho}"}
    _db.inicializar(db_path)
    con = _db.conectar(db_path)
    alvos = _alvos(con)
    agora = datetime.now(timezone.utc).isoformat()

    def _abrir():
        raw = gzip.open(p, "rb") if p.suffix == ".gz" else open(p, "rb")
        return _io.TextIOWrapper(raw, encoding="utf-8", newline="")

    n_lidos = n_casados = 0
    try:
        fh = _abrir()
        # detecta delimitador (Brasil.IO usa ',' por padrão)
        amostra = fh.read(4096); fh.seek(0)
        delim = ";" if amostra.count(";") > amostra.count(",") else ","
        leitor = csv.DictReader(fh, delimiter=delim)
        cols = {c.lower(): c for c in (leitor.fieldnames or [])}

        def col(chaves):
            for k in chaves:
                if k in cols:
                    return cols[k]
            return None
        c_nome = col(_C_NOME); c_mun = col(_C_MUNIC); c_part = col(_C_PART)
        c_tit = col(_C_TITULO); c_data = col(_C_DATA); c_sit = col(_C_SIT)
        c_uf = col(("uf", "sigla_uf"))
        if not c_nome:
            return {"erro": f"coluna de nome não encontrada; colunas={leitor.fieldnames}"}
        for row in leitor:
            n_lidos += 1
            if c_uf and (row.get(c_uf) or "").strip().upper() not in (uf, ""):
                continue
            nn = normalizar(row.get(c_nome, ""))
            if not nn or nn not in alvos:
                continue
            con.execute(
                """INSERT OR REPLACE INTO pcrj_filiado
                   (nome_norm,nome,municipio,uf,partido,titulo,data_filiacao,
                    situacao,fonte,coletado_em) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (nn, (row.get(c_nome) or "").strip(),
                 (row.get(c_mun) or "").strip().upper() if c_mun else "", uf,
                 (row.get(c_part) or "").strip() if c_part else "",
                 (row.get(c_tit) or "").strip() if c_tit else "",
                 (row.get(c_data) or "").strip() if c_data else "",
                 (row.get(c_sit) or "").strip() if c_sit else "",
                 "brasilio-arquivo", agora))
            n_casados += 1
            if n_lidos % 500000 == 0:
                con.commit()
                print(f"  {n_lidos} linhas lidas, {n_casados} casados", flush=True)
        con.commit()
    finally:
        con.close()
    return {"arquivo": str(p), "lidos": n_lidos, "casados": n_casados}


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 1:                 # caminho de arquivo local
        print(json.dumps(coletar_arquivo(sys.argv[1]), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(coletar(), ensure_ascii=False, indent=1))
