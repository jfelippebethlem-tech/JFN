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
web para clima e notícias do dia. Se algo real faltar, diga que faltou — nunca
invente números nem manchetes.

Regras fixas (do formato oficial):
- NÃO encurtar links. Sempre a URL completa do portal.
- Dados de mercado reais (dólar, Ibovespa, ouro, petróleo). Sem inventar.
- Notícias do Brasil E do Rio de Janeiro, separadas.
- Português do Brasil. Tom Mestre Yoda, com moderação — clareza acima do estilo.

Estrutura da mensagem:

Bom dia, Mestre Jorge! 🌅

Clima — Barra da Tijuca: mínima/máxima e condição (busque na web).

Piada do dia: uma, curta e original.

Reflexão: um versículo bíblico curto, com a referência (livro capítulo:versículo).

📊 MERCADO
- Dólar comercial, Ibovespa, ouro e petróleo WTI, com a variação do dia.
- Uma a duas linhas de leitura cruzada (política + mercado).
- Fonte: https://economia.uol.com.br/cotacoes/

📰 NOTÍCIAS DO BRASIL (até 5)
- Cada uma: manchete em uma linha + a URL completa do portal (UOL, Folha, G1, O Globo).

📰 NOTÍCIAS DO RIO DE JANEIRO (até 5)
- Mesmo formato, com URLs completas.

Encerre com uma saudação curta ao Mestre Jorge. 💪
"""


async def compose_briefing(agent: HermesAgent) -> AgentResponse:
    """Pede ao Hermes que monte a rotina diária e devolve a resposta."""
    return await agent.compose(BRIEFING_INSTRUCTIONS)
