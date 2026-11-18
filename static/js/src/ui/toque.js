/* ══ v67 · TOQUE — tabela vira lista de cartões no celular; todo alvo com ≥ 44 × 44 px ══════════════
   Componente ÚNICO para as ~100 tabelas do painel (escritas à mão em template string, aba a aba).
   Em vez de reescrever cada aba, um passe pós-render — idempotente, no mesmo molde do `v60Vivo` —
   marca cada `<table>` do `#view`/`#sheet`:

   - rótulo de cada célula (`data-rotulo`, lido do cabeçalho da coluna, com `colspan` respeitado);
   - o DESTINO PRINCIPAL da linha (`.tt-principal`): o `.clk` (abre o dossiê) ou, sem ele, o 1º link
     de navegação. No cartão ele ganha a área do cartão inteiro (link esticado por `::after`) — sem
     JS de clique, sem duplicar evento, e o leitor de tela continua lendo um link só;
   - as ações SECUNDÁRIAS (`.tt-sec`): ficam por cima do link esticado, como botões de 44 px.

   No celular (≤ 640 px) a tabela entra em modo cartão (`.tt-cartoes`) quando tem alvo de toque ou
   não cabe na largura. Desktop continua tabela: as classes não fazem nada fora da media query.
   Tabela só de leitura que cabe fica como está (densidade). Opt-out: `data-tt="tabela"`. */

const ALVO = 'a[href],button,[role=button],summary,input:not([type=hidden]),select,[onclick]';
const COARSE = typeof matchMedia === 'function' ? matchMedia('(pointer:coarse)') : null;
const MQ = typeof matchMedia === 'function' ? matchMedia('(max-width:640px)') : null;
const _txt = el => (el.textContent || '').replace(/\s+/g, ' ').trim();

/** Cabeçalhos por coluna (expande colspan); usa a última linha de `thead` ou a 1ª linha só de `th`. */
function _rotulos(t) {
  let linha = t.tHead && t.tHead.rows.length ? t.tHead.rows[t.tHead.rows.length - 1] : null;
  if (!linha) {
    const r0 = t.rows[0];
    if (r0 && r0.cells.length > 1 && [...r0.cells].every(c => c.tagName === 'TH')) linha = r0;
  }
  if (!linha) return null;
  const out = [];
  for (const c of linha.cells) for (let k = 0; k < (c.colSpan || 1); k++) out.push(_txt(c).slice(0, 40));
  return out;
}

function _principal(tr) {
  if (tr.hasAttribute('onclick')) return tr;
  const clk = tr.querySelector('.clk');
  if (clk) return clk;
  const a = tr.querySelector('a[href]:not([href="#"])');
  return a || null;
}

/** Marca a tabela (uma vez) e decide o modo — o modo é refeito quando a largura muda. */
function _preparar(t) {
  if (t.dataset.tt === 'tabela' || t.closest('[data-tt="tabela"]')) return;
  const corpo = [...t.tBodies].flatMap(b => [...b.rows]);
  if (!corpo.length) return;
  if (t.dataset.tt !== 'pronta' || t.dataset.ttN !== String(corpo.length)) {
    const cab = _rotulos(t);
    let alvos = 0;
    for (const tr of corpo) {
      let col = 0;
      for (const td of tr.cells) {
        const r = cab && cab[col];
        if (r && td.tagName === 'TD') td.dataset.rotulo = r; else delete td.dataset.rotulo;
        const tx = _txt(td), palavra = tx.split(' ').reduce((a, b) => b.length > a.length ? b : a, '');
        /* campo longo, ou com "palavra" comprida (nº de OB, slug, nome de modelo), ocupa a largura toda —
           em meia coluna (~150 px) ele quebraria na letra */
        /* valor (R$, número, %) não quebra no meio: "2.282.941.698,\n78" lê como dois números */
        td.classList.toggle('tt-num', tx.length > 0 && tx.length <= 24 && /^[R$\s\d.,%+\-−–—]+$/.test(tx) && /\d/.test(tx));
        if (tx.length > 34 || palavra.length > 14 || td.querySelector('table,ul,ol,details')) td.classList.add('tt-larga');
        col += td.colSpan || 1;
      }
      if (tr.cells.length === 1 && (tr.cells[0].colSpan || 1) > 1) tr.classList.add('tt-faixa');
      const p = _principal(tr);
      tr.classList.toggle('tt-tem-principal', !!p && p !== tr);
      tr.classList.toggle('tt-linha-alvo', p === tr);
      for (const el of tr.querySelectorAll(ALVO)) {
        alvos++;
        el.classList.toggle('tt-principal', el === p);
        el.classList.toggle('tt-sec', el !== p);
      }
      if (p === tr) alvos++;
    }
    t.dataset.tt = 'pronta'; t.dataset.ttN = String(corpo.length);
    t.dataset.ttAlvos = String(alvos);
    t.classList.add('tt');
  }
  _modo(t);
}

