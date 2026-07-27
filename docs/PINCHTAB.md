# PinchTab para todos os nossos Claudes — instalação, uso e o que eu medi
de: jfn-core · quando: 2026-07-26 (noite) · origem: reel indicado pelo dono (@marc.kaz)

**O que é:** um binário Go único que dá **controle de navegador a agentes por HTTP
puro** — sem SDK, sem framework, `curl` basta. Traz também **servidor MCP** (`pinchtab mcp`),
que é como o Claude Code de cada nó ganha as ferramentas de navegador nativamente.

**Procedência conferida por mim (não pelo reel):**
`github.com/pinchtab/pinchtab` · **9.575 estrelas** · licença **MIT** · Go ·
último push 2026-07-26 (hoje) · release **v0.15.0**.
Binário baixado e **checksum SHA-256 batendo com o `checksums.txt` oficial**.

**Por que nos interessa exatamente agora:** foi o problema que travou a noite inteira —
dar a um agente controle de um navegador real. O PinchTab resolve isso com browser
**próprio e isolado** (perfil em `~/.pinchtab/profiles/`), sem depender do Chrome pessoal
do dono, sem copiar perfil e sem porta de depuração no perfil padrão (que o Chrome 136+
recusa). E o `snapshot` de acessibilidade custa ~800 tokens contra uma captura de tela.

---

## 1 · Instalar (cada nó, uma linha)

**Linux ARM64 (jfn-core, jfn-agent-2):**
```bash
curl -sL -o ~/.local/bin/pinchtab \
  https://github.com/pinchtab/pinchtab/releases/download/v0.15.0/pinchtab-linux-arm64
chmod +x ~/.local/bin/pinchtab && pinchtab --version
```

**Windows (it-campo)** — PowerShell:
```powershell
iwr -Uri https://github.com/pinchtab/pinchtab/releases/download/v0.15.0/pinchtab-windows-amd64.exe `
    -OutFile "$env:LOCALAPPDATA\Programs\pinchtab.exe"
& "$env:LOCALAPPDATA\Programs\pinchtab.exe" --version
```
(confira o checksum contra `checksums.txt` do release antes de usar)

**Sanidade em qualquer nó:** `pinchtab doctor` — tem que sair `passed, 0 failed`.

## 2 · Ligar no Claude Code de cada nó (é isto que interessa)

```bash
claude mcp add pinchtab -- pinchtab mcp        # Linux/macOS
claude mcp add pinchtab -- "%LOCALAPPDATA%\Programs\pinchtab.exe" mcp   # Windows
```
Depois disso o Claude daquele nó enxerga as ferramentas de navegador (nav, click,
fill, snapshot, capture, eval, network, console…) sem gambiarra de CDP.

O servidor precisa estar de pé: `pinchtab server` (ou `pinchtab daemon install` para
subir sozinho no boot).

## 3 · O que eu MEDI aqui na jfn-core (e a ressalva honesta)

| item | resultado |
|---|---|
| download + checksum oficial | **confere** |
| `pinchtab doctor` | **6 passed, 0 failed** |
| servidor de pé | **sim** — API em `127.0.0.1:9867`, bridge em `9868` |
| guarda de segurança | **UP (maximum)** — só `127.0.0.1`, `localhost`, `::1` liberados |
| **navegar de fato** | **falha nesta VM**: `503 instance not ready after 10s` |

**Causa medida:** o tempo de prontidão da instância é curto (10 s) e esta VM de
**2 vCPU sem GPU (SwiftShader)**, com load ~5, não sobe o Chromium nesse prazo.
Troquei o Chromium do **snap** (cujo `desktop-launch` é ainda mais lento) pelo binário
direto do Playwright — o `doctor` passou a validar em 53 ms, mas o limite de 10 s
continua apertado sob carga.

**Conclusão prática, coerente com a divisão de lanes da casa:** o PinchTab é ferramenta
para a **lane pesada — o it-campo** (24 núcleos), onde deve voar. Na `jfn-core` ele fica
**instalado e configurado**, para uso pontual quando a máquina estiver ociosa; browser
pesado aqui sempre foi contraindicado ([[vm-nao-crashar]]).

Config já ajustada aqui: `browser.binary` apontando para o Chromium do Playwright
(`pinchtab config get browser.binary`). Se um dia quisermos insistir nesta VM, o caminho
é parar os sweeps antes e medir de novo — não aumentar o tempo no grito.

## 4 · Regras nossas que continuam valendo

- Navegador do PinchTab é **próprio e isolado**: nada de reaproveitar sessão logada de
  serviço de terceiro para automatizar a UI dele.
- Nada de assumir free tier em nada que seja API paga.
- Na `jfn-core`, **um pesado por vez**: se for usar, pause sweep/DuckDB antes.
