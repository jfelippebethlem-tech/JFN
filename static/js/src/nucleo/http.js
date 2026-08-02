/* O cliente HTTP do painel — e a tradução de falha para linguagem de auditor.
 *
 * As duas coisas vivem juntas de propósito: `erroHumano` só existe para traduzir o que o `J`
 * devolve quando dá errado. Separá-las deixaria a tradução órfã do contrato que ela traduz.
 */
import {esc} from './dom.js';

// 1 retry (só GET) — rede/DB ocupado num instante não pode virar aba "zerada" pro usuário.
// + cache de navegação (TTL 90s, só GET): voltar numa aba já vista abre INSTANTÂNEO sem perder
// informação — o dado expira sozinho e re-busca. Fora do cache: SSE e os status de polling.
export const _jCache = new Map();

export async function J(ep, opt) {
  const isGet = !opt || !opt.method || opt.method === 'GET';
  const cacheavel = isGet && !/\/stream|\/status|\/api\/eventos/.test(ep);
  if (cacheavel) { const c = _jCache.get(ep); if (c && Date.now() - c.t < 90000) return c.d; }
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
      const d = await r.json();
      if (cacheavel && d && d.ok !== false) _jCache.set(ep, {t: Date.now(), d});
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
