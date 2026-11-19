#!/bin/bash
# Lado ORIGEM (VM-1) do sqlite3_rsync que a réplica do it-campo chama pelo ssh (--exe). Prioridade baixa: a VM-1 é
# 2 vCPU e só lê páginas/hash. Binário oficial do SQLite 3.54.1 (tool/sqlite3_rsync.c + amalgamação, SHA3 conferidos
# com sqlite.org/download.html), compilado na VM-2 (ARM) — md5 2cbbd261c88202aa541627792549397c.
exec nice -n 15 ionice -c3 "$HOME/bin/sqlite3_rsync" "$@"
