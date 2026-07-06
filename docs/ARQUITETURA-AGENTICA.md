# ARQUITETURA AGÊNTICA — o organograma do ecossistema (1 página)

> **Para qualquer IA/sessão entender o sistema em 2 minutos.** Consolidação 2026-07-06.
> Princípio de projeto: **código determinístico com LLM nas bordas** (benchmarks provaram que IA fraca
> orquestrando livremente erra — `docs/BENCHMARKS.md`). Nada de framework multi-agente genérico.

```
Mestre Jorge (Telegram)
        │
        ▼
┌─ 🧠 YODA (interface) ─────────────────────────────────────────────┐
│ hermes-gateway.service (~/hermes-agent, fork Nous)                │
│ LLM roteia linguagem natural → capacidade registrada → curl API   │
│ /lista = menu determinístico (gerado, sem LLM)                    │
└──────────────────────────────┬────────────────────────────────────┘
                               ▼  HTTP 127.0.0.1:8000
┌─ 💪 API/MOTOR (músculo) ──────────────────────────────────────────┐
│ jfn.service → server.py → compliance_agent/* (determinístico)     │
│ Produtos: /relatorio /orgao /dossie (md+pdf+xlsx, Kroll, async    │
│ → empurra docs no Telegram via notifications/telegram OUTBOUND)   │
│ Autonomia bounded: /api/hermes/missao|trabalhar|parar (goal agent)│
└──────────────────────────────┬────────────────────────────────────┘
                               ▼
┌─ 🫀 METABOLISMO (rotina) ─────┐  ┌─ 🎓 APRENDIZADO ────────────────┐
│ cron escalonado (sweeps SEI/  │  │ jfn-metacognicao 06:50 (sono    │
│ dados/sede, 1 pesado por vez) │  │ REM: reflexão+auto-melhoria+RAG)│
│ timers systemd (tfe, núcleo,  │  │ jfn-nucleo-ciclo 06:30 (perícia │
│ sanções, ronda, hermes-update)│  │ progressiva + casos-ouro)       │
└───────────────────────────────┘  └─────────────────────────────────┘
```

## Fonte única de verdade (não duplicar; gerar)

| O quê | Fonte | Derivados (NÃO editar à mão) |
|---|---|---|
| Capacidades (o que o JFN faz) | **`capabilities.yaml`** | `docs/CAPACIDADES.md` · `data/yoda_capabilities_prompt.txt` (system prompt do Yoda) · `~/.hermes/jfn_menu.json` (menu /lista do adapter) — via `tools/gen_capabilities_md.py` (pre-commit) |
| Estado dos jobs | systemd + cron + flags | `GET /api/agenda` (skill `agenda_jobs`) consolida ao vivo |
| Regra do roteador | capabilities.yaml | Yoda só chama `id` PRONTO; fora do registro = "não tenho ferramenta", nunca invenção |

## Onde está cada peça

- **Yoda vivo** = `hermes-gateway.service` (adapter Telegram + SOUL.md + cadeia multi-IA `~/.hermes/config.yaml`).
  O antigo bot de comandos (`compliance_agent/notifications/telegram.py`) está **MORTO** desde 06/06 — só a
  metade outbound (enviar_mensagem/arquivo) segue viva. NÃO religar (disputa o token).
- **Goal agent** (autonomia bounded): `compliance_agent/hermes_goal.py`, exposto em `/api/hermes/*` e
  registrado no catálogo (`missao_autonoma`, `missao_estado`, `missao_trabalhar`, `missao_parar`).
  Cada ciclo é bounded (passos/ciclos) e para com `missao_parar` — nunca loop que se re-aciona sozinho.
- **Observabilidade**: `compliance_agent/agenda_jobs.py` → `GET /api/agenda` (timers + crons + pausas).
  Journal do gateway limpo: restart = exit 0 (drop-in planned-stop, ver memória `hermes-update-git-merge-seguro`).
- **Aprendizado**: metacognição diária reescreve método/RAG; vereditos do dono (`/veredito`) alimentam o RAG
  (lição: RAG carrega VEREDITOS, não só hipóteses — `docs/BENCHMARKS.md` §4).

## Guard-rails permanentes

1. **VM 2 vCPU**: 1 job pesado por vez (cron escalonado); pausa via `data/.pause_<sweep>` (aparece no /api/agenda).
2. **LLM com kill-switch**: `GEMINI_DISABLED` corta Gemini em tudo; cadeia cai p/ cerebras/groq/extra.
   Todo ponto de LLM tem flag própria (`JFN_LEX_DISCURSIVO`, `JFN_VEREDITO_LLM_DISABLED`, …) — regra dura.
3. **Honestidade**: indício ≠ acusação · INDISPONÍVEL ≠ 0 · proveniência real do modelo gravada
   (`direcionamento_cerebro.ultimo_provedor`).
4. **Hot files do upstream** (hermes-agent): patch mínimo, commitado, preferir fix upstream; unit systemd
   customiza por **drop-in**, nunca editando arquivo gerado.

Ligações: `docs/REFERENCIA-PROJETO.md` (estado vivo) · `docs/CAPACIDADES.md` · `docs/BENCHMARKS.md` ·
`AMBIENTE.md` · vault `~/vault/MOC-Ecossistema`.
