# ADR-007 — Identidade de pessoas e empresas

| Campo | Valor |
|---|---|
| **Estado** | Proposto (esqueleto da O1.4, 24/11/2026). A decisão final sai na onda indicada no plano |
| **Plano** | `~/vault/refatoracao/PLANO-MESTRE-v2-esteira-unica.md`; questão do doc 2 §31 |
| **Questão** | Como resolver CPF mascarado, homônimos, grupos econômicos e vínculos históricos? |
| **Relacionados** | ADR-001 (autoridade de dados), ADR-012 (motor `jfn-fluxo`) |

## Contexto

As fontes públicas mascaram o CPF de forma diferente, e a resolução de homônimos já gerou falso positivo (memória `perfil-laranja-prevalencia-e-cpf-mascarado`). O repo é público e o histórico tem CPF completo (ADR-011).

## Decisão

- A entidade é resolvida por chave forte: CNPJ de 14 dígitos com DV, ou CPF completo **só em tabela com acesso controlado**. Nome sozinho nunca une duas entidades.
- O CPF mascarado gera um candidato com grau de confiança. Nenhum achado 🔴/🟡 se apoia só nele.
- Grupo econômico e vínculo têm vigência (sócio de quando até quando).
- Em toda saída, o CPF de sócio sai mascarado (LGPD).

## Consequências

Menos falso vínculo. O custo é que parte dos vínculos fica `indeterminado` e visível.

## Não adotar

Fuzzy match de nome como prova. Guardar CPF completo em JSON solto ou no git.

## Gatilho de reavaliação

Uma fonte nova com CPF completo, ou uma taxa de homônimo confirmado acima de 2% numa amostra conferida.
