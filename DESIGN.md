# DESIGN.md — JFN

> ## 🟦 v60 CLAREZA (2026-11-10) — VIGENTE, supersede o que conflitar abaixo
> Ordem do dono: "o painel tá muito feio — ajuste tudo". Direção: **Linear/Raycast/Stripe com alma
> Jarvis** — o dado lê primeiro; a vida fica em UM lugar por tela. Vivo ≠ poluído.
> Tudo mora em **um** estrato, `static/css/src/99z-v60-clareza.css` (último, não camadado, todo
> seletor prefixado por `html.v60`), e no par `static/js/src/ui/v60.js`. Os estratos antigos não
> foram reescritos. Desligar: `/painel?v60=0` (volta o painel anterior inteiro); religar: `?v60=1`.
> Detalhe por fase: `docs/superpowers/specs/HANDOFF-painel-v60-2026-11-10.md`.
>
> **Tokens (bloco `html.v60{…}`)** — fundo `--bg` oklch(0.145 0.018 255) · header/nav `--bg-2` ·
> cartão `--card` (.82) / `--card-hi` · linhas `--line` / `--line-soft` · tinta `--ink` / `--ink-2` /
> `--muted` (≥4.5:1 sobre o cartão) · `--ion` oklch(0.78 0.14 258) = estrutura/seleção/link ·
> `--flame` oklch(0.78 0.16 55) = ação/dinheiro · severidade `--crit` / `--warn` / `--ok` ·
> raios `--r-s:8 / --r-m:12 / --r-l:16` · espaço 4/8/12/16/24/32 · `--ease` cubic-bezier(.2,.7,.2,1) ·
> `--sh` (sombra única). ÍON + CHAMA continuam; nunca dessaturar.
> Tipos (rem, fixos): display 1.75/700 · título de aba 1.25/700 · seção 1/650 · corpo .9375/400 ·
> valor de KPI 1.5 mono 600 tabular · rótulo .8125 sans 550 em sentence case, sem letter-spacing ·
> meta .75 mono.
>
> **Regras v60 (as que não se negociam):**
> 1. **Uma camada ambiente**: só `#esfnebula` (vídeo/poster da esfera a .45 sob scrim fixo). Grade,
>    malha do RJ, rede, auras, aurora, cometas, malha de luz entre cartões e textura NÃO voltam.
>    No cockpit, um canvas (o núcleo) e um vídeo. No celular, poster — vídeo só ao toque.
> 2. **Duas fontes**: IBM Plex Sans (texto) + IBM Plex Mono (número/CNPJ/valor). **Sem Orbitron.**
>    Sem caixa alta em rótulo, sem letter-spacing.
> 3. **Rating sem emoji**: ponto CSS de 10px + rótulo ("grave", "atenção", "ok"); a legenda da escala
>    continua explícita. Ícone de UI = SVG de `jfn-icones.js` (nunca emoji, nunca raster).
> 4. **Navegação**: celular = cabeçalho 56px, esferas no RODAPÉ (64px + safe-area), abas como chips
>    sticky no topo, ações no menu "⋯". Desktop = cabeçalho 64px numa linha, esferas como segmented
>    control, chips sticky sob o cabeçalho. Nenhum elemento fixo cobre conteúdo.
> 5. **KPI**: rótulo → valor → nota; alturas iguais na grade; cor no valor só para severidade ou
>    dinheiro; sem barra-glow, sem anel, sem ponto de canto. Lista = um contêiner com separadores
>    (nunca card dentro de card), linha inteira clicável.
> 6. **Movimento = estado**: 150–220ms, sem bounce, crossfade de 160ms na troca de aba;
>    `prefers-reduced-motion` desliga tudo. Foco visível: anel 2px `--ion`. Toque ≥44px no celular.
> 7. Honestidade intacta: INDISPONÍVEL ≠ 0, nenhum número inventado, indício ≠ acusação.

