#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wal_keeper — impede que QUALQUER processo apague `compliance.db-wal`/`-shm`.

O DEFEITO QUE ISTO FECHA (medido, não estimado — 2026-09-09):
O SQLite apaga `-wal` e `-shm` quando a ÚLTIMA conexão fecha, e decide "última" tentando um
lock EXCLUSIVO no arquivo do banco. Os crons e sweeps da casa usam `sqlite3` da stdlib, que
não expõe `SQLITE_FCNTL_PERSIST_WAL`; então qualquer um deles, ao fechar por último, apaga os
dois arquivos. O `jfn.service` (pool de conexões longas) fica com o mapeamento do `-shm`
APAGADO; o próximo processo recria um `-shm` novo e os dois passam a escrever sem exclusão
mútua — o lock do WAL vive dentro do `-shm`, e cada um está trancando um arquivo diferente.

Foi assim que o banco corrompeu DUAS vezes num mês (12/08: 24.660 OBs ilegíveis; 29/08:
`pcrj_contratos` com rowid fora de ordem e 70 linhas fora do índice), e o guardião reiniciava
o serviço de 3 a 8 vezes por dia pelo sintoma ("-shm morto"). Ver
[[compliance-db-malformed-e-restart]] e `compliance_agent/database/guarda_wal.py`, cuja
bandeira só cobre o caso de o PRÓPRIO servidor fechar por último.

A CURA: um lock COMPARTILHADO (F_RDLCK) na faixa de bytes que o SQLite usa como SHARED lock
(`PENDING_BYTE = 0x40000000`, `SHARED_FIRST = +2`, `SHARED_SIZE = 510`), segurado por este
processo, que não é o SQLite de ninguém. Lock compartilhado é compatível com todo leitor e,
em modo WAL, com todo escritor (escritor WAL tranca no `-shm`, não no arquivo do banco); só o
lock EXCLUSIVO — o do apagamento no fechamento e o de `journal_mode=DELETE` — passa a falhar.
Medido antes de virar serviço: sem o keeper, `wal=False shm=False` após o último `close()`;
com ele, `wal=True shm=True`, leitura OK, escrita OK, `wal_checkpoint(TRUNCATE)` OK.

Se o arquivo do banco for TROCADO (reconstrução em arquivo novo, `os.replace`), o inode muda e
o lock antigo protege um fantasma: o laço abaixo compara inodes e re-tranca o arquivo novo.
"""
from __future__ import annotations

import fcntl
import os
import sys
import time

PENDING_BYTE = 0x40000000
SHARED_FIRST = PENDING_BYTE + 2
SHARED_SIZE = 510


def _trancar(caminho: str) -> tuple[int, int]:
    fd = os.open(caminho, os.O_RDONLY)
    fcntl.lockf(fd, fcntl.LOCK_SH, SHARED_SIZE, SHARED_FIRST, 0)
    return fd, os.fstat(fd).st_ino


def main() -> int:
    caminho = sys.argv[1] if len(sys.argv) > 1 else "data/compliance.db"
    intervalo = float(os.environ.get("JFN_WAL_KEEPER_INTERVALO_S", "15"))
    fd, ino = _trancar(caminho)
    print(f"[wal-keeper] lock compartilhado em {caminho} (inode {ino})", flush=True)
    while True:
        time.sleep(intervalo)
        try:
            atual = os.stat(caminho).st_ino
        except FileNotFoundError:
            print("[wal-keeper] arquivo sumiu; mantenho o lock antigo e espero voltar", flush=True)
            continue
        if atual != ino:
            os.close(fd)
            fd, ino = _trancar(caminho)
            print(f"[wal-keeper] banco trocado — re-tranquei (inode {ino})", flush=True)


if __name__ == "__main__":
    sys.exit(main())
