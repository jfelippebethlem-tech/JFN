# Manual operacional — Adobe (Photoshop/Lightroom + Express) via API/MCP
### Nível web designer profissional · destilado 2026-07-26 para o painel JFN

> Fonte: schemas reais da API Adobe conectada + literatura de color grading.
> Guardado aqui porque o backend de imagem da Adobe (`bartlebee...adobe.io/api/v1/image/encode`)
> estava FORA em 2026-07-26 (400 até com imagem pública). Quando voltar, aplicar isto.

---

## 0. REGRAS DE OURO

- **`asset_inline_preview` ANTES de `image_apply_adjustments`** — obrigatório pelo schema, inclusive em outputs intermediários. Sem olhar, os valores são chute.
- **`outputFileType: "png"`** em toda etapa intermediária (lossless + alpha). JPEG só no deliverable.
- **Encadeamento**: cada tool devolve `outputUrl`/`presignedAssetUrl` → é o input da próxima. Exceto crop, que sempre parte do ORIGINAL.
- **Grupos atômicos** (todos os campos juntos ou nenhum): `tempA`+`tempB`+`tempLuminance` · `hslHue`+`hslSaturation`+`hslLightness` · `channelTarget`+`channelSaturation`.
- **NÃO existe neste ambiente**: geração de imagem, generative fill, remoção de objeto, troca de fundo por prompt, compositing, upscaling, OCR. Única exceção generativa: `image_generative_expand` (outpaint).

---

## 1. COLOR GRADING CINEMATOGRÁFICO

### 1.1 Ordem das operações (inverter é o erro nº1)
1. **Base tonal** — `image_apply_auto_tone` (PULE em arte de IA: ela já vem graded e o auto-tone achata)
2. **Exposição global** — `exposure`, `gamma`
3. **Regiões tonais** — `highlights`, `lights`, `darks`, `shadows`
4. **Temperatura** — `tempA`+`tempB`+`tempLuminance`
5. **HSL / canal** — `hslHue`+`hslSat`+`hslLight`, `channelTarget`+`channelSaturation`
6. **Vibrance/Saturation**
7. **Grain** — SEMPRE por último no pipeline de cor
8. **Crop/resize** — depois do grain (resize reamostra e mata o grão)

> Atalho: etapas 2–6 podem virar UM `image_apply_preset`. **Nunca empilhe presets** — preset é look completo, não filtro aditivo.

### 1.2 CIELAB decodificado (a parte mais mal compreendida)
```
tempA = VERDE(−) ↔ MAGENTA(+)  → é o TINT
tempB = AZUL(−)  ↔ AMARELO(+)  → é a TEMPERATURA
tempLuminance = 0–100, 50 neutro
```
**Aquecer exige `tempA` POSITIVO** porque ele é o contrapeso que impede o amarelo de virar cast verde (amarelo puro em Lab fica perto do verde).

| Objetivo | tempA | tempB |
|---|---|---|
| Âmbar / golden hour | +20 | +70 |
| Sépia vintage | +15 | +55 |
| **Teal cinematográfico** | **−15** | **−70** |
| Azul frio / sci-fi noturno | +10 | −80 |
| Verde clínico (Matrix) | −30 | −20 |

> **Teal NÃO é só "azul negativo".** Teal = azul + verde → os DOIS negativos. `tempA` positivo + `tempB` negativo = azul-violeta.
> Em cores já muito saturadas (neon, arte de IA vívida) os shifts Lab são absorvidos → use `hslHue`.

### 1.3 Teal & orange — receita (não há split-toning na API; faz-se por máscara)
```
1. Base (imagem inteira): gamma 0.9, contrast 25, highlights −15, darks −20, shadows −15
2. image_select_subject → maskSujeito
3. Sujeito QUENTE (maskSujeito): tempA 20, tempB 70, tempLuminance 55, vibrance 20
4. image_invert_selection → maskFundo
5. Fundo TEAL e recuado (maskFundo): tempA −15, tempB −70, tempLuminance 45, darks −25, saturation −10
6. Cirurgia de canal (inteira, 2 chamadas):
   channelTarget "cyan"  + channelSaturation  30
   channelTarget "green" + channelSaturation −35   ← O SEGREDO
```
> Matar o verde é o que separa "look de LUT" de "foto com filtro".

**Presets prontos** (via `image_list_presets`):
- `Style: Futuristic - FT04` — frio, clínico, shadows levantadas. O mais direto p/ sci-fi.
- `Creative - Cool Shadows & Warm Highlights` — literalmente teal&orange split-tone. **Começar aqui.**
- `Creative - Turquoise & Red` — versão agressiva.
- `Style: Cinematic II - CN11` — quando o azul é o herói.

### 1.4 Escurecer fundo SEM matar o glow  ← CRÍTICO p/ nossa arte de anel
> **`highlights` negativo MATA o glow. `darks`/`shadows` negativos não.**

