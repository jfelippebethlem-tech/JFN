# Aprendizado Contínuo — JFN · Massare · Yoda · Hermes

Princípio comum: **todo agente é cobrado pela realidade e se ajusta** — registra o que prevê/decide,
compara com o que aconteceu, e atualiza pesos/regras/memória. Nada de número inventado; o aprendizado
é medido. Loja compartilhada de lições: tabela `lessons` em `massare/data/massare.db`
(`massare.learning.add_lesson(agent, topic, lesson, evidence)` / `recent_lessons(agent)`).

## Massare (operacional ✅)
- **Sinais**: ensemble de sub-estratégias (momentum/trend/meanrev/rsi/sentimento) com **pesos
  adaptativos** — cada sub ganha voz proporcional à sua taxa de acerto recente (aprendizado online).
- **Avaliação honesta**: walk-forward out-of-sample (`engine.walk_forward`). Resultado real medido:
  S&P 55,4% · Nasdaq 55,2% · ouro 54,2% · BTC 53,1% (h=5d). Alvo honesto 54–56%, não 80%.
- **Ciclo 24/7** (`massare.daily`, systemd-timer 07:30 UTC): atualiza dados → **avalia previsões
  vencidas** (grade_due) → gera+registra previsão do dia → placar OOS acumulado + sentimento.
  Toda previsão de hoje é avaliada automaticamente nos próximos dias = feedback real.
- **Variável humana** (`behavior.py`): Fear&Greed, VIX, curva de juros condicionam o sinal.

## JFN (em evolução)
- **Hoje**: motor de regras/red-flags (Lei 14.133, fracionamento, sobrepreço, concentração HHI) e
  pipeline de hipóteses (analisar→padrões→hipóteses→testar). Bugs de LLM corrigidos (qwen/groq).
- **Aprendizado a plugar** (design): cada red-flag tem um **peso**; quando uma hipótese é
  **confirmada/refutada** (pelo usuário ou por evidência cruzada), o peso sobe/desce — o score de
  risco aprende quais sinais de fato indicam irregularidade no RJ, reduzindo falso-positivo
  (meta do `environment_hint`). Registrar cada veredito em `lessons(agent='jfn')` + persistir pesos.
- **Fontes que realimentam** (pesquisa salva): PNCP, dados abertos RJ (espelho TFE), TCE-RJ,
  CEIS/CNEP, BrasilAPI (QSA p/ grafo de sócios), Querido Diário.

## Yoda / Hermes (memória + correções)
- **Memória própria** (`~/.hermes/memories/USER.md` e `MEMORY.md`) injetada no system prompt a cada
  início de sessão = lembra preferências/rotinas/correções continuamente.
- **Correção do bug que travava o aprendizado**: o `replace/remove` da memória exigia substring
  exata; agora resolve por `#índice` + erros acionáveis (branch `claude/fix-memory-resolve-for-weaker-models`,
  76 testes). Limites de memória aumentados (1375→4000). Resultado: Yoda voltou a salvar diretrizes sozinho.
- **Lições estruturadas**: além da memória conversacional, gravar aprendizados duráveis em
  `lessons(agent='yoda')` para auditoria/versionamento.

## Como medir (sem se enganar)
- Massare: `learning.scoreboard()` → acerto OOS real por horizonte/modelo. Walk-forward + sem look-ahead.
- JFN: precisão/recall das red-flags contra vereditos confirmados; taxa de falso-positivo.
- Yoda: o usuário deixou de repetir a mesma correção? (sinal de que a memória aprendeu.)
- Regra de ouro: **só promove o que sobrevive out-of-sample / na realidade**, nunca o que brilha in-sample.

## Próximos passos
1. JFN: implementar pesos adaptativos das red-flags + persistência + endpoint de feedback.
2. Massare: features lag-safe (pandas-ta), regime HMM, XGBoost vs baseline (gate OOS), backtest com custos.
3. Unificar `lessons` num briefing semanal por agente (o que aprendeu, o que mudou).
