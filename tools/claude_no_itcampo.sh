#!/bin/bash
# Binário do motor Claude (JFN_CLAUDE_BIN) que RODA o CLI no Windows do it-campo — dono 22/11/2026 00h: "pode levar
# pro it-campo o que precisar de Claude de lá também". Só muda ONDE o processo roda: o motor da VM-1
# (compliance_agent/llm/claude_motor.pensar) já conferiu o ritmo semanal, reservou no orçamento diário, segurou a
# trava e vai registrar o uso — nada disso passa por aqui, e a conta é a mesma (nunca gasto em dobro).
# O shell do ssh no it-campo é o PowerShell. Argumentos e prompt vão num JSON pela entrada padrão (sem aspas atravessando ssh/cmd.exe); o receptor é
# deploy/itcampo/claude/claude_remoto.py (C:\JFN-Nativo\claude_remoto.py, sincronizado com md5 pelo vigia).
# it-campo fora do ar (ssh não conecta em 8 s) ou receptor ausente → roda o CLI LOCAL, como antes.
# Desligar: tirar a linha JFN_CLAUDE_BIN do crontab (volta o CLI local) ou criar data/.claude_local.
set -u
J=/home/ubuntu/JFN
LOCAL=/home/ubuntu/.npm-global/bin/claude
PY='C:\JFN-Nativo\venv\Scripts\python.exe'
REC='C:\JFN-Nativo\claude_remoto.py'
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=8 -o ServerAliveInterval=30 -o ServerAliveCountMax=4 it-campo)
if [ -e "$J/data/.claude_local" ] || ! timeout 20 "${SSH[@]}" "if (Test-Path '$REC') { exit 0 } else { exit 3 }" </dev/null >/dev/null 2>&1; then
  exec "$LOCAL" "$@"
fi
"$J/.venv/bin/python" -c '
import json, sys
sys.stdout.buffer.write(json.dumps({"args": sys.argv[1:], "entrada": sys.stdin.buffer.read().decode("utf-8")}).encode("utf-8"))
' "$@" | "${SSH[@]}" "& '$PY' '$REC'"
