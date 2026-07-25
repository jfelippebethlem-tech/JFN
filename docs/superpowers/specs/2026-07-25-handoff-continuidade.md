# Handoff — estado em 25/07/2026 (sessão da noite)

**Para retomar:** *"continue pelo docs/superpowers/specs/2026-07-25-handoff-continuidade.md"*.
Branch: `feat/painel-v8-melhorias` — tudo commitado e **no remoto** (`53dce811` → `e456b679`).

---

## 0 · LEIA ISTO PRIMEIRO — três armadilhas de método que custaram caro

Não são detalhes de implementação; são as coisas que fizeram trabalho ser refeito.

### 0.1 Auditoria visual sem desligar o cache não vale nada

O Chrome do CDP **reusa a folha de estilo antiga**. Passei rodadas "corrigindo" o mesmo
sintoma achando que a regra não pegava — a regra pegava, eu é que via CSS velho. O dono
viu o defeito na tela dele antes de mim.

```python
cmd("Network.enable"); cmd("Network.setCacheDisabled", {"cacheDisabled": True})
cmd("Page.navigate", {"url": "http://127.0.0.1:8000/painel"})
```

Já está em **todos** os scripts de auditoria. Se criar um novo, ponha também.

### 0.2 FPS medido nesta VM não mede nada

São **4 fps mesmo com TODOS os canvas parados** — Chrome headless com SwiftShader por
software, 2 vCPU. O que mede é **ms/quadro do desenho**: instrumente o `requestAnimationFrame`
e leia mediana/p90. Orçamento a 60fps = 16,6 ms.

### 0.3 Comparar suíte por CONTAGEM de falhas esconde regressão

50 antes e 50 depois pode ser 50 falhas **diferentes**. Compare **nome a nome**:

```bash
grep "^FAILED" log | sed 's/ - .*//' | sort > agora.txt
comm -13 base.txt agora.txt    # novas falhas = regressão
```

---

## 1 · O QUE DEPENDE DE VOCÊ

### 1.1 Adobe — o MCP já está conectado, falta só reiniciar a sessão

`claude mcp list` → **`claude.ai Adobe for creativity: https://adobe-creativity.adobe.io/mcp — ✔ Connected`**.
Servidor MCP **oficial** da Adobe (HTTP streamable, OAuth do próprio usuário) ligando
Photoshop, Lightroom, Illustrator, **Firefly**, Premiere, **Express**, InDesign e Stock.

**Ferramentas de MCP entram no conjunto do assistente no INÍCIO da sessão.** Ele foi
conectado com a sessão já aberta, então ela não as enxerga. **`/clear` resolve.**

> Correção de rumo registrada: horas antes eu havia concluído "não existe conector Adobe".
> Estava certo naquele instante e virou falso. A distinção que faltava: a **Express API
> REST** é que exige Admin Console empresarial — o **MCP é outro caminho**.
> `claude mcp list` é a fonte da verdade, não a memória da sessão.

### 1.2 Painel — a foto de referência

O painel foi reformulado sem a foto que você mandou ao Yoda (ela nunca chegou ao disco da
VM). Se a direção que você tinha em mente é outra, **anexe a foto no chat** ou salve em
`~/JFN/docs/referencias/`.

### 1.3 Yoda — 413 com foto: **verificado**, falta só o teste ao vivo

Patch `6f222a1a2` (`hermes-agent`) sobreviveu ao auto-update das 04:00 e está em HEAD.
Testado com foto sintética pesada:

| | antes | depois |
|---|---|---|
| dimensão | 4000×3000 | 1568×1176 |
| **payload base64** (o que estourava o corpo do provedor) | **11,16 MB** | **1,60 MB** |

Original em tamanho pleno preservado (`img_*.orig.jpg`). Falta mandar uma foto pesada no
Telegram para confirmar o caminho vivo.

---

## 2 · PENDENTE — o que estava em andamento quando a sessão fechou

1. **Movimento no conteúdo das abas.** Botões, chips e abas já têm a camada holográfica
   (§3.5), mas **tabelas e listas continuam paradas** — a aba `g_radar` tem 100 linhas
   completamente estáticas. Ideias já levantadas e não implementadas: cascata na entrada
   das linhas (`--li` por índice), varredura na linha sob o cursor (só `background-position`,
   sem layout), medidor de severidade honesto no score, scan no `thead`.
