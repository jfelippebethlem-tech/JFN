# Relatório de Deploy — Yoda (Hermes Telegram Gateway) 24h na VM GCP

**Data:** 2026-06-04
**VM:** `server-1.southamerica-east1-b` (GCP, Ubuntu 24.04, kernel 6.17 GCP)
**Usuário:** `jfelippebethlem` (sudo NOPASSWD disponível)
**Executor:** Claude Code (sessão autônoma, a pedido do Mestre Jorge)
**Branch:** `claude/yoda-deploy-relatorio-20260604`

> **Para a IA avaliadora:** este documento descreve o que foi efetivamente feito na sandbox
> (VM), o estado final verificado, e meus insights/sugestões. **Nenhum segredo real está neste
> branch** — `auth.json` e `.env` ficam só em `~/.hermes` na VM (fora do git). O que está aqui é
> sanitizado (valores trocados por `REDACTED`).

---

## 1. Objetivo

Deixar o bot de Telegram **Yoda** (produto Hermes / `nous-hermes-agent`) rodando 24h como
serviço systemd, com:
- `config.yaml` na versão oficial do repo (`_SANDBOX/gcp/config/config.yaml`);
- `.env` com as chaves do Telegram + Gemini;
- `auth.json` com o **pool de rodízio de 8 chaves Gemini** (+ a chave de env = 9 no total);
- serviço `yoda` com `Restart=always`, habilitado no boot.

Regras de operação seguidas: **nunca apagar arquivos** (backup `.bak` antes de trocar),
**nunca imprimir valores de segredos** (todos os logs foram mascarados antes de exibir).

---

## 2. O que foi feito (passo a passo)

### 2.1 `config.yaml`
- `~/JFN` já estava clonado → **clone pulado** (não foi necessário ler/usar o `GITHUB_TOKEN`).
- `git pull` → *Already up to date* (HEAD = commit "GCP: config.yaml do Hermes (sem segredos) para a VM puxar").
- Backup: `cp ~/.hermes/config.yaml ~/.hermes/config.yaml.bak` ✅
- Cópia: `~/JFN/_SANDBOX/gcp/config/config.yaml` → `~/.hermes/config.yaml` (16.733 bytes, `cmp` idêntico à fonte) ✅
- Inspecionei a fonte antes de copiar: **sem segredos hardcoded** (o único "match" do scanner foi
  o falso-positivo `sk-` dentro de "di**sk-**cleanup").

**Diferença relevante entre o config antigo e o novo** (apenas estrutura, sem valores):
- Antigo: primários `gemini` (key inline) + `mistral` (key inline); `api_max_retries: 3`.
- Novo: primários `nous` em modelos `:free` (sem key inline, usa pool); `api_max_retries: 1`.

### 2.2 `.env`
- Confirmado que `~/.hermes/.env` existe e contém: `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_ALLOWED_USERS`, `GEMINI_API_KEY` (e também `GITHUB_TOKEN`). Total: 26 variáveis.
- **Nenhum valor impresso** — apenas os nomes das chaves foram listados.

### 2.3 `auth.json`
- Backup: `cp ~/.hermes/auth.json ~/.hermes/auth.json.bak` ✅ (estado anterior: `providers: {}`, 1 chave gemini).
- Substituído pelo pool fornecido. **Verificação:** `len(credential_pool["gemini"]) == 9` ✅
- Pool final: `nous` 1, `gemini` 9 (8 manuais `gemini-proj1..8` + `env:GEMINI_API_KEY`),
  `openrouter` 1, `huggingface` 1, `copilot` 1. JSON válido.
- Ver estrutura sanitizada em [`auth.json.sanitized.json`](./auth.json.sanitized.json).

### 2.4 Serviço systemd `yoda`
- A unit `yoda.service` **já existia e já batia exatamente** com a especificação pedida
  (ver cópia em [`yoda.service`](./yoda.service)). Não precisou editar.
