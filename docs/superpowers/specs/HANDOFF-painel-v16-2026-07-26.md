# HANDOFF — Painel JFN v15/v16 HOLO · 2026-07-26

## Estado: NO AR, debugado, sem regressão
Branch `feat/painel-v15-holo` · 6 commits · suite `6 passed, 0 falha` em cada etapa.
Site: `curl localhost:8000/painel` → 200 · funnel `https://jfn-core.tailbbe6c9.ts.net/painel` → 303 (redirect de login, correto).

## Commits
| hash | o quê |
|---|---|
| `dcb12512` | key-art de abertura: Gemini (anel) + Pollinations (horizonte Tron), mesclada |
| `5eb8953c` | **substituída pela do Firefly Image 5** — anéis usinados, flare anamórfico, cantos pretos limpos |
| `99c7ea32` | **camada v15 HOLO** — colchetes de canto traçados no hover, facho único, barra de energia na linha, pulso no chip ativo, facho sob a aba ativa |
| `4c5c12ab` | nebulosa **Estado** (ciano) — Firefly |
| `22a6449d` | nebulosas **Prefeitura** (âmbar) + **Transversal** (violeta) — Firefly |
| `27e37ce8` | **camada v16 SABRE VIVO** — sabre acende sob o KPI, holocron gira no ícone da aba, severidade pulsa por ritmo, varredura no cabeçalho, stagger com teto de 480ms |

## PENDENTE (ordem de valor)

### 1. ~~Arc reactor do núcleo~~ — FEITO (`ebe3cf69`, v17 Mark II: contra-rotação 14s x 9s, halo pré-borrado, `.sweep` acelera a máquina inteira, hover 3D, halo no núcleo do cockpit)

### 1b. PRÓXIMO: ícones + mapa RJ
O `#kyber` (linha ~174 do HTML) já é sofisticado: arcos `.karc`, trilho `.ktrk`, segmentos tracejados `.kseg`, núcleo `.knuc` com `knucGlow`, e modo `.sweep`. **Elevar para arc reactor Mark II**: anéis concêntricos contra-rotativos, núcleo que pulsa com a atividade real dos sweeps (já existe a classe `.sweep`), partículas orbitando, e o handoff do portal→kyber (já existe, ver `portalFim()` linha ~4440) ficar mais cinematográfico. **Onde mais faz sentido**: o reator central do mapa do RJ no cockpit (`i_cockpit`), e o ícone da aba ativa.

### 2. Mapa do RJ holográfico (task #8)
DECISÃO JÁ TOMADA: geradores **não acertam a geografia do RJ** (testado — Flux produz litoral genérico). Então: arte gerada = **mesa/ambiente** (anéis de radar, feixes de luz, brilho); contorno real continua vindo de `rj-malha.js` (IBGE) por cima, com tratamento holográfico. **Nunca falsear geografia em painel de auditoria.**
Arte da mesa já gerada e arquivada: `docs/referencias/keyart/gemini/mesa-projecao_1440.jpg`.

### 3. ~~content-visibility~~ — NAO SE APLICA (verificado 26/07)
O painel usa **um unico `#view`** cujo `innerHTML` e trocado a cada aba (linha ~1891).
Nao existem 51 containers no DOM, entao nao ha nos inativos para ocultar. O painel
JA FAZ o que o guia recomenda como ideal: "nunca monte o DOM das 51 abas".
**Minha recomendacao anterior partia de premissa errada. Fechado, sem acao.**

### 3b. ~~backdrop-filter~~ — DENTRO DO TETO (verificado 26/07)
Sao 4 seletores: `header`, `nav.tabs`, `.ov`, `.sheet`. Os dois ultimos sao modal/sheet
sob demanda, entao coexistem **2 a 3**, dentro do teto recomendado de 2-4. **Sem acao.**

