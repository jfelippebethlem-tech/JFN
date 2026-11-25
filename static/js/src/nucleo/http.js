/* O cliente HTTP do painel — e a tradução de falha para linguagem de auditor.
 *
 * As duas coisas vivem juntas de propósito: `erroHumano` só existe para traduzir o que o `J`
 * devolve quando dá errado. Separá-las deixaria a tradução órfã do contrato que ela traduz.
 */
import {esc, card} from './dom.js';
import {manutencao} from './manutencao.js';

// 1 retry (só GET) — rede/DB ocupado num instante não pode virar aba "zerada" pro usuário.
// + cache de navegação (TTL 90s, só GET): voltar numa aba já vista abre INSTANTÂNEO sem perder
// informação — o dado expira sozinho e re-busca. Fora do cache: SSE e os status de polling.
export const _jCache = new Map();

/* O7.2 · LENTE GLOBAL (config/lentes.yaml). Escolhida no seletor do cabeçalho (`ui/lente.js`), ela vai como
   `lente=<nome>` em toda consulta de DADO do painel. A rota que recortou responde com o cabeçalho
   `X-JFN-Lente: <nome>`; a que não recortou (ainda sem recorte por lente) responde sem ele — e o painel CONTA as
   duas por aba e diz na faixa da lente, nunca um "filtrado" que não foi. Rotas de sistema (motores, frescor,
   estado de calibração, catálogo de lentes) não recebem a lente: não são dado de órgão. Quem já pede `lente=`
   (a aba Lentes de detecção, `/api/lentes?lente=…`) mantém o seu — o parâmetro explícito nunca é sobrescrito. */
let _lente = null;
/* `/api/lentes` é a aba Lentes de DETECÇÃO (08/2026): lá `lente=` é outra coisa (convergencia, hhi…) e o nome de
   uma lente de órgão viraria "lente desconhecida" — ela fica fora, como as rotas de sistema. */
const _LENTE_FORA = /^\/(status|api\/(ao-vivo|sistema|eventos|fontes|manchetes|esteira\/lentes|qualidade|territorio|lentes(?=[?\/]|$)))/;
export const lenteUso = {aplicada: [], nao_aplicada: []};
export function lenteAtual() { return _lente; }
export function lenteDefinir(nome) { _lente = nome || null; lenteUso.aplicada = []; lenteUso.nao_aplicada = []; }
export function lenteNovaAba() { lenteUso.aplicada = []; lenteUso.nao_aplicada = []; }
function _comLente(ep) {
  if (!_lente || !/^\/(api\/|status)/.test(ep) || _LENTE_FORA.test(ep) || /[?&]lente=/.test(ep)) return null;
  return ep + (ep.includes('?') ? '&' : '?') + 'lente=' + encodeURIComponent(_lente);
}
function _registrarLente(ep, aplicou) {
  const rota = ep.split('?')[0], lista = aplicou ? lenteUso.aplicada : lenteUso.nao_aplicada;
  if (!lista.includes(rota)) lista.push(rota);
  document.dispatchEvent(new CustomEvent('jfn-lente-uso'));
}

export async function J(ep0, opt) {
  const isGet = !opt || !opt.method || opt.method === 'GET';
  /* O10.1: em manutenção o servidor responde 503 a toda escrita — recusa aqui, com o motivo, sem ir à rede */
  const _m = !isGet && opt.method !== 'HEAD' ? manutencao() : null;
  if (_m) return {ok: false, manutencao: true, erro: _m.motivo};
  const _ep = isGet ? _comLente(ep0) : null, ep = _ep || ep0;
  const cacheavel = isGet && !/\/stream|\/status|\/api\/eventos/.test(ep);
  if (cacheavel) { const c = _jCache.get(ep); if (c && Date.now() - c.t < 90000) { if (_ep) _registrarLente(ep0, c.l); return c.d; } }
  /* TETO DE ESPERA: `fetch` sem AbortController espera para SEMPRE. Uma rota lenta não
     virava erro — virava um card parado em "—" sem explicação nenhuma, indistinguível de
     "não há dado". Foi assim que o "ninhos de fachada" ficou mudo. Agora estoura em 30 s
     e vira mensagem humana, que é honesto: INDISPONÍVEL ≠ 0, mas silêncio ≠ INDISPONÍVEL. */
  const TETO = (opt && opt.tetoMs) || 30000;
  for (let t = 0; ; t++) {
    const ac = ('AbortController' in window) ? new AbortController() : null;
    const relogio = ac ? setTimeout(() => ac.abort(), TETO) : 0;
    try {
      const r = await fetch(ep, ac ? Object.assign({}, opt, {signal: ac.signal}) : opt);
      const aplicou = !!_ep && r.headers.get('X-JFN-Lente') === _lente;
      if (_ep) _registrarLente(ep0, aplicou);
      const d = await r.json();
      if (cacheavel && d && d.ok !== false) _jCache.set(ep, {t: Date.now(), d, l: aplicou});
      return d;
    } catch (e) {
      const estourou = e && e.name === 'AbortError';
      if (!isGet || t >= 1) return {erro: estourou ? `a rota ${ep} não respondeu em ${TETO / 1000}s` : String(e)};
      await new Promise(rs => setTimeout(rs, 1200));
    } finally { if (relogio) clearTimeout(relogio); }
  }
}

