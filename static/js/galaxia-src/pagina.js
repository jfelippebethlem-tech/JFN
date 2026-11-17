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
import {preparar, enquadrar, desenhar, acertar, paraTela, semearPulsos, corScore, CRITICO} from '../src/galaxia/render.js';

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

function medir() {
  const b = cv.getBoundingClientRect();
  dpr = Math.min(devicePixelRatio || 1, 2); w = b.width; h = b.height;
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
  const pulsando = !QUIETO && G.pulsos.length > 0;
  if (!QUIETO && (sem += dt) > .28) { sem = 0; semearPulsos(G, cam, w, h, cam.k < .28 ? 2 : 3); }
  if (sujo || pulsando) {
    desenhar(ctx, G, cam, w, h, dt, {dpr, pulsos: !QUIETO});
    $('gx-nivel').textContent = nivel();
    sujo = false;
  }
  if (voo || !QUIETO) raf = requestAnimationFrame(quadro);
}

function voar(alvo, ms = 650) {
  if (QUIETO) { Object.assign(cam, alvo); sujo = true; laco(); return; }
  voo = {a: {cx: cam.cx, cy: cam.cy, k: cam.k}, b: alvo, t0: performance.now(), ms}; laco();
}
function zoomEm(px, py, f) {
  const [wx, wy] = [(px - w / 2) / cam.k + cam.cx, (py - h / 2) / cam.k + cam.cy];
  const k = Math.max(kMin(), Math.min(14, cam.k * f));
  cam.cx = wx - (px - w / 2) / k; cam.cy = wy - (py - h / 2) / k; cam.k = k; sujo = true; laco();
}
const kMin = () => enquadrar(G, w, h).k * .6;
function verTudo() { const c = enquadrar(G, w, h, G.bbox, w < 760 ? .98 : .96); voar({cx: c.cx, cy: c.cy, k: c.k}); }

/* ── gestos: arrastar, pinça, roda, toque, toque duplo ─────────────────────────────────────────── */
const ptrs = new Map();
let arrasto = null;
cv.addEventListener('pointerdown', e => {
  cv.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, {x: e.offsetX, y: e.offsetY, x0: e.offsetX, y0: e.offsetY, t0: performance.now()});
  voo = null;
  if (ptrs.size === 1) arrasto = {cx: cam.cx, cy: cam.cy, x: e.offsetX, y: e.offsetY, moveu: false};
  if (ptrs.size === 2) { const [a, b] = [...ptrs.values()]; arrasto = {pinca: Math.hypot(a.x - b.x, a.y - b.y), k: cam.k, moveu: true}; }
});
cv.addEventListener('pointermove', e => {
  const p = ptrs.get(e.pointerId);
  if (!p) {                                                         // só passando o mouse: cursor de "clicável"
    if (e.pointerType === 'mouse' && G) visor.classList.toggle('sobre-no', acertar(G, cam, w, h, e.offsetX, e.offsetY, 8) >= 0);
    return;
  }
  p.x = e.offsetX; p.y = e.offsetY;
  if (ptrs.size === 2 && arrasto && arrasto.pinca) {
    const [a, b] = [...ptrs.values()], d = Math.hypot(a.x - b.x, a.y - b.y);
    zoomEm((a.x + b.x) / 2, (a.y + b.y) / 2, (arrasto.k * d / arrasto.pinca) / cam.k);
  } else if (arrasto && ptrs.size === 1) {
    if (Math.hypot(e.offsetX - arrasto.x, e.offsetY - arrasto.y) > 6) { arrasto.moveu = true; visor.classList.add('arrastando'); }
    if (arrasto.moveu) { cam.cx = arrasto.cx - (e.offsetX - arrasto.x) / cam.k; cam.cy = arrasto.cy - (e.offsetY - arrasto.y) / cam.k; sujo = true; laco(); }
  }
});
const soltar = e => {
  const p = ptrs.get(e.pointerId); ptrs.delete(e.pointerId);
  visor.classList.remove('arrastando');
  if (p && arrasto && !arrasto.moveu && ptrs.size === 0 && performance.now() - p.t0 < 500) {
    const agora = performance.now();
    if (agora - ultimoToque < 300) { zoomEm(p.x, p.y, 2.2); ultimoToque = 0; }
    else { ultimoToque = agora; tocar(p.x, p.y); }
  }
  if (ptrs.size === 0) arrasto = null;
};
cv.addEventListener('pointerup', soltar);
cv.addEventListener('pointercancel', soltar);
cv.addEventListener('wheel', e => { e.preventDefault(); voo = null; zoomEm(e.offsetX, e.offsetY, Math.exp(-e.deltaY * (e.ctrlKey ? .01 : .0018))); }, {passive: false});
document.querySelectorAll('.gx-zoom button').forEach(b => b.addEventListener('click', () => {
  if (b.dataset.z === 'tudo') return verTudo();
  voar({cx: cam.cx, cy: cam.cy, k: Math.max(kMin(), Math.min(14, cam.k * (b.dataset.z === 'mais' ? 1.8 : 1 / 1.8)))}, 360);
}));
addEventListener('keydown', e => {
  if (e.target.closest && e.target.closest('input,select,textarea')) return;
  if (e.key === 'Escape') fecharFolha();
  if (e.key === '+' || e.key === '=') zoomEm(w / 2, h / 2, 1.5);
  if (e.key === '-') zoomEm(w / 2, h / 2, 1 / 1.5);
});

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

async function iniciar() {
  const carga = $('gx-carga');
  const d = await J('/api/galaxia');
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
