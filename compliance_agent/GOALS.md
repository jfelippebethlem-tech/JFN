# JFN — Goal Contract

Objetivo central: agente de auditoria e compliance para o Estado do RJ, confiável, gratuito e operável por WhatsApp/Telegram + painel local.

## Estado atual oficial
- Branch: `claude/rj-finance-agent-BYlhJ`
- Repo: `https://github.com/jfelippebethlem-tech/JFN`
- Telegram ativo, chat ID `45338178`
- OpenRouter/Groq como LLM gratuito principal

## Metas executáveis em andamento
1. Eliminar falhas silenciosas em `free_llm.py` e `telegram.py`
2. Tornar todo retry de API explícito e observável (429, timeout, 5xx)
3. Unificar routing entre Groq/OpenRouter/Hermes sem duplicação
4. Manter zero segredos no repositório; `.env.txt` ignorado
