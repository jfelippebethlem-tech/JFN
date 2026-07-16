#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Registro-CONTROLE de processos SEI de acesso RESTRITO, alimentado ao longo dos sweeps do itkava.

Descoberto 2026-07-14: um processo de NÍVEL DE ACESSO RESTRITO some da busca cross-unit do itkava —
retorna 0 documentos, a árvore NÃO abre (arvore_carregou None/False, ou indisponivel=True no caminho
normal), SEM redirect de login e SEM "acesso negado"/"nenhum registro"; a busca volta à fila de Controle
de Processos. Processos OSTENSIVOS da MESMA unidade abrem normal (ex.: UEPSAM Construverde 856 docs). Logo,
0-doc + árvore-não-abriu + o processo EXISTE no cadastro (contratos_tcerj/SIAFE) = provável RESTRITO
(existe mas escondido). Distingue de OK (tem docs), PARCIAL (tem docs mas cadeado/n_docs_restritos>0),
NAO_LOCALIZADO (0-doc sem evidência de existência — pode ser nº errado) e INDISPONIVEL (erro/browser/flaky).
Confirma RESTRITO só com >=2 leituras 0-doc consistentes (score), robusto à flakiness do reader.

Uso (registro, chamado pelo sweep): sei_restritos.registrar(numero, r)
CLI (lista de controle):  .venv/bin/python tools/sei_restritos.py            # tabela dos restritos
                          .venv/bin/python tools/sei_restritos.py --todos    # todos os status
                          .venv/bin/python tools/sei_restritos.py --seed NUM UNIDADE  # marca 1 à mão
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO = Path("/home/ubuntu/JFN")
REG = REPO / "data" / "sei_restritos.json"
DB = REPO / "data" / "compliance.db"

# prefixos de unidade SEI-RJ conhecidos (6 dígitos) → rótulo (best-effort; não é UG do SIAFE)
_UNIDADES = {
    "070002": "INEA", "070026": "SEAS", "070028": "UEPSAM/PSAM", "070001": "SEAS-gab",
    "133100": "ITERJ", "330020": "SECID/obras", "530100": "Cidades", "240200": "SEAS/PSAM",
    "460001": "SEOP/obras", "270042": "ITERJ",
}


def _norm(numero: str) -> str:
    return re.sub(r"\D", "", numero or "")


def _prefixo(numero: str) -> str:
    d = _norm(numero)
    return d[:6] if len(d) >= 6 else d


def existe_no_cadastro(numero: str) -> str | None:
    """Evidência independente de que o processo EXISTE (p/ separar RESTRITO de nº-errado).
    Retorna a fonte ('contratos_tcerj'/'siafe') ou None. Casa por dígitos do protocolo."""
    d = _norm(numero)
    if len(d) < 12 or not DB.exists():
        return None
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            if c.execute("SELECT 1 FROM contratos_tcerj WHERE sei_norm=? LIMIT 1", (d,)).fetchone():
                return "contratos_tcerj"
            # SIAFE guarda o processo como texto 'SEI-uuuuuu/nnnnnn/aaaa' → normaliza na consulta
            row = c.execute(
                "SELECT 1 FROM ob_orcamentaria_siafe "
                "WHERE replace(replace(replace(replace(processo,'SEI-',''),'.',''),'/',''),'-','')=? LIMIT 1",
                (d,)).fetchone()
            if row:
                return "siafe"
        finally:
            c.close()
    except sqlite3.Error:
        return None
    return None


def classificar(r: dict, existe: str | None) -> str:
    """Status de acesso de UMA leitura. RESTRITO só se 0-doc + árvore-não-abriu + existe no cadastro."""
    if r.get("erro"):
        return "INDISPONIVEL"
    docs = r.get("documentos") or []
    cadeado = bool(r.get("cadeado"))
    nrestr = int(r.get("n_docs_restritos") or 0)
    if docs:
        return "PARCIAL" if (cadeado or nrestr > 0) else "OK"
    # 0 documentos:
    arvore_falhou = (r.get("arvore_carregou") in (None, False)) or bool(r.get("indisponivel"))
    if not arvore_falhou:
        return "INDISPONIVEL"
    return "RESTRITO" if existe else "NAO_LOCALIZADO"


def _load() -> dict:
    if REG.exists():
        try:
            return json.loads(REG.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def _save(reg: dict) -> None:
    REG.parent.mkdir(parents=True, exist_ok=True)
    tmp = REG.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, REG)