function _modo(t) {
  const celular = !!(MQ && MQ.matches);
  if (!celular) { t.classList.remove('tt-cartoes'); return; }
  if (t.classList.contains('tt-cartoes')) return;
  const colunas = Math.max(0, ...[...t.rows].map(r => [...r.cells].reduce((s, c) => s + (c.colSpan || 1), 0)));
  if (colunas < 2) return;
  const caixa = t.parentElement ? t.parentElement.clientWidth : innerWidth;
  const naoCabe = t.scrollWidth > caixa + 2 || t.getBoundingClientRect().width > innerWidth;
  /* esmagada: alguma célula mais estreita que a própria palavra mais longa (a tabela "coube" quebrando
     palavra na letra — "2025OB00096" em 39 px). Olha só as primeiras linhas: é sintoma de coluna, não de linha. */
  let esmagada = false;
  for (const tr of [...t.rows].slice(0, 25)) {
    for (const td of tr.cells) {
      const w = td.clientWidth; if (!w) continue;
      const p = _txt(td).split(' ').reduce((a, b) => b.length > a.length ? b : a, '');
      if (p.length >= 7 && w < p.length * 5.2) { esmagada = true; break; }
    }
    if (esmagada) break;
  }
  if (Number(t.dataset.ttAlvos) > 0 || naoCabe || esmagada || colunas >= 5) t.classList.add('tt-cartoes');
}

/** Link dentro de frase (há texto corrido ao lado, no mesmo pai): exceção "inline" da WCAG 2.5.8 —
 *  o tamanho é o da linha de texto; engordar quebraria a leitura do parágrafo. */
function _emTexto(el) {
  const cs = getComputedStyle(el);
  if (!cs.display.startsWith('inline') || cs.display === 'inline-block' || cs.display === 'inline-flex') return false;
  const pai = el.parentElement; if (!pai) return false;
  for (const n of pai.childNodes) if (n !== el && n.nodeType === 3 && n.textContent.trim().length > 2) return true;
  return false;
}

/** Fora das tabelas-cartão: todo alvo solto (chip, botão, `.clk`, `summary`, link de ação) ganha
 *  44 × 44 reais no toque (`.tt-alvo`, só sob `pointer:coarse`). Um alvo ≥ 44 × 44 não disputa toque
 *  com o vizinho — a área de acerto É a caixa dele. */
function _alvosSoltos(raiz) {
  if (!COARSE || !COARSE.matches) return;
  for (const el of raiz.querySelectorAll(ALVO)) {
    if (el.classList.contains('tt-alvo') || el.closest('table.tt-cartoes') || el.dataset.ttTexto) continue;
    if (el.classList.contains('tt-principal') && el.closest('.tt-cartao')) continue;
    if (el.matches('input[type=checkbox],input[type=radio],input[type=range]')) continue;
    if (el.tagName === 'A' && _emTexto(el)) { el.dataset.ttTexto = '1'; continue; }
    el.classList.add('tt-alvo');
    if (getComputedStyle(el).display === 'inline') el.classList.add('tt-alvo-inl');
  }
}

/** Lista do v60 (`.v60-lista > .card.v60-abre`): o cartão inteiro já abre o dossiê (clique delegado ao
 *  `.clk`), mas o alvo de verdade era só o nome. Aqui o `.clk` vira link esticado sobre o cartão — o mesmo
 *  padrão das tabelas-cartão; o delegado do v60 continua valendo para quem clica fora do nome. */
function _listas(raiz) {
  for (const c of raiz.querySelectorAll('.v60-lista > .card.v60-abre:not(.tt-cartao)')) {
    const p = c.querySelector('.clk'); if (!p) continue;
    c.classList.add('tt-cartao');
    p.classList.add('tt-principal');
    for (const el of c.querySelectorAll(ALVO)) if (el !== p) el.classList.add('tt-sec');
  }
}

export function toqueVivo(raiz) {
  if (!raiz) return;
  for (const t of raiz.querySelectorAll('table')) _preparar(t);
  _listas(raiz);
  _alvosSoltos(raiz);
}

let _passe = 0;
export function toqueBoot() {
  const raizes = ['view', 'sheet'].map(id => document.getElementById(id)).filter(Boolean);
  /* vazão, não debounce: o `#view` tem números vivos que mudam o tempo todo — com debounce o passe
     podia nunca rodar. Um passe agendado por vez, no máximo a cada 80 ms. */
  const passe = () => { if (_passe) return; _passe = setTimeout(() => { _passe = 0; raizes.forEach(toqueVivo); }, 80); };
  /* só interessa mutação que acrescenta ELEMENTO (troca de texto de contador não pede passe) */
  const obs = ms => { for (const m of ms) for (const n of m.addedNodes) if (n.nodeType === 1) return passe(); };
  for (const r of raizes) new MutationObserver(obs).observe(r, {childList: true, subtree: true});
  if (MQ) {
    const troca = () => { for (const r of raizes) for (const t of r.querySelectorAll('table.tt')) { t.classList.remove('tt-cartoes'); _modo(t); } };
    MQ.addEventListener ? MQ.addEventListener('change', troca) : MQ.addListener(troca);
  }
  passe();
}
