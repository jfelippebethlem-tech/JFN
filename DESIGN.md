# DESIGN.md — JFN

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