def registrar(numero: str, r: dict, *, fonte: str = "sweep") -> str:
    """Registra o resultado de UMA leitura no controle de restritos. Idempotente por número.
    Score: 0-doc-existe (RESTRITO) incrementa; OK/PARCIAL zera. status_final:
    RESTRITO (score>=2) · RESTRITO? (score==1) · PARCIAL · OK · NAO_LOCALIZADO · INDISPONIVEL.
    Devolve o status_final. NUNCA levanta (degrada em silêncio p/ não derrubar o sweep)."""
    try:
        d = _norm(numero)
        if len(d) < 10:
            return "?"
        existe = existe_no_cadastro(numero)
        st = classificar(r, existe)
        reg = _load()
        e = reg.get(d) or {"numero": numero, "prefixo": _prefixo(numero),
                           "unidade": _UNIDADES.get(_prefixo(numero), ""), "primeira": _agora(),
                           "n_leituras": 0, "restrito_score": 0, "existe": existe, "fonte_existencia": existe}
        e["numero"] = numero
        e["ultima"] = _agora()
        e["n_leituras"] = int(e.get("n_leituras", 0)) + 1
        e["ult_leitura"] = st
        e["ult_docs"] = len(r.get("documentos") or [])
        if existe and not e.get("fonte_existencia"):
            e["fonte_existencia"] = existe; e["existe"] = existe
        if st == "RESTRITO":
            e["restrito_score"] = int(e.get("restrito_score", 0)) + 1
        elif st in ("OK", "PARCIAL"):
            e["restrito_score"] = 0
        # status_final consolidado
        sc = int(e.get("restrito_score", 0))
        if sc >= 2:
            e["status"] = "RESTRITO"
        elif sc == 1:
            e["status"] = "RESTRITO?"
        else:
            e["status"] = st
        e["fonte"] = fonte
        reg[d] = e
        _save(reg)
        return e["status"]
    except (OSError, ValueError, TypeError, KeyError):  # nunca derrubar o sweep
        return "?"


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def seed(numero: str, unidade: str = "", motivo: str = "confirmado à mão") -> None:
    """Marca um processo como RESTRITO confirmado (score alto), p/ semear casos já conhecidos."""
    reg = _load()
    d = _norm(numero)
    e = reg.get(d) or {"numero": numero, "prefixo": _prefixo(numero), "primeira": _agora(), "n_leituras": 0}
    e.update({"numero": numero, "unidade": unidade or _UNIDADES.get(_prefixo(numero), ""),
              "status": "RESTRITO", "restrito_score": max(2, int(e.get("restrito_score", 0))),
              "existe": e.get("existe") or existe_no_cadastro(numero), "ultima": _agora(),
              "ult_leitura": "RESTRITO", "motivo": motivo, "fonte": "seed"})
    reg[d] = e
    _save(reg)


def listar(todos: bool = False) -> list[dict]:
    reg = _load()
    itens = list(reg.values())
    if not todos:
        itens = [e for e in itens if str(e.get("status", "")).startswith("RESTRITO") or e.get("status") == "PARCIAL"]
    return sorted(itens, key=lambda e: (e.get("status", ""), e.get("prefixo", ""), e.get("numero", "")))


def _tabela(itens: list[dict]) -> str:
    if not itens:
        return "(nenhum processo restrito registrado ainda — a lista se alimenta ao longo dos sweeps)"
    linhas = [f"{'STATUS':10} {'PROCESSO':26} {'UNIDADE':14} {'EXISTE':14} {'LEIT':4} {'ÚLTIMA':16}"]
    linhas.append("-" * 92)
    for e in itens:
        linhas.append(f"{e.get('status',''):10} {e.get('numero',''):26} {(e.get('unidade') or '—'):14} "
                      f"{(e.get('fonte_existencia') or e.get('existe') or '—'):14} "
                      f"{e.get('n_leituras',0):<4} {e.get('ultima',''):16}")
    return "\n".join(linhas)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--seed" and len(args) >= 2:
        seed(args[1], args[2] if len(args) > 2 else "")
        print("semeado:", args[1])
    todos = "--todos" in args
    itens = listar(todos=todos)
    print(_tabela(itens))
    n_restr = sum(1 for e in itens if e.get("status", "").startswith("RESTRITO"))
    print(f"\nTotal: {len(itens)} listados · {n_restr} restritos (confirmados/suspeitos). Registro: {REG}")
