/* AS GRAMÁTICAS DE REVELAÇÃO — camada 4 do plano visual (§6.3 do PAINEL-v58).
 *
 * O plano pedia "surpresas por aba: tabela monta linha a linha, ranking cresce de baixo para cima,
 * grafo desenha as arestas antes dos nós, comparador desliza as colunas em sentidos opostos".
 *
 * ESTE MÓDULO NÃO É POR ABA, E ISSO É A DECISÃO CENTRAL. Escrever quinze animações amarradas a
 * quinze `id` de aba cria quinze coisas para manter sincronizadas com sessenta telas que mudam
 * toda semana: aba renomeada perde a gramática em silêncio, aba nova nasce sem nenhuma, e ninguém
 * descobre porque falta de animação não quebra teste. As gramáticas aqui são acionadas pela FORMA
 * que a tela tem no DOM — tem tabela? monta linha a linha. É um ranking? cresce da base. São dois
 * rankings seguidos? entram por lados opostos. Uma aba nova ganha a gramática certa no dia em que
 * nasce, sem uma linha de cadastro, e uma aba que deixa de ser ranking perde a dela sozinha.
 *
 * A REGRA QUE DECIDE O QUE É RANKING é medição, não lista: um container é ranking quando os
 * números que ele mostra estão de fato ordenados (§`_ehRanking`). Isso é honesto por construção —
 * a tela só ganha a gramática de ranking se ela realmente for um. Nenhum cadastro pode mentir.
 *
 * DUAS TRAVAS DE CUSTO, e as duas vêm de defeitos já medidos nesta casa (2 vCPU, 19-29 FPS):
 *   1. ZERO trabalho por quadro E ZERO leitura de geometria. Tudo é `--i` + classe; quem anima é
 *      o compositor. Este módulo não chama `getBoundingClientRect` nenhuma vez — e isso é uma
 *      correção, não uma economia de estilo. A primeira versão cortava por DOBRA ("só anima o que
 *      cabe na tela"), e medir a dobra tem dois preços: o relayout forçado que a leitura provoca,
 *      e um erro de recorte que só apareceu na sonda — num monitor de 900px a lista de ranking
 *      começa DEPOIS da fileira de KPIs, então a dobra via 7 dos 80 cartões, e sete cartões fora
 *      de ordem faziam o detector responder "não é ranking" sobre uma lista que era.
 *   2. TETO DE NÓS por container (`TETO_NOS`). É o que a trava da dobra tentava fazer, sem
 *      precisar medir nada: ninguém lê quarenta linhas de uma vez, e o custo de uma animação de
 *      compositor em elemento fora da tela é o mesmo de uma que ninguém olha — nenhum.
 *
 * O `--i` É A MOEDA ÚNICA, e é por isso que este módulo é pequeno. O v33/v34 já fez o trabalho
 * duro: `#view .num`, `#view .val` e `#view .bar>i` já derivam seu atraso de `var(--i)`. Só que
 * `--i` só existia como `nth-child` em CSS puro para os 14 primeiros filhos de `.grid`/`.cols` —
 * medido: numa tabela, TODO número e TODA barra ficavam com `--i` vazio e atraso 0, e as 100
 * barras do radar cresciam ao mesmo tempo enquanto o comentário do v34 afirmava que a coluna era
 * lida de cima para baixo. Como propriedade customizada HERDA, marcar `--i` na LINHA acerta de
 * uma vez a linha, os números dela e as barras dela. Uma atribuição, três gramáticas.
 *
 * Os dois pisos desligam tudo (`prefers-reduced-motion` e `body.fps-baixo`), e desligar não custa
 * leitura nenhuma: a ordem em que as coisas aparecem é ênfase, o dado é o mesmo.
 */
/* Teto de atraso. O mesmo 380 ms do `entraCascata` do v33, e pela mesma razão escrita lá: sem
   teto, o quadragésimo item esperaria segundos e leria como travado, não como vivo. */
const TETO_MS = 380;
/* Quantos elementos, no máximo, uma gramática numera por container. Ninguém lê quarenta linhas de
   uma vez, e com teto de 380ms a quadragésima já entra junto com a décima oitava — daí para baixo
   numerar mais não muda nada na tela e só escreve estilo à toa. */
const TETO_NOS = 40;

/** Os primeiros `TETO_NOS` de uma coleção, como array. Sem geometria: ver trava 1 no cabeçalho. */
const _primeiros = lista => [...lista].slice(0, TETO_NOS);

