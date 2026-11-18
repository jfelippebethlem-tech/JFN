/* v64 — ABERTURA EM CÓDIGO (substitui o filme v61 do reator na sala cinza, que travava no celular).
 *
 * Tudo é SVG + WAAPI, nenhum byte de mídia: fitas de luz azuis (a linguagem do fundo v63) entram pelas
 * bordas e se enrolam num anel; o anel vira o reator JFN em traço fino (anéis com segmentos girando em
 * velocidades diferentes); ignição — um pulso sai do núcleo, a marca "JFN · Controle Externo" se escreve
 * (stroke-dashoffset) e uma linha mono mostra o estado REAL dos motores (`/api/ao-vivo/estado`; sem
 * resposta → "motores: INDISPONÍVEL", nunca status fingido). Saída: o reator se expande até virar o
 * próprio fundo do painel enquanto o véu claro some — o herói do v63 já está pintado por baixo.
 *
 * Três formas:
 *   completa  1ª abertura do dia (`localStorage.jfn_abertura_dia`): 3,2 s;
 *   curta     nas demais: reator já aceso, pulso e expansão — 0,9 s;
 *   mínima    `prefers-reduced-motion` ou Save-Data: fade de 250 ms, nada se mexe.
 * Qualquer toque/tecla pula. O FIM é sempre por `setTimeout` (rAF congela em aba de fundo — lição v28.3).
 *
 * Custo: anima só transform/opacity (camadas HTML → compositor) e stroke-dashoffset (traços SVG curtos).
 * Sem filter/blur animado, sem shadowBlur; o brilho é gradiente radial estático com opacidade.
 * O `#v64-abertura` já nasce no HTML (véu claro, sem flash do esqueleto do painel enquanto o bundle
 * desce); se o JS nunca rodar, o CSS o dissolve sozinho aos 6 s.
 */
import {esc} from '../nucleo/dom.js';
import {_redMotion} from '../capacidade/estado.js';
import {lerEstado} from '../aovivo/formato.js';

const NS = 'http://www.w3.org/2000/svg';
const MOLA = 'cubic-bezier(.2,.8,.2,1)', SAI = 'cubic-bezier(.55,0,.2,1)';
const COR = ['#1D5BFF', '#6FA8FF', '#38D3FF'];
const HOJE = () => { const d = new Date(), p = n => String(n).padStart(2, '0');
                     return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; };
const DUR = {completa: 3200, curta: 900, minima: 250};

/* o reator: viewBox -100..100. Cada camada é um <div> próprio para girar no compositor. */
const ANEIS = [
  /* r, traço, largura, cor, opacidade, período do giro (ms; negativo = anti-horário) */
  {r: 92, d: '', w: .7, c: COR[0], o: .45, giro: 0},
  {r: 84, d: '17 5', w: 1.3, c: COR[0], o: .9, giro: 9000},
  {r: 74, d: '1.6 4.2', w: 3.2, c: COR[2], o: .75, giro: -6000},
  {r: 63, d: '64 34', w: 2.4, c: COR[1], o: .9, giro: 3800},
  {r: 50, d: '', w: .8, c: COR[0], o: .55, giro: 0},
  {r: 41, d: '6 9', w: 1.1, c: COR[0], o: .7, giro: -2600},
];

function reatorSvg(a) {
  const tr = a.d ? ` stroke-dasharray="${a.d}"` : '';
  return `<svg viewBox="-100 -100 200 200" aria-hidden="true"><circle r="${a.r}" fill="none" stroke="${a.c}"`
    + ` stroke-width="${a.w}" stroke-opacity="${a.o}"${tr} stroke-linecap="round" pathLength="${a.d ? 360 : 1}"/></svg>`;
}

/* uma fita: nasce fora da tela num ângulo θ, curva para dentro e entra tangente no anel, que ela
   continua contornando — várias juntas "enrolam" o anel. Coordenadas em px, origem no centro. */
