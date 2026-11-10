# BRIEF — Painel JFN v60 "CLAREZA" (2026-11-10)

> Ordem do Mestre Jorge: "o painel tá muito feio — ajuste tudo". Esta sessão faz **SÓ isto**.
> Nenhuma outra tarefa, nenhum outro projeto, nenhuma coleta, nenhum restart do `jfn`.
> Auditoria feita por outra sessão (prints em `screenshots/holo/aud_*.png`, 390×844 e 1600×1000).
> Este brief é autossuficiente: passos explícitos, comandos prontos, critério de aceite em cada fase.

---

## 0. Regras inegociáveis (ler antes de tudo)

1. Ler antes de editar: `CLAUDE.md`, `AGENTS.md`, `DESIGN.md`, `PRODUCT.md`,
   `docs/PREFERENCIAS-MESTRE-JORGE.md`, `docs/superpowers/specs/HANDOFF-painel-v27-2026-07-26.md`.
   Se algo aqui conflitar com eles, **este brief vence só no visual**; regras de dado/honestidade deles vencem sempre.
2. Branch: `git switch -c ui/painel-v60-clareza` a partir do HEAD atual (`ui/login-midia-som`).
   **Nunca** dar `git add` em `data/*`, `AGENTS.md`, `CLAUDE.md` (mudanças alheias não commitadas). Sem force-push. Sem merge em `main`.
3. **Não reiniciar o serviço `jfn`.** CSS/JS são servidos do disco; basta build + bump `?v=`.
4. Um processo pesado por vez. `nice -n 10` em build/screenshot. Sem `pkill -f`. Checar `uptime` antes de cada rodada de prints (load > 3 → esperar).
5. Scripts clássicos apenas (sem `defer`/`async`/`type=module`). As 51+ abas continuam, `i_cockpit` primeiro. Clique em CNPJ abre dossiê. `prefers-reduced-motion` desliga todo movimento. **INDISPONÍVEL ≠ 0**. Nenhum número inventado (nem em arte). Nada de `Math.random` em dado.
6. Camadas CSS são aditivas: **não reescrever estratos antigos**. Tudo novo vai em **um** estrato novo `static/css/src/99z-v60-clareza.css`, carregado por último, com todo seletor prefixado por `html.v60`.
7. Arte vem de gerador (Flow/Veo/Imagen já gerados em `static/assets/`). **Não** criar ícone raster, **não** desenhar arte por código. Ícones de UI = os SVG já existentes de `jfn-icones.js`.
8. Fluxo de build obrigatório a cada mudança:
   ```bash
   cd ~/JFN
   PYTHONPATH=. .venv/bin/python -m tools.painel_css_cortar --juntar   # se mexeu em static/css/src
   nice -n 10 npm run build:painel                                     # se mexeu em static/js/src
   PYTHONPATH=. .venv/bin/python tools/painel_bump_versao.py           # ?v= novo
   bash tools/precommit_painel.sh                                      # gate; tem que passar
   ```
9. Commit ao fim de cada fase (mensagem `feat(painel-v60): <fase>`), com prints antes/depois.

---

## 1. Diagnóstico (por que está feio)

