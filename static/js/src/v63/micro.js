/* v63 · MICROINTERAÇÕES — brilho que segue o cursor/dedo nos botões e inclinação sutil nos cartões.
 *
 * Um ouvinte de `pointermove` no documento, passivo, com UMA escrita por quadro (rAF). Ele só escreve
 * variáveis CSS no elemento sob o ponteiro (`--mx/--my` para o brilho, `--rx/--ry` para a inclinação);
 * quem desenha é o CSS, no compositor. A inclinação só existe com ponteiro fino (mouse) — no toque, o
 * cartão afunda com mola (`:active`) e o botão acende no ponto tocado (`.toque`).
 */
import {_redMotion} from '../capacidade/estado.js';

const BRILHO = '.v63-btn, .chip, nav.tabs button, .v63-fonte';
let _pend = null, _raf = 0, _tilt = null, _fino = false;

export function microLigar() {
  if (_redMotion) return;
  const fino = matchMedia('(hover:hover) and (pointer:fine)').matches;
  document.addEventListener('pointermove', e => { _pend = e; if (!_raf) _raf = requestAnimationFrame(_quadro); }, {passive: true});
  document.addEventListener('pointerdown', e => {
    const b = e.target.closest && e.target.closest(BRILHO); if (!b) return;
    _luz(b, e); b.classList.add('toque');
    const solta = () => { b.classList.remove('toque'); removeEventListener('pointerup', solta); removeEventListener('pointercancel', solta); };
    addEventListener('pointerup', solta); addEventListener('pointercancel', solta);
  }, {passive: true});
  if (!fino) _pend = null;
  _fino = fino;
}

function _luz(b, e) {
  const r = b.getBoundingClientRect();
  b.style.setProperty('--mx', (e.clientX - r.left).toFixed(0) + 'px');
  b.style.setProperty('--my', (e.clientY - r.top).toFixed(0) + 'px');
}

function _quadro() {
  _raf = 0; const e = _pend; if (!e || !e.target || !e.target.closest) return;
  const b = e.target.closest(BRILHO); if (b) _luz(b, e);
  if (!_fino) return;
  const c = e.target.closest('.v63-tilt');
  if (_tilt && _tilt !== c) { _tilt.style.removeProperty('--rx'); _tilt.style.removeProperty('--ry'); _tilt.classList.remove('v63-tilt-on'); }
  _tilt = c;
  if (!c) return;
  const r = c.getBoundingClientRect();
  const x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
  c.classList.add('v63-tilt-on');
  c.style.setProperty('--rx', (-y * 4).toFixed(2) + 'deg');
  c.style.setProperty('--ry', (x * 5).toFixed(2) + 'deg');
  c.style.setProperty('--mx', ((x + .5) * 100).toFixed(1) + '%');
  c.style.setProperty('--my', ((y + .5) * 100).toFixed(1) + '%');
}
