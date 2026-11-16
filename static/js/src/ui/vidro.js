/* VIDRO AJUSTÁVEL (16/11/2026) — o painel «Ajustar vidro», par em JS do estrato `99z2-v61-95-vidro.css`.
 *
 * Referência: o «Adjust glass» do Adjustable Glass Dashboard (21st.dev). Cinco controles — desfoque,
 * opacidade, saturação, tinta e luz de borda — que escrevem SÓ os tokens `--vidro-*` no <html>. Quem
 * transforma token em superfície é o CSS; este módulo não pinta nada.
 *
 * LEGIBILIDADE NÃO É AJUSTÁVEL: os limites abaixo (opacidade ≥ .40, tinta ≤ .12) foram medidos com
 * `tools/auditar_contraste_pixel.py` — texto sobre o vidro fica ≥ 4,5:1 nos dois extremos. Valor
 * gravado fora da faixa (versão antiga, edição à mão) é PRESO à faixa ao ler, nunca aplicado cru.
 *
 * Preferência é do aparelho: `localStorage`, sempre em try/catch (aba privada, armazenamento
 * bloqueado) — sem armazenamento o controle funciona igual, só não lembra na próxima carga.
 * Sem efeito de topo; quem liga é `vidroBoot()` na sequência de boot (`entrada.js`).
 */
import {_v61} from '../capacidade/estado.js';

const CHAVE = 'jfn_vidro';
/* [token, rótulo, mín, máx, passo, padrão, unidade, formatação] — o padrão é o do CSS */
const CTRL = [
  ['blur',  'Desfoque',      0,   40,  1,    22,  'px', v => `${v} px`],
  ['alfa',  'Opacidade',     .40, .92, .01,  .56, '',   v => `${Math.round(v * 100)}%`],
  ['sat',   'Saturação',     1,   2,   .05,  1.2, '',   v => `${Number(v).toFixed(2).replace('.', ',')}×`],
  ['tinta', 'Tinta azul',    0,   .12, .01,  .04, '',   v => `${Math.round(v / .12 * 100)}%`],
  ['borda', 'Luz de borda',  0,   1,   .05,  .6,  '',   v => `${Math.round(v * 100)}%`],
];
const _prender = (c, v) => { const n = Number(v); return Number.isFinite(n) ? Math.min(c[3], Math.max(c[2], n)) : c[5]; };

function _ler() {
  let o = {};
  try { o = JSON.parse(localStorage.getItem(CHAVE) || '{}') || {}; } catch (_) { o = {}; }
  const r = {};
  for (const c of CTRL) r[c[0]] = _prender(c, o[c[0]] ?? c[5]);
  return r;
}
function _gravar(val) { try { localStorage.setItem(CHAVE, JSON.stringify(val)); } catch (_) { /* sem armazenamento: só não lembra */ } }
function _esquecer() { try { localStorage.removeItem(CHAVE); } catch (_) { /* idem */ } }

/** Aplica os tokens. Valor igual ao padrão SAI do style inline — o CSS volta a mandar. */
function _aplicar(val) {
  const h = document.documentElement.style;
  for (const c of CTRL) {
    const v = val[c[0]];
    if (v === c[5]) h.removeProperty('--vidro-' + c[0]); else h.setProperty('--vidro-' + c[0], v + c[6]);
  }
}

const _ICO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" aria-hidden="true">'
  + '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/></svg>';

export function vidroBoot() {
  if (!_v61) return;
  let val = _ler();
  _aplicar(val);
  const box = document.querySelector('.htop .actions'); if (!box || document.querySelector('[data-vidro-abrir]')) return;
  const b = document.createElement('button');
  b.type = 'button'; b.className = 'vd-btn'; b.setAttribute('data-vidro-abrir', '');
  b.title = 'Ajustar vidro — desfoque, opacidade, saturação, tinta e luz de borda';
  b.setAttribute('aria-label', 'Ajustar vidro'); b.setAttribute('aria-haspopup', 'dialog'); b.setAttribute('aria-expanded', 'false');
  b.innerHTML = _ICO;
  box.insertBefore(b, box.querySelector('a.som') || box.firstChild);

  const pop = document.createElement('div');
  pop.id = 'vd-pop'; pop.hidden = true; pop.setAttribute('role', 'dialog'); pop.setAttribute('aria-label', 'Ajustar vidro');
  pop.innerHTML = '<h3>Ajustar vidro</h3><p class="vd-sub">Só a aparência deste aparelho. O texto fica sempre legível: os limites foram medidos.</p>'
    + CTRL.map(c => `<label>${c[1]}<output data-vidro-saida="${c[0]}"></output>`
      + `<input type="range" data-vidro="${c[0]}" min="${c[2]}" max="${c[3]}" step="${c[4]}" aria-label="${c[1]}"></label>`).join('')
    + '<div class="vd-pe"><small>gravado neste navegador</small><button type="button" class="vd-reset" data-vidro-padrao>Restaurar padrão</button></div>';
  document.body.appendChild(pop);

  const pintar = () => {
    for (const c of CTRL) {
      const i = pop.querySelector(`[data-vidro="${c[0]}"]`), o = pop.querySelector(`[data-vidro-saida="${c[0]}"]`);
      if (i) i.value = val[c[0]]; if (o) o.textContent = c[7](val[c[0]]);
    }
  };
  const abrir = sim => {
    pop.hidden = !sim; b.setAttribute('aria-expanded', sim ? 'true' : 'false');
    if (sim) { pintar(); const p = pop.querySelector('input'); if (p) p.focus({preventScroll: true}); }
  };
  b.addEventListener('click', e => { e.stopPropagation(); abrir(pop.hidden); });
  pop.addEventListener('input', e => {
    const k = e.target && e.target.dataset ? e.target.dataset.vidro : null;
    const c = CTRL.find(x => x[0] === k); if (!c) return;
    val = {...val, [k]: _prender(c, e.target.value)};
    _aplicar(val); _gravar(val);
    const o = pop.querySelector(`[data-vidro-saida="${k}"]`); if (o) o.textContent = c[7](val[k]);
  });
  pop.addEventListener('click', e => {
    if (!(e.target && e.target.closest && e.target.closest('[data-vidro-padrao]'))) return;
    val = Object.fromEntries(CTRL.map(c => [c[0], c[5]]));
    _aplicar(val); _esquecer(); pintar();
  });
  document.addEventListener('click', e => { if (!pop.hidden && !pop.contains(e.target) && e.target !== b) abrir(false); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !pop.hidden) { abrir(false); b.focus(); } });
}
