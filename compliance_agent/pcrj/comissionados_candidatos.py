# -*- coding: utf-8 -*-
"""Cruzamento INVERSO — comissionados da Prefeitura do Rio (2021+) que já foram CANDIDATOS.

Direção oposta ao ``cruzamento.py``: parte dos CANDIDATOS do TSE (RJ) e verifica quais
ocupam/ocuparam cargo COMISSIONADO na Prefeitura a partir de 2021. Escopo (decisão do dono):
comissionados (cargo em comissão, símbolo ESPECIAL/DAS/DAI), 2021→hoje; **sem aposentados**;
efetivos ficam de fora aqui (servem só ao cruzamento com a Câmara). Universo de candidatos:
município do Rio (mais provável de ser comissionado da Prefeitura) — extensível a todo o RJ.

Sem CPF → match por nome (indício). O município da candidatura = domicílio eleitoral (proxy).
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
import urllib3

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj.nomes import normalizar
from compliance_agent.pcrj.pcrj_remuneracao import Sessao

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_{ano}.zip"
_C = {"ano": 2, "uf": 10, "munic": 12, "cargo": 14, "nome": 17}
ANOS_MUNICIPAIS = [2016, 2020, 2024]
# Comissionado na Prefeitura do Rio: cargo em comissão. 'ESPECIAL' é o rótulo dominante.
_RE_COMISSIONADO = re.compile(r"\bESPECIAL\b|\bDAS\b|\bDAI\b|COMISS|ASSESSOR", re.IGNORECASE)
_ADM_MIN = 2021


def _candidatos(anos: list[int], apenas_municipio: str | None) -> dict[str, dict]:
    """Nomes de candidatos (RJ) → info da candidatura mais recente. Dedup por nome normalizado."""
    cands: dict[str, dict] = {}
    for ano in anos:
        try:
            r = requests.get(_URL.format(ano=ano), verify=False, timeout=300)
            r.raise_for_status()
        except requests.RequestException as exc:
            print(f"  [{ano}] erro download: {exc}", flush=True)
            continue
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            nome_csv = next((n for n in z.namelist() if n.lower().endswith("_rj.csv")), None)
            if not nome_csv:
                continue
            with z.open(nome_csv) as fh:
                leitor = csv.reader(io.TextIOWrapper(fh, encoding="latin-1", newline=""), delimiter=";")
                next(leitor, None)
                for row in leitor:
                    if len(row) <= _C["nome"] or (row[_C["uf"]] or "").strip().upper() != "RJ":
                        continue
                    munic = (row[_C["munic"]] or "").strip().upper()
                    if apenas_municipio and munic != apenas_municipio:
                        continue
                    nn = normalizar(row[_C["nome"]])
                    if not nn:
                        continue
                    cands[nn] = {"nome": row[_C["nome"]].strip(), "cidade": munic,
                                 "ano": int(row[_C["ano"]] or ano), "cargo": row[_C["cargo"]].strip()}
        print(f"  [{ano}] {len(cands)} candidatos únicos acumulados", flush=True)
    return cands


def _ano(data: str) -> int | None:
    m = re.search(r"/(\d{4})$", (data or "").strip())
    return int(m.group(1)) if m else None


def coletar(anos: list[int] | None = None, apenas_municipio: str | None = "RIO DE JANEIRO",
            competencias: list[tuple[int, int]] | None = None, workers: int = 2,
            pausa: float = 0.4, db_path=None) -> dict:
    """Baixa candidatos, consulta cada nome na Prefeitura e grava os que são comissionados 2021+."""
    from compliance_agent.pcrj.cruzamento import competencia_mais_recente
    anos = anos or ANOS_MUNICIPAIS
    competencias = competencias or [competencia_mais_recente(), (6, 2024), (6, 2022)]
    _db.inicializar(db_path)
    print("Baixando candidatos do TSE (RJ)…", flush=True)
    cands = _candidatos(anos, apenas_municipio)
    print(f"{len(cands)} candidatos únicos a verificar na Prefeitura", flush=True)

    sessoes = [Sessao(pausa=pausa) for _ in range(workers)]
    itens = list(cands.items())

    def tarefa(i_item):
        i, (nn, info) = i_item
        sess = sessoes[i % workers]
        achados = {}
        for mes, ano in competencias:
            linhas = sess.consultar_nome(info["nome"], mes, ano)
            if not linhas:
                continue
            for row in linhas:
                if normalizar(row.get("nome", "")) != nn:
                    continue
                if not _RE_COMISSIONADO.search(row.get("cargo", "")):
                    continue                       # só comissionados
                adm_ano = _ano(row.get("admissao", ""))
                if not adm_ano or adm_ano < _ADM_MIN:
                    continue                       # 2021 pra cá
                achados[row.get("matricula", "?")] = row
        return nn, info, achados

    con = _db.conectar(db_path)
    agora = datetime.now(timezone.utc).isoformat()
    n_pessoas = n_reg = feitos = 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
          for nn, info, achados in ex.map(tarefa, enumerate(itens)):
            if achados:
                n_pessoas += 1
            for _mat, row in achados.items():
                con.execute(
                    """INSERT OR REPLACE INTO pcrj_comissionado_candidato
                       (nome_norm,nome_pcrj,cargo_pcrj,orgao_pcrj,admissao,exoneracao,matricula,
                        cand_cidade,cand_ano,cand_cargo,coletado_em)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (nn, row.get("nome"), row.get("cargo"), row.get("lotacao"),
                     row.get("admissao"), row.get("exoneracao"), row.get("matricula"),
                     info["cidade"], info["ano"], info["cargo"], agora))
                n_reg += 1
            feitos += 1
            if feitos % 200 == 0:
                con.commit()
                print(f"  ...{feitos}/{len(itens)} verificados · {n_pessoas} comissionados-candidatos",
                      flush=True)
        con.commit()
    finally:
        con.close()
    return {"candidatos_verificados": len(itens), "comissionados_candidatos": n_pessoas,
            "registros": n_reg, "municipio": apenas_municipio}