| # | Problema observado nos prints | Causa |
|---|---|---|
| D1 | Fundo "sujo", texto disputando com luz | **12 camadas ambientes fixas** atrás do conteúdo: `#hologrid`, `canvas#rjbg`, `#esfnebula` (vídeo), `#holorj`, `canvas#netbg`, `.aura.a1`, `.aura.a2`, `#aurora`, `.cometa.c1/.c2`, mais `canvas.view-wire` de 9.145 px de altura dentro do `#view` |
| D2 | Tipografia sem voz única | 3 vozes: Plex Sans + Plex Mono + **Orbitron** (rótulos de KPI e barra de abas em caixa alta, letras exóticas, ilegível a 11 px) |
| D3 | Cards de KPI repetitivos e "game UI" | toda KPI tem barra-glow embaixo, anel-marca-d'água à direita, ponto colorido no canto, rótulo em CAIXA ALTA espaçada |
| D4 | Header gigante no celular (152 px + pill "modo sóbrio · 2 fps") | 4 botões com borda (Mudo, Termos, Controle, Sair) + reator + badge, tudo em 1ª dobra |
| D5 | Navegação pesada | esferas no topo + barra de 19 abas no rodapé com scroll horizontal e rótulo Orbitron; no desktop a barra de abas flutua por cima da última linha da lista |
| D6 | `#holofeed` (330×112, fixo, blur) fica **por cima do conteúdo** no celular | camada flutuante sem regra de mobile |
| D7 | Cabeçalho de aba (`.cover`) com selo 3D + "lâmina" de scanline falsa embaixo | enfeite que não é dado |
| D8 | Lista de Perícias: faixa de gradiente no meio de cada linha, emoji 🟡 como rating, linha alta (≈76 px), nome com sublinhado pontilhado | `.card::after` herdado + emoji |
| D9 | Radar: pills de sinal em MONO CAIXA ALTA com borda, quebrando em 3 linhas | estilo de tag v7 |
| D10 | Cockpit desktop: colunas desalinhadas, buracos verticais entre KPIs, card central com 2 vídeos + 1 canvas | grid sem `grid-auto-rows`, mídia empilhada |
| D11 | Emojis misturados com SVG nas esferas/abas (🏙️ 🌐 📊…) | legado |

**Direção v60:** "Linear/Raycast/Stripe com alma Jarvis" (PRODUCT.md) — o dado lê primeiro; a vida fica em **um** lugar por tela. Vivo ≠ poluído.

---

## 2. Mecanismo de flag (fase 0 — fazer primeiro)

Todo o v60 fica atrás de `html.v60` até a fase final, para o Mestre Jorge nunca ver meio-termo.

1. Em `static/jfn-painel.html`, **logo após `<head>`**, script clássico inline:
   ```html
   <script>(function(){try{var q=new URLSearchParams(location.search).get('v60');
   if(q==='1')localStorage.setItem('jfn_v60','1');if(q==='0')localStorage.setItem('jfn_v60','0');
   var on=localStorage.getItem('jfn_v60');if(on===null)on=window.JFN_V60_DEFAULT||'0';
   if(on==='1')document.documentElement.classList.add('v60');}catch(e){}})();</script>
   ```
   (Na fase 9 troca-se o default para `'1'`.) Escape do dono: `/painel?v60=0`.
2. Criar `static/css/src/99z-v60-clareza.css` com o cabeçalho de comentário e o bloco de tokens (§3).
3. Adaptar `_SANDBOX/shot_painel.py`: aceitar env `V60=1` → depois do login, `page.add_init_script("localStorage.setItem('jfn_v60','1')")` antes do `goto`. Prints: `screenshots/holo/v60_<fase>_<view>_<aba>.png`.
4. **Aceite:** com `?v60=0` o painel é idêntico ao atual (byte do CSS antigo intacto; `--check` do cortar passa); com `?v60=1` a classe aparece no `<html>`.

---

## 3. Tokens v60 (bloco `html.v60{…}` no topo do estrato)

Mantém v9 (ÍON azul + CHAMA laranja, nunca dessaturar), mas consolida e limpa.

