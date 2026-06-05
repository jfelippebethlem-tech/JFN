# Log de Desenvolvimento — Agente SIAFE OBs

**Projeto:** JFN Compliance — Coleta de Ordens Bancárias no SIAFE-Rio 2  
**Branch:** `claude/rj-finance-agent-BYlhJ`  
**Data:** 2026-06-05  

---

## Objetivo Original

Coletar automaticamente todas as Ordens Bancárias (OBs) do SIAFE-Rio 2 para a empresa **MGS CLEAN SOLUCOES E SERVICOS LTDA** (CNPJ: 19.088.605/0001-04), anos 2023–2026, e persistir em `data/sei_cache/mgsclean_obs_todas.json` + `data/compliance.db`.

## Objetivo Expandido (meta do usuário)

Generalizar para **todas as empresas** com seus CNPJs e todos os órgãos listados no SIAFE — não apenas MGS CLEAN.

---

## Arquitetura

### Acesso ao SIAFE
- **URL:** `https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp`
- **Sistema:** Oracle ADF (Application Development Framework) — WAF bloqueia IPs não-governamentais
- **Solução:** GitHub Actions runners (Azure IPs) conseguem acessar
- **Autenticação:** CPF + senha + potencial MFA/popup de sessão dupla

### Exercícios (Fiscal Years)
```python
EXERCICIOS = {2027: "0", 2026: "1", 2025: "2", 2024: "3", 2023: "4"}
```

### Arquivos Principais
| Arquivo | Papel |
|---------|-------|
| `_SANDBOX/coletar_obs_agora.py` | Script principal de coleta (Playwright) |
| `.github/workflows/coletar-obs-siafe.yml` | GitHub Actions workflow |
| `data/empresas_target.json` | Lista de empresas alvo |
| `data/compliance.db` | SQLite com OBs coletadas |

---

## Histórico de Runs e Erros

### Run 20 — Falha inicial de instalação
- **SHA:** `98be08db`
- **Erro:** `playwright install chromium` rodava ANTES de `pip install -r requirements.txt`
- **Fix:** Moveu `playwright install chromium` para DEPOIS de `pip install -r requirements.txt`

### Run 21 — Credenciais não configuradas
- **Erro:** `[ERRO] Credenciais não encontradas!`
- **Causa:** Workflow tinha `required: true` e usuário não preencheu os campos
- **Fix:** Usuário configurou os secrets `SIAFE_USER` e `SIAFE_PASS` no GitHub

### Run 22 — Popup: login button clicado 5x
- **SHA:** `51d99cf`
- **Erro no log:** `→ Popup fechado: [body:ok[loginBox:btnConfirmar]]` (×5)
- **Causa:** `_dismiss_popups(allow_confirm=True)` não excluía o botão de submit do formulário de login
- **Fix:** `skip_ids = ['btnconfirmar']` sempre, independente de `allow_confirm`

### Run 22 — `keyboard.press("Return")` inválido
- **Erro:** `playwright._impl._errors.Error: Keyboard.press: Unknown key: "Return"`
- **Causa:** Playwright usa `"Enter"`, não `"Return"` (que é o nome do tkinter)
- **Fix:** `replace_all=True` em todo o arquivo para trocar `"Return"` → `"Enter"`

### Run 22 — Popup "outra janela" não detectado
- **Popup:** "O Sistema está aberto em outra janela. Deseja acessá-lo nesta janela?" + botão "Sim"
- **Causa:** O loop de polling tinha filtro `!el.closest('[id*="loginBox"]')` que excluía o botão "Sim" (que estava dentro da estrutura DOM do loginBox)
- **Screenshot confirmada pelo usuário (IMG_1964.png)**
- **Fix:** Removeu o filtro `loginBox`, mantendo apenas a exclusão por `id='btnconfirmar'`

### Runs 24 e 25 — Push sem credenciais
- **Causa:** Trigger foi `push` (automático pelo commit), não `workflow_dispatch`
- **Problema adicional:** O arquivo YAML com heredoc (`cat > .env << EOF`) tinha linhas com indentação zero que quebravam o parser YAML do GitHub Actions para validação de `workflow_dispatch`
- **Fix:** Substituiu heredoc por `printf '...\n' > .env` (todas as linhas com indentação correta)
- **Evidência:** GitHub mostrava nome do workflow como o path do arquivo (`.github/workflows/...`) em vez do campo `name:` — sinal clássico de falha de parsing YAML