```
❌ exposure −1.0 · highlights −60 · brightness −40
✅ gamma 0.75 · darks −35 · shadows −30 · highlights 0 · contrast 20
```
`gamma` age na curva de MIDTONES: afunda o fundo e deixa o pico do glow onde está → a razão de contraste glow↔fundo AUMENTA (definição perceptual de "brilhar mais").

**Nível 2 (glow ganha força):** `select_by_prompt "the glowing light ring"` → invert → fundo `gamma 0.7, darks −40` / anel `lights 25, vibrance 30`.

**Limites de segurança:** `exposure` ±0.5–1.5 (>±2.0 estoura) · `gamma` 0.5–2.0 (fora de 0.3–3.0 destrói) · `exposureOffset` HIPERSENSÍVEL (±0.02 já visível) · `darks`>50 lava · `shadows`>50 + darks alto = chapado.

---

## 2. MÁSCARAS

- `image_select_subject` — sujeito único · `image_select_by_prompt` — objeto nomeável/múltiplos · `image_invert_selection` — quando o alvo é o fundo
- **`select_by_prompt` NUNCA aceita "the background"** / "everything except X". Fundo é SEMPRE 2 chamadas: select subject → invert.
- **`remove_background` NÃO é máscara** — devolve PNG com alpha. Como `maskURI` quebra a polaridade. Recortar → `remove_background`; ajustar → `select_subject`.
- **Aceitam `maskURI`**: `apply_adjustments`, `add_grain`, `add_noise`, `gaussian_blur`, `halftone`, `glitch`, `monochromatic_tint`, `fill_area`.
- **NÃO aceitam**: `lens_blur` (detecção embutida — não encadeie máscara antes), `color_overlay` (e não tem `opacity` → use `fill_area`), crops, `vectorize`, `apply_preset`.

**hslHue relativo:** `shift = alvo° − origem°`, trazer p/ −180…180. Ref: red 0, yellow 60, green 120, cyan 180, blue 240, magenta 300. Ex.: azul→ciano = 180−240 = **−60**.

**`colorize: true`** → hue vira ângulo ABSOLUTO. Só em fonte multicolor/listrada/neutra/cinza/branca. Nunca em objeto com cor base clara.
**`targetColor`** → só p/ ajuste fino dentro de UMA família (<90°). NUNCA ao recolorir p/ outra família — sai manchado (sombras/reflexos ficam fora da banda).

---

## 3. GRAIN E BANDING  ← ESSENCIAL para nossa arte (nebulosa escura + glow)

8 bits = 256 níveis/canal. Gradiente escuro suave precisa de mais → **banding**.
**Piora depois do grading**: `gamma`/`contrast`/`darks` ESTICAM a região escura (20 níveis reais espalhados por 60 de saída → 40 interpolados). Quanto mais agressivo o grade, mais obrigatório o grain.
Grain = dithering: ruído de ±1 nível quebra a borda determinística da faixa; o olho integra a média.

> **Regra dura: todo gradiente escuro que vai pra produção leva grain.**

| | `add_grain` | `add_noise` |
|---|---|---|
| Modelo | Grão de filme (orgânico, correlacionado) | Ruído digital (por pixel) |
| Param | `grainAmount` 0–100 (40 moderado, 80 forte) | `noiseAmount` 0.1–400 (25 moderado, 50 forte) |
| Usar p/ | **Anti-banding**, textura cinematográfica | Grunge, VHS/CRT, "sinal degradado" |

**Quanto aplicar:** anti-banding puro **8–15** · textura sutil **20–30** · look de filme **40–55** · analógico pesado **70–85**.
**Ordem:** `grading → add_grain → crop/resize final`. Grain antes do resize = destruído pela reamostragem. Grain antes do grading = amplificado imprevisivelmente.
**Multi-tamanho:** aplicar grain na dimensão de ENTREGA de cada variante. Grão não escala.

---

## 4. QUANDO USAR CADA EFEITO

**`lens_blur` vs `gaussian_blur`** — lens = bokeh + falloff de profundidade, SEM parâmetros, ignora máscara. gaussian = `blurRadius` 0.1–250 + `blurTarget`, aceita máscara.
Raios web: backdrop de modal 20–40 · camada de profundidade 8–15 · suavizar textura 1.5–3 · fundo abstrato 60–120.

**`monochromatic_tint`** (`hue` 0–360, `saturation` rec. **25**, `lightness` 0) — duotone de sistema é a técnica mais subvalorizada em web: mesmo `hue` em todas as fotos de uma seção = coesão instantânea.
Valores: ciano sci-fi 190/25 · blueprint 210/30 · âmbar CRT 35/30 · verde fósforo 120/22 · sépia 30/18.

**`halftone`** (`radius` 4–127) — só quando o analógico é o CONCEITO. NÃO em SaaS/fintech/dashboards (lê como falta de direção de arte), nem sobre rosto/produto.

**`glitch`** (`horizontalOffset` −50…50, desloca canal vermelho) — **o mais clichê do conjunto**. Regras: nunca no logo, nunca em elemento interativo, nunca em corpo de texto, sempre via máscara, prefira valores BAIXOS (−5 lê como "lente real"; −30 lê como "filtro").

