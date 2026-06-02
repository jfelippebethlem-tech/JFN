# JFN — Agente Auditor de Compliance

Auditor autônomo para dados públicos do Estado do Rio de Janeiro: **SIAFE2**, **DOERJ**, **SEI-RJ** e **PNCP**. Executa coleta estruturada, regras de compliance, geração de alertas, relatórios e missões paralelas.

## Funcionalidades atuais

### Coleta e ingestão
- Coleta de OBs do **SIAFE2** (inclusive exercício 2026) com navegação assistida.
- Coleta de publicações do **DOERJ** (Diário Oficial do Estado do RJ).
- Integração com **SEI-RJ** para cruzamento de processos, com leitura na
  íntegra e resolução automática do CAPTCHA de imagem por **OCR** (ver abaixo).
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

### Leitura de processos SEI com CAPTCHA (OCR automático)

O Portal de Pesquisa Pública do SEI-RJ exibe um CAPTCHA de imagem clássico
(`captcha.php` — texto distorcido). O JFN lê o processo na íntegra resolvendo
esse CAPTCHA automaticamente por OCR:

1. O agente abre a consulta na janela do Chrome (porta 9222) e preenche o
   número do processo.
2. Se aparecer o CAPTCHA, o agente captura a imagem e a lê com OCR
   (`compliance_agent/captcha_solver.py`, via pytesseract + OpenCV).
3. Preenche o código e reenvia (até algumas tentativas, pois a imagem é
   distorcida).
4. Lê o processo na íntegra (árvore de documentos, texto, CPFs/CNPJs/valores),
   reaproveitando a sessão validada para os documentos seguintes.

Como usar:
- Telegram: `/sei E-12/345/2026`.
- Programático: `compliance_agent.collectors.sei_cdp.ler_processo_sei(numero)`.
- Busca crua: `compliance_agent.collectors.sei_cdp.submit_sei_search(numero)`.
- Como ação do agente de missão: `ler_sei` (`{"numero": "E-12/345/2026"}`).
- Fallback automático: `buscar_processo()` do `sei_portal.py` cai para o caminho
  via Chrome quando o acesso direto por HTTP esbarra no CAPTCHA.

Requisitos para o OCR: Tesseract instalado (no Windows, padrão
`C:\Program Files\Tesseract-OCR\tesseract.exe`) e `pip install opencv-python
pytesseract pillow`.

Config opcional: `SEI_CAPTCHA_TENTATIVAS` (tentativas de OCR; padrão 4).

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
    sei_cdp.py        # leitura SEI via Chrome 9222 (humano-no-loop p/ CAPTCHA)
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