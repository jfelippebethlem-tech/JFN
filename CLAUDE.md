# CLAUDE.md — JFN Intelligence Engine

**Projeto:** JFN — Agente de Auditoria e Compliance do Estado do Rio de Janeiro  
**Owner:** jfelippebethlem-tech  
**Branch padrão:** `claude/rj-finance-agent-BYlhJ`  
**Repo:** https://github.com/jfelippebethlem-tech/JFN.git

> 🐧 **BRANCH `claude/ambiente-e-relatorio` = USO EXCLUSIVO LINUX (VM).** Não usar no Windows — ver [`PLATAFORMA-LINUX-ONLY.md`](PLATAFORMA-LINUX-ONLY.md).

> 🧭 **Ambiente de execução:** leia [`AMBIENTE.md`](AMBIENTE.md) (+ [`ambiente.json`](ambiente.json)) — a
> fonte única de verdade de ONDE tudo roda (VM Linux GCP, **não** Windows), o workflow de boot e como o
> Yoda aciona o JFN/Massare pela API em `127.0.0.1:8000`. O JFN é o **motor + barramento** do ecossistema.

---

## REGRAS ABSOLUTAS — LER ANTES DE QUALQUER COISA

### 1. ESTÉTICA E QUALIDADE DOS OUTPUTS

**Todo relatório, documento, análise ou saída deste projeto deve ter estética profissional impecável.**

Isso não é opcional. Aplica-se em todas as sessões, em todos os contextos, sem exceção.

- Relatórios seguem padrão de due diligence profissional (Kroll / Deloitte / Control Risks)
- Hierarquia visual clara: cabeçalho de capa, seções numeradas, tabelas alinhadas
- Indicadores de risco visualmente consistentes (🔴🟡🟢 com scores numéricos)
- Callouts para alertas críticos usando blockquotes formatados
- Números financeiros sempre com ponto de milhar e duas casas decimais
- Fontes e referências normativas citadas explicitamente
- Sem outputs funcionais mas feios — um relatório que não seria entregue a um cliente não sai daqui

### 2. METODOLOGIA FINANCEIRA — ORÇAMENTO PÚBLICO

**Empenho ≠ Pagamento. Sempre.**

- Notas de empenho podem ser canceladas antes da liquidação
- O dado definitivo de pagamento público é a **Ordem Bancária (OB)**
- Nunca citar valores de empenho como "total pago" ou "receita confirmada"
- Empenhos são sempre marcados como "valor bruto — pode incluir cancelamentos"
- OBs são a fonte de verdade; sem elas, toda análise financeira é parcial

### 3. SEGURANÇA DE CREDENCIAIS

- `SIAFE_USER` e `SIAFE_PASS` — apenas em `.env` ou GitHub Secrets. Nunca em código, logs ou git.
- `.env` está no `.gitignore` — nunca commitar
- `auth.json` e `hermes-tudo.sh` — nunca versionar
- Todas as credenciais via `os.environ.get(...)` exclusivamente

### 4. GIT

- Branch de desenvolvimento: `claude/rj-finance-agent-BYlhJ`
- Nunca fazer force push sem confirmação explícita
- Todo trabalho relevante: commit + push antes de encerrar a sessão
- Se push rejeitar por divergência: `git pull --rebase` antes de tentar novamente
- Mensagens de commit: convenção semântica (`feat:`, `fix:`, `data:`, `docs:`)

### 5. COLETA SIAFE

- SIAFE-Rio 2: `siafe2.fazenda.rj.gov.br` — WAF bloqueia IPs não-governamentais
- GitHub Actions (Azure IPs) têm acesso — usar workflows para coleta remota
- Exercícios confirmados: `{2027: "0", 2026: "1", 2025: "2", 2024: "3", 2023: "4"}`
- MFA: quando detectado, pedir o código diretamente ao usuário no chat
- Sistema de progresso: `data/sei_cache/obs_progress.json` — sempre atualizar após coleta

