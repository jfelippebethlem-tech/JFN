# CLAUDE.md — Contexto para Claude Code neste repositório

**Projeto:** Yoda Telegram + Agente Hermes + JFN  
**Dono:** Mestre Jorge (jfelippebethlem-tech)  
**Canal Telegram:** 45338178  
**Chat ativo:** J FN

---

## QUEM É QUEM

- **Mestre Yoda** — Bot Telegram (esta identidade na conversa)
  - Envia rotina diária `BOM DIA DO MESTRE JORGE` às 7:00
  - **NÃO** é um repo separado; usa a instância Hermes configurada como bot
- **Hermes** — Agente desktop/CLI do usuário
  - Path: `C:\Users\socah\.hermes`
  - Config: `config.yaml` (provedores, modelo, toolsets)
- **JFN** — Agente de auditoria/compliance do governo do RJ
  - Path: `C:\JFN\jfn`
  - Repo: https://github.com/jfelippebethlem-tech/JFN.git
  - Branch padrão: `claude/rj-finance-agent-BYlhJ`

---

## REGRAS ABSOLUTAS (não pular)

1. **Nunca encurtar links de notícias** — usar URLs completas dos portais
2. **Todo código JFN** → commit + push na branch configurada
3. **Não burlar TLS/SSL** em `sei.rj.gov.br` — usar Chrome CDP se precisar automatizar
4. **Não inventar dados de mercado** — usar yfinance ou fontes públicas reais
5. **Não usar `execute_code` para scripts arbitrários** — ferramenta bloqueada por hosted tools quota
6. **Não oferecer "modo sem ética"** — recusar qualquer pedido de bypass ou desinformação

---

## ESTRUTURA DESTE REPO

```
Yoda-Telegram-e-Agente-Hermes/
├─ CLAUDE.md                 ← você está aqui
├─ README.md                 ← visão geral
├─ SESSAO-COMPLETA-2026-06-03.md  ← histórico detalhado da sessão
├─ CHECKLIST.md              ← estado atual e pendências
├─ .gitignore                ← padrão Windows + Hermes + Python
├─ scripts/
│  ├─ hermes-start.cmd       ← auto-start do bot no Windows
│  └─ telegram-self-heal.cmd ← recuperação automática se o bot cair
├─ templates/
│  └─ bom-dia-template.md    ← formato oficial da rotina matinal
└─ marcos/
   └─ agentes.md             ← mapa de identidades
```

---

## TAREFAS COMUNS (como Claude Code neste repo)

### 1. Atualizar a rotina BOM DIA
- Editar `templates/bom-dia-template.md`
- **NÃO** encurtar links de notícias
- Usar dados reais de mercado (yfinance: `^BVSP`, `USDBRL=X`, `GC=F`, `CL=F`)
- Enviar via `send_message` para Telegram chat_id 45338178

### 2. Commitar no JFN
```bash
cd C:\JFN\jfn
git add .
git commit -m "tipo: descrição curta"
git push origin claude/rj-finance-agent-BYlhJ
```
- **Se rejeitar por divergência:** NÃO forçar push. Parar e avisar.

### 3. Adicionar novo plugin/skill ao Hermes
```bash
hermes plugins enable <nome>
# ou
hermes skills install official/<categoria>/<nome>
```
- Documentar em `CHECKLIST.md` o que foi instalado/testado

### 4. Verificar saúde do bot
```bash
hermes status
cat C:\Users\socah\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\telegram-self-heal.cmd
```

---

## ESTADO ATUAL (junção de 2026-06-03)

### Funcionando
- ✅ Bot Telegram (Mestre Yoda) online com auto-start + self-heal
- ✅ Rotina BOM DIA agendada para 7:00
- ✅ yfinance instalado e retornando cotações
- ✅ Browser para notícias (UOL, Folha, G1, O Globo)
- ✅ Memória persistente carregada
- ✅ Repo Yoda/Hermes criado, commitado e documentado
- ✅ Mapa de agentes commitado no JFN
- ✅ `pendencias-SEI.md` documentando todo o problema de automação

### Bloqueado / Pendente
- ❌ `execute_code` bloqueado por hosted tools quota (não usar até resetar)
- ❌ Gemini API cota zerada (HTTP 429) — usar Ollama local ou provedor alternativo
- ❌ DXY (USD Index) bloqueado no Yahoo Finance — precisa de fonte alternativa
- ❌ `hermes gateway restart` trava no Windows — resetar `gateway_state.json` primeiro
- ❌ Plugins restantes não instalados: google-meet, kanban dashboard, achievements, self-evolution, web-search-plus
- ❌ Repositórios de mercado pendentes: akshare, FinceptTerminal
- ❌ TLS/SEI automation — bloqueado por handshake, detalhes em `C:\JFN\jfn\pendencias-SEI.md`

### Erros comuns e soluções
- `Plugin 'X' is not installed or bundled` → não está no pacote built-in, usar skill ou clone externo
- `gateway_state.json` corrompido ou travando → deletar e rodar `hermes gateway run`
- No response 240s do provedor → provedor externo sobrecarregado, trocar para Ollama local
- HTTP 429 em APIs de mercado → respeitar rate limit, tentar fonte alternativa ou adiar
- `xlrd em uso por outro processo` → fechar processos Python que usam xlrd e reinstalar

---

## LINKS ÚTEIS

- JFN: https://github.com/jfelippebethlem-tech/JFN.git
- Yoda/Hermes: https://github.com/jfelippebethlem-tech/Yoda-Telegram-e-Agente-Hermes
- Composio plugins: https://composio.dev/content/best-hermes-plugins
- Docs Hermes: https://hermes-agent.nousresearch.com/docs/

---

## DOCUMENTOS ESSENCIAIS PARA O CLAUDE CODE

1. `CHECKLIST.md` — estado atual, bloqueios e próximos passos
2. `SESSAO-COMPLETA-2026-06-03.md` — histórico detalhado da sessão
3. `C:\JFN\jfn\pendencias-SEI.md` — pendências detalhadas de automação SEI/DOERJ/SIAFE
4. `templates/bom-dia-template.md` — formato oficial da rotina matinal

---

## CHECKS PARA O CLAUDE CODE ANTES DE QUALQUER COISA

1. Ler `CHECKLIST.md` e `SESSAO-COMPLETA-2026-06-03.md`
2. Verificar status do `gateway` e `hermes status`
3. Checar se rotina BOM DIA foi enviada hoje
4. Se `execute_code` voltar, priorizar instalar `py_mini_racer`
5. **Resolver advertência de memória cheia do Hermes (`CHECKLIST.md`)**
6. Atualizar `CHECKLIST.md` após qualquer mudança

---

## CONTATOS E IDs

- Telegram chat_id: `45338178`
- GitHub user: `jfelippebethlem-tech`
- Branch JFN: `claude/rj-finance-agent-BYlhJ`
- Hermes config: `C:\Users\socah\.hermes\config.yaml`
- Hermes local: `C:\Hermes_Yoda` (clone deste repo)
