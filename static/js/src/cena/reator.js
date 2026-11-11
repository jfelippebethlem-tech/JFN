/* v61 — REATOR VIVO do cockpit.
 *
 * A arte dá o corpo (o loop `reator`, recortado em círculo por máscara no CSS); o código dá a vida:
 * um canvas por cima com três anéis procedurais e os agentes em órbita. NADA aqui se mexe sozinho —
 * cada grandeza visual responde a um número REAL de `aovivo/estado.js`:
 *
 *   velocidade dos anéis   ∝ motores rodando agora
 *   brilho do núcleo       ∝ eventos por minuto (média móvel de 5 min)
 *   clarão + onda          = chegou um evento de tipo `achado`
 *   nós em órbita          = um por motor rodando; gira mais rápido quem emite mais eventos
 *
 * INDISPONÍVEL ≠ 0: sem resposta da API os anéis ficam PARADOS e tracejados, e a legenda diz
 * "ao vivo: INDISPONÍVEL". Com resposta e zero motores rodando, eles derivam devagar (vivo, ocioso).
 * Os nós são <button> de verdade (toque/teclado → cartão do motor); o canvas é só luz.
 */
import {_redMotion, _sobrio} from '../capacidade/estado.js';
import {quadroLigar} from '../ritmo.js';
import {aoVivo, aoVivoOuvir, eventosPorMinuto, motoresRodando} from '../aovivo/estado.js';
import {abrirMotor} from '../ui/aovivo.js';
import {esc} from '../nucleo/dom.js';
import {semEfeito} from '../aovivo/formato.js';

const A = '/static/assets/v61/';
const TAU = Math.PI * 2;
/* anéis: raio (fração do meio-lado), sentido, arcos [início, comprimento] em voltas, espessura */
const ANEIS = [
  {r: 0.74, s: 1, w: 2, arcos: [[0.00, 0.22], [0.30, 0.10], [0.50, 0.27], [0.84, 0.08]]},
  {r: 0.84, s: -1, w: 1.25, arcos: [[0.05, 0.40], [0.55, 0.05], [0.66, 0.24]]},
  {r: 0.94, s: 1, w: 1, arcos: [[0.10, 0.12], [0.36, 0.34], [0.78, 0.16]]},
];

let _sair = null;

