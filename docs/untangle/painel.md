# Decision log — untangle do painel (20/11/2026)

Escopo: `static/js/src/` (63 módulos: `entrada.js`, `abas/`, `ui/`, `cena/`, `v63/`, `nucleo/`…),
`static/jfn-painel.html` e o CSS (`static/css/src/` → `painel.css`). Rotas e servidor: só anotados.
Escolhas do dono: **Comentários = sim** (saem só os que repetem o código ou descrevem uma restrição que
já não existe; medição datada, decisão do dono e porquê de workaround ficam), **Testes = não**.
Restrição da casa: aparência e comportamento pretendido iguais — a refatoração é de estrutura.

Formato: o fix fica acima dos problemas que resolve. `[feito]` = aplicado nesta passada; `[pendente]` =
precisa de decisão do dono, muda o que a tela mostra, ou é redesenho maior que esta passada;
`[fora do escopo]` = anotado só.

Verificação de cada lote (contra o build do worktree, servido por um proxy local que entrega
`/painel` e `/static/*` do worktree e repassa `/api/*` ao servidor do 8000 — o servidor não foi
reiniciado nem tocado): `painel_build_check`, `painel_ponte_check`, `painel_boot_check --todas`
(77 abas), `painel_clique_check` (1440 e 390 px) e os testes `tests/test_painel_*.py` +
`test_v68_assets`, `test_v69_abertura`, `test_regra_catracas`, `test_regra_inventario`,
`test_cache_painel_swr`, `test_capacidade_pronta_tem_superficie`, `test_sintese_ligada_ao_360`.
Antes de tudo: boot 77/77 abas sem erro, clique OK, testes 223 passed / 6 skipped. A ordem de
avaliação dos módulos no bundle (63 seções `// static/js/src/...`) foi comparada a cada build.

## 1. Cada módulo importa de quem é dono do símbolo; o que ninguém lê sai  `[feito — lote 1]`

- `entrada.js` importa cada tela do módulo de domínio dela (`abas/cockpit.js`, `abas/comparador.js`,
  `abas/vinculos.js`) e a cena das folhas (`cena/fundo.js`, `cena/ponteiro.js`, `cena/portal.js`), em vez
  de passar por reexports; imports que ninguém lê saem; `export` sai do que só o próprio módulo usa.
  - `abas/index.js:2731-2752` reexportava 44 nomes de `cockpit.js`/`comparador.js`/`vinculos.js` só para
    "a linha de import do entrypoint não mudar uma vírgula" — 22 deles (`DRILL_ACOES`, `vincConsultar`,
    …, `VINC_ACOES`) nem o entrypoint importava. Era a porta de passagem que amarrava `abas/index.js` a
    três domínios que ele não usa.
  - `cena/index.js:977-979` (+ `export {_ckMX,_ckMY,cenaPonteiro} from './ponteiro.js'`) reexportava
    `portalStart`, `_rjCarregar`, `rjbgStart`, `netbgStart`, `_rjbgTinge` pelo mesmo motivo; o header
    do arquivo descrevia a porta.
  - `entrada.js:69` importava ~150 nomes de `abas/index.js`; 47 sem uso nenhum (`SEV_LEGENDA`,
    `TIPO_ALERTA`, `_CK`, `_DETS_ORFAOS`, `ckCard`, `ckFill`, `pollarPdf`, `frescorHtml`, …). No total,
    123 nomes importados e não usados em 10 módulos (`entrada.js` 64, `abas/index.js` 20, `cena/index.js`
    11, `cockpit.js` 9, `vinculos.js` 7, `ui/index.js` 7, …), sobra mecânica da quebra do monolito.
  - 83 `export` de símbolos que só o próprio módulo usa (`_ckTick`, `ckPull`, `_compBuscar`,
    `vincParentesco`…, `conscienciaAbrir`, `_spotPinta`, `v60Mais`, `linhaGenerica`…): a superfície
    pública mentia sobre quem depende de quem.
  - `entrada.js:21/30` importava `ritmo.js` duas vezes.
