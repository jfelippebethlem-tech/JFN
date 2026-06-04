# Parecer da revisão (IA avaliadora) — 2026-06-04

Revisão crítica das branches feitas pelas IAs da VM
(`claude/proposta-yoda-tuning-20260604` e `claude/yoda-deploy-relatorio-20260604`).

## Veredito: CONSTRUTIVO ✅ — incorporado.

### O que avaliei
- **Deploy real e funcionando**: Yoda `active`+`enabled`, Telegram conectado, pool com 9 Gemini,
  0 erros de credencial. Verificável pelos comandos do RELATORIO.
- **Disciplina de sandbox**: tudo em `_SANDBOX/gcp/propostas/` (não tocaram no protegido),
  com snapshots `ATUAL-LIVE` do que está na VM. Seguiram a CONSTITUIÇÃO.
- **Sanitização**: `auth.json.sanitized.json` sem segredo real (conferido: 0 chaves Gemini/GitHub/HF).
- **Diagnóstico do bug "corta no meio"**: sólido e com evidência de log — `gemini-2.5-flash` dá
  HTTP 503 intermitente (~1/3), fallback Nous estava morto (não autenticado), `api_max_retries:1`.

### O que INCORPOREI no repo (config oficial que a VM puxa)
`_SANDBOX/gcp/config/config.yaml`:
- `fallback_providers`: removidos os 3 Nous `:free` mortos → cadeia que responde de fato:
  `gemini-2.5-flash-lite → 2.0-flash → 2.0-flash-lite → mistral-large → mistral-small`.
- `api_max_retries`: 1 → 3 (503 é intermitente).
- `credential_pool_strategies`: `gemini: round_robin` (gira as 8 chaves) + `mistral: fill_first`.

`bootstrap-vm.sh` e `bootstrap-vm-full.sh` (unit `yoda.service`):
- `TimeoutStopSec=210` + `KillSignal=SIGTERM` (não mata no meio do drain de 180s).
- `StartLimitIntervalSec=300` + `StartLimitBurst=8` (anti restart-storm).
- `EnvironmentFile=-$HERMES_HOME/.env` (carrega o .env explicitamente).

### Ajuste fino vs proposta
- Mantive `Restart=always` (a unit já estava assim e funciona). A guarda `StartLimit*` resolve o
  risco de tempestade que a proposta levantou.
- O `key_env: GEMINI_API_KEY` nos fallbacks gemini usa 1 chave; a rotação das 8 acontece no
  provider primário via `round_robin`. Aceitável — a rede de fallback existe pra 503, não pra cota.

## Pendências pra "TUDO rodar liso" na VM (próxima rodada)
O deploy atual sobe só o **Yoda (Telegram)**. Pras outras funções, falta rodar o
`bootstrap-vm-full.sh` (ou os passos dele), que instala as ferramentas:
- **Chromium + chromium-driver + Xvfb** → automação web do **SEI/SIAFE/DOERJ** (headless).
- **Deps Python do JFN** (`oci`, `playwright`, `beautifulsoup4`, `lxml`, `websocket-client`) + `playwright install chromium`.
- **Node 22 + Claude Code** (já presente) → comando **/claude** no Telegram (ponte `claude_bridge.py`).
- **Massare**: usa dados públicos (BCB, sem chave) — só precisa do `requests` (já vem).

## ⚠️ Segurança (recomendação forte das IAs da VM — endosso)
As chaves trafegaram em texto no chat. **Rotacionar**: as **8 chaves Gemini** e o **GITHUB_TOKEN**.
Depois, manter sempre via `.env`/`auth.json` (nunca por chat). Decisão do Mestre Jorge.