```css
html.v60{
  --bg:        oklch(0.145 0.018 255);   /* fundo único, azul-noite */
  --bg-2:      oklch(0.175 0.020 255);   /* header/nav */
  --card:      oklch(0.200 0.020 255 / .82);
  --card-hi:   oklch(0.235 0.022 255 / .90);
  --line:      oklch(0.36 0.025 255 / .55);
  --line-soft: oklch(0.30 0.020 255 / .45);
  --ink:       oklch(0.97 0.006 255);
  --ink-2:     oklch(0.86 0.012 255);
  --muted:     oklch(0.72 0.016 255);    /* ≥4.5:1 sobre --card */
  --ion:       oklch(0.78 0.14 258);     /* estrutura/seleção/link */
  --flame:     oklch(0.78 0.16 55);      /* ação/dinheiro */
  --crit:      oklch(0.70 0.18 18);
  --warn:      oklch(0.82 0.14 80);
  --ok:        oklch(0.80 0.14 158);
  --r-s:8px; --r-m:12px; --r-l:16px;
  --sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-5:24px; --sp-6:32px;
  --ease: cubic-bezier(.2,.7,.2,1);
  --sh: 0 1px 0 oklch(1 0 0 / .05) inset, 0 8px 24px -12px oklch(0 0 0 / .6);
  --f-sans: "IBM Plex Sans", system-ui, sans-serif;
  --f-mono: "IBM Plex Mono", ui-monospace, monospace;
}
```
Tipos (fixos, rem): display 1.75/700/-0.02em · título aba 1.25/700 · seção 1rem/650 · corpo .9375/400 · KPI valor 1.5 mono 600 tabular · rótulo .8125 sans 550 **sentence case, sem letter-spacing** · meta .75 mono.

---

## 4. Fases de execução (uma por commit)

### Fase 1 — Fundo: de 12 camadas para 1 (resolve D1)
- `html.v60 #hologrid, html.v60 #rjbg, html.v60 #holorj, html.v60 #netbg, html.v60 .aura, html.v60 #aurora, html.v60 .cometa, html.v60 canvas.view-wire { display:none !important; }`
- **Uma** camada viva: `#esfnebula` vira backdrop de tela cheia (`inset:0; width:100%; height:100%; object-fit:cover`), vídeo por esfera (já existentes, gerados no Flow):
  `inicio → portal-hero`, `estado → nebula-estado`, `prefeitura → nebula-prefeitura`, `geral → nebula-transversal` (webm + mp4 + poster .jpg).
  Sobre ele, scrim fixo: `linear-gradient(180deg, oklch(0.145 0.018 255 / .55) 0, oklch(0.145 0.018 255 / .88) 40vh, var(--bg) 100vh)`. Opacidade do vídeo .45; `filter: saturate(1.15)`.
- No JS: se `html.v60`, **não** iniciar os RAF de `rjbg`/`netbg`/`view-wire` (guard `if(document.documentElement.classList.contains('v60')) return;` no início de cada init — achar em `static/js/src/cena/`). Economiza CPU no celular.
- Celular ou `body.fps-baixo` ou `prefers-reduced-motion` ou `navigator.connection.saveData`: **não tocar vídeo, só poster** (`video.pause(); video.removeAttribute('autoplay')`).
- Esconder a pill "modo sóbrio · 2 fps" em v60 (continua existindo no Controle).
- **Aceite:** fundo calmo; nenhuma linha/grade cruza texto; `document.querySelectorAll('canvas').length` no cockpit ≤ 1 (o do núcleo).

### Fase 2 — Tipografia única (D2)
- `html.v60 *{font-family:var(--f-sans)}` com exceções mono: `.num, .v, .mono, code, [data-cnpj], .cnpj, .kpi .v, td.r, .valor` → `var(--f-mono); font-variant-numeric: tabular-nums`.
- **Orbitron banido em v60** (todos os seletores que o usam: buscar `Orbitron` em `static/css/src/*` e sobrescrever).
- Rótulos: `text-transform:none; letter-spacing:0`. Onde o texto-fonte é CAIXA ALTA no HTML (ex. "RADAR DE RISCO"), aplicar `text-transform:lowercase` + `::first-letter{text-transform:uppercase}` só se não houver como mudar a fonte do texto; preferir corrigir no JS.
- **Aceite:** `fonts.js` de auditoria (abaixo) mostra só Plex Sans e Plex Mono.

