"""
SIAFE2/SEI Finance Agent — agentic loop sem dependência do Claude API.

Usa Groq (llama-3.3-70b, gratuito) como LLM principal.
Fallback: OpenRouter ou Anthropic se configurados no .env.
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from .browser.siafe_browser import SIAFEBrowser
from .browser.sei_browser import SEIBrowser
from .tools import TOOLS

console = Console()

SYSTEM_PROMPT = """Você é um agente especialista no SIAFE2 (Sistema Integrado de Administração Financeira
do Estado do Rio de Janeiro) e no SEI Rio.

CREDENCIAIS: As credenciais de acesso já estão configuradas. Ao fazer login, use
username={username}. Não peça credenciais ao usuário — use as pré-configuradas.

EXERCÍCIO ATIVO: {exercicio}
O exercício pode ser trocado a qualquer momento com switch_exercicio.
Quando o usuário mencionar um ano diferente do ativo, chame switch_exercicio automaticamente.
Exemplos: "gastos de 2024" → switch_exercicio(exercicio="2024") antes de navegar.

Você tem acesso a ferramentas para:
1. Fazer login no SIAFE2 (use as credenciais pré-configuradas)
2. Trocar o exercício/ano fiscal com switch_exercicio (re-faz login com o novo ano)
3. Navegar até FlexVision > Consultas > Execução por OB
4. Pesquisar gastos por órgão, data e número de OB
5. Extrair e exportar dados financeiros (CSV/JSON)
6. Cruzar com o SEI Rio para encontrar números de processo (SEI)

Estrutura do SIAFE2:
- Login: Usuário, Senha, Cliente, Exercício (4 campos)
- Framework: Oracle ADF (Application Development Framework)
- FlexVision: subdomain separado (siafe2-flexvision.fazenda.rj.gov.br)
- Caminho: FlexVision > Consultas > Execução por OB

Diretrizes:
- Se o usuário pedir dados, faça login automaticamente (sem perguntar credenciais)
- Se o usuário mencionar um ano específico, troque o exercício com switch_exercicio
- Se aparecer campo de código por e-mail (2FA), peça ao usuário
- Se um passo falhar, tire screenshot e explique o problema
- Ao extrair dados com muitas páginas, avise o usuário antes
- Apresente dados financeiros formatados (valores em R$, datas em DD/MM/AAAA)
- Se o usuário pedir número SEI de uma OB, use enrich_with_sei