> ## 🔷 v9 "ÍON" + v10 "AGÊNCIA" (2026-07-22) — VIGENTES, supersedem o que conflitar abaixo
> As camadas são ADITIVAS no CSS (v7 → v8 → v9 → v10, a cascata vence; nunca reescrever bloco antigo).
> O que está REALMENTE renderizado hoje:
> - **Paleta v9**: `--ion` azul oklch(≈0.78 0.14 258) = o console (estrutura, interação, frio) ·
>   `--flame` laranja oklch(≈0.78 0.16 55) = ENERGIA (ação, dinheiro, carga). `--accent`, `--gold`,
>   `--amber` e `--blue` do v7 são REMAPEADOS para íon/chama por cascata — o cian v7 não aparece mais.
>   Severidade mantém voz própria: rosa = crítico, verde = ok. **Nunca dessaturar** (v6 foi regressão declarada).
> - **Fontes reais**: **IBM Plex Sans** (texto) + **IBM Plex Mono** (número/telemetria/CNPJ), self-hosted
>   em `/static/assets/fonts/` (woff2, `font-display:swap`). (Inter/JetBrains abaixo = histórico.)
> - **Sistemas vivos**: portal de ignição WebGL (1×/sessão, cobre o carregamento, qualquer toque pula),
>   malha IBGE do RJ (`rj-malha.js`) atrás de toda aba tingida pela esfera, nebulosa por esfera,
>   grid holográfico, plexus, arc-reactor com status de sweep, ícones SVG (`jfn-icones.js`), 3D
>   universal via UM listener delegado (`--rx/--ry/--mx/--my`).
> - **v10 "AGÊNCIA" (consistência/confiança)**: escala única de raio `--r-s:8 / --r-m:10 / --r-l:13`;
>   sombra canônica `--sh:var(--lift)`; `--dim-sm` p/ rótulos ≤11px (contraste ≥4.5:1); ease-out-quart
>   em todo controle (bounce banido de vez); **toast/confirm da casa** (`jfnToast`/`jfnConfirm` — alert()
>   nativo é proibido); erro de rede SEMPRE via `erroHumano()` (nunca `TypeError` cru na tela); herói com
>   estado de erro + retry; **orçamento de vida**: aba do navegador oculta → `html.rest` pausa toda
>   animação CSS (canvas já pausam por RAF).
> - `prefers-reduced-motion` desliga tudo, inclusive o portal. Dado sintético segue proibido
>   (gerador `Math.random` removido no v10).

> ## ⚡ v7 "REATOR" (2026-07-19) — base viva sob as camadas acima
> Brief do dono: **vivo, interativo, cores vivas, lightsaber, Jarvis, Apple Glass**. Sistema:
> - **Paleta viva**: mesmos tokens, chroma elevado (accent cian holográfico ~oklch(0.85 0.14 200); estados do sabre teal/âmbar/rosa; ouro=dinheiro; azul=Estado, ouro=Prefeitura, violeta=Transversal).
> - **Vidro líquido (visionOS)**: card = blur+saturate, highlight especular no topo (inset 1px branco), sombra de profundidade, borda-hairline com gradiente. `prefers-reduced-transparency` → sólido.
> - **Energia contínua** (assinatura): Conduíte-lâmina (núcleo branco-quente + glow) → plexus de fundo → malha de luz entre cards → border-beam em hover/ativo. Metáfora única: informação = plasma.
> - **Cada controle vivo**: spotlight que segue o cursor (--mx/--my), borda que energiza na cor da esfera, active com spring, chips/tabs acesos com glow. Tudo desligado em reduced-motion.
> - **Honestidade intacta**: vida SÓ com dado/evento real; contraste ≥4.5:1; INDISPONÍVEL ≠ 0.

> Sistema visual do painel de fiscalização. Register **product**, dark, "Apple-elegante com alma Jarvis".
> Regência: acento com significado, motion = estado, densidade com ar. Impeccable-compliant.

## Theme
Dark único (uso noturno + sala de comando). Fundo azul-quase-preto frio; tinta clara fria; um acento teal.
Estratégia de cor: **Restrained** — neutros tintados + 1 acento (teal) ≤10% da superfície; âmbar/rosa/verde só como severidade semântica.

## Color (OKLCH)
Neutros tintados na própria hue do acento (frio ~235), chroma baixíssimo — sem "cinza morto".

| Token | OKLCH | Uso |
|---|---|---|
| `--bg` | `oklch(0.16 0.015 240)` | fundo do app |
| `--panel` | `oklch(0.20 0.016 240)` | 2ª camada (nav, toolbars, cover) |
| `--surface` | `oklch(0.225 0.017 240)` | card/conteúdo |
| `--surface-2`| `oklch(0.265 0.018 240)` | hover/raise |
| `--line` | `oklch(0.34 0.02 240)` | bordas (full, nunca side-stripe) |
| `--line-soft`| `oklch(0.28 0.016 240)` | divisores internos |
| `--ink` | `oklch(0.97 0.006 240)` | texto primário (≥12:1) |
| `--ink-2` | `oklch(0.84 0.012 240)` | texto secundário (≥6:1) |
| `--muted` | `oklch(0.70 0.015 240)` | rótulos/meta (≥4.5:1 em surface) |
| `--dim` | `oklch(0.58 0.014 240)` | hint (só texto grande/ícone) |
| `--accent` | `oklch(0.82 0.12 188)` | teal — seleção/estado/ação/link |
| `--accent-ink`| `oklch(0.20 0.05 195)` | tinta sobre fundo teal |
| `--gold` | `oklch(0.83 0.10 85)` | 2º acento raro (destaque de valor) |
| `--sev-hi` | `oklch(0.70 0.17 18)` | severidade alta / 🔴 |
| `--sev-md` | `oklch(0.80 0.13 72)` | severidade média / 🟡 |
| `--sev-ok` | `oklch(0.80 0.14 158)` | ok / 🟢 |

