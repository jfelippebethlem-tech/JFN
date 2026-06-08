# Estratégia de Modelos do Ecossistema JFN/Yoda (re-avaliada 2026-06-08)

> Fonte única da política: `capabilities.yaml` → `politica_modelo`. Implementação do roteamento:
> `tools/hermes_model_router.py`. Pool de chaves (rotação): `~/.hermes/auth.json`. **Tudo 100% grátis**
> por padrão; o único pago (`gemini-2.5-pro`) só sai sob pedido explícito + confirmação do dono.

## Fatos verificados (jun/2026 — medidos na API, não de memória)
- **Gemini free = só `gemini-2.5-flash` e `gemini-2.5-flash-lite`.** Pro e toda a geração 3.x são **PAGOS**.
  `gemini-2.0-flash` foi **desligado em 01/06/2026**.
- **Gemma free pela MESMA chave Gemini:** `gemma-4-31b-it` e `gemma-4-26b-a4b-it` (HTTP 200). Não supera o 2.5-flash.
- **Groq** serve `gemma2-9b-it` grátis e **instantâneo** (chave Groq separada → provider não-Google).
- **Mistral** "Experiment" tier: `mistral-large/small` grátis (~1B tok/mês, rate-limited).
- **Nous `:free`**: sem cota (qualidade menor → último recurso).
- **OpenRouter**: tem modelos `:free` (Gemma 4), mas a conta está sem crédito p/ os pagos.
- **char→token PT-BR jurídico ≈ 3,2 chars/token** (medido). Estimar conservador com `tokens ≈ chars/3`,
  ou usar o endpoint `:countTokens` (exato, grátis).
- ⚠️ **LIMITE FREE É POR PROJETO Google, NÃO por chave** (~250k TPM, ~15 RPM, ~1,5k RPD). → as **8 chaves
  só multiplicam a cota se forem de 8 PROJETOS/CONTAS distintas**. Se do mesmo projeto, compartilham (a rotação
  não dá 8×). **AÇÃO:** confirmar se `jfn1..jfn8` são 8 contas distintas — isso decide se temos 8× ou 1× de free.

## Política por TAREFA (qual modelo, e por quê)
| Tarefa | Modelo (free) | Por quê | Onde se aplica |
|---|---|---|---|
| **Chat / orquestração** (default) | `gemini-2.5-flash` | melhor free; multimodal; contexto 1M; 8 chaves rotacionando | Yoda (Hermes) — toda conversa no Telegram |
| **Raciocínio pesado** (parecer/jurídico/auditoria/edital/14.133/dossiê) | `gemini-2.5-flash` | é o **teto gratuito** (Pro é pago); gatilhos sobem p/ cá | Lex (parecer), `/relatorio`, missão autônoma |
| **Visão / OCR** (captcha SEI, PDF/imagem DOERJ) | `gemini-2.5-flash` | multimodal grátis | leitura SEI (itkava), OCR de documentos |
| **Bulk / lote** (extração SEI em massa, classificação de notícias) | `groq/gemma2-9b-it` | grátis + **instantâneo**; provider **não-Google** (poupa a cota Gemini) | varredor SEI, Radar/Massare notícias em lote |
| **Modelo melhor** (ultra-complexo) | `gemini-2.5-pro` ⚠️PAGO | só sob **pedido explícito** do dono ("usar o modelo melhor") + **confirmação** do Yoda | caso pontual decidido pelo dono |
| **Determinístico** (sweep SIAFE, coletores, Benford, sobrepreço) | — sem LLM — | código puro; não gasta cota nem arrisca alucinação | coleta/análise estatística |

## Cadeia de FALLBACK (resiliência — prioriza diversidade REAL de provider)
Como a cota Google é por projeto, quando o Gemini esgota **todo o tier Google esgota junto** → o failover
precisa ir para **outro provider**:

`gemini-2.5-flash` (default, 8 chaves) → `gemini-2.5-flash-lite` (Google) → **`groq/gemma2-9b-it`** (não-Google,
instantâneo) → `mistral-large-latest` → `mistral-small-latest` → `gemma-4-31b-it` (Google, mesma cota: é
alternativa de **modelo**, não failover de cota) → `nous :free ×3` (sem cota, qualidade menor — último recurso).

## Onde a política é aplicada (mecanismo)
- **Yoda (Hermes):** lê o default e a `fallback_chain` do `~/.hermes/config.yaml`; rotação das 8 chaves pelo
  pool nativo `credential_pool` do `auth.json` (recupera em 429 via `recover_with_credential_pool`).
  Roteamento adaptativo por mensagem (`escolher_modelo`) — **wiring no gateway vivo = última onda** (decisão do dono).
- **JFN (motor):** usa `gemini-2.5-flash` (chave em `~/JFN/.env`) p/ Lex/OCR; bulk via Groq.
- **Confirmação do "modelo melhor":** `quer_modelo_melhor(texto)` detecta o pedido → o Yoda **pergunta** antes
  (é pago) → só com `forcar_melhor=True` usa o `gemini-2.5-pro`.

## Pendências de verificação
- [ ] Confirmar se as 8 chaves Gemini são de **8 projetos/contas distintas** (decide 8× vs 1× de free).
- [ ] Obter chave grátis brapi.dev/Finnhub (Onda 8) — onde faltar, marcar INDISPONÍVEL.
