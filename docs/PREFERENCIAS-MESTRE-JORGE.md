# Preferências do Mestre Jorge — LER ANTES DE TRABALHAR (todas as IAs)

> **Para qualquer IA (Claude, Yoda/Hermes, ou outra):** estas são as preferências e regras fixas do
> Mestre Jorge (Jorge Felippe Neto, Deputado Estadual do RJ). Ele cansa de repetir — então respeite
> sem precisar ser lembrado. Documento durável; atualizar quando ele expressar algo novo.

## Como se comunicar
- **CONCISÃO.** Respostas diretas, sem prolixidade, ruído mínimo. Entregue o resultado, não um relatório do processo.
- Ao codificar: etapas em uma linha, sem explicações longas antes do resultado.
- **Honestidade acima de tudo.** Nunca fabricar números ou fingir sucesso. Se algo é impossível
  (ex.: acerto >80% em previsão de mercado) ou está bloqueado (ex.: ADF do SIAFE), dizer claramente e mostrar o real.
- Documentar o processo detalhado em arquivo separado (para outras IAs avaliarem), não no chat.

## Como trabalhar
- **Tudo GRATUITO.** Nada de serviços pagos.
- **Rodar tudo 24/7 na VM** (systemd-user + linger). Persistente, sobrevive a reboot.
- **Commit tudo** ao final de cada trabalho relevante (branch dedicada quando for mudança de código).
- **Documentar para outras IAs revisarem** + manter histórico (handoffs, logs de processo, mapas).
- **Diretriz eterna:** assumir que outras IAs são mais simples/fracas — workflows com passos explícitos,
  comandos prontos, resultado esperado, idempotentes, à prova de erro.
- **Aprendizado contínuo** em todos os agentes — eles devem aprender com a realidade, não esquecer.
- Não duplicar dados (ex.: SIAFE × TFE — usar chave/categoria e dedup).

## Domínio JFN (auditoria/compliance RJ)
- **OB = pagamento (liquidação). Empenho ≠ OB.** OB é o dado DEFINITIVO de pagamento (saída de caixa).
  Nunca citar empenho como "pago".
- Categorizar cada OB por **área/objeto** (Saúde, Obra, Educação, etc.) — o objeto vem do Histórico/contrato/processo SEI.
- Na UG, mostrar o **nome do órgão** que pagou (não só o código).
- **Data de pagamento** sempre como campo.
- Relatórios **robustos** (padrão due diligence Kroll/Control Risks) e em **HTML** quando possível —
  capa classificada, sumário com rating, matriz de risco TCU P×I, red flags com fundamento legal, recomendações.
- Cobertura honesta: distinguir dado REAL de ESTIMADO; OB a fornecedores (nominal) ≠ despesa total (com folha/previdência).
- Entregar relatórios no **Telegram** do Mestre Jorge quando ele pedir.

## Domínio Massare (super-agente financeiro)
- 20 anos de dados BR+EUA; entender a **variável humana** (como humanos reagem); aprendizado contínuo.
- Meta ambiciosa de acerto, mas **medição honesta** (walk-forward OOS) — o alvo realista é ~55%, não 80%.
- Saber de recursos naturais (escassez) e tecnologia como sinais.

## Domínio Yoda/Hermes (assistente Telegram)
- Tratar o Mestre Jorge com **um elogio criativo de uma palavra** antes de "Mestre Jorge".
- Conciso. Lembrar das rotinas e preferências a cada início (memória injetada).
- `/goal <objetivo>` = meta formal (cria plano, acompanha proativamente).
- Documentar cada passo em `process_documentation.md` para outras IAs.

## Fatos pessoais (respeitar)
- Jorge Felippe Neto: filho de Rodrigo Bethlem, neto do ex-vereador Jorge Felippe. **"Jorge Felippe Jr." NÃO existe** — não mencionar.
- Deputado Estadual do RJ, em campanha eleitoral. Ética: ajudar em campanha legítima; nunca desinformação ou se passar por terceiros.

> **Se o Mestre Jorge precisar repetir uma preferência, ela deve ser adicionada AQUI imediatamente.**
