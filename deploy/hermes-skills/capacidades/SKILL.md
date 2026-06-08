---
name: capacidades
description: Mostra a skilltree do JFN (capacidades por dominio) e gerencia o registro a quente. Use quando o usuario pedir "/capacidades", "o que voce sabe fazer", "quais skills/capacidades", ou detalhe/recarga/validacao do registro.
version: 1.0.0
metadata:
  hermes:
    tags: [jfn, skilltree, capacidades, registro]
    category: jfn
---

# Capacidades (skilltree do JFN)

O registro vivo de capacidades do JFN e o `capabilities.yaml`, exposto pela API do motor JFN
em `http://127.0.0.1:8000`. Use a ferramenta de terminal com `curl` (NUNCA invente ferramenta).

Quando o usuario usar **/capacidades** (ou pedir as skills/capacidades), faca:

- **/capacidades** ou **/capacidades <filtro>** (lista a arvore por dominio):
  `curl -s "http://127.0.0.1:8000/api/skills?filtro=<FILTRO>"` e mostre o campo `texto` (Markdown).
- **/capacidades skill <id>** (detalhe de uma capacidade):
  `curl -s "http://127.0.0.1:8000/api/skill?id=<ID>"` e mostre `texto`.
- **/capacidades reload** (recarrega o capabilities.yaml a quente — fail-safe):
  `curl -s -X POST "http://127.0.0.1:8000/api/skills/reload"` e resuma `{sha,total,add,rm}`.
- **/capacidades validate** (valida o contrato; rotas PRONTO existem no server):
  `curl -s "http://127.0.0.1:8000/api/skills/validate"` e diga se `ok` ou liste `problemas`.

Sempre entregue o resultado direto (sem narrar). E a fonte unica das capacidades do ecossistema —
toda skill nova aparece aqui. Honesto: nunca invente capacidade fora do registro.
