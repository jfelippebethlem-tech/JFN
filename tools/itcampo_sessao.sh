#!/bin/bash
# UMA sessão SEI do it-campo, numa JANELA VISÍVEL do Windows (pedido do dono, 14/11/2026: "quero ver na tela do it
# campo sempre o que estiver acontecendo. nada de janelas ocultas"). Lançada pelo orquestrador
# (tools/itcampo_sei_paralelo.py) com `cmd.exe /c start "<título>" wsl.exe --cd <worktree da sessão> -- bash …`.
#
#   uso: itcampo_sessao.sh <k> <N> <segundos de orçamento>
#
# A sessão roda o CÓDIGO DA CASA sem alteração (`sei_integra_fila.py --fila`, que chama `sei_integra_completa.py`
# por processo) no SEU worktree (data/, browser.lock e TMPDIR próprios — sessões não se enxergam), com o navegador
# visível quando há tela (WSLg). No fim mede a rodada (`itcampo_sei_paralelo metricas`) e entrega o LOTE à VM-1
# (`sei_integra_vm2 devolver` → conferência em tools/vm2_conferencia.py, com quarentena). Nunca toca no SIAFE.
set -u
K=${1:?k}; N=${2:?N}; SEG=${3:-1800}
S=$(pwd)
PY="$S/.venv/bin/python"
titulo(){ printf '\033]0;%s\007' "$*"; }
export PYTHONPATH="$S" TMPDIR="$S/tmp" TZ=America/Sao_Paulo SEI_SEM_TG=1
# 24 threads / 15 GB no WSL: o limiar de 1,7 do vm_guard é para a VM-1 de 2 vCPU
export VM_GUARD_MAX_LOAD="${VM_GUARD_MAX_LOAD:-20}" VM_GUARD_MIN_FREE_GB="${VM_GUARD_MIN_FREE_GB:-1.5}"
export JFN_CLAUDE_MAX_CONFERENCIA_VM2=0      # sem Claude Code aqui: a conferência da VM-1 decide sozinha
# Navegador SEM janela por padrão. MEDIDO em 14/11/2026 (A/B no mesmo processo, 270003/004118/2024): com o Chromium
# visível (WSLg) o documento em PDF abre no visualizador embutido e a leitura do frame trava até o teto de 450 s POR
# DOCUMENTO (2 de 44 em 10 min); headless, 16 de 44 em menos de 1 min. A visibilidade fica nesta janela: processo,
# documento a documento, e o título. `JFN_ITCAMPO_HEADED=1` religa o navegador visível (só para olhar, é lento).
[ "${JFN_ITCAMPO_HEADED:-0}" = 1 ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && export SEI_HEADED=1
# navegador da sessão k num lugar FIXO (mosaico 3 colunas na metade direita, janelas pequenas) — instância própria
# do Chromium do Playwright no WSL, perfil temporário em $TMPDIR; nunca o Chrome/perfil do dono
C=$(( (K - 1) % 3 )); L=$(( (K - 1) / 3 % 3 ))
export SEI_CHROMIUM_ARGS="--window-position=$((1100 + C * 480)),$((40 + L * 330)) --window-size=480,330"
mkdir -p "$TMPDIR" data
rm -f data/itcampo_sessao_fim.json
FILA=data/fila_itcampo.json
NF=$("$PY" -c "import json,sys;print(len(json.load(open(sys.argv[1]))))" "$FILA" 2>/dev/null || echo 0)
DESDE=$(stat -c %s data/sei_integra_fila.log 2>/dev/null || echo 0)
titulo "JFN SEI sessão $K/$N — começando ($NF na fila)"
echo "=== JFN SEI — sessão $K de $N — $(date '+%F %T') — $NF processo(s) na fatia, orçamento ${SEG}s ==="
echo "    navegador: $([ "${SEI_HEADED:-}" = 1 ] && echo 'VISÍVEL (WSLg, lento com PDF)' || echo 'sem janela (headless: PDF visível trava 450 s/doc) — o progresso aparece aqui')"
# progresso documento a documento do processo em captura (o stdout da captura fica dentro da fila da casa)
( while sleep 30; do
    T=$(cut -d' ' -f1 data/itcampo_estado.txt 2>/dev/null | tr / _)
    M="data/sei_cache/integra_$T/manifest.json"
    [ -n "$T" ] && [ -f "$M" ] && "$PY" -c "import json,sys,time;d=json.load(open(sys.argv[1]));o=sum(1 for x in d['docs'] if x.get('ok'));print(time.strftime('[%F %T]'),'   ',d['processo'],': documento',len(d['docs']),'de',d['total_arvore'],'(',o,'com teor)')" "$M" 2>/dev/null
  done ) &
PROG=$!
trap 'kill $PROG 2>/dev/null' EXIT
FEITOS=0; ATUAL="-"
timeout -k 120 --foreground $((SEG + 1200)) "$PY" -u tools/sei_integra_fila.py --fila "$FILA" --segundos "$SEG" 2>&1 \
| while IFS= read -r ln; do
    echo "$ln"
    if [[ "$ln" =~ ÍNTEGRA\ ([0-9]{6}/[0-9]{6}/[0-9]{4}) ]]; then
      ATUAL=${BASH_REMATCH[1]}
    elif [[ "$ln" =~ ^\[[^]]+\][[:space:]]+[0-9]{6}/[0-9]{6}/[0-9]{4}:\ [a-z_]+[[:space:]]*$ ]]; then
      FEITOS=$((FEITOS + 1))
    fi
    titulo "JFN SEI sessão $K/$N — processo $ATUAL, $FEITOS feitos"
    echo "$ATUAL $FEITOS" > data/itcampo_estado.txt
  done
RC=${PIPESTATUS[0]}
titulo "JFN SEI sessão $K/$N — medindo e entregando o lote à VM-1"
echo "--- medindo a rodada e entregando o lote à VM-1 (conferência com quarentena) ---"
"$PY" -m tools.itcampo_sei_paralelo metricas --desde "$DESDE" > data/itcampo_metricas.json 2>>data/itcampo_sessao.err
RES=$("$PY" -m tools.sei_integra_vm2 devolver --desde "$DESDE" --fila "$FILA" 2>>data/itcampo_sessao.err)
echo "$RES" > data/itcampo_devolver.json
echo "$RES" | cut -c1-400
printf '{"k": %s, "rc": %s, "fim": "%s"}\n' "$K" "$RC" "$(date '+%F %T')" > data/itcampo_sessao_fim.json
titulo "JFN SEI sessão $K/$N — terminada (rc=$RC); fecha em 20 s"
echo "=== sessão $K/$N terminada (rc=$RC) — esta janela fecha em 20 s ==="
sleep 20
