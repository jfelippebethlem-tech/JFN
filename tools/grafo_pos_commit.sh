#!/usr/bin/env bash
# grafo_pos_commit.sh — manutenção dos grafos de navegação DEPOIS do commit, fora do caminho dele (O2.5, Esteira Única).
#
# POR QUE EXISTE. Medido em 24/11 (VM-1, load 7): `graphify update` leva 410 s e 2,7 GB de RAM, e o pre-commit o rodava
# SÍNCRONO sempre que o load de 1 min estava ≤ 4 no início do hook — com várias frentes commitando, o load oscila em
# torno de 4 e o commit levava >6 min. Compressão do snapshot do dia anterior (`zstd -19` de 54 MB): mais 98 s. Nenhum
# dos dois é CHECAGEM (não bloqueiam nada); são manutenção do índice que o graphify/agentes consultam.
#
# O QUE FAZ, lançado em 2º plano pelo post-commit (com JFN_PORTAO_V2=1 — ver tools/pre_commit_v2.sh):
#   1. graphify update no it-campo (24 fios, 19 GB): o código vem do COMMIT (espelho git do portão, ~/JFN-portao.git),
#      o graphify-out/ vai e volta por rsync. Sem o it-campo: na VM-1, nice/ionice, só com load < 4 (o mesmo critério
#      do hook antigo), senão fica para o próximo commit — dito no log, nunca calado.
#   2. a compressão dos snapshots antigos (tools/graphify_snapshots_comprimir.sh), com nice/ionice.
#   3. codegraph sync, se instalado (hoje não está na VM-1: `command -v` falha).
# Um por vez: commit que chega com outro rodando só marca "pendente" e o que roda faz mais uma volta (coalesce).
#
#   bash tools/grafo_pos_commit.sh            # o post-commit chama assim, com setsid/nohup
set -u
RAIZ="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
COMUM="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"     # graphify-out vive no checkout principal
LOG=/tmp/jfn-grafo-pos-commit.log
TRAVA=/tmp/jfn-grafo-pos-commit.lock
PENDENTE=/tmp/jfn-grafo-pos-commit.pendente
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"
exec 7>"$TRAVA"
if ! flock -n 7; then : > "$PENDENTE"; exit 0; fi
exec >>"$LOG" 2>&1

remoto() {   # graphify update no it-campo; 0 = feito
  local ref sha
  ref="$(git -C "$RAIZ" symbolic-ref -q HEAD)" || { echo "HEAD destacado — sem ref para o it-campo buscar"; return 1; }
  sha="$(git -C "$RAIZ" rev-parse HEAD)"
  timeout 1800 ssh -o BatchMode=yes -o ConnectTimeout=10 it-campo 'wsl -d Ubuntu bash -s' <<EOF
set -e
export PATH=\$HOME/.local/bin:\$PATH
command -v graphify >/dev/null || { echo "graphify ausente no it-campo (uv tool install graphifyy==0.9.101)"; exit 2; }
M=\$HOME/JFN-portao.git; D=\$HOME/jfn-graphify/arvore
[ -d \$M ] || git init -q --bare \$M
( flock -w 900 8; git --git-dir=\$M fetch -q --depth=1 ssh://vm1-ts$COMUM $ref
  git --git-dir=\$M cat-file -e $sha^{commit}
  [ -d \$D ] || git --git-dir=\$M worktree add -q --detach -f \$D $sha
  git -C \$D checkout -q --detach -f $sha ) 8>\$M/.portao.lock
rsync -a --delete vm1-ts:$COMUM/graphify-out/ \$D/graphify-out/
nice -n 10 graphify update \$D >/tmp/jfn-graphify-update.log 2>&1 \
  || grep -q "Refusing to overwrite" /tmp/jfn-graphify-update.log || { tail -5 /tmp/jfn-graphify-update.log; exit 3; }
rsync -a \$D/graphify-out/ vm1-ts:$COMUM/graphify-out/
echo "graphify no it-campo ok ($sha)"
EOF
}

while :; do
  rm -f "$PENDENTE"
  echo "=== $(date '+%F %T') $(git -C "$RAIZ" rev-parse --short HEAD)"
  if ! remoto; then
    carga=$(cut -d' ' -f1 /proc/loadavg)
    if awk -v l="$carga" 'BEGIN{exit !(l < 4)}' && command -v graphify >/dev/null; then
      echo "it-campo não fez — graphify local (load $carga)"
      out="$(nice -n 19 ionice -c3 graphify update "$COMUM" 2>&1)" \
        || printf '%s' "$out" | grep -q "Refusing to overwrite" || echo "graphify update local falhou: ${out: -300}"
    else
      echo "it-campo não fez e load $carga ≥ 4 — graphify ADIADO para o próximo commit"
    fi
  fi
  [ -x "$COMUM/tools/graphify_snapshots_comprimir.sh" ] && nice -n 19 ionice -c3 bash "$COMUM/tools/graphify_snapshots_comprimir.sh" "$COMUM"
  command -v codegraph >/dev/null && nice -n 19 codegraph sync -q "$COMUM"
  [ -e "$PENDENTE" ] || break
done
exit 0
