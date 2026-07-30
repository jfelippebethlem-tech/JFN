# PEDIDO DE ARTE — o que ainda falta gerar para o painel JFN

**Data:** 2026-07-30 · **Autor:** jfn-core · **Para:** o Claude que vai gerar a arte
**Substitui:** `PEDIDO-DESKTOP-KEYART-2026-07-26.md` (mantido para histórico)
**Como usar:** cole este arquivo inteiro no Claude Code / Claude Design e execute na ordem.

---

## 0 · O QUE MUDOU DESDE O PEDIDO ANTERIOR (leia, muda o seu trabalho)

**Uma das cinco peças já foi entregue e instalada.** `nucleo-holo-rj.mp4` + `.webm` estavam prontos
no repositório desde 26/07 e o instalador nunca havia sido rodado — foram instalados em 30/07 e estão
no ar. **Não gerar de novo.**

**Sobram 4 peças**, listadas na §2.

**E há um número novo que muda o desenho de todas elas.** O painel foi medido com Playwright nesta
VM (2 vCPU, sem GPU): **1 a 2 quadros por segundo com a tela parada**, com 57 animações CSS
infinitas ativas. A 1 FPS, "deriva lenta de 60 segundos" não lê como deriva — lê como salto. Por isso
o painel agora tem um **modo sóbrio medido**: ele conta quadros no boot e, abaixo de 24 FPS, desliga
as animações caras e mostra um selo dizendo isso.

**Consequência prática para você:** a arte não pode DEPENDER de movimento para funcionar. Cada peça
tem de ficar boa **parada**, porque numa fração das máquinas ela vai ficar parada. Trate o movimento
como bônus, nunca como o efeito.

---

## 1 · REGRAS QUE VALEM PARA TODAS AS PEÇAS (custaram rodadas para aprender)

1. **ZERO texto, dígito ou numeral na arte.** O gerador adora inventar HUD com números falsos. Em
   painel de auditoria, número inventado é inaceitável mesmo ilegível. Se vier com dígito: **regere,
   não recorte.**
2. **Fundo quase-preto de verdade.** As peças entram em blend `screen`. Um véu cinza vira **quadrado
   visível** na composição. Cantos e bordas têm que morrer em preto puro (`#000`), não em cinza.
3. **Loop perfeito (seamless).** Primeiro e último quadro idênticos. Peça explicitamente "seamless
   loop" e **confira antes de mandar**: extraia os dois quadros e compare.
4. Sem marca d'água, sem moldura, sem vinheta clara, sem legenda.
5. **Movimento sutil.** Deriva lenta + pulso leve. Nada de strobe, flash ou corte rápido — e agora
   com o motivo medido: a 1-2 FPS, movimento rápido vira tremor.
6. **Geografia real.** Onde aparecer o Rio de Janeiro, o contorno tem que ser o verdadeiro
   (referência de forma: `static/assets/rj-malha.js`).
7. **NOVO — funcione parado.** Ver §0. Se a peça só faz sentido animada, ela está errada para este
   painel.

**Paleta do painel** (use exatamente estas; são as variáveis CSS reais do produto):
- íon (azul-ciano estrutural): `#38bdf8` → escuro `#0284c7`
- chama (laranja do reator, o acento quente): `#fb923c` → alto `#fed7aa`
- fundo: preto absoluto `#000` com quase-preto azulado `#050914` nas massas
- **proporção obrigatória:** o azul domina; o laranja é **acento**, nunca mais que ~15% do quadro.

---

## 2 · AS 4 PEÇAS QUE FALTAM

### 2.1 `no-energia.png` — o anel usinado do nó (PRIORIDADE 1, a mais barata)

- **Onde entra:** por baixo de cada chip de nó no mapa de vínculos (`.nu-chip`), tingido em runtime
  pela cor do nó.
- **Formato:** PNG com **transparência real**, quadrado, 512×512.
- **O que é:** um anel metálico usinado visto de frente — sulcos concêntricos finos, brilho
  especular discreto num quadrante só, centro **totalmente vazado** (alpha 0).
- **Não é:** engrenagem, mira, HUD, alvo, relógio.
- **Cor:** grafite neutro. **Não colorir** — o painel aplica a cor por cima; qualquer matiz sua vai
  brigar com a dele.
