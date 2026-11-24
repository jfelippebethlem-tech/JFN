# ADR-008 — Segurança de produção

| Campo | Valor |
|---|---|
| **Estado** | Proposto (esqueleto da O1.4, 24/11/2026). A decisão final sai na onda indicada no plano |
| **Plano** | `~/vault/refatoracao/PLANO-MESTRE-v2-esteira-unica.md`; questão do doc 2 §31 |
| **Questão** | Como autenticar, autorizar, segregar a rede, gerir segredos e auditar a exportação? |
| **Relacionados** | ADR-001 (autoridade de dados), ADR-012 (motor `jfn-fluxo`) |

## Contexto

Na linha de base: autenticação que falhava aberta, bind em todas as interfaces, sem cookie Secure, SSRF no solucionador de captcha, um workflow que aceitava credencial como input, nenhum scanner de PII ou segredo. A O0.3 já fechou bind, cookie e modo manutenção (§16.8).

## Decisão

- Boot falha-fechado sem senha forte (mínimo de 20 caracteres em produção).
- Bind local; acesso externo só pelo túnel autenticado.
- Segredos só em arquivo fora do git, lidos por variável de ambiente.
- Scanner de CPF e de segredo no pre-commit e no CI.
- Egress com lista de permissão para quem busca URL (SSRF).
- Exportação de dossiê registrada (quem, quando, hash).

## Consequências

Superfície mínima num repo público. O custo é que a troca de senha e a ativação de `JFN_ENV=producao` dependem do dono.

## Não adotar

Limpar o histórico do repo agora (é a decisão 5 do dono: só na O9.4, com ok). Expor a porta do painel na rede privada sem login.

## Gatilho de reavaliação

Incidente ou tentativa registrada, um segredo achado pelo scanner, ou uma mudança de exposição (porta nova ou túnel novo).
