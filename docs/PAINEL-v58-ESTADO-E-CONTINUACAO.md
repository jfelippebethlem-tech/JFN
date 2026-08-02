# Painel JFN v58 — o que foi feito, e exatamente o que falta

> **Leia isto antes de tocar no painel.** Escrito em 2026-08-02, ao fim da sessão que quebrou o
> monolito e instalou o relógio, os ícones autorais e o deck da Consciência — e atualizado no mesmo
> dia, ao fim da sessão que fechou o catálogo de arte (mesa viva, fundo da Consciência, trilho
> refeito no Firefly).
>
> Branch: `feat/painel-v15-holo` · commits `60abc323` (v58), `89543a2e` (v58b), `15d9948`
> (textura + selo + este documento), `e74a3fa` (mesa viva) e `22b9f19` (Consciência + trilho).

---

## 1. Como o painel está montado agora

Até esta sessão, `static/js/painel.js` era **um arquivo de 4.700 linhas** carregado direto pelo
HTML. Agora o fonte mora em `static/js/src/` e o que o navegador baixa é um **bundle IIFE**.

```
static/js/
  painel.bundle.js          ARTEFATO servido. Script CLÁSSICO — sem type, sem defer, sem async.
  painel.bundle.js.map      mapa de origem (commitado; é o que torna o stack trace legível na VM)
  caps.js                   GERADO de capabilities.yaml pelo pre-commit. Nunca editar à mão.
  src/
    entrada.js              608 linhas. O catálogo TABS, a sequência de boot e a ponte. Só isso.
    ritmo.js                o relógio: três marchas com histerese
    consciencia.js          o deck sobreposto
    app/estado.js           `esfera` e `aba` — folha que o roteador e a cena importam
    nucleo/                 dom · formato · http · lista  (primitivas, sem estado, sem DOM montado)
    capacidade/estado.js    `_redMotion` e `_sobrio` — folha que quebra o ciclo cena↔capacidade
    capacidade/sobrio.js    o medidor de FPS
    barramento/sabre.js     o SSE, recebendo ganchos
    cena/index.js           canvas de fundo, mesa 3D, vídeos de esfera, portal WebGL
    ui/index.js             a11y, spotlight, dossiê, glossário, toast/confirm
    abas/index.js           as 59 telas

static/css/
  painel.css                ARTEFATO — CONCATENAÇÃO de src/. Nunca editar direto.
  src/00-v7-base.css        ... 70-v49-sobrio ... 95-v58.css   (a ordem dos prefixos É a cascata)
```

### As duas regras que não se negociam

**1. O `painel.bundle.js` é carregado como script clássico, na mesma posição de sempre.**
Sem `type=module`, sem `defer`, sem `async`. Mudar isso é o vetor que já matou este boot três
vezes: os ~165 handlers `onclick=` do painel só resolvem no escopo GLOBAL, e o boot precisa rodar
antes do `DOMContentLoaded` (ele disputa com View Transitions). A propriedade é verificada por
`window.__jfnBootReadyState`, gravado na primeira instrução do entrypoint: com script bloqueante
ele é `'loading'`; com defer vira `'interactive'` e o `painel_boot_check` falha com o motivo escrito.

**2. Artefato nunca se edita — nem o bundle, nem o `painel.css`.**
Editou `src/`? Rode o build. O gate bloqueia os dois casos, porque a catraca `?v=` sozinha não
enxerga "fonte editado, artefato velho": o hash do artefato bate com a tag e ela diz "em dia"
enquanto serve código antigo.

```bash
npm run build:painel                                   # src/ -> painel.bundle.js
PYTHONPATH=. .venv/bin/python -m tools.painel_css_cortar --juntar    # css/src/ -> painel.css
PYTHONPATH=. .venv/bin/python -m tools.painel_bump_versao            # reescreve os ?v=
```

---

## 2. As ferramentas novas, e o buraco que cada uma tapa

