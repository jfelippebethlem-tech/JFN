#!/usr/bin/env bash
# oom_guard.sh — faz o sweep ser a PRIMEIRA vítima do OOM killer, protegendo a sessão do dono.
#
# POR QUE EXISTE. Em 27/07/2026 a VM travou às 22:22 e, ao longo do dia, o OOM killer disparou 11
# vezes. O sintoma que o dono via não era "o sweep morreu" — era **o Claude e o tmux fechando
# sozinhos**: sob pressão de memória a máquina congela e derruba tudo junto, e o kernel pode
# escolher como vítima justamente o processo interativo (o Claude chega a 570 MB de RSS).
#
# O QUE FAZ. `oom_score_adj = 1000` é o valor máximo: o kernel mata este processo (e seus filhos,
# que herdam o valor) ANTES de qualquer outro. Um sweep de background morrendo é irrelevante — o
# cron repete em 30 min. A sessão do dono morrendo custa o trabalho em andamento.
#
# LIMITE HONESTO: isto NÃO impede o vazamento nem baixa o consumo. É rede de segurança, não
# conserto. O conserto de cada passo guloso é feito no código (ver `tools/sei_pais.iter_resumos`).
# Também não protege contra congelamento por thrashing de swap antes de o killer agir.
#
# ELEVAR oom_score_adj não exige root (baixar exigiria). Falha silenciosa é aceitável aqui: se o
# kernel recusar, o sweep segue normalmente, só sem a proteção.
#
# USO (primeira linha executável do script de sweep):
#     source "$(dirname "$0")/lib/oom_guard.sh"

echo 1000 > /proc/self/oom_score_adj 2>/dev/null || true
