"""A rotina diária "BOM DIA do Mestre Jorge".

Esta é a funcionalidade-assinatura migrada do bot original. Lá, ela vivia como
um *template* (`bom-dia-template.md`) preenchido à mão; aqui, vira um roteiro
que o Hermes executa — usando a ferramenta de mercado (dados reais) e a busca
na web (notícias) — e devolve pronto.

A camada permanece agnóstica de plataforma: ela só *compõe* o texto. Enviar ao
Telegram é responsabilidade do `bot.py`.
"""

from __future__ import annotations

from .hermes import HermesAgent
from .protocol import AgentResponse

# Regras herdadas do template original, agora explícitas para o agente:
# - links de notícia sempre completos (jamais encurtados);
# - dados de mercado reais (ferramenta), nunca inventados;
# - Brasil e Rio de Janeiro, ambos.
BRIEFING_INSTRUCTIONS = """\
Monte a rotina matinal "BOM DIA DO MESTRE JORGE", para enviar agora no Telegram.

Use a ferramenta `get_market_data` para as cotações (dados reais) e a busca na
web para clima, notícias e contexto macroeconômico do dia. Se algo real faltar,
diga que faltou — nunca invente números nem manchetes.

Regras fixas (inegociáveis):
- NÃO encurtar links. Sempre a URL completa do portal.
- Dados de mercado reais (ferramenta). Nunca inventar números.
- Notícias do Brasil E do Rio de Janeiro, separadas.
- Português do Brasil. Tom Mestre Yoda, com moderação — clareza acima do estilo.

────────────────────────────────────────
ESTRUTURA OBRIGATÓRIA:

Bom dia, Mestre Jorge! 🌅

Clima — Barra da Tijuca: mínima/máxima e condição (busque na web).

Piada do dia: uma, curta e original.

Reflexão: versículo bíblico curto, com referência (livro capítulo:versículo).

📊 MERCADO
Cotações (da ferramenta): Dólar USD/BRL, Ibovespa, Ouro, Petróleo WTI — com
variação do dia em pontos e percentual.
Fonte: https://economia.uol.com.br/cotacoes/

🔍 ANÁLISE (estilo Massare — analista autônomo de mercado)
Em 4–6 linhas diretas (sem inversão Yoda nesta seção):
1. Correlação câmbio × Ibovespa: o movimento do dólar está pressionando ou
   aliviando a bolsa? Por quê?
2. Commodities: ouro e petróleo convergem ou divergem hoje? O que sinaliza
   para os setores de energia e mineração na B3?
3. Fator macro do dia: há dado econômico (EUA, China, Brasil) ou evento
   político que pode mover o mercado ao longo do dia? Cite o evento e o
   sentido esperado do impacto.
4. Oportunidade ou risco imediato: uma frase objetiva — o que o Mestre Jorge
   deve monitorar hoje.

📰 NOTÍCIAS DO BRASIL (até 5)
Cada uma: manchete + URL completa (UOL, Folha, G1, O Globo, Valor, Estadão).

📰 NOTÍCIAS DO RIO DE JANEIRO (até 5)
Mesmo formato, com URLs completas.

Encerre com uma saudação curta ao Mestre Jorge. 💪
────────────────────────────────────────
"""


async def compose_briefing(agent: HermesAgent) -> AgentResponse:
    """Pede ao Hermes que monte a rotina diária e devolve a resposta."""
    return await agent.compose(BRIEFING_INSTRUCTIONS)