function fitaPath(th, D, R, giro, arco) {
  const P0 = [D * Math.cos(th), D * Math.sin(th)];
  const fi = th + giro, E = [R * Math.cos(fi), R * Math.sin(fi)];
  const tg = [-Math.sin(fi), Math.cos(fi)];
  const C1 = [P0[0] * .62 + D * .18 * Math.cos(th + 1.57), P0[1] * .62 + D * .18 * Math.sin(th + 1.57)];
  const C2 = [E[0] - tg[0] * R * 1.25, E[1] - tg[1] * R * 1.25];
  const f2 = fi + arco, F = [R * Math.cos(f2), R * Math.sin(f2)];
  const n = v => v.toFixed(1);
  return `M${n(P0[0])} ${n(P0[1])}C${n(C1[0])} ${n(C1[1])} ${n(C2[0])} ${n(C2[1])} ${n(E[0])} ${n(E[1])}`
    + `A${n(R)} ${n(R)} 0 0 1 ${n(F[0])} ${n(F[1])}`;
}

/* duas camadas (feixes alternados) — cada uma gira/encolhe para o lugar no COMPOSITOR: o boot do painel
   por baixo pode segurar o main thread que as fitas continuam fluidas. */
function fitasHtml(w, h, R, cel) {
  const D = Math.hypot(w, h) / 2 + 40, feixes = cel ? 6 : 8, fios = cel ? 4 : 5;
  const camadas = ['', ''];
  for (let b = 0; b < feixes; b++) {
    const th = b * 2 * Math.PI / feixes + .42;
    for (let i = 0; i < fios; i++) {
      const u = i / (fios - 1) - .5;                                  // -0,5 … 0,5 através da fita
      const d = fitaPath(th + u * .16, D, R + u * 14, 1.3 + u * .12, 1.5 + (b % 3) * .1);
      const meio = Math.abs(u) < .2;
      if (meio) camadas[b % 2] += `<path class="ab-halo" d="${d}" stroke="${COR[2]}"/>`;
      camadas[b % 2] += `<path d="${d}" stroke="${COR[(b + i) % 3]}"`
        + ` stroke-width="${meio ? 1.6 : .8}" stroke-opacity="${meio ? .95 : .25 + .45 * (1 - Math.abs(u) * 2)}"/>`;
    }
  }
  return '<div class="ab-fitas">' + camadas.map((c, k) =>
    `<svg class="ab-camada" data-k="${k}" viewBox="${-w / 2} ${-h / 2} ${w} ${h}" aria-hidden="true">${c}</svg>`).join('') + '</div>';
}

function marcaSvg() {
  return `<svg class="ab-marca" viewBox="0 0 520 70" role="img" aria-label="JFN · Controle Externo">`
    + `<text class="ab-jfn" x="0" y="52">JFN</text><circle class="ab-ponto" cx="139" cy="36" r="4"/>`
    + `<text class="ab-ce" x="160" y="52">Controle Externo</text></svg>`;
}

/* v69 — FILME: a abertura renderizada no Blender (`tools/v69_abertura_blender.py`, it-campo) toca por baixo da
   marca e dos motores, que continuam em CÓDIGO (nada de texto queimado). Fundo branco-gelo → branco, o mesmo do
   painel: o vídeo cobre a tela (object-fit) sem máscara suja. Só baixa na 1ª abertura do dia; a curta (1,2 s)
   só toca se já foi pré-carregada no fim da 1ª. Se não começar a tocar em 600 ms (rede, codec, autoplay
   negado), cai na abertura em código do v64 — que segue sendo a forma de movimento reduzido/Save-Data.
   `localStorage.jfn_abertura_video`: '0' força o código; '1' força o filme e espera até 5 s por ele (A/B, QA). */
const FILME = '/static/assets/v69/';
const FILME_ESPERA = {completa: 600, curta: 300};
/* raio do anel externo no vídeo, em fração da LARGURA do vídeo, no fim do push-in (t = 2,5 s) — sai da câmera
   do script: meia-largura = d·18/lente, d = 8,53; anel 1,115. Quadrado: lente 52 → 0,189; vertical: 84,5 → 0,307 */