---

## ARQUITETURA DO PROJETO

```
JFN/
├─ CLAUDE.md                          ← você está aqui
├─ _SANDBOX/
│  ├─ coletar_obs_agora.py            ← script principal de coleta SIAFE
│  └─ gerar_relatorio_obs_pdf.py      ← gerador de PDF
├─ data/
│  ├─ empresas_target.json            ← 10 empresas-alvo com CNPJs
│  └─ sei_cache/
│     ├─ obs_progress.json            ← índice de progresso de coleta
│     ├─ obs_todas.json               ← consolidado de todas as OBs
│     └─ obs_{cnpj}_{ano}.json        ← por empresa por ano
├─ reports/
│  └─ mgs_clean_inteligencia_2026.md  ← relatório de due diligence MGS CLEAN
├─ .github/
│  └─ workflows/
│     └─ coletar-obs-siafe.yml        ← workflow de coleta (disparo manual)
└─ hermes-yoda/
   └─ CLAUDE.md                       ← contexto do agente Hermes/Yoda
```

---

## EMPRESAS-ALVO ATUAIS

| CNPJ | Empresa | Categoria |
|------|---------|-----------|
| 19.088.605/0001-04 | MGS CLEAN SOLUCOES E SERVICOS LTDA | mgs_clean_real |
| 05.526.816/0001-83 | BRINKS SEGURANCA E TRANSPORTE DE VALORES | obs_siafe |
| 33.592.510/0001-54 | LIGHT SERVICOS DE ELETRICIDADE S.A. | obs_siafe |
| 33.200.056/0001-23 | CEDAE | obs_siafe |
| 60.923.714/0001-81 | OI S.A. | obs_siafe |
| 02.558.157/0001-62 | CLARO S.A. | obs_siafe |
| 14.380.200/0001-21 | SMART FIT | obs_siafe |
| 17.245.234/0001-00 | ECOURBIS AMBIENTAL S.A. | obs_siafe |
| 38.065.730/0001-44 | GRUPO COMPORTE | obs_siafe |
| 34.028.316/0001-03 | COMLURB | obs_siafe |

---

## CONHECIMENTO ESPECIALIZADO — ORÇAMENTO PÚBLICO E DIREITO ADMINISTRATIVO

### Ciclo Orçamentário Brasileiro (Lei 4.320/64 + CF/88 Art. 165)

```
PPA (4 anos) → LDO (anual) → LOA (anual)
         ↓ execução
EMPENHO (NE) → LIQUIDAÇÃO → PAGAMENTO (OB)
```

| Etapa | Instrumento | Natureza | Reversível? |
|---|---|---|---|
| Empenho | Nota de Empenho (NE) | Reserva de dotação | Sim (anulação) |
| Liquidação | Nota de Liquidação (NL) | Ateste de entrega | Parcialmente |
| Pagamento | Ordem Bancária (OB) | Saída de caixa | Não |

**Regra de ouro:** OBs são o único dado definitivo de pagamento. Empenhos podem ser emitidos e anulados no mesmo exercício.

### Modalidades de Licitação (Lei 14.133/2021 — nova LLCA)

| Modalidade | Valor (obras) | Valor (serviços) | Critério |
|---|---|---|---|
| Dispensa eletrônica | < R$ 100k | < R$ 50k | Menor preço |
| Concorrência | > R$ 3,3M | > R$ 1,65M | Vários |
| Pregão eletrônico | Qualquer | Qualquer | Menor preço |
| Tomada de Preços (revogada) | Até R$ 1,43M | Até R$ 715k | — |
| Convite (revogado) | Até R$ 330k | Até R$ 176k | — |

**Lei 8.666/93** (revogada em 01/04/2023 pela Lei 14.133/21) ainda rege contratos firmados sob sua vigência.

