/* GALÁXIA — o PREVIEW no fim da aba Início (v64, 17/11/2026).
 *
 * Saiu o vídeo escuro da v61: aqui é a galáxia REAL, clara, em miniatura (mesmo desenho da página
 * `/galaxia`, `galaxia/render.js`), girando devagar. Só desenha quando o cartão está na tela
 * (IntersectionObserver) e a aba visível; fora disso o laço para. Movimento reduzido ou modo sóbrio →
 * um quadro parado. Os dados são um recorte (`?limite=700` — os fornecedores de maior prioridade, todos
 * os órgãos e dossiês); os totais são os GLOBAIS do resumo.
 *
 * Ponto de extensão: `renderCockpit` acrescenta `<section id="gx-prev">` ao fim da aba e `ckBoot`
 * chama `galaxiaPreviewMontar($('gx-prev'))` depois do paint. Nada no `window`, nada no boot.
 */
import {fmtN} from '../nucleo/formato.js';
import {J} from '../nucleo/http.js';
import {preparar, enquadrar, desenhar, semearPulsos} from '../galaxia/render.js';

const _CONT = [['casos', 'dossiês'], ['fornecedores_radar', 'fornecedores com sinal'], ['alertas_abertos', 'alertas abertos'],
  ['orgaos', 'órgãos'], ['arestas', 'ligações']];

export function galaxiaPreviewHtml() {
  return `<section class="gx-prev" id="gx-prev" aria-label="Galáxia dos casos"></section>`;
}

export async function galaxiaPreviewMontar(el) {
  if (!el || el.dataset.gx) return;
  el.dataset.gx = '1';
  el.innerHTML = `<div class="gx-prev-cv"><canvas aria-hidden="true"></canvas></div>
    <div class="gx-prev-txt"><div class="gx-prev-eye">Galáxia dos casos</div>
      <h2 class="gx-prev-tit">Todos os casos e as ligações entre eles, num só <em class="v63-it">céu</em></h2>
      <div class="gx-prev-num" id="gx-prev-num"><span class="dim">carregando o grafo…</span></div>
      <a class="btn gx-prev-btn" href="/galaxia" target="_blank" rel="noopener">Abrir galáxia ↗</a>
      <div class="gx-prev-aviso dim" id="gx-prev-aviso"></div></div>`;
  /* o grafo só desce quando o cartão chega perto da tela — o Início abre sem pagar por ele */
  await new Promise(ok => {
    if (typeof IntersectionObserver !== 'function') return ok();
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { io.disconnect(); ok(); } }, {rootMargin: '400px'});
    io.observe(el);
  });
  const d = await J('/api/galaxia?limite=700');
  const num = el.querySelector('#gx-prev-num');
  if (!d || d.ok === false) { if (num) num.innerHTML = '<span class="dim">grafo indisponível agora — a página da galáxia tenta de novo ao abrir.</span>'; return; }
  const r = d.resumo || {};
  num.innerHTML = _CONT.map(([k, rotulo]) => `<span class="gx-prev-k"><b>${r[k] == null ? '—' : fmtN(r[k])}</b> ${rotulo}</span>`).join('')
    + (r.criticos ? `<span class="gx-prev-k gx-prev-crit"><b>${fmtN(r.criticos)}</b> crítico${r.criticos > 1 ? 's' : ''} (≥ 50)</span>` : '');
  const av = el.querySelector('#gx-prev-aviso');
  if (av) av.textContent = `${d.aviso || ''} Atualizado ${d.gerado_em || '—'}.`;
  const cv = el.querySelector('canvas');
  if (cv && cv.isConnected) girar(el, cv, preparar(d));
}

function girar(el, cv, G) {
  const ctx = cv.getContext('2d');
  const quieto = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let w = 0, h = 0, dpr = 1, cam = null, raf = 0, ant = 0, visivel = false, semente = 0;
  const medir = () => {
    const b = cv.getBoundingClientRect(); dpr = Math.min(devicePixelRatio || 1, 2);
    w = b.width; h = b.height; cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    const giro = cam ? cam.rot : 0; cam = enquadrar(G, w, h, G.bbox, 1.02); cam.rot = giro;
  };
  const quadro = (t) => {
    raf = 0;
    const dt = ant ? Math.min(.1, (t - ant) / 1000) : 0;
    if (ant && t - ant < 40) { raf = requestAnimationFrame(quadro); return; }   // ~24 fps bastam numa miniatura
    ant = t;
    cam.rot += dt * .045;                                                       // uma volta a cada ~2 min
    if ((semente += dt) > .35) { semente = 0; semearPulsos(G, cam, w, h, 2); }
    desenhar(ctx, G, cam, w, h, dt, {dpr, rotulos: false, pulsos: true, mini: true});
    if (visivel && !document.hidden && !document.body.classList.contains('fps-baixo')) raf = requestAnimationFrame(quadro);
  };
  const tocar = () => { if (!raf && visivel && !quieto) { ant = 0; raf = requestAnimationFrame(quadro); } };
  medir();
  desenhar(ctx, G, cam, w, h, 0, {dpr, rotulos: false, mini: true});
  if (typeof ResizeObserver === 'function') new ResizeObserver(() => { medir(); if (!raf) desenhar(ctx, G, cam, w, h, 0, {dpr, rotulos: false, mini: true}); }).observe(cv);
  if (quieto || typeof IntersectionObserver !== 'function') return;
  new IntersectionObserver(([e]) => { visivel = e.isIntersecting; if (visivel) tocar(); }, {threshold: .1}).observe(el);
  document.addEventListener('visibilitychange', tocar);
}
