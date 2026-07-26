# HANDOFF — Painel JFN v23→v26 · arte gerada peça a peça · 2026-07-26 (2ª sessão)

Continuação de `HANDOFF-painel-v16-2026-07-26.md`. Branch `feat/painel-v15-holo`.
Site NO AR: `curl localhost:8000/painel` → **200** · funnel → **303** (redirect de login, correto).
Suíte guardiã (`test_painel_abas.py` + `test_painel_css_integro.py`) → **6 passed** em cada etapa.

## O que entrou (4 commits)

| commit | camada | o que muda no olho |
|---|---|---|
| `c14b764a` | **v23 CARCAÇA REAL** | o reator do cockpit ganha corpo fotográfico (Firefly Image 5) por baixo dos anéis procedurais |
| `2eea4530` | **v24 MESA REAL** | a mesa deixa de ser gradiente e vira placa de vidro usinada com anéis de radar gravados |
| `1baaef75` | **v25 SELO USINADO** | o selo da capa da aba ganha bisel usinado atrás do glifo vivo |
| `54a2d516` | **v26 TRILHO** | a linha sob o título da aba vira barra de instrumento com lâmina de luz |

**Princípio que guiou tudo:** *a arte dá o CORPO, o código dá a VIDA.* Nenhuma camada
substituiu o procedural — cada uma entrou como textura por baixo. Só o código sabe a
carga real da VM, o sweep ativo e a matiz da esfera; a arte não sabe nada disso.

## Assets novos (`static/assets/`)

- `reator-core.webp` (128 KB, RGBA) — arc reactor. **Piso de preto + vinheta de alfa**: em
  composição aditiva (`globalCompositeOperation='lighter'`) o véu de quase-preto da arte
  somava e desenhava um QUADRADO visível em volta do reator.
- `mesa-projecao.jpg` (91 KB) — placa de vidro. No desktop entra a **190%**
  (`@media min-width:900px`): a caixa tem quase a proporção da imagem e em `cover` a
  aresta reta da placa cortava o território como um risco fora de lugar.
- `selo-anel.webp` (13 KB, RGBA) — medalhão usinado, dessaturado a 25% no CSS
  (metal é incolor → o mesmo asset serve às 4 esferas sem brigar de matiz).
- `trilho-hud.jpg` (22 KB) — canal de luz. **Recorte defensivo**: o gerador escreveu
  numerais falsos nas faixas de cima e de baixo da peça; a fatia usada é só o canal de
  luz e nenhum dígito sobreviveu. Em painel de auditoria número inventado é inaceitável
  mesmo ilegível.

Originais 2K arquivados em `docs/referencias/keyart/firefly/`.

## DUAS COISAS REPROVADAS (com evidência — não repetir sem motivo novo)

