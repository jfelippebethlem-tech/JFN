# -*- coding: utf-8 -*-
"""Lock de coleta — serializa escritores do compliance.db (fim do 'database is locked').

POR QUE existe: os coletores (emendas, favorecidos, PNCP, ContasRio) escrevem no
MESMO SQLite; rodar 2 em paralelo dá OperationalError. Em vez de confiar só no
busy_timeout, um flock exclusivo garante 1 escritor por vez, VM-safe. Uso:

    from compliance_agent.coleta_lock import coleta_lock
    with coleta_lock():          # bloqueia até liberar (ou estoura no timeout)
        ...coleta...
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import time
from pathlib import Path

_LOCK = Path(__file__).resolve().parent.parent / "data" / ".coleta.lock"


@contextlib.contextmanager
def coleta_lock(timeout_s: int = 0, espera_intervalo: float = 5.0):
    """Adquire o lock exclusivo de coleta. timeout_s=0 → espera indefinida.
    Grava o PID no arquivo p/ diagnosticar quem segura."""
    _LOCK.parent.mkdir(parents=True, exist_ok=True)
    fh = open(_LOCK, "w")
    inicio = time.time()
    while True:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if timeout_s and (time.time() - inicio) > timeout_s:
                fh.close()
                raise TimeoutError(f"coleta_lock ocupado há >{timeout_s}s (ver {_LOCK})")
            time.sleep(espera_intervalo)
    try:
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        yield
    finally:
        with contextlib.suppress(Exception):
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()
