# MUDANÇAS — detalhe, justificativa, aplicação e rollback

Convenção: **APLICADO** = já vivo na VM. **PROPOSTO** = só neste pacote.
Todos os backups na VM seguem o padrão `<arquivo>.AAAAMMDD-HHMMSS.bak`.

---

## A) Serviço systemd `yoda` — **APLICADO**

**O quê:** criado `/etc/systemd/system/yoda.service` rodando o gateway do Hermes 24h.
- `User=jfelippebethlem`, `WorkingDirectory=~/hermes-agent`
- `ExecStart=/home/jfelippebethlem/hermes-agent/venv/bin/python -m hermes_cli.main gateway run`
- `Environment=HERMES_HOME=/home/jfelippebethlem/.hermes`, `PYTHONIOENCODING=utf-8`
- `Restart=always`, `RestartSec=10`

**Por quê:** objetivo da tarefa — Yoda no ar 24h, sobe no boot e se recupera de queda.

**Verificação:** `systemctl is-active yoda` → `active`; Telegram conecta (`✓ telegram connected`).

**Rollback:** `sudo systemctl disable --now yoda && sudo rm /etc/systemd/system/yoda.service && sudo systemctl daemon-reload`

---

## B) `TimeoutStopSec` 30 → 210 no unit — **APLICADO**

**O quê:** aumentei o timeout de parada do serviço.

**Por quê:** o próprio gateway avisou no log:
`Stale systemd unit detected: yoda.service has TimeoutStopSec=30s but drain_timeout=180s
(expected >=210s). systemd may SIGKILL the gateway mid-drain.` Ou seja, com 30s o systemd
poderia matar o bot no meio do "drain" (encerramento limpo de sessões) num stop/restart.

**Rollback:** backup do unit salvo em `/etc/systemd/system/yoda.service.*.bak`.

---

## C) Persona "Mestre Yoda" — **APLICADO**

**O quê:** reescrevi `~/.hermes/SOUL.md` (o prompt-núcleo de identidade). Antes:
"You are Hermes Agent... created by Nous Research". Agora: o bot se reconhece como
**Mestre Yoda**, trata o usuário como Mestre Jorge, mantém competência técnica e usa o
tom Yoda com moderação (sem prejudicar clareza). Conteúdo exato em `soul/SOUL.md.ATUAL-LIVE`.

**Por quê:** pedido explícito do Mestre Jorge ("ele tem que se reconhecer como Mestre Yoda").

**Rollback:** backup em `~/.hermes/SOUL.md.*.bak`.

---

## D) Fallback + retries + pool de credenciais — **PROPOSTO** (NÃO aplicado)

Esta é a correção do bug **"para de escrever no meio"**. Ver `config/DIFF.patch`.

### Causa-raiz (com evidência)
O modelo primário `gemini-2.5-flash` retorna **HTTP 503 (sobrecarga)** de forma
intermitente. Teste direto na API agora: **1 de 3** chamadas `generateContent` deu 503.
Quando o 503 batia no meio do streaming:
- o fallback configurado eram **3 modelos Nous**, mas **Nous não está autenticado** na VM →
  log: `Fallback to nous failed: provider not configured` / `no Nous authentication found`;
- e `api_max_retries: 1` → desistia após 1 tentativa.

Resultado: o trecho já transmitido aparecia e o resto cortava. Exatamente o sintoma
("*No contexto da sua"). Evidência no log do gateway:
```
ERROR agent.conversation_loop: API call failed after 1 retries. HTTP 503 (UNAVAILABLE)
      | provider=gemini model=gemini-2.5-flash
WARNING agent.chat_completion_helpers: Fallback to nous failed: provider not configured
```

### As 3 mudanças
1. **`fallback_providers`**: removidos os 3 entries Nous (mortos); adicionada cadeia que
   responde de verdade — Gemini descendo em demanda e Mistral como rede cross-provider:
   `gemini-2.5-flash-lite → gemini-2.0-flash → gemini-2.0-flash-lite → mistral-large-latest → mistral-small-latest`.
   Racional: modelos de famílias diferentes ficam em **pools de capacidade diferentes**, então
   descer 2.5→2.0→Mistral realmente escapa da sobrecarga. Mistral é infra fora do Google
   (sobrevive a um apagão geral do Gemini). Chaves via `key_env` (`GEMINI_API_KEY`/`MISTRAL_API_KEY`),
   ambas validadas (HTTP 200) nesta sessão.
