"""
Agente de Compliance & Auditoria — 100% gratuito.

Loop principal usa Groq (llama-3.3-70b) ou OpenRouter como LLM.
Anthropic API é opcional: se ANTHROPIC_API_KEY estiver no .env,
usa Claude para análises que exigem raciocínio mais sofisticado.
"""

import asyncio
import json
import os
from datetime import date
from pathlib import Path
from typing import Optional, Any

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from compliance_agent.database.models import (
    Alerta, Empresa, Pessoa, RegistroFolha, PublicacaoDOERJ,
    get_session, init_db,
)
from compliance_agent.collectors.cnpj import buscar_cnpj, salvar_empresa
from compliance_agent.collectors.doerj import DOERJCollector
from compliance_agent.collectors.transparency import TransparenciaRJCollector
from compliance_agent.rules.engine import MotorCompliance
from compliance_agent.rules.preco import AnalisadorPrecos
from compliance_agent.graph import GrafoRelacionamentos

console = Console()

SYSTEM_PROMPT = """Você é um agente especialista em compliance, auditoria e inteligência anticorrupção
para o governo do Estado do Rio de Janeiro.

Você tem acesso a ferramentas para:
1. Consultar CNPJ de empresas (sócios, situação, histórico)
2. Coletar publicações do DOERJ (Diário Oficial do Estado do RJ)
3. Buscar dados da folha de pagamento (Portal de Transparência RJ)
4. Executar regras de compliance (acúmulo, fantasma, nepotismo, fracionamento)
5. Analisar o grafo de relacionamentos (quem se conecta com quem)
6. Buscar alertas já gerados no banco de dados
7. Investigar processos SEI cruzando com dados públicos

Bases legais que você conhece:
- Lei 14.133/21 (Nova Lei de Licitações) — limites: dispensa até R$ 50k (serviços), R$ 30k (obras)
- Lei 8.429/92 (Improbidade Administrativa)
- Súmula Vinculante 13 (vedação ao nepotismo)
- CF/88 art. 37, XVI (vedação ao acúmulo de cargos)
- Lei de Acesso à Informação (LAI) — Lei 12.527/11

Padrões de corrupção que você conhece:
- Funcionário fantasma: na folha mas sem trabalho real, remuneração zero, CPF duplicado
- Nepotismo: empresa de familiar/cônjuge recebendo contratos do mesmo órgão
- Fracionamento: dividir compra em pedaços para evitar licitação
- Direcionamento: edital com especificações que só uma empresa consegue atender
- Empresa de fachada: CNPJ novo, endereço residencial, sócio servidor público
- Nomeação política: cargo após doação eleitoral, parente de parlamentar

Como responder:
- Seja objetivo e direto. Use dados concretos (valores, datas, nomes, CPF/CNPJ)
- Indique a base legal de cada irregularidade
- Classifique a severidade: ALTA (ilícito claro), MÉDIA (indício forte), BAIXA (verificar)
- Use tabelas markdown para dados comparativos
- Ao final de cada investigação, liste: achados, base legal, próximos passos
- Não invente dados — use apenas o que as ferramentas retornarem

Formato de valores: R$ 1.234.567,89
Formato de datas: DD/MM/AAAA
"""

