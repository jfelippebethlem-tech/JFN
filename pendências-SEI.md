# PENDÊNCIAS — SEI / Automação RJ

Projeto: JFN (compliance/auditoria do governo do RJ)  
Branch: claude/rj-finance-agent-BYlhJ  
Repositório: https://github.com/jfelippebethlem-tech/JFN.git  
Atualizado em: 2026-06-03

---

## 1. BLOQUEIO PRINCIPAL: TLS/SSL no SEI

**Problema:**  
- Python (requests/urllib/Playwright) não consegue fazer handshake TLS com `sei.rj.gov.br`  
- Erro: `ERR_SOCKET_NOT_CONNECTED` / `schannel: failed to receive handshake`  
- O browser do usuário consegue acessar normalmente (Chrome com CDP ativo)

**Causas prováveis:**  
- Bloqueio de rede corporativa (proxy/firewall) para processos Python
- Certificado ou cipher suite incompatível com o Schannel do Windows
- SNI ou TLS version mismatch

**Soluções possíveis (ordem de tentativa):**  
1. Usar Chrome CDP via Playwright (browser já aberto) — caminho atual, funciona parcialmente  
2. Testar `requests` com `verify=False` e headers de browser real  
3. Instalar `certifi` e forçar pacote de certificados atualizado  
4. Testar com `urllib3` + `pyOpenSSL` + `cryptography` mais recentes  
5. Se nada funcionar: solicitar desbloqueio ao time de rede/infra do TJRJ

**Status:** aguardando input do usuário sobre possibilidade de desbloqueio

---

## 2. CAPTCHA DO SEI (180x50px)

**Problema:**  
- Captcha do SEI tem tamanho 180x50 pixels, fundo branco, texto preto
- Todos os testes de OCR retornam string vazia:
  - Tesseract puro
  - EasyOCR puro
  - Preprocessamento: 2x contraste, grayscale + sharpen, invert, 3x resize
  - Combinações de threshold + denoise

**Arquivos de teste disponíveis:**  
- `C:\JFN\jfn\data\tmp\sei_captchas\form.html` — HTML da página de pesquisa
- `C:\JFN\jfn\data\tmp\sei_captchas\captcha_thr180.png` — captcha original
- `C:\JFN\jfn\data\tmp\sei_captchas\thr180.png` — pré-processado
- `C:\JFN\jfn\data\tmp\sei_captchas\captcha_live.png` — captcha vivo que falhou

**Soluções possíveis:**  
1. Testar modelo EasyOCR mais recente (ou trocar por PaddleOCR)  
2. Data augmentation: adicionar ruído, blur, elastic distortion no dataset de treino  
3. Treinar um modelo próprio com poucos exemplos (poucos shots)  
4. Usar API de OCR externa (Google Vision, Azure Computer Vision) — custo, mas preciso  
5. Abordagem CDP+puzzle: clicar no puzzle de arrastar se houver, ao invés deOCR

**Arquivos relacionados:**  
- `compliance_agent/captcha_solver.py`  
- `compliance_agent/collectors/sei_cdp.py`  
- Skill: `captcha-bypass-easyocr`

---

## 3. PLAYWRIGHT / CDP — ESTADO ATUAL

**O que funciona:**  
- Chrome com debugging remoto ativo em porta 9222
- `curl http://127.0.0.1:9222/json/list` retorna tabs abertas
- Playwright conecta via CDP ao SEI
- Consegue preencher o campo de busca de processos

**O que não funciona:**  
- Resolver captcha automaticamente (OCR falha)
- Submissão do formulário sem intervenção manual
- Navegação autônoma pós-login (precisa de cookie/session válidos)

**Próximos passos:**  
1. Salvar cookies da sessão manual para reuso  
2. Implementar fluxo de re-login automático se cookie expirar  
3. Testar se há token CSRF ou hidden fields no form de pesquisa  
4. Mapear todos os endpoints XHR/Fetch da página para replicar via API

---

## 4. DOERJ / SIAFE — COLETA DE DADOS

**Status:** PENDENTE (bloqueado pelo mesmo problema de TLS)

**Fontes:**  
- DOERJ (Diário Oficial do Estado do RJ) — https://www.ioerj.com.br  
- SIAFE (Sistema de Informações de Orçamento e Finanças) — https://siafe2.tj.rj.gov.br

**Abordagem atual:**  
- Usar browser já aberto + CDP para acessar DOERJ
- Extrair texto de PDFs escaneados via OCR (Tesseract/EasyOCR)
- Parsing de tabelas HTML quando disponível

**Desafios:**  
- DOERJ usa PDFs escaneados — precisa de OCR bom
- SIAFE tem autenticação forte (certificado digital?)
- Ambos podem ter bloqueio de rede similar ao SEI

---

## 5. PROBLEMA DE DIVERGÊNCIA NO GIT

**Erro:**  
```
! [rejected]        claude/rj-finance-agent-BYlhJ -> claude/rj-finance-agent-BYlhJ (non-fast-forward)
```

**Causa:**  
- Branch remota tem commits que não existem no local
- Possivelmente outra sessão/IA pushou algo enquanto estávamos trabalhando

**Solução:**  
```bash
cd C:\JFN\jfn
git fetch origin claude/rj-finance-agent-BYlhJ
git rebase origin/claude/rj-finance-agent-BYlhJ
# resolver conflitos se houver
git push origin claude/rj-finance-agent-BYlhJ
```