### Run 26 — `SECRET_USER` vazio
- **Erro:** `[ERRO] Credenciais não encontradas!`
- **Log:** `SECRET_USER: ` (vazio), `SECRET_PASS: ***` (configurado)
- **Causa:** Secret `SIAFE_USER` não estava definido no GitHub (ou vazio)
- **Status:** Pendente — usuário precisa re-configurar o secret `SIAFE_USER`

---

## Fixes Implementados

### `_SANDBOX/coletar_obs_agora.py`

1. **`sys.stdout.reconfigure(line_buffering=True)`** no topo — evita buffer de stdout quando piped no CI
2. **`_load_empresas()`** — carrega lista de empresas de `data/empresas_target.json` ou `$SIAFE_CNPJS`
3. **`_dismiss_popups`:** `skip_ids = ['btnconfirmar']` sempre (impede clicar o botão de login)
4. **Popup loop:** Removeu `!el.closest('[id*="loginBox"]')` para detectar "Sim" pós-login
5. **`keyboard.press("Enter")`** em vez de `"Return"` (fix global com `replace_all`)
6. **`_filtrar_por_cnpj(pg, cnpj=None, cnpj_fmt=None)`** — parametrizado por empresa
7. **`_coletar_exercicio(browser, ano, empresa=None)`** — recebe dict com dados da empresa
8. **`main()`** — loop por empresa × ano, salva `obs_{cnpj}_{ano}.json` individuais
9. **`_salvar_no_db`** — categoria dinâmica (`ob.get("categoria", ...)`)

### `.github/workflows/coletar-obs-siafe.yml`

1. **Removeu heredoc** → usa `printf` (fix YAML parser para `workflow_dispatch`)
2. **Inputs opcionais** (`required: false`) com fallback para secrets
3. **Novo input `cnpjs`** para especificar empresas alvo
4. **`PYTHONUNBUFFERED: '1'`** para logs em tempo real
5. **Timeout 120min** (job) / 90min (coleta)
6. **`git pull --rebase`** antes do push para evitar rejeição

### `data/empresas_target.json` (novo)
```json
[{"cnpj": "19088605000104", "cnpj_fmt": "19.088.605/0001-04", "nome": "MGS CLEAN SOLUCOES E SERVICOS LTDA", "categoria": "mgs_clean_real"}]
```

---

## Credenciais e Segurança

- **`SIAFE_USER`** e **`SIAFE_PASS`** SOMENTE via GitHub Secrets ou `~/.hermes/.env` local
- **`.env` está no `.gitignore`** — NUNCA commitar
- **`auth.json`** NUNCA versionar
- Credenciais lidas via `os.environ.get(...)` apenas

---

## MFA / Sessão dupla

O SIAFE-Rio 2 pode exibir popups após o login:
- "O Sistema está aberto em outra janela. Deseja acessá-lo nesta janela?" → clicar "Sim"
- "Deseja continuar?" → clicar OK
- Outros alertas de sessão

**Fluxo de MFA (quando necessário):**
- A IA detecta que o workflow está aguardando MFA
- Pergunta o código diretamente ao usuário no chat
- Usuário responde com o código
- A IA faz push do código para `data/sei_cache/.mfa_input` via GitHub API
- O script em execução no Actions faz polling desse arquivo e usa o código

---

## Pendências Críticas

- [ ] **Secret `SIAFE_USER` precisa ser re-configurado no GitHub** (valor atual: vazio)
- [ ] Primeira coleta bem-sucedida ainda não foi realizada
- [ ] `data/sei_cache/mgsclean_obs_todas.json` com `total_obs > 0` ainda não existe
- [ ] Dados ainda não persistidos em `data/compliance.db`
- [ ] Adicionar mais empresas ao `data/empresas_target.json`
- [ ] Descoberta dinâmica de UGs no SIAFE

---

## Próximos Passos

1. Usuário confirma que `SIAFE_USER` está configurado no GitHub
2. Disparar Run 27 via workflow_dispatch
3. Monitorar login e popup de "outra janela"
4. Se MFA solicitado, perguntar código ao usuário no chat e fazer push via API
5. Confirmar coleta com `total_obs > 0`