2. **Leitura e análise de processos SEI** — nem começou. A fila por dinheiro tem
   **18.843 processos nunca tocados, R$ 2,11 bi** (`tools/sei_fila_por_dinheiro.py`).
3. **VLM local para fotos de medição** — `foto_medicao.avaliar_fotos(descrever=…)` pronto e
   injetável; falta subir **moondream2** ou **SmolVLM** em llama.cpp na VM-2.
4. **Consulta à SEFAZ por chave de NF-e** — `nfe_verifica.situacao(consultar=…)` pronto; o
   caminho gratuito é o portal público com captcha pelo **ddddocr local** (já na VM-2).
5. **I.D.E.A.S** — R$ 3,56 bi pelo Fundo Estadual de Saúde (UG 296100), 124 processos SEI,
   743 OBs. Com o motor calibrado, vale o dossiê dedicado.
6. **Fracionamento pelo SIAFE** — 4 casos com prioridade ≥ 0,7 em 2024; o primeiro
   (4ID MÉDICOS, UG 294200) tem 12 pagamentos, 12 processos distintos, todos ≥ 80% do teto.

### Dívida consciente (medida, não corrigida de propósito)

`reporting.intel_base.moeda(None)` devolve **`0,00`** — afirma que o valor é zero, contra
`INDISPONÍVEL ≠ 0`. **Não foi mexido**: a função tem **178 chamadas** e mudar a semântica
derrubaria os goldens em massa. Nos 152 sítios corrigidos o risco é nulo (todos já
pressupunham valor numérico; hoje `f"{None:,.2f}"` levantaria `TypeError`).

---

## 3 · O QUE FOI FEITO

### 3.1 Painel v12 "HOLOMESA" — 3D de verdade no núcleo

O núcleo virou **mesa de holograma**: o território do RJ é o **chão** (perspectiva com
divisão por z), os domínios **flutuam** em três altitudes presos por feixe e pegada de luz,
e no centro está o projetor. Profundidade vem dos quatro sinais que faltavam — divisão por
z, oclusão por ordem de pintura, paralaxe do cursor, contato com um plano.

O piso é assado em bitmap ortogonal e deformado em **faixas afins** (a projeção é afim
dentro de uma faixa fina — é o que `setTransform` sabe fazer), com cache invalidado só
quando a câmera se move.

**Território com espessura e giro.** Vira **laje**: parede lateral até `ESP=0.045`, tampo de
vidro fumê (que esconde a parede de trás, como deve) e a malha projetada na altura da laje —
sem isso o contorno deitado lê como decalque. E **girado ~16°** (`HOLO.GIRO`), porque o RJ é
largo no eixo leste-oeste e a placa é redonda: alinhado ao eixo x ele deixava as pontas da
elipse vazias. O contorno de mundo recebe o **mesmo giro**, senão a parede descola da malha.

**Aro da mesa** — sem limite físico o olho lê fundo, não objeto.

### 3.2 Arc reactor e nós

**Reator** (billboard, voltado para a câmera — deitado no piso ele era só mais um anel de
chão): carcaça com bisel claro por dentro e sombra por fora, 10 bobinas radiais, 24
entalhes, **brasa laranja por dentro** (estava inteiro em azul-íon, que é o polo do
console: sem a chama lia como instrumento, não como fonte), triângulo icônico, graduação de
72 ticks. Tudo em `Path2D`: **56 arcos + 72 ticks viraram 6 traços** — mais detalhe por
menos custo.

**Nós com relógio próprio**: período e fase derivados do índice (determinístico — gerador
aleatório em cena é proibido pela casa). Brackets de mira que abrem e fecham com a
respiração, câmara hexagonal contrarrotante, anel de ping no período do domínio, pacote de
energia subindo o feixe, suporte no pé. *Sete pulsos em compassos diferentes = vivo; no
mesmo compasso = pisca-pisca de natal.*

