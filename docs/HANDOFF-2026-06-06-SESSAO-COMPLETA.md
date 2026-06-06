# HANDOFF COMPLETO — Sessão 2026-06-06 (para outra IA avaliar)

> **Leia tudo antes de mexer.** Este é o registro consolidado de TODO o trabalho desta sessão, com o
> porquê, os arquivos, os comandos exatos e como validar. Ambiente = **VM Linux GCP (Ubuntu 24.04)**, NÃO
> Windows. Verdade do ambiente: [`../AMBIENTE.md`](../AMBIENTE.md) + [`../ambiente.json`](../ambiente.json).
> Autor: Claude Code (Opus 4.8) a pedido do Mestre Jorge. Branch: `claude/ambiente-e-relatorio`.
> Commits: `c510502`, `aa50334`, `13b7f62` (pushed para `origin`).
>
> Regras do Mestre Jorge respeitadas: código em **branch dedicada**; **honestidade** (REAL vs CACHE/INDISPONÍVEL,
> nunca fabricar número; OB = pagamento, ≠ empenho); documentar para outra IA; passos idempotentes.

---

## 1. Problema que originou tudo

O Mestre Jorge pediu no Telegram "gere um relatório do JFN sobre o fornecedor MGS" e o **Yoda falhou**:
pediu esclarecimento, tentou uma ferramenta inexistente (`web_search`) e perguntou "como ativo o JFN agente
auditor?". Diagnóstico: causa **estrutural**, não pontual —
1. os agentes não sabiam o **ambiente** (o system prompt do Yoda dizia que o JFN ficava em `c:/JFN/jfn`,
   caminho **Windows** que não existe na VM);
2. o Yoda não sabia **acionar** o JFN (não sabia que o JFN é um servidor HTTP em `127.0.0.1:8000`);
3. havia um **bug de boot**: dois serviços (`yoda.service` de sistema e `hermes-gateway.service` de usuário)
   brigavam pelo mesmo bot do Telegram (loop de FAILURE/restart).

**Visão acordada:** o **Yoda é o MAESTRO** — bot do Telegram que orquestra os outros agentes (JFN, Massare)
chamando a **API do JFN** (barramento único). O JFN é o motor.

---

## 2. O que foi feito (por blocos)

### Bloco A — Infra e boot
- **Desabilitado** o `yoda.service` (systemd de SISTEMA), duplicado: `sudo systemctl disable --now yoda.service`.
  Gateway canônico do Yoda = `hermes-gateway.service` (user). **Não reativar o de sistema.**
- **Instalados Google Chrome 149 + Chromium 149**. Criado **`chrome-jfn.service`** (user) = ponte Chrome
  headless CDP na porta **9222** (habilita coleta TFE/SIAFE ao vivo). Sobe no boot.
- Units versionados em [`../deploy/systemd/`](../deploy/systemd/) (README com passo a passo de instalação).

### Bloco B — Fonte única de verdade do ambiente
- Criados **`AMBIENTE.md`** (narrativo) e **`ambiente.json`** (legível por máquina): VM, os 4 agentes,
  caminhos, portas, **workflow de boot** (serviços + timers) e o **barramento** (rotas da API do JFN).
- Corrigido o system prompt do Yoda (`~/.hermes/config.yaml`): `c:/JFN/jfn` → `/home/jfelippebethlem/JFN`,
  + mapa de capacidades (qual rota chamar) + "não existe `web_search`".
- Ponteiros para `AMBIENTE.md` em: `CLAUDE.md`, `README-AGENTES.md`, `~/.hermes/SOUL.md`, `massare/README.md`.
- Memória do Yoda (`~/.hermes/memories/MEMORY.md` e `USER.md`) com as rotas, o fluxo de desambiguação e o
  envio PDF+XLSX. (Esses arquivos `~/.hermes/*` são runtime, fora do git do JFN; têm backup `.bak`.)

### Bloco C — Barramento de agentes no JFN (FastAPI, `server.py`, porta 8000)
Novos endpoints:
| Rota | Função |
|---|---|
| `POST /api/relatorio/inteligencia` | Relatório de Inteligência de **Fornecedor** (nome parcial ou CNPJ) |
| `POST /api/relatorio/orgao` | Relatório de Inteligência de **Órgão** (nome do órgão ou código de UG) |
| `GET /api/massare/placar` · `GET /api/massare/cenarios` · `POST /api/massare/prever` | Massare (mercado) |