Estados semânticos (padronizados): hover=`--surface-2`; focus=anel `--accent` 2px; selected=borda `--accent`+tinta 8%; disabled=opacity .5; loading=skeleton (não spinner no meio do conteúdo).

## Typography
Uma família de texto (**Inter**) + **JetBrains Mono** SÓ para número/telemetria/CNPJ (par por eixo de contraste sans×mono, legítimo para dado). Sem fonte display em UI.
Escala **fixa** (rem), razão ~1.2 — não fluida:

| Papel | Tamanho | Peso | Nota |
|---|---|---|---|
| display (capa) | 1.5rem/24px | 750 | `text-wrap:balance`, tracking -0.02em |
| título seção | 1rem/16px | 700 | |
| kpi valor | 1.375rem/22px | 700 | mono, tabular-nums |
| corpo | 0.9rem/14.5px | 400 | prosa ≤72ch |
| rótulo/meta | 0.72rem/11.5px | 600 | mono, tracking 0.4px; **não** uppercase-eyebrow em toda seção |
| micro/hint | 0.72rem/11.5px | 500 | |

## Layout
- Shell: header fixo + esferas (segmented) + tabs + `#view`. `max-width` do conteúdo ~1180px.
- Grid responsivo sem breakpoint: `repeat(auto-fit, minmax(300px, 1fr))`; flex para 1D.
- Ritmo de espaçamento variado (não um gap único): escala 4/8/12/16/24/32.
- z-index semântico: base(0) < conteúdo(1) < sticky(20) < overlay(40) < sheet(50) < toast(60).
- Cards: só quando são a melhor affordance; **nunca** card dentro de card; **nunca** side-stripe.

## v5 "SABRE" — o vivo em tempo real (2026-07-18)
Assinatura única do painel (boldness gasta em UM lugar): **o Conduíte** — lâmina fina sob o
header que é o barramento SSE `/api/eventos/stream`. Cada evento real (OB, alerta, cláusula,
sweep) = pulso de plasma viajando; cor da lâmina = estado agregado (teal ok · âmbar carga ·
rosa crítico, transição 2s, nunca pisca); ocioso = respiração sutil (silêncio honesto).
**Kyber core** no header: arco = load da VM (teto 5), núcleo pisca com sweep ativo.
**Holofeed**: vidro líquido flutuante (blur + borda interna 1px + inset highlight; fallback
sólido sob `prefers-reduced-transparency`), últimos 10 eventos, mono, divide-y.
Vidro SÓ em camada flutuante (elevação real). O único glow permitido = lâmina/core.
`prefers-reduced-motion`: lâmina estática, sem pulsos; feed continua.

## Motion (alma Jarvis, contida)
- 150–220ms na maioria; ease-out-quart `cubic-bezier(.2,.7,.2,1)`. Sem bounce/elastic.
- Motion = ESTADO: hover, focus, seleção, entrada de conteúdo (crossfade curto), reveal de sheet.
- **Sem** cascata orquestrada uniforme em toda seção. Stagger só dentro de UMA lista longa, curto.
- "Alma Jarvis" = **momento raro**: a malha viva do cockpit e o glow de foco são acentos, não a página.
- `prefers-reduced-motion`: crossfade/instantâneo; malha estática.

## Components (estados completos)
- **KPI**: valor mono grande + rótulo; sem side-stripe (o antigo `.kpi::before` sai), sem gradiente; destaque por peso/cor semântica. Não repetir o template hero-metric — variar densidade.
- **Card de indício**: nome (link teal) + CNPJ meta + tags de sinal + leitura honesta; hover eleva sutil (borda `--line`→`--accent` 40%, sem lift teatral).
- **Tag/severidade**: pill de baixa saturação; 🔴🟡🟢 = escala explícita.
- **Busca+A→Z**: input com ícone; botão A→Z (ordena por fornecedor, volta à ordem por risco).
- **Empty state**: ensina a tela (o que é, como preencher), não "nada aqui". **INDISPONÍVEL** é estado honesto, não vazio.
- **Loading**: skeleton do layout, não spinner central.
