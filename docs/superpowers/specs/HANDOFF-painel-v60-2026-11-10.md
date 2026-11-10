# HANDOFF — Painel JFN v60 "CLAREZA"

| | |
|---|---|
| **Data** | 2026-11-10 |
| **Brief executado** | `docs/superpowers/specs/BRIEF-painel-v60-clareza-2026-11-10.md` (fases 0 a 9) |
| **Branch** | `ui/painel-v60-clareza` (a partir de `ui/login-midia-som` @ `efad5e94`) — sem merge em `main`, sem force-push |
| **Estado** | 🟢 **ATIVO POR PADRÃO** desde `eb8d40d2` · escape: `/painel?v60=0` |
| **Serviço `jfn`** | não foi reiniciado (CSS/JS/HTML servidos do disco) |
| **Onde mora** | `static/css/src/99z-v60-clareza.css` (um estrato, 50 KB) + `static/js/src/ui/v60.js` (16 KB) |

> **Em uma frase:** o painel passou de 12 camadas de fundo, 3 fontes e navegação empilhada para
> 1 camada, 2 fontes, cabeçalho de 56/64 px, esferas no rodapé do celular, abas em chips, KPIs
> alinhados, listas em contêiner único e rating sem emoji — sem reescrever nenhum estrato antigo.

---

## 1. Como ligar, desligar e desfazer

| Quero… | Faço |
|---|---|
| Voltar ao painel anterior **neste aparelho** | abrir `/painel?v60=0` (grava `jfn_v60=0` no `localStorage`; vale até religar) |
| Religar o v60 neste aparelho | abrir `/painel?v60=1` |
| Desligar para **todos** sem apagar nada | em `static/jfn-painel.html`, trocar `window.JFN_V60_DEFAULT='1'` por `'0'` (1 linha) — ou `git revert eb8d40d2` |
| Remover o v60 inteiro | `git revert` dos 11 commits da §2, do mais novo ao mais antigo |

Conferido nos dois sentidos por `_SANDBOX/v60_flag.py`: padrão → `html.v60` presente; `?v60=0` →
ausente e persiste; `?v60=1` → volta. Sem a classe, **nenhum** seletor do estrato se aplica
(todos começam por `html.v60`) e todo JS novo sai no primeiro `if(!_v60)`.

**Fluxo de build (igual ao do brief, §0.8):**

```bash
cd ~/JFN
PYTHONPATH=. .venv/bin/python -m tools.painel_css_cortar --juntar   # se mexeu em static/css/src
nice -n 10 npm run build:painel                                     # se mexeu em static/js/src
PYTHONPATH=. .venv/bin/python tools/painel_bump_versao.py           # ?v= novo
bash tools/precommit_painel.sh                                      # gate; tem que sair 0
```

---

## 2. O que mudou, por fase

| Fase | Commit | O que mudou no olho | Seletores/funções anulados em v60 |
|---|---|---|---|
| 0 | `89941226` | nada (flag + estrato + tokens) | — |
| 1 | `87982736` | fundo calmo: 1 camada (`#esfnebula` em tela cheia a .45 sob scrim) | `#hologrid`, `#rjbg`, `#holorj`, `#netbg`, `.aura`, `#aurora`, `.cometa`, `canvas.view-wire`, `body::before` (textura), `body::after` (piso → vira scrim), `#modo-sobrio`; JS: `rjbgStart`, `netbgStart`, `_wire`, `energiaLigar`, `holoRJ` não iniciam laço |
| 2 | `579be0a5` | só Plex Sans + Plex Mono; sem caixa alta, sem letter-spacing | `--display` (Orbitron) remapeado; `text-transform`/`letter-spacing` zerados por `html.v60 *` |
| 3 | `03e905b9` | cabeçalho 56 px (celular) / 64 px (desktop); menu "⋯"; esferas no rodapé do celular; abas em chips sticky; holofeed recolhido | `.sph`, `nav.tabs`, `nav.tabs button` refeitos com `all:unset`; `.hlx`, `.onda`, `header::before`, `#kyber::before`, `.live .pulse::after` |
| 4 | `1b03a879` | capa de aba plana; descrição em 2 linhas com "mais"; "Gerar PDF" à direita | `.cover::before/::after`, `.cover-row::before/::after`, `.cover-seal::before/::after`; `.btn` refeito |
| 5 | `8bd9a8cd` | KPIs iguais, sem enfeite; cor só para severidade/dinheiro | `.kpi .v::after`, `.ck-inst .val::after` (barra-glow), `.ck-inst::after` (anel), `.ck-inst .dot` (ponto), `.kpi::before`, `.card::after`/`.kpi::after`, `.kpi-go::after`, `.kpi.rise::after`, `.kpi-ico` (só fica na crítica) |
| 6 | `b405789b` | listas em contêiner único, rating em ponto + rótulo, pills, tabelas, filtros | `.card::before/::after`, `h2.sec::before/::after`, `tbody tr::after`, `.meter::after`, `.chip::before/::after`, `.search .az::before/::after`; emojis 🔴🟡🟢🟠⚪ trocados na renderização |
| 7 | `61d9d222` | cockpit: herói → 9 KPIs → núcleo → ticker → atividade | `.ck-orbita` (vira `display:contents`), `.ck-hero::before/::after`, `.ck-nucleo::before`, `video.mesa` (não é criado), `#nu-chips` |
| 8 | `25a53e59` | crossfade na troca de aba, esqueleto no carregamento, foco, toque ≥44 px, `#sheet` sóbrio | `.fade::before` (lâmina), `#view > .fade > *::before/::after` (trilho + pulso), `.grid::before/::after` (barramento), `.skel .sp` |
| 9 | `16a1f527` | links legíveis; troca de aba sem View Transition; sem blur atrás de KPI no celular | `filter:saturate` do fundo; `startViewTransition` não é chamado em v60 |
| 9 | `eb8d40d2` | **v60 por padrão** | — |

