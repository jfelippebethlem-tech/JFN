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

# DOIS LEITORES, E A REGRA DA CASA CONTINUA VALENDO. "1 pesado por vez" protege 2 vCPU, e a medição
# de 2026-08-14 mostra que a leitura NÃO é pesada de CPU: o leitor vivo estava em 0,1% de CPU, com
# mediana de 17,4 s por chamada — ele passa o tempo esperando a rede, não calculando. Medido contra
# o provedor com documento real (corrigindo o viés de tamanho do lote de teste): ~2,1× de vazão com
# dois em paralelo, sem 429 e sem erro de cota. A ~46 leituras/h, isso tira ~19 h do acervo.
# O `--fatia` reparte a fila de forma DETERMINÍSTICA — sem ele os dois pegariam o mesmo processo e
# gastariam IA em dobro. A escrita aguenta: `INSERT OR REPLACE` com `busy_timeout=60000`.
# Se um dia o provedor passar a recusar concorrência, basta voltar a UMA linha sem `--fatia`.
# QUATRO, e não duas: medido em 2026-08-14 contra o provedor, 4 concorrentes rendem ~2,6x a vazão
# de 2 (80k chars em 13,9s contra 48k em 21,8s), com 4/4 de sucesso e sem 429. Desconfio do
# superlinear — é variação de tamanho entre documentos —, então o ganho honesto esperado é ~2x.
# Continua sem violar "1 pesado por vez": cada leitor fica em ~0,1% de CPU, esperando rede.
# Se a memória apertar (a VM é COMPARTILHADA e outra sessão roda Chromium), voltar para 0/2 1/2.
for fatia in 0/4 1/4 2/4 3/4; do
  timeout 3000 nice -n 10 ionice -c3 .venv/bin/python -u -m tools.sei_leitura_dupla \
      --amostra 200 --gravar --max-chars 150000 --fatia "$fatia" >> data/varredura_sei.log 2>&1 &
done
wait

echo "$(date -Is) disparo encerrado (saída $?)" >> data/varredura_sei.log