# ── Definição das ferramentas (formato OpenAI / Groq) ─────────────────────────

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "consultar_cnpj",
            "description": "Consulta dados de uma empresa pelo CNPJ: razão social, sócios, situação, data de abertura, capital social.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cnpj": {"type": "string", "description": "CNPJ da empresa (com ou sem formatação)"},
                },
                "required": ["cnpj"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_servidor",
            "description": "Busca dados de servidor público pelo nome ou CPF no Portal de Transparência RJ.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome": {"type": "string", "description": "Nome do servidor (parcial ou completo)"},
                    "cpf":  {"type": "string", "description": "CPF do servidor"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "coletar_doerj",
            "description": "Coleta publicações do Diário Oficial do Estado do RJ.",
            "parameters": {
                "type": "object",
                "properties": {
                    "data":        {"type": "string", "description": "Data no formato AAAA-MM-DD. Se omitido, usa hoje."},
                    "data_inicio": {"type": "string", "description": "Data inicial para período (AAAA-MM-DD)"},
                    "data_fim":    {"type": "string", "description": "Data final para período (AAAA-MM-DD)"},
                    "tipo_ato":    {"type": "string", "description": "Filtrar por tipo: nomeação | exoneração | contrato | licitação | aposentadoria"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_contratos_empresa",
            "description": "Busca todos os contratos celebrados com uma empresa pelo CNPJ no Portal de Transparência RJ.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cnpj": {"type": "string", "description": "CNPJ da empresa"},
                },
                "required": ["cnpj"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "executar_compliance",
            "description": "Executa todas as regras de compliance contra o banco de dados e retorna alertas novos gerados.",
            "parameters": {
                "type": "object",
                "properties": {
                    "competencia": {"type": "string", "description": "Competência da folha (AAAA-MM). Opcional."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_alertas",
            "description": "Lista alertas de compliance já gerados, com filtros por tipo e severidade.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo":       {"type": "string", "description": "Tipo: fantasma | nepotismo | fracionamento | acumulacao | enriquecimento | direcionamento"},
                    "severidade": {"type": "string", "description": "Severidade: alta | média | baixa"},
                    "limite":     {"type": "integer", "description": "Quantidade máxima de alertas (padrão 20)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analisar_conexoes",
            "description": "Analisa o grafo de relacionamentos de uma pessoa ou empresa.",
            "parameters": {
                "type": "object",
                "properties": {
                    "identificador": {"type": "string", "description": "CPF, CNPJ ou nome parcial do ator"},
                },
                "required": ["identificador"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "caminho_entre_atores",
            "description": "Encontra o caminho mais curto entre dois atores no grafo de relacionamentos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ator_a": {"type": "string", "description": "CPF, CNPJ ou nome do primeiro ator"},
                    "ator_b": {"type": "string", "description": "CPF, CNPJ ou nome do segundo ator"},
                },
                "required": ["ator_a", "ator_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "atores_mais_conectados",
            "description": "Lista as pessoas e empresas com mais conexões no grafo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "top_n": {"type": "integer", "description": "Quantos atores listar (padrão 20)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analisar_precos",
            "description": "Analisa divergências de preço entre contratos similares. Detecta superfaturamento por categoria.",
            "parameters": {
                "type": "object",
                "properties": {
                    "categoria": {
                        "type": "string",
                        "description": "Categoria: veículos | combustível | informática | limpeza | alimentação | obras | saúde | segurança | consultoria | mobiliário | telefonia | transporte",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_doerj_banco",
            "description": "Busca publicações do DOERJ já indexadas no banco, por tipo ou palavra-chave.",
            "parameters": {
                "type": "object",
                "properties": {
                    "palavra_chave": {"type": "string"},
                    "tipo_ato":      {"type": "string"},
                    "data_inicio":   {"type": "string"},
                    "data_fim":      {"type": "string"},
                    "limite":        {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detectar_cpf_duplicado",
            "description": "Detecta CPFs simultâneos em múltiplas fontes: servidores, terceirizados, bolsistas, estagiários, aposentados.",
            "parameters": {
                "type": "object",
                "properties": {
                    "competencia": {"type": "string", "description": "AAAA-MM"},
                    "cpf":         {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_local",
            "description": "Busca rápida local (sem custo de API) em contratos, DOERJ e alertas usando índice FTS5.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query":  {"type": "string", "description": "Termo de busca"},
                    "tabela": {"type": "string", "description": "contratos | doerj | alertas | todos"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_doacoes_eleitorais",
            "description": "Busca doações eleitorais (TSE) feitas por pessoa ou empresa. Cruza com contratos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cpf_cnpj":    {"type": "string"},
                    "nome":        {"type": "string"},
                    "ano_eleicao": {"type": "integer", "description": "2018, 2020, 2022, 2024"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_decisoes_tce",
            "description": "Busca decisões e condenações do TCE-RJ para uma empresa ou pessoa.",
            "parameters": {
                "type": "object",
                "properties": {
                    "termo": {"type": "string", "description": "Nome da empresa, pessoa ou CNPJ"},
                },
                "required": ["termo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verificar_emprego_multiplo",
            "description": "Verifica se um CPF aparece com emprego simultâneo em múltiplos órgãos (estado, ALERJ, TJRJ, MPRJ, Defensoria).",
            "parameters": {
                "type": "object",
                "properties": {
                    "cpf":         {"type": "string"},
                    "competencia": {"type": "string", "description": "AAAA-MM"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "status_orcamento",
            "description": "Mostra quantos tokens foram usados este mês e quais LLMs gratuitos estão ativos.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "baixar_folha_orgao",
            "description": "Baixa e indexa a folha de pagamento de órgãos externos: ALERJ, TJRJ, MPRJ, Defensoria Pública.",
            "parameters": {
                "type": "object",
                "properties": {
                    "orgao": {"type": "string", "description": "alerj | tjrj | mprj | defensoria"},
                },
                "required": ["orgao"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_sei",
            "description": "Consulta processo SEI no Portal SEI-RJ. Busca metadados, documentos, cruza com SIAFE e detecta irregularidades.",
            "parameters": {
                "type": "object",
                "properties": {
                    "numero_sei":     {"type": "string", "description": "Ex: E-18/001234/2024"},
                    "ler_documentos": {"type": "boolean"},
                },
                "required": ["numero_sei"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_sei_por_termo",
            "description": "Busca processos SEI indexados no banco por termo no assunto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "termo": {"type": "string", "description": "Ex: reforma escola, SEEDUC, licitação"},
                },
                "required": ["termo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reconhecer_padrao_fraude",
            "description": "Compara texto contra base de padrões de fraude e casos históricos do RJ. Zero custo de API.",
            "parameters": {
                "type": "object",
                "properties": {
                    "texto":      {"type": "string"},
                    "objeto":     {"type": "string"},
                    "orgao":      {"type": "string"},
                    "modalidade": {"type": "string"},
                    "valor":      {"type": "number"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "status_llm_gratuito",
            "description": "Mostra quais LLMs gratuitos estão disponíveis (Ollama, Groq, OpenRouter) e como configurar.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


# ── Configuração de provedores ─────────────────────────────────────────────────

_GROQ_BASE       = "https://api.groq.com/openai/v1"
_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_ANTHROPIC_BASE  = "https://api.anthropic.com"

_GROQ_MODEL      = "llama-3.3-70b-versatile"
_ANTHROPIC_MODEL = "claude-opus-4-8"


def _openrouter_model() -> str:
    """Usa OPENROUTER_SMART_MODEL do .env (Hermes-3 por padrão)."""
    return os.environ.get("OPENROUTER_SMART_MODEL", "nousresearch/hermes-3-llama-3.1-405b:free")


def _detect_provider() -> tuple[str, str, str]:
    """
    Detecta qual provedor usar com base nas chaves do .env.
    Retorna (provider_name, api_key, model).

    Ordem padrão: groq → openrouter → anthropic.
    Para usar Hermes (OpenRouter) como principal, defina no .env:
        FREE_LLM_PREFER=openrouter
    """
    groq_key       = os.environ.get("GROQ_API_KEY", "").strip()
    anthropic_key  = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    prefer         = os.environ.get("FREE_LLM_PREFER", "groq").lower()

    # Monta lista de preferência respeitando FREE_LLM_PREFER
    free_options = [
        ("groq",       groq_key,       _GROQ_MODEL),
        ("openrouter", openrouter_key, _openrouter_model()),
    ]
    if prefer == "openrouter":
        free_options = list(reversed(free_options))

    for name, key, model in free_options:
        if key:
            return name, key, model

    if anthropic_key:
        return "anthropic", anthropic_key, _ANTHROPIC_MODEL

    raise RuntimeError(
        "\n\n❌  Nenhuma chave de LLM configurada!\n\n"
        "Abra o arquivo .env e preencha pelo menos uma das opções GRATUITAS:\n\n"
        "  GROQ_API_KEY=sua_chave_aqui      ← grátis em console.groq.com\n"
        "  OPENROUTER_API_KEY=sua_chave     ← grátis em openrouter.ai (Hermes-3)\n\n"
        "Dica: para usar o Hermes como principal, adicione também:\n"
        "  FREE_LLM_PREFER=openrouter\n"
    )


# ── Chamada HTTP ao LLM (formato OpenAI / Groq) ───────────────────────────────

def _detect_fallback() -> tuple[str, str, str] | tuple[None, None, None]:
    """Retorna o segundo provedor disponível para usar quando o principal retornar 429."""
    groq_key       = os.environ.get("GROQ_API_KEY", "").strip()
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    prefer         = os.environ.get("FREE_LLM_PREFER", "groq").lower()

    if prefer == "openrouter":
        # principal é openrouter → fallback é groq
        return ("groq", groq_key, _GROQ_MODEL) if groq_key else (None, None, None)
    else:
        # principal é groq → fallback é openrouter
        return ("openrouter", openrouter_key, _openrouter_model()) if openrouter_key else (None, None, None)


async def _call_one(
    provider: str, api_key: str, model: str,
    messages: list[dict], tools: list[dict], max_tokens: int,
) -> dict:
    """Faz uma única chamada HTTP ao LLM. Levanta httpx.HTTPStatusError em caso de erro."""
    if provider == "anthropic":
        return await _anthropic_request(api_key, model, messages, tools, max_tokens)

    base = _GROQ_BASE if provider == "groq" else _OPENROUTER_BASE
    url  = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/jfn/compliance-agent"
        headers["X-Title"] = "JFN Compliance Agent"

    payload: dict = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.1}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _llm_request(
    provider: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict],
    max_tokens: int = 8192,
    fallback: tuple | None = None,
) -> dict:
    """
    Envia requisição com retry automático e fallback.
    Se receber 429 (rate limit), espera 3s e tenta de novo.
    Se ainda 429, usa o provedor fallback (ex: OpenRouter quando Groq está lotado).
    """
    for attempt in range(2):
        try:
            return await _call_one(provider, api_key, model, messages, tools, max_tokens)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                if attempt == 0:
                    console.print(f"[yellow]⏳ {provider} está no limite de taxa — aguardando 3s...[/yellow]")
                    await asyncio.sleep(3)
                    continue
                # Depois de 2 tentativas, tenta fallback
                if fallback and fallback[0]:
                    fb_provider, fb_key, fb_model = fallback
                    console.print(f"[yellow]↩ Usando fallback: {fb_provider} ({fb_model})[/yellow]")
                    return await _call_one(fb_provider, fb_key, fb_model, messages, tools, max_tokens)
                raise RuntimeError(
                    f"❌ {provider} está com limite de taxa esgotado (429).\n"
                    "Aguarde 1 minuto e tente novamente, ou configure um segundo LLM gratuito:\n"
                    "  Se usa Groq → adicione OPENROUTER_API_KEY no .env\n"
                    "  Se usa OpenRouter → adicione GROQ_API_KEY no .env"
                ) from e
            raise


async def _anthropic_request(
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict],
    max_tokens: int,
) -> dict:
    """
    Chama a API Anthropic e converte a resposta para formato OpenAI
    para que o loop do agente seja idêntico.
    """
    # Converte tools de OpenAI → Anthropic
    anthropic_tools = [
        {
            "name": t["function"]["name"],
            "description": t["function"].get("description", ""),
            "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}}),
        }
        for t in tools
    ]

    # Separa system do histórico (Anthropic quer system separado)
    system_msg = ""
    history = []
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        else:
            history.append(m)

    payload: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_msg,
        "messages": history,
    }
    if anthropic_tools:
        payload["tools"] = anthropic_tools

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{_ANTHROPIC_BASE}/v1/messages",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()

    # Converte resposta Anthropic → formato OpenAI
    content_blocks = data.get("content", [])
    text_parts = [b["text"] for b in content_blocks if b.get("type") == "text"]
    tool_calls_raw = [b for b in content_blocks if b.get("type") == "tool_use"]

    message: dict = {"role": "assistant", "content": " ".join(text_parts) or None}
    if tool_calls_raw:
        message["tool_calls"] = [
            {
                "id": b["id"],
                "type": "function",
                "function": {
                    "name": b["name"],
                    "arguments": json.dumps(b.get("input", {}), ensure_ascii=False),
                },
            }
            for b in tool_calls_raw
        ]

    stop_reason = data.get("stop_reason", "end_turn")
    finish_reason = "tool_calls" if tool_calls_raw else "stop"

    return {
        "choices": [{"message": message, "finish_reason": finish_reason}]
    }


# ── Agente principal ──────────────────────────────────────────────────────────

class ComplianceAgent:
    """Agente de compliance gratuito: Groq (llama-3.3-70b) ou OpenRouter."""

    def __init__(self):
        self._provider, self._api_key, self._model = _detect_provider()
        self._fallback = _detect_fallback()
        self._session = get_session()
        init_db()
        self._grafo = GrafoRelacionamentos(self._session)
        self._grafo_built = False
        self._conversation: list[dict] = []

        provider_label = {
            "groq": f"Groq ({self._model}) — grátis",
            "openrouter": f"OpenRouter ({self._model}) — grátis",
            "anthropic": f"Anthropic ({self._model}) — pago",
        }.get(self._provider, self._provider)
        fb_label = f" | fallback: {self._fallback[0]}" if self._fallback[0] else ""
        console.print(f"[dim]LLM: {provider_label}{fb_label}[/dim]")

    def _ensure_grafo(self):
        if not self._grafo_built:
            self._grafo.construir()
            self._grafo_built = True

    # ── API pública ───────────────────────────────────────────────────────────

    async def chat(self, user_message: str) -> str:
        self._conversation.append({"role": "user", "content": user_message})

        # Monta histórico com system prompt na frente
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self._conversation

        while True:
            data = await _llm_request(
                self._provider, self._api_key, self._model,
                messages, TOOLS,
                fallback=self._fallback,
            )

            choice  = data["choices"][0]
            msg     = choice["message"]
            finish  = choice.get("finish_reason", "stop")

            # Armazena mensagem do assistente na conversa
            self._conversation.append(msg)
            messages.append(msg)

            tool_calls = msg.get("tool_calls") or []

            if finish == "stop" or not tool_calls:
                return msg.get("content") or ""

            # Executa ferramentas e devolve resultados
            for tc in tool_calls:
                fn   = tc["function"]
                name = fn["name"]
                try:
                    args = fn.get("arguments") or "{}"
                    inputs = json.loads(args) if isinstance(args, str) else {}
                except (json.JSONDecodeError, TypeError):
                    inputs = {}

                console.print(f"[dim]⚙ {name}({json.dumps(inputs, ensure_ascii=False)[:120]})[/dim]")
                result = await self._execute_tool(name, inputs)

                tool_result_msg = {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
                self._conversation.append(tool_result_msg)
                messages.append(tool_result_msg)

    async def run_interactive(self):
        provider_info = {
            "groq": "Groq (llama-3.3-70b) — 100% gratuito",
            "openrouter": "OpenRouter — 100% gratuito",
            "anthropic": "Claude (Anthropic) — requer API key paga",
        }.get(self._provider, self._provider)

        console.print(Panel(
            f"[bold red]⚖ Agente de Compliance & Auditoria — RJ[/bold red]\n"
            f"LLM: [green]{provider_info}[/green]\n"
            "Investigo corrupção, nepotismo, fantasmas, licitações irregulares e redes de influência.\n"
            "Digite 'sair' para encerrar.",
            title="JFN Compliance",
        ))

        while True:
            try:
                user_input = input("\n[Investigador] ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if user_input.lower() in {"sair", "exit", "q"}:
                break
            if not user_input:
                continue
            response = await self.chat(user_input)
            console.print("\n[bold yellow]Agente:[/bold yellow]")
            console.print(Markdown(response))

    # ── Dispatcher de ferramentas ──────────────────────────────────────────────

    async def _execute_tool(self, name: str, inputs: dict) -> Any:
        try:
            match name:
                case "consultar_cnpj":
                    dados = await buscar_cnpj(inputs["cnpj"])
                    if "error" not in dados:
                        salvar_empresa(dados, self._session)
                        self._grafo_built = False
                    return dados

                case "buscar_servidor":
                    collector = TransparenciaRJCollector(self._session)
                    if inputs.get("cpf"):
                        return await collector.buscar_servidor_por_cpf(inputs["cpf"])
                    elif inputs.get("nome"):
                        return await collector.buscar_servidor_por_nome(inputs["nome"])
                    return {"error": "Informe nome ou CPF."}

                case "coletar_doerj":
                    collector = DOERJCollector(self._session)
                    if inputs.get("data_inicio"):
                        inicio = date.fromisoformat(inputs["data_inicio"])
                        fim    = date.fromisoformat(inputs.get("data_fim", date.today().isoformat()))
                        pubs   = await collector.coletar_periodo(inicio, fim)
                    elif inputs.get("data"):
                        pubs = await collector.coletar_data(date.fromisoformat(inputs["data"]))
                    else:
                        pubs = await collector.coletar_hoje()

                    tipo_filtro = inputs.get("tipo_ato")
                    if tipo_filtro:
                        pubs = [p for p in pubs if p.get("tipo_ato") == tipo_filtro]

                    self._grafo_built = False
                    return {"total": len(pubs), "publicacoes": pubs[:30]}

                case "buscar_contratos_empresa":
                    collector = TransparenciaRJCollector(self._session)
                    return await collector.buscar_contratos_empresa(inputs["cnpj"])

                case "executar_compliance":
                    motor = MotorCompliance(self._session)
                    alertas = motor.executar_todas_as_regras(inputs.get("competencia"))
                    return {"total_alertas": len(alertas), "alertas": alertas[:50]}

                case "listar_alertas":
                    q = self._session.query(Alerta)
                    if inputs.get("tipo"):
                        q = q.filter(Alerta.tipo == inputs["tipo"])
                    if inputs.get("severidade"):
                        q = q.filter(Alerta.severidade == inputs["severidade"])
                    limite = inputs.get("limite", 20)
                    alertas = q.order_by(Alerta.created_at.desc()).limit(limite).all()
                    return [
                        {
                            "id": a.id, "tipo": a.tipo, "severidade": a.severidade,
                            "titulo": a.titulo, "descricao": a.descricao,
                            "evidencias": json.loads(a.evidencias or "{}"),
                            "criado_em": str(a.created_at),
                        }
                        for a in alertas
                    ]

                case "analisar_precos":
                    analisador = AnalisadorPrecos(self._session)
                    if inputs.get("categoria"):
                        return analisador.comparar_categoria(inputs["categoria"])
                    return analisador.analisar()

                case "analisar_conexoes":
                    self._ensure_grafo()
                    return self._grafo.conexoes_diretas(inputs["identificador"])

                case "caminho_entre_atores":
                    self._ensure_grafo()
                    caminho = self._grafo.caminho_entre(inputs["ator_a"], inputs["ator_b"])
                    return {"caminho": caminho} if caminho else {"caminho": None, "mensagem": "Sem conexão direta no grafo."}

                case "atores_mais_conectados":
                    self._ensure_grafo()
                    return self._grafo.atores_mais_conectados(inputs.get("top_n", 20))

                case "buscar_doerj_banco":
                    q = self._session.query(PublicacaoDOERJ)
                    if inputs.get("tipo_ato"):
                        q = q.filter(PublicacaoDOERJ.tipo_ato == inputs["tipo_ato"])
                    if inputs.get("palavra_chave"):
                        kw = f"%{inputs['palavra_chave']}%"
                        q = q.filter(
                            PublicacaoDOERJ.texto.ilike(kw) |
                            PublicacaoDOERJ.titulo.ilike(kw)
                        )
                    if inputs.get("data_inicio"):
                        q = q.filter(PublicacaoDOERJ.data_publicacao >= date.fromisoformat(inputs["data_inicio"]))
                    if inputs.get("data_fim"):
                        q = q.filter(PublicacaoDOERJ.data_publicacao <= date.fromisoformat(inputs["data_fim"]))
                    limite = inputs.get("limite", 20)
                    pubs = q.order_by(PublicacaoDOERJ.data_publicacao.desc()).limit(limite).all()
                    return [
                        {
                            "data": str(p.data_publicacao), "tipo": p.tipo_ato,
                            "titulo": p.titulo, "texto": p.texto[:500],
                            "cpfs": json.loads(p.cpfs_extraidos or "[]"),
                            "cnpjs": json.loads(p.cnpjs_extraidos or "[]"),
                            "url": p.url_fonte,
                        }
                        for p in pubs
                    ]

                case "detectar_cpf_duplicado":
                    from compliance_agent.collectors.terceirizados import (
                        detectar_cpf_duplicado_entre_fontes,
                    )
                    competencia = inputs.get("competencia", "")
                    cpf_filtro  = inputs.get("cpf", "")
                    resultados  = detectar_cpf_duplicado_entre_fontes(self._session, competencia)
                    if cpf_filtro:
                        cpf_clean  = "".join(c for c in cpf_filtro if c.isdigit())
                        resultados = [r for r in resultados if r.get("cpf") == cpf_clean]
                    return {
                        "total":       len(resultados),
                        "competencia": competencia or "todas",
                        "resultados":  resultados[:100],
                    }

                case "buscar_local":
                    from compliance_agent.database.fts import buscar_contratos_fts, buscar_doerj_fts, buscar_alertas_fts
                    query  = inputs["query"]
                    tabela = inputs.get("tabela", "todos")
                    result = {}
                    if tabela in ("contratos", "todos"):
                        result["contratos"] = buscar_contratos_fts(query)
                    if tabela in ("doerj", "todos"):
                        result["doerj"] = buscar_doerj_fts(query)
                    if tabela in ("alertas", "todos"):
                        result["alertas"] = buscar_alertas_fts(query)
                    return result

                case "buscar_doacoes_eleitorais":
                    from compliance_agent.database.models import DoacaoEleitoral
                    q = self._session.query(DoacaoEleitoral)
                    if inputs.get("cpf_cnpj"):
                        q = q.filter(DoacaoEleitoral.cpf_cnpj_doador == inputs["cpf_cnpj"].replace(".","").replace("/","").replace("-",""))
                    if inputs.get("nome"):
                        q = q.filter(DoacaoEleitoral.nome_doador.ilike(f"%{inputs['nome']}%"))
                    if inputs.get("ano_eleicao"):
                        q = q.filter(DoacaoEleitoral.ano_eleicao == inputs["ano_eleicao"])
                    doacoes = q.order_by(DoacaoEleitoral.valor.desc()).limit(30).all()
                    return [{"doador": d.nome_doador, "cpf_cnpj": d.cpf_cnpj_doador, "candidato": d.nome_candidato, "cargo": d.cargo_candidato, "partido": d.partido, "valor": d.valor, "ano": d.ano_eleicao} for d in doacoes]

                case "buscar_decisoes_tce":
                    from compliance_agent.collectors.tce import buscar_decisoes_tce
                    return await buscar_decisoes_tce(inputs["termo"], self._session)

                case "verificar_emprego_multiplo":
                    q = self._session.query(RegistroFolha)
                    if inputs.get("cpf"):
                        q = q.filter(RegistroFolha.cpf == inputs["cpf"])
                    if inputs.get("competencia"):
                        q = q.filter(RegistroFolha.competencia == inputs["competencia"])
                    registros = q.all()
                    orgaos = list({r.orgao_nome for r in registros if r.orgao_nome})
                    return {"cpf": inputs.get("cpf"), "orgaos_encontrados": orgaos, "total_registros": len(registros), "remuneracao_total": sum(r.remuneracao_bruta or 0 for r in registros)}

                case "status_orcamento":
                    from compliance_agent.llm.router import LLMRouter
                    router = LLMRouter()
                    status = router.status()
                    status["provedor_agente"] = self._provider
                    status["modelo_agente"] = self._model
                    return status

                case "baixar_folha_orgao":
                    from compliance_agent.collectors.caged import baixar_folha_orgao_externo
                    count = await baixar_folha_orgao_externo(inputs["orgao"], self._session)
                    return {"orgao": inputs["orgao"], "registros_importados": count}

                case "consultar_sei":
                    from compliance_agent.collectors.sei_portal import analisar_processo_sei
                    return await analisar_processo_sei(
                        inputs["numero_sei"],
                        self._session,
                        usar_llm_gratis=inputs.get("ler_documentos", True),
                    )

                case "buscar_sei_por_termo":
                    from compliance_agent.collectors.sei_portal import buscar_sei_por_objeto
                    return buscar_sei_por_objeto(self._session, inputs["termo"])

                case "reconhecer_padrao_fraude":
                    from compliance_agent.knowledge.pattern_engine import analisar_contexto_completo
                    contexto = {k: v for k, v in inputs.items() if v}
                    return analisar_contexto_completo(contexto)

                case "status_llm_gratuito":
                    from compliance_agent.llm.free_llm import status_provedores
                    return status_provedores()

                case _:
                    return {"error": f"Ferramenta '{name}' não reconhecida."}

        except Exception as e:
            return {"error": str(e), "tool": name}
