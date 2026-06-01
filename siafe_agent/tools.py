"""Tool definitions for the SIAFE2/SEI agent (formato OpenAI/Groq)."""

# Tool schemas in OpenAI-compatible format (works with Groq, OpenRouter, Anthropic)
TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "login_siafe",
            "description": (
                "Faz login no sistema SIAFE2 do governo do estado do Rio de Janeiro. "
                "O formulário tem 4 campos: Usuário (CPF), Senha, Cliente (organização) e Exercício (ano fiscal). "
                "Cliente e Exercício são opcionais — se não informados, usa o valor padrão/primeiro da lista. "
                "Se houver código OTP enviado por e-mail (2FA), o agente pausa e pede ao usuário. "
                "Deve ser chamado antes de qualquer outra ferramenta do SIAFE."
            ),
            "parameters": {
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
                        "description": "Valor do campo 'Cliente' (organização). Opcional.",
                    },
                    "exercicio": {
                        "type": "string",
                        "description": "Ano fiscal para o campo 'Exercício'. Ex: '2025'. Opcional.",
                    },
                },
                "required": ["username", "password"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate_flexvision",
            "description": "Navega para o módulo FlexVision dentro do SIAFE2 após login.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate_execucao_ob",
            "description": (
                "Navega para a seção 'Execução por OB' dentro do FlexVision do SIAFE2. "
                "Retorna o status da navegação."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_execucao_ob",
            "description": (
                "Executa pesquisa na tela de Execução por OB com filtros opcionais. "
                "Retorna quantas linhas foram encontradas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "orgao":       {"type": "string", "description": "Código ou nome do órgão (ex: '260' ou 'SEED'). Opcional."},
                    "data_inicio": {"type": "string", "description": "Data inicial no formato DD/MM/AAAA. Opcional."},
                    "data_fim":    {"type": "string", "description": "Data final no formato DD/MM/AAAA. Opcional."},
                    "numero_ob":   {"type": "string", "description": "Número específico de OB para buscar. Opcional."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_ob_data",
            "description": (
                "Extrai todos os dados da tabela de Execução por OB, percorrendo páginas. "
                "Retorna lista de registros com todos os campos disponíveis na tela."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_pages": {"type": "integer", "description": "Número máximo de páginas a percorrer (padrão 50)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_data",
            "description": (
                "Exporta os dados extraídos para CSV e/ou JSON. "
                "Retorna o caminho dos arquivos gerados."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "format":   {"type": "string", "enum": ["csv", "json", "both"], "description": "Formato de saída."},
                    "filename": {"type": "string", "description": "Nome base do arquivo (sem extensão)."},
                },
                "required": ["format"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enrich_with_sei",
            "description": (
                "Cruza os dados de OBs com o SEI Rio para buscar números de processo. "
                "Retorna registros com campo 'numero_sei' preenchido onde encontrado."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sei_username":          {"type": "string"},
                    "sei_password":          {"type": "string"},
                    "use_same_credentials":  {"type": "boolean", "description": "Se true, usa as mesmas credenciais do SIAFE2."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "switch_exercicio",
            "description": (
                "Troca o exercício (ano fiscal) ativo sem reiniciar o agente. "
                "Faz logout e re-login no SIAFE2 com o novo exercício. "
                "Use quando o usuário pedir dados de um ano diferente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "exercicio": {"type": "string", "description": "Ano fiscal a ativar, ex: '2026', '2025', '2024'."},
                },
                "required": ["exercicio"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_menu_items",
            "description": "Lista todos os itens de menu e links visíveis na página atual do SIAFE2.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Tira um screenshot da página atual. Útil para diagnóstico.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nome descritivo para o screenshot."},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_text",
            "description": "Retorna o texto visível da página atual. Útil para ler mensagens de erro ou conteúdo.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]