export function reatorMontar(host) {
  if (!host) return;
  if (_sair) { _sair(); _sair = null; }
  const cel = matchMedia('(max-width:760px)').matches;
  const eco = !!(navigator.connection && navigator.connection.saveData);
  host.innerHTML = `<div class="v61-reator" id="v61-reator">
      <div class="rt-corpo" style="background-image:url(${A}reator-sm.webp)"></div>
      <canvas class="rt-cv" aria-hidden="true"></canvas>
      <div class="rt-nos" id="rt-nos"></div>
    </div>
    <div class="rt-leg" id="rt-leg" aria-live="polite">ao vivo: lendo…</div>`;
  const raiz = host.querySelector('.v61-reator'), corpo = raiz.querySelector('.rt-corpo');
  const cv = raiz.querySelector('canvas'), nos = raiz.querySelector('.rt-nos'), leg = host.querySelector('.rt-leg');
  const ctx = cv.getContext('2d');

  /* corpo em vídeo: só com permissão para movimento e dados (senão fica o pôster) */
  if (!_redMotion && !_sobrio && !eco) {
    const v = document.createElement('video');
    v.muted = true; v.loop = true; v.playsInline = true; v.preload = 'metadata'; v.setAttribute('aria-hidden', 'true');
    v.innerHTML = `<source src="${A}reator-m.webm" type="video/webm"><source src="${A}reator-m.mp4" type="video/mp4">`;
    v.addEventListener('playing', () => v.classList.add('on'));
    corpo.appendChild(v); v.play().catch(() => {});
    document.addEventListener('visibilitychange', () => { if (!v.isConnected) return; document.hidden ? v.pause() : v.play().catch(() => {}); });
  }

  let L = 0, dpr = 1, sujo = true;      // `sujo`: há algo novo para desenhar (estado, tamanho)
  const medir = () => { const b = raiz.getBoundingClientRect(); dpr = Math.min(devicePixelRatio || 1, 2);
    L = b.width; cv.width = Math.round(L * dpr); cv.height = Math.round(L * dpr); sujo = true; };
  medir();
  const ro = new ResizeObserver(medir); ro.observe(raiz);

  const ang = [0, 0, 0];           // rotação acumulada de cada anel
  const orb = new Map();           // id do motor → {el, a}
  let onda = -1;                   // 0..1 enquanto a onda do achado corre; -1 = sem onda

  const sincNos = () => {
    const vivos = motoresRodando().slice(0, cel ? 5 : 8);
    for (const [id, o] of orb) if (!vivos.some(m => m.id === id)) { o.el.remove(); orb.delete(id); }
    vivos.forEach((m, i) => {
      if (orb.has(m.id)) return;
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'rt-no'; b.dataset.motor = m.id;
      b.title = m.nome + ' — rodando'; b.innerHTML = `<i aria-hidden="true"></i><span>${esc(m.nome)}</span>`;
      b.addEventListener('click', () => abrirMotor(m.id));
      nos.appendChild(b);
      orb.set(m.id, {el: b, a: (i / Math.max(1, vivos.length)) * TAU});
    });
    const n = motoresRodando().length, f = aoVivo.motores.filter(m => m.estado === 'falhou').length,
      se = aoVivo.motores.filter(semEfeito).length;
    if (aoVivo.disponivel === false) leg.innerHTML = 'ao vivo: <b>INDISPONÍVEL</b>';
    else if (aoVivo.disponivel === null) leg.textContent = 'ao vivo: lendo…';
    else leg.innerHTML = `<b class="num">${n}</b> ${n === 1 ? 'motor rodando' : 'motores rodando'}`
      + (f ? ` · <b class="num rt-falha">${f}</b> ${f === 1 ? 'falhou' : 'falharam'}` : '')
      + (se ? ` · <b class="num rt-sefeito">${se}</b> sem efeito` : '')
      + ` · <b class="num">${eventosPorMinuto().toFixed(1).replace('.', ',')}</b> eventos/min`
      + (aoVivo.conectado ? '' : ' · <span class="rt-pausa">reconectando</span>');
    raiz.classList.toggle('rt-indisp', aoVivo.disponivel === false);
    sujo = true;
  };
  const parar = aoVivoOuvir((tipo, ev) => {
    if (tipo === 'evento' && ev && ev.tipo === 'achado' && !_redMotion) onda = 0;
    sincNos();
  });
  sincNos();

  const pinta = (t, dt) => {
    if (!raiz.isConnected) { sair(); return false; }
    const parado = _redMotion || _sobrio;
    /* modo sóbrio / reduced-motion: NÃO redesenha a cada quadro — só quando o estado muda. O laço fica
       inscrito (um retorno vazio não custa) para retomar sozinho se a máquina voltar a entregar quadro. */
    const vid = corpo.querySelector('video');
    if (vid) { if (parado && !vid.paused) vid.pause(); else if (!parado && vid.paused && !document.hidden) vid.play().catch(() => {}); }
    if (parado && !sujo) return true;
    sujo = false;
    const sabe = aoVivo.disponivel === true, n = sabe ? motoresRodando().length : 0;
    const vel = sabe ? 0.05 + 0.09 * Math.min(n, 8) : 0;           // rad/s: ∝ motores rodando
    const epm = sabe ? eventosPorMinuto() : 0;
    const c = (L * dpr) / 2;
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, cv.width, cv.height);
    /* núcleo: brilho ∝ eventos/min */
    const brilho = Math.min(0.55, epm * 0.06);
    if (brilho > 0.01) {
      const g = ctx.createRadialGradient(c, c, 0, c, c, c * 0.42);
      g.addColorStop(0, `rgba(255,255,255,${brilho})`); g.addColorStop(0.5, `rgba(34,181,245,${brilho * 0.6})`);
      g.addColorStop(1, 'rgba(34,181,245,0)');
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(c, c, c * 0.42, 0, TAU); ctx.fill();
    }
    /* anéis */
    ctx.lineCap = 'round';
    ANEIS.forEach((an, i) => {
      if (!parado) ang[i] += an.s * vel * (1 + i * 0.35) * dt;
      ctx.lineWidth = an.w * dpr;
      ctx.strokeStyle = sabe ? (i === 1 ? 'rgba(34,181,245,.85)' : 'rgba(30,123,240,.7)') : 'rgba(106,126,155,.55)';
      ctx.setLineDash(sabe ? [] : [3 * dpr, 5 * dpr]);
      for (const [a0, len] of an.arcos) {
        ctx.beginPath(); ctx.arc(c, c, c * an.r, ang[i] + a0 * TAU, ang[i] + (a0 + len) * TAU); ctx.stroke();
      }
    });
    ctx.setLineDash([]);
    /* onda do achado: 1,2 s */
    if (onda >= 0) {
      onda += dt / 1.2;
      if (onda >= 1) onda = -1;
      else {
        const k = 1 - Math.pow(1 - onda, 3);
        ctx.lineWidth = (3 - 2 * onda) * dpr; ctx.strokeStyle = `rgba(34,181,245,${0.9 * (1 - onda)})`;
        ctx.beginPath(); ctx.arc(c, c, c * (0.2 + 0.78 * k), 0, TAU); ctx.stroke();
        if (onda < 0.25) { ctx.fillStyle = `rgba(255,255,255,${0.7 * (1 - onda / 0.25)})`;
                           ctx.beginPath(); ctx.arc(c, c, c * 0.36, 0, TAU); ctx.fill(); }
      }
    }
    /* agentes em órbita: mais rápido quem emite mais */
    const R = L / 2;
    for (const [id, o] of orb) {
      if (!parado) o.a += (0.16 + Math.min(0.5, eventosPorMinuto(id) * 0.12)) * dt;
      const x = R + Math.cos(o.a) * R * 0.94, y = R + Math.sin(o.a) * R * 0.94;
      o.el.style.transform = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px)`;
      o.el.classList.toggle('esq', Math.cos(o.a) < 0);
    }
    return true;
  };
  const desliga = quadroLigar(pinta);
  function sair() { desliga(); parar(); ro.disconnect(); if (_sair === sair) _sair = null; }
  _sair = sair;
}