Prints por fase em `screenshots/holo/` (pasta fora do git, como sempre): `aud_*` = **antes**
(auditoria da outra sessão), `v60_f1_*` … `v60_f8_*` = cada fase, `v60_final_<view>_<aba>.png` =
**depois**, todas as 68 abas nas duas larguras; `v60_escape_mobile_cockpit.png` = o escape `?v60=0`.

### 2.1 O que entrou de JavaScript

| Arquivo | Mudança | Guarda |
|---|---|---|
| `capacidade/estado.js` | `export const _v60` (lê a classe que o script inline do `<head>` grava) | — |
| `ui/v60.js` (novo) | `v60Boot` (1º passo do boot): subtítulo sem caixa alta, botões-ícone e "⋯", holofeed "Ao vivo · N", **passe pós-render** (`v60Vivo`) por `MutationObserver` no `#view` e no `#sheet` | `if(!_v60) return` |
| `cena/fundo.js`, `cena/energia.js`, `ui/index.js` | laços de canvas não iniciam | `if(_v60)` |
| `cena/index.js` | nebulosa só poster no celular/`saveData`; `holoRJ` e `mesaViva` não rodam; núcleo no celular = poster + toque; mesa sem chips; `NUCLEO_COM_POSTER` ganhou `nucleo-holo-rj` | `_v60` |
| `abas/cockpit.js` | grade de 9 com **Alertas**; `ckFill('alertas', …)` | `_v60` (o `ckFill` sai sozinho sem o cartão) |
| `nucleo/dom.js` | 5 abas sem glifo apontam para SVG existente | classe `v60` |
| `entrada.js` | `v60Boot()` no início do boot; chip ativo centrado; sem View Transition | `_v60` |

O passe `v60Vivo` é **idempotente** (a segunda volta não altera nada, então não se realimenta) e faz
seis coisas: sobe a barra do PDF para a capa, mede se a descrição passa de 2 linhas, grava `--n`
nos valores do cockpit, troca emoji de rating por ponto, marca as listas e veste pills/lupa.

### 2.2 Um asset novo

`static/assets/nucleo-holo-rj.jpg` (46 KB) — **quadro do próprio vídeo** `nucleo-holo-rj.mp4`
(`ffmpeg -ss 2 -frames:v 1`), não arte nova. É o poster do núcleo no celular. Foi anotado em
`NUCLEO_COM_POSTER` porque `tests/test_painel_assets.py` exige lista = disco; efeito colateral
declarado: com `?v60=0` o núcleo do Início/Estado também passa a ter poster enquanto o vídeo carrega.

---

## 3. Verificação (fase 9) — o que foi medido

### 3.1 Checklist das 68 abas × 2 larguras (`_SANDBOX/v60_auditoria.py` + `v60_resumo.py`)

