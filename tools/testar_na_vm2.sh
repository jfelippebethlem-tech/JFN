#!/bin/bash
# testar_na_vm2.sh — roda a suíte do JFN (ou um alvo) na VM-2, deixando a VM-1 livre.
#
# Por que existe (2026-07-24): a VM-1 tem 2 vCPU e roda o servidor, o Hermes, o Chrome de captura e os
# sweeps. A suíte inteira come a máquina — já derrubou a VM-1 4×. A VM-2 roda os 4 lotes em ~20 min
# (medido 15/11/2026: lotes de 4,5 min) contra 75+ min na VM-1 com load 20.
#
# 15/11/2026: o destino era vm2:~/JFN-test, que a memória marca como do dono ("não tocar") — agora é
# um diretório PRÓPRIO, recriado a cada envio (arquivo apagado aqui não sobra lá), e usa o venv do
# ~/JFN-worker (mesmo Python 3.12, pytest + pytest-timeout já instalados) em vez de criar outro.
# A entrega é conferida por md5 do pacote dos dois lados (memória entrega-entre-maquinas-confirmar-md5).
#
# Sincroniza SÓ o código (nunca `data/` — o banco fica na VM-1). Idempotente.
#
# Uso:
#   tools/testar_na_vm2.sh                    # suíte inteira, em 4 lotes (tools/ci_lote.py)
#   tools/testar_na_vm2.sh tests/test_x.py    # só um alvo
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
PAR=vm2-ts                     # rota Tailscale permanente (porta 2222) — ver memória do túnel
REMOTO='~/JFN-suite-vm1'
PY='~/JFN-worker/.venv/bin/python'
PKG=$(mktemp /tmp/jfn-suite-XXXXXX.tgz)
trap 'rm -f "$PKG"' EXIT

echo "[vm2] empacotando código…"
tar czf "$PKG" --exclude='__pycache__' --exclude='*.pyc' \
    compliance_agent tests tools siafe_agent rotas knowledge relatorio_riscos reporting static config \
    requirements.txt pyproject.toml ./*.py capabilities.yaml 2>/dev/null
MD5=$(md5sum "$PKG" | cut -d' ' -f1)
scp -q -o BatchMode=yes "$PKG" "$PAR:/tmp/jfn-suite.tgz" || { echo "[vm2] scp falhou — túnel fora?"; exit 1; }

if [ $# -gt 0 ]; then
  CMD="nice -n 15 ionice -c3 $PY -m pytest $* -q -rf -p no:cacheprovider --timeout=900"
else
  CMD="for l in 1 2 3 4; do echo \"[vm2] lote \$l/4\"; nice -n 15 ionice -c3 $PY -m pytest -q -rf -p no:cacheprovider --timeout=900 \$($PY -m tools.ci_lote \$l 4) || rc=1; done; exit \${rc:-0}"
fi

ssh -o BatchMode=yes "$PAR" "
set -e
[ \"\$(md5sum /tmp/jfn-suite.tgz | cut -d' ' -f1)\" = '$MD5' ] || { echo '[vm2] md5 do pacote NÃO confere — abortando'; exit 3; }
rm -rf $REMOTO.novo && mkdir -p $REMOTO.novo && tar xzf /tmp/jfn-suite.tgz -C $REMOTO.novo && rm -f /tmp/jfn-suite.tgz
rm -rf $REMOTO && mv $REMOTO.novo $REMOTO && cd $REMOTO
echo \"[vm2] md5 confere ($MD5); load \$(cut -d' ' -f1 /proc/loadavg); rodando\"
set +e
export PYTHONPATH=.
$CMD
"
