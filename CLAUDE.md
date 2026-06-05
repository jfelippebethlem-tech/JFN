# CLAUDE.md — JFN Intelligence Engine

**Projeto:** JFN — Agente de Auditoria e Compliance do Estado do Rio de Janeiro  
**Owner:** jfelippebethlem-tech  
**Branch padrão:** `claude/rj-finance-agent-BYlhJ`  
**Repo:** https://github.com/jfelippebethlem-tech/JFN.git

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
