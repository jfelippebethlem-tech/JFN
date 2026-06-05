# Sessão Completa — Hermes Yoda + JFN (2026-06-03)

**Data:** 2026-06-03  
**Usuário:** Mestre Jorge (jfelippebethlem-tech)  
**Canal:** Telegram DM  
**Agente ativo:** Hermes Agent (provedor: gemini → depois ollama local)  
**Teams envolvidas:** Mestre Yoda (Telegram bot), Hermes (desktop), JFN (compliance/auditoria)

---

## 1. OBJETIVOS DA SESSÃO

1. Diagnosticar por que o Gemini parou de responder e mudar provedor
2. Criar rotina automática "BOM DIA DO MESTRE JORGE" no Telegram
3. Instalar repositórios de mercado/finanças no GitHub para alimentar a rotina
4. Buscar plugins do Hermes na página Composio e instalar os gratuitos
5. Commitar tudo no JFN e criar repo separado para Hermes_Yoda

---

## 2. FLUXO DE PROVEDORES E FALHAS

### 2.1 Estado inicial
- **Provedor padrão:** Gemini (`gemini-2.0-flash`) via Google AI
- **Erro:** HTTP 429 — cota esgotada no tier gratuito
- **Mensagem de erro:**
  ```
  Gemini HTTP 429 (RESOURCE_EXHAUSTED): You exceeded your current quota
  ```

### 2.2 Fallback testado
- **Tentativa:** `hermes model ollama-launch llama3.2:3b`
- **Resultado:** timeout no comando interativo (30s)
- **Disponível localmente:** Ollama rodando em `http://127.0.0.1:11434`
  - Modelos disponíveis: `llama3.2:3b`, `ministral-3:3b`
  - `ollama version 0.24.0`
  - `curl http://127.0.0.1:11434/api/tags` retorna lista de modelos
- **Problema:** chamadas ao Ollama pelo Hermes travavam (150s+ sem resposta)
- **Diagnóstico:** contexto da sessão ~95k tokens, modelo 3b não aguenta

### 2.3 Provedores alternativos testados (todos falharam)
- `tencent/hy3-preview:free` — modelo inexistente ou erro de cota
- `inclusionai/ring-2.6-1t:free` — falha após retries
- `stepfun/step-3.7-flash:free` — timeout 240s, sem resposta

### 2.4 Estado final de provedores
- **Gemini:** cota zerada (não usar até renovar)
- **Ollama:** instalado e rodando, mas instável para sessões longas
- **Outros providers criados mas não ativados:** OpenRouter, Mistral, HuggingFace, Nemotron

---

## 3. ROTINA "BOM DIA DO MESTRE JORGE"

### 3.1 Criação
- **Nome do job:** `bom-dia-mestre-jorge`
- **Horário:** 7:30 da manhã (depois ajustado para 7:00)
- **Plataforma:** Telegram (chat_id: 45338178)
- **Conteúdo:** clima Barra da Tijuca + piada + versículo bíblico + notícias (5 Brasil + 5 Rio)

### 3.2 Formato final aprovado
```
Bom dia, Mestre Jorge! 🌅

[Clima]
[Piada]
[Versículo]

---
📰 BRASIL

[Título + resumo + link completo]

---
📰 RIO DE JANEIRO

[Título + resumo + link completo]

---
Boa semana, Mestre Jorge! 💪
```

### 3.3 Decisões tomadas
- **NÃO encurtar links:** manter URLs completas dos portais para não quebrar paywall/redirect
- **Links no corpo:** título + resumo + 🔗 link na mesma linha do item
- **Sem numeração:** apenas separação visual por seções

### 3.4 Testes executados
- Várias versões enviadas com diferentes combinações de notícias
- Fonte de notícias: UOL, Folha, G1, O Globo
- Mercado adicionado depois: dólar, bolsa, ouro, petróleo + insights de analista

---

## 4. MERCADO (dados reais)

### 4.1 Fontes testadas
- **Yahoo Finance (yfinance):** ✅ funcionando para Bovespa e Dólar
  - `^BVSP` → 171.373 pts
  - `USDBRL=X` → 5.048
  - `GC=F` → 4476.10 (ouro)
  - `CL=F` → 95.08 (petróleo WTI)
  - `^DXY` → ❌ bloqueado por rate limit (HTTP 429)

### 4.2 Bloqueios
- UOL Economia: `Access Denied` (bot detection)
- G1 Economia: timeout
- Bing Search: CAPTCHA bloqueando
- Google Search: CAPTCHA bloqueando

### 4.3 Solução adotada
- Usar dados do Yahoo Finance para cotações
- Usar textos das manchetes já acessadas para insights de análise
- DXY marcado como "indisponível no momento" até desbloqueio

---

## 5. REPOSITÓRIOS CLONADOS

### 5.1 Tentativas de instalação
| Repo | Status | Motivo |
|---|---|---|
| `ranaroussi/yfinance` | ✅ baixado | Instalado via pip, funcionando |
| `OpenBB-finance/OpenBB` | ❌ timeout clone | Repo muito grande (>2GB) |
| `Fincept-Corporation/FinceptTerminal` | ✅ baixado | Baixado mas não instalado (xlrd travado) |
| `akfamily/akshare` | ✅ baixado | Dependência `py_mini_racer` faltando |

