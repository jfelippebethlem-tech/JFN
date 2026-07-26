# PEDIDO AO DESKTOP (it-campo) — arte viva do painel JFN
**Data:** 2026-07-26 · **Autor:** jfn-core · **Para:** Claude Code do it-campo (Opus 5)
**Como usar:** o dono abre o Claude Code no desktop e cola:
`leia C:\Users\iterj\Downloads\PEDIDO-DESKTOP-KEYART.md e execute na ordem`
(o arquivo é este mesmo, copiado para lá).

---

## 0 · O QUE JÁ ESTÁ PRONTO DO MEU LADO (não precisa fazer nada disso)

O painel **já tem toda a fiação** para receber cada peça. O encaixe é
**progressivo**: eu sondo o arquivo com um `HEAD`; se responder 200, a camada
acende sozinha; se der 404, o painel segue exatamente como está hoje, sem erro.
Ou seja: **basta o arquivo existir com o nome certo em `static/assets/`** e a
arte entra no ar sem tocar em código, sem restart.

| arquivo esperado | onde entra | como entra |
|---|---|---|
| `nucleo-holo-rj.mp4` (+ `.webm`) | mesa do cockpit (`#ck-nucleo`) | vídeo por baixo do canvas procedural, `mix-blend-mode:screen`, opacidade 0.85 |
| `nebula-estado.mp4` | fundo da esfera Estado | dentro de `#esfnebula`, sobre o JPG que vira poster |
| `nebula-prefeitura.mp4` | fundo da esfera Prefeitura | idem |
| `nebula-transversal.mp4` | fundo da esfera Transversal | idem |
| `no-energia.png` | nós do mapa (`.nu-chip`) | anel usinado sob o chip, tingido pela cor do nó |

Eu recebo o arquivo, valido com `ffprobe`, converto o que precisar (H.264
yuv420p ≤1920px + irmão WebM VP9 para navegador sem H.264), faço backup do
anterior e instalo. O script já existe: `_SANDBOX/instalar_keyart.py --aplicar`.

---

## 1 · REGRAS QUE VALEM PARA TODAS AS PEÇAS (custaram rodadas para aprender)

1. **ZERO texto, dígito ou numeral na arte.** O gerador adora inventar HUD com
   números falsos. Em painel de auditoria, número inventado é inaceitável mesmo
   ilegível — já tivemos que recortar o `trilho-hud` por causa disso. Se vier
   com dígito: regere, não recorte.
2. **Fundo quase-preto de verdade.** As peças entram em blend `screen`/`lighter`:
   um véu cinza vira **quadrado visível** na composição. Cantos e bordas têm que
   morrer em preto puro (`#000`), não em cinza escuro.
3. **Loop perfeito (seamless).** Primeiro e último quadro idênticos. Peça
   explicitamente "seamless loop" e **confira antes de mandar** (extraia os dois
   quadros e compare).
4. Sem marca d'água, sem moldura, sem vinheta clara, sem legenda.
5. **Movimento sutil.** É fundo de trabalho de auditoria, não protagonista:
   deriva lenta + pulso leve. Nada de strobe, flash ou corte rápido.
6. **Geografia real.** Onde aparecer o Rio de Janeiro, o contorno tem que ser o
   verdadeiro (referência de forma: `static/assets/rj-malha.js` no repo, branch
   `feat/painel-v15-holo`).

**Ordem de ferramenta (regra do dono):** Claude Design → Gemini → ChatGPT →
Adobe Express/Firefly **por último** (créditos curtos). Nunca gerar por código
(ffmpeg/three.js/shader): a arte tem que nascer em gerador.

---

## 2 · PEÇA 1 (PRIORIDADE MÁXIMA) — `nucleo-holo-rj.mp4`

É **a** peça do pedido do dono. Se só der para fazer uma, é esta.

**Base:** `C:\Users\iterj\Downloads\portal-anel-plasma_1280.jpg`
(anel ciano concêntrico sobre grade TRON; versão 2K no repo em
`docs/referencias/keyart/gemini/portal-anel-plasma-grade_gemini_2026-07-26.png`)

**O que muda em relação à base:** o miolo de fogo dá lugar a um **holograma
volumétrico ciano da silhueta do ESTADO DO RIO DE JANEIRO**, em rotação 3D
lenta, com scanlines e partículas subindo do anel. O anel é a **base arc
reactor** que "gera" o holograma — a leitura tem que ser essa: máquina embaixo,
projeção em cima.

**Prompt sugerido (EN, ajuste como precisar):**
> Seamless looping video. A massive arc-reactor ring of concentric cyan energy
> bands, seen at a three-quarter angle, projecting a volumetric 3D hologram of
> the silhouette of the state of Rio de Janeiro floating above it. The hologram
> rotates slowly, with fine scanlines and rising particles. Dark starship
> command deck, near-black background, edges fade to pure black. Cinematic,
> subtle slow motion. No text, no numbers, no watermark, no UI elements.

**Formato:** MP4 H.264, 1920×1080 (ou 1280×720), 8–10 s, sem áudio, loop
seamless. Se puder, mande também um frame como `nucleo-holo-rj.jpg` (poster).

---

## 3 · PEÇAS 2–4 — nebulosas vivas (animar o que JÁ foi aprovado)

**Não gere do zero.** O dono já aprovou as três nebulosas estáticas; anime-as
por image-to-video para preservar a identidade:

| base (está no Downloads e no repo `static/assets/`) | saída |
|---|---|
| `nebula-estado.jpg` (ciano-íon) | `nebula-estado.mp4` |
| `nebula-prefeitura.jpg` (âmbar-ouro) | `nebula-prefeitura.mp4` |
| `nebula-transversal.jpg` (violeta) | `nebula-transversal.mp4` |