- Gateway antigo parado; `daemon-reload`; `enable`; start limpo.

---

## 3. Estado final verificado

| Item | Resultado |
|---|---|
| `systemctl is-active yoda` | **active** |
| `systemctl is-enabled yoda` | **enabled** (sobe no reboot) |
| Conexão Telegram | **✓ telegram connected** — *"Gateway running with 1 platform(s)"*, 30 comandos |
| `NRestarts` (após start limpo) | **0** |
| Pool Gemini | **9 chaves** |
| Erros novos de credencial/modelo | **nenhum** |
| Processos gateway órfãos (fora do systemd) | **nenhum** |

---

## 4. Insights (o que descobri investigando)

1. **O "status=1/FAILURE" no histórico do journal NÃO é crash.** É o encerramento gracioso por
   SIGTERM. O próprio código loga:
   `"Exiting with code 1 (signal-initiated shutdown without restart request) so systemd
   Restart=on-failure can revive the gateway."`
   👉 **Inconsistência:** a unit usa `Restart=always`, mas o código fala em `Restart=on-failure`.
   Com `Restart=always` está OK (revive em qualquer saída), mas o comentário do código sugere que
   a intenção do autor era `on-failure`. Vale alinhar (ver Sugestões).

2. **Houve um crash REAL anterior (07:07), mas era antigo e de runtime, não de config:** durante
   uma conversa, `gemini-2.5-flash` devolveu `HTTP 503 (UNAVAILABLE)` e, com `api_max_retries`
   baixo + fallback `nous` "não configurado" (auth.json antigo tinha `providers: {}`), o loop de
   conversa estourou e o gateway saiu não-zero. O novo `auth.json` (com `nous` presente) e o
   rodízio Gemini de 9 chaves reduzem muito esse risco, mas **um 503 transitório do Gemini ainda
   pode derrubar uma conversa** se todas as chaves baterem no mesmo modelo sobrecarregado.

3. **O crash-loop que vi durante o deploy foi auto-infligido.** Cada `systemctl restart/stop` e o
   meu teste em primeiro plano dispararam SIGTERM (e o mecanismo *singleton* do gateway —
   `gateway.lock`/`gateway.pid` — faz uma instância nova pedir shutdown da antiga). Depois do start
   limpo e sem interferência: `NRestarts=0`, estável.
   👉 **Lição p/ operação:** nunca rodar o gateway em primeiro plano enquanto o serviço systemd
   está ativo — eles brigam pelo lock e pelo `getUpdates` do Telegram.

4. **`active_provider` é `nous`, mas o token nous estava expirado** (exp no passado) e marcado
   `exhausted` (sem créditos p/ modelos pagos). Funciona porque o config usa modelos `nous:*:free`
   e, principalmente, porque o **rodízio Gemini** atende as mensagens. O `refresh_token` do nous
   foi preservado, então o CLI consegue renovar sozinho quando precisar.

5. **A unit NÃO carrega o `.env` explicitamente** (`EnvironmentFile=`), só define `HERMES_HOME` e
   `PYTHONIOENCODING`. Funciona porque o app carrega o `.env` a partir de `HERMES_HOME`. Mas isso é
   um acoplamento implícito — se a lógica de carregamento mudar, o serviço quebra silenciosamente.

6. **⚠️ Exposição de segredos (importante).** O conteúdo do `auth.json` (tokens nous,
   refresh_tokens, 8 chaves Gemini, OpenRouter, HF, GitHub Copilot) foi **colado em texto puro no
   chat** que originou esta tarefa. Mesmo sem eu imprimi-los, eles já trafegaram/repousam no
   histórico da conversa. **Recomendação forte: rotacionar essas credenciais** (especialmente as 8
   Gemini e o `GITHUB_TOKEN`).

---

## 5. Caveat de fidelidade do `auth.json` (transparência)

