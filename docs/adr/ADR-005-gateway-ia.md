# ADR-005 — Gateway de IA

| Campo | Valor |
|---|---|
| **Estado** | Proposto (esqueleto da O1.4, 24/11/2026). A decisão final sai na onda indicada no plano |
| **Plano** | `~/vault/refatoracao/PLANO-MESTRE-v2-esteira-unica.md`; questão do doc 2 §31 |
| **Questão** | Quais provedores e modelos, com que orçamento, cache, privacidade e fallback? |
| **Relacionados** | ADR-001 (autoridade de dados), ADR-012 (motor `jfn-fluxo`) |

## Contexto

A linha de base tem: 72,7% dos laudos da perícia saem da cascata sem Claude, a fila do Opus tem 6.907 pendentes, a concordância é de 26,8% e o cache do Opus é baixo. Há sete arquivos de estado de LLM com três travas diferentes (ADR-001 §4, linhas 40–48). Uma chave com billing já cobrou sem aviso (regra: nunca assumir free tier).

## Decisão

- Um gateway (`compliance_agent/adaptadores/llm/gateway`) é o **escritor único** de uso, custo, cota e contingência, gravados no PG.
- Orçamento com teto conferido no servidor do provedor, mais o kill-switch local. Teto ≤ US$ 100/mês (§11.9).
- O prompt fixo vem antes da parte variável, por causa do cache.
- Fallback declarado por tarefa. Toda saída sem o Claude da assinatura vai para a conferência E12.
- Privacidade: nenhum CPF completo sai para provedor externo.

## Consequências

O custo e a qualidade por tarefa ficam mensuráveis. O custo é migrar os consumidores de `llm/`, com paridade por amostra.

## Não adotar

Proxy de terceiros (gateways gratuitos já avaliados e descartados). Modelo local na VM, que não cabe em 2 vCPU. Usar provedor pago sem teto no servidor.

## Gatilho de reavaliação

Mudança de preço ou de política de um provedor, concordância com o Opus abaixo de 50% por 7 dias numa tarefa, ou custo mensal acima de 80% do teto.
