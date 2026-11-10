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
import {_v60} from '../capacidade/estado.js';

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
let _passe = 0;
function _observar() {
  const v = $('view'); if (!v) return;
  new MutationObserver(() => { clearTimeout(_passe); _passe = setTimeout(() => v60Vivo(v), 60); })
    .observe(v, {childList: true, subtree: true});
  /* "mais"/"menos" da descrição do cabeçalho de aba — delegado */
  document.addEventListener('click', e => {
    const b = e.target && e.target.closest && e.target.closest('[data-v60-desc]'); if (!b) return;
    const cv = b.closest('.cover'); if (!cv) return;
    const ab = cv.classList.toggle('v60-aberta');
    b.textContent = ab ? 'menos' : 'mais'; b.setAttribute('aria-expanded', ab ? 'true' : 'false');
  });
  v60Vivo(v);
}

export function v60Vivo(v) {
  if (!_v60 || !v) return;
  _capa(v);
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
const _ACOES = [
  ['a.help:not(.som)', '§info', 'Termos — o que cada conceito do painel significa'],
  ['a.ctrl', '🔧', 'Controle do sistema'],
  ['a.sair', '🚪', 'Sair'],
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
    <button type="button" class="v60-mi" onclick="glossario()"><span class="v60-ic" aria-hidden="true">${svgIco('§info')}</span>Termos<small>o que cada conceito significa</small></button>
    <button type="button" class="v60-mi" data-v60-feed><span class="v60-ic" aria-hidden="true">${svgIco('§sweep')}</span>Atividade ao vivo<small>últimos eventos</small></button>
    <a class="v60-mi" href="/controle"><span class="v60-ic" aria-hidden="true">${svgIco('🔧')}</span>Controle</a>
    <a class="v60-mi" href="/logout_jfn"><span class="v60-ic" aria-hidden="true">${svgIco('🚪')}</span>Sair</a>
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
  new MutationObserver(pinta).observe(ul, {childList: true});
  pinta();
  /* item "Atividade ao vivo" do menu "⋯" — delegado: o #sheet troca de innerHTML a cada abertura */
  document.addEventListener('click', e => {
    if (!(e.target && e.target.closest && e.target.closest('[data-v60-feed]'))) return;
    $('ov').classList.remove('on'); hf.classList.add('open'); pinta();
  });
}
