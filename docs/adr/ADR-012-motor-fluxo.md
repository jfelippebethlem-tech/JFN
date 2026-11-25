# ADR-012 — Motor de fluxo `jfn-fluxo` no PostgreSQL da VM-2

| Campo | Valor |
|---|---|
| **Estado** | Aceito (O1.7/O1.8 do plano mestre v2, 24/11/2026) |
| **Plano** | `~/vault/refatoracao/PLANO-MESTRE-v2-esteira-unica.md` §3.2–§3.5 |
| **Código** | `deploy/vm2/postgres/fluxo_001.sql` · `compliance_agent/fluxo/` · `compliance_agent/aplicacao/estagios/` |
| **Units** | `deploy/systemd/jfn-fluxo@.service` · `deploy/systemd/jfn-coletor.slice` (ex-jfn-jobs.slice; egress da O0.4 casa nela) · `deploy/systemd/jfn-egress.service` (instalação na O2) |

## 1. Contexto

O trabalho do JFN rodava por ~190 gatilhos espalhados: crontab nas 3 máquinas, timers do systemd, tarefas do
Windows, o despachante de `compliance_agent/propagacao.py` (SQLite, sonda `MAX(rowid)` que não vê UPDATE) e o
semáforo `tools/pesado.sh` (carga média, não pressão). Ninguém sabia o que estava atrasado, a VM-1 ocupava
118,8 h/dia de parede e a perda de um nó parava estágios inteiros (§16 do plano).

Já existia uma fila correta em `compliance_agent/evidencias.py` (`public.jobs`: chave única, reserva atômica por
`UPDATE … FOR UPDATE SKIP LOCKED … RETURNING`, prazo e ficha de posse), em uso pela leitura integral.

## 2. Decisão

1. **Fila única no PostgreSQL 16 da VM-2, schema `fluxo`** (banco `jfn_evidencias`, o mesmo do jfn-brain).
   - `fluxo.jobs` é **tabela nova**, evolução da `public.jobs`: mesmos nomes e sentidos (`estado`, `prazo`,
     `ficha`, `chave`, `tentativas`, `dono`, `criado_em`, `concluido_em`) + `tipo`, `prioridade`, `recursos`,
     `heartbeat_em`, `max_tentativas`, `disponivel_em` (backoff/debounce), `erro_tipo`/`erro_resumo`,
     `correlation_id`, `no_preferido`, `volta`, `payload`, `efeito`, `iniciado_em`.
   - **Por que nova e não `ALTER` da `public.jobs`:** a `public.jobs` tem dono vivo (leitura integral) e
     `UNIQUE(tipo, chave)`; mudar unicidade e semântica de estado debaixo de quem a usa quebraria o leitor sem teste
     de regressão. Ela continua servindo até a migração na **O3**, quando os jobs dela passam a ser `fluxo.jobs`
     com `chave = '<tipo>:<chave>'`.
   - `UNIQUE(chave)`: a chave carrega o tipo (`eco:x`, `ocr:doc:123`). Idempotência de ponta a ponta.
   - **Ficha = sequência global** (`fluxo.fichas`): identifica a reserva sozinha e só cresce. Concluir, falhar e
     renovar exigem a ficha vigente **e** o lease no prazo (fencing; lease vencido não conclui).
   - Estados: `fila`, `reservado`, `feito`, `falhou_efeito`, `quarentena`, `cancelado`. **"feito" só com efeito
     conferido** por um processo separado do handler.
   - `fluxo.eventos` = outbox: gravado na MESMA transação do "feito". `fluxo.agenda` = único lugar de horário.
     `fluxo.nos` = heartbeat, slots e PSI por máquina. `fluxo.metricas` = série leve.
   - NOTIFY `jfn_jobs` no INSERT em fila; autovacuum agressivo e `fillfactor=80` em `jobs`; `arquivar_jobs(dias)`
     move os `feito` antigos para `jobs_arquivo`.
2. **Um supervisor por máquina (`jfn-fluxo@<no>`) que só escolhe.** Cada job roda em subprocesso isolado
   (`systemd-run --user --scope --slice=jfn-coletor.slice -p MemoryMax -p CPUWeight` + `timeout`; sem systemd,
   `prlimit` + nice + `timeout`). Catraca: o supervisor não importa `compliance_agent.aplicacao`.
3. **Planejador eleito por `pg_try_advisory_lock(42)`** (lock de sessão: cai sozinho se o nó morrer).
4. **Governador por PSI** (`/proc/pressure`), disco e swap — nunca por load average.
5. **cron próprio de 5 campos** (croniter não está no requirements; o parser cobre o que a casa usa).

## 3. Consequências

- Um só lugar responde "o que está na fila, atrasado, em quarentena, em qual nó" — base da saúde honesta
  (`SAUDAVEL/DEGRADADO/ATRASADO/BLOQUEADO/INDISPONIVEL`).
- Matar um supervisor não perde job: o lease vence e volta à fila; o estágio tem de ser **idempotente pela chave**
  (contrato §3.2) porque pode rodar duas vezes.
- A VM-2 vira ponto único: sem PG, só seguem os jobs já reservados (contingência SQLite local de E15/E18 é a O2).
- Advisory lock 42 é por banco: nenhum outro sistema do `jfn_evidencias` pode usar a chave 42.
- Durante a convivência (até a O3) existem duas filas — `public.jobs` (leitura integral) e `fluxo.jobs`.
- O supervisor sem systemd do usuário roda os filhos no próprio cgroup (teto de 256M da unit): em produção o
  `nos.capacidades.isolamento` tem de ser `systemd`.

## 4. O que NÃO adotar

| Alternativa | Por que não |
|---|---|
| **Temporal** | Servidor + workers + banco próprio para 3 máquinas de 2–24 fios; operação e memória que a VM-2 não tem. O que usaríamos dele (lease, retry, histórico) cabe em 5 tabelas. |
| **Celery** | Precisa de broker (Redis/RabbitMQ), não tem efeito conferido nem fencing por ficha, e o "ack tardio" duplica trabalho sem a casa ver. |
| **Redis (fila/locks)** | Mais um estado fora do PG, sem transação com o outbox e sem durabilidade de verdade no modo padrão; o PG já está no ar e já é a fonte canônica. |
| pg-boss/graphile-worker | Exigem Node; o JFN é Python. A técnica deles (SKIP LOCKED + NOTIFY) é a mesma adotada aqui. |
