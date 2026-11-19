#!/bin/bash
# testar_na_vm2.sh — roda a suíte do JFN (ou um alvo) na VM-2, deixando a VM-1 livre.
#
# Por que existe (2026-07-24): a VM-1 tem 2 vCPU e roda o servidor, o Hermes, o Chrome de captura e os
# sweeps. A suíte inteira come a máquina — já derrubou a VM-1 4×. A VM-2 roda os 4 lotes em ~20 min
# (medido 15/11/2026: lotes de 4,5 min) contra 75+ min na VM-1 com load 20.
#
# 15/11/2026: o destino era vm2:~/JFN-test, que a memória marca como do dono ("não tocar") — agora é
# um diretório PRÓPRIO, recriado a cada envio (arquivo apagado aqui não sobra lá).
# 15/11/2026 (2): o venv deixou de ser o do ~/JFN-worker — ele não seguia o requirements.txt (faltava
# `apsw`, declarado) e duas falhas que a nuvem não tem apareciam só aqui. Agora é ~/JFN-suite-venv,
# montado do requirements.txt + requirements-dev.txt como o CI (torch CPU primeiro) e REMONTADO quando
# o md5 deles muda (~2 min medidos). Se a montagem falhar, cai no venv do worker e DIZ que caiu.
# A entrega é conferida por md5 do pacote dos dois lados (memória entrega-entre-maquinas-confirmar-md5).
#
# Sincroniza SÓ os arquivos versionados (o `data/` não versionado — bancos, acervo — fica na VM-1). Idempotente.
#
# Uso:
#   tools/testar_na_vm2.sh                    # suíte inteira, em 4 lotes (tools/ci_lote.py)
#   tools/testar_na_vm2.sh tests/test_x.py    # só um alvo
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
PAR=vm2-ts                     # rota Tailscale permanente (porta 2222) — ver memória do túnel
# 19/11/2026: duas sessões rodando ao mesmo tempo apagavam o diretório uma da outra (rm -rf + mv no mesmo
# ~/JFN-suite-vm1) e o pytest da primeira morria com 'failed to make path absolute'. Agora cada envio tem o
# SEU diretório e o seu pacote, apagados ao fim.
RUN="$(date +%s)-$$"
REL="JFN-suite-vm1-$RUN"
REMOTO="~/$REL"
TGZ="/tmp/jfn-suite-$RUN.tgz"
VENV='~/JFN-suite-venv'
PY="$VENV/bin/python"
PKG=$(mktemp /tmp/jfn-suite-XXXXXX.tgz)
trap 'rm -f "$PKG"' EXIT

echo "[vm2] empacotando código…"
# 15/11/2026: o pacote é o que um CHECKOUT LIMPO tem — os arquivos VERSIONADOS (`git ls-files`), com o
# conteúdo da árvore de trabalho. A lista fixa de pastas mandava arquivo ignorado (tools/eleicao2026_*.py,
# que importa scipy/shapely) e deixava de fora requirements-dev.txt — 2 falhas que a nuvem não tem.
# Fora só os binários pesados de docs/ (PDF e key-art, ~95 MB), que nenhum teste lê.
git ls-files -z -- . ':!docs/pdf' ':!docs/referencias' \
  | while IFS= read -r -d '' f; do [ -e "$f" ] && printf '%s\0' "$f"; done \
  | tar czf "$PKG" --null -T - 2>/dev/null
MD5=$(md5sum "$PKG" | cut -d' ' -f1)
scp -q -o BatchMode=yes "$PKG" "$PAR:$TGZ" || { echo "[vm2] scp falhou — túnel fora?"; exit 1; }

if [ $# -gt 0 ]; then
  CMD="nice -n 15 ionice -c3 $PY -m pytest $* -q -rf -p no:cacheprovider --timeout=900"
else
  CMD="for l in 1 2 3 4; do echo \"[vm2] lote \$l/4\"; nice -n 15 ionice -c3 $PY -m pytest -q -rf -p no:cacheprovider --timeout=900 \$($PY -m tools.ci_lote \$l 4) || rc=1; done; exit \${rc:-0}"
fi

ssh -o BatchMode=yes "$PAR" "
set -e
[ \"\$(md5sum $TGZ | cut -d' ' -f1)\" = '$MD5' ] || { echo '[vm2] md5 do pacote NÃO confere — abortando'; exit 3; }
trap \"cd; rm -rf \$HOME/$REL $TGZ\" EXIT
mkdir -p $REMOTO && tar xzf $TGZ -C $REMOTO && rm -f $TGZ && cd $REMOTO
# As catracas (compliance_agent/qualidade/catraca.py) medem por git ls-files e git grep: sem repositorio
# elas morrem com not-a-git-repository. Um commit local dos arquivos enviados reproduz o checkout
# (-f: arquivo versionado que casa com .gitignore, como data/*.json, tambem tem de entrar).
# SEM CRASE NEM CIFRAO AQUI: este bloco esta dentro de aspas duplas e a crase executaria NA VM-1.
git init -q && git add -A -f && git -c user.name=vm2 -c user.email=vm2@localhost commit -q --no-verify -m vm2
REQ=\$(cat requirements.txt requirements-dev.txt | md5sum | cut -d' ' -f1)
if [ \"\$(cat $VENV/.req_md5 2>/dev/null)\" != \"\$REQ\" ]; then
  echo '[vm2] requirements mudaram — remontando o venv limpo da suíte…'
  if ( set -e; rm -rf $VENV.novo; python3.12 -m venv $VENV.novo
       nice -n 15 $VENV.novo/bin/python -m pip install -q --upgrade pip
       nice -n 15 $VENV.novo/bin/python -m pip install -q --index-url https://download.pytorch.org/whl/cpu torch torchvision
       nice -n 15 $VENV.novo/bin/python -m pip install -q -r requirements.txt -r requirements-dev.txt ) >/tmp/jfn-suite-venv.log 2>&1
  then rm -rf $VENV && mv $VENV.novo $VENV && echo \"\$REQ\" > $VENV/.req_md5
  else echo '[vm2] AVISO: venv limpo NAO montou (log em vm2:/tmp/jfn-suite-venv.log)'; fi
fi
[ -f $VENV/.req_md5 ] || { echo '[vm2] AVISO: sem venv limpo — usando o do JFN-worker (pode divergir do requirements)'; ln -sfn ~/JFN-worker/.venv $VENV; }
echo \"[vm2] md5 confere ($MD5); load \$(cut -d' ' -f1 /proc/loadavg); rodando\"
set +e
export PYTHONPATH=.
$CMD
"
