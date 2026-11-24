# ADR-003 — Armazenamento imutável de originais

| Campo | Valor |
|---|---|
| **Estado** | Proposto (esqueleto da O1.4, 24/11/2026). A decisão final sai na onda indicada no plano |
| **Plano** | `~/vault/refatoracao/PLANO-MESTRE-v2-esteira-unica.md`; questão do doc 2 §31 |
| **Questão** | Onde ficam os originais, as versões, o texto do OCR e os hashes, e qual a retenção? |
| **Relacionados** | ADR-001 (autoridade de dados), ADR-012 (motor `jfn-fluxo`) |

## Contexto

Os originais ficam em três lugares: a VM-2 quente, o HD do it-campo e o Drive frio. A porta única `compliance_agent/armazenamento.py` já existe (`docs/ARMAZENAMENTO.md`). O disco da VM-2 estava em 91% na linha de base, e o OCR novo já apagou texto antigo uma vez (memória `ocr-novo-nunca-substitui-texto`).

## Decisão

- Original é **imutável** e endereçado por sha256 (`versoes` no PG, ADR-001 D2).
- Texto de OCR é uma `transformacao` nova, com motor@versão. Nunca sobrescreve: só preenche o vazio ou cria uma versão.
- Camadas: quente (VM-2), morno (HD com md5 + índice), frio (Drive). Só a porta única move arquivos; hash conferido antes de apagar.
- Retenção: insubstituível = 2 cópias grátis; re-obtível = 1 cópia.

## Consequências

A procedência de todo documento fica auditável. O custo é que o índice `armazenamento_indice.db` vira crítico: precisa de backup e restauração testada (§11.11).

## Não adotar

Armazenamento pago, que viola a regra das nuvens só no grátis. Deduplicar por nome de arquivo em vez de hash. Apagar o original depois do OCR.

## Gatilho de reavaliação

Disco da VM-2 acima de 75% (§11.3), uma nuvem grátis muda o limite, ou uma restauração semanal falha.
