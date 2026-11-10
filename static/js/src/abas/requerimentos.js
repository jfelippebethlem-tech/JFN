/* REQUERIMENTOS — os pedidos de informação que as investigações sugerem, numa aba (pedido do dono, 09/11/2026).
 *
 * Cada item é uma nota em `~/vault/requerimentos/` (um Markdown por requerimento, lido por `/api/requerimentos`).
 * A aba agrupa por situação e abre o item na folha `#ov`: pedidos, fundamento, pendências e a minuta, quando
 * ela existe no vault. SÓ LEITURA: não há envio daqui — protocolar é ato do gabinete.
 *
 * Mesmo desenho da aba Casos, de quem reaproveita as classes `cs-*`, o `mdNota` e o ouvinte `data-cs-abrir`
 * (o botão "Ver o caso" abre o dossiê do caso). Handler próprio por delegação: `data-rq-abrir`.
 */
import {$, esc, card, kpi, cover, sec, spin} from '../nucleo/dom.js';
import {fmtN} from '../nucleo/formato.js';
import {J, erroHumano} from '../nucleo/http.js';
import {a11yfy} from '../ui/index.js';
import {mdNota} from './casos.js';

const GRUPOS = [
  {k: 'sugerido', rot: 'Sugeridos', cor: 'var(--amber)', sobre: 'Pedido que uma nota de caso aponta como próximo passo. Ainda sem texto redigido.'},
  {k: 'minuta', rot: 'Com minuta', cor: 'var(--accent)', sobre: 'Texto redigido, aguardando revisão do titular. Não protocolado.'},
  {k: 'protocolado', rot: 'Protocolados', cor: 'var(--gold)', sobre: 'Enviado ao destinatário; aguardando resposta.'},
  {k: 'respondido', rot: 'Respondidos', cor: 'var(--green)', sobre: 'Resposta recebida.'},
  {k: 'indefinido', rot: 'Nota a corrigir', cor: 'var(--mut)'},
];
const _cor = s => (GRUPOS.find(g => g.k === s) || GRUPOS[4]).cor;
const _n = (n, um, varios) => `${fmtN(n)} ${n === 1 ? um : varios}`;

let _dados = null;

function _cardReq(r) {
  return `<article class="card cs-caso" style="--cs:${_cor(r.status)}">
    <div class="cs-topo">
      <span class="cs-nivel">${esc(r.id)}</span>
      ${r.prioridade ? `<span class="cs-sit">prioridade ${esc(r.prioridade)}</span>` : ''}
      ${r.data_sugestao ? `<span class="dim cs-data">${esc(r.data_sugestao)}</span>` : ''}
    </div>
    <h3 class="cs-tit">${esc(r.titulo)}</h3>
    ${r.destinatario ? `<div class="dim cs-ent">Para: ${esc(r.destinatario)}</div>` : ''}
    <div class="cs-tags"><span class="tag teal">${_n(r.pedidos.length, 'pedido', 'pedidos')}</span>
      <span class="tag ${r.pendencias.length ? 'amber' : 'green'}">${_n(r.pendencias.length, 'pendência', 'pendências')}</span>
      ${r.minuta ? '<span class="tag accent">minuta</span>' : ''}</div>
    ${r.problemas.length ? `<div class="cs-piso">⚠️ ${esc(r.problemas.join('; '))}</div>` : ''}
    <div class="btns"><button type="button" class="btn" data-rq-abrir="${esc(r.slug)}">Abrir</button>
      ${r.caso ? `<button type="button" class="btn ghost" data-cs-abrir="${esc(r.caso)}">Ver o caso</button>` : ''}</div>
  </article>`;
}

export async function renderRequerimentos() {
  let h = cover('geral', 'Requerimentos — pedidos de informação sugeridos',
    'O que as investigações indicam <b>pedir a um órgão</b> para fechar uma dúvida: cada item nasce de um próximo passo ' +
    'escrito numa nota de caso. Esta aba <b>só lê</b> — nada é enviado daqui. ' +
    '<b>Indício a verificar, não acusação</b>, com presunção de legitimidade do ato administrativo.', '📝');
  const d = await J('/api/requerimentos');
  if (!d || d.ok === false) return h + card(`<div class="warn">${erroHumano(d && d.erro)}</div>`);
  _dados = d;
  const ps = d.por_status || {};
  h += `<div class="grid g4">${GRUPOS.slice(0, 4).map(g => kpi(fmtN(ps[g.k] || 0), g.rot, g.cor, null, {sobre: g.sobre})).join('')}</div>`;
  if (!d.total) return h + card('<div class="dim">Nenhum requerimento cadastrado em <code>~/vault/requerimentos/</code>.</div>');
  for (const g of GRUPOS) {
    const it = d.itens.filter(r => r.status === g.k);
    if (it.length) h += sec(g.rot, it.length) + `<div class="cs-grade">${it.map(_cardReq).join('')}</div>`;
  }
  return h;
}

