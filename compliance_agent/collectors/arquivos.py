# -*- coding: utf-8 -*-
"""Onde o coletor grava — banco e pasta de dados — e COMO grava arquivo que outro processo lê.

Cada coletor recalculava o caminho do `compliance.db` do seu jeito: `Path(__file__)…/data`, a string
relativa `"data/compliance.db"` (que só acerta se o cron fizer `cd ~/JFN` antes), `JFN_DATA_DIR` em uns,
`JFN_DB` em outro. O efeito invisível era nos testes: o conftest aponta `JFN_DB` para um banco temporário,
e os coletores que não liam essa variável escreviam no banco de produção.

Precedência (resolvida na CHAMADA, para o conftest valer): argumento explícito > `JFN_DB` >
`JFN_DATA_DIR/compliance.db` > `<repo>/data/compliance.db`. Em produção as três últimas são o mesmo
arquivo (os serviços exportam `JFN_DATA_DIR=%h/JFN/data`; o cron roda de `~/JFN`).
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def dir_dados() -> Path:
    return Path(os.environ.get("JFN_DATA_DIR") or REPO / "data")


def caminho_db(db: str | Path | None = None) -> Path:
    return Path(db or os.environ.get("JFN_DB") or dir_dados() / "compliance.db")


def abrir_banco(db: str | Path | None = None, timeout: float = 60) -> sqlite3.Connection:
    """Conexão de ESCRITA que espera o lock. Sem `timeout` o sqlite desiste em 5 s — e o banco tem vários
    escritores concorrentes (sweep SEI, SIAFE, propagação): medido em 2026-08-09, uma recoleta morreu com
    `database is locked` depois de 18 fatias colhidas (`tests/test_escritores_esperam_o_lock.py`)."""
    return sqlite3.connect(str(caminho_db(db)), timeout=timeout)


def gravar_atomico(destino: str | Path, conteudo: str | bytes, encoding: str = "utf-8") -> None:
    """Grava num temporário ao lado e troca com `os.replace`: quem lê (outro processo, ou a próxima rodada
    que usa o arquivo como cache) vê o arquivo velho inteiro ou o novo inteiro — nunca a metade de um
    download interrompido, que o cache depois reaproveitaria como se fosse o dado."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    # nome único por chamada: duas threads do mesmo processo (rotas no threadpool) gravando o mesmo cache
    # não podem dividir o temporário
    fd, nome = tempfile.mkstemp(prefix=f".{destino.name}.", suffix=".tmp", dir=destino.parent)
    tmp = Path(nome)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(conteudo if isinstance(conteudo, bytes) else conteudo.encode(encoding))
        os.chmod(tmp, 0o644)   # mkstemp cria 0600; o arquivo de antes nascia com o umask (0644)
        os.replace(tmp, destino)
    finally:
        tmp.unlink(missing_ok=True)
