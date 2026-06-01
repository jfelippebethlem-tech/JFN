"""
Agente de Compliance & Auditoria — Claude-powered.

Combina análise de DOERJ, folha de pagamento, CNPJ, contratos e grafo de
relacionamentos para investigar corrupção, nepotismo, funcionários fantasmas
e irregularidades em processos SEI/licitações.
"""

import asyncio
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Any

import anthropic
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

TOOLS: list[anthropic.types.ToolParam] = [
    {
        "name": "consultar_cnpj",
        "description": "Consulta dados de uma empresa pelo CNPJ: razão social, sócios, situação, data de abertura, capital social.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cnpj": {"type": "string", "description": "CNPJ da empresa (com ou sem formatação)"},
            },
            "required": ["cnpj"],
        },
    },
    {
        "name": "buscar_servidor",
        "description": "Busca dados de servidor público pelo nome ou CPF no Portal de Transparência RJ.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nome": {"type": "string", "description": "Nome do servidor (parcial ou completo)"},
                "cpf":  {"type": "string", "description": "CPF do servidor"},
            },
            "required": [],
        },
    },
    {
        "name": "coletar_doerj",
        "description": "Coleta publicações do Diário Oficial do Estado do RJ. Pode ser de hoje, de uma data específica ou de um período.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data":         {"type": "string", "description": "Data no formato AAAA-MM-DD. Se omitido, usa hoje."},
                "data_inicio":  {"type": "string", "description": "Data inicial para período (AAAA-MM-DD)"},
                "data_fim":     {"type": "string", "description": "Data final para período (AAAA-MM-DD)"},
                "tipo_ato":     {"type": "string", "description": "Filtrar por tipo: nomeação | exoneração | contrato | licitação | aposentadoria"},
            },
            "required": [],
        },
    },
    {
        "name": "buscar_contratos_empresa",
        "description": "Busca todos os contratos celebrados com uma empresa pelo CNPJ no Portal de Transparência RJ.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cnpj": {"type": "string", "description": "CNPJ da empresa"},
            },
            "required": ["cnpj"],
        },
    },
    {
        "name": "executar_compliance",
        "description": "Executa todas as regras de compliance contra o banco de dados e retorna alertas novos gerados.",
        "input_schema": {
            "type": "object",
            "properties": {
                "competencia": {"type": "string", "description": "Competência da folha (AAAA-MM). Opcional."},
            },
            "required": [],
        },
    },
    {
        "name": "listar_alertas",
        "description": "Lista alertas de compliance já gerados, com filtros por tipo e severidade.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tipo":       {"type": "string", "description": "Tipo: fantasma | nepotismo | fracionamento | acumulacao | enriquecimento | direcionamento"},
                "severidade": {"type": "string", "description": "Severidade: alta | média | baixa"},
                "limite":     {"type": "integer", "description": "Quantidade máxima de alertas (padrão 20)"},
            },
            "required": [],
        },
    },
    {
        "name": "analisar_conexoes",
        "description": "Analisa o grafo de relacionamentos de uma pessoa ou empresa. Mostra quem se conecta com quem.",
        "input_schema": {
            "type": "object",
            "properties": {
                "identificador": {"type": "string", "description": "CPF, CNPJ ou nome parcial do ator"},
            },
            "required": ["identificador"],
        },
    },
    {
        "name": "caminho_entre_atores",
        "description": "Encontra o caminho mais curto entre dois atores no grafo de relacionamentos.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ator_a": {"type": "string", "description": "CPF, CNPJ ou nome do primeiro ator"},
                "ator_b": {"type": "string", "description": "CPF, CNPJ ou nome do segundo ator"},
            },
            "required": ["ator_a", "ator_b"],
        },
    },
    {
        "name": "atores_mais_conectados",
        "description": "Lista as pessoas e empresas com mais conexões no grafo (centralidade de rede).",
        "input_schema": {
            "type": "object",
            "properties": {
                "top_n": {"type": "integer", "description": "Quantos atores listar (padrão 20)"},
            },
            "required": [],
        },
    },
    {
        "name": "analisar_precos",
        "description": (
            "Analisa divergências de preço entre contratos similares. "
            "Detecta superfaturamento e subfaturamento por categoria (veículos, combustível, "
            "informática, limpeza, alimentação, obras, saúde, etc.). "
            "Gera ranking dos órgãos com contratos mais caros e mais baratos, "
            "e lista contratos com preços mais suspeitos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "categoria": {
                    "type": "string",
                    "description": (
                        "Categoria específica para detalhar (opcional). "
                        "Se omitido, analisa todas. "
                        "Categorias: veículos | combustível | informática | limpeza | "
                        "alimentação | obras | saúde | segurança | consultoria | "
                        "mobiliário | telefonia | transporte"
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "buscar_doerj_banco",
        "description": "Busca publicações do DOERJ já indexadas no banco, por tipo ou palavra-chave.",
        "input_schema": {
            "type": "object",
            "properties": {
                "palavra_chave": {"type": "string", "description": "Palavra ou nome para buscar no texto"},
                "tipo_ato":      {"type": "string", "description": "Tipo do ato"},
                "data_inicio":   {"type": "string", "description": "Data inicial AAAA-MM-DD"},
                "data_fim":      {"type": "string", "description": "Data final AAAA-MM-DD"},
                "limite":        {"type": "integer", "description": "Máximo de resultados (padrão 20)"},
            },
            "required": [],
        },
    },
    {
        "name": "detectar_cpf_duplicado",
        "description": (
            "Detecta CPFs que aparecem simultaneamente em múltiplas fontes de remuneração "
            "pública: servidores efetivos, terceirizados, bolsistas (FAPERJ/CNPq/residências), "
            "estagiários remunerados, aposentados/pensionistas com cargo ativo. "
            "Cruza a tabela RegistroFolha por CPF, agrupa por fonte e sinaliza combinações "
            "ilegais (CF/88 art. 37, XVI e §10; Lei 11.788/08 art. 3º, §1º; Lei 9.717/98)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "competencia": {
                    "type": "string",
                    "description": (
                        "Mês de referência no formato AAAA-MM. "
                        "Se omitido, verifica toda a base de dados."
                    ),
                },
                "cpf": {
                    "type": "string",
                    "description": (
                        "CPF específico para verificar (11 dígitos, com ou sem formatação). "
                        "Se informado, filtra apenas esse CPF nos resultados."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "buscar_local",
        "description": "Busca rápida local (sem custo de API) em contratos, publicações do DOERJ e alertas usando índice FTS5. Use este antes de chamadas mais pesadas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Termo de busca (nome, CNPJ, palavra-chave)"},
                "tabela": {"type": "string", "description": "contratos | doerj | alertas | todos (padrão: todos)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "buscar_doacoes_eleitorais",
        "description": "Busca doações eleitorais (TSE) feitas por uma pessoa ou empresa. Cruza com contratos para detectar 'doação × contrato'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cpf_cnpj": {"type": "string"},
                "nome": {"type": "string"},
                "ano_eleicao": {"type": "integer", "description": "Ano da eleição: 2018, 2020, 2022, 2024"},
            },
            "required": [],
        },
    },
    {
        "name": "buscar_decisoes_tce",
        "description": "Busca decisões e condenações do TCE-RJ para uma empresa ou pessoa.",
        "input_schema": {
            "type": "object",
            "properties": {
                "termo": {"type": "string", "description": "Nome da empresa, pessoa ou CNPJ"},
            },
            "required": ["termo"],
        },
    },
    {
        "name": "verificar_emprego_multiplo",
        "description": "Verifica se um CPF aparece com emprego simultâneo em múltiplos órgãos (estado, ALERJ, TJRJ, MPRJ, Defensoria, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "cpf": {"type": "string"},
                "competencia": {"type": "string", "description": "AAAA-MM"},
            },
            "required": [],
        },
    },
    {
        "name": "status_orcamento",
        "description": "Mostra quantos tokens Claude foram usados este mês e quanto resta do orçamento configurado.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "baixar_folha_orgao",
        "description": "Baixa e indexa a folha de pagamento de órgãos externos: ALERJ, TJRJ, MPRJ, Defensoria Pública.",
        "input_schema": {
            "type": "object",
            "properties": {
                "orgao": {"type": "string", "description": "alerj | tjrj | mprj | defensoria"},
            },
            "required": ["orgao"],
        },
    },
    {
        "name": "consultar_sei",
        "description": (
            "Consulta um processo SEI no Portal SEI-RJ (portalsei.rj.gov.br). "
            "Busca metadados, lista documentos, lê conteúdo, cruza com despesas SIAFE "
            "e detecta padrões de irregularidade. Use para investigar contratos, "
            "licitações e reformas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "numero_sei": {
                    "type": "string",
                    "description": "Número do processo SEI (ex: E-18/001234/2024 ou SEI-18-001234/2024)",
                },
                "ler_documentos": {
                    "type": "boolean",
                    "description": "Se true, lê o conteúdo dos documentos do processo (padrão: true)",
                },
            },
            "required": ["numero_sei"],
        },
    },
    {
        "name": "buscar_sei_por_termo",
        "description": "Busca processos SEI indexados no banco por termo no assunto ou tipo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "termo": {"type": "string", "description": "Palavra-chave (ex: reforma escola, SEEDUC, licitação)"},
            },
            "required": ["termo"],
        },
    },
    {
        "name": "reconhecer_padrao_fraude",
        "description": (
            "Compara qualquer texto ou contexto contra a base de padrões de fraude "
            "e casos históricos do RJ. Retorna score de similaridade e casos similares "
            "sem custo de API Claude. Use para contextualizar alertas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "texto":    {"type": "string", "description": "Texto para analisar (objeto, edital, despacho...)"},
                "objeto":   {"type": "string", "description": "Objeto do contrato ou processo"},
                "orgao":    {"type": "string", "description": "Órgão contratante"},
                "modalidade": {"type": "string"},
                "valor":    {"type": "number"},
            },
            "required": [],
        },
    },
    {
        "name": "status_llm_gratuito",
        "description": "Mostra quais LLMs gratuitos estão disponíveis (Ollama, Groq, OpenRouter/Hermes) e como configurar.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


class ComplianceAgent:
    """Claude-powered compliance and anti-corruption agent."""

    def __init__(self, api_key: Optional[str] = None):
        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
        )
        self._session = get_session()
        init_db()
        self._grafo = GrafoRelacionamentos(self._session)
        self._grafo_built = False
        self._conversation: list[anthropic.types.MessageParam] = []

    def _ensure_grafo(self):
        if not self._grafo_built:
            self._grafo.construir()
            self._grafo_built = True

    # ── Public API ────────────────────────────────────────────────────────────

    async def chat(self, user_message: str) -> str:
        self._conversation.append({"role": "user", "content": user_message})

        while True:
            response = self._client.messages.create(
                model="claude-opus-4-8",
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self._conversation,
            )

            assistant_content = list(response.content)
            tool_calls = [b for b in assistant_content if b.type == "tool_use"]
            self._conversation.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == "end_turn" or not tool_calls:
                return "\n".join(b.text for b in response.content if hasattr(b, "text"))

            tool_results = []
            for tc in tool_calls:
                console.print(f"[dim]⚙ {tc.name}({json.dumps(tc.input, ensure_ascii=False)[:120]})[/dim]")
                result = await self._execute_tool(tc.name, tc.input)
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": tc.id,
                    "content":     json.dumps(result, ensure_ascii=False, default=str),
                })
            self._conversation.append({"role": "user", "content": tool_results})

    async def run_interactive(self):
        console.print(Panel(
            "[bold red]⚖ Agente de Compliance & Auditoria — RJ[/bold red]\n"
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

    # ── Tool dispatcher ───────────────────────────────────────────────────────

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
                    return {
                        "total": len(pubs),
                        "publicacoes": pubs[:30],  # limita retorno ao Claude
                    }

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
                        "total":      len(resultados),
                        "competencia": competencia or "todas",
                        "resultados": resultados[:100],
                    }

                case "buscar_local":
                    from compliance_agent.database.fts import buscar_contratos_fts, buscar_doerj_fts, buscar_alertas_fts
                    query = inputs["query"]
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
                    return router.status()

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