**Identificação no lugar**: o rótulo fica junto do nó (clicável), com empurrão radial a
partir do centro do **próprio anel** (usar o centro do piso empurrava todos para cima,
porque todo nó flutua acima dele), anti-colisão com o mais próximo decidindo primeiro, e
trava dentro da caixa. A cura de raiz do empilhamento **não é algoritmo, é geometria**:
fase fixa e distribuída por anel, com uma velocidade só.

**Áreas reservadas** na lista de colisão: o **reator** e a **pílula de sweep** — nenhum
rótulo pousa em cima deles.

### 3.3 Orçamento de vida

A mesa **para de desenhar** quando sai da viewport (`IntersectionObserver`, `rootMargin:80px`)
— não havia **um** observador no arquivo, e ela seguia a 60fps depois que o usuário rolava
para as tabelas. Provado nas quatro transições lendo `__nuEstado()`.

### 3.4 Custo — medido a cada rodada

| Momento | mediana | p90 | teto |
|---|---|---|---|
| v12 inicial | 0,9 ms | 1,1 | 3,0 |
| + laje e aro | 1,1 | 2,3 | 6,0 |
| + rótulos por `left/top` ❌ | 1,5 | **8,5** | 11,5 |
| + rótulos por `transform` ✅ | 1,5 | 3,9 | 4,8 |
| + reator detalhado (batelado) | 1,4 | 3,5 | 5,7 |
| + `offset*` da pílula por quadro ❌ | 3,9 | 9,8 | **44,7** |
| + geometria em cache ✅ | 1,5 | 3,8 | 22,5 |
| + nós com relógio próprio | 1,6 | 5,4 | 10,5 |

**As duas lições de layout**, ambas medidas: posicionar por `left/top` a cada quadro dispara
**layout** 60×/s; ler `offset*` depois de escrever estilo força **layout síncrono**. Ambos se
resolvem com `transform` + cache de geometria.

### 3.5 Holograma universal (v12.3)

Todo acionável (`.btn .chip .tab .lnk .ck-inst .nu-chip .htop a`) recebe um
`<i class="hlx">` — **elemento real, não pseudo**, porque em `.btn` e `.chip` os dois
pseudos já estão ocupados desde o v7/v9. Atraso `--hd` por contador global: cada peça
respira num tempo diferente. Um `MutationObserver` alcança as abas ainda não renderizadas.
Medido: **67 acionáveis nas 9 abas, 67 com camada**.

> **Cantoneira só onde há área.** Num controle de 90×36 px os quatro cantos quase se
> encontram e o olho lê **borda quebrada** — foi a "lambança" que o dono viu. Bracket ficou
> nas superfícies grandes; botão/aba/chip receberam um **aro que acende por dentro**.

> **REGRESSÃO GRAVE que essa camada causou** — e a mais fácil de repetir: a regra incluía
> `.nu-chip{position:relative}`, o que **sobrescreveu** o `position:absolute` dos rótulos.
> Em `relative` o `top` desloca a partir da posição de **fluxo** em vez de definir a
> posição: os `top` inline continuavam certos (373/373/408/408) e o render saía empilhado
> (374/403/467/496). Quebrou celular e desktop. **Ao adicionar uma camada, nunca imponha
> `position` a quem já está posicionado.**

### 3.6 "Ninhos de fachada não carrega" (relatado pelo dono) — fechado

Reproduzido: `/api/intel/hub_compartilhado` **não respondia em 90 s**. Três metades:

- a rota calculava **ao vivo** o cruzamento do dump da Receita (6,1 mi de estabelecimentos)
  com as OB, enquanto o sweep escreve no `compliance.db` — e havia um **cache em disco
  pronto**, com exatamente esses parâmetros, que ela não lia (`ler_cache_intel`);
- `J()` do painel usava `fetch` **sem `AbortController`**: rota lenta não virava erro,
  virava um card parado em `—`, indistinguível de "não há dado";
- o preenchimento falhava em **silêncio** (`if(!d||!d.ok)return`).

Agora: **3,4 s, 88 ninhos de risco alto, R$ 16,1 bi**, com `do_cache` e a data da apuração
na tela — dado de ontem não se apresenta como de agora.