| Item | Celular 390×844 | Desktop 1600×1000 |
|---|---|---|
| `pageerror` / erro de console | 0 em 68 abas | 0 em 68 abas |
| (a) elemento fixo sobre o conteúdo | só as esferas (rodapé) | só a pílula do holofeed (canto) |
| Topo ocupado (cabeçalho + chips) | 56 px (Início) / 100 px | 64 px (Início) / 104 px |
| Início do conteúdo | 68 / **112** / 136 px ¹ | 84 / 124 / 148 px ¹ |
| (b) famílias de fonte | IBM Plex Sans, IBM Plex Mono | IBM Plex Sans, IBM Plex Mono |
| (c) camadas ambientes visíveis | nenhuma | nenhuma |
| (c) `<canvas>` | 1 (`nucleo-cv`, só no cockpit) | 1 (`nucleo-cv`, só no cockpit) |
| (d) KPIs medidos / linhas desiguais | 232 / nenhuma | 232 / nenhuma |
| (e) emoji de rating no texto visível | 0 | 0 |
| (f) textos abaixo de 4,5:1 ² | 0 de 46.338 | 0 de 46.658 |
| Overflow horizontal | nenhum | nenhum |

¹ 136/148 px = abas cujo render começa com um bloco de margem própria (ex.: `e_siafe`, sem capa).
² Medido no DOM: cor do texto × fundo composto pelos ancestrais. **Não** enxerga imagem/vídeo de
fundo — por isso o scrim da fase 1 importa. `axe-core` não está instalado; `tools/auditar_contraste.py`
(CDP, por pixel) **não foi rodado**: é longo e o próprio handoff v27 registra que ele quebra nas 51+ abas.

### 3.2 Gates

| Gate | Resultado |
|---|---|
| `tests/test_painel_*.py` | **121 passed, 4 skipped** (igual à linha de base desta sessão; o brief citava 50) |
| `bash tools/precommit_painel.sh` | `rc=0`, com a camada viva (`painel_boot_check`) rodando |
| `painel_boot_check --todas`, já com v60 por padrão | **68 abas percorridas sem erro** |
| `painel_css_cortar --check` / `painel_bump_versao --check` / `painel_modulo_livre` | em dia |

Nos commits das fases, o hook de pre-commit **pulou** a camada viva quase sempre (`load > 3` — o
próprio hook sobe a carga). A cobertura veio da auditoria da §3.1 e do `boot_check --todas` final.

### 3.3 Desempenho (celular 390×844, CPU 4× mais lenta, Chromium **sem GPU** da VM)

| Medida (`_SANDBOX/v60_perf.py`) | v60 (2 rodadas) | Painel anterior |
|---|---|---|
| Tarefas longas em 30 s de repouso após o boot | 5 e 3 | 132 |
| …acima de 200 ms | **nenhuma** (máx. 175 e 181 ms) | 5 (máx. 1.091 ms) |
| Vídeos tocando | 0 | 0 |
| Tarefas longas ao trocar de aba (2 trocas) | 18 e 20 | 69 |
| …acima de 200 ms | 5 e 4 (máx. 962 e 1.106 ms) | 25 (máx. 1.723 ms) |