### Ilícitos Mais Relevantes — Contratação Pública

| Conduta | Fundamento | Pena |
|---|---|---|
| Fracionamento de despesa | Art. 89 Lei 8.666/93 / Art. 337-E CP | Detenção 2-4 anos + multa |
| Dispensa irregular | Art. 89 Lei 8.666/93 | Idem |
| Superfaturamento | Art. 96 Lei 8.666/93 / Art. 337-J CP | Reclusão 3-8 anos |
| Direcionamento de licitação | Art. 90 Lei 8.666/93 / Art. 337-F CP | Detenção 2-4 anos |
| Pagamento antecipado irregular | Art. 38 Decreto 93.872/86 | Responsabilidade administrativa |
| Conluio entre licitantes | Art. 36 Lei 12.529/11 (CADE) | Multa 0,1%-20% faturamento |

### Controle Externo — RJ

| Órgão | Competência | Base Legal |
|---|---|---|
| TCE-RJ | Controle externo estadual/municipal | CE-RJ Art. 97 |
| TCU | Controle externo federal | CF/88 Art. 71 |
| CGU | Controle interno federal | Lei 10.683/03 |
| MP-RJ/GAECO | Ação penal | CF/88 Art. 127 |
| CGE-RJ | Controle interno estadual | Lei RJ 287/79 |

### Registros de Irregularidades — Bases de Dados

| Base | Gestor | Conteúdo |
|---|---|---|
| CEIS | CGU | Empresas sancionadas com suspensão/impedimento |
| CNEP | CGU | Multas e acordos de leniência |
| CEPIM | CGU | Entidades inadimplentes (convênios federais) |
| BNC | CGU | Obras embargadas / paralisadas |
| BNAFAR | ANVISA | Irregularidades sanitárias |
| Lista OFAC | OFAC (EUA) | Sanções internacionais |
| Lista FATF | GAFI | Países e entidades de risco |
| Sintegra | Estadual | Situação fiscal/ICMS |
| Cadastro TCE-RJ | TCE-RJ | Inabilitações estaduais |

### Indicadores de Risco — Metodologia TCU

**Matriz P×I (Probabilidade × Impacto):**
- Escala: 1 (mínimo) a 9 (máximo) para P e I
- Pontuação: P × I = Score (1–81)
- Faixas: Baixo 1–9 | Médio 10–39 | Alto 40–79 | Extremo 80–81

**Red flags clássicos (ACFE Report to the Nations 2024):**
- Concentração ≥60% em único órgão sem justificativa técnica
- Série de dispensas de licitação abaixo do teto regulatório
- Aditivos sucessivos totalizando >25% (Lei 8.666 Art. 65 §1º) ou >50% (serviços por TI)
- Pagamentos em datas atípicas (fim de exercício, véspera de eleições, feriados)
- Ausência de publicação no PNCP (obrigatório, Lei 14.133 Art. 94)
- Gap entre empenho e liquidação > 90 dias sem justificativa
- Contratos "Em Vigor" sem execução financeira por > 12 meses

### SIAFE-Rio 2 — Estrutura de Dados

| Dado | Localização SIAFE | Relevância |
|---|---|---|
| Empenhos (NE) | Execução > Despesa > Consultas | Base — sujeito a cancelamento |
| Liquidações (NL) | Execução > Despesa > Consultas | Confirma entrega |
| OBs Pagamentos | Execução > Tesouraria > OBs | Definitivo — source of truth |
| Contratos | Execução > CDP | Metadados contratuais |
| UGs (Unidades Gestoras) | Cadastros > Entidades | Mapeamento de órgãos |

**Exercícios mapeados (SIAFE-Rio 2):** `{2027: "0", 2026: "1", 2025: "2", 2024: "3", 2023: "4"}`

### UGs Relevantes — Estado do Rio de Janeiro