### 3c. (obsoleto) content-visibility (task #10)
`content-visibility` = 0 ocorrências. Com 51 abas é a maior alavanca de perf (web.dev mediu 232ms→30ms, ~7×). Usar **`hidden`, não `auto`** — preserva estado de render, volta instantânea.
**BLOQUEIO**: a classe do container de aba não é `.tabc` (não existe). Achar a classe/estrutura real antes de aplicar — minha primeira tentativa virou código morto e eu removi.
**Gotcha**: chamar `offsetHeight`/`getBoundingClientRect` no conteúdo oculto anula o ganho.

### 4. backdrop-filter — auditar
10 ocorrências no arquivo; teto recomendado é 2–4 **simultaneamente visíveis** no mobile (cada um força readback+blur do backdrop composto por frame). Verificar quantos coexistem na tela.

### 5. Ícones (pedido explícito)
`static/assets/jfn-icones.js` — melhorar via Firefly/Express. Regra do guia: **espessura de traço idêntica no set inteiro**; nunca escalar ícone de 24→16 (traço vira 1,33px e borra).

## JÁ VERIFICADO — não precisa refazer
- **Sem halação**: `#000`/`#fff` aparecem só em `rgba()`/sombras, nunca como cor de texto ou fundo. O painel já acerta o ponto mais crítico do dark sci-fi.
- **`tabular-nums` presente** (6 ocorrências).
- Auditoria anterior do painel: **17/20 "Good+"**.

## COMO TRABALHAR (aprendido a duras penas)

**Acesso**: `ssh ubuntu@jfn-core` — usuário do projeto é `ubuntu`, NÃO `opc` (opc não lê /home/ubuntu, e não tem sudo).

**Regra dura do dono**: *toda* arte vem dos **geradores** (Firefly > Gemini > Pollinations). **Nunca compor imagem por código** (PIL/CSS) — ele reprovou explicitamente: "vai sempre sair ruim". Eu errei nisso uma vez e a diferença de acabamento foi gritante.

**Firefly (o melhor motor, conta premium)**: `firefly.adobe.com/generate/image` no Chrome logado via `mcp__claude-in-chrome__navigate`. Image 5 = 10 créditos, 16:9, 2K, aceita imagem de referência.
- **Gotcha**: a árvore de acessibilidade NÃO expõe o campo de prompt (`find` falha). Clicar no **texto do placeholder** por coordenada e digitar.
- Baixar: hover na imagem → ícone de download. Cai em `C:\Users\iterj\Downloads\Firefly_<prompt>.png`.
- Menu "..." tem **"Imagem para vídeo"** (image-to-video nativo), "Abrir no Photoshop na Web", "Abrir no Express".
- Doc Express existente: "JFN · Cockpit SABRE" `urn:aaid:sc:US:4e38c1f8-3bb0-45cb-bbc2-e85a34d3a124`.

**MCP Adobe**: NÃO faz text-to-image; backend de processamento estava fora em 26/07 (400 até com imagem pública). `animate_design` só opera em documento Express (motion de apresentação, não image-to-video). `export_html_to_express` é canvas fixo — **não serve para dashboard responsivo**.

**Teste (obrigatório, o dono exige)**: coder + humano a cada etapa.
```
cd ~/JFN && .venv/bin/pytest tests/test_painel_abas.py tests/test_painel_css_integro.py -q
.venv/bin/python _SANDBOX/shot_painel.py "e_pericias,g_radar" LABEL desktop   # abas via ir(id)
.venv/bin/python _SANDBOX/shot_portal.py LABEL                                 # portal (aparece ~400ms)
```
Saem em `screenshots/holo/`. Puxar com `scp` e **olhar** antes de seguir.

**Invariantes (os testes guardam)**: 51 abas, `i_cockpit` primeira, POR_ESFERA={inicio:1,estado:14,prefeitura:14,geral:22}. CSS: comentários e chaves balanceados — **nunca digitar os 2 chars de fecha-comentário dentro de um comentário** (engole o `@media` abaixo em silêncio). 4 strings-âncora vivas. **Camadas são ADITIVAS**: anexar no fim do `<style>`, nunca reescrever bloco antigo.