### 5.2 Estado final dos deps Python
```bash
uv pip install idna requests  # ✅
uv pip install -r requirements.txt  # ❌ xlrd em uso por outro processo
```

### 5.3 Repositórios no filesystem
```
/c/repos/
├─ yfinance/          (já era existente, funcional)
├─ Finance/           (repositório local para dados de mercado)
├─ findatapy/         (encontrado, não ativado)
├─ free-market-data-widgets/  (encontrado, não ativado)
├─ FinceptTerminal/   (baixado, não ativado)
└─ akshare/           (baixado, não ativado)
```

---

## 6. PLUGINS DO HERMES (Composio + Built-in)

### 6.1 Fonte
Artigo: https://composio.dev/content/best-hermes-plugins  
Baixado em `/tmp/hermes-plugins.html` (após curl)

### 6.2 Instalados com sucesso
| Plugin | Comando | Status |
|---|---|---|
| disk-cleanup | `hermes plugins enable disk-cleanup` | ✅ |
| observability/langfuse | `pip install langfuse` + `hermes plugins enable observability/langfuse` | ✅ |
| kanban-orchestrator | `hermes skills load devops/kanban-orchestrator` | ✅ (skill carregada) |

### 6.3 Não instalados / bloqueados
| Plugin | Motivo do bloqueio |
|---|---|
| google-meet | Retornou "not installed or bundled" |
| kanban dashboard | Mesmo motivo acima |
| achievements | Plugin não encontrado na instalação atual |
| composio connect | Requer OAuth + cadastro no Composio |
| honcho / hindsight | Memory providers — requer `hermes memory setup` e escolha no fluxo |
| hermes-agent-self-evolution | Framework externo — precisa clone do GitHub |
| hermes-web-search-plus | Idem — precisa clone + config |

### 6.4 Comandos para instalação futura (não executados)
```bash
# Google Meet
hermes plugins enable google-meet

# Kanban Dashboard
pip install 'hermes-agent[web,pty]'
hermes dashboard

# Memory Providers
hermes memory setup  # escolher Honcho ou Hindsight

# Self-Evolution
git clone https://github.com/composiohq/hermes-agent-self-evolution.git
cd hermes-agent-self-evolution && ./install.sh

# Web Search Plus
git clone https://github.com/composiohq/hermes-web-search-plus.git
cd hermes-web-search-plus && ./install.sh
```

---

## 7. ARQUIVOS CRIADOS/MODIFICADOS

### 7.1 No JFN
- `C:\JFN\jfn\README-AGENTES.md` — Mapa de agentes Yoda/Hermes/JFN
  - Commit: `0ba856a` na branch `claude/rj-finance-agent-BYlhJ`
  - Push: ✅ https://github.com/jfelippebethlem-tech/JFN.git

### 7.2 No Hermes_Yoda (novo repo)
- `C:\Hermes_Yoda\README.md` — Estrutura inicial
  - Commit: `d7a0a5d` no `main`
  - Push: ✅ https://github.com/jfelippebethlem-tech/Yoda-Telegram-e-Agente-Hermes

### 7.3 No Desktop (não versionado)
- `C:\Users\socah\Desktop\IAs boas pra codigo.txt` — Lista de IAs gratuitas para código
- `C:\Users\socah\Desktop\hermes-plugins-passo-a-passo.txt` — Guia de plugins

### 7.4 No JFN (anterior)
- `compliance_agent/captcha_solver.py` — OCR + EasyOCR para SEI
- `compliance_agent/collectors/sei_cdp.py` — Automação SEI via Chrome CDP
- `data/tmp/sei_captchas/` — HTML + captchas de teste
- **Status:** push bloqueado por divergência na branch remota

---

## 8. ERROS E TRATAMENTOS

### 8.1 Erros de rede/TLS
| Erro | Onde | Causa | Solução |
|---|---|---|---|
| `ERR_SOCKET_NOT_CONNECTED` | Python → SEI | Falha TLS handshake em `sei.rj.gov.br` | Usar Chrome CDP via browser já aberto |
| `schannel: failed to receive handshake` | Python → Yahoo Finance | Bloqueio na rede corporativa | Usar dados locais/cache |
| Google CAPTCHA | browser_navigate | Detecção de bot | Usar curl direto ou fontes alternativas |
| HTTP 429 Yahoo Finance | DXY | Rate limit | Desserializar dados de outra fonte ou marcar como indisponível |

### 8.2 Erros de ferramentas
| Erro | Onde | Causa | Resolução |
|---|---|---|---|
| `HTTP 429 Gemini` | API do provedor | Cota esgotada | Mudar para Ollama local (instável) |
| `Plugin 'google-meet' is not installed or bundled` | `hermes plugins enable` | Plugin built-in mas não detectado | Instalar via outra via ou deixar para depois |
| `ModuleNotFoundError: py_mini_racer` | akshare | Dep não instalada | Instalar `py_mini_racer` |
| `xlrd em uso por outro processo` | akshare install | Arquivo bloqueado | Reiniciar terminal |
| `gateway_state.json não existe` | Auto-start script | Script cria arquivo no startup | Resetar e rodar `hermes gateway run` |
| `hermes gateway restart trava encoding` | Windows | Bug no Windows | Resetar `gateway_state.json` primeiro |
| `FilePermissionError: [WinError 32]` | Instalação Python | Arquivo em uso | Fechar processos Python que usam xlrd |
| `Cannot connect to Hermes gateway` | Telegram | gateway não respondendo | Usar script self-heal |

