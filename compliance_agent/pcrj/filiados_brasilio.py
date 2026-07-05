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


if __name__ == "__main__":
    import json
    print(json.dumps(coletar(), ensure_ascii=False, indent=1))