/* ── é ranking? ────────────────────────────────────────────────────────────────────────────────
   Lê o primeiro número de cada filho e responde se a série está ordenada. Ordenada nos DOIS
   sentidos conta: "do que paga mais ao que paga menos" e "do mais barato ao mais caro" são os
   dois rankings do comparador, e os dois merecem a gramática.

   Por que 4 e não 3: com três itens, duas comparações bastam para "ordenado" e qualquer trio
   acerta por acaso perto de 25% das vezes. Com quatro a coincidência já é rara, e um ranking de
   três linhas não tem gesto para mostrar de qualquer forma.

   Empate NÃO quebra a ordem, porque ranking com valores repetidos continua sendo ranking — score
   8, 8, 7, 5 é uma fila legítima. Mas empate também não CONSTRÓI ordem: se a série toda for
   constante ela é uma coluna de valores iguais, e anunciar "cresce da base" sobre valores iguais é
   afirmar uma ordem que não existe. Daí a exigência de pelo menos um degrau de verdade.

   O número vem OBRIGATORIAMENTE de um `.num`/`.val`/`.v`, sem cair para o texto do cartão. Sem
   essa exigência o detector lia o primeiro número que encontrasse, e em `p_gastos` isso era o
   CNPJ do cabeçalho: 33781055000135, 33781055000135, 5, 5, 5 passava como "decrescente" e a aba
   ganhava a gramática de ranking sobre uma lista que não era ranking nenhum. */
/* O PONTO É AMBÍGUO NESTE PAINEL, e ler errado inverte a ordem. `fmtN`/`fmtD` produzem pt-BR
   ("1.234,56": ponto é milhar), mas dezenas de renders interpolam o número cru do JSON com
   `${x.razao_mediana}×`, e aí o ponto é DECIMAL ("0.7"). Tratar todo ponto como milhar — que foi a
   primeira versão — lia "0.7" como 7 e "0.64" como 64, e a lista de fornecedores mais baratos
   (0,64 · 0,64 · 0,66 · 0,7 · 0,72…) aparecia como 64, 64, 66, 7, 72: fora de ordem, ranking
   legítimo recusado. Medido na aba do comparador, visão "Fornecedores caros/baratos".

   A desambiguação é determinística e não precisa de heurística: separador de milhar em pt-BR vem
   SEMPRE seguido de exatamente três dígitos, em todos os grupos. Então
     · tem vírgula  → pt-BR: ponto é milhar, vírgula é decimal;
     · sem vírgula e casa em `d{1,3}(.ddd)+` → milhar ("1.234", "12.345.678");
     · qualquer outro ponto → decimal ("0.7", "5.48"). */
const _num = el => {
  const alvo = el.querySelector('.num, .val, .v');
  if (!alvo) return null;
  const m = String(alvo.textContent || '').match(/-?\d[\d.\s]*(?:,\d+)?/);
  if (!m) return null;
  const s = m[0].replace(/\s/g, '');
  const n = s.includes(',') ? parseFloat(s.replace(/\./g, '').replace(',', '.'))
          : /^-?\d{1,3}(\.\d{3})+$/.test(s) ? parseFloat(s.replace(/\./g, ''))
          : parseFloat(s);
  return isFinite(n) ? n : null;
};

function _ehRanking(nos) {
  if (nos.length < 4) return false;
  const s = nos.map(_num);
  if (s.some(v => v === null)) return false;
  let desce = true, sobe = true, degraus = 0;
  for (let i = 1; i < s.length; i++) {
    if (s[i] > s[i - 1]) desce = false;
    if (s[i] < s[i - 1]) sobe = false;
    if (s[i] !== s[i - 1]) degraus++;
  }
  return (desce || sobe) && degraus >= 2;
}

// ═══ GRAMÁTICA 1 · A TABELA MONTA LINHA A LINHA ═════════════════════════════════════════════════
/* A tabela era a única forma grande do painel que aparecia inteira de uma vez — e é justamente a
   forma que se lê de cima para baixo. Marcar `--i` na `<tr>` faz a linha entrar, o número dela
   chegar e a barra dela crescer no mesmo tempo, porque os três já leem `var(--i)` e propriedade
   customizada herda. */
function _tabelas(v) {
  let tocadas = 0;
  v.querySelectorAll('table tbody').forEach(tb => {
    const trs = _primeiros(tb.rows);
    if (trs.length < 3) return;          // duas linhas não formam cascata, formam um piscar
    trs.forEach((tr, i) => {
      tr.classList.add('rv-linha');
      tr.style.setProperty('--i', i);
    });
    tocadas += trs.length;
  });
  return tocadas;
}

// ═══ GRAMÁTICA 2 · O RANKING CRESCE DA BASE ═════════════════════════════════════════════════════
/* Numa lista comum a cascata desce, na ordem em que se lê. Num RANKING ela sobe: a pilha se
   monta da base e o primeiro colocado — o pior órgão, o maior sobrepreço — aterrissa por último,
   coroando o que já está montado. O olho termina o movimento exatamente onde está a resposta.
   É a mesma animação do v33; o que muda é a ORDEM dos índices, e só. Gramática nova sem
   `@keyframes` novo é gramática que não custa nada. */
function _rankings(v) {
  let n = 0;
  v.querySelectorAll('.grid, .cols').forEach(g => {
    const filhos = _primeiros([...g.children]
      .filter(el => el.classList.contains('card') || el.classList.contains('ck-inst')));
    if (!_ehRanking(filhos)) return;
    g.classList.add('rv-rank');
    /* De baixo para cima: o ÚLTIMO recebe índice 0, o primeiro colocado recebe o maior e aterrissa
       por último, coroando a pilha já montada. O `nth-child` do v33 continua no arquivo e perde na
       cascata — `style` inline vence folha, sempre. */
    filhos.forEach((el, i) => el.style.setProperty('--i', filhos.length - 1 - i));
    n++;
  });
  return n;
}