const _lista = (tit, itens, ord) => `<h3 class="cs-h">${tit}</h3>` + (itens.length
  ? `<${ord ? 'ol' : 'ul'}>${itens.map(x => `<li>${esc(x)}</li>`).join('')}</${ord ? 'ol' : 'ul'}>`
  : '<p class="dim">Nenhum item registrado na nota.</p>');

/* A minuta traz âncoras de navegação do Obsidian (`<a id>`, `[↑ topo](#topo)`, sumário com `(#secao)`) que o
 * `mdNota` — que escapa tudo — mostraria como texto cru. Saem antes de renderizar. */
const _semAncoras = md => String(md || '')
  .replace(/^<a id="[^"]*"><\/a>\s*$/gm, '').replace(/^\[↑ topo\]\(#[^)]*\)\s*$/gm, '')
  .replace(/\[([^\]]+)\]\(#[^)]*\)/g, '$1');

async function _abrir(slug) {
  const ov = $('ov'), sh = $('sheet'); if (!ov || !sh) return;
  const r = ((_dados && _dados.itens) || []).find(k => k.slug === slug); if (!r) return;
  const x = '<span class="x" onclick="fecharDossie()">✕ fechar</span><div class="grab"></div>';
  const naVault = /\.md$/.test(r.minuta);
  const corpo = minuta => `<div class="cs-nota" data-rq-folha="${esc(slug)}" style="--cs:${_cor(r.status)}">
    <div class="cs-topo"><span class="cs-nivel">${esc(r.id)} · ${esc(r.status)}</span>
      ${r.prioridade ? `<span class="cs-sit">prioridade ${esc(r.prioridade)}</span>` : ''}
      ${r.data_sugestao ? `<span class="dim cs-data">sugerido em ${esc(r.data_sugestao)}</span>` : ''}</div>
    <h2 class="cs-h">${esc(r.titulo)}</h2>
    ${r.destinatario ? `<p><b>Destinatário:</b> ${esc(r.destinatario)}</p>` : ''}
    ${r.problemas.length ? `<div class="cs-piso">⚠️ ${esc(r.problemas.join('; '))}</div>` : ''}
    ${_lista('Pedidos', r.pedidos, true)}
    <h3 class="cs-h">Fundamento</h3><p>${r.fundamento ? esc(r.fundamento) : '<span class="dim">Não registrado na nota.</span>'}</p>
    ${_lista('Pendências', r.pendencias)}
    ${r.origem ? `<div class="dim cs-fonte">Origem: <code>${esc(r.origem)}</code></div>` : ''}
    ${r.caso ? `<div class="btns"><button type="button" class="btn ghost" data-cs-abrir="${esc(r.caso)}">Ver o caso</button></div>` : ''}
    <hr><h3 class="cs-h">Minuta</h3>
    ${naVault ? `<div class="dim cs-fonte">Fonte: <code>${esc(r.minuta)}</code></div>${minuta}`
      : r.minuta ? `<p class="dim">Fora do vault — não exibida aqui: <code>${esc(r.minuta)}</code></p>`
      : '<p class="dim">Ainda não há minuta.</p>'}
    <div class="note">Nota do vault: <code>requerimentos/${esc(slug)}.md</code> — editar lá; esta folha só lê e não envia nada.</div></div>`;
  ov.classList.add('on');
  sh.innerHTML = x + corpo(naVault ? spin('Abrindo a minuta…') : ''); a11yfy(sh);
  if (!naVault) return;
  const d = await J('/api/requerimentos/minuta?slug=' + encodeURIComponent(slug));
  const no = sh.querySelector('.cs-nota');
  if (!ov.classList.contains('on') || !no || no.dataset.rqFolha !== slug) return;   // fechou ou abriu outra folha na espera
  sh.innerHTML = x + corpo(!d || d.ok === false ? `<div class="warn">${erroHumano(d && d.erro)}</div>` : mdNota(_semAncoras(d.markdown)));
  a11yfy(sh);
}

export function ligarRequerimentos() {
  document.addEventListener('click', ev => {
    const a = ev.target.closest && ev.target.closest('[data-rq-abrir]');
    if (a) { ev.preventDefault(); _abrir(a.dataset.rqAbrir); }
  });
}
