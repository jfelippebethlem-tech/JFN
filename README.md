# JFN — Agente Auditor de Compliance

Auditor autônomo para dados públicos do Estado do Rio de Janeiro: **SIAFE2**, **DOERJ**, **SEI-RJ** e **PNCP**. Executa coleta estruturada, regras de compliance, geração de alertas, relatórios e missões paralelas.

## Funcionalidades atuais

### Coleta e ingestão
- Coleta de OBs do **SIAFE2** (inclusive exercício 2026) com navegação assistida.
- Coleta de publicações do **DOERJ** (Diário Oficial do Estado do RJ).
- Integração com **SEI-RJ** para cruzamento de processos.
- Integração com **PNCP** para compras públicas.
- Diagnóstico rápido (`checar.py`) com verificação de Chrome debug, DOERJ e SIAFE2.

### Compliance e regras
- Motor de regras com múltiplos detectores.
- Geração automática de alertas.
- Exportação de relatórios em **TXT / PDF / DOCX / MD**.
- Histórico de sessões e memória de aprendizado persistente.

### Interface
- Servidor HTTP com endpoints REST para painel e operação do agente auditor.
- Suporte a múltiplas missões paralelas, com pool limitado, retomada e histórico.

## Stack

- **Python 3.12** (ambiente do projeto JFN).
- **FastAPI / Uvicorn** para API.
- **SQLAlchemy + SQLite** para banco local.
- **Playwright** para automação navegacional.
- **Relatórios** com geração local (txt, pdf, docx).

## Requisitos

- Python 3.12.
- Dependências em `requirements.txt`.
- Playwright/Chromium instalado.

```bash
pip install -r requirements.txt
playwright install chromium
```

## Como rodar

```bash
python checar.py
python server.py --host 0.0.0.0 --port 8000
```

## Endpoints principais

- `GET /` e `/chat` — Painel/chat.
- `GET /api/hermes/estado` — Estado do agente.
- `POST /api/hermes/missao` — Definir missão atual.
- `DELETE /api/hermes/missao` — Limpar missão atual.
- `POST /api/hermes/missoes` — Criar missão paralela (multi-missão).
- `GET /api/hermes/missoes` — Listar missões.
- `GET /api/hermes/missoes/{id}` — Detalhe de missão.
- `POST /api/hermes/trabalhar` — Disparar execução da missão.
- `POST /api/hermes/parar` — Parar execução.
- `POST /api/hermes/relatorio` — Gerar relatório.
- `GET /api/compliance/painel` — Snapshot do painel.
- `GET /api/compliance/investigar` — Investigar pessoa/empresa.
- `GET /api/compliance/relatorio_30d` — Relatório últimos 30 dias.
- `GET /api/compliance/graph` — Grafo de relacionamentos.
- `GET /api/compliance/alerts` — Alertas.
- `GET /api/compliance/stats` — Estatísticas.
- `GET /api/compliance/buscar` — Busca textual.
- `GET /graph` — Visualização de grafo.

## Estrutura principal

```
compliance_agent/
  collectors/
    siafe_ob.py
    doerj.py
    sei_portal.py
    pncp.py
    caged.py
    web_research.py
  rules/
    default_audit_config.py
    generate_alerts.py
    engine.py
    obra.py
    preco.py
  reporting/
    export_relatorios.py
    charts.py
    pdf.py
  database/
    models.py
    migrations/
  herm