const FILME_RAIO = {q: .189, v: .307};

function filmeEl(nome, w, h) {
  const ret = h > w * 1.05, b = FILME + nome + (ret ? '_m' : '');
  const v = document.createElement('video');
  v.className = 'ab-filme'; v.muted = true; v.playsInline = true; v.preload = 'auto';
  v.setAttribute('muted', ''); v.setAttribute('playsinline', ''); v.setAttribute('aria-hidden', 'true');
  v.poster = b + '.webp';
  /* nível AV1 medido no arquivo: 1920×1920@60 = 5.0 (12); 1080×1920@60 = 4.1 (09) */
  v.innerHTML = `<source src="${b}.av1.mp4" type='video/mp4; codecs="av01.0.${ret ? '09' : '12'}M.08"'>`
    + `<source src="${b}.webm" type='video/webm; codecs="vp9"'><source src="${b}.mp4" type="video/mp4">`;
  /* caixa: vertical 9:16 em "cover"; quadrado do lado da maior dimensão, com teto de 1,8× a altura (tela muito
     larga): aí as laterais dissolvem no branco por máscara em vez de cortar o reator */
  let bw, bh;
  if (ret) { bw = Math.max(w, h * 9 / 16); bh = bw * 16 / 9; } else { bw = bh = Math.min(Math.max(w, h), h * 1.8); }
  v.style.cssText = `width:${bw.toFixed(1)}px;height:${bh.toFixed(1)}px;left:${((w - bw) / 2).toFixed(1)}px;top:${((h - bh) / 2).toFixed(1)}px`;
  if (bw < w - 1) v.classList.add('ab-filme-borda');
  return {v, raio: bw * FILME_RAIO[ret ? 'v' : 'q']};
}

function tentaFilme(v, ms) {
  return new Promise(res => {
    let feito = false;
    const fim = ok => { if (feito) return; feito = true; clearTimeout(t); res(ok); };
    const t = setTimeout(() => fim(false), ms);
    v.addEventListener('playing', () => fim(true), {once: true});
    v.addEventListener('error', () => fim(false), {once: true});
    const ult = v.querySelector('source:last-of-type');                // todas as fontes falharam (404, codec)
    if (ult) ult.addEventListener('error', () => fim(false), {once: true});
    const p = v.play(); if (p && p.catch) p.catch(() => fim(false));
  });
}

/* no fim da 1ª abertura: baixa a curta no mesmo formato que tocou (cache HTTP) e marca que ela existe */
function preCurta(v) {
  const src = v.currentSrc || '';
  if (!src) return;
  const url = src.replace(/\/abertura(_m)?\./, (_, m) => `/abertura_c${m || ''}.`);
  setTimeout(() => fetch(url, {priority: 'low'}).then(r => r.ok ? r.blob() : null)
    .then(b => { if (b && b.size) try { localStorage.setItem('jfn_abertura_c_ok', '1'); } catch (_) {} }).catch(() => {}), 1500);
}