| UG | Órgão |
|---|---|
| 270005 | Fundo Especial do Tribunal de Justiça (FUNETJ) |
| 270009 | Fundo Especial da PGE |
| 270016 | Fundo Especial do Corpo de Bombeiros (FUNESBOM) |
| 270020 | RIOPREVIDÊNCIA |
| 270024 | INEA |
| 270029 | Fundo Estadual de Saúde |
| 270042 | ITERJ (Instituto de Terras e Cartografia) |
| 270051 | Secretaria de Polícia Militar |
| 270060 | Casa Civil |
| 300100 | Tesouro Estadual |

> ⚠️ **Dois sistemas de numeração de UG.** A tabela acima é do **SIAFE-Rio 2**. Os dados abertos
> **TFE** (que alimentam `data/compliance.db`) usam **outra numeração** (6 dígitos, ex.: `166100`,
> `036100`, `133100`). **Não confundir.**
>
> **APRENDIZADO 2026-06-06 — ITERJ:** no espelho TFE/`compliance.db`, **ITERJ = UG `133100`**
> (SIAFE-Rio 2 = `270042`). As Ordens Bancárias (`ordens_bancarias.ug_nome`) rotulavam a UG 133100
> com o nome do **órgão superior** ("Secretaria de Estado de Infraestrutura e Obras/Cidades"), fazendo
> os pagamentos do ITERJ "sumirem" dentro da Secretaria. A tabela `despesa_execucao.nome_ug` traz o
> nome **correto** da unidade. Correção implementada em `compliance_agent/ugs.py` (mapa canônico
> `data/ug_canonico.json` + overrides curados) e aplicada em todos os relatórios: o nome do órgão é
> resolvido pelo **código** da UG, não pelo texto da OB. Para regerar o mapa:
> `python -m compliance_agent.ugs --reconstruir`.

---

## PADRÃO DE RELATÓRIO DE INTELIGÊNCIA

Todo relatório gerado deve seguir este padrão mínimo:

1. **Cabeçalho de capa** — classificação, CNPJ, data, analista, metodologia, fontes
2. **Sumário executivo** — rating visual de risco, tabela de exposição, alertas prioritários
3. **Perfil cadastral** — dados Receita Federal + verificação em listas restritivas (CEIS/CNEP)
4. **Análise de contratos** — HHI de concentração, aditivos, situação
5. **Análise financeira** — empenhos brutos + OBs confirmadas (quando disponíveis)
6. **Matriz de risco** — metodologia TCU P×I, mapa de calor
7. **Red flags de compliance** — com fundamento legal específico (artigo + lei)
8. **Linha do tempo** — eventos relevantes cronológicos
9. **Recomendações** — priorizadas por nível (imediato / curto / estrutural)
10. **Referências** — fontes nacionais (CGU, TCU, TCE-RJ) e internacionais (FATF, ACFE, OCDE)

---

## MOTOR DE RELATÓRIOS E BARRAMENTO DE AGENTES (atualizado 2026-06-06)

> Documentação completa da sessão: [`docs/HANDOFF-2026-06-06-SESSAO-COMPLETA.md`](docs/HANDOFF-2026-06-06-SESSAO-COMPLETA.md).
> Ambiente e workflow de boot: [`AMBIENTE.md`](AMBIENTE.md) + [`ambiente.json`](ambiente.json).

O **Yoda** (bot Telegram) é o MAESTRO e aciona o JFN pela **API HTTP em `127.0.0.1:8000`** (`server.py`,
`jfn.service`). Rotas do barramento:

| Rota | O que faz |
|---|---|
| `POST /api/relatorio/inteligencia` `{empresa\|cnpj, anos?}` | Relatório de Inteligência de **Fornecedor** |
| `POST /api/relatorio/orgao` `{orgao\|ug, anos?}` | Relatório de Inteligência de **Órgão** (quanto a UG pagou e a quem) |
| `GET/POST /api/massare/{placar,cenarios,prever}` | Massare (mercado/predição) |
| `GET /api/siafe/stats` | OBs do SIAFE (OB Orçamentária) coletadas/ingeridas |

