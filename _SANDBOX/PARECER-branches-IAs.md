# Parecer — branches/commits das IAs (Gemini/Nous) — revisão 2026-06-04

Avaliação crítica do que as IAs mais fracas produziram, com julgamento (aproveitar / descartar)
e o que fiz pra "rodar mais liso conforme nossos parâmetros".

## Julgamento por branch
| Branch | O que é | Veredito |
|---|---|---|
| `claude/yoda-hermes-improvements-YlYXb` | yoda.bat self-heal (Win sem Docker), provedores OpenAI-compat (sem chave Anthropic), comandos /atualizar /metricas /Massare, BOM DIA 07:30, **+ suíte de testes (~3.945 linhas: config, providers, memory, tools...)** | ✅ **BOM** — operacional sólido **com testes**. Aproveitar no deploy do Yoda (revisar antes). |
| `claude/build-agents-TRd73` | `stock_agent/` (backtester pandas, scorer, tracker, notifier) + whatsapp sender | ✅ **Útil p/ o Massare** (análise financeira). Manter no projeto Massare, separado da auditoria. |
| `claude/polimonitor-app-ZClUe` | app polimonitor + agente paralelo autônomo + 17/17 testes | 🟡 **App separado** — parece ok; fora do escopo auditoria. Não misturar. |
| `claude/yoda-deploy-relatorio-20260604` | commits novos = só `docs:` (auto-análise do Gemini: prolixidade, uso do nome, fallback) | 🟡 **Aprendizado, sem código.** As propostas de tuning (que eu já mergei) eram boas; o resto é reflexão. |
| `feature/image-generation-outback-girl` | Stable Diffusion (imagem "menina patinando") + `tmp/*.html` (páginas raspadas) | 🔴 **Tangente + lixo.** Não mergear. Os `tmp/*.html` são lixo de scraping (não versionar). |

## O que aprenderam de bom (lições válidas)
- O **fallback Gemini** funciona e o rodízio de chaves segura a operação (confirmado por elas).
- Auto-crítica de **prolixidade / uso excessivo do nome** — feedback de estilo pertinente.
- Disciplina de **testes** (yoda-hermes-improvements) — é o padrão que queremos.

## O que fiz pra rodar mais liso (conforme nossos parâmetros)
1. **Consolidei a auditoria** num pacote oficial: `compliance_agent/auditoria/` (orquestrador de 1
   comando + coletores + `PASSO-A-PASSO.md`). Antes estava espalhado no `_SANDBOX`.
2. **Auditoria executável por IA fraca**: `python -m compliance_agent.auditoria.auditar_fornecedor <CNPJ> <anos>`
   — testado (MGS CLEAN 2025/2026 OK), gera relatório sozinho.
3. **Parâmetros respeitados**: só leitura, ritmo humano, segredos só no `.env`, dados em `data/sei_cache`,
   relatórios em `reports/`, nada de segredo no git.

## Recomendações (não executadas — decisão do Mestre Jorge)
- **NÃO** mergear `feature/image-generation-*` nem os `tmp/*.html` (lixo) na branch principal.
- Aproveitar os **testes** da `yoda-hermes-improvements` no deploy do Yoda (rodar na VM).
- Manter `stock_agent` (backtester) como base do **Massare**, em pasta própria.
- Padronizar: toda IA fraca cria branch sandbox; eu reviso e só incorporo o que passa nos parâmetros.