- Código morto apagado (zero referência em `src/`, HTML, CSS, `tests/`, `tools/`):
  - `cena/malha-rj.js::_rjBuild` (traçador do portal de ignição, que saiu na v63) e o comentário
    "Um só fetch serve o portal e o núcleo";
  - `abas/cockpit.js::_CK` (paleta hex), `ritmo.js::quadroInscritos`, `nucleo/drill.js::temDrill`;
  - `nucleo/drill.js::limparDrill` — "limpa o registro da aba anterior", nunca chamado desde que nasceu
    (ver pendência 9.4);
  - **`static/js/nucleo/`** — cópia acidental de `entrada.js`, `abas/index.js`, `abas/vinculos.js` e de
    `rotas/vinculos.py`, commitada em `54ef8bdb` (09/08) por um arquivo escrito no diretório errado.
    Estava sob `/static/js`, que o servidor publica: um `.py` de rota era servido como estático.
- Ligação escondida: `entrada.js::gerarPdfIntel` chamava `jfnToast` sem importar — funcionava só porque
  o esbuild achata todos os módulos no mesmo escopo do IIFE (a mesma família do `sessaoReports` de
  v59). Agora importa de `ui/index.js`. `tools/painel_modulo_livre` não pegou porque pula o
  `entrada.js` ("o entrypoint importa tudo") — ver pendência 9.5.
- Comentários que descreviam restrição que não existe mais:
  - `abas/index.js:1-12, 30-32, 74-75` — "declarado ANTES de `const TABS`, senão TDZ": o `TABS` mora em
    `entrada.js` desde a v59, outro módulo, avaliado depois; não há TDZ possível entre módulos.
  - `abas/index.js:2722` (setters de `_compView`… que foram para `comparador.js`), `entrada.js:192`
    (história do `sessaoReports`, já contada onde ele mora), `entrada.js:378-381` (dois cabeçalhos sem
    código), `entrada.js:423` (`VINC_ACOES` mora em `vinculos.js`), `cena/portal.js:1-2`.
  - `entrada.js:386-394` — dois comentários (barramento por gancho; vídeos no modo sóbrio) estavam 60
    linhas longe do código que explicam; foram para cima de `sabreStart(...)` e `sobrioAoMudar(...)`.
- Mantidos de propósito:
  - `cena/portal.js::portalStart` é um invólucro de uma linha (`aberturaStart(null)`), mas o nome é o
    que `tests/test_painel_ordem_de_boot.py` e `tools/painel_efeitos_boot.py` fixam na ordem de boot.
  - `ir()` continua com `if(typeof nebulaViva==='function')` e irmãos, embora sejam imports (sempre
    função): `tests/test_painel_vida_viva.py:50` exige o texto `nebulaViva==='function'`. Testes = não.
- Efeito no bundle: a ordem de avaliação dos módulos mudou só em `app/estado.js` e `cena/holomesa.js`
  (passaram para depois de `cena/fundo.js`), porque `fundo.js` deixou de importar `app/estado.js` sem
  usá-lo. Nenhum dos dois tem efeito de topo que dependa de ordem.

## 2. O que mais de uma aba usa mora em `nucleo/`; aba não importa aba  `[feito — lote 2]`

- `nucleo/http.js::cardErro(e)` é o cartão de falha de toda tela (a moldura em volta do `erroHumano`).
  - `card(\`<div class="warn">${erroHumano(…)}</div>\`)` escrito à mão 82 vezes em 15 módulos
    (`abas/index.js` 40, `vinculos.js` 18, `comparador.js` 7, `acervo.js` 3, …). Mudar a moldura do erro
    era mudar 82 linhas. HTML gerado idêntico.
