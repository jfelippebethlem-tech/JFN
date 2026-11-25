# portao_no.sh — corpo que roda NO NÓ DE TESTE (VM-2 ou it-campo) a pedido de tools/portao.py (O2.5, Esteira Única).
#
# Não é executado direto: o portao.py manda este texto pelo stdin do ssh (`bash -s`) com um CABEÇALHO de variáveis:
#   SHA      commit a testar (o que o push leva — nunca a árvore de trabalho, que tem WIP de outras frentes)
#   REF      ref temporária que a VM-1 criou apontando para SHA (refs/portao/<run>): o upload-pack só serve objeto
#            anunciado, e o commit de um push pode não ser ponta de branch nenhuma (medido: "unadvertised object")
#   ORIGEM   repositório de onde buscar o commit (ssh://vm1-ts/home/ubuntu/JFN)
#   RUN      id da rodada (diretórios próprios: duas rodadas no mesmo nó não se pisam)
#   PAR      quantos pytest em paralelo neste nó (cada um no SEU worktree: teste que grava em data/ não colide)
#   TESTES   arquivos de teste, separados por espaço
#   TETO     segundos até o nó desistir sozinho (o ssh caído não deixa pytest órfão rodando)
#
# Por que um ESPELHO GIT e não um tar. As catracas medem por `git ls-files`/`git grep --cached`: precisam de
# repositório. O espelho (~/JFN-portao.git, raso) busca SÓ os objetos novos de cada commit — o primeiro fetch traz a
# árvore (~200 MB), os seguintes, o delta. O worktree tirado do espelho é um checkout limpo do commit, com índice.
#
# Contrato de saída (o portao.py lê só estas linhas; o código de saída do ssh pelo `wsl` do it-campo não é confiável):
#   PORTAO_INFRA <motivo>                — o nó não conseguiu medir (fetch, venv, disco): NÃO é falha de teste
#   PORTAO_LOTE <k> rc=<n> <resumo>      — um por lote
#   PORTAO_FALHA <nodeid>                — linhas FAILED/ERROR do pytest
#   PORTAO_LOG <k>| <linha>              — cauda do log de lote que falhou (diagnóstico)
#   PORTAO_FIM rc=<n>                    — último; sem ele a rodada não conta
set -u
infra() { echo "PORTAO_INFRA $*"; exit 90; }
M="$HOME/JFN-portao.git"
VENV="$HOME/JFN-suite-venv"
BASE_RUN="$HOME/JFN-portao-run/$RUN"
command -v git >/dev/null || infra "git ausente"
command -v flock >/dev/null || infra "flock ausente"
mkdir -p "$HOME/JFN-portao-run" || infra "mkdir"
[ -d "$M" ] || git init -q --bare "$M" || infra "git init do espelho"

limpar() {
  for d in "$BASE_RUN"/w*; do [ -d "$d" ] && git --git-dir="$M" worktree remove --force "$d" >/dev/null 2>&1; done
  rm -rf "$BASE_RUN"
  git --git-dir="$M" worktree prune >/dev/null 2>&1
}
trap limpar EXIT

# ── 1. o commit, pelo espelho (um fetch por vez no nó) ─────────────────────────────────────────────────────────────
(
  flock -w 900 8 || { echo "PORTAO_INFRA espelho ocupado por 900 s"; exit 90; }
  if ! git --git-dir="$M" cat-file -e "$SHA^{commit}" 2>/dev/null; then
    timeout 900 git --git-dir="$M" fetch -q --depth=1 "$ORIGEM" "$REF" >/tmp/portao-fetch-$RUN.log 2>&1 \
      || { echo "PORTAO_INFRA fetch de $SHA falhou: $(tail -2 /tmp/portao-fetch-$RUN.log | tr '\n' ' ')"; exit 90; }
    git --git-dir="$M" cat-file -e "$SHA^{commit}" 2>/dev/null || { echo "PORTAO_INFRA $REF não trouxe $SHA"; exit 90; }
  fi
  mkdir -p "$BASE_RUN"
  for k in $(seq 1 "$PAR"); do
    git --git-dir="$M" worktree add -q --detach -f "$BASE_RUN/w$k" "$SHA" >/dev/null 2>&1 \
      || { echo "PORTAO_INFRA worktree $k"; exit 90; }
  done
) 8>"$M/.portao.lock"
rc=$?; rm -f "/tmp/portao-fetch-$RUN.log"
[ "$rc" -eq 0 ] || exit "$rc"