// Erro de rede NUNCA chega cru ao usuário (era `TypeError: Failed to fetch` na tela).
/* v60: rodando o painel SEM os bancos (laboratório no desktop) apareceram 17 telas
   despejando erro cru de SQLite — "no such table: pncp_resultado" e mais cinco nomes de
   tabela interna. O culpado era o `else if` final: ele existe para deixar passar mensagem
   de NEGÓCIO da API, e acabava deixando passar mensagem de ESQUEMA também. Duas coisas
   erradas de uma vez: o auditor não entende, e o nome da tabela é detalhe interno que não
   tem por que estar na tela. Agora o erro técnico vira frase de FONTE (o que falta coletar),
   com o texto original preservado no title para quem for investigar. */
const _FONTE_TABELA = {
  pncp_resultado: 'PNCP — resultados de licitação', ob_orcamentaria_siafe: 'SIAFE — ordens bancárias',
  ordens_bancarias: 'TFE — ordens bancárias', pcrj_contratos: 'Prefeitura do Rio — contratos',
  sancoes_federais: 'CEIS/CNEP — sanções', edital_documento: 'editais coletados',
  socios_receita: 'Receita Federal — quadro societário',
};

export function erroHumano(e) {
  const s = String(e || '');
  const tec = /no such table|no such column|OperationalError|DatabaseError|IntegrityError|disk image is malformed|database is locked|sqlite3|Traceback/i.test(s);
  let msg = 'Este dado não respondeu agora.';
  if (/failed to fetch|networkerror|load failed/i.test(s)) msg = 'Sem resposta do servidor — a VM pode estar ocupada com um sweep.';
  else if (/timeout|timed out/i.test(s)) msg = 'O servidor demorou demais para responder.';
  else if (/json|unexpected token/i.test(s)) msg = 'O servidor respondeu em formato inesperado.';
  else if (tec) {
    const t = (s.match(/no such table:\s*([a-z0-9_]+)/i) || [])[1];
    const fonte = t && _FONTE_TABELA[t];
    msg = fonte ? `A fonte <b>${esc(fonte)}</b> ainda não foi coletada neste ambiente.`
                : 'A base que alimenta esta tela ainda não foi coletada neste ambiente.';
    msg += ' <span class="dim">INDISPONÍVEL não é zero — a tela não está dizendo que não há nada, e sim que não tem como saber.</span>';
  }
  else if (s && !/^indispon/i.test(s)) msg = esc(s);   // mensagem de negócio vinda da API passa direto
  const det = tec ? ` title="${esc(s).slice(0, 220)}"` : '';
  // `_jCache` e `ir`/`aba` são citados por NOME dentro do onclick: handler inline resolve no
  // escopo global, que a ponte alimenta. Import aqui não serviria para nada.
  return `<span${det}>${msg}</span> <button class="btn ghost v10retry" onclick="_jCache.clear();ir(aba)">↻ Tentar de novo</button>`;
}

/* O cartão de falha de TODA tela — a mesma moldura em volta do `erroHumano`. Era escrito à mão
   (`card(`<div class="warn">${erroHumano(d.erro)}</div>`)`) 82 vezes em 15 módulos. */
export const cardErro = e => card(`<div class="warn">${erroHumano(e)}</div>`);
