/* v63 · REVELAR — a entrada de cada bloco no estilo Relay: desfocado e 24px abaixo → nítido no lugar.
 *
 * Um só IntersectionObserver para a página toda. Quem entra na tela ganha `.v63-in` (o CSS faz o resto,
 * só `opacity`/`transform`/`filter` — compositor) e é DESOBSERVADO: revela uma vez, sem custo depois.
 * Número com `data-alvo` conta de 0 ao valor na primeira vez que aparece; o texto final é exatamente o
 * que o formatador da casa escreve para o valor real (milhar + 2 casas em R$).
 * Reduzir movimento / modo sóbrio: tudo nasce revelado e o número nasce no valor final.
 */
import {_redMotion, _sobrio} from '../capacidade/estado.js';
import {fmtN, fmtR} from '../nucleo/formato.js';

const SEL = '.v63-rv, .v63-run-i, .v63-iso-b, .v63-fonte, .v63-integra';
let _io = null;
const _parado = () => _redMotion || _sobrio || !('IntersectionObserver' in window);

function _obs() {
  if (_io) return _io;
  _io = new IntersectionObserver(es => {
    for (const e of es) {
      if (!e.isIntersecting) continue;
      e.target.classList.add('v63-in');
      _io.unobserve(e.target);
      e.target.querySelectorAll && e.target.querySelectorAll('[data-alvo]').forEach(_contar);
      if (e.target.dataset && e.target.dataset.alvo) _contar(e.target);
    }
  }, {rootMargin: '0px 0px -8% 0px', threshold: .12});
  return _io;
}

export function revelarEm(raiz) {
  const els = [...(raiz.matches && raiz.matches(SEL) ? [raiz] : []), ...raiz.querySelectorAll(SEL)];
  if (_parado()) { els.forEach(e => e.classList.add('v63-in')); raiz.querySelectorAll('[data-alvo]').forEach(_final); return; }
  const io = _obs();
  els.forEach(e => { if (!e.classList.contains('v63-in')) io.observe(e); });
}

/** Contadores de um bloco que JÁ foi revelado antes de o dado chegar: conta agora. */
export function contarEm(bloco) {
  if (_parado()) { bloco.querySelectorAll('[data-alvo]').forEach(_final); return; }
  if (bloco.classList.contains('v63-in')) bloco.querySelectorAll('[data-alvo]').forEach(_contar);
}

const _f = (fmt, x) => fmt === 'R$' ? fmtR(x) : fmtN(Math.round(x));
function _final(el) { el.textContent = _f(el.dataset.fmt, +el.dataset.alvo); el.dataset.contado = '1'; }
function _contar(el) {
  if (el.dataset.contado) return;
  const alvo = +el.dataset.alvo; if (!isFinite(alvo)) return;
  el.dataset.contado = '1';
  const fmt = el.dataset.fmt, dur = 1400, t0 = performance.now();
  const passo = now => {
    const p = Math.min(1, (now - t0) / dur), k = 1 - Math.pow(1 - p, 4);   // sai rápido, pousa devagar
    el.textContent = p < 1 ? _f(fmt, alvo * k) : _f(fmt, alvo);            // o último quadro é o valor exato
    if (p < 1) requestAnimationFrame(passo);
  };
  requestAnimationFrame(passo);
}