| ferramenta | o buraco |
|---|---|
| `tools/painel_ponte_check.py` | Extrai dos ~165 handlers inline TODO nome que eles resolvem no escopo global, inclusive os 19 que o HTML **escreve** (`onchange="_respProc=this.value"`). Lê atributo literal **e** `setAttribute` em tempo de execução. |
| `tools/painel_build_check.py` | Rebuild em temporário + comparação byte a byte. Bloqueia bundle defasado. Degrada com aviso sem Node. |
| `tools/painel_efeitos_boot.py` | Inventaria os efeitos de topo em ordem, e prova que **nenhum módulo tem efeito de topo** — o invariante que torna a ordem de import irrelevante. |
| `tools/painel_css_cortar.py` | Corta/concatena os estratos e prova identidade por sha256. |
| `tests/test_painel_ordem_de_boot.py` | A sequência de boot é um contrato. Reordenar, remover ou acrescentar quebra com o diff na cara. |
| `tests/test_painel_ponte_completa.py` | Completude da ponte + **teto que só desce** (hoje 70 globais, 19 escritos). |
| `tests/test_painel_script_classico.py` | Trava `type=module`/`defer`/`async` e a ordem das três tags. |

### O comando que decide se está tudo bem

```bash
bash tools/precommit_painel.sh          # roda tudo na ordem certa
```

E, **antes de qualquer commit que mexa em módulo**, a varredura completa — não a de 5 abas:

```bash
JFN_BASE=http://127.0.0.1:8010 PYTHONPATH=. .venv/bin/python -m tools.painel_boot_check --todas
```

> **Isto não é conselho, é cicatriz.** Nesta sessão eu commitei a etapa 6 depois de rodar só as 5
> abas padrão. `vivo` (a cascata de entrada dos cards) tinha ficado sem export e quatro abas
> quebravam. O `--todas` pegou; o de 5 não pegaria.

---

## 3. Os cinco bugs que só o IIFE revela — e como reconhecê-los

Todos apareceram no primeiro carregamento depois de mover código para módulo. **Nenhum aparece em
revisão de código.** Se aparecerem de novo, o padrão é sempre o mesmo: *um nome que era global e
passou a ser fechado dentro do IIFE.*

| sintoma | causa | conserto |
|---|---|---|
| `RangeError: Maximum call stack size exceeded` num getter | O nome está na ponte mas **não está no `import`** do entrypoint. `()=>_compCat` resolve para o próprio getter do `window`. | Importar o nome do módulo onde ele agora vive. |
| `X is not defined` no primeiro quadro | Um módulo lê um símbolo que ficou no entrypoint. | Mover o símbolo para o módulo que o consome, ou para uma **folha** que os dois importam. |
| `Cannot assign to import` na build | Um dos 19 estados escritos pelo HTML mudou de arquivo. | Exportar `_setX(v)` do módulo e apontar a ponte para ele. **Este é o bom** — o compilador está impedindo uma falha que seria muda. |
| Botão morto, sem erro no console | Handler ligado por `setAttribute('onclick', …)`, que não é atributo literal. | `painel_ponte_check` já lê isso; se um novo aparecer, ele acusa. |
| Boot reordenado, sem erro nenhum | Efeito de topo dentro de um módulo — roda na ordem do **import**. | `painel_efeitos_boot` acusa. Vira função, chamada da sequência de boot. |

### A armadilha da declaração múltipla

`let _compView='catalogo', _compTermo='', _compGrupo=null, _compCat=null, …` — regex de
`^export let X` só casa o **primeiro**. Isso me cegou **duas vezes** nesta sessão: uma no extrator
da ponte (corrigido em `_declaradores`) e outra no gerador de setters, sete estados depois. Se for
escrever ferramenta que lê declarações, trate declarador múltiplo desde o primeiro minuto.

---

## 4. O relógio (`--bpm`) — como funciona e o que NÃO fazer

`static/js/src/ritmo.js` põe `data-ritmo` no `<body>` a partir do barramento real. O CSS traduz
marcha em tempo, e toda a respiração da cena deriva por `calc()`.

```
vigilia    2.60s   sem sweep, carga baixa, < 1 evento/min
coleta     1.50s   sweep vivo OU >= 1 evento/min
enxurrada  0.85s   >= 12 eventos/min OU load1 >= 3.5 (2 vCPU)
```

Histerese: **3 s para subir, 15 s para descer.** Sem isso um evento isolado faz o painel piscar
entre marchas.

> **NÃO transicione o `--bpm`.** Medido em campo: com `transition` declarada, a primeira troca de
> marcha simplesmente não acontece (o computado fica preso em 2.6s). E interpolar um `<time>` que
> alimenta `animation-duration` **reinicia a animação a cada valor novo** — 60×/s, em dezenas de
> elementos. A troca é carregada por um pulso de uma passada só no conduíte.