export function aberturaStart(portal) {
  if (portal) portal.remove();
  let el = document.getElementById('v64-abertura');
  let off = false, dia = '', filmeOk = true, curtaOk = false, forca = false;
  try {
    off = localStorage.getItem('jfn_portal_off') === '1'; dia = localStorage.getItem('jfn_abertura_dia') || '';
    const fv = localStorage.getItem('jfn_abertura_video'); filmeOk = fv !== '0'; forca = fv === '1';
    curtaOk = localStorage.getItem('jfn_abertura_c_ok') === '1';
  } catch (_) {}
  if (off) { if (el) el.remove(); return; }
  const eco = !!(navigator.connection && navigator.connection.saveData);
  const modo = (_redMotion || eco || typeof Element.prototype.animate !== 'function') ? 'minima'
    : (dia === HOJE() ? 'curta' : 'completa');
  if (modo === 'completa') try { localStorage.setItem('jfn_abertura_dia', HOJE()); } catch (_) {}

  if (!el) { el = document.createElement('div'); el.id = 'v64-abertura'; document.body.prepend(el); }
  el.className = 'ab-' + modo;
  el.setAttribute('role', 'dialog'); el.setAttribute('aria-label', 'Abertura do painel'); el.removeAttribute('aria-hidden');
  const w = innerWidth, h = innerHeight, cel = w <= 760;
  const S = Math.round(Math.max(200, Math.min(cel ? 300 : 360, Math.min(w, h) * (cel ? .74 : .5))));
  const R = S / 200 * 92;                                              // raio do anel externo em px
  el.style.setProperty('--ab-s', S + 'px');
  const comFilme = filmeOk && (modo === 'completa' || (modo === 'curta' && curtaOk));
  const codigoHtml = () => (modo === 'completa' ? fitasHtml(w, h, R, cel) : '')
    + `<div class="ab-reator">${ANEIS.map((a, i) => `<div class="ab-anel" data-i="${i}">${reatorSvg(a)}</div>`).join('')}`
    + '<div class="ab-varre"></div><div class="ab-nucleo"></div><div class="ab-pulso"></div></div>';
  el.innerHTML = '<div class="ab-veu"></div>'
    + (comFilme ? '' : codigoHtml())
    + (modo === 'minima' ? '' : `<div class="ab-texto">${marcaSvg()}`
      + (modo === 'completa' ? '<p class="ab-motores" aria-live="polite"><span class="ab-m-t">motores · lendo…</span></p>' : '')
      + '</div>')
    + (modo === 'completa' ? '<button type="button" class="ab-pular">Pular</button>' : '');

  const H = document.documentElement;
  const revela = () => H.classList.remove('v64-ab-cobre');            // o painel volta a pintar
  if (modo !== 'minima') H.classList.add('v64-ab-cobre');
  const $ = s => el.querySelector(s), $$ = s => [...el.querySelectorAll(s)];
  const anims = [];
  const A = (alvo, kf, op) => { if (!alvo) return null; const a = alvo.animate(kf, {fill: 'both', ...op}); anims.push(a); return a; };
  const escalaFim = Math.hypot(w, h) / (2 * R) * 1.15;                 // o anel externo passa das bordas

  let fim = false, tFim = 0;
  const remover = () => { revela(); el.remove(); removeEventListener('keydown', tecla, true); };
  /* saída: o reator se expande até virar o fundo (no filme ele já saiu do quadro), o véu dissolve, o texto some */
  const sair = (ms, atraso = 0) => {
    if (fim) return; fim = true;
    clearTimeout(tFim);
    el.classList.add('ab-saindo');
    const op = {duration: ms, delay: atraso, easing: SAI};
    revela();
    A($('.ab-reator'), [{transform: 'scale(1)', opacity: 1}, {transform: `scale(${escalaFim.toFixed(2)})`, opacity: 0}], op);
    A($('.ab-filme'), [{opacity: 1}, {opacity: 0}], op);
    A($('.ab-veu'), [{opacity: 1}, {opacity: 0}], {...op, duration: ms * .85, delay: atraso + ms * .15});
    const fitas = $('.ab-fitas');
    if (fitas) A(fitas, [{opacity: 0, transform: 'scale(1.25)'}], op);   // 1 quadro-chave: parte do valor atual
    A($('.ab-texto'), [{opacity: 0, transform: 'translateY(-10px)'}], {...op, duration: ms * .6});
    setTimeout(remover, atraso + ms + 40);
  };
  const pular = () => sair(fim ? 0 : 380);
  const tecla = e => { if (['Escape', 'Enter', ' '].includes(e.key)) { e.preventDefault(); pular(); } };
  addEventListener('keydown', tecla, true);
  el.addEventListener('pointerdown', pular, {once: true});
  const pularBtn = $('.ab-pular');
  if (pularBtn) pularBtn.addEventListener('click', e => { e.stopPropagation(); pular(); });

  if (modo === 'minima') {                                            // nada se mexe: só o fade
    el.classList.add('ab-quieto');
    A(el, [{opacity: 1}, {opacity: 0}], {duration: DUR.minima, easing: 'linear'});
    fim = true; setTimeout(remover, DUR.minima + 30);
    return;
  }

  /* a marca se escreve: contorno corre, depois o preenchimento acende (igual no filme e no código) */
  const marca = atraso => {
    A($('.ab-texto'), [{opacity: 0}, {opacity: 1}], {duration: 200, delay: atraso, easing: 'linear'});
    $$('.ab-marca text').forEach((t, i) => {
      A(t, [{strokeDashoffset: 420, fillOpacity: 0}, {strokeDashoffset: 0, fillOpacity: 0, offset: .7}, {strokeDashoffset: 0, fillOpacity: 1}],
        {duration: 820, delay: atraso + 20 + i * 160, easing: 'ease-out'});
    });
    A($('.ab-ponto'), [{opacity: 0, transform: 'scale(0)'}, {opacity: 1, transform: 'scale(1)'}], {duration: 300, delay: atraso + 300, easing: MOLA});
    motores($('.ab-m-t'), () => fim);
  };

  const codigo = () => {
    /* giro contínuo dos anéis segmentados (compositor) */
    $$('.ab-anel').forEach((n, i) => {
      const g = ANEIS[i].giro;
      if (g) A(n, [{transform: 'rotate(0deg)'}, {transform: `rotate(${g > 0 ? 360 : -360}deg)`}],
        {duration: Math.abs(g), iterations: Infinity, easing: 'linear', fill: 'none'});
    });
    const reator = $('.ab-reator'), texto = $('.ab-texto'), fitas = $('.ab-fitas');

    if (modo === 'curta') {
      A(reator, [{transform: 'scale(.92)', opacity: .0}, {transform: 'scale(1)', opacity: 1}], {duration: 260, easing: MOLA});
      pulso(A, $, 60, 520);
      A(texto, [{opacity: 0, transform: 'translateY(6px)'}, {opacity: 1, transform: 'none'}], {duration: 240, easing: MOLA});
      setTimeout(() => revela(), 120);
      tFim = setTimeout(() => sair(DUR.curta - 340), 320);
      setTimeout(remover, DUR.curta + 400);                           // rede de segurança
      return;
    }

    /* ── completa (3,2 s) ── */
    $$('.ab-camada').forEach((c, k) => A(c, [{opacity: 0, transform: `rotate(${k ? 42 : -34}deg) scale(1.9)`},
      {opacity: 1, transform: 'none'}], {duration: 1150, delay: 30 + k * 110, easing: MOLA}));
    A(fitas, [{opacity: 1}, {opacity: .42}], {duration: 700, delay: 1300, easing: 'linear'});
    $$('.ab-anel').forEach((n, i) => A(n.firstElementChild, [{opacity: 0, transform: 'scale(.72)'}, {opacity: 1, transform: 'scale(1)'}],
      {duration: 620, delay: 560 + i * 70, easing: MOLA}));
    A($('.ab-varre'), [{opacity: 0, transform: 'rotate(0deg)'}, {opacity: 1, transform: 'rotate(200deg)', offset: .4},
      {opacity: .55, transform: 'rotate(560deg)'}], {duration: 2400, delay: 700, easing: 'cubic-bezier(.3,.6,.4,1)'});
    pulso(A, $, 1250, 760);
    marca(1300);
    setTimeout(() => revela(), 2150);
    tFim = setTimeout(() => sair(DUR.completa - 2480), 2480);
    setTimeout(remover, DUR.completa + 600);                          // rede de segurança: nunca fica preso
  };

  document.addEventListener('visibilitychange', () => { if (document.hidden && !fim) { fim = true; remover(); } }, {once: true});
  if (!comFilme) { codigo(); return; }

  /* ── filme ── */
  const {v, raio} = filmeEl(modo === 'completa' ? 'abertura' : 'abertura_c', w, h);
  el.classList.add('ab-com-filme');
  $('.ab-veu').after(v);
  tentaFilme(v, forca ? 5000 : FILME_ESPERA[modo]).then(ok => {
    if (fim) return;
    if (!ok) {                                                        // cai na abertura em código, sem flash
      v.pause(); v.remove(); el.classList.remove('ab-com-filme');
      $('.ab-veu').insertAdjacentHTML('afterend', codigoHtml());
      codigo();
      return;
    }
    el.style.setProperty('--ab-s', Math.round(2 * raio) + 'px');      // texto logo abaixo do anel do vídeo
    const resta = s => Math.max(0, (s - v.currentTime) * 1000);
    if (modo === 'curta') {
      A($('.ab-texto'), [{opacity: 0, transform: 'translateY(6px)'}, {opacity: 1, transform: 'none'}], {duration: 240, easing: MOLA});
      setTimeout(() => revela(), resta(.62));
      tFim = setTimeout(() => sair(360), resta(.80));
      setTimeout(remover, resta(1.2) + 1200);                         // rede de segurança
      return;
    }
    marca(Math.max(0, 1300 - v.currentTime * 1000));
    setTimeout(() => revela(), resta(2.70));
    tFim = setTimeout(() => { sair(380); preCurta(v); }, resta(2.82));
    v.addEventListener('ended', () => sair(300), {once: true});
    setTimeout(remover, resta(3.2) + 1400);                           // rede de segurança: nunca fica preso
  });
}