2. **`api_max_retries`: 1 → 3**: como o 503 é intermitente (≈1/3 passa), 3 tentativas
   reduzem muito o corte antes mesmo de trocar de modelo.
3. **`credential_pool_strategies: { gemini: round_robin, mistral: fill_first }`**: liga a
   rotação de chaves. Com 1 chave Gemini é **no-op seguro**; passa a alternar assim que
   houver mais chaves (ver item E).

### Risco
Baixo. YAML validado (`yaml.safe_load` OK). Esquema de `fallback_providers`
(`provider/model/base_url/key_env`) confere com o parser em
`hermes-agent/gateway/run.py:_try_resolve_fallback_provider` e
`agent/chat_completion_helpers.py` (resolução por `key_env`/`api_key`). `round_robin` é
estratégia válida em `agent/credential_pool.py`.

### Aplicar
```bash
cp ~/.hermes/config.yaml ~/.hermes/config.yaml.$(date +%Y%m%d-%H%M%S).bak
cp ~/JFN/_SANDBOX/gcp/propostas/2026-06-04-yoda-tuning/config/config.yaml.PROPOSTO ~/.hermes/config.yaml
~/hermes-agent/venv/bin/python -c "import yaml;yaml.safe_load(open('$HOME/.hermes/config.yaml'));print('YAML OK')"
sudo systemctl restart yoda && sleep 10 && systemctl is-active yoda
```
### Rollback
```bash
cp ~/.hermes/config.yaml.<timestamp>.bak ~/.hermes/config.yaml && sudo systemctl restart yoda
```

---

## E) Múltiplas chaves Gemini (pool) — **PROPOSTO** (instruções)

**Importante:** na varredura de hoje há **apenas 1** chave Gemini (`GEMINI_API_KEY` em
`~/.hermes/.env`). Não existe pool montado, nem suporte a `GEMINI_API_KEY_2` automático
nem a chaves separadas por vírgula numa só variável. O caminho **suportado** para várias
chaves é o pool em `~/.hermes/auth.json`, alimentado pelo CLI:

```bash
# Adicione cada chave extra ao pool do provider gemini (não imprime a chave):
~/hermes-agent/venv/bin/python -m hermes_cli.main auth add gemini --type api-key --label chave-2
~/hermes-agent/venv/bin/python -m hermes_cli.main auth add gemini --type api-key --label chave-3
# Conferir:
~/hermes-agent/venv/bin/python -m hermes_cli.main auth list
# Limpar status de exausta (após 429) se precisar:
~/hermes-agent/venv/bin/python -m hermes_cli.main auth reset gemini
```
Com o item D (`credential_pool_strategies.gemini: round_robin`) ativo, o gateway passa a
**alternar entre as chaves** a cada chamada e a **pular a que estourou cota (429)** — o que
multiplica o teto de requisições grátis do Gemini.

**Ação para o Mestre Jorge / revisor:** me passar as chaves extras (ou rodar os comandos
acima) para popular o pool.

### Estratégia de modelos recomendada (Gemini é forte e tem grátis para tudo)
A VM enxerga 30 modelos Gemini (família 3.x e 2.x). Sugestão de uso por tarefa:

| Tarefa | Modelo sugerido | Observação |
|---|---|---|
| Chat geral (primário) | `gemini-2.5-flash` | Estável, 1M contexto, bom equilíbrio (atual). |
| Raciocínio pesado / compliance | `gemini-3-pro-preview` ou `gemini-2.5-pro` | Mais caro/cota menor; usar sob demanda. |
| Respostas rápidas / barato | `gemini-2.5-flash-lite`, `gemini-2.0-flash-lite` | Alta disponibilidade — bons como fallback. |
| Visão / OCR (captcha SEI, PDFs DOERJ) | `gemini-2.5-flash` (multimodal) | Via `auxiliary.vision`. |
| Rede de segurança | `mistral-large-latest` | Provider fora do Google. |

> Opção "máxima qualidade" (se quiser, troca de primário): `model.default: gemini-3-pro-preview`
> com a mesma cadeia de fallback descendo até os flash/lite e Mistral. Fica a critério da revisão
> (cota grátis do `-pro` é menor; por isso o default proposto mantém `2.5-flash`).

---

## F) Ponte Desktop ↔ Claude Code — **PROPOSTO**
Ver documento dedicado `ponte-desktop-claude-code.md`.