**Motores:** `compliance_agent/reporting/inteligencia.py` (fornecedor), `inteligencia_orgao.py` (órgão),
`planilha.py` (Excel). Rodar pela CLI: `.venv/bin/python -m compliance_agent.reporting.inteligencia "MGS Clean"`.
Resolvem por **nome parcial ou CNPJ/UG**; se ambíguo, devolvem `{ambiguo:true, pergunta, candidatos}`.

**Toda saída tem 3 formatos:** `.md` + `.pdf` (fonte Unicode DejaVu) + **`.xlsx` interativo** (Tabela do Excel
com autofiltro; abas Resumo/Pagamentos/Concentração [+ "Por Fornecedor" no de órgão]).

**`/relatorio` de FORNECEDOR gera 3 DOCUMENTOS** (o Yoda envia os 3): (1) PDF de inteligência, (2) planilha XLSX,
(3) **Parecer do agente LEX** (`compliance_agent/lex.py`) — avaliação fático-jurídica/tomada de contas, mesma
estética, com `grau_lex` 🟢/🟡/🔴. Lex aplica os red flags do controle externo (TCU/TCE-RJ) aos dados +
processos SEI correlacionados; base jurídica em [`docs/LEX-BASE-JURIDICA.md`](docs/LEX-BASE-JURIDICA.md). Retorno
do endpoint: `path_pdf`, `path_xlsx`, `path_lex`, `grau_lex`.

**Lex LÊ A ÍNTEGRA do SEI** (módulo do JFN ligado ao Lex): `_ler_integra_sei()` usa `collectors/sei_cdp.py`
(Chrome 9222 + OCR de CAPTCHA) com fallback em `collectors/sei_portal.py` (httpx), extrai objeto/modalidade/
documentos/CNPJs/valores e gera achados sobre o **texto real** (R5 dispensa/inexigibilidade, R3 pesquisa de
preços, R9 aditivos, R7 restrição) — seção "II-B" do parecer. Env: `JFN_LEX_LER_SEI`, `JFN_LEX_MAX_SEI`,
`JFN_LEX_SEI_BUDGET`. ⚠️ **Bloqueio de infra:** da VM (IP GCP) o `sei.rj.gov.br` é barrado por **WAF**
("Web Page Blocked") e `consultaprocessos.rj.gov.br` não resolve DNS — a leitura efetiva exige **IP
autorizado/proxy**; o Lex detecta a página de WAF e reporta honestamente. Cache 24h em
`data/sei_cache/cdp_*.json`: se preenchido de um IP permitido, o parecer passa a usar a íntegra.

**Correlação OB↔SEI** (`compliance_agent/correlacao_sei.py`): o SIAFE traz o **processo SEI** que originou cada OB
(campo Processo). `correlacionar()` casa por `numero_ob`+UG e preenche `ordens_bancarias.numero_sei` (SIAFE
prepondera). É o insumo do Lex (`processos_de_fornecedor(cnpj)`).

**Obrigatório em todo relatório:** a seção **"Análise Jurídica e de Mérito — Parecer Preliminar do JFN"**
(`parecer_fornecedor`/`parecer_orgao`): mérito + avaliação jurídica (CF/88 art.37, Lei 14.133/8.666/4.320,
TCU/ACFE) + grau de atenção + ressalvas. **Honesto:** indícios a verificar, NUNCA afirma irregularidade nem
inventa número (presunção de regularidade dos atos administrativos).

**UGs canônicas:** `compliance_agent/ugs.py` + `data/ug_canonico.json` resolvem o nome do órgão pelo **código
da UG** (as OBs às vezes rotulam a UG com o órgão superior). Aprendizado-chave: **ITERJ = UG 133100** (ver §
"UGs Relevantes"). Regerar: `python -m compliance_agent.ugs --reconstruir`.

