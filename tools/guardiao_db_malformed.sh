#!/bin/bash
# Vigia do "database disk image is malformed" nas rotas do painel.
#
# CAUSA-RAIZ (2026-07-23, diagnosticada com fd do processo): o SQLite cacheia o
# WAL-index (-shm) POR PROCESSO, indexado pelo inode do banco. Quando um gravador
# noturno/manutenção recria -wal/-shm enquanto o jfn.service tem conexões longas
# abertas (pool), o processo inteiro fica preso à memória compartilhada DELETADA:
# até conexão NOVA falha dentro dele, embora o arquivo esteja íntegro e um processo
# novo leia normalmente. Sintoma no site: "Economia potencial: database disk image
# is malformed". Cura = reiniciar o serviço (conexões novas, -shm novo).
#
# SALVAGUARDA: só reinicia se o ARQUIVO estiver ÍNTEGRO (quick_check=ok). Se o banco
# estiver de fato corrompido, NÃO entra em loop de restart — grita no log e para,
# porque aí o problema é de dado, não de processo (indício ≠ diagnóstico).
set -u
cd /home/ubuntu/JFN || exit 1
LOG=data/guardiao_db_malformed.log
exec 9>/tmp/guardiao_db_malformed.lock
flock -n 9 || exit 0

ROTAS=("comparador/economia" "intel/sancionadas?limite=1" "pericias?limite=1")
doente=""
for r in "${ROTAS[@]}"; do
  if curl -s -m 25 "http://127.0.0.1:8000/api/$r" | grep -q "disk image is malformed"; then
    doente="$r"; break
  fi
done
[ -z "$doente" ] && exit 0

integro=$(.venv/bin/python -c "
import sqlite3
try:
    c = sqlite3.connect('file:data/compliance.db?mode=ro', uri=True)
    print(c.execute('PRAGMA quick_check(1)').fetchone()[0]); c.close()
except Exception as e:
    print('ERRO:%s' % e)
" 2>/dev/null)

if [ "$integro" != "ok" ]; then
  echo "$(date -Is) 🔴 ARQUIVO CORROMPIDO de verdade (quick_check=$integro) — NÃO reinicio; exige perícia humana" >> "$LOG"
  exit 1
fi

echo "$(date -Is) ⚠️ malformed em /$doente com arquivo ÍNTEGRO = -shm morto no processo; reiniciando jfn.service" >> "$LOG"
systemctl --user restart jfn.service
for _ in $(seq 1 30); do
  curl -s -o /dev/null -m 2 http://127.0.0.1:8000/api/compliance/painel && break
  sleep 2
done
if curl -s -m 25 "http://127.0.0.1:8000/api/$doente" | grep -q "disk image is malformed"; then
  echo "$(date -Is) 🔴 AINDA malformed após restart — escalar (não insisto)" >> "$LOG"
else
  echo "$(date -Is) ✓ curado" >> "$LOG"
fi
