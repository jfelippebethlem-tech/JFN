# -*- coding: utf-8 -*-
"""folha_estado — folha de ATIVOS do Executivo do Estado do RJ (GESPERJ).

A SPA https://www.rj.gov.br/remuneracao/ consome uma API REST aberta (descoberta no bundle
2026-07-17): ``/remuneracao/api/rest/remuneracoes?page=&size=&ano=&mes=`` — ~482 mil registros
por competência, com órgão, nome, CPF mascarado (middle-6), cargo, vínculo e valores.
Regras da API: ``size`` ∈ [10, 50]; export CSV dá 504 (inviável); portanto paginação com pausa.

~9,6 mil páginas por competência → coleta RESUMÍVEL: progresso em data/folha_estado_progresso.json;
cada run continua de onde parou (teto ``paginas_por_run`` p/ caber no cron do orquestrador).
Grava em ``registros_folha`` (fonte=gesperj_estado), dedup por (nome, cargo, orgao) na competência.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import httpx

_BASE = "https://www.rj.gov.br/remuneracao/api/rest"
_H = {"User-Agent": "Mozilla/5.0 (X11; Linux) JFN-Compliance/2.0"}
_FONTE = "gesperj_estado"
_RAIZ = Path(__file__).resolve().parent.parent.parent
_DB = _RAIZ / "data" / "compliance.db"
_PROGRESSO = _RAIZ / "data" / "folha_estado_progresso.json"
_SIZE = 50  # máximo aceito pela API (validação rejeita >50 e <10)
_SQL_INSERT = (
    "INSERT INTO registros_folha (cpf,nome,orgao_codigo,orgao_nome,cargo,vinculo,competencia,"
    "remuneracao_bruta,remuneracao_liquida,abonos,descontos,matricula,fonte,created_at) "
    f"VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'{_FONTE}',datetime('now'))")


def _get(client: httpx.Client, params: dict) -> dict | None:
    for tent in range(4):
        try:
            r = client.get(f"{_BASE}/remuneracoes", params=params, headers=_H)
        except httpx.HTTPError:
            time.sleep(2 * (tent + 1))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 502, 503, 504):
            time.sleep(4 * (tent + 1))
            continue
        return None
    return None


def ultima_competencia(client: httpx.Client) -> tuple[int, int] | None:
    """Competência mais recente com dado (a publicação atrasa alguns meses)."""
    a, m = date.today().year, date.today().month
    for _ in range(10):
        j = _get(client, {"page": 0, "size": 10, "ano": a, "mes": m})
        if j and j.get("totalElements"):
            return a, m
        a, m = (a - 1, 12) if m == 1 else (a, m - 1)
    return None


def _cpf_middle6(masc: str) -> str:
    """"***.889.157-**" → "XX889157XXX" (reusa o parser middle-6 canônico do projeto)."""
    from compliance_agent.resolucao_cpf import middle6
    m = middle6(masc)
    return f"XX{m}XXX" if m else ""


def _carregar_progresso() -> dict:
    """{"competencia","pagina","completa"} do último run, ou {} (arquivo ausente/corrompido)."""
    try:
        p = json.loads(_PROGRESSO.read_text())
        return p if isinstance(p, dict) else {}
    except Exception:
        return {}


def _salvar_progresso(comp: str, pagina: int, completa: bool = False) -> None:
    # write atômico: crash no meio do write_text deixaria JSON truncado → run recomeça da pág. 0
    import os
    tmp = _PROGRESSO.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"competencia": comp, "pagina": pagina, "completa": completa}))
    os.replace(tmp, _PROGRESSO)


def coletar(paginas_por_run: int = 1500, pausa: float = 0.35, db_path: str | None = None) -> dict:
    """Coleta incremental da competência mais recente. Idempotente (dedup) e resumível.
    Lock de instância única: sweep manual × cron do orquestrador ao MESMO tempo leriam o mesmo
    dedup inicial e duplicariam linhas — o segundo processo sai limpo."""
    import fcntl
    import sqlite3
    lock = open(_RAIZ / "data" / "folha_estado.lock", "w")  # noqa: SIM115 — vive até o fim do run
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return {"fonte": _FONTE, "erro": "já em execução (lock)", "paginas": 0, "novos": 0}
    con = sqlite3.connect(db_path or str(_DB), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    # migração leve: matrícula desambigua homônimos (2 "JOSE DA SILVA" PROFESSOR na mesma
    # secretaria são servidores DISTINTOS) e torna o dedup resumível sem subcontar
    cols = {r[1] for r in con.execute("PRAGMA table_info(registros_folha)")}
    if "matricula" not in cols:
        con.execute("ALTER TABLE registros_folha ADD COLUMN matricula VARCHAR(30)")
        con.commit()
    tot = {"fonte": _FONTE, "paginas": 0, "novos": 0, "vistos": 0, "erros": 0}
    try:
        with httpx.Client(timeout=40) as client:
            # competência-alvo: TERMINAR a do progresso antes de pular para uma recém-publicada
            # (senão a anterior ficaria ~parcial p/ sempre, indistinguível de completa)
            prog = _carregar_progresso()
            if prog.get("competencia") and not prog.get("completa"):
                comp = prog["competencia"]
                ano, mes = int(comp[:4]), int(comp[5:7])
                pagina = int(prog.get("pagina", 0))
            else:
                comp_am = ultima_competencia(client)
                if not comp_am:
                    return {**tot, "erro": "nenhuma competência com dado (API fora?)"}
                ano, mes = comp_am
                comp = f"{ano:04d}-{mes:02d}"
                pagina = 0
                if prog.get("competencia") == comp and prog.get("completa"):
                    return {**tot, "competencia": comp, "completa": True}
            tot["competencia"] = comp
            # dedup: o que já existe desta fonte nesta competência (matrícula desambigua homônimo)
            vistos = {(r[0], r[1], r[2], r[3] or "") for r in con.execute(
                "SELECT nome, cargo, orgao_nome, matricula FROM registros_folha "
                "WHERE fonte=? AND competencia=?", (_FONTE, comp))}
            lote: list[tuple] = []
            fim = False
            while tot["paginas"] < paginas_por_run and not fim:
                j = _get(client, {"page": pagina, "size": _SIZE, "ano": ano, "mes": mes})
                if j is None:
                    tot["erros"] += 1
                    break
                regs = j.get("remuneracoes") or []
                for r in regs:
                    chave = (r.get("nomeServidor"), r.get("funcaoCargo"), r.get("orgao"),
                             (r.get("matriculaServidor") or "").strip())
                    if not chave[0] or chave in vistos:
                        tot["vistos"] += 1
                        continue
                    vistos.add(chave)
                    lote.append((_cpf_middle6(r.get("cpf") or ""), r["nomeServidor"], "",
                                 r.get("orgao") or "", r.get("funcaoCargo") or "",
                                 (r.get("vinculo") or "")[:50], comp,
                                 float(r.get("totalVantagens") or 0),
                                 float(r.get("valorLiquido") or 0), 0.0,
                                 float(r.get("totalDescontos") or 0), chave[3]))
                tot["paginas"] += 1
                pagina += 1
                fim = pagina >= (j.get("totalPages") or 0)
                if len(lote) >= 1000 or fim:
                    con.executemany(_SQL_INSERT, lote)
                    con.commit()
                    tot["novos"] += len(lote)
                    lote = []
                    _salvar_progresso(comp, pagina, completa=fim)
                time.sleep(pausa)
            if lote:
                con.executemany(_SQL_INSERT, lote)
                con.commit()
                tot["novos"] += len(lote)
            _salvar_progresso(comp, pagina, completa=fim)
            tot["completa"] = fim
    finally:
        con.close()
        lock.close()  # solta o flock
    return tot


if __name__ == "__main__":
    import sys
    teto = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1500
    print(json.dumps(coletar(paginas_por_run=teto), ensure_ascii=False), flush=True)
