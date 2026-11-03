/* CASOS — os dossiês do vault, conferidos à mão, numa aba própria (pedido do dono, 03/11/2026).
 *
 * O painel tinha 59 abas de DETECÇÃO e nenhuma dos CASOS: o que passou por leitura humana e virou nota em
 * `~/vault/casos/` só existia no Obsidian. A aba lista os dossiês por gravidade, filtra sem refazer o fetch
 * (o filtro repinta só `#cs-lista`), cruza cada um com o parecer do Processo 360 dos autos que ele cita e
 * abre a nota inteira na folha `#ov`.
 *
 * Handlers por DELEGAÇÃO (`data-cs-*`, um ouvinte no `document`, como `data-fila`): nada novo na ponte de
 * globais, e o ouvinte sobrevive à troca de `innerHTML` do `#view`.
 */
import {$, esc, card, kpi, cover, leitura, spin} from '../nucleo/dom.js';
import {fmtN} from '../nucleo/formato.js';
import {J, erroHumano} from '../nucleo/http.js';
import {a11yfy, abrirDossie} from '../ui/index.js';

const NIVEIS = [
  {k: 'alto', ic: '🔴', cor: 'var(--rose)'},
  {k: 'médio-alto', ic: '🟠', cor: 'var(--amber)'},
  {k: 'médio', ic: '🟡', cor: 'var(--gold)'},
  {k: 'baixo', ic: '🟢', cor: 'var(--green)'},
  {k: 'sem grau', ic: '⚪', cor: 'var(--mut)'},
];
const _cor = r => (NIVEIS.find(n => n.k === r) || NIVEIS[4]).cor;
const _ic = r => (NIVEIS.find(n => n.k === r) || NIVEIS[4]).ic;
const SITUACOES = ['aberto', 'concluído', 'afastado', 'contexto'];

let _dados = null;
const _f = {nivel: '', situacao: 'aberto', q: ''};

function _filtrados() {
  const q = _f.q.trim().toLowerCase();
  return (_dados.casos || []).filter(c =>
    (!_f.nivel || c.nivel_rotulo === _f.nivel) &&
    (!_f.situacao || c.situacao === _f.situacao) &&
    (!q || [c.titulo, c.resumo, c.entidade, c.slug, (c.tags || []).join(' '), (c.sei || []).join(' '),
      (c.cnpjs || []).join(' ')].join(' ').toLowerCase().includes(q)));
}

function _chips() {
  const cont = _dados.por_nivel || {};
  const b = (grupo, v, rot, on) => `<button type="button" class="chip ${on ? 'on' : ''}" data-cs-f="${grupo}" data-cs-v="${esc(v)}" aria-pressed="${on}">${rot}</button>`;
  return `<div class="cs-filtros">
    <div class="chips" role="group" aria-label="Gravidade">${b('nivel', '', 'Todas as gravidades', !_f.nivel)}${
      NIVEIS.filter(n => cont[n.k]).map(n => b('nivel', n.k, `${n.ic} ${n.k} · ${fmtN(cont[n.k])}`, _f.nivel === n.k)).join('')}</div>
    <div class="chips" role="group" aria-label="Situação">${b('situacao', '', 'Todas', !_f.situacao)}${
      SITUACOES.map(s => b('situacao', s, s, _f.situacao === s)).join('')}</div>
    <div class="search"><span class="mag"></span><input id="cs-q" placeholder="filtrar por empresa, órgão, nº SEI, CNPJ, tag…" value="${esc(_f.q)}" aria-label="Filtrar casos"></div>
  </div>`;
}

function _cardCaso(c) {
  const par = (c.pareceres || []).map(p =>
    `<span class="tag ${p.grau === 'A' || p.grau === 'B' ? 'rose' : 'teal'}" title="Parecer do Processo 360 em ${esc(String(p.avaliado_em || '').slice(0, 10))}">360 ${esc(p.numero)} · grau ${esc(p.grau)}${p.score100 != null ? ' · ' + Math.round(p.score100) : ''}</span>`).join('');
  const sei = (c.sei || []).filter(n => !(c.pareceres || []).some(p => p.numero === n)).slice(0, 3)
    .map(n => `<span class="cs-sei">${esc(n)}</span>`).join('');
  const mais = Math.max(0, (c.sei || []).length - (c.pareceres || []).length - 3);
  const cnpj = (c.cnpjs || []).slice(0, 4).map(x =>
    `<button type="button" class="cs-cnpj" data-cs-cnpj="${esc(x)}" title="Abrir o dossiê da empresa">${esc(x)}</button>`).join('');
  return `<article class="card cs-caso" style="--cs:${_cor(c.nivel_rotulo)}">
    <div class="cs-topo">
      <span class="cs-nivel" title="${esc(c.grau || c.nivel_rotulo)}">${_ic(c.nivel_rotulo)} ${esc(c.nivel_rotulo)}</span>
      <span class="cs-sit ${esc(c.situacao)}">${esc(c.situacao)}</span>
      ${c.atualizado ? `<span class="dim cs-data">${esc(c.atualizado)}</span>` : ''}
    </div>
    <h3 class="cs-tit">${esc(c.titulo)}</h3>
    ${c.entidade ? `<div class="dim cs-ent">${esc(c.entidade)}</div>` : ''}
    ${c.resumo ? `<p class="cs-res">${esc(c.resumo)}</p>` : ''}
    ${par || sei ? `<div class="cs-tags">${par}${sei}${mais ? `<span class="dim">+${mais}</span>` : ''}</div>` : ''}
    ${cnpj ? `<div class="cs-tags">${cnpj}</div>` : ''}
    ${c.piso_siafe ? `<div class="cs-piso">⚠️ valores de SIAFE da nota são PISO (coleta incompleta)</div>` : ''}
    <div class="btns"><button type="button" class="btn" data-cs-abrir="${esc(c.slug)}">Ler o dossiê</button></div>
  </article>`;
}

