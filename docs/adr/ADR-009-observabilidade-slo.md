# ADR-009 — Observabilidade e SLO

| Campo | Valor |
|---|---|
| **Estado** | Proposto (esqueleto da O1.4, 24/11/2026). A decisão final sai na onda indicada no plano |
| **Plano** | `~/vault/refatoracao/PLANO-MESTRE-v2-esteira-unica.md`; questão do doc 2 §31 |
| **Questão** | Quais métricas, alertas, retenção, painéis e responsáveis? |
| **Relacionados** | ADR-001 (autoridade de dados), ADR-012 (motor `jfn-fluxo`) |

## Contexto

A saúde mentia: "ok" com 24 de 36 derivados sujos, e um diário morto por 4 dias sem aviso. A linha de base (O1.3) mediu 30 derivados sujos e 7 atrasados (o maior com 49,6 h) no snapshot.

## Decisão

- Métrica só sai do efeito conferido (`fluxo.metricas`), nunca de "o processo rodou".
- SLO por estágio e por visão. Passou do SLO, o estado é ATRASADO no painel e na automelhoria.
- INDISPONÍVEL é um estado, nunca 0.
- Retenção: série leve de 90 dias no PG; os jobs `feito` são arquivados por mês (ADR-012).
- Responsável: E18 `observar`. O alerta vai no chat do Claude Code; o Yoda não fala sem pedido.

## Consequências

Atraso visível antes do dono perceber. O custo é que cada estágio precisa declarar o seu efeito verificável.

## Não adotar

Prometheus, Grafana ou Loki: são serviços a mais em 2 vCPU; o painel já existe e lê o PG. Alerta por e-mail a cada falha, que vira ruído.

## Gatilho de reavaliação

Um defeito percebido pelo dono antes do sensor, ou um sensor em INDISPONÍVEL por mais de 24 h.