### Fase 3 — Header e navegação (D4, D5, D6, D11)
**Celular (≤ 760px):**
- Header 56px: marca (logo "CE" atual) + "Controle Externo" 15px/650 + subtítulo 11px muted. Reator (kyber) pequeno 22px à direita. Badge AO VIVO vira ponto 6px ao lado do título.
- Botões Mudo/Termos/Controle/Sair → **um** botão "⋯" (ícone SVG da casa) que abre o `#sheet` existente (`#ov`) com essas 4 ações em lista grande (48px por linha). Reaproveitar funções já existentes; só mudar o gatilho.
- `#conduit` (lâmina SSE): manter, 2px, colado no fim do header — é a assinatura viva. Nada mais brilha no header.
- **Esferas vão para o rodapé** (`#spheres` → `position:fixed; bottom:0; inset-inline:0; height:64px + env(safe-area-inset-bottom)`), 4 itens com ícone SVG 22px + rótulo 11px sentence case; ativa = ícone em `--ion` + pílula `--ion / .14` atrás. Trocar emojis 🏙️ 🌐 por ícones SVG de `jfn-icones.js` (Estado já usa `§rj`).
- **Abas vão para o topo** (`#tabs` → `position:sticky; top:56px`), trilho horizontal de chips: altura 40, chip 32px, padding 0 12px, raio 999, Plex Sans 13px/550, ícone 16px opcional. Ativo: fundo `--ion / .16`, texto `--ink`, borda `--ion / .45`. Máscara de fade nas bordas (`mask-image: linear-gradient(90deg, transparent, #000 16px, #000 calc(100% - 16px), transparent)`). Ao trocar de aba, `scrollIntoView({inline:'center', block:'nearest'})` no chip ativo.
- `#holofeed`: **oculto no celular**; vira item "Atividade ao vivo" dentro do sheet "⋯" e mini-card recolhível no fim do cockpit.
- `main#view` ganha `padding-bottom: calc(80px + env(safe-area-inset-bottom))`.

**Desktop (> 760px):**
- Header 64px numa linha: marca à esquerda · esferas como **segmented control** central (sem subtítulo; subtítulo vira `title`) · ações como botões-ícone 36px sem borda à direita (tooltip). Largura útil 1280px.
- Abas: trilho de chips sticky sob o header (não mais flutuando no rodapé por cima da lista). Overflow com setas ‹ › só se transbordar.
- `#holofeed` mantém, canto inferior direito, recolhido por padrão (pill "Ao vivo · N"), expande ao clicar.
- **Aceite:** 1ª dobra do celular mostra header + chips + começo do conteúdo em ≤ 112px; nenhum elemento fixo cobre conteúdo; 4 ações acessíveis em ≤ 2 toques.

### Fase 4 — Cabeçalho de aba `.cover` (D7)
- Selo: 40px, plano (sem 3D/sombra interna), ícone SVG em `--ion` sobre `--ion / .12`, raio `--r-m`.
- Título 1.25rem/700; descrição `--muted` .875rem, **máx. 2 linhas** com `line-clamp` + botão "mais" que expande (JS mínimo, delegado).
- Remover a "lâmina"/scanline sob o cover (`html.v60 .cover::after, .cover::before{display:none}` — confirmar seletor real).
- Botões de ação da aba (ex. "Gerar PDF") alinhados à direita do cover no desktop; abaixo, largura total, no celular.