function _pintarLista() {
  const el = $('cs-lista'); if (!el || !_dados) return;
  const it = _filtrados();
  el.innerHTML = `<div class="dim cs-conta">${fmtN(it.length)} de ${fmtN(_dados.total)} casos</div>` + (it.length
    ? `<div class="cs-grade">${it.map(_cardCaso).join('')}</div>`
    : card('<div class="dim">Nenhum caso com esses filtros.</div>'));
  a11yfy(el);
}

export async function renderCasos() {
  let h = cover('geral', 'Casos — os dossiês conferidos',
    'O que passou por <b>leitura humana</b> e virou dossiê no vault: fatos, fontes, o que fecha e o pedido concreto. ' +
    'Os achados automáticos ficam nas abas de detecção; aqui só entra o que foi conferido. ' +
    '<b>Indício a verificar, não acusação</b>, com presunção de legitimidade do ato administrativo.', '🗂️');
  const d = await J('/api/casos');
  if (!d || d.ok === false) return h + card(`<div class="warn">${erroHumano(d && d.erro)}</div>`);
  _dados = d;
  const pn = d.por_nivel || {};
  h += `<div class="grid g4">
    ${kpi(fmtN(d.total), 'Dossiês no vault', null, '🗂️', {sobre: 'Cada nota em <code>~/vault/casos/</code>. É o trabalho conferido à mão — não a saída de um detector.'})}
    ${kpi(fmtN(d.abertos), 'Em aberto', 'var(--amber)', '📂', {sobre: 'Status aberto no frontmatter da nota: falta um passo para fechar (documento, ofício, recaptura).'})}
    ${kpi(fmtN(pn['alto'] || 0), 'Gravidade alta (🔴)', 'var(--rose)', '🔴', {sobre: 'Primeiro semáforo encontrado em severidade/grau/gravidade/risco da nota. Nota sem semáforo fica <b>sem grau</b> — nunca vira verde por omissão.'})}
    ${kpi(fmtN(d.com_parecer_360), 'Com parecer 360 dos autos', 'var(--accent)', '⚖️', {sobre: 'Casos cujo nº SEI citado já tem avaliação no Processo 360 — o que o motor diz hoje dos mesmos autos.'})}
  </div>`;
  if (pn['sem grau']) h += leitura(`${fmtN(pn['sem grau'])} dossiê(s) não declaram gravidade na nota — aparecem como <b>sem grau</b>, não como baixo risco.`);
  h += _chips() + `<div id="cs-lista">${spin()}</div>`;
  // o #view só recebe este HTML depois do return: espera o nó para pintar a lista
  let t = 0; const por = () => { if ($('cs-lista')) _pintarLista(); else if (t++ < 40) setTimeout(por, 50); }; por();
  return h;
}