### Bloco D — Os relatórios (o padrão robusto, "nosso padrão sempre")
Motores: `compliance_agent/reporting/inteligencia.py` (fornecedor) e `inteligencia_orgao.py` (órgão).
Cada relatório tem: capa + sumário executivo; **tabela de OBs pagas POR ANO** (pagamentos individuais);
concentração + **HHI**; **Análise Jurídica e de Mérito — Parecer Preliminar do JFN** (`parecer_fornecedor`/
`parecer_orgao`: mérito + base legal CF/88 art.37, Lei 14.133/8.666/4.320, TCU/ACFE + grau de atenção +
ressalvas; **honesto** — indícios a verificar, nunca afirma irregularidade nem inventa número).
Saídas: **`.md` + `.pdf` (fonte Unicode DejaVu) + `.xlsx`** em `reports/`.

- **Resolução por NOME parcial ou CNPJ**; se ambíguo, retorna `{ambiguo:true, pergunta, candidatos}` para o
  Yoda perguntar ao Mestre Jorge (e chamar de novo com o CNPJ/UG escolhido).
- **Título do relatório de órgão** = "Relatório de Inteligência de \<nome do órgão\>".

### Bloco E — Planilha Excel interativa (`compliance_agent/reporting/planilha.py`)
Anexo PADRÃO de todo relatório. Boas práticas de planilha de auditoria: **Tabela do Excel** (autofiltro +
zebra), **painel congelado**, moeda/data reais, abas **Resumo / Pagamentos (OBs) / Concentração**, e
(no relatório de órgão) **"Por Fornecedor"** com OBs agrupadas por fornecedor (subtotal + linhas colapsáveis).
Formatação condicional: estornos (R$ 0) em vermelho, barras de dados no valor.
> Obs.: a prévia do Telegram NÃO é interativa — abrir em Excel/Google Sheets/WPS.

### Bloco F — Aprendizado de dados: UGs canônicas (ITERJ)
Cada UG (Unidade Gestora) é o código de um órgão. Nas OBs, a UG vinha rotulada com o nome do órgão
**SUPERIOR**. Resolvido: **ITERJ = UG `133100`** (SIAFE-Rio 2 = `270042`); as OBs a chamavam de "Secretaria
de Infraestrutura e Obras". Implementado `compliance_agent/ugs.py` + `data/ug_canonico.json` (gerado de
`despesa_execucao.nome_ug` + `OVERRIDES` curados). Relatórios resolvem o nome do órgão pelo **código** da UG.
Para corrigir/adicionar uma UG: editar `OVERRIDES` e rodar `python -m compliance_agent.ugs --reconstruir`.

### Bloco G — Base ampliada 2019–2026 (gestão Cláudio Castro)
Ingeridas as OBs de **2019, 2020, 2021, 2022** do ZIP TFE (`data/tfe_cache/fornecedor_ob.zip`, já tinha
2017–2026) via `compliance_agent.collectors.tfe_ob.ingest(ano)` (~508 mil OBs). `ordens_bancarias` cobre
**2019–2026**. O timer `jfn-tfe-ob.service` foi atualizado para reingerir 2019–2026.
Anos sem OB do favorecido simplesmente não aparecem no relatório (normal).

### Bloco H — Massare como agente de pregão
`massare/market.py` + `massare-market.timer` (dias úteis, 12:50–21:00 UTC = 09:50–18:00 BRT, a cada 15min):
cenários **multi-horizonte** (curtíssimo=1, curto=5, médio=21, longo=63 pregões) + notícias (Google News RSS)
+ snapshot em `massare/data/market_snapshot.json`. `record=False` (não polui o placar; o `massare-daily`
segue registrando a previsão oficial). Exposto via `/api/massare/*`.

---

## 3. Como rodar e validar (comandos exatos)

```bash
cd ~/JFN
# Testes (devem passar 17+)
.venv/bin/python -m pytest tests/test_relatorio_inteligencia.py -q

# Relatórios pela CLI (gera .md/.pdf/.xlsx em reports/)
.venv/bin/python -m compliance_agent.reporting.inteligencia "MGS Clean"
.venv/bin/python -m compliance_agent.reporting.inteligencia_orgao "iterj"   # ou a UG 133100

# Relatórios pela API (como o Yoda faz)
curl -s -X POST http://127.0.0.1:8000/api/relatorio/inteligencia -H 'Content-Type: application/json' -d '{"empresa":"MGS Clean"}'
curl -s -X POST http://127.0.0.1:8000/api/relatorio/orgao        -H 'Content-Type: application/json' -d '{"orgao":"iterj"}'
curl -s http://127.0.0.1:8000/api/massare/cenarios

# Enviar PDF+XLSX no Telegram (chat 45338178)
TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' ~/.hermes/.env | cut -d= -f2- | tr -d '"'"'"')
curl -s -F chat_id=45338178 -F document=@reports/ARQ.pdf  "https://api.telegram.org/bot${TOKEN}/sendDocument"
curl -s -F chat_id=45338178 -F document=@reports/ARQ.xlsx "https://api.telegram.org/bot${TOKEN}/sendDocument"

# Saúde dos serviços
systemctl --user is-active hermes-gateway jfn chrome-jfn
systemctl --user list-timers massare-market.timer
# Se mexer no server.py: reinicie e espere ~15s (uvicorn só escuta após o startup que tenta login SIAFE)
systemctl --user restart jfn.service
```

