/* SISTEMA — configurações e funcionamento do JFN, numa esfera própria.

   Pedido do dono (14/11/2026): "coloque uma outra aba (configurações e funcionamento do sistema) e
   mova o que for disso." O Início e o Transversal misturavam o que o JFN ACHA (riscos, casos,
   alertas) com como o JFN FUNCIONA (motores rodando, coletas, instrumentação, regras de qualidade,
   concordância entre modelos). Esta aba junta a segunda parte: a grade de motores, o cruzamento de
   motores, o frescor das fontes e as funções mestras saíram do Início para cá.

   Custo de API e uso da assinatura NÃO aparecem (dono, 14/11: "isso polui"). */
import {cover} from '../nucleo/dom.js';
import {aoVivoLigar} from '../aovivo/estado.js';
import {motoresMontar} from '../ui/aovivo.js';
import {cruzamentoMontar} from './motores_cruzamento.js';
import {frescorMontar, blocoComandosMestres} from './cockpit.js';

/* O `ir()` pinta o HTML depois que o render resolve (às vezes dentro de uma View Transition), e só
   o cockpit tem gancho pós-pintura. Aqui se espera o nó existir, quadro a quadro, por até ~3 s. */
function _quandoExistir(id, fn, tentativas = 180) {
  const el = document.getElementById(id);
  if (el) { fn(el); return; }
  if (tentativas > 0) requestAnimationFrame(() => _quandoExistir(id, fn, tentativas - 1));
}

export async function renderMotoresSistema() {
  aoVivoLigar();
  _quandoExistir('s-motores', motoresMontar);
  _quandoExistir('s-cruz', cruzamentoMontar);
  _quandoExistir('s-fontes', frescorMontar);
  return cover('sistema', 'Motores — o que está rodando e se os modelos concordam',
    'Estado de cada motor do JFN (rodando, com falha, agendado, sem efeito) e o cruzamento entre o Claude e os outros modelos. Clique num motor para ver os eventos da última hora. Rota que não responde é INDISPONÍVEL, nunca zero.', '⚙️')
    + '<section class="c61-motores" id="s-motores" aria-labelledby="c61-motores-t"></section>'
    + '<div class="ck-fontes" id="s-fontes" style="margin-top:18px"></div>'
    + '<section class="c61-cruz" id="s-cruz" aria-label="Cruzamento de motores" style="margin-top:18px"></section>';
}

/* "Funções mestras" — os comandos de capabilities.yaml, que ficavam no rodapé do Início. */
export async function renderComandosSistema() {
  return cover('sistema', 'Comandos — as funções mestras do JFN',
    'Cada botão é uma capacidade pronta (capabilities.yaml), a mesma que o Yoda atende no Telegram. Nada é disparado sem a sua decisão.', '🧭')
    + (blocoComandosMestres() || '<div class="dim">Lista de comandos INDISPONÍVEL nesta carga.</div>');
}
