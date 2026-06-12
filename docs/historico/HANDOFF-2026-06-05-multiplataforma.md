# HANDOFF — Portabilidade Multiplataforma do JFN (2026-06-05)

> **Autor:** Claude Code rodando na **VM GCP** (`~/JFN`, Linux Ubuntu 24.04).
> **Para:** a IA do **Claude Desktop** (Windows, `C:\JFN\jfn`) e o Mestre Jorge.
> **Branch:** `claude/rj-finance-agent-BYlhJ` (canônica do JFN).
> **Objetivo desta sessão:** fazer **o mesmo repositório rodar nos três alvos**
> sem editar caminhos à mão, e deixar este passo a passo para você **testar e validar**.

---

## 1. Os três alvos (um repo só)

| # | Alvo | Papel | Como o usuário usa |
|---|------|-------|--------------------|
| 1 | **Windows desktop** (`C:\JFN\jfn`) | Desenvolvimento + Chrome real (porta 9222) para SIAFE/SEI | `.bat` launchers, `JFN.bat` |
| 2 | **VM Linux GCP** (`~/JFN`) | Servidor/agente 24h + Docker | `docker compose up -d` ou `python server.py` |
| 3 | **GitHub Actions** ("rodar no git") | Coleta SIAFE de IP liberado pelo WAF (Azure) | `.github/workflows/coletar-obs-siafe.yml`, **disparável pelo celular** via app/web do GitHub |

> **Celular:** por decisão do Mestre Jorge, o acesso pelo celular fica via **Telegram**
> (bot Mestre Yoda / comandos do JFN) e via **disparo do workflow no app do GitHub**.
> Não expusemos o painel web (porta 8000) à internet nesta sessão.

---

## 2. O que foi alterado nesta sessão (e por quê)

Todas as mudanças removem **suposição de que o SO é Windows**. Nada de lógica nova de
negócio — só portabilidade. Cada item tem o "antes → depois".

### 2.1 `compliance_agent/captcha_solver.py` — caminho do Tesseract
**Problema:** linha fixa apontava para o executável do Windows; em Linux/Docker isso
aponta para um arquivo inexistente e o OCR do SEI quebra na importação do módulo.

```diff
- pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
+ def _resolver_tesseract():
+     # TESSERACT_CMD (env) > caminho padrão do Windows > 'tesseract' no PATH (Linux/Mac)
+     ...
+ _tess = _resolver_tesseract()
+ if _tess:
+     pytesseract.pytesseract.tesseract_cmd = _tess
```
**Efeito:** no Windows continua achando `C:\Program Files\Tesseract-OCR\tesseract.exe`;
em Linux usa o `tesseract` do PATH; dá para forçar com a variável `TESSERACT_CMD`.

### 2.2 `compliance_agent/collectors/sei_sei_direct.py` — pasta de saída
**Problema:** `OUT = Path("C:/JFN/jfn/data/tmp/sei_run")` — só existe no Windows.
```diff
- OUT = Path("C:/JFN/jfn/data/tmp/sei_run")
+ OUT = Path(os.environ.get("JFN_DATA_DIR", "data")) / "tmp" / "sei_run"
```
**Efeito:** grava em `data/tmp/sei_run` relativo ao repo (qualquer SO); dá para
redirecionar com `JFN_DATA_DIR`.

### 2.3 `debug_server.py` — leitura do próprio server.py
```diff
- path = Path(r"C:/JFN/jfn/server.py")
+ path = Path(__file__).resolve().parent / "server.py"
```
**Efeito:** o utilitário de debug acha o `server.py` ao lado dele em qualquer máquina.

### 2.4 `Dockerfile` — instala Tesseract + libs do OpenCV
**Problema:** a imagem instalava Chromium mas **não** o Tesseract, então o OCR do SEI
não funcionaria no container; e o `cv2` (OpenCV) precisa de `libgl1`/`libglib2.0-0`.
```diff
      fonts-liberation fonts-noto-color-emoji \
+     tesseract-ocr tesseract-ocr-por libgl1 libglib2.0-0 \
      && rm -rf /var/lib/apt/lists/*
```
**Efeito:** o container do JFN passa a ter OCR (pt) e as libs do OpenCV.