**`color_overlay` blend modes**: `screen` = adicionar glow SEM lavar sombras (preto vira transparente) · `softLight` = tint de marca mais seguro · `multiply` = sombra colorida · `color` = recolorir preservando estrutura tonal.

---

## 5. ADOBE EXPRESS

**Dois grupos, não misturar:**
- **G1 Documento Express**: `search_design` → `fill_text`/`change_background_color`/`animate_design` → `download_design` (exporta PDF).
- **G2 HTML Design**: autorar HTML → `html_export_readiness_skill` → `export_html_to_express`.

**`animate_design`**: recebe `templateOrDocumentURN` + `description` + `generalQuery` — SEM parâmetros de animação; você descreve em linguagem natural. Só funciona em DOCUMENTOS EXPRESS (não em HTML, não em imagem). **NÃO é image-to-video.**
Vocabulário que ele entende: categorias **In / Out / Looping**; efeitos Zoom, Pan, Blur, Color, Fade; texto typewriter, dynamic, flicker, color shuffle, fade, slide, grow; ainda Bloom, Glide, Popping, Sunrise, Waterfall. Props: Intensity, Speed, Direction, Personality.
`generalQuery` = a `description` sem PII (idêntica se não houver PII).
**`fill_text` só troca TEXTO** — nada de cor, tamanho, fonte, peso ou alinhamento.

**`export_html_to_express` — CANVAS FIXO, não é ferramenta de web design.** Doc explícita: "Responsive/adaptive layouts — não disponível". Dashboard/app UI/wireframe → `frontend-design`.
CSS NÃO suportado: `backdrop-filter`, `filter: blur()` em fundo, `mix-blend-mode` encadeado, `@keyframes`/`transition` (não executa), `var(--...)`, `position: sticky/fixed`, `box-shadow` 3+ camadas.
Suportado: box-shadow único, border-radius, gradientes, transform rotate/scale/translate, **SVG inline**.
Outros limites: overflow é CLIPADO · JS não executa · captura estática única · conta `guest` não exporta · `url` só de `*.adobe.com`/`*.claudeusercontent.com` · ≥70 KB inline pode falhar.
Root precisa de `width`/`height` em PX + `data-canvas-*` + meta `hz:*`. Fonte aplicada nos ELEMENTOS de texto (não só no body).

---

## 6. WORKFLOW COMPLETO (IA → asset web)
```
0 INGESTÃO   asset_add_file → asset_inline_preview (avaliar de verdade)
1 GEOMETRIA  auto_straighten · generative_expand (antes da cor)
2 GRADE      1 preset OU adjustments na ordem da §1.1
3 MÁSCARAS   select → [invert] → adjustments (sujeito quente / fundo frio)
4 EFEITOS    gaussian_blur mascarado · color_overlay (com justificativa)
5 GRAIN      add_grain 8–15 (anti-banding) ou 20–30 (textura)
6 ENTREGA    crop_and_resize por variante → inline_preview → preview_file
```
**Crop:** use aspect ratio STRING ("16:9"), nunca pixels (estica). `fit`: reframe (default) · extract (isolar X) · pad. `align: {x:0.3}` deixa espaço à direita p/ copy. Remoção de letterbox: ultrapasse a borda em +5%. Sempre cropar do ORIGINAL.

---

## 7. TABELA RÁPIDA
| Param | Range | Sutil | Moderado | Forte | Perigo |
|---|---|---|---|---|---|
| exposure | −20…20 | ±0.5 | ±0.8 | ±1.5 | >±2.0 |
| gamma | 0.01…9.99 | 1.2/0.8 | 1.5/0.7 | 1.8/0.6 | fora 0.3–3.0 |
| exposureOffset | −0.5…0.5 | ±0.02 | ±0.05 | ±0.1 | >±0.2 |
| highlights | −100…100 | −30 | −50 | −80 | positivo em área clara |
| lights/darks | −100…100 | ±15 | ±25 | ±40 | >50 lava |
| shadows | −100…100 | ±15 | ±30 | ±45 | >50 + darks alto |
| contrast | −50…100 | ±20 | ±30 | ±40 | — |
| tempA | −128…127 | ±10 | ±20 | ±35 | negativo p/ aquecer |
| tempB | −128…127 | ±40 | ±65 | ±100 | — |
| vibrance/saturation | −100…100 | ±15 | ±25 | ±40 | — |
| grainAmount | 0…100 | 8–15 | 20–40 | 60–85 | — |
| noiseAmount | 0.1…400 | 10 | 25 | 50 | >100 |
| blurRadius | 0.1…250 | 2 | 8–15 | 40+ | — |
| halftone radius | 4…127 | 6 | 15 | 40 | — |
| glitch offset | −50…50 | −5 | −15 | −35 | −50 |
| mono saturation | 0…100 | 15 | 25 (rec) | 40 | — |
