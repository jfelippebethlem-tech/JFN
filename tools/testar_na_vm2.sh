#!/bin/bash
# testar_na_vm2.sh — roda a suíte do JFN na VM-2, deixando a VM-1 livre.
#
# Por que existe (2026-07-24): a VM-1 tem 2 vCPU e roda o servidor, o Hermes, o Chrome de captura e os
# sweeps. A suíte inteira (~2.500 testes) come a máquina — rodá-la aqui já derrubou a VM-1 uma vez. A
# VM-2 (JFN-Agent-2) tem os mesmos 2 vCPU e fica quase ociosa: é o lugar certo para o trabalho pesado.
#
# Sincroniza SÓ o código (nunca `data/` — o banco fica na VM-1) por tar+ssh sobre a rede Tailscale, e
# roda lá com `nice`. Idempotente: pode chamar quantas vezes quiser.
#
# Uso:
#   tools/testar_na_vm2.sh                    # suíte inteira
#   tools/testar_na_vm2.sh tests/test_x.py    # só um alvo
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
ALVO="${*:-tests/}"
PAR=vm2-ts                     # rota Tailscale permanente (porta 2222) — ver memória do túnel
REMOTO='~/JFN-test'

echo "[vm2] sincronizando código…"
tar czf /tmp/jfn-sync.tgz --exclude='__pycache__' --exclude='*.pyc' \
    compliance_agent tests tools siafe_agent rotas knowledge relatorio_riscos reporting static config \
    requirements.txt pyproject.toml ./*.py 2>/dev/null
scp -q -o BatchMode=yes /tmp/jfn-sync.tgz "$PAR:/tmp/" || { echo "[vm2] scp falhou — túnel fora?"; exit 1; }
rm -f /tmp/jfn-sync.tgz

# O venv remoto é criado uma vez; se o SO trocar a minor do Python ele vira órfão em silêncio
# (lib/python3.10 com interpretador 3.12) — por isso a checagem abaixo, que o recria quando preciso.
ssh -o BatchMode=yes "$PAR" "
set -e
mkdir -p $REMOTO && cd $REMOTO && tar xzf /tmp/jfn-sync.tgz && rm -f /tmp/jfn-sync.tgz
if [ -f .venv/pyvenv.cfg ] && [ ! -d .venv/lib/python\$(.venv/bin/python -c 'import sys;print(f\"{sys.version_info.major}.{sys.version_info.minor}\")') ]; then
    echo '[vm2] venv órfão (upgrade de Python) — recriando'; rm -rf .venv
fi
[ -d .venv ] || { python3 -m venv .venv && nice -n 10 .venv/bin/pip install -q -r requirements.txt pytest pytest-timeout; }
echo '[vm2] rodando: $ALVO'
nice -n 5 .venv/bin/python -m pytest $ALVO -q --timeout=900 --ignore=tests/test_sei_pagina_de_unidade.py
"
