# ADR-002 — Identidade e normalização SEI

| Campo | Valor |
|---|---|
| **Estado** | Proposto (esqueleto da O1.4, 24/11/2026). A decisão final sai na onda indicada no plano |
| **Plano** | `~/vault/refatoracao/PLANO-MESTRE-v2-esteira-unica.md`; questão do doc 2 §31 |
| **Questão** | Qual formato canônico, que regras de validação e que política para identificadores incompletos? |
| **Relacionados** | ADR-001 (autoridade de dados), ADR-012 (motor `jfn-fluxo`) |

## Contexto

O mesmo processo SEI aparece com grafias diferentes (com ou sem prefixo, com ou sem zeros, `/` ou `_`). A medida de 19/11/2026 achou R$ 469 mi escondidos atrás de grafias irregulares. A O4.1 criou `compliance_agent/dominio/processo_id.py` e `documento_id.py` (funções puras), mas os chamadores antigos ainda normalizam cada um à sua maneira.

## Decisão

- Forma canônica única, produzida só por `compliance_agent/dominio/processo_id.py`. Nenhum outro módulo normaliza.
- Identificador incompleto (sem ano ou sem órgão) **não** é completado por inferência. Ele fica `incompleto` e entra em fila de resolução com motivo.
- A chave de `fluxo.jobs` usa só a forma canônica: `arvore:<canônico>`.
- Critério de aceite (§11.6): 0 grafia divergente nos manifestos carregados.

## Consequências

Uma chave só para juntar OB, contrato, árvore e laudo. Custo: migrar os chamadores antigos (O3) com teste de paridade por amostra.

## Não adotar

Normalização por regex espalhada (o estado atual). Fuzzy match de identificador: produz junção falsa, e em projeto de governo junção falsa é acusação falsa.

## Gatilho de reavaliação

Aparece um formato novo de número SEI (mudança do sistema estadual ou municipal) ou uma taxa de `incompleto` acima de 1% dos processos carregados.
