/* v60 CLAREZA — os ajustes de DOM que só existem com `html.v60`.
 *
 * O CSS do v60 mora num estrato só (`static/css/src/99z-v60-clareza.css`); este módulo é o par dele
 * no JS: tudo o que o CSS sozinho não alcança (texto em caixa alta na origem, gatilho novo no
 * cabeçalho, estado recolhido do holofeed). Uma função de entrada, `v60Boot`, chamada UMA vez no
 * início da sequência de boot de `entrada.js` — e que não faz nada sem a classe. Sem a classe o
 * painel é o anterior, byte a byte no comportamento.
 *
 * Não tem efeito de topo (o boot é ordenado pelo entrypoint, não pelo import).
 */
import {$, svgIco} from '../nucleo/dom.js';
import {_v60, _v61} from '../capacidade/estado.js';
import {v61TemaItem} from './v61.js';

export function v60Boot() {
  if (!_v60) return;
  /* rótulo do cabeçalho: sentence case na ORIGEM (o CSS não baixa "RJ"/"SIAFE" sem estragar a sigla) */
  const hs = $('hsub'); if (hs) hs.textContent = 'Central de inteligência · RJ';
  _acoes();
  _feed();
  _observar();
}

/* ── o passe pós-render ────────────────────────────────────────────────────────────────────────
   O `#view` troca de `innerHTML` a cada aba e várias listas chegam depois (fetch). Um observador
   só, com debounce, chama `v60Vivo` sempre que o miolo muda. O passe é IDEMPOTENTE — na segunda
   volta não altera nada, então não se realimenta. */
let _passe = 0, _passeS = 0;
function _observar() {
  const v = $('view'); if (!v) return;
  new MutationObserver(() => { clearTimeout(_passe); _passe = setTimeout(() => v60Vivo(v), 60); })
    .observe(v, {childList: true, subtree: true});
  /* o #sheet (dossiê, termos, gavetas) recebe o mesmo passe: rating sem emoji, pills, listas */
  const sh = $('sheet');
  if (sh) new MutationObserver(() => { clearTimeout(_passeS); _passeS = setTimeout(() => v60Vivo(sh), 60); })
    .observe(sh, {childList: true, subtree: true});
  /* "mais"/"menos" da descrição do cabeçalho de aba — delegado */
  document.addEventListener('click', e => {
    const b = e.target && e.target.closest && e.target.closest('[data-v60-desc]'); if (!b) return;
    const cv = b.closest('.cover,.ck-lead'); if (!cv) return;
    const ab = cv.classList.toggle('v60-aberta');
    b.textContent = ab ? 'menos' : 'mais'; b.setAttribute('aria-expanded', ab ? 'true' : 'false');
  });
  /* linha de lista inteira clicável: repassa o clique ao `.clk` da própria linha */
  v.addEventListener('click', e => {
    const linha = e.target && e.target.closest && e.target.closest('.v60-lista > .card.v60-abre');
    if (!linha || e.target.closest('button,a,input,select,label,[onclick]')) return;
    const alvo = linha.querySelector('.clk'); if (alvo) alvo.click();
  });
  v60Vivo(v);
}

export function v60Vivo(v) {
  if (!_v60 || !v) return;
  _capa(v);
  _kpiN(v);
  _graus(v);
  _listas(v);
  _miudos(v);
  _cockpit(v);
}

/* ── cockpit: "mais" no texto do herói e o mini-card "Atividade ao vivo" ───────────────────────── */
function _cockpit(v) {
  const ck = v.querySelector('.ck'); if (!ck) return;
  const big = ck.querySelector('.ck-big');
  if (big) { const n = String((big.textContent || '').trim().length || 1);
             if (big.style.getPropertyValue('--n') !== n) big.style.setProperty('--n', n); }
  const sub = ck.querySelector('.ck-sub'), lead = ck.querySelector('.ck-lead');
  if (sub && lead && !lead.querySelector('.v60-desc-mais') && sub.scrollHeight > sub.clientHeight + 2) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'v60-desc-mais'; b.dataset.v60Desc = '1';
    b.setAttribute('aria-expanded', 'false'); b.textContent = 'mais';
    lead.appendChild(b);
  }
  if (!ck.querySelector('.v60-feed')) {
    const d = document.createElement('details'); d.className = 'v60-feed';
    d.innerHTML = '<summary>Atividade ao vivo · <span class="num v60-feed-n">0</span></summary>'
      + '<ul></ul><div class="v60-feed-vz">Sem eventos novos por enquanto.</div>';
    ck.appendChild(d);
    v60FeedEspelhar();
  }
}

