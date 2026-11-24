# -*- coding: utf-8 -*-
"""cache — cache COMPOSTO local do gateway LLM (plano mestre v2 §6 "fatos reaproveitados pela chave"; O6.1 c).

CHAVE = sha256 do JSON canônico dos componentes (`componentes()`): versão da montagem do prompt, tarefa, hash das
mensagens do chamador, por documento (id, versão sha256, sha do texto, versão da extração, nº de páginas, hash dos
metadados), prompt_version, modelo pedido, regra/versão, schema, contexto, classe do dado, camadas candidatas
(provedores que a política deixa receber) e se a citação é exigida. INVALIDAÇÃO: qualquer componente mudou ⇒
chave nova ⇒ miss (o antigo nunca é servido); `invalidar()` apaga por tarefa e/ou documento.

O QUE GUARDA: a resposta COMO VEIO do provedor — já MASCARADA (CPF/conta como `[CPF_n]`; o mapa nunca é gravado).
No acerto, o gateway remascara a entrada (mesma entrada ⇒ mesmo mapa), desmascara e roda de novo a validação
pós-parse (citações, schema): o acerto passa pelos mesmos portões que a resposta nova. Só entra no cache
resultado RESPONDIDO ou ABSTEVE (INDETERMINADO_FALHA_CITACAO e falha nunca: outra tentativa pode acertar).

Banco: `JFN_LLM_CACHE_DB` ou `data/llm_cache.db` (gitignored, `data/*.db`). Falha de disco não derruba a chamada.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)
_REPO = Path(__file__).resolve().parents[3]

_DDL = """CREATE TABLE IF NOT EXISTS llm_cache(
  chave TEXT PRIMARY KEY, tarefa TEXT, criado_em TEXT DEFAULT (datetime('now')), usado_em TEXT, hits INT DEFAULT 0,
  componentes TEXT, documentos TEXT, texto TEXT, dados TEXT, estado TEXT, provedor TEXT, camada INT, modelo TEXT,
  release_ia TEXT)"""


def caminho() -> Path:
    return Path(os.environ.get("JFN_LLM_CACHE_DB") or (_REPO / "data" / "llm_cache.db"))


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(caminho(), timeout=5)
    con.execute(_DDL)
    con.execute("CREATE INDEX IF NOT EXISTS ix_llm_cache_tarefa ON llm_cache(tarefa)")
    return con


def _sha(obj) -> str:
    bruto = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def componentes(*, montagem: str, tarefa: str, sistema: str, prompt: str, documentos: list, prompt_version: str,
                modelo: str | None, regra: str | None, schema: str | None, contexto, classe_dado: str,
                candidatos: list, exigir_citacao: bool) -> dict:
    """Só hashes e ids — nenhum texto entra (nem na chave nem na coluna `componentes`)."""
    return {"montagem": montagem, "tarefa": tarefa, "mensagens": _sha([sistema, prompt]), "documentos": documentos,
            "prompt_version": prompt_version, "modelo": modelo, "regra": regra,
            "schema": _sha(schema) if schema is not None else None,
            "contexto": _sha(contexto) if contexto is not None else None, "classe_dado": classe_dado,
            "candidatos": [list(c) for c in candidatos], "exigir_citacao": bool(exigir_citacao)}


def chave(comp: dict) -> str:
    return _sha(comp)


def ler(ch: str) -> dict | None:
    try:
        con = _con()
        try:
            con.row_factory = sqlite3.Row
            r = con.execute("SELECT * FROM llm_cache WHERE chave=?", (ch,)).fetchone()
            if r is None:
                return None
            con.execute("UPDATE llm_cache SET hits=hits+1, usado_em=datetime('now') WHERE chave=?", (ch,))
            con.commit()
            d = dict(r)
            d["dados"] = json.loads(d["dados"]) if d.get("dados") else None
            return d
        finally:
            con.close()
    except (sqlite3.Error, OSError, ValueError) as e:
        logger.warning("gateway: cache ilegível (%s) — segue sem cache", type(e).__name__)
        return None


def gravar(ch: str, comp: dict, *, tarefa: str, texto: str, dados, estado: str, provedor: str, camada: int,
           modelo: str | None, release_ia: str) -> None:
    try:
        con = _con()
        try:
            con.execute("INSERT OR REPLACE INTO llm_cache(chave, tarefa, componentes, documentos, texto, dados, estado,"
                        " provedor, camada, modelo, release_ia) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (ch, tarefa, json.dumps(comp, ensure_ascii=False, sort_keys=True),
                         json.dumps([d[0] for d in comp.get("documentos") or []], ensure_ascii=False), texto,
                         json.dumps(dados, ensure_ascii=False, default=str) if dados is not None else None, estado,
                         provedor, camada, modelo, release_ia))
            con.commit()
        finally:
            con.close()
    except (sqlite3.Error, OSError, TypeError) as e:
        logger.warning("gateway: cache não gravado (%s)", type(e).__name__)


def invalidar(*, tarefa: str | None = None, documento_id: str | None = None) -> int:
    """Apaga entradas da tarefa e/ou que usaram o documento. Sem filtro ⇒ erro (nada de apagar tudo sem querer)."""
    if tarefa is None and documento_id is None:
        raise ValueError("invalidar: diga a tarefa e/ou o documento")
    onde, args = [], []
    if tarefa is not None:
        onde.append("tarefa=?")
        args.append(tarefa)
    if documento_id is not None:
        onde.append("EXISTS (SELECT 1 FROM json_each(llm_cache.documentos) WHERE value=?)")
        args.append(documento_id)
    con = _con()
    try:
        n = con.execute(f"DELETE FROM llm_cache WHERE {' AND '.join(onde)}", args).rowcount
        con.commit()
        return n
    finally:
        con.close()