**A linha que separa o que deriva do relógio.** Respiração deriva; **progresso não**. `.skel .sp` e
os anéis de carregamento giram sempre no mesmo tempo — um spinner que acelera junto com o sweep
passa a mentir sobre o que está esperando. `graveGlow` (alarme de severidade) também não deriva: se
mudasse de ritmo, "grave" significaria coisas diferentes em momentos diferentes.

---

## 5. Arte — o que existe, e o método que funciona

**Toda arte vem de gerador** (Gemini, ChatGPT, Adobe Express/Firefly). Nada é desenhado à mão.

### O que está instalado

| peça | de onde | onde vive |
|---|---|---|
| 26 glifos autorais (4 sigilos de esfera + 22 de seção) | Gemini Pro, **como código SVG** | `static/assets/jfn-icones.js` |
| cantoneiras + trilho graduado | ChatGPT, como código SVG | `static/css/src/95-v58.css`, como `mask-image` |
| anel de instrumento (12 ticks radiais) | ChatGPT | idem, atrás do número dos chips |
| textura de placa (metal escovado) | Gemini, raster | `static/assets/textura-placa.webp` |
| selo usinado com alfa recuperado | Gemini, raster | `static/assets/selo-anel.webp` |
| **mesa de projeção viva** | Gemini/Veo | `static/assets/mesa-projecao.{webm,mp4,jpg}` |
| **fundo da Consciência** | Gemini/Veo | `static/assets/consciencia-fundo.{webm,mp4,jpg}` |
| **trilho de instrumento (raster)** | **Adobe Firefly** | `static/assets/trilho-hud.jpg` |
| 8 vídeos (nebulosas, núcleos, holograma do RJ) | Gemini/Veo, sessão anterior | `static/assets/` |

`static/assets/portal-nebula.jpg` está no disco e **não tem consumidor no painel** — aposentado, como
o plano previa. Não foi apagado porque `tools/express_ponte.py:237` ainda o nomeia como alvo de
geração; apagar quebraria a expectativa da ferramenta sem ganho nenhum.

### O método, em passos

1. **Peça SVG como TEXTO quando a peça for vetor.** Contorna o problema de download inteiro e é o
   formato certo para ícone. Prompt tem de dizer: *inner markup only, no `<svg>` wrapper, no stroke
   or fill attributes (they inherit), only path/circle/line/polyline/polygon/rect, 24×24 grid,
   every coordinate at least 1.1 from the edges, exactly one `<circle class="no">`.*
2. **Gere em folha de contato**, 6 glifos por imagem, todos no mesmo pedido. O gerador mantém
   coerência dentro de uma imagem muito melhor do que entre imagens.
3. **Quando a peça sair torta, dite a geometria em NÚMEROS.** Não peça "melhor". Foi assim que
   Capital (virou uma gota d'água), Radar (virou um funil) e o anel de instrumento (ticks não
   radiais) foram consertados na segunda passada. Para o anel bastou dar a fórmula:
   *para centro (60,60) e ângulo A, o tick vai de (60+44cosA, 60−44senA) a (60+56cosA, 60−56senA).*
4. **Geometria verdadeira entra como ENTRADA, não como pedido.** O sigilo do Estado usa o path de
   33 vértices derivado de `static/assets/rj-malha.js` (IBGE, estado 33), passado ao gerador com
   ordem de não redesenhar. Arte gerada e geografia verdadeira ao mesmo tempo.
5. **Raster: gere grande, sirva pequeno.** A textura saiu 2048² e 6 MB; entra 512² e 13 KB. Seis
   megabytes para uma peça a 6% de opacidade é desperdício, não fidelidade.

### 🎬 A receita de vídeo, provada duas vezes (mesa e Consciência)

Um vídeo de gerador **nunca** entra cru. São quatro passos, nesta ordem, e cada um existe por um
defeito que já apareceu na tela.

```bash
# 1+2. tira a marca do gerador E fecha o loop, numa passada só
ffmpeg -y -i FONTE.mp4 -filter_complex \
 "[0]delogo=x=1128:y=562:w=76:h=76[c];\
  [c]split[x][y];\
  [x]trim=4:10,setpts=PTS-STARTPTS[body];\
  [y]trim=0:4,setpts=PTS-STARTPTS[head];\
  [body][head]xfade=transition=fade:duration=4:offset=2[v]" \
 -map "[v]" -an -c:v libx264 -crf 20 -pix_fmt yuv420p loop.mp4
```

