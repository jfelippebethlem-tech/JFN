# Manual — Layout e Organização da VM

VM: Oracle Cloud ARM (`jfn-core`, 2 vCPU · 11,6 GB RAM · 4 GB swap · disco 191 GB).

## Onde mora cada coisa (`/home/ubuntu`)
| Pasta | Tamanho aprox. | O que é |
|---|---|---|
| `JFN/` | 16 G | motor de auditoria (código + `data/compliance.db` + caches SEI) |
| `models/` | 5,1 G | modelos locais (llama/qwen para o Hermes) |
| `hermes-agent/` | 1,6 G | gateway Yoda (fork NousResearch) |
| `polimonitor/` | ~1 G | monitor Instagram (Next.js) |
| `likers-sync/` | 790 M | captura de curtidores (Syncthing ↔ Jorge) |
| `vault/` | — | segundo cérebro Obsidian (memória permanente) |
| `tools-ext/`, `llama.cpp/`, `spiderfoot/` | — | ferramentas auxiliares |

## Regras de recurso (2 vCPU — crítico)
- **1 tarefa pesada por vez.** Nunca 2 browsers (derruba a sessão SEI e a VM).
- Antes de browser/OCR: `~/JFN/tools/vm_guard.py` (preflight de load + mata órfãos).
- Pesado (DuckDB, sweep) → parar sweeps antes; rodar em background serial.

## Higiene de disco (o que limpar quando apertar)
```bash
df -h /                                   # uso
du -sh /tmp/* | sort -rh | head           # lixo em /tmp (tarballs de install!)
npm cache clean --force                   # cache npm cresce até ~2G
journalctl --user --vacuum-size=200M      # logs do systemd do usuário
# logs grandes do JFN: truncar para as últimas ~200KB
```
Limpeza de 2026-07-05: removidos `/tmp/ollama.tar*` (3,6 G) + cache npm (2,1 G) + pid órfão;
disco 34% → 31%.

## Artefatos de estado (não versionar, podem ser apagados se o processo morreu)
`data/*.pid`, `data/*.lock`, `data/.pause_*` — checar `kill -0 <pid>` antes de remover.
`browser.lock` e `bombeiros_supervisor.pid` costumam estar VIVOS durante sweeps.

## Backup
- `backup_compliance.sh` (dom 03:50) — backup do compliance.db.
- **Pendente do dono:** conta Backblaze B2/R2 + app key para backup frio cifrado (rclone crypt).