**Base de dados:** `ordens_bancarias` (OB = pagamento) cobre **2019–2026** (gestão Cláudio Castro), ingerida do
ZIP TFE via `compliance_agent.collectors.tfe_ob`. Anos sem OB do favorecido não aparecem — normal.

**Coletor SIAFE (OB Orçamentária):** `compliance_agent/siafe_ob_orcamentaria.py` raspa a tela
"Execução > Execução Financeira > OB Orçamentária" do SIAFE-Rio 2 (login real via Playwright; arquitetura ADF
documentada em [`docs/SIAFE-ARQUITETURA.md`](docs/SIAFE-ARQUITETURA.md)). Traz **23 colunas ricas** (NL, PD,
**Processo**, Credor, Competência...) que o TFE não tem, e ingere na tabela **`ob_orcamentaria_siafe`**
(**SIAFE prepondera** por `numero_ob`). CLI: `python -m compliance_agent.siafe_ob_orcamentaria --exercicio 2025
--max 1000 --ingerir --resiliente`. Anos liberados na conta: **2024–2026** (2023 bloqueado pelo servidor — o
coletor detecta e pula). Sessão única do SIAFE: coordenação via Telegram (`/siafelivre`, `/siafeocupado`,
flag `siafe_coord.json`). **Limitação conhecida:** a varredura COMPLETA por UG (passar do limite de 1000/consulta)
depende do filtro rico do ADF, que resiste a eventos sintéticos do Playwright — ver §8b do doc de arquitetura
(caminho: replay HTTP do request de filtro, ou Computer Use).

---

## OPERAÇÃO MULTIPLATAFORMA (um repo, três alvos)

O mesmo repositório roda em três lugares. **Não** colocar caminhos fixos de SO no
código (ex.: `C:\...`); usar `Path` relativo, `platform.system()` ou variável de ambiente.

| Alvo | Caminho | Como rodar |
|---|---|---|
| **Windows desktop** | `C:\JFN\jfn` | `JFN.bat` / `.bat` launchers; Chrome real na porta 9222 |
| **VM Linux GCP** | `~/JFN` | `docker compose up -d` **ou** `python server.py --host 0.0.0.0 --port 8000` |
| **GitHub Actions** ("rodar no git") | nuvem | aba **Actions** → `coletar-obs-siafe` → **Run workflow** (disparável pelo celular) |

**Celular:** controle via **Telegram** (comandos do JFN / bot Yoda) e disparo do
workflow pelo app do GitHub. O painel web (porta 8000) **não** é exposto à internet por padrão.

### Variáveis de ambiente (resumo — ver `.env.example`)
- **LLM (≥1 obrigatória):** `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `FREE_LLM_PREFER`.
- **SIAFE (rede gov/Actions):** `SIAFE_USER`, `SIAFE_PASS`, `SIAFE_CLIENTE`, `SIAFE_EXERCICIO`.
- **Telegram (celular):** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- **Portabilidade (opcionais):** `TESSERACT_CMD` (caminho do Tesseract), `JFN_DATA_DIR` (pasta de dados).
- **Outras:** `HERMES_MAX_TOKENS`, `SEI_CAPTCHA_TENTATIVAS`, `AUDITOR_24H_INTERVALO`, `ANTHROPIC_API_KEY`.

### Setup rápido (Linux/VM)
```bash
pip install -r requirements.txt && playwright install chromium
cp .env.example .env   # preencher as chaves
python server.py --host 0.0.0.0 --port 8000
```
No Docker, o `Dockerfile` já instala Chromium **e** Tesseract (pt) para o OCR do SEI.

> **Handoff de portabilidade:** ver `docs/HANDOFF-2026-06-05-multiplataforma.md` —
> passo a passo do que foi tornado independente de SO e como testar/validar em cada alvo.
