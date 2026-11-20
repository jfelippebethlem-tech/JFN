# Units systemd (--user) do JFN

Esta pasta é o ESPELHO do que está instalado em `~/.config/systemd/user/` da VM-1 (`jfn-core`);
`../vm2/` é o espelho da VM-2. O instalado é a verdade: quem muda uma unit na máquina copia para cá
no mesmo commit. Até 20/11/2026 o espelho estava atrasado (fisc-refresh às 05:40, que derrubou o
job em 2026-07-20; integra-fila sem a fila por dinheiro; chrome-jfn com google-chrome em `/tmp`) —
um `cp` daqui desfazia correções da produção.

Conferir o espelho antes de instalar (nada impresso = igual):
```bash
for f in deploy/systemd/*.service deploy/systemd/*.timer; do
  cmp -s "$f" ~/.config/systemd/user/"$(basename "$f")" || echo "difere: $f"; done
```

Instalar uma unit (copiar só a que mudou, nunca a pasta inteira por cima):
```bash
cp deploy/systemd/<unit> ~/.config/systemd/user/ && systemctl --user daemon-reload
```

## Drop-ins (`drop-ins/`)
- `_onfailure/onfailure.conf` — `OnFailure=notificar-falha@%n.service` (falha vai ao Telegram por
  `tools/notificar_falha.sh`). Instalado em `<unit>.d/onfailure.conf` de: chrome-jfn, handoff-watcher,
  jfn, jfn-integra-fila, jfn-metacognicao, jfn-nucleo-ciclo, jfn-ronda, jfn-sancoes, jfn-tfe, jfn-tfe-ob,
  keepalive, painel-tunnel (e hermes-gateway/hermes-update, que não são deste repositório).
- `jfn-intel-cache.service.d/` (autoauditoria, cadastro), `jfn-pncp-resultados.service.d/atas.conf`,
  `jfn.service.d/unbuffered.conf`.

## Estado em 20/11/2026
- Desligados de propósito: `jfn-tfe.timer` e `jfn-tfe-ob.timer` (o TFE recusa IP de datacenter),
  `jfn-warp.service`, `sweeps-serial*.service`. `jfn-radar.*` não está instalado.
- `jfn.service`: o instalado escuta em `0.0.0.0`; o espelho mantém `127.0.0.1` (decisão pendente do
  dono — ver `docs/untangle/deploy-e-tools-infra.md`).
- Fora do repositório de propósito: `whatsapp-*` (nada do WhatsApp sai da VM) e `hermes-*` (Hermes).
- Massare saiu da VM em 2026-07-07 — não recriar as units `massare-*`.

> ⚠️ O `yoda.service` (nível de SISTEMA) foi DESABILITADO em 2026-06-06 (duplicava o hermes-gateway). Não reativar.