- `abas/sistema.js` passa a ser dono do que a esfera Sistema mostra: `frescorMontar`,
  `blocoComandosMestres` e `abrirCapMestra` saem de `abas/cockpit.js`.
  - Os três foram para Sistema em 14/11 (pedido do dono) mas o código ficou no cockpit; `sistema.js`
    importava `cockpit.js` — e com ele `v63/inicio`, `cena/*`, `mapa/territorio` — só para isso.
  - Efeito colateral bom: `tests/test_cache_painel_swr::test_prewarm_cobre_toda_rota_da_home` lia
    `/api/fontes/frescor` como "rota da home" porque estava no arquivo do cockpit; não é mais.
- `nucleo/markdown.js` (novo): `mdNota` (a nota do vault) e `mdSimples` (negrito + código).
  - `abas/requerimentos.js` importava `mdNota` de `abas/casos.js` — aba dependendo de aba por um helper.
  - `comissao.js::_md` e `abas/index.js::_mdLim` (dentro de `renderFontesExternas`) eram a mesma linha.
- `nucleo/formato.js::normalizar` (sem acento, caixa alta).
  - `governo_couto.js:15` e `orcamento_orgao.js:18` tinham a mesma `_norm`.
- `governo_couto.js:229` e `acervo.js:334` chamavam `window.abrirDossie` atrás de `typeof`; agora importam
  de `ui/index.js`, como `casos`, `vinculos` e `cockpit` já faziam. (`window.ir` continua onde está:
  importar `ir` de `entrada.js` criaria ciclo — ver pendência 9.2.)

## 3. Versão que virou padrão perde o `if` — v60/v61/v63 são constantes  `[feito — lote 3]`

O `<head>` de `jfn-painel.html` liga `v60`, `v61` e `v63` em TODA carga (decisão do dono: claro
sempre, 11/11; v63 padrão, 17/11), então `_v60`/`_v61`/`_v63`/`_v61flag` são constantes verdadeiras.
Cada `if(!_v61)return;` e cada ternário `_v61 ? novo : antigo` era um ramo morto que o leitor ainda
tinha de pesar; e atrás de alguns deles havia módulos inteiros sem caminho de execução.
- Guardas e ternários removidos (comportamento idêntico, a condição era sempre verdadeira):
  `entrada.js` (título das esferas, centragem da aba ativa, View Transition, rótulo do cabeçalho),
  `abas/cockpit.js` (moldura `ck61`, herói v63, grade de cartões, reator/mapa/preocupações, contagem
  com flip), `ui/movimento.js`, `ui/jarvis.js`, `ui/v61.js`, `ui/vidro.js`, `ui/v60.js` (ícones do menu),
  `v63/index.js`, `mapa/territorio.js` (rampa de cor), `cena/index.js::nucleoViva` (`semAuto`).
- Código que só existia para o ramo "desligado" — apagado (≈2.000 linhas; bundle 1.049 KB → 980 KB):
  - `cena/index.js::nucleoStart` (≈650 linhas: o laço da mesa de vigília, trilhos, órbitas, HUD de
    sweep `nuSweepPoll`) — o cockpit só o chamava em `if(_v61){…} else nucleoStart();`.
  - `cena/holomesa.js` inteiro (câmera 3D da mesa; único consumidor era `nucleoStart`).
  - `cena/index.js::mesaViva` (piso vivo; começava com `if(_v60){…return;}`) e `holoRJ` (holograma do
    Estado; `if(_v60||…){apaga();return;}` — `body.holo-on` nunca era posto).
  - `ui/index.js::_wire` + `_ESF_RGB`/`_wireRAF` (malha de luz atrás dos cards; `if(_v60)return;`) e
    `_countUp` (o contador antigo de KPI, só chamado em `!_v61`; quem conta é `ui/movimento.js`).
  - `cena/index.js`: `_reatorArt` (pré-carga de `reator-core.webp` para o desenho da mesa — sai uma
    requisição de imagem no boot que ninguém usava), `_nuPulses`/`_nuFlux` (só escritos), `_swInt`.
  - `abas/cockpit.js`: a segunda grade de cartões (`else g.innerHTML=[…]`), `energiaLigar` no `!_v61`.
  - `capacidade/estado.js::_v61flag`.
