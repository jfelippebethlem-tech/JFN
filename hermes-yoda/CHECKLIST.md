# CHECKLIST.md — Estado do Projeto Yoda/Hermes/JFN

**Atualizado em:** 2026-06-03  
**Próxima revisão:** quando Claude Code retomar ou após mudanças significativas

---

## FUNCIONANDO ✅

- [x] Bot Telegram (Mestre Yoda) operando com auto-start + self-heal
- [x] Rotina BOM DIA agendada para 7:00
- [x] Formato final aprovado por Mestre Jorge (clima + piada + versículo + mercado + notícias Brasil/Rio)
- [x] Links de notícias sem encurtamento (URLs completas)
- [x] yfinance instalado e retornando cotações (Bovespa, Dólar, Ouro, Petróleo)
- [x] Browser automático para notícias (UOL, Folha, O Globo, G1, Tempo Real)
- [x] Memória persistente carregada (regras, identidades, protocolos)
- [x] Repo Yoda/Hermes criado no GitHub e populado
- [x] Mapa de agentes commitado no JFN
- [x] Skills instaladas: kanban-orchestrator, disk-cleanup, langfuse
- [x] Provedores configurados no Hermes (Ollama local + alternativas externas)
- [x] Documentação completa do SEI e pendências em `C:\JFN\jfn\pendencias-SEI.md`
- [x] Scripts de auto-start e self-heal no repo Yoda/Hermes

---

## BLOQUEADO / AGUARDANDO ⏸️

- [ ] `execute_code` — bloqueado por hosted tools quota (aguardando reset)
- [ ] Gemini API — cota zerada (HTTP 429), aguardando renovação
- [ ] DXY (USD Index) — bloqueado no Yahoo Finance, precisa de fonte alternativa
- [ ] `hermes gateway restart` — trava no Windows, usar reset de `gateway_state.json`
- [ ] Plugins não instalados: google-meet, kanban dashboard, achievements, self-evolution, web-search-plus
- [ ] Repositórios de mercado pendentes: akshare, FinceptTerminal (deps não resolvidas)
- [ ] TLS/SEI automation — bloqueado por handshake, aguardando liberação de rede

---

## FAZER EM BREVE 🔜

### Curto prazo
- [ ] Testar rotina BOM DIA ao vivo quando chegar 7:00
- [ ] Validar links das notícias no Telegram (paywall/redirect)
- [ ] Instalar `py_mini_racer` para destravar akshare
- [ ] Fechar processos Python travando xlrd (FilePermissionError)

### Médio prazo
- [ ] Resolver divergência na branch remota JFN (`claude/rj-finance-agent-BYlhJ`)
- [ ] Instalar plugins restantes (google-meet, achievements, self-evolution)
- [ ] Configurar fonte alternativa para DXY
- [ ] Migrar auto-start script para pasta correta do Windows Startup

### Longo prazo
- [ ] Integração Composio Connect (OAuth) para expandir apps acessíveis
- [ ] Implementar fallback automático entre provedores (Gemini → Ollama → OpenRouter)
- [ ] Adicionar notícias setoriais (energia, infraestrutura, Óleo&Gás)
- [ ] Automatizar coleta DOERJ/SIAFE quando SEI liberar

---

## ERROS CONHECIDOS E TRATAMENTO

| Erro | Onde | Causa | Tratamento |
|---|---|---|---|
| `Plugin 'X' is not installed or bundled` | hermes plugins | Não está no pacote built-in | Instalar via skill ou clone externo |
| `gateway_state.json` corrompido | Auto-start | Windows trava encoding | Deletar e rodar `hermes gateway run` |
| No response 240s do provedor | API externa | Rate limit ou cota | Trocar para Ollama local ou provedor alternativo |
| `xlrd em uso por outro processo` | pip install | Lock de arquivo no Windows | Fechar processos Python e reinstalar |
| CAPTCHA Google/Bing | browser_navigate | Detecção de bot | Usar curl direto ou fontes alternativas |
| HTTP 429 APIs de mercado | yfinance/Yahoo | Rate limit | Esperar ou usar fonte alternativa |

