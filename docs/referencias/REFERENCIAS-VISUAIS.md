# Referências visuais — painel JFN "Controle Externo"

O sistema visual do cockpit, escrito para poder ser **conferido e cobrado**.
Cada decisão traz o motivo e, onde existe, a medição que a sustenta.

---

## 1. A ideia

Um **cockpit de auditoria**: quem senta aqui está caçando dinheiro público mal
gasto. O teatro holográfico existe para **orientar** — cor diz de quem é o
dinheiro, ritmo diz o quanto é grave, luz diz o que está vivo — e nunca para
decorar. Toda peça que não informa nada foi cortada ou nunca entrou.

Registro (impeccable): o painel é **register product** — design SERVE a tarefa.
A tensão com "Jarvis ultrafuturístico" foi resolvida assim: o espetáculo mora
na **abertura** e nas **camadas de fundo**; o dado lê primeiro em toda tela de
trabalho.

---

## 2. Cor — as quatro esferas

A cor não é enfeite: ela responde **de quem é o dinheiro**.

| esfera | cor | o que é |
|---|---|---|
| `inicio` | ciano-íon | command deck ao vivo |
| `estado` | ciano-íon | órgãos estaduais (SIAFE + PNCP) |
| `prefeitura` | âmbar-ouro | município do Rio (PNCP + folha) |
| `geral` / transversal | violeta | riscos, busca, poder, ferramentas |

Tudo que é interativo herda `--esf`: a onda de toque, o trilho da malha, o
brilho do ícone ativo, o carimbo da linha. **Trocar de esfera troca a cor de
todo o circuito** — é o sinal mais barato de "você mudou de jurisdição".

Fundo: `oklch(0.035 0.014 265)` — azul-marinho quase preto, tinta 0.014 na
direção da marca. Não é preto puro (preto puro achata o brilho) nem cinza
neutro (cinza neutro apaga a identidade).

**Contraste:** corpo ≥ 4.5:1. O `--mut` foi puxado para `oklch(0.70 0.019 265)`
justamente para o texto de apoio e o placeholder não caírem abaixo do mínimo —
cinza claro "por elegância" é o defeito nº 1 de painel escuro.

---

## 3. Tipografia

| papel | fonte | por quê |
|---|---|---|
| display / rótulo técnico | **Orbitron** (variável) | dá o tom de instrumento |
| dado, número, código | **IBM Plex Mono** | tabular, alinha coluna |
| texto corrido | **IBM Plex Sans** | leitura longa |

Todas **self-hosted** em `/static/assets/fonts/` — sem CDN, o painel abre em
rede fechada.

**Medido e corrigido:** o subset do Orbitron **não tem** `· → ↔ ₂ º ª § ✓ ✗`,
e nem Plex Mono nem Plex Sans têm `✗`. Estado de sistema virou **sinal**
(ponto colorido com `aria-label`), não dingbat — sinal não depende de fonte.
`unicode-range` trava o Orbitron no que ele cobre.

---

## 4. Profundidade — o 3D angulado

O painel inteiro assume **uma câmera**: peças vistas de canto, nunca de frente.

- `--ico3d: perspective(180px) rotateY(-13deg) rotateX(5deg)` — o ângulo comum
- **Extrusão**: pilha de três `drop-shadow` na cor da esfera, cada camada
  seguindo o contorno do glifo. Lê como chapa recortada com lateral, não como
  sombra colada atrás. Três degraus: mais vira borrão em 18px, menos não fecha
  a lateral.
- `--lift`: o relevo dos cartões. **Bisel com spread negativo** (`-0.5px`) —
  sem isso, em tela de DPR fracionário a linha do bisel e a borda caem em
  subpixels diferentes e o cartão ganha **contorno fantasma**.

> **Regra sem exceção:** nenhum quadro de animação pode deixar o alvo de clique
> **menor** do que ele parado. Quebrada duas vezes nesta sessão (uma animação
> partia de `scale(.8)` espelhado; depois eu somei ângulos e cheguei a -55°,
> achatando o ícone para 12,3px). A entrada agora parte de **maior e mais aceso**.

---

## 5. Movimento — o que se move e por quê

| camada | o que faz | regra |
|---|---|---|
| **abertura** | vídeo em loop do reator (Gemini) com a imagem de `poster` | 1,96s + 0,42s de saída |
| **transição de aba** | View Transitions: cabeçalho e abas **parados**, miolo recua e o novo chega da frente | profundidade, não troca lateral |
| **malha de energia** | trilho vertical + pulso + barramento horizontal com corrente | `pointer-events:none` |
| **tato** | afunda 1px, onda de luz onde o dedo tocou, carimbo na linha | `pointerdown`, não `click` |
| **cascata** | conteúdo entra escalonado por `nth-child` | teto de 380ms |

**Duas leis aprendidas na marra:**

1. **Reveal nunca parte de `opacity:0`.** Animação de CSS congela em aba de
   segundo plano; um reveal partindo de zero deixa a aba **em branco** para
   quem volta o foco no meio. A cascata parte de `.35`.
