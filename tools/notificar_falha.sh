#!/bin/bash
# notificar_falha — handler genérico do OnFailure= das unidades systemd do ecossistema.
# Uso: notificar_falha.sh <unidade>  (o template notificar-falha@.service passa %i)
#
# POR QUE ELE DIZ MAIS DO QUE "FALHOU". Com `Restart=always` + `RestartSec=5`, a unidade quase
# sempre JÁ VOLTOU quando a mensagem chega ao dono — e um alerta vermelho sem esse contexto manda
# alguém correr para um problema que se resolveu sozinho. Medido em 2026-08-18: o `jfn.service`
# morreu com SIGBUS (7/BUS), reiniciou em 5 s e serviu SIAFE normalmente; o dono recebeu só o
# "FALHOU" e foi investigar um serviço que estava de pé.
#
# Agora a mensagem carrega: estado ATUAL, há quanto tempo, quantos reinícios acumulados e a última
# linha de erro do journal. Diagnóstico na notificação, não no comando que o dono teria de rodar.
set -u
cd /home/ubuntu/JFN || exit 1
set -a; . .env; set +a

UNIT="${1:-desconhecida}"
# Um instante para o Restart= agir — senão o estado lido é o do instante da morte, não o de agora.
sleep 6

ESTADO="$(systemctl --user is-active "$UNIT" 2>/dev/null || true)"
DESDE="$(systemctl --user show "$UNIT" -p ActiveEnterTimestamp --value 2>/dev/null | cut -c1-25)"
NREST="$(systemctl --user show "$UNIT" -p NRestarts --value 2>/dev/null || echo '?')"
MOTIVO="$(journalctl --user -u "$UNIT" -n 40 --no-pager 2>/dev/null \
          | grep -iE 'exited, code=|Failed with result|Traceback|Error|status=' | tail -2 | cut -c1-190)"

UNIT="$UNIT" ESTADO="$ESTADO" DESDE="$DESDE" NREST="$NREST" MOTIVO="$MOTIVO" \
PYTHONPATH=. exec .venv/bin/python - <<'PY'
import os
from tools.ronda import notificar

u = os.environ.get("UNIT", "desconhecida")
estado = (os.environ.get("ESTADO") or "?").strip()
desde = (os.environ.get("DESDE") or "").strip()
nrest = (os.environ.get("NREST") or "?").strip()
motivo = (os.environ.get("MOTIVO") or "").strip()

if estado == "active":
    cab = (f"🟡 <b>systemd</b>: <b>{u}</b> caiu e <b>JÁ VOLTOU</b> sozinha"
           f"{f' (de pé desde {desde})' if desde else ''}.")
    acao = "Nada a fazer agora — mas reinício repetido merece olhar a causa."
else:
    cab = f"🔴 <b>systemd</b>: <b>{u}</b> FALHOU e está <b>{estado or 'inativa'}</b>."
    acao = f"Precisa de ação: <code>journalctl --user -u {u} -n 30</code>"

partes = [cab, f"reinícios acumulados: <b>{nrest}</b>"]
if motivo:
    partes.append("último erro no journal:\n<code>" + motivo.replace("<", "&lt;")[:400] + "</code>")
partes.append(acao)
notificar("\n\n".join(partes))
PY
