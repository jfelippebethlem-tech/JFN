# Experimento — instruindo a IA fraca (processo 330005/000030/2026)

- Documentos com fase objetiva (gabarito): 7 de 7
- **Concordância prompt INGÊNUO:** 100%
- **Concordância prompt INSTRUÍDO:** 100%
- **Ganho pela instrução explícita:** +0%

## Confusões mais comuns do prompt ingênuo


## Lições — como instruir a IA fraca

1. **Diga a fase PROCESSUAL, não o assunto.** A IA fraca lê 'Termo de Referência' e pensa 'contrato'; precisa da regra explícita de que TR é planejamento.
2. **Liste exemplos-âncora por fase** (o prompt instruído faz isso). Sem âncora, ela chuta pelo substantivo mais saliente.
3. **Dê a regra de ouro dos casos-armadilha** (TR≠contrato, Aditivo=execução, Liquidação=despesa).
4. **Force saída estruturada E normalize** (JSON; tire acento/caixa): a IA fraca devolve 'tramitação'/'seleção' — sem normalizar, vira falso desacordo em volume.
5. **Quando o gabarito é determinístico, use-o direto** (compliance_agent/sei/fases.py); a IA fraca só entra onde não há regra objetiva. É mais barato e não regride.