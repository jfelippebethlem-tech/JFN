/* JARVIS — a vida contínua do painel (16/11/2026). Par em JS do estrato `99z2-v61-96-jarvis.css`.
 *
 * Pedido do dono: "quero tudo ultratech jarvis nesse painel … que tudo se mexa e esteja vivo".
 * Cinco gestos, e NENHUM inventa dado:
 *   reflexo     de tempos em tempos uma lâmina de luz atravessa UM cartão de vidro visível;
 *   anéis HUD   dois anéis girando em volta do logo e do instrumento principal da tela;
 *   telemetria  no fim do ticker: hora, motores rodando, eventos/min e carga — todos lidos do que o
 *               painel JÁ tem (`aovivo/estado.js`, `ritmo.js`). Sem dado, o campo não aparece:
 *               telemetria vazia não vira "0";
 *   partículas  poucas (12; 6 no celular), só CSS, atrás do vidro, sem evento de ponteiro;
 *   toque       registra ONDE e EM QUE chip foi o último toque — a gramática 7 (`revelacao.js`)
 *               usa o lado para a sub-aba deslizar, e o pulso radial nasce no ponto do clique.
 * Custo: nenhum laço de quadro. Dois `setInterval` (1 s do relógio, 5,2 s do reflexo) que PARAM com a
 * aba oculta; o resto é animação de compositor (`transform`/`opacity`). Com `prefers-reduced-motion`
 * ou modo sóbrio nada se move (o CSS desliga e o JS nem agenda), mas a telemetria — que é DADO —
 * continua escrita.
 * Sem efeito de topo; quem liga é `jarvisBoot()` na sequência de boot (`entrada.js`).
 */
import {$} from '../nucleo/dom.js';
import {_v61, _redMotion, _sobrio} from '../capacidade/estado.js';
import {aoVivo, aoVivoOuvir, motoresRodando} from '../aovivo/estado.js';
import {ritmoEstado} from '../ritmo.js';

const _mobile = () => matchMedia('(max-width:760px)').matches;
const _parado = () => _redMotion || _sobrio || document.hidden;

/* ── toque ───────────────────────────────────────────────────────────────────────────────────── */
let _toque = {x: 0, y: 0, t: -1e9, dir: 1};
/** O último toque: lado (+1 direita / −1 esquerda) e se foi agora (≤ 1,5 s). */
export function jarvisToque() {
  return {dir: _toque.dir, recente: performance.now() - _toque.t < 1500, x: _toque.x, y: _toque.y};
}
function _registrarToque(e) {
  const c = e.target && e.target.closest ? e.target.closest('.chip, nav.tabs button, .sph') : null;
  let dir = 1;
  if (c && c.parentElement) {
    const irmaos = [...c.parentElement.children];
    const de = irmaos.findIndex(x => x.classList.contains('on')), pa = irmaos.indexOf(c);
    if (de >= 0 && pa >= 0 && pa < de) dir = -1;
  }
  _toque = {x: e.clientX, y: e.clientY, t: performance.now(), dir};
}

/* ── depois de cada render: varredura (holo), pulso (pulso), anel HUD no instrumento principal ── */
function _efemero(cls, estilo, ms) {
  const i = document.createElement('i');
  i.className = cls; i.setAttribute('aria-hidden', 'true');
  if (estilo) i.setAttribute('style', estilo);
  document.body.appendChild(i);
  /* `animationend` não chega se a animação não rodar (aba oculta, CSS desligado): o prazo garante a saída */
  const fora = () => i.remove();
  i.addEventListener('animationend', fora, {once: true});
  setTimeout(fora, ms);
}
function _aposRender(f) {
  const fam = f.dataset.fam;
  if (!_parado()) {
    if (fam === 'holo') _efemero('jv-scan', '', 1400);
    const tq = jarvisToque();
    if (fam === 'pulso' && tq.recente) _efemero('jv-onda', `left:${tq.x}px;top:${tq.y}px`, 1400);
  }
  const alvo = f.querySelector('.ck-hero, .card.kpi, .ck-inst');
  if (alvo && !alvo.querySelector('.jv-hud')) {
    const h = document.createElement('i');
    /* o canto de cima é do ⚠ da KPI crítica: lá o anel desce para o canto de baixo */
    h.className = 'jv-hud' + (alvo.querySelector('.kpi-ico[style*="rose"]') ? ' jv-hud-baixo' : '');
    h.setAttribute('aria-hidden', 'true'); h.innerHTML = '<b></b><b></b>';
    alvo.appendChild(h);
  }
}