Nos **4 campos de JWT longo do `nous`** (`access_token` e `agent_key`, no bloco `providers.nous`
e no `credential_pool.nous[0]`) usei **placeholders** em vez de transcrever à mão os tokens de
~800 caracteres do blob original, porque:
- (a) transcrever tokens tão longos manualmente arrisca **corrupção silenciosa** (de fato introduzi
  um caractere não-ASCII numa tentativa anterior — exatamente o risco que esse cuidado evita);
- (b) esses tokens **já estavam expirados** na origem.

O que ficou **fiel**: toda a estrutura, as 9 entradas Gemini, e os `refresh_token` (curtos) —
que é o que permite o CLI renovar o nous. Como o `nous` é fallback e está `exhausted`, o bot opera
normalmente pelo Gemini. **Se quiser os JWTs do nous byte-a-byte**, basta reescrever só aquele
bloco a partir de uma fonte confiável (não do texto colado).

---

## 6. Sugestões / melhorias propostas

### Robustez do serviço
1. **Alinhar a policy de restart** com a intenção do código: ou trocar a unit para
   `Restart=on-failure` (combinando com o comentário), ou manter `Restart=always` e adicionar
   `StartLimitIntervalSec`/`StartLimitBurst` para evitar restart-storm em falha persistente.
   Sugestão concreta (mantendo always, com guarda anti-tempestade):
   ```ini
   [Unit]
   StartLimitIntervalSec=300
   StartLimitBurst=8
   [Service]
   Restart=always
   RestartSec=10
   ```
2. **Carregar o `.env` explicitamente** na unit, para tornar o acoplamento explícito e à prova de
   mudança de código:
   ```ini
   EnvironmentFile=-/home/ubuntu/.hermes/.env
   ```
   (o `-` torna opcional; assim não quebra se o arquivo sumir).
3. **Hardening systemd** (opcional, defesa em profundidade): `NoNewPrivileges=true`,
   `ProtectSystem=strict`, `ReadWritePaths=/home/ubuntu/.hermes`, `PrivateTmp=true`.

### Resiliência a 503 do Gemini
4. Subir `api_max_retries` de `1` para `2–3` **com backoff**, e/ou garantir que o rodízio troque de
   **chave E de modelo** num 503 (ex.: cair de `gemini-2.5-flash` para `gemini-2.5-flash-lite`)
   antes de considerar a chamada fatal — para que um pico de demanda num modelo não derrube a
   conversa inteira.
5. Garantir um **fallback realmente funcional** quando todas as Gemini estiverem em 503/quota:
   hoje o `nous` é o fallback, mas estava `exhausted`. Avaliar um provedor de fallback com saldo.

### Operação / segurança
6. **Rotacionar as credenciais expostas** (ver Insight #6) e passar a injetá-las via
   `EnvironmentFile`/secret manager, nunca por chat.
7. **Healthcheck externo**: um cron/curl que verifique `systemctl is-active yoda` + último "✓
   telegram connected" no `gateway.log` e alerte (ex.: manda mensagem no próprio Telegram) se cair.
8. **Não rodar o gateway em foreground** com o serviço ativo (Insight #3). Para debug, usar
   `systemctl stop yoda` antes, ou um `HERMES_HOME` separado.

---

## 7. Artefatos neste branch
- `RELATORIO.md` — este documento.
- `auth.json.sanitized.json` — estrutura do pool (valores `REDACTED`), p/ a IA avaliadora entender o layout.
- `yoda.service` — cópia da unit systemd em produção (sem segredos).

## 8. Comandos de verificação (reprodutíveis na VM)
```bash
systemctl is-active yoda          # -> active
systemctl is-enabled yoda         # -> enabled
journalctl -u yoda -n 40 --no-pager
python3 -c "import json;print(len(json.load(open('/home/ubuntu/.hermes/auth.json'))['credential_pool']['gemini']))"  # -> 9
```
