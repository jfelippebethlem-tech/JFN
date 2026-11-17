/* v63 · TRANSIÇÃO DE CLIQUE — o "uau" do Relay: o elemento tocado cresce até cobrir a tela em azul
 * sólido, e a cor se abre revelando a tela nova.
 *
 * TRÊS GESTOS, em rodízio (cada clique é uma novidade), ou o que o elemento pedir em `data-v63-gesto`:
 *   expandir  o retângulo do próprio elemento cresce até a tela (clip-path inset, com o raio dele);
 *   cortina   uma lâmina diagonal varre da esquerda para a direita;
 *   zoom      um círculo nasce do ponto tocado (o nó do grafo, o dedo) e engole a tela.
 *
 * POR QUE NÃO ATRASA A NAVEGAÇÃO: a cobertura começa no MESMO clique em que o `ir()` começa a buscar a
 * aba — o azul esconde o "carregando" em vez de somar tempo a ele. A revelação espera a tela nova ser
 * pintada (o `.fade` novo dentro do `#view`, avisado por `transicaoPintou`) ou 1,6 s, o que vier antes.
 * Enquanto a cobertura está no ar, o `ir()` não abre View Transition (classe `v63-tr-on`): as duas
 * fotografariam uma à outra no meio do gesto.
 *
 * Reduzir movimento e modo sóbrio: sem gesto nenhum — a navegação é a de sempre.
 */
import {_redMotion, _sobrio} from '../capacidade/estado.js';

const GESTOS = ['expandir', 'cortina', 'zoom'];
const ENTRA = 430, SAI = 560, TETO = 1600;
const CURVA = 'cubic-bezier(.7,0,.2,1)';
let _n = 0, _ov = null, _cobriuEm = 0, _pintou = false, _saida = 0;

export function transicaoLigar() {
  document.addEventListener('click', _clique, true);
  document.addEventListener('keydown', e => {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.closest && e.target.closest('[data-v63-ir],[data-v63-dossie]')) {
      e.preventDefault(); e.target.click();
    }
  });
}

function _clique(e) {
  if (e.defaultPrevented || e.button > 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
  const t = e.target.closest && e.target.closest('[data-v63-ir],[data-v63-dossie],nav.tabs button[data-aba],.sph,.ck-inst');
  if (!t) return;
  /* dossiê: abre a folha lateral da casa — sem cobrir a tela (a folha já é um gesto) */
  if (t.dataset.v63Dossie) { e.preventDefault(); window.abrirDossie && window.abrirDossie(t.dataset.v63Dossie, t.dataset.nome || ''); return; }
  if (t.classList.contains('on')) return;                       // aba/esfera em que já se está
  const destino = t.dataset.v63Ir;
  if (!_redMotion && !_sobrio) _cobrir(t, e);
  if (destino) { e.preventDefault(); e.stopPropagation(); window.ir && window.ir(destino); }
}

function _cobrir(el, e) {
  if (_ov) { _ov.remove(); _ov = null; }
  const r = el.getBoundingClientRect(), W = innerWidth, H = innerHeight;
  const gesto = el.dataset.v63Gesto || GESTOS[_n++ % GESTOS.length];
  const cx = e.clientX || r.left + r.width / 2, cy = e.clientY || r.top + r.height / 2;
  const raio = parseFloat(getComputedStyle(el).borderTopLeftRadius) || 16;
  const ov = document.createElement('div');
  ov.className = 'v63-tr g-' + gesto; ov.setAttribute('aria-hidden', 'true');
  const rotulo = (el.getAttribute('title') || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 42);
  ov.innerHTML = `<span class="v63-tr-l">${rotulo.replace(/[<>&]/g, '')}</span>`;
  document.body.appendChild(ov);
  document.documentElement.classList.add('v63-tr-on');
  _ov = ov; _pintou = false; _cobriuEm = 0; clearTimeout(_saida);
  const ini = {
    expandir: `inset(${r.top}px ${W - r.right}px ${H - r.bottom}px ${r.left}px round ${raio}px)`,
    cortina: 'polygon(0% 0%, 0% 0%, -40% 100%, -40% 100%)',
    zoom: `circle(0px at ${cx}px ${cy}px)`,
  }[gesto];
  const fim = {
    expandir: 'inset(0px 0px 0px 0px round 0px)',
    cortina: 'polygon(0% 0%, 140% 0%, 100% 100%, -40% 100%)',
    zoom: `circle(${Math.hypot(Math.max(cx, W - cx), Math.max(cy, H - cy)) + 2}px at ${cx}px ${cy}px)`,
  }[gesto];
  ov.dataset.fim = fim;
  const a = ov.animate([{clipPath: ini}, {clipPath: fim}], {duration: ENTRA, easing: CURVA, fill: 'forwards'});
  a.finished.then(() => { _cobriuEm = performance.now(); if (_pintou) _revelar(); }).catch(() => {});
  _saida = setTimeout(_revelar, TETO);
}

/** Chamado pelo observador do `#view` quando a tela nova foi pintada. */
export function transicaoPintou() {
  _pintou = true;
  if (_ov && _cobriuEm) _revelar();
}

function _revelar() {
  const ov = _ov; if (!ov || ov.dataset.saindo) return;
  ov.dataset.saindo = '1'; clearTimeout(_saida);
  const g = ov.className.replace(/.*g-/, '');
  const fim = ov.dataset.fim;
  const quadros = {
    expandir: [{clipPath: fim}, {clipPath: 'inset(0px 0px 100% 0px round 0px)'}],             // a cor sobe como cortina
    cortina: [{clipPath: fim}, {clipPath: 'polygon(140% 0%, 140% 0%, 100% 100%, 100% 100%)'}],   // a lâmina segue e sai
    zoom: [{opacity: 1, transform: 'scale(1)'}, {opacity: 0, transform: 'scale(1.06)'}],
  }[g];
  const a = ov.animate(quadros, {duration: SAI, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'forwards'});
  const fora = () => { ov.remove(); if (_ov === ov) { _ov = null; document.documentElement.classList.remove('v63-tr-on'); } };
  a.finished.then(fora).catch(fora);
}