- O que ficou com as bandeiras (preso por teste — §9.6): `nebulaViva`, `cena/fundo.js`
  (`rjbgStart`/`netbgStart`) e `cena/energia.js`. O comentário de `capacidade/estado.js` diz isso.
- Achado no caminho: `_nuHover` (estado escrito por `onpointerenter` nos chips da mesa) não tem mais
  quem o escreva nem quem o leia — os chips eram montados por `nucleoStart`. Continua na ponte porque
  `tests/test_painel_ponte_completa.py` trava `TETO_ESCRITOS = 19` e manda "baixe o teto" quando cai —
  e o extrator ainda conta 19 porque lê o COMENTÁRIO de `cena/index.js` que cita
  `onpointerenter="_nuHover='...'"`. Tirar `_nuHover` = baixar o teto para 18 (§9.6).

## 9. Pendente — muda o que a tela mostra, depende do dono, ou é redesenho maior  `[pendente]`

9.1 **Gancho "depois de pintar" por aba (a causa de quatro esperas e seis observadores).**
O `ir()` só chama algo depois do paint para o cockpit (`ckBoot`); toda outra tela que precisa mexer no
DOM que acabou de devolver espera por conta própria. Fix desenhado: `TABS` ganha `montar` opcional e o
`ir()` o chama depois de `pintar()` (o mesmo lugar do `ckBoot`); um evento `jfn:pintou` serve os
observadores. Não aplicado: muda o momento exato em que cada tela é montada (timing é o vetor que já
matou este boot 3×) e precisa de passada própria, aba a aba, com o boot_check de cada uma.
  - `abas/acervo.js:33 _quandoExistir` (50 ms, desiste em 5 s), `abas/sistema.js:18 _quandoExistir`
    (rAF, 180 quadros), `abas/periodo.js:42 _quandoNaTela` (50 ms × 200), `abas/casos.js:102 por()`
    (50 ms × 40), `abas/index.js:641 por()` (`#acu-lift`, 50 ms × 40), `abas/index.js:1063
    setTimeout(missaoListar,50)` — seis esperas com seis políticas.
  - `MutationObserver` em `#view` com atraso próprio: `ui/movimento.js:39` (90 ms), `ui/toque.js:155`
    (80 ms), `ui/v60.js:31/35` (60 ms), `ui/jarvis.js:143`, `v63/index.js:24`, `ui/index.js:69`.
  - `entrada.js` `if(aba!=='i_cockpit'){energiaParar();vivo();} else ckBoot();` — o `if` por id de aba.

9.2 **Navegação como módulo.** `ir`, `TABS`, `trocarEsfera` moram em `entrada.js`; quem precisa navegar de
dentro de um módulo chama `window.ir` (`acervo.js:330`, `v63/transicao.js:44`, `abas/index.js:3239`
com `typeof window!=='undefined'` num bundle que só roda no navegador) ou o `ir` livre que a ponte
põe no `window` (`abas/index.js:2640 sweep()`). Um `app/navegacao.js` com `ir` + `TABS` (o catálogo
importa os renders; os renders importam `ir`) dá o ciclo que o esbuild resolve mas a casa já decidiu
evitar (`cena/ponteiro.js`, `capacidade/estado.js`). Precisa de desenho: provavelmente `ir` com
registro tardio do catálogo (`registrarAbas(TABS)` no boot).