**A lição do v14**: foi revertido pelo dono porque cortava o canto de TUDO com clip-path e o rótulo longo quebrava letra-a-letra no celular. Decoração **não pode disputar espaço com texto** — por isso v15/v16 vivem em pseudo-elemento com `pointer-events:none`, fora do fluxo.

## Biblioteca de arte (VM1)
`docs/referencias/keyart/{firefly,gemini,pollinations,originais}/` — 25+ imagens. `originais/` guarda o que havia ANTES, para rollback e comparação.
`docs/referencias/design/ADOBE-MANUAL.md` — manual operacional (color grading, máscaras, grain/banding, Express).

Backups: `static/jfn-painel.html.bak-v15`, `_SANDBOX/painel.antes-v15layer.html`, `_SANDBOX/painel.antes-v16.html`.

---

# ATUALIZAÇÃO 26/07 (fim da sessão) — v17/v18/v19 entregues

| commit | camada |
|---|---|
| `ebe3cf69` | **v17 ARC REACTOR Mark II** — contra-rotação 14s×9s (anel só girando é spinner; dois opostos são mecanismo), halo pré-borrado animando opacity+scale, `.sweep` acelera a máquina inteira, hover 3D, halo no núcleo do cockpit |
| `bb53f07c` | **v18 GLIFO VIVO** — ícones se traçam na ignição, volume 3D no hover (8deg/6px — ícone é alvo de clique, se foge do cursor vira erro de mira), glifo da esfera ativa respira no MESMO período do kyber (3.4s), território pulsa + varredura de radar |
| `5d2ed910` | **v19 GRAMÁTICA** — caixa normalizada por CSS + **correção de regressão que eu causei na v18** |

## ⚠️ LIÇÃO CARA (não repetir)
`pathLength` é **ATRIBUTO SVG**, não propriedade CSS. Setar `pathLength:100` em CSS não faz nada, então o `stroke-dasharray:100` fixo cortou todo glifo com caminho > 100 unidades e **o ícone do cabeçalho sumiu**. Peguei no screenshot, não no teste — os testes não olham pixel. **Confirma a regra do dono: screenshot a cada etapa, sempre.** Correção: dasharray só existe DENTRO do @keyframes.

## PRÓXIMO: arte individual no Firefly (pedido explícito do dono)
Gerar **cada peça** no Firefly, não só fundos:
1. **Ícones** — 51 abas. Hoje são glifos Lucide (ISC) em `static/assets/jfn-icones.js` (mapa emoji→SVG paths). Gerar no Firefly como **SVG/vetor** ou PNG→`image_vectorize`. **Regra dura do guia**: espessura de traço IDÊNTICA no set inteiro; nunca escalar 24→16 (traço vira 1,33px e borra).
2. **Botões** — arte de estado (repouso/hover/ativo).
3. **Núcleo/reator e nós do mapa** — o dono quer muito melhores; hoje são SVG+canvas procedurais.
4. **Fonte sci-fi** — hoje IBM Plex Sans/Mono self-hosted em `static/assets/fonts/`. Candidatos do guia: **Orbitron** (feita como alternativa a Eurostile/Bank Gothic), **Chakra Petch**, Rajdhani. Baixar woff2, subsetar Latin+Latin-Ext (pt-BR precisa `ãõçáéíóúâêô`), `font-display:swap`, máx 3 arquivos. **Só para DISPLAY/labels — nunca em corpo ou tabela.**
5. **Onde há texto, pode haver arte** — cabeçalhos de aba e capas de seção.

**Fluxo Firefly** (validado nesta sessão): Chrome logado → `firefly.adobe.com/generate/image` → Image 5, 16:9, 2K → **clicar no TEXTO do placeholder por coordenada** (a árvore de acessibilidade não expõe o campo; `find` falha) → digitar → Gerar → hover → download → cai em `C:\Users\iterj\Downloads\Firefly_<prompt>.png`. Menu "..." tem **Imagem para vídeo**, Photoshop na Web, Express.
