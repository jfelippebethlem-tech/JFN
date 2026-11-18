/* GALÁXIA DOS CASOS — página /galaxia (v64, 17/11/2026).
 *
 * Canvas 2D com níveis de detalhe (`../src/galaxia/render.js`): longe = aglomerados por órgão; perto =
 * fornecedores, sócios, processos SEI e nomes. Arrastar move, roda/pinça aproxima, toque num ponto abre o
 * cartão com a PROVA (`/api/galaxia/no`): sinais do Radar, alertas abertos, dossiês, o motivo de cada
 * ligação — e o link para o painel. Busca, filtro por score e por órgão.
 *
 * Desempenho: o laço só desenha quando algo mudou (câmera, filtro, seleção) ou há pulsos correndo; sem
 * movimento permitido (`prefers-reduced-motion`) não há pulsos nem voo animado. Aba oculta → laço para.
 * Ligação = indício de relação a conferir, nunca prova.
 */
import {preparar, enquadrar, desenhar, acertar, paraTela, semearPulsos, contarNaTela, corScore, CRITICO} from '../src/galaxia/render.js';
import {cineVideo, cineSoPoster} from '../src/cena/cine3d.js';
import CINE from '../../assets/v68/cine3d.json';

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmtN = n => n == null ? '—' : Number(n).toLocaleString('pt-BR');
const fmtR = v => v == null ? '—' : 'R$ ' + Number(v).toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const cnpjFmt = c => c && c.length === 14 ? `${c.slice(0, 2)}.${c.slice(2, 5)}.${c.slice(5, 8)}/${c.slice(8, 12)}-${c.slice(12)}` : (c || '');
const norm = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const QUIETO = matchMedia('(prefers-reduced-motion: reduce)').matches;
const TIPO = {orgao: 'órgão', cnpj: 'fornecedor', caso: 'dossiê', socio: 'sócio', sei: 'processo SEI'};
const SINAL = {
  conluio_forte: 'conluio forte (sócio em comum com concorrente)', conluio_medio: 'conluio (sócio em comum com concorrente)',
  sancao_a_epoca: 'sanção vigente à época do ato', sancao_fora_vigencia: 'sanção fora da vigência', fantasma_alto: 'sinais de fachada (alto)',
  fantasma_medio: 'sinais de fachada (médio)', socio_servidor: 'sócio é servidor público', perdedora_contumaz: 'perdedora contumaz',
  hub_massa: 'endereço compartilhado em massa', fenix: 'pagamento após baixa do CNPJ (fênix)', capital_irrisorio: 'capital social irrisório',
};

async function J(url) {
  try {
    const r = await fetch(url, {credentials: 'same-origin'});
    if (r.status === 401 || r.redirected && /login/.test(r.url)) return {ok: false, erro: 'autenticação necessária'};
    return await r.json();
  } catch (e) { return {ok: false, erro: String(e && e.message || e)}; }
}

let G = null, cam = null, w = 0, h = 0, dpr = 1, sujo = true, raf = 0, ant = 0, sem = 0, voo = null;
let scoreMin = 0, orgaoSel = '', ultimoToque = 0;
const cv = $('gx-cv'), ctx = cv.getContext('2d'), visor = $('gx-visor');

/* DPR real do aparelho (iPhone = 3), limitado por ÁREA: o Safari recusa canvas acima de ~16 MP e a
   memória do iOS aperta antes disso — teto de 12 MP. (v64 cortava em 2 → borrado no iPhone.) */
const AREA_MAX = 12e6;
function medir() {
  const b = cv.getBoundingClientRect();
  w = b.width; h = b.height;
  dpr = Math.min(devicePixelRatio || 1, 3);
  if (w * h * dpr * dpr > AREA_MAX) dpr = Math.sqrt(AREA_MAX / (w * h));
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  sujo = true; laco();
}

function nivel() {
  if (!cam) return '';
  return cam.k < .28 ? 'afastado · aglomerados por órgão' : cam.k < .95 ? 'médio · fornecedores e ligações' : 'perto · sócios, processos SEI e nomes';
}

function laco() { if (!raf && !document.hidden) raf = requestAnimationFrame(quadro); }
function quadro(t) {
  raf = 0;
  const dt = ant ? Math.min(.1, (t - ant) / 1000) : 0; ant = t;
  if (voo) {
    const p = Math.min(1, (t - voo.t0) / voo.ms), e = 1 - Math.pow(1 - p, 3);
    cam.cx = voo.a.cx + (voo.b.cx - voo.a.cx) * e; cam.cy = voo.a.cy + (voo.b.cy - voo.a.cy) * e;
    cam.k = Math.exp(Math.log(voo.a.k) + (Math.log(voo.b.k) - Math.log(voo.a.k)) * e);
    if (p >= 1) voo = null;
    sujo = true;
  }
  if (inercia) passoInercia(dt);
  if (!camOk()) { console.warn('galáxia: câmera inválida, recentrando'); Object.assign(cam, enquadrar(G, w, h, G.bbox, w < 760 ? .98 : .96)); voo = null; inercia = null; sujo = true; }
  const pulsando = !QUIETO && G.pulsos.length > 0;
  if (!QUIETO && (sem += dt) > .28) { sem = 0; semearPulsos(G, cam, w, h, cam.k < .28 ? 2 : 3); }
  if (sujo || pulsando) {
    nVis = desenhar(ctx, G, cam, w, h, dt, {dpr, pulsos: !QUIETO});
    if (!aviso) $('gx-nivel').textContent = nivel();
    sujo = false;
  }
  if (!voo && !inercia && !ptrs.size) assentar();
  if (voo || inercia || !QUIETO) raf = requestAnimationFrame(quadro);
}

