# Manual — Polimonitor / Bond (monitor de Instagram)

## O que é
`~/polimonitor` (Next.js :3000) é o painel de inteligência de redes sociais. Mostra a aba
**Interações** (curtidores/comentaristas por período), leaderboard, análise viral. O "bond" que o
dono usa é este (`~/polimonitor`), não `~/Bond`.

## Peças
- **App web** (`next dev`, porta 3000) — a interface.
- **Workers** (`tsx`): `hermes-worker.ts` (análise IA), `bond-worker.ts` (captura), `telegram.ts`.
- `~/likers-sync` — repo de captura de curtidores (branches = motores; nodriver recomendado).
- **Jorge (desktop QBL7LAM)** faz a captura local e sincroniza por **Syncthing**.

## Como ver saúde
```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/     # 307 (redirect de login) = vivo
ps -ef | grep -E 'next-server|tsx' | grep -v grep                  # app + workers
```

## Fluxo de dados (curtidores por período)
1. Jorge captura → `~/likers-sync/likers-sync/likers.json` (via Syncthing).
2. Cron `run-likers-import.sh` (a cada 5min) importa → BondInteracao (habilita filtro por data).
3. Cron `refresh-posts-index.sh` (04:40–09:40) reindexa posts na pasta Syncthing.
4. Regra do dono: toda run começa pelos 10 posts mais novos (IG_TOP_RECENTES, delta).

## Syncthing (a ponte com o Jorge)
- GUI/API: `http://100.123.89.59:8384` (tailnet). Pastas: likers-sync, sei-processos, shared-brain, vault.
- Ver peers: `curl -H "X-API-Key: <apikey do config.xml>" .../rest/system/connections`.
- **Sintoma comum:** import parado apesar do cron rodando = a **captura no Jorge** parou (reiniciar
  na máquina). Se `likers.json` não muda de horário, o problema é upstream (Jorge), não a VM.

## Crons (todos no crontab do usuário)
`run-likers-import.sh` (5min) · `refresh-posts-index.sh` (04:40–09:40) · `run-resumo-semanal.sh`
(sex 18h) · `run-watch-leaderboard.sh` (qui 08h) · `run-viral-semanal.sh` (sex 09h).