**NÃO usar `git push --force`** — pode quebrar o repo remoto

---

## 6. PROVIDERS E MODELOS — ESTADO ATUAL

**Configurado em `C:\Users\socah\.hermes\config.yaml`:**  
- Provedor padrão: `ollama-launch`
- Modelo: `llama3.2:3b`
- Toolsets: `hermes-cli`, `web`

**Disponível localmente (Ollama):**  
- `llama3.2:3b` — padrão, funciona mas instável em contexto longo
- `ministral-3:3b` — mais rápido, menos context

**Provedores criados mas não ativados:**  
- OpenRouter
- Mistral
- HuggingFace/Llama
- Nemotron
- Gemini (cota zerada)

**Problema:**  
- `hermes gateway restart` trava no Windows (encoding issue)
- Para trocar provedor: resetar `gateway_state.json` + rodar `hermes gateway run`

---

## 7. SCRIPT DE AUTO-START E SELF-HEAL

**Arquivos:**  
- `C:\Users\socah\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\hermes-start.cmd`
- `C:\Users\socah\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\telegram-self-heal.cmd`

**Função:**  
- Resetar `gateway_state.json` antes de subir o Hermes
- Monitorar se o processo `hermes.exe` está rodando
- Reiniciar automaticamente se cair

**Problema:**  
- Script pode estar apontando para local errado (verificar caminhos)
- Logs em `%USERPROFILE%\telegram-self-heal.log`

---

## 8. PIPELINE DE MERCADO (ROTINA YODA)

**Fontes funcionando:**  
- yfinance: Bovespa, Dólar, Ouro, Petróleo
- Browser: UOL, Folha, O Globo, G1 para notícias

**Bloqueado:**  
- DXY (USD Index) — Yahoo bloqueou por rate limit
- API de notícias em tempo real — sites bloqueiam CAPTCHA

**Soluções alternativas:**  
1. Usar Alpha Vantage API (free tier: 25 req/dia) para DXY
2. Usar Banco Central (BCB) API para dólar oficial: https://api.bcb.gov.br
3. Usar Investing.com via scraping (bloqueio de bot)
4. Cachear último DXY e atualizar a cada 1h

---

## 9. O QUE FALTA FAZER (PRIORIZADO)

### CRÍTICO (bloqueia automação SEI)
1. Resolver TLS handshake ou conseguir desbloqueio de rede
2. Implementar OCR que funcione no captcha 180x50 do SEI
3. Salvar/reativar cookies de sessão para evitar re-login manual

### ALTO (impacta qualidade da rotina)
4. Fonte alternativa para DXY (BCB API ou Alpha Vantage)
5. Resolver divergência git no JFN (rebase + push)
6. Testar rotina BOM DIA ao vivo (aguardando 7:00 ou execução manual)

### MÉDIO (melhora operacional)
7. Instalar plugins restantes do Hermes (google-meet, achievements, etc.)
8. Documentar API do BCB no repo Yoda/Hermes
9. Adicionar notícias setoriais (energia, Óleo&Gás, infraestrutura)

### BAIXO (nice to have)
10. Integração Composio Connect (1.000+ apps via OAuth)
11. Self-evolution do Hermes (auto-otimização de skills)
12. Dashboard Kanban para multi-agent tracking

---

## 10. COMANDOS ÚTEIS PARA RETOMADA

```bash
# Ver status do Hermes
hermes status

# Resetar gateway (quando travar)
del %USERPROFILE%\.hermes\gateway_state.json
hermes gateway run

# Testar yfinance
python -c "import yfinance as yf; print(yf.Ticker('^BVSP').history(period='1d'))"

# Testar captcha solver
cd C:\JFN\jfn
python compliance_agent/captcha_solver.py data/tmp/sei_captchas/captcha_thr180.png

# Resolver divergência JFN
cd C:\JFN\jfn
git fetch origin claude/rj-finance-agent-BYlhJ
git rebase origin/claude/rj-finance-agent-BYlhJ
git push origin claude/rj-finance-agent-BYlhJ

# Clonar este repo no Claude Code
git clone https://github.com/jfelippebethlem-tech/Yoda-Telegram-e-Agente-Hermes.git
```

---

## 11. ARQUIVOS DE REFERÊNCIA

- `C:\Hermes_Yoda\CHECKLIST.md` — estado atual do projeto
- `C:\Hermes_Yoda\CLAUDE.md` — instruções para Claude Code
- `C:\Hermes_Yoda\SESSAO-COMPLETA-2026-06-03.md` — histórico detalhado
- `C:\Hermes_Yoda\templates\bom-dia-template.md` — formato oficial da rotina
- `C:\JFN\jfn\README-AGENTES.md` — mapa de agentes
- `C:\Users\socah\Desktop\IAs boas pra codigo.txt` — lista de providers
- `C:\Users\socah\Desktop\hermes-plugins-passo-a-passo.txt` — guia de plugins

---

## 12. CONTATOS E CREDENCIAIS

- **GitHub user:** jfelippebethlem-tech
- **Telegram chat_id:** 45338178
- **Hermes config:** C:\Users\socah\.hermes\config.yaml
- **JFN path:** C:\JFN\jfn
- **Yoda path:** C:\Hermes_Yoda
- **Branch JFN:** claude/rj-finance-agent-BYlhJ
