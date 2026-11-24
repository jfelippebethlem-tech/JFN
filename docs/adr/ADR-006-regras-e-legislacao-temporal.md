# ADR-006 — Regras e legislação temporal

| Campo | Valor |
|---|---|
| **Estado** | Proposto (esqueleto da O1.4, 24/11/2026). A decisão final sai na onda indicada no plano |
| **Plano** | `~/vault/refatoracao/PLANO-MESTRE-v2-esteira-unica.md`; questão do doc 2 §31 |
| **Questão** | Como versionar normas, critérios, exceções e aprovação? |
| **Relacionados** | ADR-001 (autoridade de dados), ADR-012 (motor `jfn-fluxo`) |

## Contexto

Os tetos legais estiveram copiados em três lugares divergentes (memória `teto-dispensa-terceira-copia`). O fracionamento por credor ainda sobrevive em 4 pontos (§2), e a Lei 8.666 e a Lei 14.133 convivem por data de contratação.

## Decisão

- Norma, teto e critério vivem num registro único versionado, com vigência `[inicio, fim)`. O detector consulta pela **data do fato**, nunca pela data de hoje.
- Toda mudança de regra jurídica passa por um lote ⚖️ com aprovação do dono (§4) e casos ouro verdes (§11.7).
- Exceção (hipótese inocente) é registrada com o código que a exclui.

## Consequências

Um achado fica reprodutível na data em que foi gerado. O custo é a carga inicial da tabela de vigências (O4).

## Não adotar

Tetos literais no código, que a catraca já proíbe. Motor de regras genérico (Drools e afins): complexidade sem ganho para cerca de 150 detectores.

## Gatilho de reavaliação

Lei ou decreto novo que mude teto ou modalidade, ou divergência entre o teto do registro e o da fonte oficial.