1. **A marca do gerador.** O Gemini assina com uma estrela ✦ **sempre no mesmo canto**: caixa
   `x=1128 y=562 w=76 h=76` num quadro 1280×720. Invisível na miniatura, gritante em tela cheia
   sobre preto. `delogo` interpola a partir da borda da caixa. **Confira em zoom antes e depois**,
   no quadro 0, recortando a região — foi assim que ela foi pega nas duas peças.
2. **A emenda do loop.** O último quadro não continua o primeiro e o corte pisca a cada volta.
   `xfade` da segunda metade sobre a primeira. **A prova é numérica, não visual:** RMS entre último
   e primeiro quadro contra o passo RMS entre quadros vizinhos. Medido: mesa 4,195 contra
   4,068/4,130; Consciência 6,362 contra 6,046/6,204. Até ~3% acima é ruído do próprio vídeo.
3. **A borda — e só quando a peça mora dentro de um cartão.** Aí um `geq` com rampa de 80 px leva
   luma e croma a preto puro nas quatro bordas, e a peça dissolve em vez de recortar. **Sobreposição
   de viewport inteira NÃO leva rampa** — sangra até a beirada. A mesa leva; a Consciência não.
4. **Saída:** VP9 `.webm` + `.mp4` + poster `.jpg`, sempre `-an`.

**No painel**, toda peça viva segue a mesma receita de `nucleoViva()`: `HEAD` antes de baixar,
poster enquanto carrega, classe `.on` só no evento `playing`, e os dois pisos
(`prefers-reduced-motion` e modo sóbrio) desligando com a placa estática assumindo. Peça que vive em
camada invocável (a Consciência) acrescenta duas: **só toca com a camada aberta**, e o `HEAD` só
acontece na primeira abertura.

### ⚠️ Arte por cima de texto: meça, não olhe

Vídeo atrás de conteúdo **precisa de medição de contraste com o vídeo composto**, e
`auditar_contraste.py` não serve — ele lê estilo computado e não enxerga pixel de vídeo.

O que aconteceu no fundo da Consciência: com a placa dos blocos a 78% de opacidade, o pior pixel do
fundo composto deu RGB(141,142,133) e o **texto de corpo caiu para 1,01:1**. Parecia ótimo na tela.

Receita da medição (rodar no navegador, com o deck aberto):
1. resolva as cores pelo **canvas** — `getComputedStyle` devolve `oklch(...)` e regex de `[\d.]+`
   lê `oklch(0.64 0.03 240)` como RGB e produz lixo (um canal deu 259). Pinte a cor num canvas 1×1
   e leia o pixel;
2. amostre ~24 quadros do vídeo num canvas, componha cada pixel sobre a cor de fundo real com a
   fórmula do blend em uso (`screen` com alfa: `out = bg + (1−bg)·(video·op)`), guarde o **pixel
   mais claro**;
3. para cada elemento de texto, suba a árvore até achar a primeira placa com alfa ≥ 0,99 — se não
   houver, o vídeo atravessa e o piso de 4,5:1 não está garantido.

**A correção certa não é abaixar a arte até sumir.** É dar calha: largura máxima na coluna de
leitura + placa opaca enquanto o vídeo toca, e a arte passa a morar na lateral — que é onde ela foi
gerada para morar. Depois da correção: corpo 5,60 · rótulo 7,33 · marcha 7,24 · título 16,78.

### ⚠️ A armadilha do mapa de ícones

`jfn-icones.js` é indexado **por emoji**, e o mesmo emoji costuma servir abas de sentidos
diferentes. Antes de trocar o VALOR de uma chave, **veja quem mais a usa**:

```bash
grep -o "ic:'🏛️'[^}]*tl:'[^']*'" static/js/src/abas/index.js static/js/src/entrada.js
```

Já aconteceu quatro vezes: `🏛️` também é *Nomeados* e *Poder*; `✂️` também é *Gastos*; `🕸️`
também é *Vínculos*; `🎯` também é *Acurácia*; `🛰️` também é *Missões* e *Sistema*. Quando o
desenho novo só vale para uma delas, crie chave própria (`§rj`, `§frac`, `§conluio`, `§cartel`,
`§fant`, `§radar`, `§fonte`, `§sev`, `§indisp`, `§licit`, `§sweep`) e reaponte só as abas certas.