**Prompt de movimento:**
> subtle slow drift of the nebula clouds, thin TRON-like energy lines pulsing
> gently, seamless loop, keep composition and colors exactly as in the input
> image, no new elements, no text, edges fade to pure black

**Formato:** MP4 H.264, 1920×1080, 6–10 s, sem áudio, loop seamless, ≤25 MB
(se passar, manda assim mesmo que eu comprimo).

---

## 4 · PEÇA 5 — `no-energia.png` (corpo dos nós do mapa)

Última pendência de arte do handoff v27. Peça pequena, mas fecha um item.

**Formato:** PNG **com transparência (RGBA)**, 512×512, peça única centrada.

**Prompt (EN):**
> Single small sci-fi energy node seen from directly above, perfectly top-down
> orthographic, radially symmetric machined metal ring with a glowing core,
> arc reactor / holocron style, desaturated cold metal, centered on fully
> transparent background, no perspective, no shadow outside the ring, no text.

**Por que esta dá certo onde ícone e botão foram reprovados:** é peça circular
radialmente simétrica — perspectiva e esticamento não a distorcem. O metal vem
**dessaturado** de propósito: eu tinjo por esfera no CSS (mesmo truque do
`selo-anel`).

**NÃO gerar:** grid de ícones e placa de botão. Foram reprovados 2× cada, com
evidência (forma preenchida, espessura desigual, perspectiva onde foi pedido
ortográfico). Registro em `docs/superpowers/specs/HANDOFF-painel-v27-2026-07-26.md`.

---

## 5 · PEÇAS 6–7 (só depois das anteriores) — núcleos das outras esferas

- `nucleo-holo-prefeitura.mp4` — mesma linguagem da Peça 1, mas holograma da
  silhueta do **município do Rio** (não o estado), energia **âmbar-ouro**.
- `nucleo-holo-transversal.mp4` — mesma linguagem, holograma de **grafo/rede 3D**
  (nós e arestas girando — a teia de vínculos), energia **violeta**.

---

## 6 · COMO ENTREGAR

Qualquer um destes serve (o primeiro é o mais simples):

1. **Taildrop** para `jfn-core` (o dono arrasta os arquivos, ou o agente usa
   `tailscale file cp <arquivo> jfn-core:`).
2. **scp** direto: `scp <arquivo> ubuntu@100.123.89.59:~/JFN/data/taildrop_in/`
3. Deixar em `C:\Users\iterj\Downloads\` e avisar o dono — eu puxo depois.

**Junto com as peças, mande um `KEYART-STATUS.md`** dizendo, por peça: qual
ferramenta gerou, o prompt final usado, se o loop foi conferido (primeiro =
último quadro) e qualquer recusa/limite que tenha aparecido. Isso me poupa
adivinhação e vira registro no repo.

---

## 7 · O QUE **NÃO** FAZER (para não repetir as rodadas de hoje)

- **Não mexer em Syncthing, SSH, firewall ou qualquer infra.** Está tudo
  funcionando: o desktop sincroniza como **Desktop-JFN** e o elo SSH está
  fechado nos dois sentidos.
- **Não copiar perfil do Chrome** para tentar herdar login: o Chrome 127+ usa
  App-Bound Encryption e o perfil copiado **sempre** abre deslogado. Medido hoje.
- **Não tentar porta de depuração no perfil padrão**: o Chrome 136+ recusa —
  é por isso que `--remote-debugging-port` "não pegava" no perfil real.
- **Não usar API paga** de nenhum provedor sem "sim" expresso do dono
  (a regra da casa é dura: nada de presumir free tier).
- **Não gerar imagem/vídeo por código.**

O caminho que funciona é o mais simples: **usar as janelas de navegador que já
estão abertas e logadas na máquina** (Gemini, Claude Design, ChatGPT) ou o
**Claude for Desktop**, gerar ali e salvar o arquivo. Sem automação nenhuma.

---

## 8 · ESTADO DO PAINEL HOJE (para você saber o que a arte vai encontrar)

Trabalho fechado nesta sessão, branch `feat/painel-v15-holo`
(commits `5a2bd8bf`, `5a86d7ba`, `35c6f505`, `25fe367f`, `45e2dc56`):

- **v36** faceta 3D com sentido: trocar de aba gira o miolo para o lado do
  destino; vale também entre esferas.
- **v37/38/41** encaixes progressivos (as peças acima acendem sozinhas).
- **v39** a lâmina do trilho da capa corre de verdade (era foto parada).
- **v40/47** contraste: os padrões reais abaixo de 4.5:1 fechados.
- **v42** aba **Sistema**: fila SEI (2.054 de 45.742 lidos) com barra, arquivo
  compacto (0,99 GB), 21 pipelines com sinal, 5.967 aprendizados, refresh 30 s.
- **v43** cards/KPIs invisíveis em toda aba com grid (animação sobrescrita).
- **v44** **o cockpit estava morto desde o v31**: corrida entre o `setTimeout`
  de montagem e o paint assíncrono das View Transitions.
- **v45** dois `ReferenceError` de TDZ (`_redMotion`, `_nebVid`) abortavam o
  boot — eram a causa de 154 cards invisíveis em `g_fenix`, 78 em `g_socserv`,
  44 em `g_porta` e dos cliques falhando. Mais o `visibilitychange` sem aspas
  no portal (o segundo guarda-corpo da abertura nunca existiu).
- **v46** o chip ativo passou a falar a cor da esfera (era azul fixo em aba
  âmbar da Prefeitura).

O núcleo está **procedural e limpo** esperando a Peça 1. O vídeo interino que
usei para testar o encaixe foi arquivado em
`docs/referencias/keyart/gemini/tratados/` — não está no ar.
