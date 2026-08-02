# Painel JFN v59 — o que foi feito, e exatamente o que falta

> **Leia isto antes de tocar no painel.** Escrito em 2026-08-02, ao fim da sessão que fechou o §6
> do documento v58 — as gramáticas de revelação, o cockpit como centro de gravidade, o corte de
> `cena/` e `abas/`, o primeiro domínio fora da ponte — e que, no caminho, achou o dossiê quebrado
> em produção.
>
> Substitui `PAINEL-v58-ESTADO-E-CONTINUACAO.md`, que fica no repositório como registro: três
> premissas dele foram **medidas e desmentidas** nesta sessão, e ver o erro ao lado da correção
> vale mais do que ver só a correção.
>
> Branch: `feat/painel-v15-holo`.

---

## 0. As três premissas do v58 que a medição desmentiu

Nenhuma era descuido. As três eram afirmações plausíveis, escritas com convicção, sobre coisas que
ninguém tinha medido. É o padrão que vale levar adiante: **o que está no comentário não é o que
está na tela até alguém apontar um instrumento para lá.**

| o v58 dizia | o que a medição mostrou |
|---|---|
| "o atraso escalonado faz a coluna ser LIDA de cima para baixo" (v34) | O `--i` só existia como `nth-child` para os 14 primeiros filhos de `.grid`/`.cols`. Em `g_radar`, as 100 barras e os 204 números tinham `--i` vazio e atraso 0 — **cresciam todas no mesmo quadro**, desde o v34. |
| "os 16 `!important` do arquivo estão todos na família de degradação" | São **15**, e **7 não estão**. Três delas são a mesma regra em três gerações (`nav.tabs button.on::after`) duelando por `!important` e resolvidas por ordem de documento — que é o que faz a respiração da aba derivar do relógio. |
| "subdividir `cena/` é reescrita, não mudança de arquivo" | Certo sobre o sentido, errado sobre o tamanho. As cinco referências cruzadas andam **num sentido só**: a mesa chama a câmera, a câmera nunca chama a mesa. Dependência de mão única vira `import` sem reescrever nada. |

E uma quarta, que não estava escrita mas estava implícita em todo o §3: **que o `painel_boot_check`
era a rede final.** Não era. Ele percorre as 60 abas e não clica num CNPJ — e o dossiê estava
morto.

---

## 1. O DOSSIÊ ESTAVA QUEBRADO EM PRODUÇÃO

Vem primeiro porque é o mais grave, e porque a forma como escapou é a lição.

`ui/index.js` chamava `sec()` e `leitura()` sem importar as duas, desde o corte em módulos do v58.
A chamada `sec('Contato & rede (Receita)')` dentro de `abrirDossie` é **incondicional**.

