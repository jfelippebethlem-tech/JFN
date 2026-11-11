/* v61 — ABERTURA. Substitui o portal/kyber quando `html.v61` está valendo.
 *
 * O filme (reator acende → câmera recua → sala de comando) é CENÁRIO; o que se lê por cima é
 * código: a marca, e um checklist de boot com o estado REAL dos motores (`/api/ao-vivo/estado`).
 * Se a API não responde, a lista diz `motores: INDISPONÍVEL` — nunca linha fixa fingindo status.
 *
 * Três formas, da mais cara à mais barata:
 *   completa  só na 1ª abertura do dia (`localStorage.jfn_abertura_dia`): ~10 s, com Pular;
 *   curta     nas demais: pôster do reator + clarão + fade, 1,2 s;
 *   mínima    `prefers-reduced-motion` ou Save-Data: pôster + fade de 300 ms, sem baixar vídeo.
 *
 * O relógio do HUD é o do VÍDEO enquanto ele anda; se o vídeo não tocar (autoplay barrado, codec,
 * máquina sem quadro) vale o relógio de parede — a abertura nunca fica presa esperando quadro
 * (lição v28.3: rAF congela em aba de fundo; aqui o fim é por `setTimeout`).
 */
import {esc} from '../nucleo/dom.js';
import {_redMotion} from '../capacidade/estado.js';
import {lerEstado, rotuloEstado} from '../aovivo/formato.js';

const A = '/static/assets/v61/';
const HOJE = () => { const d = new Date(), p = n => String(n).padStart(2, '0');
                     return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; };

export function aberturaStart(portal) {
  if (portal) portal.remove();                        // o portal antigo não entra em cena
  let off = false, dia = '';
  try { off = localStorage.getItem('jfn_portal_off') === '1'; dia = localStorage.getItem('jfn_abertura_dia') || ''; } catch (_) {}
  if (off) return;
  const eco = !!(navigator.connection && navigator.connection.saveData);
  const cel = matchMedia('(max-width:760px)').matches;
  const modo = (_redMotion || eco) ? 'minima' : (dia === HOJE() ? 'curta' : 'completa');

  const el = document.createElement('div');
  el.id = 'v61-abertura'; el.className = 'ab-' + modo;
  el.setAttribute('role', 'dialog'); el.setAttribute('aria-label', 'Abertura do painel');
  const poster = A + 'reator' + (cel ? '-sm' : '') + '.webp';
  el.innerHTML = `<div class="ab-poster" style="background-image:url(${poster})"></div>`
    + (modo === 'completa'
      ? `<video class="ab-vid" muted playsinline preload="auto" aria-hidden="true">`
        + `<source src="${A}abertura${cel ? '-m' : ''}.webm" type="video/webm">`
        + `<source src="${A}abertura${cel ? '-m' : ''}.mp4" type="video/mp4"></video>` : '')
    + `<div class="ab-clarao" aria-hidden="true"></div>`
    + (modo === 'minima' ? '' :
      `<div class="ab-marca"><div class="ab-jfn v61-disp" aria-label="JFN"><span>J</span><span>F</span><span>N</span></div>`
      + `<div class="ab-sub v61-disp">INTELIGÊNCIA FISCAL · RJ</div></div>`)
    + (modo === 'completa'
      ? `<ul class="ab-boot" aria-live="polite" aria-label="Motores do sistema"></ul>`
        + `<button type="button" class="ab-pular">Pular</button>` : '');
  document.body.appendChild(el);

  let fim = false;
  const fechar = (ms) => {
    if (fim) return; fim = true;
    el.style.setProperty('--ab-sai', ms + 'ms'); el.classList.add('ab-off');
    removeEventListener('keydown', tecla);
    setTimeout(() => el.remove(), ms + 60);
  };
  const tecla = e => { if (e.key === 'Escape' || e.key === 'Enter' || e.key === ' ') fechar(300); };

  if (modo === 'minima') { setTimeout(() => fechar(300), 350); return; }
  if (modo === 'curta') {
    requestAnimationFrame(() => el.classList.add('ab-on'));
    setTimeout(() => fechar(400), 800);                 // 0,8 s de pôster + clarão, 0,4 s de fade = 1,2 s
    return;
  }

  /* ── completa ── */
  try { localStorage.setItem('jfn_abertura_dia', HOJE()); } catch (_) {}
  const v = el.querySelector('video'), boot = el.querySelector('.ab-boot');
  const DUR = 10.0, t0 = performance.now();
  let tocando = false;
  v.addEventListener('playing', () => { tocando = true; el.classList.add('ab-tocando'); });
  v.addEventListener('ended', () => fechar(600));
  v.play().catch(() => {});
  const tempo = () => (tocando && v.currentTime > 0) ? v.currentTime : (performance.now() - t0) / 1000;

  /* checklist: os motores REAIS, um por linha, soltos entre 1,0 s e 7,0 s */
  let linhas = null;                                  // null = ainda lendo; [] = indisponível
  lerEstado(3500).then(j => {
    linhas = j ? j.motores.map(m => ({cls: 'e-' + (m.estado || 'indisponivel'), txt: `${m.nome} — ${rotuloEstado(m)}`})) : [];
  });
  let postas = 0, avisou = false;
  const passo = () => {
    if (fim) return;
    const t = tempo();
    if (t >= 0.05) el.classList.add('ab-on');
    if (t >= 2.5) el.classList.add('ab-marca-off');
    if (t >= 1.0 && t < 7.4 && linhas) {
      if (!linhas.length) {
        if (!avisou) { avisou = true; boot.innerHTML = '<li class="e-indisponivel on"><i></i>motores: INDISPONÍVEL</li>'; }
      } else {
        const alvo = Math.min(linhas.length, Math.ceil((t - 1.0) / (6.0 / linhas.length)));
        for (; postas < alvo; postas++) {
          const li = document.createElement('li'); li.className = linhas[postas].cls;
          li.innerHTML = '<i></i>' + esc(linhas[postas].txt);
          boot.appendChild(li); requestAnimationFrame(() => li.classList.add('on'));
          while (boot.children.length > (cel ? 7 : 12)) boot.firstChild.remove();
        }
      }
    }
    if (t >= 7.5) el.classList.add('ab-hud-off');
    if (t >= DUR - 0.6) { fechar(600); return; }
    setTimeout(passo, 80);
  };
  passo();
  el.querySelector('.ab-pular').addEventListener('click', () => fechar(300));
  addEventListener('keydown', tecla);
  setTimeout(() => fechar(600), (DUR + 2) * 1000);    // rede de segurança: nunca passa de 12 s
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && (performance.now() - t0) / 1000 >= DUR) fechar(0);
  });
}
