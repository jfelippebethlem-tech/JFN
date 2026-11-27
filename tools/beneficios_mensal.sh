#!/usr/bin/env bash
# Benefícios sociais × sócios de fornecedores e × servidores/nomeados (dono 27/11/2026: «tem que entrar no fluxo»).
# Roda na VM-1 (dona do compliance.db) e usa o it-campo (IP residencial; o Portal recusa datacenter; disco folgado):
#   1. chaves (só leitura do banco) → it-campo; 2. histórico mês a mês no it-campo (só meses novos; retoma);
#   3. concomitância servidor × benefício; 4. traz os resultados para ~/dados-externos/beneficios com md5 conferido.
# Dados FORA do git (repo público): só a máscara pública de cada fonte, nunca CPF completo.
set -euo pipefail
cd "$(dirname "$0")/.."
L="$HOME/dados-externos/beneficios"; mkdir -p "$L"
.venv/bin/python -m tools.beneficios.chaves "$L"
it(){ timeout "${2:-120}" ssh it-campo "wsl -d Ubuntu -- bash -c \"$1\""; }
it "mkdir -p ~/beneficios"
for f in chaves_socios.json chaves_servidores.json; do it "cat > ~/beneficios/$f" 300 < "$L/$f"; done
for f in historico.py concomitancia_servidores.py; do it "cat > ~/beneficios/$f" < "tools/beneficios/$f"; done
it "cd ~/beneficios && nice -n 10 python3 historico.py" 86000 | tail -1
it "cd ~/beneficios && nice -n 10 python3 concomitancia_servidores.py" 3600 | tail -1
for f in casamentos.jsonl concomitancias_servidores.jsonl; do
  it "cat ~/beneficios/$f" 600 > "$L/$f.novo"
  [ "$(it "md5sum ~/beneficios/$f" | cut -c1-32)" = "$(md5sum "$L/$f.novo" | cut -c1-32)" ] || { echo "md5 diverge em $f"; exit 1; }
  mv "$L/$f.novo" "$L/$f"
done
echo "beneficios_mensal: ok — $(wc -l < "$L/casamentos.jsonl") casamentos de sócio, $(wc -l < "$L/concomitancias_servidores.jsonl") concomitâncias de servidor"