def competencias_mensais(ini_mes: int = 1, ini_ano: int = 2021,
                         fim: tuple[int, int] | None = None) -> list[tuple[int, int]]:
    """Todas as competências (mês,ano) de ini→fim (default: até a mais recente com dados)."""
    from compliance_agent.pcrj.cruzamento import competencia_mais_recente
    fm, fa = fim or competencia_mais_recente()
    out = []
    m, a = ini_mes, ini_ano
    while (a, m) <= (fa, fm):
        out.append((m, a))
        m += 1
        if m > 12:
            m, a = 1, a + 1
    return out


def coletar_mensal(anos: list[int] | None = None,
                   apenas_municipio: str | None = "RIO DE JANEIRO",
                   ini: tuple[int, int] = (1, 2021), workers: int = 2,
                   pausa: float = 0.4, db_path=None) -> dict:
    """Varre a folha da Prefeitura MÊS A MÊS (2021→hoje) atrás de candidatos que viraram
    comissionados. RESUMÍVEL: um checkpoint (data/pcrj_comiss_mensal.done) guarda as
    competências já concluídas — reiniciar retoma de onde parou. Throttle seguro (workers=2,
    pausa=0.4 = 0 bloqueios). Loop competência-externo p/ o checkpoint fazer sentido."""
    import json
    from pathlib import Path

    from compliance_agent.pcrj import db as _db2
    anos = anos or ANOS_MUNICIPAIS
    _db.inicializar(db_path)
    ckpt = (Path(db_path).parent if db_path else _db2.DB_PATH.parent) / "pcrj_comiss_mensal.done"
    feitas = set()
    if ckpt.exists():
        feitas = {tuple(x) for x in json.loads(ckpt.read_text() or "[]")}
    print("Baixando candidatos do TSE (RJ)…", flush=True)
    cands = _candidatos(anos, apenas_municipio)
    itens = list(cands.items())
    todas = [c for c in competencias_mensais(*ini) if tuple(c) not in feitas]
    print(f"{len(cands)} candidatos × {len(todas)} competências pendentes "
          f"({len(feitas)} já feitas)", flush=True)

    sessoes = [Sessao(pausa=pausa) for _ in range(workers)]
    agora = datetime.now(timezone.utc).isoformat()
    total_reg = 0
    for (mes, ano) in todas:
        def tarefa(i_item, mm=mes, aa=ano):
            i, (nn, info) = i_item
            sess = sessoes[i % workers]
            achados = {}
            for row in sess.consultar_nome(info["nome"], mm, aa) or []:
                if normalizar(row.get("nome", "")) != nn:
                    continue
                if not _RE_COMISSIONADO.search(row.get("cargo", "")):
                    continue
                adm_ano = _ano(row.get("admissao", ""))
                if not adm_ano or adm_ano < _ADM_MIN:
                    continue
                achados[row.get("matricula", "?")] = row
            return nn, info, achados

        con = _db.conectar(db_path)
        reg = feitos = 0
        try:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                for nn, info, achados in ex.map(tarefa, enumerate(itens)):
                    for _mat, row in achados.items():
                        con.execute(
                            """INSERT OR REPLACE INTO pcrj_comissionado_candidato
                               (nome_norm,nome_pcrj,cargo_pcrj,orgao_pcrj,admissao,exoneracao,
                                matricula,cand_cidade,cand_ano,cand_cargo,coletado_em)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                            (nn, row.get("nome"), row.get("cargo"), row.get("lotacao"),
                             row.get("admissao"), row.get("exoneracao"), row.get("matricula"),
                             info["cidade"], info["ano"], info["cargo"], agora))
                        reg += 1
                    feitos += 1
                    if feitos % 300 == 0:      # commit incremental: não segura o lock a competência inteira
                        con.commit()
            con.commit()
        finally:
            con.close()
        total_reg += reg
        feitas.add((mes, ano))
        ckpt.write_text(json.dumps([list(c) for c in sorted(feitas)]))
        print(f"  {mes:02d}/{ano}: {reg} registros (total {total_reg})", flush=True)
    return {"competencias": len(todas), "registros": total_reg}


if __name__ == "__main__":
    import sys
    if "--mensal" in sys.argv:
        print(coletar_mensal())
    else:
        print(coletar())
