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
