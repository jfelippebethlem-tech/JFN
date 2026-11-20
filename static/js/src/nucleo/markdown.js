/* MARKDOWN DO PAINEL — duas réguas, as duas escapam TUDO antes de reintroduzir a marcação conhecida.
 *
 * `mdSimples` só negrito e código (rótulos curtos de tabela e campos de requerimento); `mdNota` é a
 * nota inteira do vault (tabela, citação, lista, wikilink, link). Moravam em abas (`casos.js`,
 * `comissao.js`, `abas/index.js`) e eram importadas de aba para aba.
 */
import {esc} from './dom.js';

export const mdSimples = t => esc(t).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/`(.+?)`/g,'<code>$1</code>');

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
