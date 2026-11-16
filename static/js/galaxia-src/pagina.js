/* GALÁXIA DOS CASOS — página própria (`/galaxia`), bundle `static/js/galaxia.bundle.js`.
 *
 * Decisão do dono (16/11/2026): a galáxia NÃO pesa no painel. O Início mostra um preview 2D leve e
 * o botão "Abrir galáxia" abre ESTA página em outra aba; só ela baixa three.js + 3d-force-graph.
 *
 * O que é desenhado (dados de `GET /api/galaxia`, sem CPF; nome de sócio só do QSA público):
 *   · estrela  = caso (dossiê conferido do vault) — tamanho e pulso pelo nível; o nível 4 pulsa mais;
 *   · planeta  = CNPJ citado pelo caso;  · lua = sócio do QSA;  · ponto ciano = processo SEI;
 *   · ponte    = dois casos que compartilham CNPJ, SEI, sócio ou entidade (partículas correm nela).
 * Ligação = indício de relação a conferir, nunca prova (o aviso da rota fica visível o tempo todo).
 *
 * Modos: 3D com brilho (desktop) · 3D sem brilho (celular ≤600px, ou máquina que não entrega quadro)
 * · 2D estático (movimento reduzido, `?modo=2d`, sem WebGL, ou FPS medido muito baixo).
 *
 * Este arquivo mora FORA de `static/js/src/` de propósito: é um entrypoint com efeito de topo
 * (o boot da página), e `src/` é vigiado pela lei "nenhum módulo tem efeito de topo" do painel.
 */
import * as THREE from 'three';
import ForceGraph3D from '3d-force-graph';
import {UnrealBloomPass} from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import {layoutEspiral, desenhar2D, COR, h01} from '../src/galaxia/layout.js';
import {mdNota} from '../src/abas/casos.js';
import {esc} from '../src/nucleo/dom.js';
import {fmtN, fmtRc} from '../src/nucleo/formato.js';
import {J, erroHumano} from '../src/nucleo/http.js';

const $ = id => document.getElementById(id);
const TIPOS = {
  caso: {rot: 'Casos', sing: 'Caso (dossiê)', cor: COR.ciano},
  cnpj: {rot: 'Empresas', sing: 'Empresa (CNPJ)', cor: COR.ion},
  socio: {rot: 'Sócios', sing: 'Sócio (QSA público)', cor: COR.gelo},
  sei: {rot: 'Processos SEI', sing: 'Processo SEI', cor: '#3FD0FF'},
};
const NIVEL = ['sem grau', 'baixo', 'médio', 'médio-alto', 'alto'];
const MOTIVO = {cnpj: ['CNPJ', 'CNPJs'], sei: ['processo SEI', 'processos SEI'], socio: ['sócio', 'sócios'], entidade: ['entidade', 'entidades']};

const qs = new URLSearchParams(location.search);
const redMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const celular = matchMedia('(max-width: 600px)').matches;

const E = {
  dados: null, nos: [], porId: new Map(), viz: new Map(), pontes: new Set(),
  tipos: new Set(Object.keys(TIPOS)), soPontes: false,
  graph: null, modo: '', halos: [], estrelas: null, bloom: null, mx: 0, my: 0,
  ocioso: 0, voando: null, pos2d: null, P2d: null, hover: null,
};

/* ── utilidades ─────────────────────────────────────────────────────────────────────────── */
const norm = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const fmtCnpj = c => String(c || '').replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, '$1.$2.$3/$4-$5');
const idDe = x => (x && typeof x === 'object' ? x.id : x);

