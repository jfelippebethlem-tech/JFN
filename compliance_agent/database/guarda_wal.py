# -*- coding: utf-8 -*-
"""Uma conexão viva pelo tempo de vida do processo, para o WAL-index não sumir embaixo dele.

POR QUE ESTE MÓDULO EXISTE. O painel devolvia HTTP 500 em seis rotas da capa com
`database disk image is malformed` — e o ARQUIVO íntegro (`quick_check: ok`). Acontecia 7 a 14
vezes por dia; o `guardiao_db_malformed.sh` curava reiniciando o serviço, o que derruba junto a
sessão de browser e o login SIAFE. Reiniciar é sintoma; a causa foi medida em 31/07/2026 com um
vigia que registrava o inode dos três arquivos e os descritores abertos do `jfn.service`:

    16:14:31   fds=0                            <- o servidor chegou a ZERO conexões
    16:17:42   wal=AUSENTE  shm=AUSENTE  fds=0  <- os arquivos foram APAGADOS
    16:18:02   wal=2345988  shm=2346076  fds=0  <- recriados

O SQLite desvincula `-wal` e `-shm` quando a ÚLTIMA conexão do banco fecha. `get_engine()` cria um
engine NOVO a cada chamada (pool novo, descartado depois), então numa janela ociosa o servidor fica
sem nenhuma conexão; outro processo fecha por último e leva os arquivos embora. O processo longo
mantém o WAL-index mapeado por inode e, a partir daí, até conexão NOVA dentro dele falha — enquanto
um processo novo lê o mesmo arquivo sem problema. Daí o sintoma enganoso.

Com uma conexão sempre aberta, a condição "última conexão fechou" nunca ocorre e a desvinculação
não acontece. Custa um descritor.

CUIDADO QUE NÃO É ÓBVIO: ela precisa ser uma LEITORA que não segura lock de escrita, senão trocaria
um defeito por "database is locked" nos sweeps. Por isso só faz um `SELECT` trivial e fica parada.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_CONEXAO: sqlite3.Connection | None = None


def segurar(db_path) -> bool:
    """Abre (uma vez) a conexão guardiã. `True` se há guardiã viva ao final."""
    global _CONEXAO
    if _CONEXAO is not None:
        return True
    caminho = Path(db_path)
    if not caminho.exists():
        logger.info("guarda_wal: %s não existe — servidor sobe sem guardiã", caminho.name)
        return False
    try:
        con = sqlite3.connect(str(caminho), timeout=30, check_same_thread=False)
        # força o WAL-index a existir e a ficar mapeado neste processo; sem tocar em escrita.
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("SELECT 1").fetchone()
    except sqlite3.Error as exc:
        logger.warning("guarda_wal: não consegui segurar %s (%s) — o painel volta a depender do "
                       "guardião de restart", caminho.name, exc)
        return False
    _CONEXAO = con
    logger.info("guarda_wal: conexão viva em %s — -wal/-shm não serão desvinculados", caminho.name)
    return True


def soltar() -> None:
    """Fecha a guardiã (usado nos testes e no desligamento)."""
    global _CONEXAO
    if _CONEXAO is not None:
        try:
            _CONEXAO.close()
        except sqlite3.Error:
            pass
        _CONEXAO = None


def vivo() -> bool:
    return _CONEXAO is not None