function voar(alvo, ms = 650) {
  inercia = null;
  if (QUIETO) { Object.assign(cam, alvo); sujo = true; laco(); return; }
  voo = {a: {cx: cam.cx, cy: cam.cy, k: cam.k}, b: alvo, t0: performance.now(), ms}; laco();
}

/* ── câmera (v66): limites com mola, guarda de NaN, "nunca tela vazia" ───────────────────────────
 * Zoom entre kMin (galáxia inteira × .5) e K_MAX; o centro não sai da caixa do grafo (+ meia tela).
 * Durante o gesto passa-se do limite com resistência elástica; ao soltar, a mola traz de volta.
 * Se ao assentar não houver NENHUM nó na tela, voa para o nó mais próximo do centro. */
const K_MAX = 6;                                            // 'perto' começa em .95; acima de ~6 só espalha os nós
const kFit = () => enquadrar(G, w, h, G.bbox, w < 760 ? .98 : .96).k;
const kMin = () => kFit() * .5;
const camOk = () => cam && Number.isFinite(cam.cx) && Number.isFinite(cam.cy) && Number.isFinite(cam.k) && cam.k > 0;
let inercia = null, aviso = 0, nVis = -1, assentado = true;
/** Resistência elástica: dentro do limite é 1:1; fora, cresce em raiz (puxa como borracha). */
function elastico(k) {
  const a = kMin(), b = K_MAX;
  if (k > b) return b * Math.pow(k / b, .3);
  if (k < a) return a * Math.pow(k / a, .3);
  return k;
}
const travaK = k => Math.max(kMin(), Math.min(K_MAX, k));
function caixaCentro(k) {                                  // onde o centro da câmera pode ficar
  const [x0, y0, x1, y1] = G.bbox, mx = w * .5 / k, my = h * .5 / k;
  return [x0 - mx * .2, y0 - my * .2, x1 + mx * .2, y1 + my * .2];
}
function travaCentro(cx, cy, k) {
  const [a, b, c, d] = caixaCentro(k);
  return [Math.max(a, Math.min(c, cx)), Math.max(b, Math.min(d, cy))];
}
/** Põe o ponto do mundo (wx, wy) sob o ponto de tela (px, py) no zoom k. */
function ancorar(wx, wy, px, py, k) { cam.k = k; cam.cx = wx - (px - w / 2) / k; cam.cy = wy - (py - h / 2) / k; }
const mundo = (px, py) => [(px - w / 2) / cam.k + cam.cx, (py - h / 2) / cam.k + cam.cy];

function zoomEm(px, py, f) {                               // roda, teclado: limite duro, sem mola
  if (!camOk()) return;
  const [wx, wy] = mundo(px, py);
  ancorar(wx, wy, px, py, travaK(cam.k * f));
  [cam.cx, cam.cy] = travaCentro(cam.cx, cam.cy, cam.k);
  assentado = false; sujo = true; laco();
}
/** Gesto acabou: mola de volta aos limites; se a tela ficou vazia, voa para o nó mais próximo. */
let nAssentar = 0;
function assentar() {
  if (assentado || !G || !camOk()) return;
  assentado = true; nAssentar++;
  const k = travaK(cam.k), [cx, cy] = travaCentro(cam.cx, cam.cy, k);
  if (Math.abs(k - cam.k) > 1e-6 * k || Math.abs(cx - cam.cx) * k > .5 || Math.abs(cy - cam.cy) * k > .5) {
    voar({cx, cy, k}, 320); assentado = false; return;
  }
  const A = areaUtil();
  if (nVis === 0 || contarNaTela(G, cam, w, h, A) === 0) {   // nada na área livre (os painéis tapam o resto)
    const [mx, my] = mundo((A[0] + A[2]) / 2, (A[1] + A[3]) / 2), i = maisProximo(mx, my);
    if (i >= 0) {
      const n = G.nos[i], k2 = Math.min(cam.k, Math.max(kFit() * 2, n.t === 'orgao' ? .5 : 1.2));
      avisar('nada neste ponto — voltando ao aglomerado mais próximo');
      voar({cx: n.x - ((A[0] + A[2]) / 2 - w / 2) / k2, cy: n.y - ((A[1] + A[3]) / 2 - h / 2) / k2, k: k2}, 520); assentado = false;
    }
  }
}
/** Retângulo do canvas que NÃO está coberto pelos controles (topo) nem pela telemetria (base). */
function areaUtil() {
  const c = cv.getBoundingClientRect(), ctl = $('gx-ctl') || document.querySelector('.gx-ctl'), num = $('gx-num');
  const y0 = ctl ? Math.max(0, ctl.getBoundingClientRect().bottom - c.top) : 0;
  const y1 = num && num.offsetHeight ? Math.min(h, num.getBoundingClientRect().top - c.top) : h;
  return y1 - y0 > 120 ? [0, y0, w, y1] : [0, 0, w, h];
}
function maisProximo(x, y) {
  let m = -1, dm = Infinity;
  G.nos.forEach((n, i) => {
    if (G.filtro && !G.filtro(n)) return;
    if ((n.t === 'socio' || n.t === 'sei')) return;          // alvo é algo que aparece em qualquer nível
    const d = (n.x - x) ** 2 + (n.y - y) ** 2; if (d < dm) { dm = d; m = i; }
  });
  return m;
}
function avisar(txt) {
  const el = $('gx-nivel'); el.textContent = txt; clearTimeout(aviso);
  aviso = setTimeout(() => { aviso = 0; el.textContent = nivel(); }, 2200);
}
/** Inércia do arrasto: velocidade em px/ms, decaimento exponencial (~325 ms). */
function passoInercia(dt) {
  const ms = dt * 1000, f = Math.exp(-ms / 325);
  cam.cx -= inercia.vx * ms / cam.k; cam.cy -= inercia.vy * ms / cam.k;
  const [a, b, c, d] = caixaCentro(cam.k);                  // na borda a inércia freia forte
  if (cam.cx < a || cam.cx > c) inercia.vx *= .5;
  if (cam.cy < b || cam.cy > d) inercia.vy *= .5;
  inercia.vx *= f; inercia.vy *= f; sujo = true;
  if (Math.hypot(inercia.vx, inercia.vy) < .02) inercia = null;
}
function verTudo() { const c = enquadrar(G, w, h, G.bbox, w < 760 ? .98 : .96); voar({cx: c.cx, cy: c.cy, k: c.k}); }

