# Próxima sessão — começar AQUI (cole o conteúdo abaixo ou diga "leia docs/PROXIMA-SESSAO.md")

**Continuação JFN — leia o handoff primeiro.**

Estou no projeto `~/JFN`, branch **`feat/lista-limpa`** (live, tudo commitado). Antes de qualquer coisa, leia nesta ordem:
1. `docs/HANDOFF-2026-06-09-LOOP-RETOMADA.md` (estado vivo, como religar, fatos-chave, o que NÃO repetir)
2. `docs/LOOP-MELHORIA-2026-06-09.md` (os 5 loops já feitos, com erros & acertos)
3. A lição em memória `licao-v2-revertida-2026-06-08` (princípios: mudança **pequena/isolada/verificada com o artefato real**; **nunca LLM no hot-path** sem cache+bound; wiring mínimo)

**Contexto rápido:** `jfn.service` é **user service** (`systemctl --user restart jfn.service`); LLM válido só Gemini (9 chaves em `~/.hermes/.env`); bot vivo = Hermes gateway (`cd ~/hermes-agent && PYTHONPATH=. venv/bin/python -m hermes_cli.main -z "msg"` pra testar). Tenho **autonomia total** pra mexer em tudo (JFN/Lex/Massare/Hermes/Yoda) e religar à vontade. Visão: outputs perfeitos, integrado/baixa-fricção, grátis, rápido, belo, **sistema pensante** em JFN/Lex/Massare.

**Prioridade (os 2 fixes profundos que fecham o "último elo do sistema pensante" — precisam Chrome ao vivo + teste do artefato real):**
1. **Coletor SEI → inteiro teor:** `collectors/sei_cdp.py::ler_processo_sei_via_chrome` hoje fica na caixa/desktop e não abre o processo (frames `ifrArvore`/`ifrVisualizacao`). Conserte e teste ao vivo com `SEI-070002/004332/2024` até `n documentos > 0`. Isso destrava a análise discursiva do Lex (já pronta, esperando input).
2. **Scorer OOS do Massare:** 44 previsões pendentes, 0 resolvidas, `hit_rate=null` em `/api/massare/placar`. Rode/agende a cobrança contra o realizado (`massare/validation.py`/`learning.db`).

Continue o **loop de melhoria** (backtest → análise crítica do artefato → reavaliação → plano → execução → checkpoint+commit+doc de erros/acertos), gerando `/relatorio` e `/orgao` reais pra reavaliar a qualidade. Documente tudo pra próxima IA.
