/* O motor de lista do painel — usado por ~40 dos 59 renders. É infraestrutura, não UI de aba.
 *
 * A propriedade que faz ele valer, e que já foi medida: `_pagRenderInner` monta SÓ o lote
 * visível (`itens.slice(0, mostrados)`), não monta-e-esconde. O dataset inteiro vive em
 * memória JS, e é ELE que o filtro e o autocomplete varrem. Numa aba de 770 empresas isso é
 * 770 dados carregados e 80 cards no DOM — o custo no celular sobe no parse do JSON, não no
 * DOM. Filtro que varre só os cards já montados (o que o painel fazia antes) mente: some com
 * resultado que existe e o usuário não tem como saber.
 */
import {$, esc} from './dom.js';
import {fmtN} from './formato.js';

// filtro burro, sobre o DOM: sobrevive para as listas curtas que nunca viraram `listaPaginada`
export function filtrar(inp, sel) {
  const q = inp.value.toLowerCase();
  document.querySelectorAll(sel).forEach(c => {
    c.style.display = c.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
}

// ═══ LISTA PAGINADA incremental — nunca trava o DOM (lote pequeno por vez) e nunca esconde
// dado atrás de um cap fixo (o resto sempre alcançável via "carregar mais", não perdido) ═══
export const _pagState = {};

function _pagFiltrados(st) {
  if (!st.filtro) return st.itens;
  if (!st._idx) st._idx = st.itens.map(x => JSON.stringify(x).toLowerCase());  // índice 1×, filtra em ms
  return st.itens.filter((_, i) => st._idx[i].includes(st.filtro));
}

function _pagRenderInner(id) {
  const st = _pagState[id]; if (!st) return '';
  const itens = _pagFiltrados(st);
  const corpo = itens.slice(0, st.mostrados).map(st.montarCard).join('');
  const restam = itens.length - st.mostrados;
  const nota = st.filtro ? `<div class="dim" style="margin:4px 2px 8px">${fmtN(itens.length)} de ${fmtN(st.itens.length)} no filtro — buscando em <b>tudo</b>, não só no que está na tela.</div>` : '';
  const mais = restam > 0 ? `<div style="text-align:center;margin:14px 0"><button class="btn ghost" onclick="_pagMais('${id}')">Carregar mais (${fmtN(restam)} restante${restam === 1 ? '' : 's'} de ${fmtN(itens.length)})</button></div>` : '';
  return `${nota}<div class="grid">${corpo}</div>${mais}`;
}

export function _pagMais(id) {
  const st = _pagState[id]; if (!st) return;
  st.mostrados = st.mostrados + st.lote;
  const wrap = $(id + '-wrap'); if (wrap) wrap.innerHTML = _pagRenderInner(id);
}

// filtro paginado: varre o DATASET COMPLETO em memória (não só os cards já no DOM)
export function filtrarPag(inp, id) {
  const st = _pagState[id]; if (!st) { filtrar(inp, '#' + id + '-wrap .card'); return; }
  st.filtro = inp.value.trim().toLowerCase(); st.mostrados = st.lote;
  const wrap = $(id + '-wrap'); if (wrap) wrap.innerHTML = _pagRenderInner(id);
  _acPagSugerir(inp, id);
}

// autocomplete CONTEXTUAL da seção: sugere nomes que existem NESTA aba (dataset em memória)
function _acPagSugerir(inp, id) {
  const st = _pagState[id], box = $(id + '-ac'); if (!st || !box) return;
  const q = st.filtro; if (!q || q.length < 2 || !st.campoSug) { box.classList.remove('on'); return; }
  const vistos = new Set(), sug = [];
  for (const x of st.itens) {
    const v = st.campoSug(x); if (!v) continue;
    const lv = String(v); if (vistos.has(lv)) continue;
    if (lv.toLowerCase().includes(q)) { vistos.add(lv); sug.push(lv); if (sug.length >= 8) break; }
  }
  if (!sug.length) { box.classList.remove('on'); return; }
  box.innerHTML = sug.map(s => `<div class="ac-item" onmousedown="event.preventDefault();_acPagPick('${id}',${JSON.stringify(s).replace(/"/g, '&quot;')})">${esc(s)}</div>`).join('');
  box.classList.add('on');
}

export function _acPagPick(id, valor) {
  const box = $(id + '-ac'); if (box) box.classList.remove('on');
  const inp = box && box.parentElement.querySelector('input'); if (!inp) return;
  inp.value = valor; filtrarPag(inp, id);
}

// barra de busca padrão das listas paginadas (filtro no dataset todo + sugestões da própria aba)
export const buscaPag = (id, ph) => `<div class="search" style="margin-top:14px;position:relative"><span class="mag"></span><input placeholder="${ph}" oninput="filtrarPag(this,'${id}')" onblur="setTimeout(()=>{const b=$('${id}-ac');if(b)b.classList.remove('on')},150)"><div class="ac-box" id="${id}-ac"></div></div>`;

export function listaPaginada(id, itens, montarCard, lote, campoSug) {
  lote = lote || 60;
  _pagState[id] = {itens, montarCard, lote, mostrados: Math.min(lote, itens.length), filtro: '', campoSug: campoSug || null};
  return `<div id="${id}-wrap">${_pagRenderInner(id)}</div>`;
}

// ordena qualquer lista por NOME do fornecedor (A→Z) e volta à ordem original (por risco/valor)
export function ordenar(sel, btn) {
  const cont = document.querySelector(String(sel).split(' ')[0]); if (!cont) return;
  const cards = [...cont.querySelectorAll(':scope > .card')]; if (!cards.length) return;
  const chave = c => ((c.querySelector('.clk,b,strong,a') || c).textContent || '').trim().toLowerCase();
  const az = btn.classList.toggle('on');
  if (az) {
    cards.forEach((c, i) => { if (c.dataset.ord0 == null) c.dataset.ord0 = i; });
    cards.sort((a, b) => chave(a).localeCompare(chave(b), 'pt')); btn.textContent = 'A-Z ativo';
  } else {
    cards.sort((a, b) => (+a.dataset.ord0) - (+b.dataset.ord0)); btn.textContent = 'A-Z';
  }
  cards.forEach(c => cont.appendChild(c));
  const cv = document.querySelector('#view .view-wire'); if (cv) cv.remove();   // posições mudaram → tira malha estática
}