### Fase 5 — KPIs (D3, D10)
- `.card.kpi`: fundo `--card`, borda 1px `--line-soft`, raio `--r-l`, padding 16, `box-shadow: var(--sh)`, `backdrop-filter: blur(14px) saturate(1.2)` (fallback sólido em `prefers-reduced-transparency`).
- **Remover**: barra-glow inferior, anel marca-d'água, ponto do canto (`::before/::after` da KPI; confirmar seletores em `95-v58`/`96-v59`).
- Conteúdo: rótulo (.8125 sans muted, 1 linha, ellipsis) → valor (1.5rem mono 600, cor semântica **só** quando o dado é de severidade: crit/warn/ok; dinheiro = `--flame`; demais = `--ink`) → nota (.75 muted, máx. 2 linhas).
- Ícone de alerta ⚠ só em KPI crítica, 14px, ao lado do rótulo (não no canto).
- Grid: `grid-template-columns: repeat(auto-fill, minmax(160px, 1fr))` no celular (2 colunas em 390px), `minmax(220px,1fr)` no desktop; `grid-auto-rows: 1fr` → **alturas iguais, sem buracos**. Gap 12/16.
- Hover (desktop): borda → `--ion / .5`, `translateY(-1px)`, 160ms `--ease`. Toque: `:active` scale .98.
- `data-sobre` (popover explicativo) continua igual.

### Fase 6 — Listas e tabelas (D8, D9)
**Linhas de lista (Perícias, Sancionadas, Escalada etc. — tudo que é `.card` clicável de fornecedor):**
- Altura ~60px, padding 12/16, separador `--line-soft` entre linhas dentro de **um** container (não um card por linha; nunca card dentro de card).
- Remover a faixa de gradiente do meio (`.card::after` / `.rise` herdado — achar e anular em v60).
- Esquerda: nome (15px/600 `--ink`, sem sublinhado; hover → `--ion`) + meta (12px mono muted: "34 indícios · 14 órgãos · 1.549 OBs").
- Direita: valor (mono 14px, `--flame` se dinheiro) + **rating como ponto CSS 10px** (crit/warn/ok) com rótulo textual curto ("grave", "atenção", "ok") — **substituir emojis 🟢🟡🔴** na renderização v60 (manter o significado e a legenda explícita da escala). Chevron › 16px muted no fim.
- Linha inteira clicável (mantém abrir dossiê).

**Pills de sinal (Radar e afins):**
- Plex Sans 12px/550 sentence case, sem borda, fundo da severidade a .14, texto na cor da severidade clareada (contraste ≥4.5:1), raio 999, padding 3/8, gap 6. Pontuação "+25" em mono .75 com opacidade .8.

**Tabelas (`table`):**
- Cabeçalho sticky, 12px sans 600 muted, sem caixa alta; linhas 44px; zebra sutil `oklch(1 0 0 / .02)`; números à direita mono tabular; no celular a tabela rola **dentro** do card com sombra de borda indicando overflow.

**Filtros/busca:**
- Input 44px, raio `--r-m`, ícone lupa SVG 16px à esquerda, A→Z vira botão-ícone 36px. Chips de filtro (Todos/Atenção/Grave) = mesmo componente de chip da Fase 3.

### Fase 7 — Cockpit (`i_cockpit`)
Ordem e layout (celular, de cima para baixo):
1. **Herói "Economia potencial identificada"**: rótulo .8125 muted; valor 2.25rem mono 650 `--flame`; texto explicativo 2 linhas com "mais". Sem caixa alta.
2. **Grade de KPIs** (Fase 5): Radar de risco, Alertas, Pago a empresa morta, Compras auditáveis, Comunidades, Caro + suspeito, Órgão que mais economiza, Ninhos de fachada, Melhor detector.
3. **Núcleo/mesa holográfica**: **um** vídeo só (`nucleo-holo-rj` no celular como poster estático + play ao tocar; desktop autoplay muted loop) + o canvas do núcleo por cima. Remover o segundo vídeo (`video.mesa`) em v60. Altura 280 celular / 420 desktop. A pílula "alimentando · SEI · itkava · 14.329 lidos" vira legenda sob o card.
4. **Ticker** (`.ck-ticker`): mover para baixo do núcleo, velocidade −40%, fade nas bordas, pausa ao tocar; `prefers-reduced-motion` → lista estática de 3 itens.
5. Atividade ao vivo (holofeed recolhível — Fase 3).