/* ── gestos (v66): máquina de estados que se REFAZ a cada dedo que entra ou sai ─────────────────
 * v64: ao soltar 1 dedo da pinça, o "arrasto" continuava sendo o da pinça (sem cx/cy) e o próximo
 * movimento gravava NaN na câmera — a galáxia sumia para sempre (reproduzido em _SANDBOX/v66_repro.py).
 * Agora: 1 dedo = arrasto ancorado no ponto do mundo sob o dedo; 2 dedos = pinça ancorada no ponto
 * médio (zoom + pan juntos); ao mudar o nº de dedos a âncora é recalculada a partir da câmera atual. */
const ptrs = new Map();
let gesto = null;                                            // {tipo:'arrasto'|'pinca', ...}
let toqueIni = null;                                         // candidato a toque (1 dedo, sem mover)
let vel = [];                                                // amostras recentes p/ inércia
function recomecar() {
  const pts = [...ptrs.values()];
  if (!pts.length) { gesto = null; return; }
  if (pts.length === 1) {
    const [wx, wy] = mundo(pts[0].x, pts[0].y);
    gesto = {tipo: 'arrasto', wx, wy}; vel = [];
  } else {
    const [a, b] = pts, mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, [wx, wy] = mundo(mx, my);
    gesto = {tipo: 'pinca', d0: Math.max(10, Math.hypot(a.x - b.x, a.y - b.y)), k0: cam.k, wx, wy};
  }
}
function xy(e) { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
cv.addEventListener('pointerdown', e => {
  if (!G || !camOk()) return;
  if (e.pointerType === 'mouse' && e.button !== 0) return;
  try { cv.setPointerCapture(e.pointerId); } catch (_) { /* ponteiro já liberado */ }
  const [x, y] = xy(e);
  ptrs.set(e.pointerId, {x, y, x0: x, y0: y, t0: performance.now()});
  voo = null; inercia = null; assentado = false;
  toqueIni = ptrs.size === 1 ? {id: e.pointerId, t0: performance.now(), x, y} : null;
  recomecar();
});
cv.addEventListener('pointermove', e => {
  const p = ptrs.get(e.pointerId);
  if (!p) {                                                         // só passando o mouse: cursor de "clicável"
    if (e.pointerType === 'mouse' && G && camOk()) visor.classList.toggle('sobre-no', acertar(G, cam, w, h, e.offsetX, e.offsetY, 8) >= 0);
    return;
  }
  const [x, y] = xy(e); p.x = x; p.y = y;
  if (!gesto || !camOk()) return;
  if (toqueIni && Math.hypot(x - toqueIni.x, y - toqueIni.y) > 6) toqueIni = null;
  if (gesto.tipo === 'pinca' && ptrs.size >= 2) {
    const [a, b] = [...ptrs.values()], d = Math.hypot(a.x - b.x, a.y - b.y);
    ancorar(gesto.wx, gesto.wy, (a.x + b.x) / 2, (a.y + b.y) / 2, elastico(gesto.k0 * d / gesto.d0));
  } else if (gesto.tipo === 'arrasto' && !toqueIni) {
    visor.classList.add('arrastando');
    ancorar(gesto.wx, gesto.wy, x, y, cam.k);
    const [cx, cy] = travaCentro(cam.cx, cam.cy, cam.k);        // fora da caixa: borracha (1/3 do excesso)
    cam.cx = cx + (cam.cx - cx) / 3; cam.cy = cy + (cam.cy - cy) / 3;
    const t = performance.now(); vel.push([t, x, y]); while (vel.length > 2 && t - vel[0][0] > 100) vel.shift();
  } else return;
  sujo = true; laco();
});
const soltar = e => {
  if (!ptrs.has(e.pointerId)) return;
  ptrs.delete(e.pointerId);
  visor.classList.remove('arrastando');
  const eraArrasto = gesto && gesto.tipo === 'arrasto';
  if (toqueIni && toqueIni.id === e.pointerId && ptrs.size === 0 && e.type === 'pointerup' && performance.now() - toqueIni.t0 < 500) {
    const agora = performance.now(), {x, y} = toqueIni;
    if (agora - ultimoToque < 300) {                               // toque duplo: aproxima NO ponto, animado
      ultimoToque = 0;
      const [wx, wy] = mundo(x, y), k = travaK(cam.k * 2.2);
      voar({cx: wx - (x - w / 2) / k, cy: wy - (y - h / 2) / k, k}, 380);
    } else { ultimoToque = agora; tocar(x, y); }
  } else if (eraArrasto && ptrs.size === 0 && vel.length >= 2 && !QUIETO) {
    const [t0, x0, y0] = vel[0], [t1, x1, y1] = vel[vel.length - 1], dt = Math.max(16, t1 - t0);
    if (performance.now() - t1 < 80) {
      const vx = (x1 - x0) / dt, vy = (y1 - y0) / dt;
      if (Math.hypot(vx, vy) > .25) inercia = {vx: Math.max(-4, Math.min(4, vx)), vy: Math.max(-4, Math.min(4, vy))};
    }
  }
  toqueIni = null;
  recomecar();                                                     // 2→1 dedo: novo arrasto ancorado aqui
  sujo = true; laco();
};
cv.addEventListener('pointerup', soltar);
cv.addEventListener('pointercancel', soltar);
cv.addEventListener('lostpointercapture', soltar);
/* Safari iOS: a pinça dispara gesturestart/change (zoom da PÁGINA) mesmo com touch-action; barra aqui. */
['gesturestart', 'gesturechange', 'gestureend'].forEach(t => visor.addEventListener(t, e => e.preventDefault(), {passive: false}));
cv.addEventListener('dblclick', e => e.preventDefault());
let rodaFim = 0;
cv.addEventListener('wheel', e => {
  e.preventDefault(); voo = null; inercia = null;
  const [x, y] = xy(e); zoomEm(x, y, Math.exp(-e.deltaY * (e.ctrlKey ? .01 : .0018)));
  assentado = true; clearTimeout(rodaFim); rodaFim = setTimeout(() => { assentado = false; sujo = true; laco(); }, 220);
}, {passive: false});
document.querySelectorAll('.gx-zoom button').forEach(b => b.addEventListener('click', () => {
  if (!G) return;
  if (b.dataset.z === 'tudo' || !camOk()) return verTudo();
  const base = voo ? voo.b : cam;                          // toques seguidos somam a partir do ALVO do voo
  voar({cx: base.cx, cy: base.cy, k: travaK(base.k * (b.dataset.z === 'mais' ? 1.8 : 1 / 1.8))}, 360); assentado = false;
}));
addEventListener('keydown', e => {
  if (e.target.closest && e.target.closest('input,select,textarea')) return;
  if (e.key === 'Escape') fecharFolha();
  if (!G) return;
  if (e.key === '+' || e.key === '=') zoomEm(w / 2, h / 2, 1.5);
  if (e.key === '-') zoomEm(w / 2, h / 2, 1 / 1.5);
  if (e.key === '0') verTudo();
});
/* Diagnóstico só-leitura para o teste de gesto (_SANDBOX/v66_gesto.py): câmera, nós na tela, limites. */
window.__gx = () => ({cam: cam && {...cam}, nVis, nUtil: G && camOk() ? contarNaTela(G, cam, w, h, areaUtil()) : -1, kMin: G && kMin(), kMax: K_MAX, dpr, cw: cv.width, ch: cv.height, ptrs: ptrs.size, gesto: gesto && gesto.tipo, parado: !voo && !inercia && !ptrs.size && assentado && !sujo,
  voo: !!voo, inercia: inercia && {...inercia}, assentado, sujo, nAssentar});

function tocar(px, py) {
  const i = acertar(G, cam, w, h, px, py, matchMedia('(pointer:coarse)').matches ? 16 : 10);
  if (i < 0) { if (G.sel >= 0) { G.sel = -1; sujo = true; laco(); fecharFolha(); } return; }
  selecionar(i, px, py);
}

/* ── filtros ──────────────────────────────────────────────────────────────────────────────────── */
function aplicarFiltro() {
  const so = orgaoSel, min = scoreMin;
  G.filtro = (!so && !min) ? null : n => (!so || n.cl === so) && (n.t !== 'cnpj' || (n.s || 0) >= min) && (n.t !== 'socio' || !min);
  sujo = true; laco(); resumo();
}
$('gx-score').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  scoreMin = +b.dataset.min;
  $('gx-score').querySelectorAll('button').forEach(x => x.setAttribute('aria-checked', String(x === b)));
  aplicarFiltro();
});
$('gx-org').addEventListener('change', e => {
  orgaoSel = e.target.value; aplicarFiltro();
  if (!orgaoSel) return verTudo();
  const o = G.nos.find(n => n.t === 'orgao' && n.cl === orgaoSel);
  if (o) { const R = (o.R || 80) * 1.1; const c = enquadrar(G, w, h, [o.x - R, o.y - R, o.x + R, o.y + R]); voar({cx: c.cx, cy: c.cy, k: c.k}); }
});