9.3 **Contrato de falha do `J()` — três leituras diferentes (muda o que a tela mostra).**
`J()` devolve `{erro}` SEM `ok` quando a rede cai ou estoura o teto de 30 s. Telas que testam
`d.ok===false` (`abas/index.js` 2028, 2766, 2811, 2857, 2889, 2956, 2996, 3033, 3116, 3152, 3193 — Poder,
painéis da fila do fiscal, lentes) não veem a falha e desenham "—" e zeros. `renderAlertas`
(`lst=[]` → "Sem alertas no momento 🟢"), `renderCartel` ("Sem dados de concentração"),
`renderValidar` ("Tudo revisado") e `_liftBloco` (`''`) mostram INDISPONÍVEL como zero — contra a
regra INDISPONÍVEL ≠ 0. O fix estrutural é `J()` sempre devolver `ok:false` junto com `erro` (uma
linha em `nucleo/http.js`), mas isso troca o que dezenas de telas mostram em falha de rede — é
correção de comportamento, para o dono decidir e conferir tela a tela. Junto: `try{await J()}catch`
inalcançável em `abas/index.js` 46, 1048, 3115, 3150, 3191 (o `J` nunca lança).

9.4 **`nucleo/drill.js::limparDrill` foi apagado como morto**, mas o comentário dizia "limpa o registro
da aba anterior — conjunto velho reaparecendo em tela nova é pior que nenhum". Nunca foi chamado. Se
a intenção vale, o lugar é o `ir()` antes de `pintar()`; é mudança de comportamento (pequena).

9.5 **`tools/painel_modulo_livre.py` pula o `entrada.js`** ("o entrypoint importa tudo") — e foi ali que
o `jfnToast` livre passou. Incluir o entrypoint fecha a família (fora do escopo: `tools/`).

9.6 **Testes amarrados à implementação seguram código morto** (Testes = não, então ficou):
  - `tests/test_painel_vida_viva.py:49-50` exige `function nebulaViva` e o texto `nebulaViva==='function'`
    no `ir()`. Desde a v63 `nebulaViva` começa com `if(_v63)return;` — a função inteira (sonda HEAD,
    vídeo por esfera, pôster) não roda nunca; os vídeos `nebula-*`/`v61/*` só são citados por ela.
  - `tests/test_painel_modo_sobrio_para_os_canvas.py:61-104` exige que `rjbgStart`/`netbgStart`
    consultem `_sobrio` — os dois fazem `if(_v60){cv.remove();return;}` na 2ª linha; o resto (≈90
    linhas de canvas) é inalcançável.
  - `tests/test_painel_ordem_de_boot.py:91` fixa `window.energiaCenso`: a órbita de energia do cockpit
    (`cena/energia.js`, 215 linhas) remove o próprio canvas no `energiaLigar` (v60) e
    `energiaPacote` volta na guarda `!_linhas.length` — o módulo só existe para o censo dizer "0".
    `rjbgStart` remove o canvas antes de pedir a malha, então `cena/malha-rj.js::_rjCarregar` também
    não roda mais.
  - Por isso `capacidade/estado.js` mantém `_v60`/`_v61`/`_v63`: os únicos leitores que sobraram são
    esses blocos presos por teste.
  - `tests/test_painel_ponte_completa.py:56` `TETO_ESCRITOS = 19` segura `_nuHover` (§3) e sua dupla
    get/set na ponte; o extrator `tools/painel_ponte_check` conta o nome porque lê comentários.

