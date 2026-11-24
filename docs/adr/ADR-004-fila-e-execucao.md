# ADR-004 — Fila e execução

| Campo | Valor |
|---|---|
| **Estado** | Proposto (esqueleto da O1.4, 24/11/2026). A decisão final sai na onda indicada no plano |
| **Plano** | `~/vault/refatoracao/PLANO-MESTRE-v2-esteira-unica.md`; questão do doc 2 §31 |
| **Questão** | Qual mecanismo, que semântica de entrega, lease, idempotência, retry e dead-letter? |
| **Relacionados** | ADR-001 (autoridade de dados), ADR-012 (motor `jfn-fluxo`) |

## Contexto

Hoje são cerca de 190 gatilhos (cron, timers, tarefas do Windows, despachante) sem visão de atraso, e as filas em JSON estão sem trava entre máquinas (ADR-001 §4). A decisão de mecanismo já foi tomada e implementada na **ADR-012** (motor `jfn-fluxo` no PG da VM-2).

## Decisão

- Adota a ADR-012 como decisão de mecanismo. Este ADR fixa a **semântica**:
  - entrega pelo menos uma vez, com efeito idempotente pela `chave`;
  - lease com ficha (fencing);
  - retry com backoff (`disponivel_em`) até `max_tentativas`;
  - depois disso, `quarentena`, que faz o papel de dead-letter visível no painel.
- "Feito" só com efeito conferido por um processo separado do handler.
- Um job tem um gatilho só (§11.1).

## Consequências

O atraso e a perda ficam visíveis e a perda de um nó não perde o job. O custo é que todo handler precisa ser idempotente: isso é testado por estágio na O2/O3.

## Não adotar

Celery, RabbitMQ, Redis ou Kafka: mais um serviço para manter em 2 vCPU, sem ganho sobre o `SKIP LOCKED` do PG que já existe. Manter cron com `flock`: não atravessa máquinas.

## Gatilho de reavaliação

Vazão acima de cerca de 50 mil jobs/dia, ou latência de reserva acima de 1 s no p95, ou o PG da VM-2 fica indisponível por mais de 1 h em 7 dias.