/* ── busca ────────────────────────────────────────────────────────────────────────────────────── */
let indice = [], resSel = -1;
const q = $('gx-q'), res = $('gx-res');
q.addEventListener('input', () => {
  const t = norm(q.value.trim()), dig = q.value.replace(/\D/g, '');
  if (t.length < 2 && dig.length < 4) { res.hidden = true; q.setAttribute('aria-expanded', 'false'); return; }
  const ordem = {orgao: 0, caso: 1, cnpj: 2, socio: 3, sei: 4};
  const achou = indice.filter(([s, d, i]) => s.includes(t) || (dig.length >= 4 && d.includes(dig))).map(x => x[2])
    .sort((a, b) => ordem[G.nos[a].t] - ordem[G.nos[b].t] || (G.nos[b].s || 0) - (G.nos[a].s || 0)).slice(0, 14);
  resSel = -1;
  res.innerHTML = achou.length ? achou.map((i, k) => { const n = G.nos[i]; return `<li role="option" id="gx-r${k}" data-i="${i}" aria-selected="false">`
    + `<span class="gx-r-t">${TIPO[n.t]}</span><span class="gx-r-l">${esc(n.l)}</span>${n.t === 'cnpj' && n.s ? `<span class="gx-r-s">${n.s}</span>` : ''}</li>`; }).join('')
    : '<li class="gx-r-vazio" aria-disabled="true">nada com esse nome na galáxia</li>';
  res.hidden = false; q.setAttribute('aria-expanded', 'true');
});
q.addEventListener('keydown', e => {
  const itens = [...res.querySelectorAll('li[data-i]')];
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault(); if (!itens.length) return;
    resSel = (resSel + (e.key === 'ArrowDown' ? 1 : -1) + itens.length) % itens.length;
    itens.forEach((li, k) => li.setAttribute('aria-selected', String(k === resSel)));
    q.setAttribute('aria-activedescendant', itens[resSel].id);
  } else if (e.key === 'Enter') { const li = itens[Math.max(0, resSel)]; if (li) irPara(+li.dataset.i); }
  else if (e.key === 'Escape') { res.hidden = true; q.setAttribute('aria-expanded', 'false'); }
});
res.addEventListener('click', e => { const li = e.target.closest('li[data-i]'); if (li) irPara(+li.dataset.i); });
document.addEventListener('pointerdown', e => { if (!e.target.closest('.gx-busca')) { res.hidden = true; q.setAttribute('aria-expanded', 'false'); } });

function irPara(i) {
  res.hidden = true; q.setAttribute('aria-expanded', 'false'); q.blur();
  const n = G.nos[i];
  if (G.filtro && !G.filtro(n)) { orgaoSel = ''; scoreMin = 0; $('gx-org').value = ''; $('gx-score').querySelectorAll('button').forEach((x, k) => x.setAttribute('aria-checked', String(k === 0))); aplicarFiltro(); }
  const k = n.t === 'orgao' ? Math.max(cam.k, Math.min(1.1, (Math.min(w, h) * .42) / (n.R || 80))) : Math.max(cam.k, n.t === 'socio' || n.t === 'sei' ? 2.2 : 1.6);
  voar({cx: n.x, cy: n.y, k});
  setTimeout(() => { const [x, y] = paraTela(cam, w, h, n.x, n.y); selecionar(i, x, y); }, QUIETO ? 0 : 680);
}

/* ── folha (cartão com a prova) ───────────────────────────────────────────────────────────────── */
const folha = $('gx-folha');
let pedido = 0, quemAbriu = null;
function fecharFolha() {
  if (folha.hidden) return;
  const fim = () => { folha.hidden = true; folha.innerHTML = ''; };
  if (QUIETO) fim(); else folha.animate([{opacity: 1, transform: 'none'}, {opacity: 0, transform: 'scale(.96)'}], {duration: 160, easing: 'ease-in'}).finished.then(fim, fim);
  if (quemAbriu && quemAbriu.focus) quemAbriu.focus({preventScroll: true});
}

async function selecionar(i, px, py) {
  G.sel = i; sujo = true; laco();
  const n = G.nos[i], meu = ++pedido;
  quemAbriu = document.activeElement;
  /* expande a partir do ponto tocado (a "transição de expandir" do v63, em transform/opacity) */
  const vb = visor.getBoundingClientRect();
  const abrir = folha.hidden;
  folha.hidden = false;
  const fb = folha.getBoundingClientRect();
  folha.style.setProperty('--ox', `${vb.left + px - fb.left}px`); folha.style.setProperty('--oy', `${vb.top + py - fb.top}px`);
  folha.innerHTML = cabecalho(n) + '<div class="gx-f-sec"><span class="gx-f-sub">lendo a prova…</span></div>';
  if (abrir && !QUIETO) folha.animate([{opacity: 0, transform: 'scale(.18)'}, {opacity: 1, transform: 'none'}], {duration: 380, easing: 'cubic-bezier(.2,.8,.2,1)'});
  folha.querySelector('.gx-f-x').addEventListener('click', fecharFolha);
  const d = await J('/api/galaxia/no?id=' + encodeURIComponent(n.id));
  if (meu !== pedido || folha.hidden) return;
  if (!d || d.ok === false) { folha.querySelector('.gx-f-sec').innerHTML = `<span class="gx-f-sub">prova INDISPONÍVEL agora (${esc(d && d.erro)}).</span>`; return; }
  let corpo = '';
  if (n.t === 'caso') corpo = await corpoCaso(d);
  else corpo = ({cnpj: corpoForn, orgao: corpoOrgao, socio: corpoSocio, sei: corpoSei}[n.t] || (() => ''))(d);
  if (meu !== pedido || folha.hidden) return;
  folha.innerHTML = cabecalho(n, d.no) + corpo + `<p class="gx-f-nota">${esc(d.aviso)} Grafo gerado em ${esc(d.gerado_em || '—')}.</p>`;
  folha.querySelector('.gx-f-x').addEventListener('click', fecharFolha);
  folha.querySelectorAll('[data-ir]').forEach(b => b.addEventListener('click', () => {
    const j = G.nos.findIndex(x => x.id === b.dataset.ir); if (j >= 0) irPara(j);
  }));
  const fo = folha.querySelector('[data-filtra]');
  if (fo) fo.addEventListener('click', () => { $('gx-org').value = fo.dataset.filtra; $('gx-org').dispatchEvent(new Event('change')); });
}

function cabecalho(n, full) {
  const sub = n.t === 'cnpj' ? `CNPJ ${cnpjFmt(n.cnpj)}` : n.t === 'orgao' ? (full && full.ug ? `UG ${full.ug}` : full && full.ocnpj ? `CNPJ ${cnpjFmt(full.ocnpj)}` : '')
    : n.t === 'caso' ? `casos/${n.slug}.md` : n.t === 'socio' ? 'nome do QSA público · sem CPF' : '';
  return `<button type="button" class="gx-f-x" aria-label="Fechar">×</button>`
    + `<div class="gx-f-eye">${TIPO[n.t]}${n.t === 'cnpj' && (n.s || 0) >= CRITICO ? ' · <b style="color:var(--alerta-tx)">crítico</b>' : ''}</div>`
    + `<h2 id="gx-f-tit">${esc(n.l)}</h2>${sub ? `<div class="gx-f-sub">${esc(sub)}</div>` : ''}`;
}

const rotAl = (d, t) => (d.rotulos_alerta || {})[t] || t;
function blocoAlertas(d, no) {
  const al = no.al || {}, ex = no.ex || [];
  if (!Object.keys(al).length) return '';
  return `<div class="gx-f-sec"><h3>alertas abertos · ${fmtN(Object.values(al).reduce((a, b) => a + b, 0))}</h3><ul class="gx-f-lst">`
    + Object.entries(al).map(([t, c]) => `<li><span class="gx-peso">${fmtN(c)}</span>${esc(rotAl(d, t))}</li>`).join('')
    + ex.map(x => `<li><span class="gx-sev ${esc(x.sev)}">${esc(x.sev || '—')}</span>${esc(x.titulo)}<small>alerta nº ${esc(x.id)} · ${esc(rotAl(d, x.tipo))}</small></li>`).join('')
    + `</ul></div>`;
}
function blocoViz(d, filtro, titulo, max = 12) {
  const vs = d.vizinhos.filter(filtro);
  if (!vs.length) return '';
  return `<div class="gx-f-sec"><h3>${titulo} · ${fmtN(vs.length)}</h3><ul class="gx-f-lst">`
    + vs.slice(0, max).map(v => `<li><button type="button" class="gx-viz" data-ir="${esc(v.id)}"><span class="gx-v-t">${TIPO[v.t] || v.t}</span>`
      + `<span class="gx-v-l">${esc(v.l)}</span>${v.t === 'cnpj' && v.s ? `<b style="font:600 12px var(--mono);color:${(v.s >= CRITICO) ? 'var(--alerta-tx)' : 'var(--ion)'}">${v.s}</b>` : ''}</button>`
      + (v.det ? `<small>${esc(v.det)}</small>` : '') + (v.motivos ? `<small>em comum: ${esc(Object.entries(v.motivos).map(([k, c]) => `${c} ${({cnpj: 'CNPJ', socio: 'sócio', sei: 'processo SEI', ent: 'entidade'})[k] || k}`).join(' · '))}</small>` : '') + '</li>').join('')
    + (vs.length > max ? `<li><small>+ ${fmtN(vs.length - max)} outras ligações (aproxime na galáxia para ver)</small></li>` : '') + '</ul></div>';
}

function corpoForn(d) {
  const no = d.no, s = no.s || 0;
  const rating = s >= CRITICO ? '🔴' : s >= 25 ? '🟡' : '🟢';
  let h = `<div class="gx-f-score${s >= CRITICO ? ' crit' : ''}"><b style="color:${s >= CRITICO ? '' : corScore(s) === '#BFD3FF' ? 'var(--muted)' : corScore(s)}">${s}</b>`
    + `<small>${rating} score do Radar (0–100) — soma de sinais independentes; 🔴 ≥ 50 · 🟡 25–49 · 🟢 &lt; 25. Indício interno, não acusação.</small></div>`;
  if (no.sin && no.sin.length) h += `<div class="gx-f-sec"><h3>por que está aqui · sinais do radar</h3><ul class="gx-f-lst">`
    + no.sin.map(x => `<li><span class="gx-peso">+${esc(x.peso)}</span>${esc(SINAL[x.sinal] || x.sinal)}${x.detalhe ? `<small>${esc(x.detalhe)}</small>` : ''}</li>`).join('') + '</ul></div>';
  else if (!s) h += `<div class="gx-f-sec"><span class="gx-f-sub">sem sinal no Radar — está na galáxia por alerta aberto ou dossiê.</span></div>`;
  h += blocoAlertas(d, no);
  if (no.pago) h += `<div class="gx-f-sec"><h3>pagamentos (ob contabilizada no siafe)</h3><ul class="gx-f-lst"><li><b>${fmtR(no.pago)}</b><small>soma das OB pagas pelos órgãos ligados — OB = pagamento efetivo; empenho não entra.</small></li></ul></div>`;
  h += blocoViz(d, v => v.t === 'caso', 'dossiês do vault que citam');
  h += blocoViz(d, v => v.t === 'orgao', 'órgãos');
  h += blocoViz(d, v => v.tipo === 'endereco', 'mesmo endereço / contato');
  h += blocoViz(d, v => v.t === 'socio', 'sócios (qsa público)');
  h += `<div class="gx-f-acoes"><a class="gx-btn sol" href="/painel#g_radar" target="_blank" rel="noopener">Radar no painel ↗</a>`
    + (no.nal ? `<a class="gx-btn" href="/painel#e_alertas" target="_blank" rel="noopener">Alertas ↗</a>` : '')
    + (no.k && no.k.length ? `<a class="gx-btn" href="/painel#g_casos" target="_blank" rel="noopener">Dossiês ↗</a>` : '') + '</div>';
  return h;
}

