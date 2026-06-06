# Storage da VM — racionalização e o que é seguro limpar

> VM: boot disk de **48 GB** (GCE). Mantenha folga; a base de OBs cresce com a coleta SIAFE. Última
> racionalização: 2026-06-06 (de 100% cheio → ~37%, 30 GB livres). Para a próxima IA: o que é lixo vs. o que NÃO tocar.

## O que JÁ foi liberado (2026-06-06)
- **Docker (~23,5 GB):** imagens/containers dos experimentos `spaceship-video-sandbox`/`stable-diffusion-sandbox`
  (em `/var/lib/containerd`, namespace `moby`). `docker system prune -a -f --volumes`. Não roda mais nada em Docker.
- **Chromium snap + deps (~1,1 GB):** `snap remove chromium gnome-46-2404 mesa-2404 gtk-common-themes`
  (a ponte usa **google-chrome** `.deb`; o Playwright usa o `~/.cache/ms-playwright`). `snap set system refresh.retain=2`.
- **Cache do snapd (~1,3 GB):** `sudo rm -rf /var/lib/snapd/cache/*` (cache regenerável, seguro).
- **Caches** pip/npm, kernel antigo (`linux-image-6.17.0-1016-gcp`), screenshots de debug, `/tmp` de teste.

## Medidas permanentes (para não acumular)
- **Relatórios** (`reports/*.{md,pdf,xlsx}`) são **regeneráveis sob demanda** (cada `/relatorio` gera de novo e o
  Yoda envia na hora). Não precisam ficar no disco: o motor **poda automaticamente** os mais antigos que
  `JFN_REPORTS_RETENCAO_DIAS` (default **7**) — ver `_prune_reports` em `compliance_agent/reporting/inteligencia.py`.
- **Screenshots do coletor SIAFE** só são salvos com `JFN_SIAFE_DEBUG=1`, e vão para `/tmp` (efêmero), nunca para a base.

## NÃO TOCAR (uso legítimo — perderia dados/quebraria sistemas)
| Item | Tam | Por quê manter |
|---|---|---|
| `~/JFN/data/compliance.db` | ~780 MB | A BASE (612k OBs + SIAFE + correlação SEI). Densa (0% free pages) — VACUUM não ajuda. |
| `~/JFN/.venv` | ~6 GB | Ambiente Python do JFN/Massare (Playwright, etc.). |
| `~/hermes-agent/venv` | ~1 GB | Runtime do Yoda. |
| `~/.cache/ms-playwright/chromium-1117` | ~517 MB | Chromium do Playwright (coletor SIAFE). |
| `~/.hermes/state.db` | ~24 MB | Memória/conversas do Yoda. |
| `~/JFN/data/tfe_cache/fornecedor_ob.zip` | ~124 MB | Fonte da reingestão TFE (o timer `jfn-tfe-ob` rebaixa, mas mantém). |
| `~/.EasyOCR`, `~/.cache/huggingface` | ~94M+142M | Modelos de OCR (captcha do SEI). |

## Avaliáveis (liberar se precisar de espaço, com tradeoff)
- `~/.agent-browser/browsers` (~379 MB): Chrome do tool `browser_navigate` do Yoda. Hoje pouco usado (as rotinas
  passaram a usar a API do JFN em vez de raspar). **Removível** — o Yoda rebaixa (~379 MB) se precisar navegar.
- `/var/lib/snapd/seed` (~458 MB): snaps da imagem original (só usados em reseed). Remoção é mais arriscada — evitar.
- `/tmp/claude-1001` (transcrições de tarefas): efêmero, **limpa no reboot**.

## Se faltar espaço de verdade
Não apague dados — **aumente o disco no GCP** (a quente, sem downtime):
```bash
gcloud compute disks resize <DISK> --size=100GB --zone=southamerica-east1-b
sudo growpart /dev/sda 1 && sudo resize2fs /dev/sda1   # (ou o device da raiz)
```
