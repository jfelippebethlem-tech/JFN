#!/usr/bin/env bash
# Guard de ambiente para falar com o systemd --user fora de uma sessão de login.
#
# O cron entrega só HOME/LOGNAME/PATH/SHELL. Sem XDG_RUNTIME_DIR e
# DBUS_SESSION_BUS_ADDRESS, `systemctl --user` morre com "Failed to connect to
# bus: No medium found" — e morre calado dentro de script sem `set -e`.
#
# Sourceie no topo de qualquer script de cron que mexa em serviço de usuário:
#   . "$(dirname "$0")/lib/systemd_user_env.sh"
: "${XDG_RUNTIME_DIR:=/run/user/$(id -u)}"
: "${DBUS_SESSION_BUS_ADDRESS:=unix:path=${XDG_RUNTIME_DIR}/bus}"
export XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS
