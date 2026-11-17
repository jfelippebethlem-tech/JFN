/* v63 · FUNDO VIVO — fitas de luz atrás de tudo, que mudam de lugar a cada seção (como no Relay).
 *
 * TRÊS CAMADAS, cada uma um vídeo do Higgsfield (loop sem costura, câmera parada):
 *   hero    `fluxo_hero[_m]` — o herói do Início (retrato usa o recorte 540×720 `_m`);
 *   secao1  `fluxo_secao1`  — seções 01–02 do Início;
 *   secao2  `fluxo_secao2`  — seções 03–04 e o cockpit.
 * Fora do Início, cada aba fica com uma das três (hash estável do id).
 *
 * REGRAS DE CUSTO:
 *   · SÓ UM VÍDEO TOCA POR VEZ. Na troca, a camada nova entra em crossfade (1,2 s, CSS) e a velha
 *     é PAUSADA na hora — ela some congelada no último quadro, ninguém percebe.
 *   · Camada de seção é criada (pôster + vídeo) na PRIMEIRA vez que vira ativa: quem não rola não baixa.
 *   · Aba oculta ou modo sóbrio (FPS medido baixo) → pausa; o CSS mostra o pôster.
 *   · Reduzir movimento / economia de dados → só pôsteres, sem vídeo nenhum (a troca por seção continua).
 *   · Fallback em canvas (`v63/fitas.js`) SÓ se o vídeo do herói não der quadro (codec, rede).
 *
 * MOVIMENTO DE CÂMERA: parallax na rolagem (`--v63-sy`) + um enquadramento leve por seção/aba
 * (`data-quadro`, CSS) por cima do crossfade.
 */
import {_redMotion, _sobrio} from '../capacidade/estado.js';
import {desenharFitas} from './fitas.js';

const CAMADAS = ['hero', 'secao1', 'secao2'];
/* quadro (seção/aba) → camada. 1 = herói; 2–3 = seções 01–02; 4–6 = seções 03–04 / cockpit */
const CAMADA_DO_QUADRO = {1: 'hero', 2: 'secao1', 3: 'secao1', 4: 'secao2', 5: 'secao2', 6: 'secao2'};

let _camada = null, _cv = null, _raf = 0, _vivo = false, _io = null, _passo = null;
let _so_poster = false, _ret = false, _ativa = '';
const _videos = {};          // camada → <video>

const _base = c => '/static/assets/v63/fluxo_' + c + (c === 'hero' && _ret ? '_m' : '');

export function fundoMontar() {
  if (_camada) return;
  _ret = matchMedia('(max-aspect-ratio: 4/5)').matches;
  const eco = !!(navigator.connection && navigator.connection.saveData);
  _so_poster = _redMotion || eco || _sobrio;
  const f = document.createElement('div');
  f.id = 'v63-fundo'; f.setAttribute('aria-hidden', 'true'); f.dataset.quadro = '1';
  f.innerHTML = `<div class="v63-cam">${CAMADAS.map(c => `<div class="v63-quadro" data-c="${c}"></div>`).join('')}</div>`
    + '<div class="v63-veu"></div>';
  document.body.insertBefore(f, document.body.firstChild);
  _camada = f;
  _ativar('hero');
  document.addEventListener('visibilitychange', _visib);
  if (!_redMotion) { addEventListener('scroll', _rolou, {passive: true}); _rolou(); }
}

function _q(c) { return _camada && _camada.querySelector(`.v63-quadro[data-c="${c}"]`); }

/** Troca a camada ativa: crossfade pelo CSS (`.ativa`), pausa a velha NA HORA, toca a nova. */
function _ativar(c) {
  if (!_camada || c === _ativa) return;
  const velha = _ativa; _ativa = c;
  const q = _q(c);
  if (!q.style.backgroundImage) q.style.backgroundImage = `url(${_base(c)}.webp)`;   // pôster: na 1ª vez
  for (const k of CAMADAS) _q(k).classList.toggle('ativa', k === c);
  _camada.dataset.camada = c;
  if (velha && _videos[velha]) _videos[velha].pause();                                // só um toca
  if (_cv) { _vivo = c === 'hero' && !document.hidden && !_sobrio; if (_vivo && !_raf) _raf = requestAnimationFrame(_passo); }
  if (_so_poster) return;
  if (!_videos[c]) _criarVideo(c, q);
  _tocar();
}

function _criarVideo(c, q) {
  const v = document.createElement('video');
  v.muted = true; v.loop = true; v.playsInline = true; v.preload = 'auto';
  v.setAttribute('muted', ''); v.setAttribute('playsinline', '');
  v.innerHTML = `<source src="${_base(c)}.webm" type="video/webm"><source src="${_base(c)}.mp4" type="video/mp4">`;
  v.addEventListener('playing', () => {
    q.classList.add('toca');
    if (c === 'hero' && _cv) { _vivo = false; _cv.remove(); _cv = null; }   // o vídeo chegou depois do canvas
  }, {once: true});
  if (c === 'hero') {
    v.addEventListener('error', _paraCanvas, true);       // `error` dos <source> não borbulha: captura
    /* rede lenta: se em 4 s o herói não deu quadro, o canvas assume (o vídeo segue tentando por baixo) */
    setTimeout(() => { if (!q.classList.contains('toca') && _ativa === 'hero') _paraCanvas(); }, 4000);
  }
  q.appendChild(v); _videos[c] = v;
}

function _tocar() {
  const v = _videos[_ativa]; if (!v) return;
  if (document.hidden || _sobrio) { v.pause(); return; }
  const p = v.play(); if (p && p.catch) p.catch(() => { if (_ativa === 'hero') _paraCanvas(); });
}

function _paraCanvas() {
  if (_cv || !_camada) return;
  const q = _q('hero');
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
  _tocar();
  if (_cv) { _vivo = !parar && _ativa === 'hero'; if (_vivo && !_raf) _raf = requestAnimationFrame(_passo); }
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
  const q = id === 'i_cockpit' ? 1 : 2 + (h % 5);
  _camada.dataset.quadro = String(q);
  _ativar(id === 'i_cockpit' ? 'hero' : CAMADAS[h % 3]);
}

/** Observa as seções `[data-v63-quadro]` dentro de `raiz`: a que cruza o meio da tela manda. */
export function fundoSeguirSecoes(raiz) {
  if (!_camada || !('IntersectionObserver' in window)) return;
  if (_io) _io.disconnect();
  _io = new IntersectionObserver(es => {
    for (const e of es) if (e.isIntersecting) {
      const q = e.target.dataset.v63Quadro;
      _camada.dataset.quadro = q;
      _ativar(CAMADA_DO_QUADRO[q] || 'secao2');
    }
  }, {rootMargin: '-45% 0px -45% 0px'});
  raiz.querySelectorAll('[data-v63-quadro]').forEach(s => _io.observe(s));
}
export function fundoSoltarSecoes() { if (_io) { _io.disconnect(); _io = null; } }