# ── 2. o venv da suíte (o mesmo de tools/testar_na_vm2.sh: requirements.txt + requirements-dev.txt, md5 marcado) ──
W1="$BASE_RUN/w1"
REQ=$(cat "$W1/requirements.txt" "$W1/requirements-dev.txt" | md5sum | cut -d' ' -f1)
(
  flock -w 1800 7 || { echo "PORTAO_INFRA venv ocupado por 1800 s"; exit 90; }
  [ "$(cat "$VENV/.req_md5" 2>/dev/null)" = "$REQ" ] && exit 0
  echo "[nó] requirements mudaram — remontando $VENV (minutos, uma vez)" >&2
  UV=$(command -v uv || ls "$HOME/.local/bin/uv" 2>/dev/null)
  rm -rf "$VENV.novo"
  if [ -n "$UV" ]; then
    ( set -e; "$UV" venv -q -p 3.12 "$VENV.novo"
      "$UV" pip install -q --python "$VENV.novo/bin/python" --index-url https://download.pytorch.org/whl/cpu torch torchvision
      "$UV" pip install -q --python "$VENV.novo/bin/python" -r "$W1/requirements.txt" -r "$W1/requirements-dev.txt" )
  else
    ( set -e; python3.12 -m venv "$VENV.novo"
      nice -n 15 "$VENV.novo/bin/python" -m pip install -q --upgrade pip
      nice -n 15 "$VENV.novo/bin/python" -m pip install -q --index-url https://download.pytorch.org/whl/cpu torch torchvision
      nice -n 15 "$VENV.novo/bin/python" -m pip install -q -r "$W1/requirements.txt" -r "$W1/requirements-dev.txt" )
  fi >"/tmp/jfn-suite-venv.log" 2>&1 || { echo "PORTAO_INFRA venv não montou (log no nó: /tmp/jfn-suite-venv.log)"; exit 90; }
  rm -rf "$VENV" && mv "$VENV.novo" "$VENV" && echo "$REQ" > "$VENV/.req_md5"
) 7>"$HOME/.jfn-suite-venv.lock"
rc=$?
[ "$rc" -eq 0 ] || exit "$rc"
[ -x "$VENV/bin/python" ] || infra "venv sem python"

# ── 3. os lotes: round-robin pelos PAR worktrees, todos ao mesmo tempo ─────────────────────────────────────────────
read -r -a LISTA <<< "$TESTES"
echo "[nó] $(hostname) load $(cut -d' ' -f1 /proc/loadavg) · ${#LISTA[@]} arquivo(s) em $PAR lote(s) · $SHA" >&2
for k in $(seq 1 "$PAR"); do
  lote=()
  for i in "${!LISTA[@]}"; do [ $(( i % PAR )) -eq $(( k - 1 )) ] && lote+=("${LISTA[$i]}"); done
  [ "${#lote[@]}" -eq 0 ] && { echo 0 > "$BASE_RUN/rc$k"; : > "$BASE_RUN/log$k"; continue; }
  ( cd "$BASE_RUN/w$k" && PYTHONPATH=. timeout "$TETO" nice -n 15 ionice -c3 "$VENV/bin/python" -m pytest \
      -q -rfE -p no:cacheprovider -p no:randomly --timeout=900 "${lote[@]}" >"$BASE_RUN/log$k" 2>&1
    echo $? > "$BASE_RUN/rc$k" ) &
done
wait

final=0
for k in $(seq 1 "$PAR"); do
  r=$(cat "$BASE_RUN/rc$k" 2>/dev/null || echo 99)
  resumo=$(grep -E "[0-9]+ (passed|failed|error)|no tests ran" "$BASE_RUN/log$k" | tail -1)
  echo "PORTAO_LOTE $k rc=$r $resumo"
  grep -E "^(FAILED|ERROR) " "$BASE_RUN/log$k" | sed 's/^/PORTAO_FALHA /'
  case "$r" in
    0|5) ;;
    124) final=1; echo "PORTAO_FALHA lote $k: TETO de $TETO s estourado (não terminou)";;
    *) final=1; tail -40 "$BASE_RUN/log$k" | sed "s/^/PORTAO_LOG $k| /";;
  esac
done
echo "PORTAO_FIM rc=$final"