/* Markdown mínimo e SEGURO para a nota: escapa tudo antes e só então reintroduz a marcação conhecida. */
function _inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, '$1<i>$2</i>')
    .replace(/~~([^~]+)~~/g, '<s>$1</s>')
    .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, a, b) => `<span class="cs-wl">${b || a.split('/').pop()}</span>`)
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
export function mdNota(md) {
  const L = String(md || '').replace(/<!--[\s\S]*?-->/g, '').split('\n');
  const out = []; let i = 0;
  while (i < L.length) {
    const l = L[i];
    if (/^\s*\|/.test(l)) {
      const rows = []; while (i < L.length && /^\s*\|/.test(L[i])) rows.push(L[i++]);
      const cel = r => r.trim().replace(/^\||\|$/g, '').split('|').map(x => x.trim());
      const sep = rows[1] && /^[\s|:-]+$/.test(rows[1]);
      const head = sep ? cel(rows[0]) : null, body = rows.slice(sep ? 2 : 0).map(cel);
      out.push(`<div class="cs-tbw"><table class="tb">${head ? `<thead><tr>${head.map(x => `<th>${_inline(x)}</th>`).join('')}</tr></thead>` : ''}<tbody>${
        body.map(r => `<tr>${r.map(x => `<td>${_inline(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
      continue;
    }
    if (/^>\s?/.test(l)) {
      const q = []; while (i < L.length && /^>\s?/.test(L[i])) q.push(L[i++].replace(/^>\s?/, ''));
      out.push(`<blockquote>${q.map(_inline).join('<br>')}</blockquote>`); continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(l)) {
      const ord = /^\s*\d+\./.test(l), it = [];
      while (i < L.length && (/^\s*([-*]|\d+\.)\s+/.test(L[i]) || (/^\s{2,}\S/.test(L[i]) && it.length))) {
        if (/^\s*([-*]|\d+\.)\s+/.test(L[i])) it.push(L[i].replace(/^\s*([-*]|\d+\.)\s+/, ''));
        else it[it.length - 1] += ' ' + L[i].trim();
        i++;
      }
      out.push(`<${ord ? 'ol' : 'ul'}>${it.map(x => `<li>${_inline(x)}</li>`).join('')}</${ord ? 'ol' : 'ul'}>`); continue;
    }
    const m = l.match(/^(#{1,4})\s+(.*)$/);
    if (m) { out.push(`<h${m[1].length + 1} class="cs-h">${_inline(m[2])}</h${m[1].length + 1}>`); i++; continue; }
    if (/^\s*(---|\*\*\*)\s*$/.test(l)) { out.push('<hr>'); i++; continue; }
    if (!l.trim()) { i++; continue; }
    const p = []; while (i < L.length && L[i].trim() && !/^(#{1,4}\s|>|\s*\||\s*([-*]|\d+\.)\s)/.test(L[i])) p.push(L[i++]);
    if (!p.length) p.push(L[i++]);
    out.push(`<p>${_inline(p.join(' '))}</p>`);
  }
  return out.join('');
}

async function _abrirNota(slug) {
  const ov = $('ov'), sh = $('sheet'); if (!ov || !sh) return;
  const x = '<span class="x" onclick="fecharDossie()">✕ fechar</span><div class="grab"></div>';
  ov.classList.add('on');
  sh.innerHTML = x + spin('Abrindo o dossiê…'); a11yfy(sh);
  const d = await J('/api/casos/nota?slug=' + encodeURIComponent(slug));
  if (!d || d.ok === false) { sh.innerHTML = x + card(`<div class="warn">${erroHumano(d && d.erro)}</div>`); a11yfy(sh); return; }
  const c = ((_dados && _dados.casos) || []).find(k => k.slug === slug) || {};
  sh.innerHTML = x + `<div class="cs-nota" style="--cs:${_cor(c.nivel_rotulo)}">
    <div class="cs-topo"><span class="cs-nivel">${/[🔴🟠🟡🟢]/u.test(c.grau || '') ? '' : _ic(c.nivel_rotulo) + ' '}${esc(c.grau || c.nivel_rotulo || '')}</span>
      ${c.situacao ? `<span class="cs-sit ${esc(c.situacao)}">${esc(d.meta.status || c.situacao)}</span>` : ''}</div>
    ${c.fonte ? `<div class="dim cs-fonte">Fonte: ${esc(c.fonte)}</div>` : ''}
    ${mdNota(d.markdown)}
    <div class="note">Nota do vault: <code>casos/${esc(slug)}.md</code> — editar lá; esta folha só lê.</div></div>`;
  a11yfy(sh);
}

export function ligarCasos() {
  document.addEventListener('click', ev => {
    if (!ev.target.closest) return;
    const f = ev.target.closest('[data-cs-f]');
    if (f) { ev.preventDefault(); _f[f.dataset.csF] = f.dataset.csV;
      for (const b of document.querySelectorAll(`[data-cs-f="${f.dataset.csF}"]`)) {
        const on = b.dataset.csV === _f[f.dataset.csF]; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); }
      _pintarLista(); return; }
    const a = ev.target.closest('[data-cs-abrir]');
    if (a) { ev.preventDefault(); _abrirNota(a.dataset.csAbrir); return; }
    const c = ev.target.closest('[data-cs-cnpj]');
    if (c) { ev.preventDefault(); abrirDossie(c.dataset.csCnpj, ''); }
  });
  let tm = null;
  document.addEventListener('input', ev => {
    if (ev.target && ev.target.id === 'cs-q') { _f.q = ev.target.value; clearTimeout(tm); tm = setTimeout(_pintarLista, 120); }
  });
}