function corpoOrgao(d) {
  const no = d.no;
  let h = `<div class="gx-f-score"><b>${fmtN(no.nf || 0)}</b><small>fornecedores neste aglomerado · ${fmtN(no.nal || 0)} alertas abertos (do órgão e dos fornecedores)`
    + `${no.s >= CRITICO ? ' · tem fornecedor crítico' : ''}</small></div>`;
  h += blocoAlertas(d, no);
  if (no.al && no.al.acumulacao) h += `<p class="gx-f-nota" style="margin-top:8px">Acúmulo de cargos é alerta de PESSOA: entra só como contagem no órgão, sem nome nem CPF.</p>`;
  h += blocoViz(d, v => v.t === 'caso', 'dossiês do vault');
  h += blocoViz(d, v => v.t === 'cnpj', 'fornecedores (maior score primeiro)', 15);
  h += `<div class="gx-f-acoes"><button type="button" class="gx-btn sol" data-filtra="${esc(no.cl)}">Isolar este órgão</button>`
    + `<a class="gx-btn" href="/painel#g_radar" target="_blank" rel="noopener">Radar no painel ↗</a></div>`;
  return h;
}

async function corpoCaso(d) {
  const no = d.no;
  let h = `<div class="gx-f-score"><b>${esc(no.nv ?? '—')}</b><small>nível do dossiê (${esc(no.nvr || 'sem grau')}) · situação: ${esc(no.sit || '—')}`
    + `${no.ent ? `<br>entidade: ${esc(no.ent)}` : ''}</small></div>`;
  const nota = await J('/api/casos/nota?slug=' + encodeURIComponent(no.slug));
  if (nota && nota.ok !== false) {
    const txt = String(nota.texto || nota.conteudo || nota.md || '').replace(/^---[\s\S]*?---\s*/, '').replace(/[#*_>`]/g, '').trim().slice(0, 700);
    if (txt) h += `<div class="gx-f-sec"><h3>resumo da nota</h3><div class="gx-f-txt">${esc(txt)}${txt.length >= 700 ? '…' : ''}</div></div>`;
  }
  h += blocoViz(d, v => v.tipo === 'caso_caso', 'pontes com outros dossiês');
  h += blocoViz(d, v => v.t === 'cnpj', 'empresas citadas');
  h += blocoViz(d, v => v.t === 'sei', 'processos SEI citados');
  h += `<div class="gx-f-acoes"><a class="gx-btn sol" href="/painel#g_casos" target="_blank" rel="noopener">Abrir dossiê no painel ↗</a></div>`;
  return h;
}
const corpoSocio = d => `<p class="gx-f-sub">Nome do quadro societário público (Receita). Mesmo nome ≠ mesma pessoa: confirmar o CPF completo antes de citar.</p>`
  + blocoViz(d, v => v.t === 'cnpj', 'empresas em que aparece', 20);
const corpoSei = d => blocoViz(d, v => v.t === 'caso', 'dossiês que citam este processo')
  + `<div class="gx-f-acoes"><a class="gx-btn" href="/painel#g_casos" target="_blank" rel="noopener">Dossiês no painel ↗</a></div>`;

/* ── resumo, órgãos, carga ─────────────────────────────────────────────────────────────────────── */
function resumo() {
  const r = G.d.resumo || {};
  const visiveis = G.filtro ? G.forn.filter(i => G.filtro(G.nos[i])).length : null;
  $('gx-num').innerHTML = `<span class="gx-n-eye">telemetria do grafo${visiveis != null ? ` · filtro: ${fmtN(visiveis)} fornecedores visíveis` : ''}</span>`
    + `<span><b>${fmtN(r.casos)}</b>dossiês</span><span><b>${fmtN(r.orgaos)}</b>órgãos</span>`
    + `<span><b>${fmtN(r.fornecedores_radar)}</b>fornecedores com sinal</span>`
    + `<span class="gx-n-crit"><b>${fmtN(r.criticos)}</b>críticos</span>`
    + `<span><b>${fmtN(r.alertas_abertos)}</b>alertas abertos</span><span><b>${fmtN(r.arestas)}</b>ligações</span>`;
}

/* v68 · VOO 3D enquanto a galáxia carrega (a API leva ~15 s quando o cache da ronda venceu): vídeo renderizado
   no Blender com os nós e ligações REAIS de um retrato datado, a câmera termina no fornecedor crítico. Só na
   1ª visita do dia; toque pula; sai sozinho quando o vídeo acaba E a galáxia viva está pronta (teto 22 s). */
function vooCinema() {
  const hoje = new Date().toISOString().slice(0, 10);
  let dia = ''; try { dia = localStorage.getItem('jfn_gx_voo_dia') || ''; } catch (e) { /* sem storage: toca */ }
  if (cineSoPoster() || dia === hoje) return null;
  try { localStorage.setItem('jfn_gx_voo_dia', hoje); } catch (e) { /* idem */ }
  const M = CINE.galaxia3d, dataRetrato = String(M.gerado_em || '').slice(0, 10).split('-').reverse().join('/');
  const el = document.createElement('div'); el.className = 'gx-voo';
  const v = cineVideo('galaxia3d'); v.preload = 'auto'; el.appendChild(v);
  el.insertAdjacentHTML('beforeend', `<div class="gx-voo-leg"><span class="gx-eye">voo pela galáxia real · retrato de ${esc(dataRetrato)}</span>`
    + `<b>${fmtN(M.nos)} nós · ${fmtN(M.ligacoes)} ligações</b>`
    + `<span>a câmera para no fornecedor crítico (score ≥ ${fmtN(M.limiar_critico)}) — indício a conferir, não acusação</span></div>`
    + `<button type="button" class="gx-voo-pular">pular <span aria-hidden="true">›</span></button>`);
  visor.appendChild(el);
  let acabou = false, pronto = false;
  const sair = () => { if (el.classList.contains('sai')) return; el.classList.add('sai'); v.pause(); setTimeout(() => el.remove(), 700); };
  const talvez = () => { if (acabou && pronto) sair(); };
  const fim = () => { acabou = true; talvez(); };
  v.addEventListener('ended', fim);
  v.addEventListener('error', fim, true);
  el.addEventListener('pointerdown', sair);
  addEventListener('keydown', sair, {once: true});
  setTimeout(() => { acabou = pronto = true; talvez(); }, 22000);
  const p = v.play(); if (p && p.catch) p.catch(fim);
  return {pronto() { pronto = true; talvez(); }};
}

async function iniciar() {
  const carga = $('gx-carga');
  const voo = vooCinema();
  const d = await J('/api/galaxia');
  if (voo) voo.pronto();
  if (!d || d.ok === false) {
    const aut = /autentic/.test(String(d && d.erro));
    carga.innerHTML = `<div class="gx-warn">${aut ? 'Sessão do painel expirada.' : 'A galáxia está INDISPONÍVEL agora (' + esc(d && d.erro) + ').'}`
      + `${aut ? ' <a href="/login_jfn">Entrar</a>' : ' Tente de novo em alguns minutos.'}</div>`;
    return;
  }
  G = preparar(d);
  indice = G.nos.map((n, i) => [norm(n.l) + ' ' + norm(n.slug || ''), (n.cnpj || '') + ' ' + String(n.l).replace(/\D/g, ''), i]);
  const orgs = G.orgaos.map(i => G.nos[i]).filter(n => n.nf).sort((a, b) => b.nf - a.nf);
  $('gx-org').insertAdjacentHTML('beforeend', orgs.map(n => `<option value="${esc(n.cl)}">${esc(n.l.slice(0, 48))} (${fmtN(n.nf)})</option>`).join(''));
  const r = d.resumo || {}, f = d.fontes || {};
  const indisp = Object.entries(f).filter(([, v]) => v !== 'ok').map(([k]) => k);
  $('gx-aviso').textContent = d.aviso || $('gx-aviso').textContent;
  $('gx-fonte').innerHTML = `Fonte: <code>/api/galaxia</code> (gerado em ${esc(d.gerado_em || '—')}, a cada ronda) — Radar de risco (todos os ${fmtN(r.fornecedores_radar)} fornecedores com sinal), `
    + `${fmtN(r.alertas_abertos)} alertas abertos (${fmtN(r.alertas_no_grafo)} ancorados em fornecedor/órgão; os demais — ${esc(Object.entries(r.alertas_sem_ancora || {}).map(([t, c]) => `${fmtN(c)} ${rotAl(d, t)}`).join(', ') || 'nenhum')} — só contados), `
    + `OB contabilizada no SIAFE (órgão pagador), contratos PCRJ/PNCP, dossiês do vault, QSA público (sem CPF), grupos de endereço compartilhado. `
    + `${esc(d.nota || '')}${indisp.length ? ` <b>INDISPONÍVEL nesta geração: ${esc(indisp.join(', '))}.</b>` : ''}`;
  medir();
  const c = enquadrar(G, w, h, G.bbox, w < 760 ? .98 : .96);
  cam = {...c};
  resumo();
  carga.classList.add('ok');
  if (!QUIETO) { cam.k = c.k * .55; voar({cx: c.cx, cy: c.cy, k: c.k}, 1100); }
  sujo = true; laco();
}

if (typeof ResizeObserver === 'function') new ResizeObserver(() => G && medir()).observe(cv);
document.addEventListener('visibilitychange', () => { if (!document.hidden && G) { ant = 0; sujo = true; laco(); } });
iniciar();
