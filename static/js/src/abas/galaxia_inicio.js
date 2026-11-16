/* GALÁXIA — o PREVIEW leve no fim da aba Início (decisão do dono, 16/11/2026).
 *
 * A galáxia 3D completa é uma PÁGINA PRÓPRIA (`/galaxia`, bundle `static/js/galaxia.bundle.js`) que
 * abre em outra aba do navegador. Aqui fica só o convite: um canvas 2D pintado UMA vez (sem laço,
 * sem WebGL, sem three.js — o bundle 3D nunca é baixado pelo painel), os contadores do resumo e o
 * botão "Abrir galáxia".
 *
 * Ponto de extensão: `renderCockpit` acrescenta `<section id="gx-prev">` ao fim da aba e `ckBoot`
 * chama `galaxiaPreviewMontar($('gx-prev'))` depois do paint. Nada no `window`, nada no boot.
 */
import {fmtN} from '../nucleo/formato.js';
import {J} from '../nucleo/http.js';
import {layoutEspiral, desenhar2D} from '../galaxia/layout.js';

const _CONT = [['casos', 'casos'], ['cnpjs', 'empresas'], ['socios', 'sócios'],
  ['processos_sei', 'processos SEI'], ['pontes_entre_casos', 'pontes entre casos']];

export function galaxiaPreviewHtml() {
  return `<section class="gx-prev" id="gx-prev" aria-label="Galáxia dos casos"></section>`;
}

export async function galaxiaPreviewMontar(el) {
  if (!el || el.dataset.gx) return;
  el.dataset.gx = '1';
  /* fundo vivo: loop da galáxia (Higgsfield, 16/11) por baixo; por cima, os nós e ligações REAIS do grafo.
     Só toca visível, fora do modo sóbrio e sem movimento reduzido (CSS esconde o vídeo; o pôster fica). */
  const cel = matchMedia('(max-width:700px)').matches ? '-m' : '';
  el.innerHTML = `<div class="gx-prev-cv"><video class="gx-prev-vid" muted loop playsinline preload="none" aria-hidden="true">
      <source src="/static/assets/v61/galaxia-loop${cel}.webm" type="video/webm"><source src="/static/assets/v61/galaxia-loop${cel}.mp4" type="video/mp4"></video>
      <canvas aria-hidden="true"></canvas><span class="gx-prev-ring" aria-hidden="true"></span></div>
    <div class="gx-prev-txt"><div class="gx-prev-eye">Galáxia dos casos</div>
      <h2 class="gx-prev-tit">Todos os dossiês e as ligações entre eles, num só céu</h2>
      <div class="gx-prev-num" id="gx-prev-num"><span class="dim">carregando o grafo…</span></div>
      <a class="btn gx-prev-btn" href="/galaxia" target="_blank" rel="noopener">Abrir galáxia ↗</a>
      <div class="gx-prev-aviso dim" id="gx-prev-aviso"></div></div>`;
  const d = await J('/api/galaxia');
  const num = el.querySelector('#gx-prev-num');
  if (!d || d.ok === false) { if (num) num.innerHTML = '<span class="dim">grafo indisponível agora — a página da galáxia tenta de novo ao abrir.</span>'; return; }
  const r = d.resumo || {};
  num.innerHTML = _CONT.map(([k, rotulo]) => `<span class="gx-prev-k"><b>${r[k] == null ? "—" : fmtN(r[k])}</b> ${rotulo}</span>`).join('');
  const av = el.querySelector('#gx-prev-aviso'); if (av) av.textContent = d.aviso || '';
  const cv = el.querySelector('canvas');
  if (cv && cv.isConnected) desenhar2D(cv, d, layoutEspiral(d), {escala: 0.8, estrelas: 220, fundo: false});
  tocarQuandoVisivel(el.querySelector('.gx-prev-vid'));
  el.querySelector('.gx-prev-cv').setAttribute('title', `${fmtN(r.casos)} casos · ${fmtN(r.arestas)} ligações — ${d.aviso || ''}`);
}

function tocarQuandoVisivel(v) {
  if (!v || typeof IntersectionObserver !== 'function') return;
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  new IntersectionObserver(([e]) => {
    if (e.isIntersecting && !document.body.classList.contains('fps-baixo')) v.play().catch(() => {});
    else v.pause();
  }, {threshold: 0.15}).observe(v);
}
