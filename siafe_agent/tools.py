"""Tool definitions for the Claude-powered SIAFE2/SEI agent."""

import json
import asyncio
from typing import Any

import anthropic

# Tool schemas passed to Claude API
TOOLS: list[anthropic.types.ToolParam] = [
    {
        "name": "login_siafe",
        "description": (
            "Faz login no sistema SIAFE2 do governo do estado do Rio de Janeiro. "
            "O formulário tem 4 campos: Usuário (CPF), Senha, Cliente (organização) e Exercício (ano fiscal). "
            "Cliente e Exercício são opcionais — se não informados, usa o valor padrão/primeiro da lista. "
            "Se houver código OTP enviado por e-mail (2FA), o agente pausa e pede ao usuário. "
            "Deve ser chamado antes de qualquer outra ferramenta do SIAFE."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "username": {
                    "type": "string",
                    "description": "CPF ou login do usuário no SIAFE2 (ex: '14398839712')",
                },
                "password": {
                    "type": "string",
                    "description": "Senha do usuário",
                },
                "cliente": {
                    "type": "string",
                    "description": "Valor do campo 'Cliente' (organização). Opcional — deixa padrão se omitido.",
                },
                "exercicio": {
                    "type": "string",
                    "description": "Ano fiscal para o campo 'Exercício'. Ex: '2025'. Opcional.",
                },
            },
            "required": ["username", "password"],
        },
    },
    {
        "name": "navigate_flexvision",
        "description": "Navega para o módulo FlexVision dentro do SIAFE2 após login.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "navigate_execucao_ob",
        "description": (
            "Navega para a seção 'Execução por OB' dentro do FlexVision do SIAFE2. "
            "Retorna o status da navegação."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "search_execucao_ob",
        "description": (
            "Executa pesquisa na tela de Execução por OB com filtros opcionais. "
            "Retorna quantas linhas foram encontradas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "orgao": {
                    "type": "string",
                    "description": "Código ou nome do órgão (ex: '260' ou 'SEED'). Opcional.",
                },
                "data_inicio": {
                    "type": "string",
                    "description": "Data inicial no formato DD/MM/AAAA. Opcional.",
                },
                "data_fim": {
                    "type": "string",
                    "description": "Data final no formato DD/MM/AAAA. Opcional.",
                },
                "numero_ob": {
                    "type": "string",
                    "description": "Número específico de OB para buscar. Opcional.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "extract_ob_data",
        "description": (
            "Extrai todos os dados da tabela de Execução por OB, percorrendo páginas. "
            "Retorna lista de registros com todos os campos disponíveis na tela."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "max_pages": {
                    "type": "integer",
                    "description": "Número máximo de páginas a percorrer (padrão 50).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "export_data",
        "description": (
            "Exporta os dados extraídos para CSV e/ou JSON. "
            "Retorna o caminho dos arquivos gerados."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["csv", "json", "both"],
                    "description": "Formato de saída: 'csv', 'json', ou 'both'.",
                },
                "filename": {
                    "type": "string",
                    "description": "Nome base do arquivo (sem extensão). Padrão: 'execucao_ob_YYYYMMDD'.",
                },
            },
            "required": ["format"],
        },
    },
    {
        "name": "enrich_with_sei",
        "description": (
            "Cruza os dados de OBs com o SEI Rio para buscar números de processo. "
            "Recebe lista de registros OB e retorna com campo 'numero_sei' preenchido onde encontrado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sei_username": {
                    "type": "string",
                    "description": "Usuário para login no SEI Rio.",
                },
                "sei_password": {
                    "type": "string",
                    "description": "Senha para login no SEI Rio.",
                },
                "use_same_credentials": {
                    "type": "boolean",
                    "description": "Se true, usa as mesmas credenciais do SIAFE2 para o SEI.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "list_menu_items",
        "description": (
            "Lista todos os itens de menu e links visíveis na página atual do SIAFE2. "
            "Útil para explorar a navegação disponível."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "take_screenshot",
        "description": (
            "Tira um screenshot da página atual e retorna o caminho do arquivo. "
            "Útil para diagnóstico quando algo não funciona como esperado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Nome descritivo para o screenshot.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_page_text",
        "description": (
            "Retorna o texto visível da página atual. "
            "Útil para ler mensagens de erro, instruções ou conteúdo não tabelado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]