---

## COMANDOS ÚTEIS (referência rápida)

```bash
# Git (JFN)
cd C:\JFN\jfn
git add .
git commit -m "tipo: descrição"
git push origin claude/rj-finance-agent-BYlhJ

# Git (Yoda/Hermes)
cd C:\Hermes_Yoda
git add .
git commit -m "tipo: descrição"
git push origin main

# Hermes — health check
hermes status

# Hermes — instalar plugin
hermes plugins enable disk-cleanup

# Hermes — instalar skill
hermes skills install official/devops/kanban-orchestrator

# Hermes — resetar gateway (quando travar)
del %USERPROFILE%\.hermes\gateway_state.json
hermes gateway run

# Ollama — ver modelos
curl http://127.0.0.1:11434/api/tags

# Rodar rotina manualmente (se precisar)
hermes cron run bom-dia-mestre-jorge
```

---

## NÃO FAZER (bloqueios éticos/técnicos)

- ❌ Não burlar TLS/SSL do SEI
- ❌ Não forçar push se rejeitar por divergência
- ❌ Não inventar dados de mercado
- ❌ Não usar `execute_code` para scripts arbitrários
- ❌ Não encurtar links de notícias
- ❌ Não criar "modo sem ética" ou provedores alternativos para bypass

---

## MEMÓRIA DO HERMES — ATENÇÃO

**Problema atual:**  
A memória persistente do Hermes está em **96%** (aproximadamente 2.113/2.200 caracteres).  
Quando ela encher, novos fatos não entram mais.

**Causas prováveis:**  
- Entradas duplicadas ou inchadas no profile  
- Regras repetidas que já deveriam estar só no repo  
- Falta de limpeza/consolidação

**O que o Claude Code deve fazer:**  
1. Verificar `hermes memory usage` ou o equivalente disponível no ambiente  
2. Identificar entradas duplicadas ou que já estão bem documentadas no repo  
3. Consolidar em até 3 entradas curtas e objetivas  
4. Confirmar queda para abaixo de 75%  
5. Atualizar este checklist após a limpeza

**Regra:** não dependa de memória cheia para lembrar do básico — o principal já está documentado no repo.

---

## PRÓXIMA SESSÃO (para Claude Code)

1. Ler `CLAUDE.md`, `CHECKLIST.md` e `SESSAO-COMPLETA-2026-06-03.md`
2. Verificar status do `gateway` e `hermes status`
3. Checar se rotina BOM DIA foi enviada hoje
4. Se `execute_code` voltar, priorizar instalar `py_mini_racer`
5. **Resolver advertência de memória cheia documentada acima**
6. Atualizar este checklist após qualquer mudança

---

## ARQUIVOS DE REFERÊNCIA

- `C:\Hermes_Yoda\CHECKLIST.md` — este arquivo
- `C:\Hermes_Yoda\CLAUDE.md` — instruções para Claude Code
- `C:\Hermes_Yoda\SESSAO-COMPLETA-2026-06-03.md` — histórico detalhado
- `C:\Hermes_Yoda\templates\bom-dia-template.md` — formato oficial da rotina
- `C:\JFN\jfn\README-AGENTES.md` — mapa de agentes Yoda/Hermes/JFN
- `C:\JFN\jfn\pendencias-SEI.md` — pendências SEI/DOERJ/SIAFE
- `C:\Users\socah\Desktop\IAs boas pra codigo.txt` — lista de providers
- `C:\Users\socah\Desktop\hermes-plugins-passo-a-passo.txt` — guia de plugins

---

## CONTATOS E CREDENCIAIS

- **GitHub user:** jfelippebethlem-tech
- **Telegram chat_id:** 45338178
- **Hermes config:** C:\Users\socah\.hermes\config.yaml
- **JFN path:** C:\JFN\jfn
- **Yoda path:** C:\Hermes_Yoda
- **Branch JFN:** claude/rj-finance-agent-BYlhJ