### Resultados de referência (para conferir que está igual)
- **MGS CLEAN** (CNPJ 19.088.605/0001-04): pago 2021–2026 = **R$ 136.225.497,94** (sem OB 2019/2020). Maior
  órgão: Fundo Especial do Corpo de Bombeiros (UG 166100), ~59,5%. HHI ALTA.
- **ITERJ** (UG 133100): pago 2019–2026 = **R$ 292.292.309,xx** em ~2.457 OBs a 123+ fornecedores. Maior
  recebedor: **Enge Prat Engenharia ≈ R$ 178,9M** (construtora dominando uma UG de "terras e cartografia" —
  red flag de concentração, ver parecer).

---

## 4. Mapa de arquivos (o que olhar)

| Arquivo | Papel |
|---|---|
| `AMBIENTE.md`, `ambiente.json` | Verdade do ambiente + barramento. |
| `compliance_agent/reporting/inteligencia.py` | Motor do relatório de fornecedor (+ `parecer_fornecedor`, PDF). |
| `compliance_agent/reporting/inteligencia_orgao.py` | Motor do relatório de órgão (+ `parecer_orgao`). |
| `compliance_agent/reporting/planilha.py` | Planilha Excel interativa (anexo padrão). |
| `compliance_agent/ugs.py` + `data/ug_canonico.json` | UG → nome canônico (correção ITERJ). |
| `compliance_agent/collectors/tfe_ob.py` | Coletor/ingestor de OBs do TFE (2017–2026 no ZIP). |
| `massare/market.py` | Massare no pregão (cenários multi-horizonte). |
| `server.py` | Endpoints REST (barramento). |
| `tests/test_relatorio_inteligencia.py` | 17 testes. |
| `deploy/systemd/` | Units systemd (chrome-jfn, massare-market, jfn-tfe-ob, etc.). |
| `docs/HANDOFF-2026-06-06-relatorios-inteligencia.md` | Handoff focado nos relatórios. |
| `hermes-yoda/process_documentation.md` | Log cronológico (append-only). |

---

## 5. Pendências / pontos honestos

- O **`massare-market.timer` só dispara em dia útil** — primeiro disparo ao vivo: segunda 12:00 UTC.
- O **token do GitHub está embutido no remote** do JFN (já estava antes; consta na memória do projeto **a
  rotacionar**). Não logar/expor.
- **Enriquecimento** do relatório de fornecedor (perfil/sanções/rede via `relatorio_riscos`) depende de rede;
  se o egress falhar, a seção sai marcada **INDISPONÍVEL** e o resto (OBs/contratos = REAL) sai normal.
- Avisos `DeprecationWarning (ln=True)` do fpdf2 são inofensivos.
- A branch `claude/ambiente-e-relatorio` está **pronta para revisão** (não foi feito merge na
  `claude/rj-finance-agent-BYlhJ` — deixado para validação por outra IA).

---

## 6. Checklist para a IA revisora

- [ ] `pytest tests/test_relatorio_inteligencia.py -q` passa (17+)?
- [ ] `curl` nos 2 endpoints de relatório retorna `ok:true` com `path_pdf` e `path_xlsx`?
- [ ] UG 133100 aparece como **ITERJ** (não "Secretaria de Infraestrutura") nos relatórios?
- [ ] `ordens_bancarias` cobre 2019–2026? (`SELECT DISTINCT exercicio ...`)
- [ ] Os relatórios trazem a seção **Análise Jurídica e de Mérito** e a tabela de **OBs por ano**?
- [ ] A planilha tem Tabela com autofiltro + abas Resumo/Pagamentos/Concentração (+ Por Fornecedor no de órgão)?
- [ ] Nenhum número fabricado? Tudo marcado REAL vs CACHE/INDISPONÍVEL?
- [ ] `systemctl --user is-active hermes-gateway jfn chrome-jfn` = active?
