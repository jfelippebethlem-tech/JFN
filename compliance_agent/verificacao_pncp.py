# -*- coding: utf-8 -*-
"""Conferência de item de compra na FONTE PRIMÁRIA (API do PNCP) — VERIFICADO / PENDENTE.

Diretriz do dono (2026-11-13): "não pode ter margem pra erro em nada". Todo sobrepreço
exibido mostra o estado da conferência, e a economia potencial só SOMA o que foi conferido.

O que "VERIFICADO" afirma — e nada além disso: o PNCP, consultado item a item
(`/orgaos/{cnpj}/compras/{ano}/{seq}/itens/{n}` e `/resultados`), publica para aquele item a
MESMA descrição, a MESMA unidade de medida, a MESMA quantidade e o MESMO valor unitário
homologado para o MESMO fornecedor que a base local usou na conta. Não afirma que houve
sobrepreço (isso exige termo de referência e pesquisa de mercado da época).

Estados: VERIFICADO · DIVERGENTE (a fonte diz outra coisa — sai da conta, motivo por extenso)
· PENDENTE (ainda não conferido, ou a fonte não respondeu — nunca vira zero nem verificado).

A conferência fica num SQLite próprio (`verificacao_precos.db`, ao lado do compliance.db),
para não escrever no banco principal (escrita nele trava as rotas de leitura do painel).
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.request
from datetime import datetime
from pathlib import Path

VERIFICADO, DIVERGENTE, PENDENTE = "VERIFICADO", "DIVERGENTE", "PENDENTE"
_API = "https://pncp.gov.br/api/pncp/v1"
_UA = {"User-Agent": "JFN-Compliance/2.0"}
_RX_CERT = re.compile(r"^(\d{14})-\d+-(\d+)/(\d{4})$")


def caminho_store(db_path: str | None) -> Path:
    from compliance_agent.comparador_precos import _DB
    return Path(db_path or _DB).resolve().parent / "verificacao_precos.db"


def _abrir(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path), timeout=30)
    con.execute("""CREATE TABLE IF NOT EXISTS verificacao (
        certame TEXT NOT NULL, item INTEGER NOT NULL, fornecedor_cnpj TEXT NOT NULL,
        estado TEXT NOT NULL, divergencias TEXT, descricao_pncp TEXT, unidade_pncp TEXT,
        quantidade_pncp REAL, valor_unitario_pncp REAL, verificado_em TEXT,
        PRIMARY KEY (certame, item, fornecedor_cnpj))""")
    # dados da CONTRATAÇÃO (não do item): ata de registro de preços? modalidade? objeto?
    con.execute("""CREATE TABLE IF NOT EXISTS certame_info (
        certame TEXT PRIMARY KEY, srp INTEGER, modalidade_nome TEXT, objeto TEXT,
        situacao TEXT, consultado_em TEXT)""")
    return con


def info_certames(db_path: str | None) -> dict[str, dict]:
    """certame → {srp, modalidade_nome, objeto}. Ausente = desconhecido (nunca 'não é ata')."""
    p = caminho_store(db_path)
    if not p.exists():
        return {}
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return {r["certame"]: {"srp": (None if r["srp"] is None else bool(r["srp"])),
                               "modalidade_nome": r["modalidade_nome"], "objeto": r["objeto"]}
                for r in con.execute("SELECT * FROM certame_info")}
    except sqlite3.OperationalError:
        return {}
    finally:
        con.close()


def url_api_compra(certame: str) -> str | None:
    m = _RX_CERT.match(certame or "")
    if not m:
        return None
    return (f"https://pncp.gov.br/api/consulta/v1/orgaos/{m.group(1)}/compras/"
            f"{m.group(3)}/{int(m.group(2))}")


def link_pncp(certame: str | None) -> str | None:
    """'42498733000148-1-000131/2025' → página pública da contratação no PNCP."""
    m = _RX_CERT.match(certame or "")
    if not m:
        return None
    return f"https://pncp.gov.br/app/editais/{m.group(1)}/{m.group(3)}/{int(m.group(2))}"


def url_api_item(certame: str, item: int) -> str | None:
    m = _RX_CERT.match(certame or "")
    if not m:
        return None
    return f"{_API}/orgaos/{m.group(1)}/compras/{m.group(3)}/{int(m.group(2))}/itens/{int(item)}"


def estados(db_path: str | None) -> dict[tuple, dict]:
    """(certame, item, cnpj) → registro da conferência. Store ausente → {} (tudo PENDENTE)."""
    p = caminho_store(db_path)
    if not p.exists():
        return {}
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return {(r["certame"], r["item"], r["fornecedor_cnpj"]): dict(r)
                for r in con.execute("SELECT * FROM verificacao")}
    except sqlite3.OperationalError:
        return {}
    finally:
        con.close()


def estado_de(tabela: dict, certame, item, cnpj) -> dict:
    r = tabela.get((certame, item, cnpj)) if item is not None else None
    if not r:
        return {"estado": PENDENTE, "divergencias": None, "verificado_em": None}
    return {"estado": r["estado"], "divergencias": r.get("divergencias"),
            "verificado_em": r.get("verificado_em")}


def _ws(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def comparar(esperado: dict, item_api: dict, resultados_api: list) -> tuple[str, list[str], dict]:
    """Confronta a linha da base com o que o PNCP publica. Função pura (testável)."""
    div = []
    if _ws(item_api.get("descricao")) != _ws(esperado["descricao"]):
        div.append(f"descrição no PNCP: '{_ws(item_api.get('descricao'))[:80]}'")
    if _ws(item_api.get("unidadeMedida")).lower() != _ws(esperado["unidade"]).lower():
        div.append(f"unidade no PNCP: '{_ws(item_api.get('unidadeMedida'))}'")
    q = item_api.get("quantidade")
    if q is None or abs(float(q) - float(esperado["quantidade"] or 0)) > 1e-6:
        div.append(f"quantidade no PNCP: {q}")
    res = [r for r in (resultados_api or [])
           if re.sub(r"\D", "", str(r.get("niFornecedor") or "")) ==
           re.sub(r"\D", "", esperado["fornecedor_cnpj"] or "")
           and not r.get("dataCancelamento")]
    vu = res[0].get("valorUnitarioHomologado") if res else None
    if vu is None:
        div.append("resultado do fornecedor não encontrado (ou cancelado) no PNCP")
    elif abs(float(vu) - float(esperado["valor_unitario"])) > 0.005:
        div.append(f"valor unitário homologado no PNCP: {vu}")
    fonte = {"descricao_pncp": item_api.get("descricao"), "unidade_pncp": item_api.get("unidadeMedida"),
             "quantidade_pncp": q, "valor_unitario_pncp": vu}
    return (VERIFICADO if not div else DIVERGENTE), div, fonte


def _get(url: str, timeout: int = 40):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 — URL fixa do PNCP
        return json.loads(r.read().decode("utf-8"))


def verificar(db_path: str | None, linhas: list[dict], pausa: float = 1.0,
              refazer: bool = False, log=print) -> dict:
    """Confere cada linha {certame, item, fornecedor_cnpj, descricao, unidade, quantidade,
    valor_unitario} no PNCP e grava o estado. Falha de rede → fica PENDENTE (não grava)."""
    p = caminho_store(db_path)
    con = _abrir(p)
    feitos = {(r[0], r[1], r[2]) for r in con.execute(
        "SELECT certame, item, fornecedor_cnpj FROM verificacao")} if not refazer else set()
    certs_feitos = {r[0] for r in con.execute(
        "SELECT certame FROM certame_info WHERE srp IS NOT NULL")}
    cont = {VERIFICADO: 0, DIVERGENTE: 0, PENDENTE: 0, "ja_conferidos": 0, "certames": 0}
    try:
        for ln in linhas:
            cert = ln["certame"]
            if cert not in certs_feitos and url_api_compra(cert):
                try:
                    c = _get(url_api_compra(cert))
                    time.sleep(pausa)
                    srp = c.get("srp")
                    con.execute("INSERT OR REPLACE INTO certame_info VALUES (?,?,?,?,?,?)",
                                (cert, None if srp is None else int(bool(srp)),
                                 c.get("modalidadeNome"), c.get("objetoCompra"),
                                 c.get("situacaoCompraNome"),
                                 datetime.now().isoformat(timespec="seconds")))
                    con.commit()
                    certs_feitos.add(cert)
                    cont["certames"] += 1
                except Exception as exc:  # noqa: BLE001 — sem resposta: srp segue desconhecido
                    log(f"  certame {cert} sem resposta: {exc}")
            k = (ln["certame"], ln["item"], ln["fornecedor_cnpj"])
            if k in feitos:
                cont["ja_conferidos"] += 1
                continue
            url = url_api_item(ln["certame"], ln["item"])
            if not url:
                cont[PENDENTE] += 1
                continue
            try:
                item_api = _get(url)
                time.sleep(pausa)
                res_api = _get(url + "/resultados")
                time.sleep(pausa)
            except Exception as exc:  # noqa: BLE001 — rede/HTTP: fica PENDENTE, nunca verificado
                log(f"  PENDENTE {k}: {exc}")
                cont[PENDENTE] += 1
                time.sleep(pausa * 3)
                continue
            est, div, fonte = comparar(ln, item_api, res_api)
            con.execute(
                "INSERT OR REPLACE INTO verificacao VALUES (?,?,?,?,?,?,?,?,?,?)",
                (*k, est, "; ".join(div) or None, fonte["descricao_pncp"], fonte["unidade_pncp"],
                 fonte["quantidade_pncp"], fonte["valor_unitario_pncp"],
                 datetime.now().isoformat(timespec="seconds")))
            con.commit()
            cont[est] += 1
            log(f"  {est} {k}{(' — ' + '; '.join(div)) if div else ''}")
    finally:
        con.close()
    return cont