### 8.3 Decisões tomadas sob erro
- Não forçar push do JFN quando deu divergência — abortar para não quebrar remoto
- Não tentar burlar TLS/SSL no SEI — usar CDP do Chrome
- Não insistir em `execute_code` após bloqueio de hosted tools — usar apenas terminal/browser
- Não clonar OpenBB (muito grande) — priorizar repositórios leves

---

## 9. FERRAMENTAS UTILIZADAS NA SESSÃO

### 9.1 Toolsets usados
- `terminal` — comandos bash, git, pip, curl
- `browser_*` — navegação, snapshot, scroll
- `send_message` — envio para Telegram
- `memory` — persistência de regras e preferências
- `write_file`, `patch`, `read_file` — manipulação de arquivos
- `skill_view` — leitura de skills do Hermes
- `cronjob` — criação da rotina de bom dia
- `delegate_task` — (reservado, não usado diretamente aqui)

### 9.2 Toolsets bloqueados
- `execute_code` — bloqueado por cota de hosted tools
- `web_search` — não disponível nesta sessão
- `vision_analyze` — não utilizada diretamente (browser_vision usada)

### 9.3 Scripts Python executados
- **Teste Ollama:** curl POST para `http://127.0.0.1:11434/v1/chat/completions`
- **Leitura yfinance:** `import yfinance as yf` → histórico de cotações
- **Extração HTML:** Python parse do arquivo baixado `/tmp/hermes-plugins.html`

---

## 10. MEMÓRIA PERSISTENTE ATUALIZADA

Entradas salvas no `memory`:

1. **User profile** (4 entradas duplicadas): Mestre Jorge, PT-BR, JFN, direto/minimal
2. **Protocolo Telegram 24h:** auto-start + self-heal
3. **DOERJ pattern:** OCR/CDP para SEI
4. **Rotina Bom Dia:** não encurtar links, usar URLs completas
5. **Telegram bot Mestre Yoda:** identidade separada do Hermes desktop

---

## 11. ESTADO FINAL DO AMBIENTE

### 11.1 Repositórios GitHub
- `jfelippebethlem-tech/JFN` — ativo, branch `claude/rj-finance-agent-BYlhJ`
- `jfelippebethlem-tech/Yoda-Telegram-e-Agente-Hermes` — criado agora, branch `main`

### 11.2 Locais
- `C:\JFN\jfn` — projeto JFN
- `C:\Users\socah\.hermes` — configuração Hermes
- `C:\Hermes_Yoda` — clone do repo novo
- `C:\repos\` — repositórios de mercado/finanças
- `C:\Users\socah\Desktop\*.txt` — guias auxiliares

### 11.3 Provedores configurados
- Gemini (padrão, cota zerada)
- Ollama local (`llama3.2:3b`, `ministral-3:3b`)
- OpenRouter, Mistral, HuggingFace, Nemotron (criados mas não ativados)

### 11.4 Rotinas ativas
- `bom-dia-mestre-jorge` — 7:30 (depois 7:00), Telegram

---

## 12. PENDÊNCIAS

1. **Reparo do SEI:** TLS handshake ainda bloqueado no Python — aguardando liberação de rede
2. **Repositórios de mercado:** akshare e FinceptTerminal não instalados (deps pendentes)
3. **Plugins restantes:** Google Meet, Kanban Dashboard, Achievements, Self-Evolution, Web Search Plus
4. **Token GitHub:** não salvo no ambiente — cria repo atual requer criação manual
5. **DXY:** bloqueado no Yahoo Finance — precisa de fonte alternativa
6. **Divergência remota JFN:** branch `claude/rj-finance-agent-BYlhJ` tem commits não sincronizados

---

## 13. COMANDOS ÚTEIS PARA O CLAUDE CODE

```bash
# Clonar JFN
git clone -b claude/rj-finance-agent-BYlhJ https://github.com/jfelippebethlem-tech/JFN.git C:\JFN\jfn

# Clonar Hermes_Yoda
git clone https://github.com/jfelippebethlem-tech/Yoda-Telegram-e-Agente-Hermes.git C:\Hermes_Yoda

# Ver status do Hermes
hermes status

# Instalar plugins
hermes plugins enable disk-cleanup
hermes plugins enable observability/langfuse
hermes skills load devops/kanban-orchestrator

# Ollama local — ver modelos
curl http://127.0.0.1:11434/api/tags

# Rodar rotina manualmente (se precisar)
hermes cron run bom-dia-mestre-jorge

# Logs do Telegram self-heal
cat C:\Users\socah\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\telegram-self-heal.cmd
```
