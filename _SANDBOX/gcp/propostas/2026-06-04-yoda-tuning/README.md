# Proposta de tuning do Yoda (VM GCP) — 2026-06-04

> **Para a IA revisora:** este pacote é uma **proposta para revisão ANTES de implementar**.
> Nada aqui é aplicado automaticamente. Cada item abaixo tem status claro
> (`APLICADO` = já está rodando na VM | `PROPOSTO` = só neste pacote, não aplicado).
> Autor: Claude Code (Opus 4.8) rodando na própria VM, a pedido do Mestre Jorge.

## Contexto

A VM GCP roda o bot de Telegram **Yoda** (gateway do `hermes-agent`, serviço systemd
`yoda`). Durante a sessão surgiram 3 demandas:

1. Melhorar uso de IAs: preparar **múltiplas chaves Gemini (pool com rotação)** e uma
   **cadeia de fallback do melhor modelo ao mais disponível**, alternando conforme a
   necessidade. Rodar bem no ambiente da VM (2 vCPU / 7.8 GB, sem GPU).
2. Fazer o **Claude do Desktop** e este **Claude Code da VM** "se falarem" / continuar
   sessão de um no outro.
3. Bug observado: **o chatbot parava de escrever no meio** (ex.: parou em "*No contexto da sua").

## Índice dos arquivos

| Arquivo | O que é |
|---|---|
| `MUDANCAS.md` | **Leia primeiro.** Detalhe de cada mudança: problema, causa-raiz (com evidência de log), o que muda, risco, como aplicar e como reverter. |
| `config/config.yaml.ATUAL-LIVE.snapshot` | Cópia fiel do `~/.hermes/config.yaml` que está rodando AGORA (estado original, sem minhas mudanças de config). |
| `config/config.yaml.PROPOSTO` | O mesmo config **com as mudanças propostas** aplicadas. |
| `config/DIFF.patch` | `diff -u` entre os dois acima — a revisão mais rápida. |
| `soul/SOUL.md.ATUAL-LIVE` | A persona "Mestre Yoda" que **já está aplicada** (ver status abaixo). |
| `systemd/yoda.service.ATUAL-LIVE` | O unit systemd que **já está aplicado** e rodando. |
| `ponte-desktop-claude-code.md` | Tarefa 2: o que dá pra fazer hoje p/ Desktop ↔ Code conversarem/continuarem sessão, com passos concretos. |

## Status de cada mudança

| # | Mudança | Arquivo alvo (produção) | Status | Reversível? |
|---|---|---|---|---|
| A | Serviço systemd `yoda` (24h, Restart=always) | `/etc/systemd/system/yoda.service` | **APLICADO** | sim (`systemctl disable --now yoda` + rm unit) |
| B | `TimeoutStopSec` 30→210 no unit | idem | **APLICADO** | sim (backup `.bak` na VM) |
| C | Persona "Mestre Yoda" | `~/.hermes/SOUL.md` | **APLICADO** | sim (backup `.bak` na VM) |
| D | Fallback Nous→Gemini/Mistral + `api_max_retries` 1→3 + pool Gemini | `~/.hermes/config.yaml` | **PROPOSTO** (revertido na produção a pedido) | n/a (não aplicado) |
| E | Múltiplas chaves Gemini (instruções `hermes auth add`) | `~/.hermes/auth.json` | **PROPOSTO** (instruções) | n/a |
| F | Ponte Desktop ↔ Claude Code | Desktop do Mestre + VM | **PROPOSTO** (pesquisa/recomendação) | n/a |

> Itens A/B/C estão vivos porque eram pré-requisito de "deixar o Yoda no ar" e a persona
> foi pedida explicitamente. Se a revisão preferir que TUDO vire proposta pura (produção
> intocada), é só pedir que eu reverto A/B/C usando os backups `.bak` já existentes na VM.

## Como revisar rápido
1. `config/DIFF.patch` — 3 mudanças de config, todas comentadas inline.
2. `MUDANCAS.md` seção D — causa-raiz do corte de texto, com linhas de log.
3. `ponte-desktop-claude-code.md` — decisão de arquitetura da Tarefa 2.

## Como aplicar (DEPOIS de aprovado) — resumo
Detalhes e rollback completos em `MUDANCAS.md`.
```bash
# Item D (config):
cp ~/.hermes/config.yaml ~/.hermes/config.yaml.$(date +%Y%m%d-%H%M%S).bak
cp ~/JFN/_SANDBOX/gcp/propostas/2026-06-04-yoda-tuning/config/config.yaml.PROPOSTO ~/.hermes/config.yaml
sudo systemctl restart yoda && systemctl is-active yoda
```