// ═══ GRAMÁTICA 3 · RANKINGS SEGUIDOS ENTRAM POR LADOS OPOSTOS ═══════════════════════════════════
/* O comparador mostra dois rankings um sob o outro — "órgãos, do que paga MAIS ao que paga MENOS"
   e "fornecedores, do mais caro ao mais barato". Empilhados e entrando iguais, os dois leem como
   uma lista só de trinta itens. Entrando por lados opostos, o corpo entende antes do texto que
   são duas leituras distintas do mesmo item.
   Vale para qualquer aba com dois ou mais rankings, não só o comparador: a alternância é do
   PADRÃO "rankings irmãos", e é ele que carrega o sentido. Com um ranking só não há oposição a
   marcar, e a gramática não entra — nada aqui se move por decoração. */
function _colunasOpostas(v) {
  const rks = [...v.querySelectorAll('.rv-rank')];
  if (rks.length < 2) return 0;
  rks.forEach((g, i) => {
    g.classList.add('rv-lado');
    g.style.setProperty('--lado', i % 2 ? '-1' : '1');
  });
  return rks.length;
}

// ═══ GRAMÁTICA 4 · A SEÇÃO RISCA ANTES DE O CONTEÚDO CHEGAR ═════════════════════════════════════
/* `h2.sec` já tem um filete que atravessa a largura (`::after`). Ele nasce inteiro. Fazê-lo ser
   TRAÇADO da esquerda para a direita, e só depois o conteúdo entrar, dá à seção a leitura de um
   instrumento se armando — e é o gesto mais barato deste arquivo: uma transformação de escala num
   elemento de 1 px de altura, sem repintura de nada. */
function _secoes(v) {
  const secs = _primeiros(v.querySelectorAll('h2.sec'));
  secs.forEach((s, i) => { s.classList.add('rv-sec'); s.style.setProperty('--i', i); });
  return secs.length;
}

// ═══ GRAMÁTICA 5 · A FILEIRA DE CHIPS ABRE EM LEQUE ═════════════════════════════════════════════
/* Os chips são as escolhas da tela — a primeira coisa que a mão procura. Abrindo em leque da
   esquerda para a direita eles se anunciam como um controle, não como um rodapé de rótulos.
   Fileira de um chip só não abre leque nenhum. */
function _chips(v) {
  let n = 0;
  v.querySelectorAll('.chips').forEach(row => {
    const bs = _primeiros(row.children);
    if (bs.length < 2) return;
    row.classList.add('rv-leque');
    bs.forEach((b, i) => b.style.setProperty('--i', i));
    n += bs.length;
  });
  return n;
}

/* ── a porta ──────────────────────────────────────────────────────────────────────────────────
   Chamada por `vivo()`, uma vez por render, depois do paint. Devolve o censo do que foi tocado —
   é o que o teste e a sonda leem para provar que a gramática ENTROU, em vez de acreditar.

   Os dois pisos saem por aqui e não só no CSS: com movimento desligado, `--i` inline sobre
   centenas de linhas é escrita de estilo sem nenhum efeito. Não fazer é mais barato que fazer e
   mandar ignorar. */
export function revelar(v, rm, sobrio) {
  if (!v) return null;
  if (rm || sobrio) return {desligado: true, motivo: rm ? 'reduced-motion' : 'fps-baixo'};
  const censo = {
    linhas: _tabelas(v),
    rankings: _rankings(v),
    secoes: _secoes(v),
    chips: _chips(v),
  };
  censo.opostos = _colunasOpostas(v);   // depende de `_rankings` já ter marcado `.rv-rank`
  return censo;
}

// ═══ GRAMÁTICA 6 · O GRAFO DESENHA AS ARESTAS ANTES DOS NÓS ═════════════════════════════════════
/* A malha de luz do `_wire` desenhava aresta e nó no mesmo quadro, e um grafo que nasce pronto
   não mostra que é um grafo — vira textura de fundo. Traçado, ele conta a estrutura: primeiro os
   fios, ligando um card ao outro; depois os nós acendem em cima do que já está ligado.
   `_wireFase(t0)` devolve as duas frações da intro para o desenho consumir, e é só aritmética —
   o laço de animação é o que já existia, não há um segundo laço. */
const INTRO_ARESTA = 620, INTRO_NO = 300;

export function _wireFase(msDesdeInicio) {
  if (msDesdeInicio == null) return {aresta: 1, no: 1};
  const a = Math.min(1, Math.max(0, msDesdeInicio / INTRO_ARESTA));
  const n = Math.min(1, Math.max(0, (msDesdeInicio - INTRO_ARESTA) / INTRO_NO));
  /* Aceleração de saída nos dois: o fio sai rápido e chega devagar, que é como uma linha traçada
     à mão se comporta. Curva idêntica à do `cubic-bezier(.2,.9,.25,1)` do resto da casa, na forma
     que dá para escrever em aritmética. */
  return {aresta: 1 - Math.pow(1 - a, 3), no: 1 - Math.pow(1 - n, 3)};
}
