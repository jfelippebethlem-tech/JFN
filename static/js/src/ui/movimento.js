/* v61 — MOVIMENTO CONTÍNUO (sistema). O par em JS do estrato `99z2-v61-70-movimento.css`.
 *
 * Três gestos, e nenhum deles inventa nada:
 *   contar     número conta de 0 ao valor na 1ª vez que APARECE na tela. Só valor real: texto que não
 *              é número ("INDISPONÍVEL", "—", "off") fica como está. O texto final é o que o render
 *              escreveu, byte a byte — a contagem só passa por ele.
 *   flip       um número que MUDOU ao vivo vira com um flip curto + lâmina de luz na borda de cima
 *              do cartão (`flipAoVivo`, chamado por quem atualiza — hoje o `ckFill` do cockpit).
 *   pausar     vídeo de fundo para quando a aba some (`visibilitychange`) e volta quando ela volta.
 * `prefers-reduced-motion` e o modo sóbrio (FPS medido baixo) desligam contagem e flip.
 */
import {$} from '../nucleo/dom.js';
import {_v61, _redMotion, _sobrio} from '../capacidade/estado.js';

const RE_NUM = /^(R\$\s?)?(-?\d{1,3}(?:\.\d{3})*|-?\d+)(?:,(\d+))?(\s?(?:%|×|x))?$/;
const ALVO = '.card.kpi .v, .tf-k b';
let _io = null;

export function movimentoBoot() {
  if (!_v61) return;
  document.addEventListener('visibilitychange', () => {
    document.querySelectorAll('#esfnebula video').forEach(v => {
      if (document.hidden) v.pause(); else if (v.classList.contains('on')) v.play().catch(() => {});
    });
  });
  if (_redMotion || !('IntersectionObserver' in window)) return;
  _io = new IntersectionObserver(es => { for (const e of es) if (e.isIntersecting) { _io.unobserve(e.target); _contar(e.target); } },
    {threshold: 0.6});
  let passe = 0;
  const marcar = raiz => raiz.querySelectorAll(ALVO).forEach(el => {
    if (el.dataset.v61n !== undefined || el.children.length) return;
    const t = el.textContent.trim();
    el.dataset.v61n = RE_NUM.test(t) ? t : '';
    if (el.dataset.v61n) _io.observe(el);
  });
  for (const id of ['view', 'c61-mapa']) {
    const r = $(id); if (!r) continue;
    new MutationObserver(() => { clearTimeout(passe); passe = setTimeout(() => marcar(document), 90); }).observe(r, {childList: true, subtree: true});
  }
  marcar(document);
}

function _contar(el) {
  const fim = el.dataset.v61n, m = RE_NUM.exec(fim);
  if (!m || _sobrio || el.textContent.trim() !== fim) return;
  const dec = (m[3] || '').length, alvo = parseFloat(m[2].replace(/\./g, '') + (dec ? '.' + m[3] : ''));
  if (!isFinite(alvo) || alvo === 0) return;
  const fmt = x => (m[1] || '') + x.toLocaleString('pt-BR', {minimumFractionDigits: dec, maximumFractionDigits: dec}) + (m[4] || '');
  const t0 = performance.now(), DUR = 600;
  let ultimo = fim;
  const passo = t => {
    if (!el.isConnected || el.textContent.trim() !== ultimo) return;       // alguém atualizou o número: a contagem sai da frente
    const k = Math.min(1, (t - t0) / DUR), e = 1 - Math.pow(1 - k, 3);
    ultimo = k >= 1 ? fim : fmt(dec ? alvo * e : Math.round(alvo * e));
    el.textContent = ultimo;
    if (k < 1) requestAnimationFrame(passo);
  };
  ultimo = fmt(0); el.textContent = ultimo;
  requestAnimationFrame(passo);
}

/** Um número do cartão mudou AO VIVO: flip curto no valor + lâmina de luz na borda superior. */
export function flipAoVivo(cartao) {
  if (!_v61 || _redMotion || _sobrio || !cartao) return;
  cartao.classList.remove('v61-lamina'); void cartao.offsetWidth; cartao.classList.add('v61-lamina');
  const v = cartao.querySelector('.val,.v');
  if (v) { v.classList.remove('v61-flip'); void v.offsetWidth; v.classList.add('v61-flip'); }
  setTimeout(() => { cartao.classList.remove('v61-lamina'); if (v) v.classList.remove('v61-flip'); }, 700);
}