/* ── reflexo: uma lâmina de luz num cartão visível, a cada 5,2 s ─────────────────────────────── */
function _reflexo() {
  if (_parado()) return;
  const v = $('view'); if (!v) return;
  const cand = [...v.querySelectorAll('.jv-c.card, .jv-c.ck-inst, .jv-c.ck-hero, .card.kpi')].slice(0, 16);
  if (!cand.length) return;
  for (let k = 0; k < 4; k++) {
    const el = cand[Math.floor(Math.random() * cand.length)];
    const r = el.getBoundingClientRect();              // uma leitura a cada 5 s: só para não brilhar fora da tela
    if (r.bottom < 0 || r.top > innerHeight || el.querySelector('.jv-brilho')) continue;
    if (getComputedStyle(el).position === 'static') continue;
    const i = document.createElement('i');
    i.className = 'jv-brilho'; i.setAttribute('aria-hidden', 'true');
    el.appendChild(i);
    const fora = () => i.remove();
    i.addEventListener('animationend', fora, {once: true});
    setTimeout(fora, 2000);
    return;
  }
}

/* ── telemetria: só dado que o painel já tem ─────────────────────────────────────────────────── */
const _p2 = n => String(n).padStart(2, '0');
function _tele() {
  const t = $('jv-tele'); if (!t) return;
  const d = new Date();
  const partes = [`<span class="num">${_p2(d.getHours())}:${_p2(d.getMinutes())}:${_p2(d.getSeconds())}</span>`];
  if (aoVivo.disponivel === true) partes.push(`<b class="num">${motoresRodando().length}</b> motores`);
  const r = ritmoEstado();
  if (r && r.eventosPorMinuto > 0) partes.push(`<b class="num">${r.eventosPorMinuto}</b> ev/min`);
  if (r && r.load1 > 0) partes.push(`carga <b class="num">${r.load1.toFixed(1).replace('.', ',')}</b>`);
  const h = partes.join('<i aria-hidden="true"></i>');
  if (t.dataset.h !== h) { t.dataset.h = h; t.innerHTML = h; }
}

let _relogio = 0, _brilho = 0;
function _ligarRelogios() {
  if (!_relogio) _relogio = setInterval(_tele, 1000);
  if (!_brilho && !_redMotion) _brilho = setInterval(_reflexo, 5200);
}
function _pararRelogios() { clearInterval(_relogio); clearInterval(_brilho); _relogio = _brilho = 0; }

export function jarvisBoot() {
  if (!_v61) return;
  addEventListener('pointerdown', _registrarToque, {capture: true, passive: true});

  /* anéis HUD em volta do logo */
  const lg = document.querySelector('.brand .lg');
  if (lg && !lg.querySelector('.jv-hud')) {
    const h = document.createElement('i'); h.className = 'jv-hud jv-hud-lg'; h.setAttribute('aria-hidden', 'true');
    h.innerHTML = '<b></b><b></b>'; lg.appendChild(h);
  }
  /* partículas atrás do vidro */
  if (!$('jv-part')) {
    const p = document.createElement('div'); p.id = 'jv-part'; p.setAttribute('aria-hidden', 'true');
    p.innerHTML = '<i></i>'.repeat(_mobile() ? 6 : 12);
    const fundo = $('v61-fundo');
    if (fundo) fundo.insertAdjacentElement('afterend', p); else document.body.insertBefore(p, document.body.firstChild);
  }
  /* telemetria no fim do ticker */
  const tk = $('v61-ticker');
  if (tk && !$('jv-tele')) {
    const t = document.createElement('span'); t.id = 'jv-tele'; t.className = 'jv-tele';
    t.title = 'Telemetria: hora local, motores rodando, eventos por minuto no barramento e carga da VM (só o que já chegou)';
    tk.appendChild(t);
    aoVivoOuvir(_tele);
  }
  _tele();

  /* cada render novo do miolo */
  const v = $('view');
  if (v) new MutationObserver(ms => {
    for (const m of ms) for (const n of m.addedNodes) if (n.nodeType === 1 && n.classList.contains('fade')) _aposRender(n);
  }).observe(v, {childList: true});

  /* aba oculta: tudo para (relógios cancelados; o CSS pausa o que é animação) */
  const vis = () => {
    document.documentElement.classList.toggle('jv-oculto', document.hidden);
    if (document.hidden) _pararRelogios(); else { _tele(); _ligarRelogios(); }
  };
  document.addEventListener('visibilitychange', vis);
  vis();
}
