#!/bin/bash
# Lane da VARREDURA do acervo SEI — leitura dupla (regra + LLM gratuita) de todos os processos.
#
# POR QUE ESTE ARQUIVO EXISTE. A leitura custa ~70 s por processo e o acervo tem 2.354. Enquanto ela
# dependia de eu relançar lote a lote entre uma supervisão e outra, o gargalo deixava de ser a
# máquina e passava a ser a minha cadência: a VM ficava ociosa no intervalo. O dono pediu que a
# leitura continue; este lane é a forma de continuar sem depender de sessão aberta.
#
# FORMA OBRIGATÓRIA DA CASA (aprendizados/obediencia-e-loop-autonomo):
#   · cron SINGLE-PASS com `timeout`, NUNCA `while true` — cada disparo lê um lote e termina;
#   · não paralelizar: `flock` garante um só de cada vez (2 vCPU é o gargalo);
#   · respeitar carga: acima do teto, o disparo DESISTE em silêncio e tenta no próximo;
#   · parar é imediato — basta `rm -f data/.varredura_sei.off` ao contrário: criar o arquivo desliga.
#
# Desligar:  touch data/.varredura_sei.off
# Religar :  rm -f data/.varredura_sei.off
set -u
cd /home/ubuntu/JFN || exit 1

[ -f data/.varredura_sei.off ] && exit 0          # kill-switch do dono, sem precisar mexer no cron

exec 9>/tmp/varredura_sei.lock
flock -n 9 || exit 0                              # já tem um DISPARO DESTE LANE lendo

# O `flock` sozinho NÃO BASTA, e isso foi medido no primeiro teste: ele só serializa os disparos do
# lane, e havia uma varredura lançada À MÃO fora dele. Resultado: dois leitores concorrendo em 2
# vCPU, exatamente o que a regra da casa proíbe. A checagem abaixo enxerga QUALQUER leitura viva.
#
# A busca por padrão na linha de comando de TODOS os processos casaria com o PRÓPRIO script (o
# comando dele contém o nome do módulo) — armadilha que já mordeu nesta casa. Por isso a checagem
# é restrita ao interpretador, via `ps -C python`, que não inclui shells.
if ps -C python -o args= 2>/dev/null | grep -q "sei_leitura_dupla"; then
  exit 0
fi

# TETO DE CARGA. A regra da casa é 1 pesado por vez em 2 vCPU; acima de 4 o disparo desiste e
# tenta de novo no próximo, em vez de somar com o que já está rodando.
carga=$(awk '{printf "%d", $1}' /proc/loadavg)
[ "$carga" -ge 4 ] && exit 0

# `timeout` para o disparo NUNCA virar processo eterno: 50 min lê ~40 processos e devolve a máquina.
# `--amostra` alto não é problema: o lote termina quando o timeout chega, e o próximo continua de
# onde parou (a fila é calculada do que ainda não foi lido).
set -a; . .env 2>/dev/null; set +a
timeout 3000 nice -n 10 ionice -c3 .venv/bin/python -u -m tools.sei_leitura_dupla \
    --amostra 200 --gravar --max-chars 150000 >> data/varredura_sei.log 2>&1

echo "$(date -Is) disparo encerrado (saída $?)" >> data/varredura_sei.log