### Notas de operação dos geradores

- **Chrome real** (extensão): digitação funciona normalmente, download funciona, é o caminho bom.
- **Navegador integrado**: o campo de texto do Gemini e do ChatGPT **não aceita digitação
  sintética** depois que a janela é redimensionada. O que funciona é focar o `contenteditable` e
  usar `document.execCommand('insertText', false, texto)`. Download não materializa arquivo,
  "Copiar imagem" não chega ao clipboard do SO, e POST para `127.0.0.1` é barrado por
  mixed-content.
- O Gemini às vezes **trava com o botão "Parar resposta" preso** depois de uma resposta longa. Não
  adianta insistir: abra `/app` (conversa nova) e reenvie.
- `"Algo deu errado (1155)"` é **rejeição por alta demanda**, não cota. Retentar funciona.
- **Fechar as janelas depois de baixar.**

---

## 6. O QUE FALTA — passo a passo

### 6.1 · Arte — o catálogo está fechado

**Não falta nenhuma peça que tenha consumidor.** Confira você mesmo antes de gerar qualquer coisa:

```bash
grep -rhoE "assets/[A-Za-z0-9_.-]+" static/css/src static/js/src static/*.html | sed 's|assets/||' | sort -u
```

Toda peça que aparece nessa lista existe em `static/assets/`. As quatro que faltavam na sessão
anterior — selo em alta, mesa viva, fundo da Consciência e trilho raster — foram feitas e estão na
tabela do §5.

**Duas peças do plano original NÃO foram geradas, de propósito**, e isso é decisão, não pendência:
as texturas de *metal escovado* e *vidro líquido*. Elas não têm superfície pedindo por elas — a
única textura com lugar definido era a placa, que está instalada em `body::before` a 6%. Gerar arte
sem call-site é pior do que não gerar: vira peso no repositório e mentira no catálogo. Se algum dia
uma superfície pedir, o método do §5 resolve em uma passada.

### 6.2 · Código — as três frentes abertas

**A) `@layer` no CSS (o que restou da etapa 10).**
Só entre com prova. A única segura é um diff de `getComputedStyle` nas 59 abas × 2 larguras.

1. Estenda `tools/auditar_layout.py` com um modo `--dump-computado` que serialize todas as
   propriedades computadas de todos os elementos, por aba e largura, em JSON.
2. Grave o baseline **antes** de qualquer `@layer`.
3. Ordem proposta: `@layer tokens, base, layout, componentes, cena, cockpit, dialogo, responsivo;`
4. **A família de degradação fica FORA de camada e por último.** Para `!important` a ordem de
   camadas é **invertida**, e os 16 `!important` do arquivo estão todos nela
   (`prefers-reduced-motion`, `body.fps-baixo`, `html.rest`). Camadá-la manteria os `!important`
   vencendo mas rebaixaria as declarações **normais** dela — regressão silenciosa de acessibilidade.
5. Um estrato só sai da cauda não-camadada quando o diff sair vazio.

**B) Subdividir `cena/index.js` (1.299 linhas) e `abas/index.js` (2.349 linhas).**
Os dois saíram como módulo único de propósito, e a razão está no cabeçalho de cada um:

- `cena/` está **interleavada** com o cockpit no arquivo original: `netbgStart` termina e `_ckCount`
  começa na linha seguinte; `nucleoStart` termina e `ckCard` começa na seguinte. Subdividir exige
  resolver as referências cruzadas (`nucleoStart` usa `_holoProj`, `_rjCarregar`, `_rjBuild`,
  `_holoPiso`, `HOLO`) — isso é reescrita, não mudança de arquivo.
- `abas/` está em duas faixas separadas pelo próprio `TABS`, e o comentário original explica: `TABS`
  é `const` e referencia o render na **avaliação**, então um `const renderX` declarado depois daria
  TDZ e mataria o boot em silêncio. Separar por domínio exige classificar 59 funções e resolver as
  compartilhadas entre esferas (`renderSobrepreco`, `renderConluio` e `renderPoder` aparecem em duas
  ou três, com argumento diferente).

Se for fazer: um domínio por commit, `--todas` entre cada um.