> ⚠️ **Ressalva honesta.** O critério do brief ("nenhuma tarefa longa > 200 ms após o boot; ≤ 1 vídeo
> tocando") foi atendido **em repouso**. **Na troca de aba** ainda há picos acima de 200 ms. O perfil
> de CPU (`_SANDBOX/v60_prof.py`) mostra que é pintura por software: o JavaScript do v60 soma menos
> de 150 ms em 36 s; o resto é `(program)`. O handoff v27 já registrou que esta VM (SwiftShader, sem
> GPU) infla esses números em relação ao Chrome real. **Não foi medido em celular de verdade** — é a
> pendência nº 1. A virada foi feita porque o v60 é mais leve que o painel que estava no ar em todas
> as medidas; quem discordar da leitura desfaz em uma linha (§1).

---

## 4. Decisões tomadas sem perguntar (regra §6 do brief: a mais sóbria e legível)

| # | Decisão | Por quê |
|---|---|---|
| 1 | Rótulo de KPI pode ir a **2 linhas no celular** (o brief pedia 1 linha com reticências) | em 2 colunas de 166 px, "Órgão que mais econo…" perdia o sentido |
| 2 | KPI com valor de 17+ caracteres ocupa as **2 colunas** no celular | "R$ 141.532.323.112,11" encolhia até 10 px |
| 3 | Trilho de chips com **44 px** no celular (o brief dizia 40) | alvo de toque ≥ 44 px da fase 8; o conteúdo ainda começa em 112 px |
| 4 | Esmaecimento das pontas do trilho por **elemento sticky**, não `mask-image` | a máscara deixaria o conteúdo aparecer por baixo das pontas |
| 5 | `.gl` do KPI continua oculto | é um emoji-glifo decorativo, não a "nota" que o brief imaginava |
| 6 | **Chips-rótulo da mesa de vigília saem** | repetiam os 7 números da grade ao lado e cobriam o mapa no celular; a grade ganhou **Alertas** para nenhum número sumir |
| 7 | Botão de som segue com ponto + texto no desktop | não há glifo de alto-falante no set, e a regra 7 proíbe desenhar ícone |
| 8 | "⋯" é desenhado com três pontos em CSS | não depende de glifo de fonte (lição do v27 sobre cobertura) |
| 9 | Sem blur atrás do KPI **no celular** | era o item mais caro de pintar; com `--card` a .82 o resultado é o mesmo |
| 10 | Troca de aba = fade em CSS, **sem View Transition** em v60 | a transição fotografa a tela inteira; o efeito pedido é só o crossfade |
| 11 | Cinco abas (Lentes, Casos, Requerimentos, Acervo, LAI) usam glifo existente "de sentido próximo" | não tinham SVG e caíam no emoji; desenhar ícone novo é vetado |
| 12 | Cabeçalho de tabela só gruda no topo a partir de **1100 px** | abaixo disso a tabela rola dentro do cartão, e os dois não convivem |
| 13 | "MESMA SALA" / "DEPOIS" seguem em maiúsculas dentro das frases | é ênfase de texto corrido, não rótulo |

---

## 5. Avisos do GitNexus (regra do `CLAUDE.md`)

`impact` acusou **HIGH/CRITICAL** em `rjbgStart`, `netbgStart`, `_wire`, `nebulaViva`, `holoRJ`,
`nucleoStart`, `svgIco` — todos no caminho do boot ou usados por dezenas de fluxos. A mitigação é a
mesma em todos: a mudança é **um retorno antecipado sob `_v60`**; sem a classe, o caminho antigo
é o de sempre. `detect-changes` foi rodado antes de cada commit (fase 2: *critical*, por causa de
`svgIco`; demais: *low*).

---

## 6. Pendências

1. **Olhar em celular e Chrome reais.** Tudo aqui foi visto em Chromium headless sem GPU. Em especial:
   fluidez na troca de aba, `env(safe-area-inset-bottom)` no iPhone e o toque-para-tocar do núcleo.
2. **Nós da mesa sem rótulo.** Com os chips fora, cada ponto de luz do mapa perdeu o nome. Os números
   estão na grade; falta decidir se a mesa ganha uma legenda curta.
3. **Ícones aproximados** nas 5 abas da decisão 11 e nos 3 botões do cabeçalho (`§info`, 🔧, 🚪). Se
   o set ganhar glifos próprios (inclusive alto-falante), trocar em `_ICO_V60` (`nucleo/dom.js`) e
   `_ACOES` (`ui/v60.js`).
4. **Estilos `style="…"` nos renders.** O v60 venceu vários por seletor de atributo ou `!important`
   (6 declarações no estrato). Limpar na origem é trabalho de `abas/*.js`, fora deste brief.
5. **Telas não revisadas uma a uma no olho.** As 68 passaram no checklist automático e ~15 foram
   vistas em print; as demais podem ter resto de estilo antigo em componentes raros (formulários do
   Validar/LAI, gavetas de drill).
6. **`/controle`** carrega o mesmo CSS mas não tem a classe `v60` — segue com o visual antigo, de propósito.
7. `data/*`, `AGENTS.md`, `CLAUDE.md` e os demais arquivos alheios modificados **não foram tocados nem commitados**.

---

## 7. Ferramentas desta sessão (em `_SANDBOX/`, fora do git)

| Script | Para quê |
|---|---|
| `shot_painel.py` | harness de sempre; agora aceita `V60=1` / `V60=0` e imprime `PAGEERROR` |
| `v60_probe.py <view> <aba> <js> [print]` | abre o painel autenticado, avalia JS, tira print |
| `v60_auditoria.py <view> [abas]` | checklist (a)–(f) + print de todas as abas → `v60_auditoria_<view>.json` |
| `v60_resumo.py <view>` | resume o JSON da auditoria |
| `v60_fonts.js` | auditoria de fontes de uma tela |
| `v60_perf.py` / `v60_prof.py` | tarefas longas e perfil de CPU com throttle 4× |
| `v60_flag.py` | confere a flag nos dois sentidos |
| `v60_espera.py` | espera o load cair abaixo de 3 (regra §0.4) |