> **Não tocado de propósito:** textos de ajuda em `diagnose_siafe.py` e
> `notifications/telegram.py` que mostram ao usuário Windows como abrir o Chrome
> (`"C:\Program Files\...\chrome.exe"`). São instruções corretas para Windows, não
> operações de arquivo. O `_SANDBOX/sei_auditor.py` (Windows) também ficou intocado
> por ser experimento em `_SANDBOX/`.

---

## 3. Como TESTAR / VALIDAR (passo a passo)

### 3.1 Validar portabilidade (em qualquer SO — Windows ou Linux)
Os módulos corrigidos devem **importar sem erro** mesmo sem Tesseract instalado:

```bash
# Na raiz do repo:
python -c "import compliance_agent.captcha_solver; print('captcha_solver OK')"
python -c "import compliance_agent.collectors.sei_sei_direct" 2>&1 | head -1
python debug_server.py | head -3
```
- `captcha_solver OK` deve aparecer **sem** o erro antigo de caminho do Tesseract.
- (`sei_sei_direct` importa `easyocr`/`playwright`; se não estiverem instalados, o erro
  será de dependência — **não** de caminho `C:\`. É isso que queremos confirmar.)

### 3.2 Validar o servidor (Linux VM / Windows)
```bash
pip install -r requirements.txt
playwright install chromium
python server.py --host 0.0.0.0 --port 8000
# em outra aba:
curl -sf http://localhost:8000/api/hermes/estado && echo "  <- server OK"
```

### 3.3 Validar o Docker (Linux VM — o build agora inclui Tesseract)
```bash
docker compose build         # deve instalar tesseract-ocr sem erro
docker compose up -d
docker compose exec jfn-agent tesseract --version   # confirma OCR no container
docker compose logs -f                              # esperar "Uvicorn running on http://0.0.0.0:8000"
```

### 3.4 Validar "rodar no git" (GitHub Actions — pelo celular)
1. No app/site do GitHub → repo **JFN** → aba **Actions**.
2. Workflow **"coletar-obs-siafe"** → **Run workflow** (`workflow_dispatch`).
3. Preencher inputs (ou deixar usar os *secrets* `SIAFE_USER`/`SIAFE_PASS`).
4. Acompanhar o log pelo celular; o resultado vai para `data/sei_cache/` (e Telegram, se configurado).

### 3.5 Validar pelo celular (Telegram)
Com o agente no ar (VM) e Telegram configurado no `.env`:
`/status`, `/obs`, `/alertas`, `/sei <numero>`, `/painel`.

---

## 4. Checklist de validação para a IA do Desktop

- [ ] `git pull` na branch `claude/rj-finance-agent-BYlhJ` traz estas mudanças.
- [ ] No **Windows**, `captcha_solver` continua achando o Tesseract em `C:\Program Files\...`.
- [ ] No **Windows**, o OCR do SEI segue funcionando como antes (sem regressão).
- [ ] `python debug_server.py` roda no Windows e no Linux.
- [ ] (Opcional) `docker compose build` conclui na VM com Tesseract instalado.
- [ ] Confirmar que o disparo do workflow pelo celular coleta OBs normalmente.

Se algo regredir no Windows, **reverter é seguro**: as mudanças são pontuais e cada
arquivo tem o "antes → depois" acima.

---

## 5. Pendências / recomendações (não feitas nesta sessão)

1. **🔐 Rotacionar credenciais expostas.** O `git remote` desta VM tem um **PAT do GitHub
   embutido na URL** (`https://github_pat_...@github.com/...`, em texto puro no
   `.git/config`); e o `auth.json` (chaves Gemini + GITHUB_TOKEN) já foi colado em chat
   em sessões anteriores (ver `_SANDBOX/gcp/propostas/2026-06-04-yoda-deploy/RELATORIO.md`,
   Insight #6). **A pedido do Mestre Jorge, NÃO mexemos no token nesta sessão.**
2. **Tesseract no Windows:** se o Desktop não tiver, instalar em
   `C:\Program Files\Tesseract-OCR\` (o código acha automático) ou setar `TESSERACT_CMD`.
3. **CAPTCHA do SEI** segue sem solução de OCR confiável (ver `pendências-SEI.md`).
4. **TLS/SSL no SEI**: continua só via Chrome CDP (porta 9222) — regra ética: não burlar TLS.

---

*Handoff gerado pela sessão Claude Code na VM GCP. Próxima IA: leia também `CLAUDE.md`,
`CONSTITUICAO.md` e `pendências-SEI.md` antes de agir.*