**C) Baixar o teto da ponte (hoje 70).**
A ponte é um degrau, não o destino. O caminho é delegação por `data-*` no `#view`, **por domínio**.
Cada domínio migrado baixa `TETO_GLOBAIS` em `tests/test_painel_ponte_completa.py`, e o teste
falha de propósito quando o número cai — para forçar a atualização e tornar o progresso visível.

### 6.3 · Camadas 3 e 4 do plano visual

- **Consciência**: a cena de fundo própria está feita. Falta mostrar o *frescor* com o glifo
  `§fonte` por fonte, em vez de só o nome.
- **Cockpit como centro de gravidade** (o resto da camada 2): a mesa de vigília ainda é um bloco
  dentro da página. O plano é ela virar o centro com os painéis orbitando, e as linhas de energia
  ligarem os painéis ao núcleo com pacotes viajando na taxa real de eventos.
- **Surpresas por aba** (~15 gramáticas de revelação): tabela monta linha a linha, ranking cresce de
  baixo para cima, grafo desenha as arestas antes dos nós, comparador desliza as colunas em sentidos
  opostos. Nenhuma implementada ainda.

---

## 7. Coisas que vão te morder se você não souber

1. **CRLF quebra o gate na VM.** Arquivo que passa pelo Windows chega com `\r\n` e o
   `precommit_painel.sh` morre com `set: -: invalid option`. Depois de qualquer transferência:
   ```bash
   for f in $(git diff --name-only); do file "$f" | grep -q CRLF && sed -i 's/\r$//' "$f"; done
   ```
2. **O `?v=` do `/controle` também está na catraca.** Ele carrega `painel.css` e `jfn-icones.js`.
   Ficar de fora significaria servir a folha velha de cache numa página que ninguém lembra de olhar.
3. **`e_alertas` vazio no laboratório local é esperado** — é a única aba que depende de dado que o
   ambiente sem banco não tem. Em produção ela responde.
4. **O laboratório local roda em `127.0.0.1:8010`**, sem banco. É onde os caminhos de erro e vazio
   aparecem — foi assim que as 17 telas que vazavam `no such table` foram descobertas.
   ```bash
   .venv/Scripts/python.exe server.py --host 127.0.0.1 --port 8010
   ```
5. **Não medir FPS em aba oculta.** O Chrome congela o rAF e a conta dá ~0, o que jogava o painel em
   modo sóbrio permanente. Já resolvido em `capacidade/sobrio.js`, mas se mexer ali, lembre.
6. **Nunca `pkill -f`** na VM — `pgrep` + `kill` por PID. E o painel é `systemctl --user restart jfn`,
   nunca matar o processo.
7. **O censo de animações infinitas subiu de 54 para 69** e isso é esperado: o bloco do relógio é
   **aditivo**, as regras antigas continuam no arquivo e perdem na cascata. A duração **aplicada** é
   a nova (medida). Reescrever as antigas é trabalho do `@layer` (§6.2-A).

---

## 8. Números de referência (medidos nesta sessão)

| medida | valor |
|---|---|
| `entrada.js` | 4.700 → **608 linhas** |
| bundle servido | **~350 KB** (94 KB gzip) |
| `painel.css` | 237.101 bytes, seis estratos, sha256 idêntico à concatenação |
| abas | **60** (43 varridas pelo `--todas`) |
| globais exigidos por handler inline | **70** (19 escritos) |
| efeitos de topo no boot | **27**, em contrato |
| testes estáticos do painel | **44** |
| FPS headless (parado / após 20 navegações) | 19 / 29 — sem mudança desde o baseline |
| vídeos / canvas / fixos em cena | 2 / 3 / 15 — sem vazamento em 20 navegações |
| emenda do loop — mesa | 4,195 contra passo normal 4,068 / 4,130 |
| emenda do loop — Consciência | 6,362 contra passo normal 6,046 / 6,204 |
| contraste no deck com o vídeo ligado | corpo **5,60** · rótulo 7,33 · marcha 7,24 · título 16,78 |
| peso das peças vivas novas | mesa 435+644+36 KB · Consciência 513+725+37 KB · trilho 26 KB |

**Estado do gate ao fim desta sessão:** `painel_css_cortar --check` idêntico, `painel_build_check`
em dia, `painel_bump_versao --check` em dia, 30 testes estáticos passando, `painel_boot_check
--todas` com **43 abas e zero `pageerror`**. O único apontamento é `e_alertas` vazia, que é dado
ausente no laboratório local e não regressão (§7.3).