Desktop: grid 12 colunas, `max-width:1280px`. Linha 1: herói (col 1–7) + núcleo (col 8–12, span 2 linhas). Linha 2+: KPIs em `repeat(auto-fill,minmax(220px,1fr))` nas col 1–7. Sem buracos (`grid-auto-flow: dense`).

### Fase 8 — Microinterações, som, estados
- Toda transição 150–220ms `--ease`; sem bounce. Troca de aba: crossfade 160ms do `#view`.
- Loading = skeleton com a forma do conteúdo (KPI/linha), shimmer só se não houver reduced-motion.
- Vazio/indisponível: manter as 2 ilustrações já geradas (consultou-e-não-achou vs fonte indisponível), centralizadas, 160px, texto 2 linhas.
- Sons (já existem, desligados por padrão): não mexer.
- Foco visível: anel 2px `--ion` com offset 2px em todo controle.
- Alvos de toque ≥ 44px no celular.

### Fase 9 — Verificação e virada
1. Prints com `V60=1` de **todas** as abas, celular e desktop:
   ```bash
   cd ~/JFN && uptime
   V60=1 nice -n 10 .venv/bin/python _SANDBOX/shot_painel.py "$(PYTHONPATH=. .venv/bin/python -c 'import tools.painel_abas as a; print(",".join(a.ids()))' 2>/dev/null || echo ',e_panorama,e_pericias,e_siafe,p_gastos,g_radar,g_casos,g_buscar')" v60_final "mobile,desktop"
   ```
   (Se `tools.painel_abas` não expõe `ids()`, extrair os ids de `TABS` em `static/js/src/entrada.js`.)
2. Comparar lado a lado com `aud_*` (antes). Checklist por print: (a) nada fixo cobre conteúdo; (b) só 2 fontes; (c) nenhuma linha/grade atrás de texto; (d) KPIs com mesma altura; (e) nenhum emoji de rating; (f) contraste ≥4.5:1 (rodar axe-core se disponível; senão checar `--muted` sobre `--card`).
3. Gates: `bash tools/precommit_painel.sh` verde; `.venv/bin/python -m pytest -q tests/test_painel_*.py` verde (eram 50); `painel_boot_check` sem `pageerror`; todas as abas abrem sem erro de console.
4. Performance celular (Playwright 390×844, CPU throttle 4×): nenhum long task > 200ms após boot; ≤ 1 vídeo tocando.
5. **Só se 1–4 passarem:** trocar o default da flag para `'1'` (`window.JFN_V60_DEFAULT='1'` no script inline), build, bump, commit `feat(painel-v60): ativa por padrão`. Escape: `/painel?v60=0`.
6. Escrever `docs/superpowers/specs/HANDOFF-painel-v60-2026-11-10.md`: o que mudou por fase, seletores anulados, prints antes/depois, como desfazer (`?v60=0`, ou `git revert` dos commits), pendências.
7. Atualizar `DESIGN.md` com um bloco topo "## v60 CLAREZA — VIGENTE" resumindo §3 e as regras: 1 camada ambiente, 2 fontes, sem Orbitron, rating sem emoji, esferas no rodapé no celular.

---

## 5. Relatório final (para o Mestre Jorge, curto)
Ao terminar, gravar em `_SANDBOX/v60_RELATORIO.md` (≤ 15 linhas, português simples):
- o que mudou (5 bullets), se ficou ativo por padrão, como desligar (`/painel?v60=0`), o que ficou pendente.
Sem jargão técnico, sem números inventados.

## 6. Se travar
- Seletor não encontrado → `grep -rn` em `static/css/src` e `static/js/src`; registrar no handoff, seguir.
- Gate falhou por carga da VM → esperar 5 min e repetir (não pular).
- Qualquer dúvida de produto → escolher a opção mais sóbria e legível, registrar no handoff. **Não parar para perguntar.**
