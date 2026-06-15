# ⚠️ ESTA BRANCH É DE USO EXCLUSIVO LINUX (VM)

> **Para qualquer IA/dev que abrir esta branch (`claude/ambiente-e-relatorio`):**
> Ela foi construída e validada **APENAS para a VM Linux de produção** (Google Cloud, Ubuntu 24.04).
> **NÃO use no Windows.** Caminhos `C:\...` em docs antigos são legado e não se aplicam aqui.

## Por quê
Todo o ecossistema (Yoda/Hermes, JFN, Massare, coletor SIAFE) roda via **systemd `--user`** na VM, com
caminhos absolutos Linux (`/home/ubuntu/...`), `.venv`, Playwright/Chromium de Linux, e serviços de
boot. A infra, os timers, a coordenação de sessão e a ponte Chrome CDP são específicos de Linux.

## Verdade do ambiente (sempre)
- Onde tudo roda, os serviços e o workflow de boot: **[`AMBIENTE.md`](AMBIENTE.md)** + **[`ambiente.json`](ambiente.json)**.
- Storage e o que é seguro limpar: **[`docs/STORAGE.md`](docs/STORAGE.md)**.
- Comandos do Yoda: **[`docs/COMANDOS.md`](docs/COMANDOS.md)**.
- Arquitetura do SIAFE (ADF): **[`docs/SIAFE-ARQUITETURA.md`](docs/SIAFE-ARQUITETURA.md)**.
- Handoff completo da sessão: **[`docs/HANDOFF-2026-06-06-SESSAO-COMPLETA.md`](docs/HANDOFF-2026-06-06-SESSAO-COMPLETA.md)**.

## Se for portar para Windows
NÃO faça merge cego. A branch `claude/rj-finance-agent-BYlhJ` é a base multiplataforma. Esta branch
(`claude/ambiente-e-relatorio`) carrega caminhos/serviços Linux e deve permanecer no contexto da VM.
</content>