9.7 **Cópias que pedem decisão de régua (unificar muda o que aparece):**
  - Severidade 🔴/🟠/🟡 → rótulo/cor em 5 mapas que discordam: `acervo.js:12 GRAU` ignora 🟠,
    `ui/v60.js:104 _GRAU` chama 🟠 de "atenção", `casos.js:17` de "médio-alto", `conformidade.js:12
    _SEV`, `abas/index.js:2526 SEV_LEGENDA`.
  - Frescor de fonte com três limiares: `abas/sistema.js::frescorMontar` (≤2 / ≤10 dias, hex),
    `consciencia.js:145` (>14 dias), `abas/index.js::frescorHtml`.
  - `TIPO_ALERTA` (`abas/index.js:2518`) re-rotula `pcrj_d7/d9/d10` com ícone e texto diferentes dos de
    `_DET_ROTULO` (1707) para os mesmos detectores; `fracionamento`/`sobrepreco` sobrepõem
    `formato.ROTULOS`.
  - Selo VERIFICADO/PENDENTE escrito 5×: `_pdTag`, `_SNF_SELO`, `_VERIF_TAG` (`abas/index.js`),
    `_verifTag` (`governo_couto.js`), `_TAG` (`orcamento_orgao.js`). Quatro mapas força→cor
    (`_FORCA_CF`, `_FORCA`, `_VERIF_TAG`, `_ADT_ESTADO`).
  - Nomes de mês em 4 listas (`periodo.js:16-17`, `orcamento_orgao.js:16`, `mapa/territorio.js:54`,
    `comissao.js:93`); três contadores animados (`cockpit.js::_ckCount`, `v63/revelar.js::_contar`,
    `ui/movimento.js::_contar`); três `_hora`/`_ha` (`v63/inicio.js`, `propagacao.js`,
    `motores_cruzamento.js`) ao lado de `aovivo/formato.haQuanto`.
  - Sondagem própria de `/api/ao-vivo/estado` em `v63/moldura.js:30-45` (30 s) ao lado de
    `aovivo/estado.js` (SSE) com a mesma regra `motoresRodando`; `/api/sweeps/status` sondado a cada
    15 s por `cena/index.js:887` e por `consciencia.js:243`.

9.8 **Moldura repetida dos painéis da fila do fiscal (`#ff-out`).** 16 funções em `abas/index.js`
(114–422 e 2764–3067) repetem `o=$('ff-out');if(!o)return; d=await J(); if(!d||d.ok===false)return;
alvo=createElement('div'); …; o.appendChild(alvo)`. Um `painelFF(rota, montar)` resolve — mas o
`d.ok===false` é o defeito da 9.3; fazer os dois juntos.

9.9 **Comportamento visível achado no caminho (não corrigido):**
  - `abas/lai.js:88,91` põe `erroHumano()` (HTML: `<span>` + botão) dentro de `alert()` — o markup sai
    cru na caixa.
  - `abas/index.js:1477` (Riscos › Sancionadas): `acoesAba('sancionadas')` + `renderSancionadas('')`,
    que já põe o mesmo `acoesAba` — dois botões "Gerar PDF".
  - `abas/index.js:706` diz "Dez leituras" e `_DETS_ORFAOS` tem 12.
  - `abas/index.js:1301` a escalada registra o drill `'aditAcimaMercado'` com título de aditivos.

9.10 **CSS (`static/css/src/`, 39 estratos, 500 KB) — fora desta passada.** O próprio
`tools/painel_css_cortar.py` explica: o CSS é sedimentar (`.btn` declarado em 14 pontos) e cada estrato
sobrescreve o anterior por ordem de cascata; juntar por semântica é reescrever a cascata, o que muda
aparência. Regras de elementos que o JS já não cria (`video.mesa`, `body.holo-on`, `#holorj video`,
`.view-wire`, `#rjbg`/`#netbg` — removidos no boot) ficam como resíduo para uma passada própria com
auditoria visual (`tools/painel_computado.py`).

## 10. Fora do escopo (anotado, não mexido)

- `tools/painel_boot_check.py` e `tools/painel_clique_check.py` só medem o servidor do `JFN_BASE` — um
  worktree não tem como verificar o próprio build sem um servidor; nesta passada isso foi um proxy
  local (`/painel` e `/static/*` do worktree, `/api/*` repassado ao 8000).
- `tools/painel_build_check.py` compila com `cwd` no repositório; num worktree com `node_modules`
  como symlink o esbuild resolve o caminho real e o comentário de origem muda
  (`// ../../../node_modules/...`) — o check acusa defasagem falsa. Usar cópia por hardlink.
