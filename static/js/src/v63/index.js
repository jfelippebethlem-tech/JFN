/* v63 FLUXO CLARO — ponto de entrada. O par em JS dos estratos `static/css/src/99z5-v63-*.css`.
 *
 * Mesmo contrato da `ui/v60.js` e da `ui/v61.js`: UMA função (`v63Boot`), chamada uma vez no início
 * do boot (a classe `v63` está sempre no <html> desde que virou o padrão). Sem efeito de topo.
 *
 * O que muda a cada tela pintada é decidido por UM observador no `#view` (só filhos diretos): quando
 * o `.fade` novo entra, as fitas trocam de enquadramento, a capa ganha a palavra em itálico, os
 * blocos revelam ao entrar na tela e a cobertura azul da transição se abre.
 */
import {_v63} from '../capacidade/estado.js';
import {fundoMontar, fundoQuadroDaAba, fundoSoltarSecoes} from './fundo.js';
import {molduraMontar, capaItalico} from './moldura.js';
import {transicaoLigar, transicaoPintou} from './transicao.js';
import {microLigar} from './micro.js';
import {revelarEm} from './revelar.js';

export function v63Boot() {
  if (!_v63) return;
  fundoMontar();
  molduraMontar();
  transicaoLigar();
  microLigar();
  const v = document.getElementById('view'); if (!v) return;
  new MutationObserver(ms => {
    for (const m of ms) for (const n of m.addedNodes) if (n.nodeType === 1 && n.classList.contains('fade')) _pintou(n);
  }).observe(v, {childList: true});
}

function _pintou(f) {
  const id = f.dataset.aba || '';
  if (id !== 'i_cockpit') { fundoSoltarSecoes(); fundoQuadroDaAba(id); }
  capaItalico(f);
  f.querySelectorAll(':scope > .cover, :scope > .card, :scope > .grid > .card, :scope > .cols > *').forEach((c, i) => {
    if (i < 10) { c.classList.add('v63-rv'); c.style.setProperty('--v63i', String(i)); }   // `--i` é da revelação da casa
  });
  revelarEm(f);
  transicaoPintou();
}