/** Copia a janela do holofeed para o mini-card do cockpit (quando ele existe). */
export function v60FeedEspelhar() {
  const ul = $('hflist'); if (!ul) return;
  document.querySelectorAll('.v60-feed').forEach(d => {
    const n = d.querySelector('.v60-feed-n'), l = d.querySelector('ul'), z = d.querySelector('.v60-feed-vz');
    if (n) n.textContent = ul.children.length;
    if (l) l.innerHTML = ul.innerHTML;
    if (z) z.hidden = ul.children.length > 0;
  });
}

/* ── rating sem emoji ───────────────────────────────────────────────────────────────────────────
   🔴🟡🟢 (e ⚪/🟠) chegam dos renders E do servidor, em ~40 pontos. Em vez de caçar cada um, o passe
   troca o EMOJI pelo mesmo significado em forma de ponto CSS. Só mexe em nó de TEXTO (atributo e
   `onclick` ficam intactos — os filtros continuam mandando o emoji para a API).
   Emoji sozinho no nó = é o rating da linha → ponto + rótulo curto. Emoji no meio de uma frase
   (legenda da escala, "🔴 ≥50 · 🟡 25-49") → só o ponto, com `aria-label`; o texto em volta já diz
   o que cada um é, e a legenda segue explícita. */
/* classes `g-*` e não `crit`/`warn`/`ok`: `.warn` já é uma caixa de aviso da casa */
const _GRAU = {'🔴': ['g-crit', 'grave'], '🟠': ['g-warn', 'atenção'], '🟡': ['g-warn', 'atenção'],
               '🟢': ['g-ok', 'ok'], '⚪': ['g-nd', 'sem classificação']};
const _GRAU_RE = /(?:🔴|🟠|🟡|🟢|⚪)\uFE0F?/gu;
function _graus(v) {
  const w = document.createTreeWalker(v, NodeFilter.SHOW_TEXT, {acceptNode: n =>
    n.nodeValue.search(_GRAU_RE) >= 0 && n.parentElement
      && !n.parentElement.closest('script,style,textarea,option,select,code,pre,.v60-grau')
      ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT});
  const nos = []; let n; while ((n = w.nextNode())) nos.push(n);
  for (const no of nos) {
    const txt = no.nodeValue, so = txt.trim().replace(/\uFE0F/g, '');
    const frag = document.createDocumentFragment();
    if (_GRAU[so]) {                                   // rating isolado → ponto + rótulo
      const [c, r] = _GRAU[so];
      const s = document.createElement('span'); s.className = 'v60-grau ' + c;
      s.innerHTML = `<i class="v60-pt ${c}" aria-hidden="true"></i>${r}`;
      frag.appendChild(s);
    } else {                                           // dentro de frase → só o ponto
      let i = 0;
      for (const m of txt.matchAll(_GRAU_RE)) {
        if (m.index > i) frag.appendChild(document.createTextNode(txt.slice(i, m.index)));
        const [c, r] = _GRAU[m[0].replace(/\uFE0F/g, '')];
        const p = document.createElement('i'); p.className = 'v60-pt ' + c;
        p.setAttribute('role', 'img'); p.setAttribute('aria-label', r);
        frag.appendChild(p); i = m.index + m[0].length;
      }
      if (i < txt.length) frag.appendChild(document.createTextNode(txt.slice(i)));
    }
    no.parentNode.replaceChild(frag, no);
  }
}

/* ── listas ─────────────────────────────────────────────────────────────────────────────────────
   Lista = `.grid` de coluna única cujos filhos são todos cartões-linha (sem KPI, sem tabela, sem
   gráfico, sem grade dentro). Vira UM contêiner com separadores. A linha que tem `.clk` (o nome
   que abre o dossiê) fica inteira clicável — o clique é repassado ao próprio `.clk`. */
