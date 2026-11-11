/* v61 TRON CLARO — o par em JS do estrato `static/css/src/99z2-v61-*.css`.
 *
 * Mesmo contrato do `ui/v60.js`: uma função de entrada (`v61Boot`), chamada UMA vez no início do
 * boot, que não faz nada sem a flag. Sem `html.v61` o painel é a v60, byte a byte.
 * Não tem efeito de topo (o boot é ordenado pelo entrypoint, não pelo import).
 */
import {_v61, _v61flag} from '../capacidade/estado.js';

/* glifos de linha próprios (traço 1.6, cantos redondos, caixa 24) — o set da casa não tem sol/lua */
const _SOL = '<svg class="jico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M18.7 5.3l-1.8 1.8M7.1 16.9l-1.8 1.8"/></svg>';
const _LUA = '<svg class="jico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/></svg>';

export function v61Boot() {
  if (!_v61flag) return;
  _tema();
  if (!_v61) return;
  _fundo();
}

/** Linha "Tema escuro / Tema claro" da folha "⋯" (o `ui/v60.js` a encaixa no menu). */
export function v61TemaItem() {
  if (!_v61flag) return '';
  return `<button type="button" class="v60-mi" data-v61-tema><span class="v60-ic" aria-hidden="true">${_v61 ? _LUA : _SOL}</span>${_v61 ? 'Tema escuro' : 'Tema claro'}<small>${_v61 ? 'volta ao painel escuro' : 'volta ao painel claro'}</small></button>`;
}

/* ── tema: claro é o padrão; "Tema escuro" grava `jfn_tema=escuro` e recarrega (a classe é posta
   pelo script inline do <head>, antes do CSS pintar — trocar em voo deixaria os canvas no tema velho) */
function _tema() {
  const box = document.querySelector('.htop .actions');
  if (box && !box.querySelector('[data-v61-tema]')) {
    const a = document.createElement('a');
    const txt = _v61 ? 'Tema escuro' : 'Tema claro';
    a.setAttribute('role', 'button'); a.tabIndex = 0; a.dataset.v61Tema = '1';
    a.title = txt; a.setAttribute('aria-label', txt);
    a.innerHTML = `<span class="v60-ic" aria-hidden="true">${_v61 ? _LUA : _SOL}</span><span class="v60-tx">${txt}</span>`;
    box.insertBefore(a, box.querySelector('a.help:not(.som)') || null);
  }
  const troca = e => {
    const b = e.target && e.target.closest && e.target.closest('[data-v61-tema]'); if (!b) return;
    if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault();
    try { if (_v61) localStorage.setItem('jfn_tema', 'escuro'); else localStorage.removeItem('jfn_tema'); } catch (_) {}
    location.reload();
  };
  document.addEventListener('click', troca);
  document.addEventListener('keydown', troca);
}

/* ── fundo: véu claro + grade Tron em perspectiva + 3 rastros de luz. Só CSS anima; aqui só nasce
   o DOM (uma camada fixa, sem evento de ponteiro). O vídeo/pôster da esfera segue no `#esfnebula`. */
function _fundo() {
  if (document.getElementById('v61-fundo')) return;
  const f = document.createElement('div');
  f.id = 'v61-fundo'; f.setAttribute('aria-hidden', 'true');
  f.innerHTML = '<div class="v61-veu"></div><div class="v61-piso"><div class="v61-plano"><div class="v61-grade"></div><i class="r1"></i><i class="r2"></i><i class="r3"></i></div></div>';
  document.body.insertBefore(f, document.body.firstChild);
}
