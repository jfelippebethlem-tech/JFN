# JFN — SIAFE2 / SEI Finance Agent

Agente conversacional com IA para navegar o [SIAFE2](https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp) e o SEI Rio de Janeiro, extrair dados de **Execução por OB** e cruzar com números de processo SEI.

## Funcionalidades

- Login no SIAFE2 com suporte a código OTP via e-mail
- Navegação até FlexVision → Execução por OB
- Pesquisa com filtros: órgão, período, número de OB
- Extração de dados com paginação automática
- Exportação para CSV e JSON
- Cruzamento com SEI Rio para obter número de processo
- Interface conversacional em português

## Requisitos

- Python 3.11+
- Chave da API Anthropic

## Instalação

```bash
pip install -r requirements.txt
playwright install chromium
```

## Uso

### Interativo (recomendado)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python main.py
```

### Com browser visível (para depuração)

```bash
python main.py --visible
```

### Consulta única

```bash
python main.py --query "Mostre os gastos da SEEDUC em maio de 2025"
```

## Exemplos de perguntas ao agente

```
Faça login com meu usuário e extraia as OBs da última semana
Liste todos os gastos do órgão 260 em abril de 2025
Qual o número SEI da OB 2025OB000123?
Exporte os dados extraídos para CSV
Quais órgãos aparecem na tela de Execução por OB?
```

## Fluxo típico

1. `login_siafe` — autentica (pede OTP se necessário)
2. `navigate_flexvision` — acessa o módulo
3. `navigate_execucao_ob` — vai para a seção de OBs
4. `search_execucao_ob` — filtra por período/órgão
5. `extract_ob_data` — extrai todos os registros
6. `enrich_with_sei` — busca números de processo SEI
7. `export_data` — salva em CSV/JSON

## Estrutura

```
siafe_agent/
  browser/
    siafe_browser.py   # Automação Playwright para SIAFE2
    sei_browser.py     # Automação Playwright para SEI Rio
  tools.py             # Definições das ferramentas para Claude
  agent.py             # Loop agentico com Claude API
main.py                # CLI
requirements.txt
```
