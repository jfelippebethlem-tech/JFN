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
. tools/lib/systemd_user_env.sh
LOG=data/guardiao_db_malformed.log
exec 9>/tmp/guardiao_db_malformed.lock
flock -n 9 || exit 0

# ── SONDA PROATIVA DE INTEGRIDADE (2026-08-12) ─────────────────────────────────────────────────
# POR QUE ISTO ENTROU. Este vigia era só REATIVO: checava o arquivo apenas quando UMA das rotas
# abaixo devolvia "malformed". Em 11-12/08 o banco corrompeu de verdade e o vigia NÃO VIU — a
# tabela atingida (`ordens_bancarias`) não é tocada por nenhuma das três sondas, e a corrupção
# viveu ~13 horas invisível, apagando 19 achados fiscais pelo caminho (processos reavaliados com
# dado quebrado saem com MENOS achado, e um de risco EXTREMO foi a score 0).
#
# `quick_check(1)` custa 10,6 s numa base de 3,4 GB — barato de hora em hora, caro a cada 5 min.
# O carimbo controla a cadência; o vigia continua rodando a cada 5 min para o caso reativo.
SONDA_S=${JFN_GUARDIAO_SONDA_S:-3600}
STAMP=data/.guardiao_integridade.stamp
AGORA=$(date +%s)
ULT=$(cat "$STAMP" 2>/dev/null || echo 0)
if [ $((AGORA - ULT)) -ge "$SONDA_S" ]; then
  q=$(ionice -c3 nice -n19 .venv/bin/python -c "
import sqlite3
try:
    c = sqlite3.connect('file:data/compliance.db?mode=ro', uri=True, timeout=120)
    print(c.execute('PRAGMA quick_check(1)').fetchone()[0]); c.close()
except Exception as e:
    print('ERRO:%s' % e)
" 2>/dev/null)
  echo "$AGORA" > "$STAMP"
  if [ "$q" != "ok" ]; then
    # ALERTA UMA VEZ POR INCIDENTE. Avisar a cada 5 minutos seria trocar um silêncio por um
    # dilúvio — e o dono já pagou o preço do dilúvio de e-mail do CI.
    if [ ! -f data/.guardiao_corrompido.alertado ]; then
      date -Is > data/.guardiao_corrompido.alertado
      echo "$(date -Is) 🔴 SONDA: quick_check=$q — corrupção REAL detectada pela sonda proativa" >> "$LOG"
      PYTHONPATH=. .venv/bin/python -c "
from tools.ronda import notificar
notificar('🔴 <b>compliance.db CORROMPIDO</b> — a sonda de integridade do guardião falhou.\n'
          'NÃO é o caso do -shm morto (ali quick_check volta ok). Perícia de dado, não restart:\n'
          '<code>python -m tools.reconstruir_db --saida /tmp/novo.db --laudo /tmp/laudo.json</code>\n'
          'Avaliações feitas a partir de agora podem sair com MENOS achado — foi o que aconteceu em 12/08.')" 2>/dev/null
    fi
    exit 1
  fi
  # voltou ao normal: limpa a marca para que um próximo incidente volte a avisar
  rm -f data/.guardiao_corrompido.alertado
fi

ROTAS=("comparador/economia" "intel/sancionadas?limite=1" "pericias?limite=1" "ugs")
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
if ! erro=$(systemctl --user restart jfn.service 2>&1); then
  echo "$(date -Is) 🔴 systemctl NÃO executou o restart: ${erro:-sem mensagem} — vigia impotente, não é o banco" >> "$LOG"
  exit 1
fi
for _ in $(seq 1 30); do
  curl -s -o /dev/null -m 2 http://127.0.0.1:8000/api/compliance/painel && break
  sleep 2
done
if curl -s -m 25 "http://127.0.0.1:8000/api/$doente" | grep -q "disk image is malformed"; then
  echo "$(date -Is) 🔴 AINDA malformed após restart — escalar (não insisto)" >> "$LOG"
else
  echo "$(date -Is) ✓ curado" >> "$LOG"
fi