- **Teste de aceite:** sobre fundo preto, o anel se lê; sobre fundo claro, também (é alpha, não
  fundo). Sem serrilhado na borda externa.

### 2.2–2.4 `nebula-estado.mp4` · `nebula-prefeitura.mp4` · `nebula-transversal.mp4`

- **Onde entram:** faixa superior de 46vh atrás do conteúdo (`#esfnebula`), em `mix-blend-mode:screen`
  com opacidade **0,14–0,20**. Ou seja: **vai ficar bem apagada**. Arte com detalhe fino desaparece;
  o que sobrevive é massa, gradiente e silhueta.
- **Formato:** MP4 H.264 yuv420p, **1920×1080**, 12–20 s, seamless loop, **≤ 4 MB cada**. Mande também
  `.webm` VP9 se puder (há navegador na casa sem H.264).
- **Movimento:** deriva de nuvem, muito lenta. Sem elementos que cruzem o quadro.
- **As três precisam ser IRMÃS e DISTINGUÍVEIS:** mesma linguagem visual, temperatura diferente —
  quem troca de esfera tem de sentir a mudança sem precisar ler o rótulo.

| peça | tema | leitura cromática |
|---|---|---|
| `nebula-estado.mp4` | Estado do RJ — máquina pública estadual | azul frio profundo, mais estrutural, leve grade cósmica |
| `nebula-prefeitura.mp4` | município do Rio | azul com âmbar quente ao fundo (luz de cidade), mais orgânico |
| `nebula-transversal.mp4` | risco, poder, vínculos | mais escura e densa, filamentos que sugerem rede/teia, acento laranja mínimo |

- **Referência que já existe no repo** (use como ponto de partida de cor e massa, não copie):
  `static/assets/nebula-estado.jpg`, `nebula-prefeitura.jpg`, `nebula-transversal.jpg` — são os
  posters atuais e continuam por baixo.

---

## 3 · GEOMETRIA MEDIDA (isto é o que causou o bug que acabou de ser corrigido)

Se algum dia gerar arte para o **portal de abertura**, esta seção é obrigatória.

O portal compõe cinco camadas. O núcleo incandescente do shader procedural fica em
**x = 50%, y = 41%** da viewport — e isso é demonstrável por duas fontes independentes no código:
`vec2 pr = p - vec2(0.0, 0.09)` com `gl_FragCoord.y` crescendo para cima (50% − 9% = 41%), e o
desenho do território usando `const cy = H*0.41` com o comentário *"nasce no núcleo do reator"*.

A máscara radial que abre o buraco para a arte aparecer estava em **51% 46%** — calibrada na era da
FOTO PARADA e nunca reajustada quando o vídeo entrou (v30). Resultado visível: o topo do orbe laranja
escapava da máscara e ficava **flutuando sobre o vídeo**, enquanto o buraco revelava pixels sem
reator nenhum. Foi corrigida para 50% 41% em 30/07.

**Portanto: se a peça tiver um núcleo/foco luminoso, ele precisa cair em x=50%, y=41% do quadro.**
Não no centro geométrico. Um núcleo no centro (50% 50%) reabre o mesmo bug.

---

## 4 · ORDEM DE FERRAMENTA E ENTREGA

1. **Claude Design** → 2. **Gemini** → 3. **ChatGPT** (regra do dono).
2. Entregar em `~/JFN/data/taildrop_in/` (ou Taildrop para a VM `jfn-core`).
3. Instalar com: `.venv/bin/python _SANDBOX/instalar_keyart.py --aplicar`
   — ele valida com `ffprobe`, converte o que precisar, faz backup do anterior e instala.
4. **Não é preciso reiniciar nada.** O painel sonda cada asset com `HEAD`; 200 acende a camada, 404
   mantém o painel como está. O encaixe é progressivo por desenho.

## 5 · CHECKLIST DE ACEITE (rode antes de mandar)

- [ ] nenhum dígito, letra ou glifo em qualquer quadro
- [ ] cantos em `#000` puro (abra no editor e conte o pixel do canto)
- [ ] primeiro e último quadro idênticos (seamless)
- [ ] a peça se lê **parada** (pause no meio e olhe)
- [ ] ≤ 4 MB por vídeo; PNG com alpha real
- [ ] se houver núcleo luminoso: está em x=50%, y=41% — não no centro
- [ ] o laranja não passa de ~15% do quadro
