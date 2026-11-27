#!/usr/bin/env bash
# REGRA (dono, 27/11/2026): «deixar os Claudes atualizados tem que ser regra em todas as máquinas». O executável do
# Claude Code se atualiza sozinho, mas o PROCESSO segue na versão velha (exe «(deleted)») até reiniciar. Esta rotina
# (E17, a cada 15 min) reinicia o que está DESATUALIZADO e OCIOSO, e retoma:
#   · remote-control (laço ~/bin/claude-rc): encerra só se não tem sessão filha aberta; o laço religa em 15 s.
#   · sessão interativa no tmux (`claude --resume <id>`): ociosa = transcrição parada há OCIOSO_MIN, nenhuma tarefa em
#     2º plano (shell filho vivo) e a tela sem «esc to interrupt». Então /exit, religa com `--resume <mesmo id>` (o
#     contexto volta) e manda o aviso para retomar pela RETOMADA.
#   · sessão filha do remote-control (`--print --sdk-url`): não mexe (é do celular; termina sozinha).
# Uso: tools/claude_atualizar_sessoes.sh [--simular]   Saída: `claude_sessoes: {json}`
set -u
SIM=0; [ "${1:-}" = "--simular" ] && SIM=1
OCIOSO_MIN="${CLAUDE_OCIOSO_MIN:-30}"
AVISO="Sessão reiniciada automaticamente para atualizar o Claude Code (regra do dono: Claudes sempre atualizados). Retome de onde parou: leia ~/vault/RETOMADA.md e continue as tarefas e o objetivo que estavam em andamento."
acoes=(); esperando=()
# o EXECUTÁVEL também tem de estar no último (na VM-2 a instalação é por npm e não se atualiza sozinha): a cada 6 h
CARIMBO="$HOME/.claude/.jfn_claude_update"
if [ $SIM = 0 ] && [ -z "$(find "$CARIMBO" -mmin -360 2>/dev/null)" ]; then
  timeout 600 claude update >/dev/null 2>&1 && acoes+=("executavel:atualizado_ou_ja_no_ultimo"); touch "$CARIMBO"
fi
eh_claude(){ case "$(basename "$(readlink "/proc/$1/exe" 2>/dev/null)")" in claude*) return 0;; esac; return 1; }
desatualizado(){ readlink "/proc/$1/exe" 2>/dev/null | grep -q "(deleted)"; }
cmd_de(){ tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null; }
descendentes(){ local f; for f in $(pgrep -P "$1"); do echo "$f"; descendentes "$f"; done; }
tem_tarefa(){ local d c; for d in $(descendentes "$1"); do c=$(cat "/proc/$d/comm" 2>/dev/null); case "$c" in bash|sh|zsh|timeout) return 0;; esac; done; return 1; }
painel_de(){ local p=$1 a; while [ -n "$p" ] && [ "$p" != 1 ]; do a=$(tmux list-panes -a -F "#{pane_pid} #{pane_id}" 2>/dev/null | awk -v x="$p" '$1==x{print $2}'); [ -n "$a" ] && { echo "$a"; return; }; p=$(ps -o ppid= -p "$p" | xargs); done; }
# a sessão RETOMADA grava num arquivo NOVO (outro id) que carrega a cadeia — o id a retomar é a transcrição mais nova
# entre a de lançamento e as que a mencionam (27/11: retomar o id de lançamento voltaria à conversa de dias atrás)
id_atual(){ local id=$1 f melhor="" t=0 m; for f in "$HOME"/.claude/projects/*/"$id".jsonl $(grep -l -- "$id" "$HOME"/.claude/projects/*/*.jsonl 2>/dev/null); do
  [ -f "$f" ] || continue; m=$(stat -c %Y "$f"); [ "$m" -gt "$t" ] && { t=$m; melhor=$(basename "$f" .jsonl); }; done; echo "$melhor"; }
log(){ if [ $SIM = 1 ]; then echo "SIMULAR: $*" >&2; fi; }

