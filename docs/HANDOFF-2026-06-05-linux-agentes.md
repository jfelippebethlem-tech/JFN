# HANDOFF — Todos os agentes rodando no Linux (VM GCP) — 2026-06-05

> **Autor:** Claude Code na **VM GCP** (`~/JFN`, Ubuntu 24.04).
> **Branch:** `claude/rj-finance-agent-BYlhJ` (canônica).
> **Objetivo desta sessão:** fazer **todos os agentes do JFN funcionarem no Linux**
> sem quebrar Windows nem GitHub Actions ("sem apagar os outros ambientes").

---

## 1. O que foi feito

### 1.1 Ambiente Linux montado (não versionado — fica só na VM)
- **venv** em `~/JFN/.venv` (gitignored).
- `pip install -r requirements.txt` → core (fastapi, uvicorn, playwright, pandas…).
- `pip install -r requirements-sei.txt` → **extras OCR/CDP** (pytesseract, opencv-headless,
  websocket-client, selenium, webdriver-manager, easyocr+torch CPU). Ver arquivo novo `requirements-sei.txt`.
- **Playwright Chromium** baixado + libs de sistema.
- **apt (sistema):** `tesseract-ocr tesseract-ocr-por libgl1 libglib2.0-0 libnss3 libnspr4`.
- Modelos do **easyocr** pré-cacheados (`~/.cache/easyocr`).

### 1.2 Portabilidade — caminhos `C:\` hardcoded que o handoff anterior não pegou
Todos tornados OS-aware (Windows fica **idêntico**; Linux usa `<repo>/data`, override por `JFN_DATA_DIR`):
| Arquivo | Antes → Depois |
|---|---|
| `compliance_agent/sei_driver.py` | `SAVE_DIR` Windows → `JFN_DATA_DIR`/data/tmp/sei_captchas; perfil Chrome via `CHROME_USER_DATA_DIR` |
| `compliance_agent/auditoria/sei_auditor.py` | `PROFILE/CHROME/ENV/CACHE` → env-overridable; Windows ainda lê `.env` do Hermes se existir |
| `compliance_agent/auditoria/tfe_fornecedor.py` | `cache` Windows → `<repo>/data/sei_cache` |
| `compliance_agent/auditoria/siafe_contratos.py` | dump Windows → `<repo>/data/sei_cache` |
| `reports/build_relatorio_geral.py` | `db_path`/`out_path` Windows → relativo ao repo |

### 1.3 Bug real corrigido (afetava qualquer SO)
- `compliance_agent/llm/hermes_agent.py:64` — docstring quebrado deixava prosa solta com
  travessão `—` (U+2014) como código → **SyntaxError**. Unificado num único docstring.

### 1.4 Novos arquivos
- `requirements-sei.txt` — extras opcionais documentados.
- `start_linux.sh` — launcher Linux (usa venv, seta `JFN_DATA_DIR`, sobe `server.py`).
  `./start_linux.sh --setup` reinstala tudo do zero.

---

## 2. Validação (resultado real desta sessão)
- **69 módulos** do `compliance_agent` + `siafe_agent` importam OK.
- **0 erros de caminho `C:\`** na varredura de código ativo.
- Os 6 agentes pesados (captcha_solver, sei_driver, sei_sei_direct, auditoria/*CDP) importam OK
  com os extras. O único "erro" restante do `sei_sei_direct` é `ECONNREFUSED 9222` — é só a
  ausência de um Chrome CDP vivo (pré-requisito de runtime, igual no Windows), não dependência.
- **`server.py` sobe** em `127.0.0.1:8000`: `GET /` → 200 (UI 11.9KB), `GET /api/hermes/estado`
  → 200 `{"llm_ok":true,...}`. Todas as rotas FastAPI (Hermes auditor 24h, compliance, túnel) registradas.

## 3. Como rodar no Linux
```bash
cd ~/JFN
./start_linux.sh                 # sobe o agente em 127.0.0.1:8000
# primeira vez numa VM nova:
./start_linux.sh --setup         # cria venv + instala core + extras + chromium
```
Coleta SIAFE (precisa de IP gov / Chrome CDP) continua via **GitHub Actions** ou Chrome na porta 9222.

## 4. Não tocado de propósito
- `_PROTEGIDO/` e `_SANDBOX/` (CONSTITUICAO.md) — incluindo `criar_vm.py` e os scripts de
  vídeo cancelados (`compose_video_audio.py`, `generate_*`, `run_all.py`) na raiz.
- `iniciar.sh` (Windows-oriented) — mantido; `start_linux.sh` é o caminho Linux.
- 🔐 **PAT do GitHub** em texto puro no `.git/config` — **não mexido** (a pedido do Mestre Jorge). Rotacionar quando autorizado.
