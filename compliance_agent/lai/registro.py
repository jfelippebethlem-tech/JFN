# -*- coding: utf-8 -*-
"""Registro dos pedidos LAI (data/lai.db): o que foi gerado, protocolado, respondido — e o prazo."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
DB = _RAIZ / "data" / "lai.db"
STATUS = ("rascunho", "protocolado", "respondido", "negado", "recurso", "arquivado")

DDL = """CREATE TABLE IF NOT EXISTS lai_requerimento (
    id INTEGER PRIMARY KEY AUTOINCREMENT, alvo TEXT NOT NULL, esfera TEXT, destinatario TEXT,
    processos TEXT, contratos TEXT, itens_pedido INTEGER, path_docx TEXT, path_md TEXT,
    status TEXT NOT NULL DEFAULT 'rascunho', protocolo TEXT, protocolado_em TEXT, prazo_resposta TEXT,
    respondido_em TEXT, notas TEXT, criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL);"""


def _con(db_path=None) -> sqlite3.Connection:
    p = Path(db_path or DB)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(DDL)
    return con


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def registrar(alvo: str, esfera: str, destinatario: str, processos: list[str], contratos: list[str],
              itens_pedido: int, path_docx: str | None, path_md: str | None, db_path=None) -> int:
    con = _con(db_path)
    try:
        cur = con.execute(
            "INSERT INTO lai_requerimento (alvo, esfera, destinatario, processos, contratos, itens_pedido, path_docx, "
            "path_md, criado_em, atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (alvo, esfera, destinatario, json.dumps(processos, ensure_ascii=False), json.dumps(contratos, ensure_ascii=False),
             itens_pedido, path_docx, path_md, _agora(), _agora()))
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()


def atualizar(id_: int, status: str, protocolo: str | None = None, notas: str | None = None,
              prazo_dias: int = 20, db_path=None) -> dict:
    """Muda o status; 'protocolado' carimba a data e calcula o prazo de resposta (20 dias, art. 11 §1º)."""
    if status not in STATUS:
        raise ValueError(f"status inválido: {status} (use {', '.join(STATUS)})")
    con = _con(db_path)
    try:
        campos, vals = ["status=?", "atualizado_em=?"], [status, _agora()]
        if protocolo is not None:
            campos.append("protocolo=?"); vals.append(protocolo)
        if notas is not None:
            campos.append("notas=?"); vals.append(notas)
        if status == "protocolado":
            campos += ["protocolado_em=?", "prazo_resposta=?"]
            vals += [_agora(), (datetime.now() + timedelta(days=prazo_dias)).strftime("%Y-%m-%d")]
        if status in ("respondido", "negado"):
            campos.append("respondido_em=?"); vals.append(_agora())
        vals.append(id_)
        con.execute(f"UPDATE lai_requerimento SET {', '.join(campos)} WHERE id=?", vals)
        con.commit()
        r = con.execute("SELECT * FROM lai_requerimento WHERE id=?", (id_,)).fetchone()
        return dict(r) if r else {}
    finally:
        con.close()


def listar(limite: int = 100, db_path=None) -> list[dict]:
    con = _con(db_path)
    try:
        rows = con.execute("SELECT * FROM lai_requerimento ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
        hoje = datetime.now().strftime("%Y-%m-%d")
        saida = []
        for r in rows:
            d = dict(r)
            d["vencido"] = bool(d.get("prazo_resposta") and d["status"] == "protocolado" and d["prazo_resposta"] < hoje)
            saida.append(d)
        return saida
    finally:
        con.close()


def vencendo(dias: int = 3, db_path=None) -> list[dict]:
    """Protocolados cujo prazo vence em até N dias ou já venceu — para o Yoda cobrar."""
    limite = (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d")
    return [d for d in listar(500, db_path) if d["status"] == "protocolado" and d.get("prazo_resposta") and d["prazo_resposta"] <= limite]