function pulso(A, $, atraso, dur) {
  A($('.ab-nucleo'), [{opacity: 0, transform: 'scale(.5)'}, {opacity: 1, transform: 'scale(1.08)', offset: .35}, {opacity: .85, transform: 'scale(1)'}],
    {duration: dur, delay: atraso, easing: MOLA});
  A($('.ab-pulso'), [{opacity: .9, transform: 'scale(.25)'}, {opacity: 0, transform: 'scale(2.6)'}], {duration: dur, delay: atraso, easing: 'ease-out'});
}

/* a linha mono: cada motor REAL, um por vez, com ✓ (ok) · ✕ (falhou) · — (sem estado); fecha com a soma */
function motores(alvo, acabou) {
  if (!alvo) return;
  const t0 = performance.now();
  lerEstado(1400).then(j => {
    if (acabou() || !alvo.isConnected) return;
    if (!j) { alvo.innerHTML = '<i class="e-indisponivel">—</i> motores: INDISPONÍVEL'; return; }
    const ms = j.motores || [];
    const marca = m => m.estado === 'falhou' ? ['falhou', '✕'] : ['rodando', 'agendado', 'ocioso'].includes(m.estado) ? ['ok', '✓'] : ['indisponivel', '—'];
    const soma = () => {
      const c = {ok: 0, falhou: 0, indisponivel: 0}; ms.forEach(m => c[marca(m)[0]]++);
      alvo.innerHTML = `<i class="e-ok">✓</i> ${ms.length} motores · ${c.ok} em ordem`
        + (c.falhou ? ` · <b class="e-falhou">${c.falhou} com falha</b>` : '') + (c.indisponivel ? ` · ${c.indisponivel} sem estado` : '');
    };
    const ini = Math.max(0, 1500 - (performance.now() - t0)), passo = Math.max(45, Math.min(110, 820 / Math.max(1, ms.length)));
    ms.forEach((m, i) => setTimeout(() => {
      if (acabou() || !alvo.isConnected) return;
      const [cls, s] = marca(m);
      alvo.innerHTML = `<i class="e-${cls}">${s}</i> ${esc(m.nome)} <span class="ab-m-e">${esc(m.estado || 'INDISPONÍVEL')}</span>`;
    }, ini + i * passo));
    setTimeout(() => { if (!acabou() && alvo.isConnected) soma(); }, ini + ms.length * passo + 40);
  });
}
