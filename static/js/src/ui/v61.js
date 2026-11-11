/* v61 TRON CLARO — o par em JS do estrato `static/css/src/99z2-v61-*.css`.
 *
 * Mesmo contrato do `ui/v60.js`: uma função de entrada (`v61Boot`), chamada UMA vez no início do
 * boot, que não faz nada sem a flag. Sem `html.v61` o painel é a v60, byte a byte.
 * Não tem efeito de topo (o boot é ordenado pelo entrypoint, não pelo import).
 */
import {_v61, _v61flag} from '../capacidade/estado.js';
import {tickerMontar, abrirHistorico} from './aovivo.js';
import {svgIco} from '../nucleo/dom.js';

export function v61Boot() {
  if (!_v61flag || !_v61) return;
  _fundo();
  _som();
  tickerMontar();
  /* "Atividade ao vivo" da folha "⋯" abre o histórico da v61 (o holofeed antigo fica oculto) */
  document.addEventListener('click', e => {
    if (e.target && e.target.closest && e.target.closest('[data-v60-feed]')) { e.stopPropagation(); abrirHistorico(); }
  }, true);
}

/** O painel tem um tema só (o claro, desde 11/11/2026): a folha "⋯" não leva mais a linha de tema. */
export function v61TemaItem() { return ''; }

/* ── fundo: véu claro + grade Tron em perspectiva + 3 rastros de luz. Só CSS anima; aqui só nasce
   o DOM (uma camada fixa, sem evento de ponteiro). O vídeo/pôster da esfera segue no `#esfnebula`. */
function _fundo() {
  if (document.getElementById('v61-fundo')) return;
  const f = document.createElement('div');
  f.id = 'v61-fundo'; f.setAttribute('aria-hidden', 'true');
  f.innerHTML = '<div class="v61-veu"></div><div class="v61-piso"><div class="v61-plano"><div class="v61-grade"></div><i class="r1"></i><i class="r2"></i><i class="r3"></i></div></div>';
  document.body.insertBefore(f, document.body.firstChild);
}

/* ── som: o set não tinha alto-falante (o botão era um ponto + "Mudo"). Entram os dois glifos; a
   classe `.on`, que o `ui/midia.js` já alterna, decide pelo CSS qual aparece. O texto segue para o
   leitor de tela. */
function _som() {
  const a = document.querySelector('.htop a.som'); if (!a || a.querySelector('.v61-som')) return;
  const i = document.createElement('span');
  i.className = 'v60-ic v61-som'; i.setAttribute('aria-hidden', 'true');
  i.innerHTML = `<span class="s-on">${svgIco('§v61-som')}</span><span class="s-off">${svgIco('§v61-mudo')}</span>`;
  a.insertBefore(i, a.firstChild);
}