function textoGlow() {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d'), r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  r.addColorStop(0, 'rgba(255,255,255,1)'); r.addColorStop(0.18, 'rgba(255,255,255,.85)');
  r.addColorStop(0.42, 'rgba(255,255,255,.22)'); r.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = r; g.fillRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

/* ── HUD ────────────────────────────────────────────────────────────────────────────────── */
function contar(el, alvo) {
  if (!el) return;
  if (alvo == null) { el.textContent = '—'; return; }
  if (redMotion) { el.textContent = fmtN(alvo); return; }
  const t0 = performance.now(), dur = 1100;
  const passo = t => { const k = Math.min(1, (t - t0) / dur), e = 1 - (1 - k) ** 3;
    el.textContent = fmtN(Math.round(alvo * e)); if (k < 1) requestAnimationFrame(passo); };
  requestAnimationFrame(passo);
}

function montarHud() {
  const r = E.dados.resumo || {};
  const itens = [['casos', 'casos'], ['cnpjs', 'empresas'], ['socios', 'sócios'], ['processos_sei', 'processos SEI'],
    ['arestas', 'ligações'], ['pontes_entre_casos', 'pontes entre casos']];
  $('gx-num').innerHTML = itens.map(([k, rot]) =>
    `<div class="gx-k${k === 'pontes_entre_casos' ? ' gx-k-ponte' : ''}"><b data-k="${k}">0</b><span>${rot}</span></div>`).join('');
  for (const b of $('gx-num').querySelectorAll('b[data-k]')) contar(b, r[b.dataset.k]);
  const cont = {}; for (const n of E.nos) cont[n.tipo] = (cont[n.tipo] || 0) + 1;
  $('gx-leg').innerHTML = Object.entries(TIPOS).map(([k, t]) =>
    `<button type="button" class="gx-chip on" data-gx-tipo="${k}" aria-pressed="true"><i class="gx-dot gx-dot-${k}"></i>${t.rot}<em>${fmtN(cont[k] || 0)}</em></button>`).join('')
    + `<button type="button" class="gx-chip gx-chip-ponte" data-gx-pontes aria-pressed="false"><i class="gx-dot gx-dot-ponte"></i>Só pontes entre casos<em>${fmtN(r.pontes_entre_casos)}</em></button>`;
  $('gx-aviso').textContent = E.dados.aviso || 'Ligação = indício de relação a conferir, nunca prova.';
}

function visivelNo(n) { return E.tipos.has(n.tipo) && (!E.soPontes || E.pontes.has(n.id)); }
function visivelAresta(l) {
  if (E.soPontes && l.tipo !== 'caso_caso') return false;
  const a = E.porId.get(idDe(l.source)), b = E.porId.get(idDe(l.target));
  return !!(a && b && visivelNo(a) && visivelNo(b));
}
function aplicarFiltro() {
  if (E.graph) pintarCores();
  else if (E.modo === '2d') pintar2D();
}

function ligarControles() {
  $('gx-leg').addEventListener('click', ev => {
    const t = ev.target.closest('[data-gx-tipo]'), p = ev.target.closest('[data-gx-pontes]');
    if (t) {
      const k = t.dataset.gxTipo, on = !E.tipos.has(k);
      if (on) E.tipos.add(k); else E.tipos.delete(k);
      t.classList.toggle('on', on); t.setAttribute('aria-pressed', on); aplicarFiltro();
    } else if (p) {
      E.soPontes = !E.soPontes; p.classList.toggle('on', E.soPontes); p.setAttribute('aria-pressed', E.soPontes); aplicarFiltro();
    }
  });
  const q = $('gx-q'), lista = $('gx-res');
  let sel = 0, achados = [];
  const pintarRes = () => {
    lista.hidden = !achados.length;
    lista.innerHTML = achados.map((n, i) => `<li role="option" aria-selected="${i === sel}" data-gx-ir="${esc(n.id)}" class="${i === sel ? 'on' : ''}">
      <i class="gx-dot gx-dot-${n.tipo}"></i><span>${esc(n.label)}</span><em>${TIPOS[n.tipo].sing}${n.tipo === 'caso' ? ' · ' + esc(n.nivel_rotulo || '') : ''}</em></li>`).join('');
  };
  q.addEventListener('input', () => {
    const t = norm(q.value.trim()); sel = 0;
    achados = t.length < 2 ? [] : E.nos.filter(n => norm(n.label + ' ' + (n.cnpj || '') + ' ' + (n.slug || '') + ' ' + (n.entidade || '')).includes(t))
      .sort((a, b) => (a.tipo === 'caso' ? 0 : 1) - (b.tipo === 'caso' ? 0 : 1) || (b.grau || 0) - (a.grau || 0)).slice(0, 8);
    pintarRes();
  });
  q.addEventListener('keydown', ev => {
    if (ev.key === 'ArrowDown') { sel = Math.min(achados.length - 1, sel + 1); pintarRes(); ev.preventDefault(); }
    else if (ev.key === 'ArrowUp') { sel = Math.max(0, sel - 1); pintarRes(); ev.preventDefault(); }
    else if (ev.key === 'Enter' && achados[sel]) { irPara(achados[sel]); lista.hidden = true; }
    else if (ev.key === 'Escape') { lista.hidden = true; }
  });
  lista.addEventListener('click', ev => {
    const li = ev.target.closest('[data-gx-ir]'); if (!li) return;
    irPara(E.porId.get(li.dataset.gxIr)); lista.hidden = true;
  });
  $('gx-folha').addEventListener('click', ev => {
    if (ev.target.closest('[data-gx-fechar]')) { fecharFolha(); return; }
    const a = ev.target.closest('[data-gx-ir]');
    if (a) { const n = E.porId.get(a.dataset.gxIr); if (n) { irPara(n); abrir(n); } }
  });
  addEventListener('keydown', ev => { if (ev.key === 'Escape') fecharFolha(); });
  const visor = $('gx-visor');
  visor.addEventListener('pointermove', ev => {
    const r = visor.getBoundingClientRect(); E.mx = ev.clientX - r.left; E.my = ev.clientY - r.top;
    if (E.modo === '2d') hover2D(); else { posicionarTip(); hover3D(); }
  });
  visor.addEventListener('pointerleave', () => { mostrarTip(null); });
  visor.addEventListener('click', () => { if (E.modo === '2d' && E.hover) abrir(E.hover); });
}

/* ── tooltip ────────────────────────────────────────────────────────────────────────────── */
function tipNo(n) {
  const t = TIPOS[n.tipo];
  let h = `<div class="gx-tip-eye"><i class="gx-dot gx-dot-${n.tipo}"></i>${t.sing}</div><div class="gx-tip-tit">${esc(n.label)}</div><dl>`;
  if (n.tipo === 'caso') h += `<dt>Nível</dt><dd>${esc(n.nivel_rotulo || NIVEL[n.nivel || 0])} <span class="gx-niv">${'▮'.repeat(n.nivel || 0)}${'▯'.repeat(4 - (n.nivel || 0))}</span></dd>`
    + (n.situacao ? `<dt>Situação</dt><dd>${esc(n.situacao)}</dd>` : '') + (n.entidade ? `<dt>Entidade</dt><dd>${esc(n.entidade)}</dd>` : '');
  if (n.tipo === 'cnpj') h += `<dt>CNPJ</dt><dd class="gx-mono">${esc(fmtCnpj(n.cnpj))}</dd>`;
  h += `<dt>Ligações</dt><dd class="gx-mono">${fmtN(n.grau || 0)}</dd></dl>`;
  if (n.tipo === 'caso' || n.tipo === 'cnpj') h += `<div class="gx-tip-pe">clique para ${n.tipo === 'caso' ? 'ler o dossiê' : 'abrir a empresa'}</div>`;
  return h;
}
function tipAresta(l) {
  const a = E.porId.get(idDe(l.source)), b = E.porId.get(idDe(l.target));
  const m = Object.entries(l.motivos || {}).map(([k, v]) => `<li><b class="gx-mono">${fmtN(v)}</b> ${esc((MOTIVO[k] || [k, k])[v > 1 ? 1 : 0])} em comum</li>`).join('');
  return `<div class="gx-tip-eye"><i class="gx-dot gx-dot-ponte"></i>Ponte entre casos · peso ${fmtN(l.peso)}</div>
    <div class="gx-tip-tit gx-tip-par">${esc(a ? a.label : '')}<span>⟷</span>${esc(b ? b.label : '')}</div>
    ${m ? `<ul class="gx-tip-mot">${m}</ul>` : ''}<div class="gx-tip-pe">indício de relação — conferir nos dois dossiês</div>`;
}
function mostrarTip(html) {
  const t = $('gx-tip');
  if (!html) { t.classList.remove('on'); t.setAttribute('aria-hidden', 'true'); return; }
  t.innerHTML = html; t.classList.add('on'); t.setAttribute('aria-hidden', 'false'); posicionarTip();
}
function posicionarTip() {
  const t = $('gx-tip'); if (!t.classList.contains('on')) return;
  const v = $('gx-visor'), W = v.clientWidth, H = v.clientHeight, w = t.offsetWidth, h = t.offsetHeight;
  let x = E.mx + 18, y = E.my + 18;
  if (x + w > W - 12) x = E.mx - w - 18; if (y + h > H - 12) y = E.my - h - 18;
  t.style.transform = `translate(${Math.max(12, x)}px,${Math.max(12, y)}px)`;
}

/* ── folha lateral (nota do caso / empresa / vizinhos) ─────────────────────────────────── */
function vizinhosHtml(n) {
  const v = (E.viz.get(n.id) || []).map(id => E.porId.get(id)).filter(Boolean)
    .sort((a, b) => (a.tipo === 'caso' ? 0 : 1) - (b.tipo === 'caso' ? 0 : 1) || (b.grau || 0) - (a.grau || 0));
  if (!v.length) return '';
  return `<h4 class="gx-sec">Ligações na galáxia · ${fmtN(v.length)}</h4><ul class="gx-viz">${v.slice(0, 40).map(x =>
    `<li><button type="button" data-gx-ir="${esc(x.id)}"><i class="gx-dot gx-dot-${x.tipo}"></i><span>${esc(x.label)}</span><em>${TIPOS[x.tipo].sing}</em></button></li>`).join('')}</ul>`;
}
function folha(html) {
  const f = $('gx-folha');
  f.innerHTML = `<div class="gx-folha-top"><button type="button" class="gx-x" data-gx-fechar aria-label="Fechar">✕ fechar</button></div><div class="gx-folha-corpo">${html}</div>`;
  f.hidden = false; requestAnimationFrame(() => f.classList.add('on'));
}
function fecharFolha() { const f = $('gx-folha'); f.classList.remove('on'); f.hidden = true; }

async function abrir(n) {
  if (!n) return;
  mostrarTip(null);
  if (n.tipo === 'caso') {
    folha(`<div class="gx-carregando">Abrindo o dossiê…</div>`);
    const d = await J('/api/casos/nota?slug=' + encodeURIComponent(n.slug));
    const topo = `<div class="gx-f-eye"><i class="gx-dot gx-dot-caso"></i>Caso · nível ${esc(n.nivel_rotulo || '')}${n.situacao ? ' · ' + esc(n.situacao) : ''}</div>
      ${n.entidade ? `<div class="gx-f-ent">${esc(n.entidade)}</div>` : ''}`;
    if (!d || d.ok === false) { folha(topo + `<div class="gx-warn">${esc(erroHumano(d && d.erro))}</div>` + vizinhosHtml(n)); return; }
    folha(topo + `<article class="gx-nota">${mdNota(d.markdown)}</article>
      <div class="gx-f-pe">Nota do vault: <code>casos/${esc(n.slug)}.md</code> — esta folha só lê. <a href="/painel#g_casos" target="_blank" rel="noopener">Abrir a aba Casos no painel ↗</a></div>` + vizinhosHtml(n));
    return;
  }
  if (n.tipo === 'cnpj') {
    folha(`<div class="gx-carregando">Abrindo a empresa…</div>`);
    const d = await J('/api/perfil?cnpj=' + encodeURIComponent(n.cnpj));
    let h = `<div class="gx-f-eye"><i class="gx-dot gx-dot-cnpj"></i>Empresa citada em dossiê</div><h3 class="gx-f-tit">${esc((d && d.nome) || n.label)}</h3>
      <div class="gx-mono gx-f-ent">${esc(fmtCnpj(n.cnpj))}</div>`;
    if (d && d.ok !== false) {
      const ob = d.ob || {}, per = d.pericia || {};
      h += `<div class="gx-mini"><div><b>${ob.total == null ? 'indisponível' : esc(fmtRc(ob.total))}</b><span>Pago pelo Estado (OB)</span></div>
        <div><b>${ob.orgaos == null ? '—' : fmtN(ob.orgaos)}</b><span>Órgãos pagadores</span></div>
        <div><b>${esc(per.grau || '⚪')}</b><span>Perícia${per.score != null ? ' · score ' + esc(per.score) : ''}</span></div></div>
        <div class="gx-f-pe">Fonte: <code>/api/perfil</code> — OB = Ordem Bancária (pagamento efetivo).</div>`;
      if ((d.socios || []).length) h += `<h4 class="gx-sec">Quadro societário (QSA público)</h4><ul class="gx-qsa">${d.socios.slice(0, 12).map(s => `<li>${esc(s.nome)}<em>${esc(s.qualificacao || '')}</em></li>`).join('')}</ul>`;
    } else h += `<div class="gx-warn">${esc(erroHumano(d && d.erro))}</div>`;
    folha(h + vizinhosHtml(n));
    return;
  }
  folha(`<div class="gx-f-eye"><i class="gx-dot gx-dot-${n.tipo}"></i>${TIPOS[n.tipo].sing}</div><h3 class="gx-f-tit">${esc(n.label)}</h3>` + vizinhosHtml(n));
}

/* ── 3D ─────────────────────────────────────────────────────────────────────────────────────
 * DESENHO EM LOTE. A primeira versão dava um objeto three.js por nó e por aresta (~1.500 chamadas de
 * desenho por quadro): medido no Chromium headless (SwiftShader) desta VM, 2 quadros em 40 s. Agora
 * o 3d-force-graph cuida só da simulação de forças, da câmera, dos controles e do compositor; o que
 * se vê são QUATRO camadas, cada uma uma chamada de desenho: estrelas do fundo, nós (um `Points` com
 * shader — estrela, planeta, lua e ponto saem do mesmo programa), arestas (`LineSegments`) e as
 * partículas das pontes (posição calculada no próprio shader, nada de CPU por quadro).
 * O hover/clique é por projeção dos nós na tela (491 projeções por movimento do ponteiro). */
const FORMA = {caso: 0, cnpj: 1, socio: 2, sei: 3};

function campoEstrelas(n, pr) {
  const p = new Float32Array(n * 3), fase = new Float32Array(n), tam = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const u = h01('u' + i) * 2 - 1, th = h01('t' + i) * Math.PI * 2, r = 1400 + h01('r' + i) * 2200, s = Math.sqrt(1 - u * u);
    p[i * 3] = r * s * Math.cos(th); p[i * 3 + 1] = r * u; p[i * 3 + 2] = r * s * Math.sin(th);
    fase[i] = h01('f' + i); tam[i] = 1 + 2.2 * h01('s' + i) ** 3;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(p, 3));
  geo.setAttribute('fase', new THREE.BufferAttribute(fase, 1));
  geo.setAttribute('tam', new THREE.BufferAttribute(tam, 1));
  const mat = new THREE.ShaderMaterial({
    uniforms: {uT: {value: 0}, uPR: {value: pr}},
    vertexShader: `attribute float fase; attribute float tam; uniform float uT; uniform float uPR; varying float vA;
      void main(){ vA = .35 + .65 * (.5 + .5 * sin(uT * (0.6 + fase) * 1.7 + fase * 6.2831));
        gl_PointSize = tam * uPR * (0.8 + .4 * vA); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }`,
    fragmentShader: `varying float vA; void main(){ float d = length(gl_PointCoord - .5); float a = smoothstep(.5, .0, d) * vA;
        gl_FragColor = vec4(vec3(.72, .86, 1.) * a, a); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const pts = new THREE.Points(geo, mat); pts.frustumCulled = false; return pts;
}

function camadaNos(nodes, pr) {
  const n = nodes.length, pos = new Float32Array(n * 3), cor = new Float32Array(n * 3);
  const tam = new Float32Array(n), fase = new Float32Array(n), amp = new Float32Array(n), forma = new Float32Array(n), vis = new Float32Array(n);
  const c = new THREE.Color();
  nodes.forEach((no, i) => {
    const nv = no.nivel || 0;
    if (no.tipo === 'caso') { c.set(nv >= 4 ? COR.ciano : nv >= 2 ? COR.ion : '#2F5FC4'); tam[i] = 24 + nv * 8; amp[i] = nv >= 4 ? 0.26 : 0.07; }
    else if (no.tipo === 'cnpj') { c.set('#2C8BFF'); tam[i] = 14; }
    else if (no.tipo === 'socio') { c.set(COR.gelo); tam[i] = 8; }
    else { c.set('#3FD0FF'); tam[i] = 7.5; }
    cor.set([c.r, c.g, c.b], i * 3); fase[i] = h01(no.id) * 6.2831; forma[i] = FORMA[no.tipo]; vis[i] = visivelNo(no) ? 1 : 0;
  });
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
  for (const [k, v] of Object.entries({cor: [cor, 3], tam: [tam, 1], fase: [fase, 1], amp: [amp, 1], forma: [forma, 1], vis: [vis, 1]}))
    geo.setAttribute(k, new THREE.BufferAttribute(v[0], v[1]));
  const mat = new THREE.ShaderMaterial({
    uniforms: {uT: {value: 0}, uPR: {value: pr}, uEsc: {value: 520}},
    vertexShader: `attribute vec3 cor; attribute float tam, fase, amp, forma, vis; uniform float uT, uPR, uEsc;
      varying vec3 vCor; varying float vForma, vPulso;
      void main(){ vec4 mv = modelViewMatrix * vec4(position, 1.); vCor = cor; vForma = forma;
        float vel = amp > .2 ? 2.3 : 1.1; vPulso = 1. + amp * sin(uT * vel + fase);
        gl_PointSize = vis * tam * vPulso * uPR * uEsc / max(1., -mv.z); gl_Position = projectionMatrix * mv; }`,
    fragmentShader: `varying vec3 vCor; varying float vForma, vPulso;
      void main(){ vec2 q = gl_PointCoord - .5; float d = length(q); if (d > .5) discard; vec3 col; float a;
        if (vForma < .5) {                       // estrela: núcleo branco + halo + raios finos
          float nucleo = smoothstep(.11, .0, d), halo = exp(-d * d * 16.) * .9 + exp(-d * d * 70.) * .6;
          float raio = (exp(-abs(q.x) * 70.) + exp(-abs(q.y) * 70.)) * smoothstep(.5, .0, d) * .35 * vPulso;
          col = vCor * (halo + raio) + vec3(1.) * nucleo; a = clamp(halo + nucleo + raio, 0., 1.);
        } else if (vForma < 1.5) {               // planeta: disco com borda iluminada e atmosfera
          float disco = smoothstep(.24, .22, d), borda = smoothstep(.16, .23, d) * disco, atm = exp(-pow(max(d - .22, 0.) * 14., 2.)) * (1. - disco);
          vec3 base = mix(vCor * .55, vCor * 1.2, smoothstep(.2, -.2, q.x + q.y));
          col = base * disco + vec3(.75, .93, 1.) * borda * .8 + vCor * atm * .7; a = max(disco, atm * .7);
        } else {                                 // lua / processo SEI: ponto com brilho curto
          float nucleo = smoothstep(.22, .12, d), halo = exp(-d * d * 30.) * .6;
          col = vCor * halo + mix(vCor, vec3(1.), .55) * nucleo; a = clamp(nucleo + halo, 0., 1.);
        }
        gl_FragColor = vec4(col * a, a); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const pts = new THREE.Points(geo, mat); pts.frustumCulled = false; return pts;
}

function camadaArestas(links, ponte) {
  const ls = links.filter(ponte), n = ls.length;
  const pos = new Float32Array(n * 6), cor = new Float32Array(n * 8);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
  geo.setAttribute('cor', new THREE.BufferAttribute(cor, 4));
  const mat = new THREE.ShaderMaterial({
    vertexShader: `attribute vec4 cor; varying vec4 vC; void main(){ vC = cor; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }`,
    fragmentShader: `varying vec4 vC; void main(){ gl_FragColor = vec4(vC.rgb * vC.a, vC.a); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const obj = new THREE.LineSegments(geo, mat); obj.frustumCulled = false;
  return {obj, ls};
}

function camadaParticulas(pontes, porArestas, pr) {
  const tot = pontes.length * porArestas;
  const a = new Float32Array(tot * 3), b = new Float32Array(tot * 3), t0 = new Float32Array(tot), vel = new Float32Array(tot), vis = new Float32Array(tot);
  pontes.forEach((l, i) => { for (let k = 0; k < porArestas; k++) {
    const j = i * porArestas + k; t0[j] = k / porArestas + h01(l.source + k) * 0.1; vel[j] = 0.10 + Math.min(8, l.peso || 1) * 0.012; vis[j] = 1; } });
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(a, 3).setUsage(THREE.DynamicDrawUsage));
  geo.setAttribute('alvo', new THREE.BufferAttribute(b, 3).setUsage(THREE.DynamicDrawUsage));
  geo.setAttribute('t0', new THREE.BufferAttribute(t0, 1));
  geo.setAttribute('vel', new THREE.BufferAttribute(vel, 1));
  geo.setAttribute('vis', new THREE.BufferAttribute(vis, 1));
  const mat = new THREE.ShaderMaterial({
    uniforms: {uT: {value: 0}, uPR: {value: pr}},
    vertexShader: `attribute vec3 alvo; attribute float t0, vel, vis; uniform float uT, uPR; varying float vA;
      void main(){ float f = fract(t0 + uT * vel); vec3 p = mix(position, alvo, f); vA = sin(f * 3.14159);
        vec4 mv = modelViewMatrix * vec4(p, 1.); gl_PointSize = vis * uPR * 4.2 * (300. / max(1., -mv.z)) + vis * 2.; gl_Position = projectionMatrix * mv; }`,
    fragmentShader: `varying float vA; void main(){ float d = length(gl_PointCoord - .5); float a = smoothstep(.5, .0, d) * vA;
        gl_FragColor = vec4(vec3(.85, .97, 1.) * a, a); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const obj = new THREE.Points(geo, mat); obj.frustumCulled = false; return obj;
}

/* Anel de varredura holográfico no plano da galáxia: um arco claro gira em volta do disco. Fino → barato. */
function anelVarredura(raio) {
  const geo = new THREE.RingGeometry(raio, raio + 2.2, 256, 1);
  const mat = new THREE.ShaderMaterial({
    uniforms: {uT: {value: 0}},
    vertexShader: `varying vec2 vP; void main(){ vP = position.xy; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }`,
    fragmentShader: `uniform float uT; varying vec2 vP;
      void main(){ float a = atan(vP.y, vP.x); float f = fract((a / 6.28318) - uT * .045);
        float arco = pow(f, 10.) * .95, tique = step(.82, fract(a * 24. / 6.28318)) * .10;
        float k = .07 + arco + tique; gl_FragColor = vec4(vec3(.5, .86, 1.) * k, k); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
  });
  const m = new THREE.Mesh(geo, mat); m.rotation.x = -Math.PI / 2; return m;
}

function montar3D() {
  const visor = $('gx-cena');
  const W = visor.clientWidth, H = visor.clientHeight;
  const pr = Math.min(window.devicePixelRatio || 1, celular ? 1 : 1.5);
  const pos = layoutEspiral(E.dados, 340);
  const nodes = E.nos.map(n => { const p = pos[n.id] || {x: 0, y: 0, z: 0}; return Object.assign({}, n, {x: p.x, y: p.z, z: p.y}); });
  const idx = new Map(nodes.map((n, i) => [n.id, i]));
  const links = (E.dados.arestas || []).map(a => Object.assign({}, a));
  const ponte = l => l.tipo === 'caso_caso';
  const stub = new THREE.Object3D();
  const g = new ForceGraph3D(visor, {controlType: 'orbit', rendererConfig: {antialias: false, alpha: false, powerPreference: 'high-performance'}})
    .width(W).height(H).backgroundColor(COR.fundo).showNavInfo(false)
    .enablePointerInteraction(false).enableNodeDrag(false)
    .nodeId('id').nodeThreeObject(() => stub.clone()).nodeThreeObjectExtend(false)
    .linkVisibility(false)
    .warmupTicks(60).cooldownTicks(140).cooldownTime(7000)
    .graphData({nodes, links});
  E.graph = g; E.nodes3 = nodes; E.idx3 = idx;
  g.renderer().setPixelRatio(pr);
  g.d3Force('charge').strength(-22).distanceMax(260);
  g.d3Force('link').distance(l => ponte(l) ? 70 : l.tipo === 'socio' ? 9 : l.tipo === 'cita_sei' ? 26 : 22)
    .strength(l => ponte(l) ? 0.04 : 0.5);
  let ns = [];
  const disco = a => { for (const n of ns) { n.vy -= (n.y || 0) * 0.08 * a; n.vx -= (n.x || 0) * 0.012 * a; n.vz -= (n.z || 0) * 0.012 * a; } };   // achata num disco e puxa para o núcleo
  disco.initialize = x => { ns = x; };
  g.d3Force('disco', disco);

  const cena = g.scene();
  E.estrelas = campoEstrelas(celular ? 900 : 2600, pr); cena.add(E.estrelas);
  const tex = textoGlow();
  const nebulosa = (x, y, z, s, cor, op) => { const sp = new THREE.Sprite(new THREE.SpriteMaterial({map: tex, color: new THREE.Color(cor),
    blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, opacity: op}));
    sp.position.set(x, y, z); sp.scale.set(s, s, 1); cena.add(sp); return sp; };
  E.nucleoGal = nebulosa(0, 0, 0, 260, COR.gelo, 0.14);       // brilho do núcleo galáctico
  nebulosa(0, 0, 0, 700, COR.ion, 0.06);
  nebulosa(-700, 260, -1500, 1100, COR.marinho, 0.16);
  /* eram dois sprites de tela cheia (custo de preenchimento puro no SwiftShader); ficou um, menor e distante. */

  E.cNos = camadaNos(nodes, pr);
  E.cFio = camadaArestas(links, l => !ponte(l));
  E.cPonte = camadaArestas(links, ponte);
  E.cPart = camadaParticulas(E.cPonte.ls, celular ? 1 : 3, pr);
  cena.add(E.cFio.obj, E.cPonte.obj, E.cPart, E.cNos);
  E.anel = anelVarredura(430); cena.add(E.anel);
  pintarCores();
  atualizarPosicoes();
  g.onEngineTick(atualizarPosicoes);

  if (!celular && !qs.has('sembrilho')) {
    E.bloom = new UnrealBloomPass(new THREE.Vector2(Math.round(W / 2), Math.round(H / 2)), 1.0, 0.6, 0.06);
    g.postProcessingComposer().addPass(E.bloom);
  }
  g.cameraPosition({x: 0, y: 330, z: 600}, {x: 0, y: 0, z: 0}, 0);
  /* enquadra o disco depois do aquecimento e de novo quando as forças assentam (uma vez cada) */
  setTimeout(() => { if (E.graph) enquadrar(0); }, 60);
  let assentou = false;
  g.onEngineStop(() => { if (!assentou && E.graph) { assentou = true; enquadrar(redMotion ? 0 : 1600); } });
  const ctl = g.controls();
  ctl.autoRotate = !redMotion; ctl.autoRotateSpeed = 0.45; ctl.enableDamping = true; ctl.dampingFactor = 0.08;
  ctl.minDistance = 40; ctl.maxDistance = 1800;
  ctl.addEventListener('start', () => { ctl.autoRotate = false; E.ocioso = performance.now(); mostrarTip(null); });
  ctl.addEventListener('end', () => { E.ocioso = performance.now(); });

  const t0 = performance.now();
  cena.onBeforeRender = () => {                                   // roda no laço do próprio grafo
    const t = (performance.now() - t0) / 1000;
    E.estrelas.material.uniforms.uT.value = t;
    E.cNos.material.uniforms.uT.value = t;
    E.cPart.material.uniforms.uT.value = t;
    E.anel.material.uniforms.uT.value = redMotion ? 0 : t;
    E.cNos.material.uniforms.uEsc.value = g.renderer().domElement.clientHeight * 0.62;
    if (!ctl.autoRotate && !redMotion && E.ocioso && performance.now() - E.ocioso > 9000) { ctl.autoRotate = true; E.ocioso = 0; }
    E.quadros = (E.quadros || 0) + 1;
  };
  const cv = g.renderer().domElement;
  let pd = null;
  cv.addEventListener('pointerdown', ev => { pd = [ev.clientX, ev.clientY]; });
  cv.addEventListener('pointerup', ev => {
    if (!pd || Math.hypot(ev.clientX - pd[0], ev.clientY - pd[1]) > 6) return;
    const n = pick3D(); if (n) { irPara(n); abrir(n); } else mostrarTip(null);
  });
  E.ro = new ResizeObserver(() => { const w = visor.clientWidth, h = visor.clientHeight; if (w && h && E.graph) g.width(w).height(h); });
  E.ro.observe(visor);
  document.addEventListener('visibilitychange', () => { if (!E.graph) return; if (document.hidden) g.pauseAnimation(); else g.resumeAnimation(); });
  addEventListener('pagehide', destruir);
  vigiarFps();
}

function enquadrar(ms) {
  let r = 1;
  for (const n of E.nodes3) if (visivelNo(n)) r = Math.max(r, Math.hypot(n.x || 0, n.z || 0));
  r = Math.min(r, 900);
  const d = r * (celular ? 2.4 : 1.6);
  E.graph.cameraPosition({x: 0, y: d * 0.52, z: d * 0.86}, {x: 0, y: 0, z: 0}, ms);
}

function atualizarPosicoes() {
  const ns = E.nodes3, ix = E.idx3; if (!ns) return;
  const P = E.cNos.geometry.attributes.position.array;
  ns.forEach((n, i) => { P[i * 3] = n.x || 0; P[i * 3 + 1] = n.y || 0; P[i * 3 + 2] = n.z || 0; });
  E.cNos.geometry.attributes.position.needsUpdate = true;
  for (const c of [E.cFio, E.cPonte]) {
    const A = c.obj.geometry.attributes.position.array;
    c.ls.forEach((l, k) => { const a = ix.get(idDe(l.source)), b = ix.get(idDe(l.target));
      A.set([P[a * 3], P[a * 3 + 1], P[a * 3 + 2], P[b * 3], P[b * 3 + 1], P[b * 3 + 2]], k * 6); });
    c.obj.geometry.attributes.position.needsUpdate = true;
  }
  const per = E.cPart.geometry.attributes.position.count / Math.max(1, E.cPonte.ls.length);
  const pa = E.cPart.geometry.attributes.position.array, pb = E.cPart.geometry.attributes.alvo.array;
  E.cPonte.ls.forEach((l, k) => { const a = ix.get(idDe(l.source)), b = ix.get(idDe(l.target));
    for (let j = 0; j < per; j++) { const o = (k * per + j) * 3;
      pa.set([P[a * 3], P[a * 3 + 1], P[a * 3 + 2]], o); pb.set([P[b * 3], P[b * 3 + 1], P[b * 3 + 2]], o); } });
  E.cPart.geometry.attributes.position.needsUpdate = true; E.cPart.geometry.attributes.alvo.needsUpdate = true;
}

/* Visibilidade e realce: tudo em atributos — nada é recriado ao filtrar. */
function pintarCores() {
  if (!E.cNos) return;
  const vis = E.cNos.geometry.attributes.vis.array;
  E.nodes3.forEach((n, i) => { vis[i] = visivelNo(n) ? (E.hover && E.hover.id === n.id ? 1.7 : 1) : 0; });
  E.cNos.geometry.attributes.vis.needsUpdate = true;
  const foco = E.hover ? E.hover.id : null;
  const tinta = (c, base, forte) => {
    const C = c.obj.geometry.attributes.cor.array;
    c.ls.forEach((l, k) => { const s = idDe(l.source), t = idDe(l.target), v = visivelAresta(l);
      const toca = foco && (s === foco || t === foco);
      const [r, g, b, a] = toca ? forte : base, al = v ? a : 0;
      C.set([r, g, b, al, r, g, b, al], k * 8); });
    c.obj.geometry.attributes.cor.needsUpdate = true;
  };
  tinta(E.cFio, [0.16, 0.55, 1, 0.20], [0.6, 0.9, 1, 0.75]);
  tinta(E.cPonte, [0.55, 0.9, 1, 0.85], [0.9, 1, 1, 1]);
  const pv = E.cPart.geometry.attributes.vis.array, per = pv.length / Math.max(1, E.cPonte.ls.length);
  E.cPonte.ls.forEach((l, k) => { const v = visivelAresta(l) ? 1 : 0; for (let j = 0; j < per; j++) pv[k * per + j] = v; });
  E.cPart.geometry.attributes.vis.needsUpdate = true;
}

const _v3 = new THREE.Vector3();
function telaDe(n) {
  const g = E.graph, cam = g.camera(), el = g.renderer().domElement;
  _v3.set(n.x || 0, n.y || 0, n.z || 0).project(cam);
  if (_v3.z > 1) return null;
  return {x: (_v3.x + 1) / 2 * el.clientWidth, y: (1 - _v3.y) / 2 * el.clientHeight};
}
function pick3D() {
  if (!E.graph) return null;
  let melhor = null, dm = 16 * 16;
  for (const n of E.nodes3) {
    if (!visivelNo(n)) continue;
    const p = telaDe(n); if (!p) continue;
    const d = (p.x - E.mx) ** 2 + (p.y - E.my) ** 2, r = n.tipo === 'caso' ? 18 : 12;
    if (d < Math.min(dm, r * r) + 1) { dm = d; melhor = n; }
  }
  return melhor;
}
function pickPonte() {
  let melhor = null, dm = 7 * 7;
  for (const l of E.cPonte.ls) {
    if (!visivelAresta(l)) continue;
    const a = telaDe(E.nodes3[E.idx3.get(idDe(l.source))]), b = telaDe(E.nodes3[E.idx3.get(idDe(l.target))]); if (!a || !b) continue;
    const vx = b.x - a.x, vy = b.y - a.y, L = vx * vx + vy * vy || 1;
    const t = Math.max(0, Math.min(1, ((E.mx - a.x) * vx + (E.my - a.y) * vy) / L));
    const d = (a.x + t * vx - E.mx) ** 2 + (a.y + t * vy - E.my) ** 2;
    if (d < dm) { dm = d; melhor = l; }
  }
  return melhor;
}
let _pickAg = 0;
function hover3D() {
  if (_pickAg) return;
  _pickAg = requestAnimationFrame(() => {
    _pickAg = 0; if (!E.graph) return;
    const n = pick3D();
    E.graph.renderer().domElement.style.cursor = n ? 'pointer' : '';
    if (n !== E.hover) { E.hover = n; pintarCores(); }
    if (n) { mostrarTip(tipNo(n)); return; }
    const l = pickPonte();
    mostrarTip(l ? tipAresta(l) : null);
  });
}

function irPara(n) {
  if (!n) return;
  if (E.modo === '2d') { E.hover = n; pintar2D(); return; }
  const g = E.graph; if (!g) return;
  const no = E.nodes3[E.idx3.get(n.id)]; if (!no) return;
  const d = Math.hypot(no.x, no.y, no.z) || 1, dist = no.tipo === 'caso' ? 110 : 70, k = 1 + dist / d;
  g.controls().autoRotate = false; E.ocioso = performance.now() + 6000;
  g.cameraPosition({x: no.x * k, y: no.y * k + 30, z: no.z * k}, {x: no.x, y: no.y, z: no.z}, redMotion ? 0 : 1800);
  E.hover = no; pintarCores();
}

/* Mede o FPS DEPOIS do aquecimento e desce degraus, do mais barato de perder ao mais caro:
   brilho + resolução interna 60% → resolução 45% → 2D estático (só abaixo de 6 fps, para que uma amostra
   ruim numa máquina ocupada não derrube a galáxia viva). Cada degrau espera 1 s e mede 3 s. */
function vigiarFps() {
  const medir = (fim) => setTimeout(() => { const q0 = E.quadros || 0, t0 = performance.now();
    setTimeout(() => { if (!document.hidden && E.graph) fim(((E.quadros || 0) - q0) * 1000 / (performance.now() - t0)); }, 3000); }, 1000);
  const resolucao = k => {
    E.graph.renderer().setPixelRatio(Math.min(window.devicePixelRatio || 1, 1) * k); E.resReduzida = true;
    E.cNos.material.uniforms.uPR.value = E.cPart.material.uniforms.uPR.value = E.estrelas.material.uniforms.uPR.value = k;
    E.graph.width(E.graph.width());
  };
  setTimeout(() => medir(fps => {
    document.body.dataset.gxFps = Math.round(fps);
    if (fps >= 24) return;
    if (E.bloom) { E.graph.postProcessingComposer().removePass(E.bloom); E.bloom.dispose(); E.bloom = null; }
    resolucao(0.6); modoHud();
    medir(f2 => {
      document.body.dataset.gxFps = Math.round(f2);
      if (f2 >= 15) return;
      resolucao(0.45);
      medir(f3 => { document.body.dataset.gxFps = Math.round(f3); if (f3 < 6) { destruir(); montar2D('máquina lenta'); } });
    });
  }), 1500);
}

function destruir() {
  const g = E.graph; if (!g) return;
  E.graph = null;
  if (E.ro) E.ro.disconnect();
  try {
    g.pauseAnimation();
    for (const o of [E.anel, E.estrelas, E.cNos, E.cFio && E.cFio.obj, E.cPonte && E.cPonte.obj, E.cPart]) if (o) { o.geometry.dispose(); o.material.dispose(); }
    if (E.bloom) E.bloom.dispose();
    const r = g.renderer(); g._destructor(); r.dispose(); r.forceContextLoss();
  } catch (e) { /* já destruído */ }
  E.bloom = null;
  $('gx-cena').innerHTML = '';
}

/* ── 2D estático ────────────────────────────────────────────────────────────────────────── */
function pintar2D() {
  const cv = $('gx-2d'); if (!cv) return;
  const r = desenhar2D(cv, E.dados, E.pos2d, {escala: celular ? 1.1 : 1.6, estrelas: 520, filtro: visivelNo});
  if (!r) return;
  E.P2d = r.P;
  if (E.hover && visivelNo(E.hover)) {
    const p = r.P(E.hover.id); const g = cv.getContext('2d');
    if (p) { g.strokeStyle = 'rgba(217,246,255,.95)'; g.lineWidth = 1.4; g.beginPath(); g.arc(p[0], p[1], 11, 0, Math.PI * 2); g.stroke(); }
  }
}
function hover2D() {
  if (!E.P2d) return;
  let melhor = null, dm = 14 * 14;
  for (const n of E.nos) {
    if (!visivelNo(n)) continue;
    const p = E.P2d(n.id); if (!p) continue;
    const d = (p[0] - E.mx) ** 2 + (p[1] - E.my) ** 2;
    if (d < dm) { dm = d; melhor = n; }
  }
  if (melhor !== E.hover) { E.hover = melhor; pintar2D(); }
  $('gx-2d').style.cursor = melhor ? 'pointer' : '';
  mostrarTip(melhor ? tipNo(melhor) : null);
}
function montar2D(motivo) {
  E.modo = '2d'; E.motivo2d = motivo;
  $('gx-cena').innerHTML = '<canvas id="gx-2d" class="gx-2d" aria-label="Galáxia dos casos (estática)"></canvas>';
  E.pos2d = layoutEspiral(E.dados);
  pintar2D();
  document.body.classList.add('gx-estatico');
  new ResizeObserver(() => pintar2D()).observe($('gx-cena'));
  modoHud();
}

function modoHud() {
  const m = $('gx-modo'); if (!m) return;
  m.textContent = E.modo === '2d' ? `modo estático · ${E.motivo2d}` : E.bloom ? 'holo 3D · brilho neon · arraste para girar'
    : E.resReduzida ? 'holo 3D · modo leve · arraste para girar' : 'holo 3D · arraste para girar';
}

function webglOk() {
  try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')); } catch (e) { return false; }
}

/* ── boot ───────────────────────────────────────────────────────────────────────────────── */
async function boot() {
  const d = await J('/api/galaxia');
  const carga = $('gx-carga');
  if (!d || d.ok === false) {
    carga.innerHTML = `<div class="gx-warn">${esc(erroHumano(d && d.erro))}${/autentic/.test(String(d && d.erro)) ? ' <a href="/login_jfn">Entrar</a>' : ''}</div>`;
    return;
  }
  E.dados = d; E.nos = d.nos || [];
  for (const n of E.nos) E.porId.set(n.id, n);
  for (const a of d.arestas || []) {
    for (const [x, y] of [[a.source, a.target], [a.target, a.source]]) { if (!E.viz.has(x)) E.viz.set(x, []); E.viz.get(x).push(y); }
    if (a.tipo === 'caso_caso') { E.pontes.add(a.source); E.pontes.add(a.target); }
  }
  montarHud(); ligarControles();
  const forca2d = qs.get('modo') === '2d';
  if (redMotion || forca2d || !webglOk()) montar2D(redMotion ? 'movimento reduzido' : forca2d ? 'pedido na URL' : 'sem WebGL');
  else { E.modo = '3d'; montar3D(); modoHud(); }
  carga.classList.add('fora');
  /* sonda de teste (`?sonda=1`): onde está um nó na tela e quantos quadros já saíram — só para o Playwright. */
  if (qs.has('sonda')) window.__gxSonda = {
    quadros: () => E.quadros || 0, modo: () => E.modo, bloom: () => !!E.bloom, vivo: () => !!E.graph,
    tela(id) {
      if (E.modo === '2d') { const p = E.P2d && E.P2d(id); return p ? {x: p[0], y: p[1]} : null; }
      const n = E.graph && E.nodes3[E.idx3.get(id)]; return n ? telaDe(n) : null;
    },
    pararRotacao() { if (E.graph) E.graph.controls().autoRotate = false; },
  };
  document.body.dataset.gxModo = E.modo;
}

boot();