function _listas(v) {
  v.querySelectorAll('.grid:not(.g2):not(.g3):not(.g4):not(.two):not(.v60-lista):not(.v60-nl)').forEach(g => {
    const fs = [...g.children];
    const ok = fs.length >= 3 && fs.every(c => c.classList.contains('card') && !c.classList.contains('kpi'))
      && !g.querySelector('table,canvas,.grid,textarea,.chart,svg:not(.jico)')
      && fs.some(c => c.querySelector('.clk,[onclick]') || c.hasAttribute('onclick'));
    g.classList.add(ok ? 'v60-lista' : 'v60-nl');
  });
  v.querySelectorAll('.v60-lista > .card:not(.v60-abre)').forEach(c => {
    if (c.querySelector('.clk') || c.hasAttribute('onclick')) c.classList.add('v60-abre');
  });
  /* dinheiro à direita da linha fala em chama */
  v.querySelectorAll('.v60-lista .right > *:not(.v60-din)').forEach(el => {
    if (!el.children.length && /^R\$\s?[\d.]/.test((el.textContent || '').trim())) el.classList.add('v60-din');
  });
}

/* ── miúdos: "+25" da pill em mono, lupa na busca ──────────────────────────────────────────────── */
function _miudos(v) {
  v.querySelectorAll('.tag:not([data-v60])').forEach(t => {
    t.dataset.v60 = '1';
    if (t.children.length) return;
    const m = (t.textContent || '').match(/^(.*\S)\s+([+−-]\d+)$/); if (!m) return;
    t.textContent = m[1];
    const b = document.createElement('span'); b.className = 'v60-pts'; b.textContent = m[2];
    t.appendChild(b);
  });
  v.querySelectorAll('.search').forEach(b => {
    let m = b.querySelector('.mag');
    if (!m) { m = document.createElement('span'); m.className = 'mag'; m.setAttribute('aria-hidden', 'true'); b.insertBefore(m, b.firstChild); }
    if (!m.firstChild) m.innerHTML = svgIco('🔍');
  });
}

/* KPI: `--n` = caracteres do valor (cockpit), para o CSS encolher o corpo só quando o número
   exato não cabe (mesmo contrato que `kpi()` já cumpre nas outras abas). Escreve em `style`,
   que o observador não escuta — não se realimenta. */
function _kpiN(v) {
  v.querySelectorAll('.ck-inst .val').forEach(el => {
    const n = String((el.textContent || '').trim().length || 1);
    if (el.style.getPropertyValue('--n') !== n) el.style.setProperty('--n', n);
  });
  /* valor longo ganha a largura inteira no celular (classe; o observador não escuta atributo) */
  v.querySelectorAll('.card.kpi > .v, .ck-inst > .val').forEach(el => {
    const largo = (el.textContent || '').trim().length >= 17, k = el.parentElement;
    if (k.classList.contains('v60-largo') !== largo) k.classList.toggle('v60-largo', largo);
  });
}

/* cabeçalho de aba: a barra "Gerar PDF" sobe para a direita do título e a descrição ganha "mais"
   só quando de fato passa de duas linhas (medido, não presumido) */
function _capa(v) {
  const cv = v.querySelector('.cover'); if (!cv || cv.dataset.v60) return;
  cv.dataset.v60 = '1';
  const row = cv.querySelector('.cover-row'), nx = cv.nextElementSibling;
  if (row && nx && nx.classList.contains('btns') && nx.querySelector('[onclick^="gerarPdfIntel"]')) {
    nx.classList.add('cover-acts'); nx.removeAttribute('style'); row.appendChild(nx);
  }
  const s = cv.querySelector('.s'), tx = cv.querySelector('.cover-tx');
  if (s && tx && s.scrollHeight > s.clientHeight + 2) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'v60-desc-mais'; b.dataset.v60Desc = '1';
    b.setAttribute('aria-expanded', 'false'); b.textContent = 'mais';
    tx.appendChild(b);
  }
}

/* ── cabeçalho: gatilho "⋯" (celular) e ações como botão-ícone (desktop) ───────────────────────
   As quatro ações continuam sendo os MESMOS elementos e as MESMAS funções; só ganham ícone (do set
   da casa) e rótulo acessível. O som não tem glifo no set — fica com o ponto de estado + o texto. */
/* v61: glifos próprios (`_ICO_V61` em `nucleo/dom.js`) no lugar dos emprestados */
const _IC = {termos: _v61 ? '§v61-termos' : '§info', controle: _v61 ? '§v61-controle' : '🔧', sair: _v61 ? '§v61-sair' : '🚪',
             atividade: _v61 ? '§v61-atividade' : '§sweep'};
