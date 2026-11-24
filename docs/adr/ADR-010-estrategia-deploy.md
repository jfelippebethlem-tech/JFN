# ADR-010 — Estratégia de deploy

| Campo | Valor |
|---|---|
| **Estado** | Proposto (esqueleto da O1.4, 24/11/2026). A decisão final sai na onda indicada no plano |
| **Plano** | `~/vault/refatoracao/PLANO-MESTRE-v2-esteira-unica.md`; questão do doc 2 §31 |
| **Questão** | Como promover a branch, fazer rollback, migrar o banco e comprovar a versão em produção? |
| **Relacionados** | ADR-001 (autoridade de dados), ADR-012 (motor `jfn-fluxo`) |

## Contexto

O deploy pós-commit (`tools/deploy_pos_commit.sh`) reinicia o painel. O schema vinha de `create_all` + `ALTER` automático, e uma migração que falhava seguia adiante. As três máquinas podem rodar commits diferentes, e houve 16 timers na VM-2 apontando para duas árvores.

## Decisão

- Uma árvore por máquina. O commit em produção é registrado em `fluxo.nos`, e uma divergência entre nós é alerta.
- Migração versionada que falha **para** o deploy. Ela nunca segue adiante.
- Rollback = voltar ao commit anterior + migração reversa testada. Em dado, rollback é o backup (O0.0).
- A religação (O9.0) segue a sequência verificada E1→E18, cada etapa liberando a seguinte com o efeito conferido.

## Consequências

Sempre se sabe o que está rodando. O custo é escrever a migração reversa de cada mudança de schema.

## Não adotar

Deploy contínuo sem portão em 2 vCPU. Contêineres (Docker ou k8s): peso extra sem ganho para três nós.

## Gatilho de reavaliação

Uma divergência de commit entre nós por mais de 1 h, uma migração que falha em produção, ou um rollback que não restaura a paridade.