Formato de resposta:
- Markdown com tabelas e listas
- Valores monetários: R$ 1.234.567,89
- Datas: DD/MM/AAAA
"""

# ── Configuração de provedor LLM ──────────────────────────────────────────────

_GROQ_BASE       = "https://api.groq.com/openai/v1"
_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_ANTHROPIC_BASE  = "https://api.anthropic.com"

_GROQ_MODEL      = "llama-3.3-70b-versatile"
_ANTHROPIC_MODEL = "claude-opus-4-8"


def _openrouter_model() -> str:
    return os.environ.get("OPENROUTER_SMART_MODEL", "nousresearch/hermes-3-llama-3.1-405b:free")


def _detect_provider() -> tuple[str, str, str]:
    groq_key       = os.environ.get("GROQ_API_KEY", "").strip()
    anthropic_key  = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    prefer         = os.environ.get("FREE_LLM_PREFER", "groq").lower()

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
        "Abra o arquivo .env e preencha:\n\n"
        "  GROQ_API_KEY=sua_chave_aqui      ← grátis em console.groq.com\n"
        "  OPENROUTER_API_KEY=sua_chave     ← grátis em openrouter.ai (Hermes-3)\n"
    )


async def _llm_request(
    provider: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict],
    max_tokens: int = 4096,
) -> dict:
    if provider == "anthropic":
        return await _anthropic_request(api_key, model, messages, tools, max_tokens)

    base = _GROQ_BASE if provider == "groq" else _OPENROUTER_BASE
    url = f"{base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/jfn/compliance-agent"
        headers["X-Title"] = "JFN SIAFE Agent"

    payload: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _anthropic_request(
    api_key: str, model: str, messages: list[dict], tools: list[dict], max_tokens: int
) -> dict:
    """Chama API Anthropic e converte resposta para formato OpenAI."""
    anthropic_tools = [
        {
            "name": t["function"]["name"],
            "description": t["function"].get("description", ""),
            "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}}),
        }
        for t in tools
    ]
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

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{_ANTHROPIC_BASE}/v1/messages",
            json=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    blocks = data.get("content", [])
    text_parts = [b["text"] for b in blocks if b.get("type") == "text"]
    tool_calls_raw = [b for b in blocks if b.get("type") == "tool_use"]

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

    return {
        "choices": [{
            "message": message,
            "finish_reason": "tool_calls" if tool_calls_raw else "stop",
        }]
    }


# ── Agente SIAFE ──────────────────────────────────────────────────────────────

class SIAFEAgent:
    """Agente de automação do SIAFE2/SEI — usa Groq (gratuito) como LLM padrão."""

    def __init__(
        self,
        headless: bool = True,
        output_dir: str = "output",
        default_username: str = "",
        default_password: str = "",
        default_cliente: Optional[str] = None,
        default_exercicio: Optional[str] = None,
    ):
        self._provider, self._api_key, self._model = _detect_provider()
        self._siafe = SIAFEBrowser(headless=headless, screenshots_dir="screenshots")
        self._sei: Optional[SEIBrowser] = None
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(exist_ok=True)
        self._extracted_data: list[dict] = []
        self._siafe_username: str = default_username
        self._siafe_password: str = default_password
        self._siafe_cliente: Optional[str] = default_cliente
        self._siafe_exercicio: Optional[str] = default_exercicio
        self._conversation: list[dict] = []

    async def start(self):
        await self._siafe.start()
        console.print("[green]Browser iniciado.[/green]")

    async def stop(self):
        await self._siafe.close()
        console.print("[yellow]Browser encerrado.[/yellow]")

    async def run_interactive(self):
        await self.start()

        provider_label = {
            "groq": "Groq (llama-3.3-70b) — grátis",
            "openrouter": "OpenRouter — grátis",
            "anthropic": "Anthropic Claude — pago",
        }.get(self._provider, self._provider)

        console.print(Panel(
            f"[bold cyan]SIAFE2 / SEI Finance Agent[/bold cyan]\n"
            f"Usuário: [yellow]{self._siafe_username}[/yellow]\n"
            f"LLM: [green]{provider_label}[/green]\n"
            "Digite sua pergunta ou comando. Use 'sair' para encerrar.",
            title="Bem-vindo",
        ))

        console.print("[dim]Fazendo login no SIAFE2...[/dim]")
        login_result = await self._tool_login_siafe(
            username=self._siafe_username,
            password=self._siafe_password,
            cliente=self._siafe_cliente,
            exercicio=self._siafe_exercicio,
        )
        if login_result.get("success"):
            console.print(f"[green]Login realizado.[/green] URL: {login_result.get('url', '')}")
        else:
            console.print(f"[red]Login falhou:[/red] {login_result.get('message')}")
            console.print("[yellow]Você ainda pode usar o agente — ele tentará logar quando necessário.[/yellow]")

        try:
            while True:
                try:
                    user_input = input("\n[Você] ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if user_input.lower() in {"sair", "exit", "quit", "q"}:
                    break
                if not user_input:
                    continue

                response = await self.chat(user_input)
                console.print(f"\n[bold green]Agente:[/bold green]")
                console.print(Markdown(response))
        finally:
            await self.stop()

    async def chat(self, user_message: str) -> str:
        self._conversation.append({"role": "user", "content": user_message})

        system = SYSTEM_PROMPT.format(
            username=self._siafe_username,
            exercicio=self._siafe_exercicio or "padrão do SIAFE",
        )
        messages = [{"role": "system", "content": system}] + self._conversation

        while True:
            data = await _llm_request(
                self._provider, self._api_key, self._model,
                messages, TOOLS,
            )

            choice     = data["choices"][0]
            msg        = choice["message"]
            finish     = choice.get("finish_reason", "stop")
            tool_calls = msg.get("tool_calls") or []

            self._conversation.append(msg)
            messages.append(msg)

            if finish == "stop" or not tool_calls:
                return msg.get("content") or ""

            for tc in tool_calls:
                fn   = tc["function"]
                name = fn["name"]
                try:
                    inputs = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    inputs = {}

                console.print(f"[dim]→ Executando: {name}({json.dumps(inputs, ensure_ascii=False)})[/dim]")
                result = await self._execute_tool(name, inputs)

                tool_result_msg = {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
                self._conversation.append(tool_result_msg)
                messages.append(tool_result_msg)

    # ── Dispatcher ────────────────────────────────────────────────────────────

    async def _execute_tool(self, name: str, inputs: dict) -> Any:
        try:
            match name:
                case "login_siafe":
                    return await self._tool_login_siafe(**inputs)
                case "navigate_flexvision":
                    return await self._siafe.navigate_to_flexvision()
                case "navigate_execucao_ob":
                    return await self._siafe.navigate_to_execucao_ob()
                case "search_execucao_ob":
                    return await self._siafe.search_execucao_ob(**inputs)
                case "extract_ob_data":
                    max_pages = inputs.get("max_pages", 50)
                    data = await self._siafe.extract_ob_data(max_pages=max_pages)
                    self._extracted_data = data
                    return {"success": True, "records": len(data), "preview": data[:3]}
                case "export_data":
                    return await self._tool_export_data(**inputs)
                case "switch_exercicio":
                    return await self._tool_switch_exercicio(**inputs)
                case "enrich_with_sei":
                    return await self._tool_enrich_with_sei(**inputs)
                case "list_menu_items":
                    items = await self._siafe.list_menu_items()
                    return {"items": items}
                case "take_screenshot":
                    path = await self._siafe.screenshot(inputs.get("name", "debug"))
                    return {"path": path}
                case "get_page_text":
                    text = await self._siafe.get_page_text()
                    return {"text": text[:5000]}
                case _:
                    return {"error": f"Ferramenta '{name}' não reconhecida."}
        except Exception as e:
            return {"error": str(e), "tool": name}

    async def _tool_login_siafe(
        self,
        username: str,
        password: str,
        cliente: Optional[str] = None,
        exercicio: Optional[str] = None,
    ) -> dict:
        self._siafe_username = username
        self._siafe_password = password

        async def otp_callback():
            return input("\n[SIAFE2] Código recebido por e-mail: ").strip()

        result = await self._siafe.login(
            username, password,
            cliente=cliente,
            exercicio=exercicio,
            otp_callback=otp_callback,
        )
        if result.get("success") and exercicio:
            self._siafe_exercicio = exercicio
        return result

    async def _tool_switch_exercicio(self, exercicio: str) -> dict:
        if not exercicio.strip():
            return {"error": "Exercício não informado."}

        prev = self._siafe_exercicio or "padrão"
        self._siafe_exercicio = exercicio.strip()

        async def otp_callback():
            return input(f"\n[SIAFE2] Código OTP para exercício {exercicio}: ").strip()

        result = await self._siafe.login(
            self._siafe_username,
            self._siafe_password,
            cliente=self._siafe_cliente,
            exercicio=exercicio.strip(),
            otp_callback=otp_callback,
        )

        if result.get("success"):
            return {"success": True, "message": f"Exercício trocado: {prev} → {exercicio}.", "url": result.get("url")}
        else:
            self._siafe_exercicio = prev
            return {"success": False, "message": f"Falha ao trocar para exercício {exercicio}: {result.get('message')}"}

    async def _tool_export_data(self, format: str = "both", filename: Optional[str] = None) -> dict:
        if not self._extracted_data:
            return {"error": "Nenhum dado extraído ainda. Use extract_ob_data primeiro."}

        if not filename:
            filename = f"execucao_ob_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        paths = []

        if format in ("json", "both"):
            json_path = self._output_dir / f"{filename}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(self._extracted_data, f, ensure_ascii=False, indent=2, default=str)
            paths.append(str(json_path))

        if format in ("csv", "both"):
            import pandas as pd
            csv_path = self._output_dir / f"{filename}.csv"
            df = pd.DataFrame(self._extracted_data)
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            paths.append(str(csv_path))

        return {"success": True, "files": paths, "records": len(self._extracted_data)}

    async def _tool_enrich_with_sei(
        self,
        sei_username: Optional[str] = None,
        sei_password: Optional[str] = None,
        use_same_credentials: bool = False,
    ) -> dict:
        if not self._extracted_data:
            return {"error": "Nenhum dado OB disponível. Extraia dados primeiro."}

        user = self._siafe_username if use_same_credentials else (sei_username or self._siafe_username)
        pwd  = self._siafe_password if use_same_credentials else (sei_password or self._siafe_password)

        if not user:
            user = input("[SEI] Usuário: ").strip()
            pwd  = input("[SEI] Senha: ").strip()

        new_page = await self._siafe._context.new_page()
        self._sei = SEIBrowser(new_page, screenshots_dir="screenshots")

        login_result = await self._sei.login(user, pwd)
        if not login_result["success"]:
            await new_page.close()
            return {"error": f"Login SEI falhou: {login_result['message']}"}

        enriched    = []
        found_count = 0
        for i, record in enumerate(self._extracted_data):
            result = await self._sei.extract_ob_sei_numbers_from_siafe_row(record)
            enriched.append(result)
            if result.get("numero_sei"):
                found_count += 1
            if (i + 1) % 10 == 0:
                console.print(f"[dim]SEI: {i+1}/{len(self._extracted_data)} processados...[/dim]")

        self._extracted_data = enriched
        await new_page.close()

        return {"success": True, "total_records": len(enriched), "sei_found": found_count, "preview": enriched[:3]}
