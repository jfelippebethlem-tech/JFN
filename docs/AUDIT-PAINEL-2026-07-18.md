# Auditoria técnica do painel — 2026-07-18 (impeccable /audit)

Escopo: `static/jfn-painel.html` após a elevação de design + polish (cockpit, abas principais, comparador, covers). Auditoria de código (verificável), não crítica subjetiva.

## Health Score

| # | Dimensão | Nota | Achado principal |
|---|-----------|:---:|---|
| 1 | Acessibilidade | **4/4** | `clk`/`chips`/`spheres` agora `<button>` semânticos; foco visível + touch-targets + teclado ✅ (ver "Atualização") |
| 2 | Performance | 3/4 | Canvas rAF (netbg/malha) + `backdrop-filter` — limitados e com guarda de reduced-motion; sem layout thrash |
| 3 | Theming | 4/4 | Sistema OKLCH completo; componentes derivam de tokens; dark único **intencional** (DESIGN.md) |
| 4 | Responsivo | 3/4 | Grid `auto-fit/minmax`, media query mobile, `overflow-x:hidden`, touch-targets ≥44px em ponteiro grosso |
| 5 | Anti-padrões | 3/4 | Side-stripes/hero-metric/motion decorativo removidos; resta glass + número-herói no **cockpit** (contido = brief) |
| **Total** | | **17/20** | **Good+** — perto de Excellent |

> **Atualização 2026-07-18 (gap #1 resolvido estruturalmente):** os `onclick` viraram elementos semânticos —
> `clk()`→`<button>` (nomes de empresa), `montarSpheres()`→`<button aria-pressed>` (nav), 15 chips→`<button>`.
> Os cards `<div onclick>` (HTML aninhado) e `<a>` sem href seguem o **padrão ARIA button** (role+tabindex+Enter/Espaço
> via `a11yfy`), recomendação WAI-ARIA quando `<button>` nativo aninharia bloco. Verificado: sphere=`BUTTON aria-pressed`,
> clk=`BUTTON` abre dossiê, layout inline preservado, 0 erro. A11y 3→**4/4**.

## Corrigido nesta run (animate + audit)
- **Foco de teclado visível**: `:focus-visible{outline:2px solid var(--accent)}` global (antes: só o anel do UA). Verificado: regra parseada, `--accent`→`oklch(0.82 0.12 188)`.
- **Feedback de clique**: `:active{transform:scale(.97)}` em botões/chips/tabs/spheres/az; `.clk:hover` acende o acento. Tudo sob `prefers-reduced-motion`.
- **Foco de input**: transição de borda + halo `color-mix(--accent)`.
- **Touch targets**: `@media (pointer:coarse)` → `min-height:44px` (WCAG 2.5.5).
- **Theming**: últimos hard-coded de componentes interativos (btn/warn/clk/tabs/az) tokenizados.

## Dívida conhecida (não bloqueia; próximas runs)
1. **A11y estrutural** (maior gap): `.chip`, `.sph`, `.clk` são `span/div` com `onclick` — não operáveis por teclado (Tab/Enter). Fix correto: virar `<button>`/`<a>` ou `role=button`+`tabindex=0`+handler de tecla. As `nav.tabs` já são `<button>` ✓. Requer toque no render (JS), fora do escopo de CSS-only desta run.
2. **Cockpit** carrega os últimos "tells" (glassmorphism via `backdrop-filter`, número-herói, grid de cards similar) — **mantidos de propósito** como a "alma Jarvis" do brief, mas são o teto da nota de anti-padrões enquanto existirem.
3. **Hard-coded atmosférico** (~34 ocorrências): grid-floor, cantoneiras HUD, aura, shimmer da marca, keyframe `beat` — efeitos decorativos intencionais; baixa prioridade de tokenizar.
4. **Tema claro**: inexistente por decisão (dark único). Só reabrir se o uso diurno pedir.

## Veredito
Painel em nível **Good (16/20)**, alinhado ao PRODUCT.md/DESIGN.md. Os pontos que faltam são um trabalho **estrutural de JS** (a11y de teclado) e uma escolha **de brief** (glass do cockpit), não drift de design. Pronto para uso; próxima run natural = converter os `onclick` em elementos semânticos.