### 1. Ícones raster no lugar dos 51 glifos — REPROVADO
Duas gerações no Firefly (grid 4×4 de pictogramas; a segunda com prompt "monoline,
outline only, no fills, same stroke weight, Feather/Lucide style"): **as duas saíram com
forma preenchida, espessura desigual e símbolos que não batem com o rótulo.** Reprova
pela regra dura do guia (traço idêntico no set inteiro) e a 16–24px viraria borrão.
**Os glifos de linha ficam.** A arte foi aplicada onde raster de fato ganha: o selo de
48–54px (v25).

### 2. Placa de botão gerada — REPROVADO
Duas gerações; a segunda com "flat orthographic top-down, zero perspective, no vanishing
point": **as duas saíram em perspectiva.** 9-slice de render em perspectiva enviesa a
borda em todo tamanho, e controle de largura variável estica raster. Os botões seguem
com colchetes de canto + sweep + spotlight (v15) — a técnica certa para tamanho variável.
**Se quiser insistir:** o único asset com forma compatível é o `trilho-hud.jpg` (faixa
horizontal — estica só na horizontal, sem canto para distorcer), num pseudo livre do
estado ativo. `.chip.on::after` e `.btn.primary::after` já estão ocupados.

## A ARMADILHA QUE CUSTOU MEIA HORA

Patch por `ssh vm "python - heredoc"` com aspas **duplas** por fora: o shell LOCAL come
as aspas vazias, e `content:""` chegou na VM como `content:;`. CSS inválido → o
pseudo-elemento nunca foi gerado, e a camada ficou invisível **com a suíte toda passando**.

- Sintoma: `getComputedStyle(el,'::before').content === 'none'`.
- Regra: patch por ssh usa heredoc com aspas **simples** por fora, ou escreve os dois
  chars via `chr(34)*2` em Python.
- E o diagnóstico que fecha a questão é ler o computed style — não olhar o screenshot e
  ficar chutando opacidade (foi o que eu fiz por duas iterações).
- Corolário: documento com heredoc dentro **não** vai por `ssh <<MD`; escrever local e `scp`.

## Método que se confirmou de novo

- **Screenshot a cada etapa é o único detector.** Duas vezes nesta sessão os testes
  passaram com a camada quebrada.
- Harness: `_SANDBOX/shot_painel.py "abas" LABEL desktop,mobile` (viewport).
  **Não usar `full=1`** para o cockpit: em full_page o canvas re-layouta e sai vazio.
- Diagnóstico de camada: screenshot com a camada de cima escondida
  (`#nucleo-cv{display:none}`) injetada via `page.add_style_tag`.
- Fluxo Firefly (Chrome logado): clicar no TEXTO do prompt por coordenada (a árvore de
  acessibilidade não expõe o campo), `ctrl+a`, digitar, Gerar, hover na linha → **Baixar**
  no cabeçalho da linha. Cai em `C:\Users\iterj\Downloads`.

## Benchmarks pesquisados (referência de linguagem, não de código)

- **ARWES** (`arwes.dev`) — framework sci-fi de UI web; influências declaradas Star Citizen,
  Halo, TRON: Legacy. É o benchmark vivo mais próximo do que este painel faz.
- **SciFiCN UI**, **Holo (Vue 3)** — sistemas de HUD/painel tático em componente.
- **GMUNK / Territory Studio** — FUI de cinema. A regra que se aplica aqui: linhas finas e
  nítidas, composição limpa, tudo alinhado a uma grade. É por isso que a arte gerada entra
  como CORPO e a grade continua sendo do código.

## Pendente

1. **Nós do mapa** (`.nu-chip` e os pontos de luz) continuam procedurais — era a outra
   metade do item "núcleo/reator e nós do mapa".
2. Botão: só com o trilho, ver a seção de reprovação.
3. Auditoria CDP de contraste (`tools/auditar_contraste.py`, 51 abas) é longa; rodar até
   o fim e conferir ≥4.5:1.

---

# ANEXO — auditoria de fecho (2026-07-26)

## Site
`curl localhost:8000/painel` → **200** · funnel `https://jfn-core.tailbbe6c9.ts.net/painel` → **303**.

## Suíte
- Guardiãs (`test_painel_abas.py` + `test_painel_css_integro.py`): **6 passed** em cada uma das 4 etapas.
- Suíte completa: **2762 passed, 2 failed, 7 skipped, 7 errors** em 18m51s.
  Os **7 errors** são `tests/test_auditor_contraste.py` — eu estava rodando
  `tools/auditar_contraste.py` em paralelo e os dois disputam a mesma conexão CDP em
  `:9222` (`RuntimeError`). **Não rodar os dois juntos.**
  As 2 falhas são `test_catraca_excepts.py::test_except_exception_nao_cresce` e
  `test_lex_snapshot.py::test_parecer_lex_snapshot_identico` — **pré-existentes e sem
  relação com o painel**: o diff desta sessão (`git diff 9866933e..HEAD --name-only`) não
  tocou em nenhum `.py`, só em `static/jfn-painel.html`, 4 assets e a documentação.

## Contraste (CDP, WCAG 2.1) — 4 padrões abaixo de 4.5:1

Medido em `i_cockpit`, `e_pericias`, `g_radar` (`tools/auditar_contraste.py <abas>`):

| razão | tam | aba | classe | texto |
|---|---|---|---|---|
| **2.04:1** | 10px | i_cockpit | `hfload` | "load 5.08 · ram 30%" |
| **3.12:1** | 10px | e_pericias | `hf-t` | "holofeed" |
| **3.90:1** | 9.5px | i_cockpit | `nu-legend` | "Mesa de vigília · cada feixe" |
| **4.45:1** | 12px | g_radar | `dim` | "Score 0-100 somando sinais" |

**São PRÉ-EXISTENTES, não regressão das camadas de arte.** Verificado por medição direta:
screenshot do `#ck-nucleo` com e sem `.ck-nucleo::before`, amostrando o fundo real sob a
legenda — **7.06:1 sem a mesa · 7.05:1 com a mesa** (Δ 0.01). A arte entra em `screen`
sobre região já escura: soma luz onde a arte é clara, e ali ela é quase preta.
As três primeiras são texto de 9.5–10px, onde o mínimo é o mais duro de atingir.

**Correção sugerida (não aplicada — fora do escopo de arte, e cada verificação custa
minutos de auditoria):** subir `hfload`, `hf-t` e `nu-legend` para um cinza com ≥4.5:1
sobre o fundo do cartão. `hfload` a 2.04:1 é o mais grave.

## Bug do próprio auditor (pré-existente)
`tools/auditar_contraste.py` nas 51 abas **quebra**:

```
File "tools/auditar_contraste_pixel.py", line 374, in medir_pagina_atual
  laudo.append(_veredito(alvos[x["cpx"]], ...
KeyError: 30
```

Passar as abas explicitamente contorna. Enquanto isso não for corrigido, não existe laudo
das 51 abas — só por lote.

---

# v27 — systematic-debugging aplicado aos bugs relatados (2026-07-26)

Skills baixadas da VM (`~/.claude/plugins/cache/claude-plugins-official/superpowers/6.2.0/skills/`)
para `~/.claude/skills/` no desktop: `brainstorming`, `systematic-debugging`.

## O erro de método que a Fase 1 evitou

Medi a abertura no **Chromium headless da VM** e achei `domready=2850ms`, uma long task de
**2381ms** e **3 quadros em 4,5s**. Ia "otimizar" o painel.

Antes disso medi no **Chrome real do dono** (24 CPUs, 32 GB, dpr 1.5):
`ttfb 74ms · domInteractive 217ms · load 612ms · maior long task 56ms`.

**A página não é lenta.** Os 2,4s eram SwiftShader — a VM não tem GPU. Se eu tivesse
"consertado" o que medi na VM, teria mexido no que não estava quebrado.
*Diferença de ambiente é item 3 da Fase 1 por um motivo.*

## Os três bugs, com a medição de cada um

### 1. "letras estranhas"
Cobertura medida por canvas nas três fontes embarcadas:

| fonte | não tem |
|---|---|
| Orbitron (display) | `· → ↔ ₂ º ª § ✓ ✗` |
| IBM Plex Mono | `✗` |
| IBM Plex Sans | `✗` |

**Nenhuma das três tem U+2717 (`✗`)** — com o SIAFE fora do ar o cabeçalho renderizava um
caractere de sistema. E `✓` a 10px com letter-spacing largo **lê como a letra "v"** (era
isso que aparecia em `SIAFE ✓ · 2026`).
**Fix:** estado de sistema virou **sinal** (ponto verde/vermelho com `aria-label`), que não
depende de fonte. `A→Z ✓` e `identidade ✓` viraram palavra. `unicode-range` trava o
Orbitron no que ele cobre de fato.

### 2. "ícones que quando clica ficam pequenos"
Medido 3s **depois** do clique, na aba ativa:
`transform: matrix3d(-0.8, 0, 0, 0, 0, 0.8, ...)` — **espelhado no X e 20% menor**,
com a animação em `running` e **`currentTime` travado em 0**.

Hipótese H1 (a nav é recriada em laço, reiniciando a animação) → **REFUTADA**:
0 nós adicionados, 0 mutações em 5s.

Causa real: `@keyframes v16holo{from{transform:rotateY(-180deg) scale(.8)}}` — o **quadro
inicial** encolhia e espelhava justamente o alvo de clique, e é nele que a animação
congela em qualquer engasgo de quadro.
**Fix:** a entrada agora vem de **maior e mais aceso** (`rotateY(-34deg) scale(1.16)`,
`brightness(2.1)`). Medido depois: **17,5×21,5 contra 19,6×17,9 dos inativos** — congelar
ali lê como "ligado", nunca como defeito. Sem escala < 1, sem espelhamento em instante nenhum.

### 3. "demorando a fazer tudo"
Não é carga (load 612ms). Era o **portal**: `FIM=3520ms` + `760ms` de saída = **4,3s de
espera obrigatória** toda abertura. Agora **1960 + 420**.

## O que mais entrou

- **Abertura 3D angulada** (Firefly Image 5): reator massivo em três quartos, carcaça com
  espessura, anéis de plasma em ângulos diferentes. O shader desenhava um disco azul
  chapado bem em cima do núcleo incandescente da arte — máscara radial abre um furo no
  `#pcv` exatamente ali, e do procedural sobra o que ele faz bem.
  *Gotcha:* o furo precisou de duas tentativas — o primeiro raio (`42%` de 158px = 66px)
  era menor que o blob (~90px) e não mudou nada na tela.
- **Tato em todo controle.** O painel tinha `:hover` em tudo e `:active` em nada — e hover
  não existe no celular, então **no telefone o painel era mudo ao toque**. Agora: afunda
  1px, onda de luz nasce onde o dedo tocou, linha acionada carimba a cor da esfera.
  UM listener delegado no documento (o `#view` troca de innerHTML a cada aba: listener por
  elemento morreria junto), em `pointerdown` e não `click` — resposta no toque.
  Verificado: `.onda` presente, 138px, `animationName: ondaAbre`, `:active` aplicado.

## Continua pendente (dito com clareza)

- **Ícones "feios"**: continuam sendo os glifos de linha. Duas gerações no Firefly foram
  reprovadas com evidência (forma preenchida, espessura desigual). Text-to-image **não**
  produz sistema de ícone com traço uniforme. Caminho real: desenhar o set com traço único
  ou vetorizar em ferramenta de traçado, não em gerador.
- **Movimento no conteúdo das dezenas de abas**: entrou o tato (toque/clique em todos os
  controles). A entrada em cascata dos cards por aba usa o stagger v16 e **não foi
  auditada aba a aba** nesta sessão.