```
bundle publicado em 30a04e94:  7 chamadas a `sec(`   ·   0 definições de `sec`
```

O esbuild só renomeia em caso de colisão. A `sec` de `nucleo/dom.js` virou `sec2`; o nome livre de
`ui/index.js` não tinha a quem se ligar. Reproduzido no navegador servindo aquele bundle exato,
com o servidor intocado:

```
ReferenceError: sec is not defined
    at abrirDossie (painel.bundle.js:2763:34)
```

**Clicar num CNPJ — a interação mais usada do painel — não funcionava.** E nada pegava:

- o `esbuild` não pega (identificador livre ele assume que é global do navegador);
- revisão de código não pega (a linha parece certa);
- o `painel_boot_check` não pega (ele visita abas, não abre dossiê).

### A ferramenta que fecha o buraco

`tools/painel_modulo_livre.py` — 40 ms, sem navegador. É o bug nº 2 da tabela do §3, agora com
detector estático. **Entra no gate do pre-commit.**

Ela olha uma **lista fechada**: os símbolos que os módulos da casa exportam entre si. Fora dela não
opina — `window`, `document`, `Math` e os globais de script clássico (`CAPS_MESTRAS`, `RJ_MALHA`)
são livres de propósito. Lista fechada troca cobertura por **confiança**, e confiança é o que faz
um detector continuar sendo lido depois do terceiro alarme falso.

**Duas notas de método, porque ela quase nasceu inútil:**

1. A primeira versão acusou **seis** símbolos, **todos falsos**. Causa: tirar literal antes de
   comentário e tirar comentário antes de literal erram em sentidos opostos, os dois em silêncio
   (uma crase dentro de comentário casa com outra crase lá adiante e come código de verdade; um
   `//` dentro de uma URL em string come o resto da linha). A cura é **varredura da esquerda para
   a direita**, um token por vez.
2. O template **não** é apagado inteiro: o que está dentro de `${...}` fica. Este painel monta HTML
   com template e chama função de dentro da interpolação o tempo todo — apagar o template cegaria
   o detector justamente onde mais há chamada. Foi assim que ele achou o `sec`.

---

## 2. Como o painel está montado agora

```
static/js/
  painel.bundle.js          ARTEFATO servido. Script CLÁSSICO — sem type, sem defer, sem async.
  caps.js                   GERADO de capabilities.yaml pelo pre-commit. Nunca editar à mão.
  src/
    entrada.js              o catálogo TABS, a sequência de boot (27 efeitos) e a ponte
    ritmo.js · consciencia.js
    app/estado.js           `esfera` e `aba` — folha
    capacidade/estado.js    `_redMotion` e `_sobrio` — folha que quebra o ciclo cena↔capacidade
    nucleo/                 dom · formato · http · lista   (primitivas, sem estado)
    barramento/sabre.js     o SSE
    cena/                   index 934 · portal 225 · energia 182 · holomesa 118 · fundo 114
                            · malha-rj 72 · ponteiro 18 (folha, quebra o ciclo index↔fundo)
    ui/                     index 429 · revelacao 182
    abas/                   index 1.663 · vinculos 373 · cockpit 280 · comparador 217

static/css/src/             00-v7-base … 95-v58 … 96-v59   (a ordem dos prefixos É a cascata)
```

### As duas regras que não se negociam

**1. O `painel.bundle.js` é script clássico, bloqueante, na mesma posição de sempre.** Sem
`type=module`, sem `defer`, sem `async`. Verificado por `window.__jfnBootReadyState`.

**2. Artefato nunca se edita** — nem o bundle, nem o `painel.css`. Editou `src/`? Rode o build.

```bash
npm run build:painel
PYTHONPATH=. .venv/bin/python -m tools.painel_css_cortar --juntar
PYTHONPATH=. .venv/bin/python -m tools.painel_bump_versao
bash tools/precommit_painel.sh                      # roda tudo na ordem certa
JFN_BASE=http://127.0.0.1:8000 PYTHONPATH=. .venv/bin/python -m tools.painel_boot_check --todas
```

---

## 3. O que a v59 fez

### 3.1 · As gramáticas de revelação (era §6.3-c)

O plano pedia "~15 surpresas por aba". **Não foram escritas por aba**, e a decisão é o centro do
desenho: quinze animações amarradas a quinze `id` criam quinze coisas para manter sincronizadas
com sessenta telas que mudam toda semana. Aba renomeada perde a gramática em silêncio; aba nova
nasce sem nenhuma; ninguém descobre, porque **falta de animação não quebra teste**.

As gramáticas são acionadas pela **forma** que a tela tem no DOM (`ui/revelacao.js`):

| # | gramática | dispara quando |
|---|---|---|
| 1 | tabela monta linha a linha | há `table tbody` com 3+ linhas |
| 2 | ranking cresce da base | os números de um `.grid` estão **de fato ordenados** |
| 3 | rankings irmãos entram por lados opostos | há 2+ rankings na mesma tela |
| 4 | a seção risca antes de o conteúdo chegar | há `h2.sec` |
| 5 | a fileira de chips abre em leque | há `.chips` com 2+ filhos |
| 6 | a malha traça as arestas ANTES dos nós | sempre (`_wire`) |

"É um ranking?" é **medido**, não cadastrado. O container só ganha a gramática se os números
estiverem ordenados — nenhum cadastro pode mentir sobre isso, e uma aba que deixa de ser ranking
perde a gramática sozinha.

**Dois bugs que só a medição pegou:**

- **A armadilha do v43 de volta.** `.rise` tem `opacity:0` estático e quem segura o cartão visível
  no fim é o `both` da própria `rise`. A primeira versão da regra de lados opostos declarava
  `animation:` só com a gramática nova, e teria feito o cartão **sumir** ao fim da animação — o
  mesmo bug que deixou o achado mais grave invisível por treze versões. Agora compõe, e há teste
  estático que falha se alguém repetir.
- **O ponto decimal é ambíguo neste painel.** `fmtN`/`fmtD` produzem pt-BR (`1.234,56`) mas dezenas
  de renders interpolam o número cru do JSON (`0.7`). Tratar todo ponto como milhar lia `0.7` como
  `7`, e a lista de fornecedores mais baratos (0,64 · 0,66 · 0,7 · 0,72) aparecia fora de ordem —
  **ranking legítimo recusado**. A desambiguação é determinística: milhar em pt-BR vem sempre
  seguido de exatamente três dígitos.

**Custo:** zero trabalho por quadro, **zero leitura de geometria**. A primeira versão cortava por
dobra e isso custava dois preços — o relayout forçado da leitura, e um erro de recorte: num monitor
de 900px a lista de ranking começa depois da fileira de KPIs, a dobra via 7 dos 80 cartões, e sete
cartões fora de ordem faziam o detector recusar a lista inteira.

### 3.2 · O cockpit como centro de gravidade (era §6.3-b)

A mesa de vigília era um bloco empilhado. Agora é o centro, com quatro instrumentos de cada lado e
linhas de energia ligando cada um ao núcleo (`cena/energia.js` + `.ck-orbita`).

**O pacote É o evento.** O plano pedia "pacotes na taxa real de eventos". Ler `eventosPorMinuto` e
emitir naquela cadência seria série sintética com outro nome — o `PRODUCT.md` proíbe. Cada pacote é
**um** evento real, na linha do domínio que o produziu, do mesmo gancho e com a mesma tabela
(`EV_DOMINIO`/`EV_COR`) que já alimenta a onda do piso. Quem olha dez segundos e conta três pacotes
contou três eventos. **Barramento calado = nada se move**, e o laço nem chega a existir.

Três decisões que não são estéticas:

- `display:contents` no `#ck-grid` promove os oito cartões a itens da grade da órbita **sem
  desmanchar o container** — `ckBoot` e `ckFill` continuam achando o mesmo id.
- A órbita só existe a partir de **1100px**. Abaixo disso os cartões ficam embaixo do núcleo e o
  fio viraria um risco vertical. O JS faz a mesma checagem: as duas metades têm de concordar.
- O `requestAnimationFrame` **só vive enquanto há pacote**. Sem pacote, desenha o quadro parado uma
  vez e para.

`energiaCenso()` pagou-se na primeira leitura: mostrou que sair do cockpit soltava o laço mas não
esquecia a geometria — um evento depois disso levantaria um rAF para desenhar num canvas já fora do
documento. Laço vivo, zero pixel, custo real.

### 3.3 · O corte de `cena/` e `abas/` (era §6.2-B)

```
cena/index.js   1.329 → 934      abas/index.js   2.349 → 1.663
```

**O eixo do corte é DOMÍNIO, não esfera.** A objeção do v58 era que seis renders aparecem em duas
ou três esferas e teriam de ser arbitrados. O obstáculo some quando o eixo muda: o comparador é um
domínio que duas esferas consomem — e módulo importado por dois lugares é a coisa mais banal que
existe. As seis telas "compartilhadas" nunca foram um problema; eram um problema do eixo errado.

`vinculos` era o caso difícil e prova a mesma regra: o domínio vivia em **duas faixas separadas por
quatro blocos alheios** — o mesmo "interleavamento" que o v58 apontava. Interleavamento é obstáculo
para recortar **texto**, não para cortar por domínio: as faixas só se referenciavam por nome, e
nome não tem endereço.

Um ciclo `index ↔ fundo` apareceu e foi desfeito com a folha `cena/ponteiro.js` — mesmo remédio de
`capacidade/estado.js`. **ESM resolve ciclo e o bundle não reclama, e é por isso que ciclo é
perigoso:** não quebra nada hoje e amarra os dois arquivos para sempre.

Nenhum chamador mudou: os módulos novos são reexportados pelos `index.js`. Trocar o corte **e** a
lista de imports de todo mundo na mesma passada é como se perde a capacidade de dizer o que
quebrou.

### 3.4 · O primeiro domínio fora da ponte (era §6.2-C)

```
TETO_GLOBAIS  70 → 58        handlers inline  168 → 155
```

Os 12 `vinc*` viraram delegação por `data-vinc` no **documento** (não no `#view`, que é trocado a
cada navegação). Vínculos foi o primeiro por três razões conferíveis: 12 nomes (o maior bloco
coeso); os 12 são handlers de **zero argumento**, então o `data-*` carrega tudo o que o `onclick`
carregava — o que **não** vale para `ir('e_resp')` ou `abrirDossie(cnpj,nome)`; e vivem todos numa
aba só. A migração **ganha** acessibilidade: os doze já eram `<button type=button>` e passam a ser
operáveis por teclado nativamente, sem depender do `a11yfy`.

### 3.5 · O frescor mostra o veredito da rota (era §6.3-a)

`/api/fontes/frescor` já classifica cada fonte com o critério **dela** (a folha do Estado é mensal,
o PNCP é semanal — 6 dias significa coisas diferentes nas duas), e a tela jogava isso fora para
reclassificar por idade crua com um corte único em 14 dias. Medido: PNCP com 6 dias e estado
`atencao` aparecia **neutro**, igual a uma fonte coletada hoje.

Três canais redundantes de propósito: glifo `§fonte` (forma), palavra (texto) e cor. Cor sozinha
reprova em daltonismo. `sem_medicao` é uma quarta linha e **não** sinônimo de crítico — fonte sem
idade apurada não é fonte parada, é fonte sobre a qual não se sabe.

---

## 4. As ferramentas novas, e o buraco que cada uma tapa

| ferramenta | o buraco |
|---|---|
| `tools/painel_modulo_livre.py` | `X is not defined` no primeiro quadro. Achou o dossiê quebrado. **No gate.** |
| `tools/painel_computado.py` | A prova de que uma mudança de cascata não mudou nada: hash do estilo computado de 60 abas × 2 larguras, antes e depois. |
| `tools/painel_css_camadar.py` | Aplica `@layer` mantendo toda regra com `!important` numa cauda não-camadada. **Só entra com diff vazio.** |
| `tests/test_painel_revelacao.py` | As três leis do estrato v59 provadas no arquivo, incluindo a armadilha do v43. **No gate.** |

---

## 5. O QUE FALTA

### 5.1 · `@layer` — DUAS INVESTIDAS, e a segunda parou no INSTRUMENTO

**Não entrou.** E a razão da segunda tentativa é diferente da primeira, o que é um progresso.

#### 1ª investida — reprovou por um bug REAL, e ele foi corrigido

96 telas, 188 elementos acusados, **100% deles `.btn`**: o botão fantasma trocava o fundo escuro
por um âmbar de outra geração. Causa exata: o bloco do v54 que compõe o fundo do botão tem o
próprio comentário dizendo que conta com especificidade — *"só o `.btn` puro adoeceu:
`.ghost/.accent/.red/.green` têm duas classes e ganham a cascata"*. Dentro de uma camada isso
continua verdade; **entre** camadas a especificidade não conta.

Corrigido com uma escotilha que diz, ao lado da regra, a que camada ela pertence:

```css
/* @camada: base — este bloco DEFINE o botão base; não sobrescreve ninguém. */
.btn{ … }
```

E, para não descobrir uma família por vez a ~1 h por rodada de navegador,
**`tools/painel_css_inversao.py`**: ele lista, em segundos, todo duelo cujo vencedor muda ao
camadar. Hoje: **zero**, com 11 blocos marcados (2 no v54, 10 no v55, todos definições do botão e
da esfera). Ele também teve de aprender três vezes:

| versão | resultado | causa |
|---|---|---|
| 1 | 47 acusações, quase todas impossíveis | comparava por "última classe do seletor" — `.sph .i .jico` contra `.chip .jico` |
| 2 | **zero, com o bug conhecido presente** | `_compativel` dependia da ORDEM: para `.btn.ghost` × `.btn` testava se `{btn,ghost}` cabia em `{btn}` |
| 3 | 31, todas sem efeito | comparava PARES; um terceiro seletor já resolvia o duelo nos dois mundos |
| 4 | 5 reais, e acha o `.btn` quando desmarcado | vencedor EFETIVO do conjunto, não duelo par a par |

> Antes de usar um detector, faça-o achar o bug que você **sabe** que existe. A versão 2 dizia
> "nenhuma inversão" com o `.btn` intacto na frente dela.

#### 2ª investida — o instrumento não sustenta o veredito

Com as 11 marcas, a comparação viva caiu de 96 para **20 telas**, e nelas não sobrou um `.btn`
nem um `.card`. Parecia pronto. Então rodei o **controle**: a mesma comparação, mesmo baseline,
**sem camadagem nenhuma**.

```
camadado   20 telas acusadas
CONTROLE   88 telas acusadas   ← com ZERO mudança de CSS
```

O controle acusa mais que o experimento. Ou seja: **o resíduo não é da camadagem, e o comparador
ainda não é estável o bastante para certificar essa mudança.** Há pelo menos uma variável solta
que ele não congela — a sonda `body.art-no` é assíncrona e chega antes ou depois da foto, e a
largura de `div.v` depende do instante do `_countUp`.

Ficaria fácil declarar vitória com o "20 contra 96". O controle é o que impede — e é por isso que
ele foi rodado.

#### O que falta, concretamente

1. Congelar a última variável: `body.art-no` (esperar a sonda) e excluir a LARGURA de `.kpi .v`
   sem perder a cor dele.
2. Repetir o controle. Ele tem de dar **zero** antes de qualquer veredito valer.
3. Só então aplicar e comparar.

O que já está pago: a escotilha, as 11 marcas, o detector estático validado, a fixture de dado
congelado (69 rotas) e o baseline. Quem retomar não recomeça — retoma no passo 1.

```bash
PYTHONPATH=. .venv/bin/python -m tools.painel_css_inversao          # zero antes de aplicar
PYTHONPATH=. .venv/bin/python -m tools.painel_computado --gravar data/computado-antes.json
PYTHONPATH=. .venv/bin/python -m tools.painel_computado --comparar data/computado-antes.json
#   ↑ ESTE É O CONTROLE: sem mudar nada, tem de dar zero. Só depois aplique o camadar.
```

### 5.2 · Baixar mais o teto da ponte (58)

O caminho é o mesmo: delegação por `data-*`, um domínio por commit. Os que sobram levam
**argumento** (`ir('e_resp')`, `abrirDossie(cnpj,nome)`), então a tradução precisa de
`data-*` com o argumento dentro — mais trabalho por nome do que Vínculos deu.

### 5.3 · Arte — o catálogo continua fechado

Nenhuma peça com consumidor está faltando. Confira antes de gerar qualquer coisa:

```bash
grep -rhoE "assets/[A-Za-z0-9_.-]+" static/css/src static/js/src static/*.html | sed 's|assets/||' | sort -u
```

As texturas de *metal escovado* e *vidro líquido* continuam **não geradas de propósito**: não há
superfície pedindo por elas. Arte sem call-site é peso no repositório e mentira no catálogo.

---

## 6. Coisas que vão te morder se você não souber

1. **A VM é compartilhada com outra sessão Claude.** O índice do git é compartilhado: um `git add`
   alheio leva os seus arquivos. Nesta sessão isso aconteceu — os 23 arquivos da v59 entraram no
   commit `489519a6`, cuja mensagem fala de outra coisa. **Commite por caminho explícito**
   (`git commit -- <paths>`), nunca `-a` nem `add -A`, e confira `git log --name-only` depois.
2. **CRLF quebra o gate na VM.** `for f in $(git diff --name-only); do file "$f" | grep -q CRLF && sed -i 's/\r$//' "$f"; done`
3. **`pgrep` casa a si mesmo** quando o padrão está na linha de comando do próprio pipeline. Já
   levou a "ainda está rodando" sobre processo morto duas vezes nesta sessão.
4. **`| tail -N` num comando longo segura TODA a saída até o fim.** Um baseline de 33 minutos
   pareceu travado por causa disso.
5. **Nunca `pkill -f`** — `pgrep` + `kill` por PID. O painel é `systemctl --user restart jfn`.
6. **`e_alertas` vazio no laboratório local é esperado.** Em produção ela responde.
7. **Não medir FPS em aba oculta** — o Chrome congela o rAF e a conta dá ~0.

---

## 7. Números de referência (medidos nesta sessão)

| medida | valor |
|---|---|
| `cena/index.js` | 1.329 → **934** (+ 6 módulos) |
| `abas/index.js` | 2.349 → **1.663** (+ 3 módulos) |
| globais exigidos por handler inline | 70 → **58** (19 escritos) |
| handlers inline | 168 → **155** |
| efeitos de topo no boot | **27**, em contrato |
| símbolos da casa vigiados por `painel_modulo_livre` | **250** |
| `sec(` sem definição no bundle anterior | **7** |
| `!important` no CSS | **15** — 8 degradação, **7 não** |
| `painel_boot_check --todas` | **60 abas, zero pageerror** |
| dossiê depois da correção | 3.739 caracteres, zero erro |
| órbita a 1600px | 4 instrumentos de cada lado · 8 linhas · 40 cartões em opacidade 1 |