### 3.7 R$ no padrão brasileiro — 152 lugares + trava

`f"{v:,.2f}"` produz `57,208.00`, que no Brasil se lê **cinquenta e sete reais**. Havia
**164 linhas** montando `R$` assim. 152 trocas em 57 arquivos para `reporting.intel_base.moeda`,
reusando o formatador **local** onde já havia um. `tests/test_moeda_padrao_brasileiro.py`
varre o código e **falha se voltar**.

> O `_brl` de `editais/teste_finalistico.py` é um **parser** (`str→float`): usá-lo seria bug,
> e o script de transformação o rejeita explicitamente. E `"{:,.2f}".format(x)` tem
> placeholder **vazio** — a substituição ingênua gerou `moeda()` sem argumento em 6 sítios;
> quem pegou foi o `ruff` do pre-commit.

**Suíte: 2.524 passando, as MESMAS 50 falhas de ambiente da VM-2**, comparadas nome a nome.

### 3.8 Contraste — `--dim` estava abaixo do mínimo da casa

Medido: 4,22–4,47:1 nos textos de 9,5–12px, abaixo do 4,5:1 que a `PRODUCT.md` declara
obrigatório. **L=0.60** é o menor passo que resolve (**4,78:1**) sem encostar em `--mut` e
apagar um degrau de hierarquia. Depois: **0 violações e 0 não medidos nas 9 abas**.

`tools/auditar_contraste.py` guarda o auditor. Três coisas que ele aprendeu, cada uma
nascida de um laudo falso que ele mesmo deu: resolve a cor **pintando 1px num canvas**
(ler `oklch(...)` com regex de dígitos inventa número), **compõe o fundo camada a camada**
até um opaco, e lê só a **primeira** camada de `background-image` — declarando "não sei
medir" quando não sabe.

### 3.9 Ponte do Adobe Express (independe do MCP)

`tools/express_ponte.py`:
- `--spec` — identidade do painel (paleta **OKLCH→HEX**, fontes, medidas, teto de peso).
  Conversão conferida contra os cinco pontos de referência do sRGB;
- `--gerar <alvo>` — o painel gera a **própria arte** na paleta dele, pelo Pollinations,
  grátis, ~2 s. *O 403 do primeiro teste era o `User-Agent` `Python-urllib`, que eles bloqueiam;*
- `--importar` — valida (recusa `.png` que é texto), versiona e imprime o trecho pronto.

---

## 4 · COMANDOS

```bash
# suíte (na VM-2, deixa a VM-1 livre) — compare nome a nome com as 50 de base
./tools/testar_na_vm2.sh

# auditoria de contraste no navegador que já roda na VM (CDP 9222)
.venv/bin/python tools/auditar_contraste.py

# ponte do Express
.venv/bin/python -m tools.express_ponte --spec
.venv/bin/python -m tools.express_ponte --gerar portal --seeds 3
.venv/bin/python -m tools.express_ponte --importar

# painel (o serviço leva ~20 s para responder: faz login SIAFE no boot)
systemctl --user restart jfn && sleep 25 && \
  curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/painel
```

**Auditar o painel sem chutar:** CDP na 9222 com
`websocket.create_connection(..., suppress_origin=True)` (sem isso o Chrome recusa com 403)
**e `Network.setCacheDisabled`** (§0.1). Recorte de elemento: `getBoundingClientRect()` em
`clip` com `scale:2`. **As variantes é que revelam o defeito** que a tela normal esconde:
`Emulation.setEmulatedMedia` com `prefers-reduced-motion:reduce` (achou a mesa em branco e o
ticker vazio) e `setDeviceMetricsOverride` a 390px (achou a mesa esmagada e, depois, os
rótulos fora da caixa).

**Ganchos de auditoria no painel** (existem para isto, não são código morto):
`window.__holoCam` (estado da câmera) e `window.__nuEstado()` (visibilidade + rAF do laço).

**Regras da casa que valeram em cada passo:** OB é pagamento (empenho não); INDISPONÍVEL ≠
irregular; indício ≠ acusação; nunca dessaturar o que já brilha; e **a VM tem 2 vCPU** — um
pesado por vez.
