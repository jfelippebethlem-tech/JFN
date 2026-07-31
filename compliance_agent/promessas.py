# -*- coding: utf-8 -*-
"""Promessas de entrega que sobrevivem ao processo.

POR QUE EXISTE. As rotas de produto (`/api/relatorio/inteligencia`, `/api/relatorio/orgao`,
`/api/dossie`) respondem na hora — *"Eu te envio aqui mesmo em ~1–2 min"* — e delegam a geração a um
`asyncio.create_task`. O tratamento de erro DENTRO da tarefa já é bom: falhou, avisa no Telegram e
limpa no `finally`. O buraco é a morte do PROCESSO: a tarefa morre com ele, sem aviso e sem
retentativa, e o humano fica esperando um PDF que nunca chega — a queixa "promete e não entrega".

Não era hipótese: medido em 31/07/2026, o `jfn.service` era reiniciado **7 a 14 vezes por dia** pelo
`guardiao_db_malformed.sh` (defeito do WAL-index, corrigido no mesmo dia). Toda geração em curso
naquele instante virava silêncio.

O `_REL_EM_CURSO` de `rotas/produtos.py` já era o registro de "em curso" — só vivia em memória.
Aqui ele ganha disco: a promessa é anotada ANTES de prometer, apagada quando a entrega termina, e o
que sobrar no arquivo depois de um boot é exatamente o que ficou devendo.

Escrita atômica (tmp + replace) porque um crash no meio do write deixaria JSON truncado — e aí o
boot perderia TODAS as promessas, trocando um silêncio por outro maior.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_ARQ = Path(__file__).resolve().parent.parent / "data" / "promessas_pendentes.json"


def _ler() -> list[dict]:
    try:
        d = json.loads(_ARQ.read_text(encoding="utf-8"))
        return [x for x in d if isinstance(x, dict) and x.get("chave")] if isinstance(d, list) else []
    except (OSError, ValueError):
        return []   # ausente ou corrompido: o servidor sobe igual, sem promessa a cobrar


def _gravar(itens: list[dict]) -> None:
    _ARQ.parent.mkdir(parents=True, exist_ok=True)
    tmp = _ARQ.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(itens, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _ARQ)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def registrar(chave: str, tipo: str, args: dict) -> None:
    """Anota a promessa ANTES de responder ao Mestre. Idempotente pela chave."""
    itens = [x for x in _ler() if x.get("chave") != chave]
    itens.append({"chave": chave, "tipo": tipo, "args": args})
    _gravar(itens)


def concluir(chave: str) -> None:
    """Apaga a promessa — chamada no `finally` da tarefa, tenha ela entregue ou avisado o erro."""
    itens = _ler()
    restantes = [x for x in itens if x.get("chave") != chave]
    if len(restantes) != len(itens):
        _gravar(restantes)


def pendentes() -> list[dict]:
    """O que ficou devendo. Depois de um boot, é o que o processo anterior não entregou."""
    return _ler()