const _ACOES = [
  ['a.help:not(.som)', _IC.termos, 'Termos — o que cada conceito do painel significa'],
  ['a.ctrl', _IC.controle, 'Controle do sistema'],
  ['a.sair', _IC.sair, 'Sair'],
];
function _acoes() {
  const box = document.querySelector('.htop .actions'); if (!box) return;
  for (const [sel, ico, dica] of _ACOES) {
    const a = box.querySelector(sel); if (!a || a.querySelector('.v60-ic')) continue;
    const txt = a.textContent.trim();
    a.innerHTML = `<span class="v60-ic" aria-hidden="true">${svgIco(ico)}</span><span class="v60-tx">${txt}</span>`;
    a.title = dica; a.setAttribute("aria-label", txt);
  }
  const b = document.createElement('button');
  b.type = 'button'; b.className = 'v60-mais'; b.id = 'v60-mais';
  b.title = 'Mais ações'; b.setAttribute('aria-label', 'Mais ações'); b.setAttribute('aria-haspopup', 'menu');
  b.innerHTML = '<i aria-hidden="true"></i>';
  b.addEventListener('click', v60Mais);
  box.appendChild(b);
}

/** O menu "⋯": as quatro ações do cabeçalho + a atividade ao vivo, em linhas de 48px no #sheet. */
export function v60Mais() {
  const ov = $('ov'), sh = $('sheet'); if (!ov || !sh) return;
  const som = document.querySelector('.htop [data-som]');
  const ligado = !!(som && som.classList.contains('on'));
  sh.innerHTML = `<span class="x" onclick="fecharDossie()">✕ fechar</span><div class="grab"></div>
   <div class="v60-menu">
    <button type="button" class="v60-mi${ligado ? ' on' : ''}" data-som aria-pressed="${ligado}"><span class="v60-ic" aria-hidden="true"><i class="som-d"></i></span><span class="som-t">${ligado ? 'Som' : 'Mudo'}</span><small>som de interface</small></button>
    <button type="button" class="v60-mi" onclick="glossario()"><span class="v60-ic" aria-hidden="true">${svgIco(_IC.termos)}</span>Termos<small>o que cada conceito significa</small></button>
    <button type="button" class="v60-mi" data-v60-feed><span class="v60-ic" aria-hidden="true">${svgIco(_IC.atividade)}</span>Atividade ao vivo<small>últimos eventos</small></button>
    ${v61TemaItem()}
    <a class="v60-mi" href="/controle"><span class="v60-ic" aria-hidden="true">${svgIco(_IC.controle)}</span>Controle</a>
    <a class="v60-mi" href="/logout_jfn"><span class="v60-ic" aria-hidden="true">${svgIco(_IC.sair)}</span>Sair</a>
   </div>`;
  ov.classList.add('on');
}

/* ── holofeed recolhido: o título vira "Ao vivo · N" e abre/fecha a lista ──────────────────────
   N é a contagem REAL de linhas na janela do feed (teto de 10, definido em `barramento/sabre.js`);
   sem evento, N = 0 e a lista aberta diz o silêncio honesto de sempre. */
function _feed() {
  const hf = $('holofeed'), ul = $('hflist'); if (!hf || !ul) return;
  hf.classList.remove('open');
  const t = hf.querySelector('.hf-t'); if (!t) return;
  for (const n of [...t.childNodes]) if (n.nodeType === 3) n.remove();
  const lab = document.createElement("span");
  lab.innerHTML = 'Ao vivo · <span id="v60-hfn" class="num">0</span>';
  t.insertBefore(lab, $('hfload'));
  t.setAttribute('role', 'button'); t.tabIndex = 0;
  t.title = 'Eventos recentes do barramento (janela das últimas 10 linhas) — clique para abrir ou recolher';
  const pinta = () => { const n = $('v60-hfn'); if (n) n.textContent = ul.children.length;
                        t.setAttribute('aria-expanded', hf.classList.contains('open') ? 'true' : 'false'); };
  const alterna = () => { hf.classList.toggle('open'); pinta(); };
  t.addEventListener('click', alterna);
  t.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); alterna(); } });
  new MutationObserver(() => { pinta(); v60FeedEspelhar(); }).observe(ul, {childList: true});
  pinta();
  /* item "Atividade ao vivo" do menu "⋯" — delegado: o #sheet troca de innerHTML a cada abertura */
  document.addEventListener('click', e => {
    if (!(e.target && e.target.closest && e.target.closest('[data-v60-feed]'))) return;
    $('ov').classList.remove('on'); hf.classList.add('open'); pinta();
  });
}