for p in $(pgrep -u "$(id -u)" -f "claude"); do
  eh_claude "$p" || continue
  desatualizado "$p" || continue
  c=$(cmd_de "$p")
  case "$c" in
    *"--print"*"--sdk-url"*) continue ;;                                           # filha do remote-control
    *"remote-control"*)
      filhas=$(for d in $(descendentes "$p"); do eh_claude "$d" && echo "$d"; done)
      if [ -n "$filhas" ]; then
        # sessão do celular parada: nenhuma transcrição da máquina mudou em FILHA_OCIOSA_MIN → encerra a parte LOCAL
        # (a sessão fica na nuvem e se retoma pelo app); o daemon reinicia na rodada seguinte, já atualizado
        recente=$(find "$HOME"/.claude/projects -name '*.jsonl' -mmin -"${FILHA_OCIOSA_MIN:-120}" 2>/dev/null | head -1)
        if [ -z "$recente" ]; then
          log "kill filhas $filhas (sessão do celular parada há ≥ ${FILHA_OCIOSA_MIN:-120} min)"
          [ $SIM = 0 ] && kill $filhas; acoes+=("rc:$p:filha_ociosa_encerrada")
        else esperando+=("rc:$p:sessao_filha_ativa"); fi
        continue
      fi
      log "kill $p (remote-control desatualizado, sem sessão filha; o laço religa)"
      [ $SIM = 0 ] && kill "$p"; acoes+=("rc:$p:reiniciado") ;;
    *"--resume "*)
      lanc=$(echo "$c" | grep -oE -- "--resume [0-9a-f-]{36}" | awk '{print $2}')
      id=$(id_atual "$lanc"); pane=$(painel_de "$p")
      [ -z "$pane" ] || [ -z "$id" ] && { esperando+=("sessao:$p:sem_painel_ou_transcricao"); continue; }
      # ociosidade pela ATIVIDADE do painel (a tela redesenha enquanto trabalha), não pelo arquivo
      idade=$(( ( $(date +%s) - $(tmux display-message -p -t "$pane" "#{window_activity}") ) / 60 ))
      if [ "$idade" -lt "$OCIOSO_MIN" ]; then esperando+=("sessao:${id:0:8}:ativa_ha_${idade}min"); continue; fi
      if tem_tarefa "$p"; then esperando+=("sessao:${id:0:8}:tarefa_em_2o_plano"); continue; fi
      if tmux capture-pane -p -t "$pane" 2>/dev/null | tail -5 | grep -qi "esc to interrupt"; then
        esperando+=("sessao:${id:0:8}:trabalhando_na_tela"); continue; fi
      flags=$(echo "$c" | sed -E 's/^.*--resume [0-9a-f-]{36}//')
      log "tmux $pane: /exit; claude --resume $id$flags; aviso de retomada"
      if [ $SIM = 0 ]; then
        sessao=$(tmux display-message -p -t "$pane" "#{session_name}")
        tmux send-keys -t "$pane" "/exit" Enter
        for _ in $(seq 1 30); do kill -0 "$p" 2>/dev/null || break; sleep 2; done
        kill -0 "$p" 2>/dev/null && kill "$p"
        sleep 2
        if tmux list-panes -a -F "#{pane_id}" | grep -qx "$pane"; then
          tmux respawn-pane -k -t "$pane" "claude --resume $id$flags"
        else
          pane=$(tmux new-window -d -P -F "#{pane_id}" -t "$sessao" -c "$HOME" "claude --resume $id$flags")
        fi
        sleep 25
        tmux send-keys -t "$pane" "$AVISO" Enter
      fi
      acoes+=("sessao:${id:0:8}:reiniciada") ;;
    *) esperando+=("outro:$p:sem_regra") ;;
  esac
done
j(){ printf '%s\n' "$@" | python3 -c 'import json,sys; print(json.dumps([l.strip() for l in sys.stdin if l.strip()], ensure_ascii=False))'; }
echo "claude_sessoes: {\"no\": \"$(hostname)\", \"simular\": $SIM, \"versao_instalada\": \"$(claude --version 2>/dev/null | awk '{print $1}')\", \"acoes\": $(j "${acoes[@]:-}"), \"esperando\": $(j "${esperando[@]:-}")}"
