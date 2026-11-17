/* v63 · FUNDO VIVO — fitas de luz atrás de tudo, que acompanham a rolagem.
 *
 * Ordem de preferência (a mais barata que funciona):
 *   1. `<video>` em loop (`static/v63/fluxo_hero[_m].{webm,mp4}`) — decodificação em hardware, ~0 CPU;
 *   2. canvas ao vivo (`v63/fitas.js`, a MESMA função que gerou o vídeo) a meia resolução e 30 fps,
 *      quando o vídeo não toca (codec ausente, erro de rede);
 *   3. o pôster `.webp` parado — reduzir movimento, economia de dados ou modo sóbrio (FPS medido baixo).
 *
 * MOVIMENTO DE CÂMERA (o Relay troca o enquadramento das fitas entre as seções):
 *   · parallax: `--v63-sy` = rolagem × 0,12, escrito num rAF só quando a rolagem muda;
 *   · enquadramento: cada seção do Início traz `data-v63-quadro="1..4"`; a que ocupa o meio da tela
 *     escreve `data-quadro` na camada e o CSS (`99z5-v63-20-fundo.css`) desliza/gira/escala as fitas
 *     com mola de 1,4 s. Fora do Início, o enquadramento é o da ABA (hash estável do id) — cada aba
 *     tem o seu, e trocar de aba move as fitas.
 * Tudo para quando a aba do navegador some (`visibilitychange`).
 */
import {_redMotion, _sobrio} from '../capacidade/estado.js';
import {desenharFitas} from './fitas.js';

let _camada = null, _video = null, _cv = null, _raf = 0, _vivo = false, _io = null, _passo = null;

export function fundoMontar() {
  if (_camada) return;
  const ret = matchMedia('(max-aspect-ratio: 4/5)').matches;
  const eco = !!(navigator.connection && navigator.connection.saveData);
  const base = '/static/v63/fluxo_hero' + (ret ? '_m' : '');
  const f = document.createElement('div');
  f.id = 'v63-fundo'; f.setAttribute('aria-hidden', 'true'); f.dataset.quadro = '1';
  f.innerHTML = `<div class="v63-cam"><div class="v63-quadro" style="background-image:url(${base}.webp)"></div></div>`
    + '<div class="v63-veu"></div>';
  document.body.insertBefore(f, document.body.firstChild);
  _camada = f;
  const q = f.querySelector('.v63-quadro');
  if (_redMotion || eco || _sobrio) return;                 // pôster parado — e nada mais roda
  const v = document.createElement('video');
  v.muted = true; v.loop = true; v.playsInline = true; v.autoplay = true; v.preload = 'auto';
  v.setAttribute('muted', ''); v.setAttribute('playsinline', '');
  v.poster = base + '.webp';
  v.innerHTML = `<source src="${base}.webm" type="video/webm"><source src="${base}.mp4" type="video/mp4">`;
  v.addEventListener('playing', () => {
    q.classList.add('toca');
    if (_cv) { _vivo = false; _cv.remove(); _cv = null; }   // o vídeo chegou depois do canvas: o canvas sai
  }, {once: true});
  v.addEventListener('error', _paraCanvas, true);            // `error` dos <source> não borbulha: captura
  q.appendChild(v); _video = v;
  const p = v.play(); if (p && p.catch) p.catch(_paraCanvas);
  /* rede lenta: se em 4 s o vídeo não deu quadro, o canvas assume (o vídeo segue tentando por baixo) */
  setTimeout(() => { if (!q.classList.contains('toca')) _paraCanvas(); }, 4000);
  document.addEventListener('visibilitychange', _visib);
  addEventListener('scroll', _rolou, {passive: true});
  _rolou();
}

function _paraCanvas() {
  if (_cv || !_camada) return;
  const q = _camada.querySelector('.v63-quadro');
  const cv = document.createElement('canvas'); cv.className = 'v63-cv';
  q.appendChild(cv); _cv = cv;
  const ctx = cv.getContext('2d');
  const medir = () => { cv.width = Math.round(innerWidth * .5); cv.height = Math.round(innerHeight * .5); };
  medir(); addEventListener('resize', medir, {passive: true});
  q.classList.add('toca');
  _vivo = true;
  let ult = 0;
  const t0 = performance.now();
  _passo = now => {
    _raf = 0;
    if (!_vivo) return;
    if (now - ult >= 33) { ult = now; desenharFitas(ctx, cv.width, cv.height, (now - t0) / 1000, .6); }
    _raf = requestAnimationFrame(_passo);
  };
  _raf = requestAnimationFrame(_passo);
}

/* `visibilitychange` também é o sinal que o modo sóbrio reemite ao ligar/desligar (`capacidade/sobrio.js`):
   aba oculta OU sóbrio → vídeo pausado e canvas parado (o CSS mostra o pôster). */
function _visib() {
  const parar = document.hidden || _sobrio;
  if (_video) { if (parar) _video.pause(); else { const p = _video.play(); if (p && p.catch) p.catch(() => {}); } }
  if (_cv) { _vivo = !parar; if (_vivo && !_raf) _raf = requestAnimationFrame(_passo); }
}

/* parallax: uma escrita de variável por quadro em que houve rolagem — nada de leitura de layout */
let _sy = -1, _pend = false;
function _rolou() {
  if (_pend) return; _pend = true;
  requestAnimationFrame(() => {
    _pend = false;
    const y = Math.min(scrollY, 4000);
    if (y === _sy || !_camada) return;
    _sy = y; _camada.style.setProperty('--v63-sy', (-y * .12).toFixed(1) + 'px');
  });
}

/** Enquadramento das fitas para a aba atual (Início: o observador de seções assume em seguida). */
export function fundoQuadroDaAba(id) {
  if (!_camada) return;
  let h = 0; for (const c of String(id)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  _camada.dataset.quadro = id === 'i_cockpit' ? '1' : String(2 + (h % 5));
}

/** Observa as seções `[data-v63-quadro]` dentro de `raiz`: a que cruza o meio da tela manda. */
export function fundoSeguirSecoes(raiz) {
  if (!_camada || !('IntersectionObserver' in window)) return;
  if (_io) _io.disconnect();
  _io = new IntersectionObserver(es => {
    for (const e of es) if (e.isIntersecting) _camada.dataset.quadro = e.target.dataset.v63Quadro;
  }, {rootMargin: '-45% 0px -45% 0px'});
  raiz.querySelectorAll('[data-v63-quadro]').forEach(s => _io.observe(s));
}
export function fundoSoltarSecoes() { if (_io) { _io.disconnect(); _io = null; } }
