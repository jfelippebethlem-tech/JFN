# -*- coding: utf-8 -*-
"""Cadastro COMPLETO de servidores da Prefeitura do Rio (folha mensal, em bloco).

Fonte pública em bloco (descoberta 2026-07): o portal de remuneração
(jeap.rio.rj.gov.br/contrachequeapi) expõe um repositório de CSVs mensais:
    https://contrachequedoc.rio.gov.br/repositorio/ArquivoTC{AAAAMM}.csv
Cada arquivo (~22MB, latin-1, ';') traz TODA a folha da competência:
    NOME · MATRICULA · SIGLA_UA (unidade/órgão) · TIPO_FOLHA · remunerações.
São ~214 mil linhas/mês (efetivos, comissionados, cedidos e aposentados/pensionistas
via FUNPREVI). É o cadastro que faltava para cruzar a Prefeitura inteira por órgão —
substitui a consulta nome a nome (contrachequeapi), que só paginava 10.

Grava em tabela dedicada ``pcrj_folha_pref`` no mesmo banco do PCRJ. Idempotente por
competência (limpa e regrava a competência). VM-safe: stream do CSV, sem carregar tudo em RAM.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

import httpx

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj.nomes import normalizar
from compliance_agent.pcrj.orgaos_siglas import decodificar

_URL = "https://contrachequedoc.rio.gov.br/repositorio/ArquivoTC{ym}.csv"
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0 Safari/537.36")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pcrj_folha_pref (
    nome_norm   TEXT NOT NULL,
    nome        TEXT,
    matricula   TEXT,
    sigla_ua    TEXT,           -- código da unidade administrativa (órgão) na folha
    orgao       TEXT,           -- SIGLA_UA decodificada p/ nome legível
    tipo_folha  TEXT,           -- NORMAL / PREVNORMAL (aposent./pens.) / TSVE / ...
    remun_bruta TEXT,
    competencia TEXT NOT NULL,  -- AAAAMM
    coletado_em TEXT,
    PRIMARY KEY (matricula, sigla_ua, competencia)
);
CREATE INDEX IF NOT EXISTS ix_folha_nome ON pcrj_folha_pref(nome_norm);
CREATE INDEX IF NOT EXISTS ix_folha_comp ON pcrj_folha_pref(competencia);
"""

# TIPO_FOLHA que indica APOSENTADO/PENSIONISTA (não é nomeação ativa) — útil p/ separar no cruzamento.
_INATIVO = ("PREV", "APA", "PENSAO", "PENSÃO", "APOSENT")


def eh_ativo(tipo_folha: str | None) -> bool:
    t = (tipo_folha or "").upper()
    return not any(k in t for k in _INATIVO)


def coletar(ym: str = "202605") -> dict:
    _db.inicializar()
    con = _db.conectar()
    con.execute("PRAGMA busy_timeout=180000")  # cede ao cron mensal que também escreve no pcrj.db
    con.executescript(_SCHEMA)
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")

    url = _URL.format(ym=ym)
    print(f"[folha] baixando {url}", flush=True)
    linhas = 0
    con.execute("DELETE FROM pcrj_folha_pref WHERE competencia=?", (ym,))
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=180,
                          headers={"User-Agent": _UA}, verify=False) as r:
            r.raise_for_status()
            buf = io.StringIO()
            # decodifica em streaming (latin-1), acumula em memória modesta e parseia
            for chunk in r.iter_bytes(1 << 20):
                buf.write(chunk.decode("latin-1", "replace"))
            buf.seek(0)
            rd = csv.reader(buf, delimiter=";")
            header = next(rd, None)
            if not header:
                con.close()
                return {"competencia": ym, "erro": "csv vazio"}
            lote = []
            for row in rd:
                if len(row) < 4:
                    continue
                nome = (row[0] or "").strip()
                sigla = (row[2] or "").strip()
                lote.append((normalizar(nome), nome, (row[1] or "").strip(), sigla,
                             decodificar(sigla), (row[3] or "").strip(),
                             (row[4] or "").strip() if len(row) > 4 else "", ym, agora))
                if len(lote) >= 5000:
                    con.executemany(
                        "INSERT OR IGNORE INTO pcrj_folha_pref (nome_norm,nome,matricula,sigla_ua,"
                        "orgao,tipo_folha,remun_bruta,competencia,coletado_em) VALUES (?,?,?,?,?,?,?,?,?)",
                        lote)
                    linhas += len(lote); lote = []
            if lote:
                con.executemany(
                    "INSERT OR IGNORE INTO pcrj_folha_pref (nome_norm,nome,matricula,sigla_ua,"
                    "orgao,tipo_folha,remun_bruta,competencia,coletado_em) VALUES (?,?,?,?,?,?,?,?,?)",
                    lote)
                linhas += len(lote)
        con.commit()
    except Exception as e:  # noqa: BLE001
        con.close()
        print(f"[folha] {ym} FALHOU: {e}", flush=True)
        return {"competencia": ym, "erro": str(e)}
    n_org = con.execute("SELECT COUNT(DISTINCT orgao) FROM pcrj_folha_pref WHERE competencia=?",
                        (ym,)).fetchone()[0]
    con.close()
    print(f"[folha] {ym}: {linhas} servidores, {n_org} órgãos distintos", flush=True)
    return {"competencia": ym, "servidores": linhas, "orgaos": n_org}


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(coletar(sys.argv[1] if len(sys.argv) > 1 else "202605"), ensure_ascii=False))