2. **Animação que segura a tela precisa de trava independente de quadro.** O
   `requestAnimationFrame` congela em aba oculta: a abertura media o tempo com
   `performance.now()` mas só avançava no rAF, então ficava presa — e ao voltar
   o foco corria todos os quadros de uma vez (o "rápido e embaralhado").
   Agora há `setTimeout` + `visibilitychange`.

Tudo respeita `prefers-reduced-motion`.

---

## 6. As peças de arte

Ordem de produção (regra do dono): **imagem → ChatGPT · vídeo → Gemini ·
Firefly → animações**, por último (créditos do Express são limitados).
Nunca *codar* imagem à mão.

| arquivo | onde entra | origem |
|---|---|---|
| `portal-hero.mp4` | abertura, vídeo em loop | Gemini |
| `portal-hero.jpg` | poster do vídeo + nebulosa do `inicio` | Gemini |
| `nebula-estado.jpg` | fundo da esfera estado | Firefly |
| `nebula-prefeitura.jpg` | fundo da esfera prefeitura | Firefly |
| `nebula-transversal.jpg` | fundo da esfera transversal | Firefly |
| `reator-core` · `mesa-projecao` · `selo-anel` · `trilho-hud` | núcleo, mesa, selos | Firefly |

**Reprovado e por quê:** ícones raster gerados por texto-para-imagem. Duas
tentativas saíram com forma preenchida e espessura desigual — text-to-image não
produz sistema de ícone com traço uniforme. Os ícones são **vetores Lucide
(ISC)**; o que faltava neles não era desenho, era profundidade, e isso veio da
extrusão.

---

## 7. Proibições

- **Faixa lateral colorida** (`border-left` grosso) — lê como enfeite de
  template. Gravidade vem da borda inteira mais tinta de fundo. *(Estava no
  bloco de veredito do cockpit; removida.)*
- Texto com degradê, glassmorphism decorativo, eyebrow em toda seção.
- Vazio que não ensina: "aguardando…" virou "lendo o barramento — o número
  aparece aqui".
- Motion que não conta estado.

---

## 8. Como conferir (e me cobrar)

```bash
cd ~/JFN
.venv/bin/pytest tests/test_painel_abas.py tests/test_painel_css_integro.py -q
```

**Medir animação e canvas só com Playwright na VM, com a página em foco.**
Navegador automatizado reporta `visibilityState: "hidden"`, o rAF congela e
**todo canvas mede vazio** — isso me custou uma rodada inteira caçando um
defeito que não existia.

---

## 9. Sessão 2026-07-26 (noite) — v35→v43

- **v36 FACETA COM SENTIDO**: `data-nav-dir` (posto pelo `ir()`) gira o miolo
  em Y **para o lado do destino** — inclusive entre esferas (o `trocarEsfera`
  pré-atribuía `aba` e apagava o sentido; corrigido). `perspective()` dentro do
  próprio transform: pseudo-elementos de view transition não herdam cena 3D.
- **v37/v38/v41 ENCAIXE PROGRESSIVO**: vídeo da nebulosa por esfera, corpo do
  nó e núcleo-holo-RJ ligam sozinhos quando o arquivo aparecer em
  `static/assets/` (sonda HEAD; 404 = segue como está). `.on` só no evento
  `playing` — o Chromium do Playwright **não tem H.264**, então `play()` que
  resolve não prova quadro.
- **v39**: a lâmina do trilho v26 agora corre de verdade (12s, cor da esfera).
- **v40**: 7 contrastes de token fechados; holofeed 97% opaco (o pior pixel
  não pode depender da esfera). Auditor agora **zera one-shots de chegada**
  no congelar — mede o repouso, não o flash do barramento.
- **v42 COCKPIT DO SISTEMA**: g_sweeps virou a sala de máquinas (fila SEI com
  barra, arquivo compacto, pipelines SLO, aprendizados; refresh 30s em lugar).
- **v43 O KPI QUE SUMIA (lição dura, sintoma novo da armadilha velha)**: dentro
  de `.grid`, a `entraCascata` sobrescrevia a `rise` e, ao terminar
  (`backwards`), a opacity caía no **0 estático** da `.rise` — KPI invisível
  em toda aba com grid. O rastro no laudo eram as dezenas de "não pintou
  glifo". **Aba com área vazia + 'não pintou glifo' no auditor = procure
  animação sobrescrita, não dado faltando.**
- **Canal com o desktop (corrigido)**: o desktop tem duas identidades Syncthing
  — `FOGTP75` (morta) e `QBL7LAM`/"Desktop-JFN" (viva). O handoff falhava porque
  `shared-brain` só era compartilhada com a morta; agora está compartilhada com
  a viva (aguarda aceite lá). Reservas que funcionam: Taildrop, Telegram e o
  SSH deles→cá. Laço de confirmação por arquivo-recibo tocado via SSH.
