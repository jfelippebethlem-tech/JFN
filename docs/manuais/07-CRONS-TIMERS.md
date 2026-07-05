# Manual — Crons & Timers (agendamentos)

Há dois agendadores: **systemd user timers** (JFN/Hermes) e o **crontab do usuário** (coletas e sweeps).

## systemd user timers
```bash
systemctl --user list-timers            # próximos disparos
systemctl --user --failed               # deve vir vazio
```
| Timer | Quando | Faz |
|---|---|---|
| `jfn-ronda.timer` | a cada 10min | checa serviço + alerta |
| `jfn-tfe.timer` | diário | coleta TFE (espelho D-1) |
| `jfn-tfe-ob.timer` | semanal | base completa de OBs |
| `jfn-sancoes.timer` | dom 05:40 | CEIS/CNEP (24,7k sanções) |
| `jfn-nucleo-ciclo.timer` | 06:30 | perícia + calibração + aprende |
| `jfn-metacognicao.timer` | 06:50 | reflexão + auto-melhoria + RAG |
| `jfn-integra-fila.timer` | 03:30 | íntegras SEI da fila |
| `hermes-update.timer` | ~04:00 | auto-update seguro do Hermes |
| `keepalive.timer` | ~7min | anti-idle Oracle |
| `painel-tunnel.service` | boot | túnel Cloudflare do painel |

## crontab do usuário (`crontab -l`)
Principais: `siafe_runner diario` (05:00) · `backfill_enderecos` (05:40) · `folha_orquestrador`
(06:00) · sweeps SEI (`sweep_sei.sh` a cada 30min) · `sweep_dados`/`cruzador`/`sweep_sede` ·
`pericia_sweep` (06:30) · `sei_integra_fila --geral` (04:00) · `triagem_amarelos --enviar`
(seg 09:00) · `backup_compliance` (dom 03:50) · `guardiao_failover` (5min) · imports do polimonitor.

## Regra que já quebrou (não repetir)
Comando de cron que usa **caminho relativo** ou **módulo** (`-m pacote`) PRECISA de
`cd /home/ubuntu/JFN &&` e/ou `PYTHONPATH=/home/ubuntu/JFN`. Sem isso, falha silenciosa diária
(visto e corrigido 2026-07-05 em `folha_orquestrador`, `obra_fase_sei` e `sei_integra_fila --geral`).

## Diagnóstico rápido
```bash
grep -iE 'error|traceback|no such file' ~/JFN/data/*_cron.log | tail   # erros recentes
journalctl --user -u <timer-service> -n 30                              # último run de um timer
```
