/* O10.1 item 7 (25/11/2026) — EM MANUTENÇÃO, CONTROLE DE ESCRITA NÃO É CLICÁVEL.
 *
 * Com `JFN_MANUTENCAO=1` (parada de obras, O0.7) o servidor responde 503 a todo POST/PUT/PATCH/DELETE
 * (`server._manutencao`) e injeta no HTML a faixa `#jfn-manutencao` ("Em manutenção — dados congelados em <data>").
 * A auditoria O10.1 achou "Rodar", "Gerar", "Enfileirar missão", "Pausar/Retomar"… ativos: o clique falhava com 503
 * sem explicação (H5/H9). O sinal para o front É a própria faixa — sem rota nova, sem tocar no servidor.
 *
 * O que trava: só o que ESCREVE (método ≠ GET) — a lista `ESCRITA` abaixo, conferida contra cada `method:'POST'` do
 * fonte (grep, 25/11/2026). Leitura continua viva: "Rodar" de Detectores é GET (só lê), "Gerar PDF" e "Gerar de novo"
 * da Comissão são GET e o middleware os deixa passar — travá-los seria dizer "em manutenção" sobre o que funciona.
 * Defesa em profundidade: `J()` recusa escrita em manutenção sem ir à rede (o Enter de um campo não passa batido).
 * Módulo sem efeito de topo; liga pela sequência de boot (`ligarManutencao()`).
 */

let _estado;   // undefined = não lido; null = fora de manutenção

/** {desde, motivo} se o painel está em manutenção; null se não. A faixa nasce no HTML, antes do bundle. */
export function manutencao() {
  if (_estado !== undefined) return _estado;
  const f = typeof document !== 'undefined' && document.getElementById('jfn-manutencao');
  if (!f) { _estado = null; return _estado; }
  const desde = ((f.textContent || '').match(/congelados em\s+(.+?)\s*$/) || [])[1] || 'data não informada';
  _estado = {desde, motivo: `em manutenção — dados congelados em ${desde}`};
  return _estado;
}

/* Controles que disparam escrita (POST). Cada linha aponta a função que faz o POST. */
export const ESCRITA = [
  '[onclick*="pecaGerar("]',                       // g_pecas      → pecaGerar        POST <rota da peça>
  '[onclick*="instAcionar("][onclick*="POST"]',    // g_instr      → instAcionar      POST /api/siafe/…, /api/radar/…
  '[onclick*="missaoCriar("]',                     // g_missoes    → missaoCriar      POST /api/hermes/missoes
  '[onclick^="sweep("]',                           // g_sweeps     → sweep            POST /api/sweeps/<a>
  '[onclick^="validar("]',                         // g_validar    → validar          POST /api/fachada/veredito
  '[onclick^="acao("]',                            // g_acoes      → acao             POST /api/relatorio/…, /api/dossie
  '[onclick*="seiArvore("]',                       // dossiê       → seiArvore        POST /api/sei/empresa/iniciar
  '[data-lai="gerar"]', '[data-lai="alvo"]',       // LAI          → laiGerar         POST /api/lai/gerar
  '[data-lai="status"]',                           // LAI          → laiStatus        POST /api/lai/status
  '[data-acervo="acao"]',                          // g_acervo     → acervoAcao       POST <rota da ação>
].join(',');

const _NOTA = 'manut-motivo';

/** Desabilita, com o motivo, todo controle de escrita dentro de `raiz`. Idempotente. Devolve quantos travou. */
export function travarEscritas(raiz) {
  const m = manutencao(); if (!m || !raiz || !raiz.querySelectorAll) return 0;
  let n = 0;
  for (const el of raiz.querySelectorAll(ESCRITA)) {
    if (el.dataset.manut) continue;
    el.dataset.manut = '1'; n++;
    if ('disabled' in el) el.disabled = true;
    el.setAttribute('aria-disabled', 'true');
    el.title = m.motivo;
    /* o motivo VISÍVEL, uma vez por grupo (no toque não há `title`) */
    const grupo = el.closest('.btns') || el.closest('table') || el.parentElement;
    if (grupo && !grupo.dataset.manutNota) {
      grupo.dataset.manutNota = '1';
      const nota = `<span class="dim ${_NOTA}" role="note" style="display:block;margin-top:6px">${m.motivo.replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]))}</span>`;
      grupo.insertAdjacentHTML(grupo.tagName === 'TABLE' ? 'beforebegin' : 'beforeend', nota);
    }
  }
  return n;
}

let _ligado = false;
/** Liga a trava: passa no documento agora e a cada troca de conteúdo (`#view`, dossiê, gavetas). */
export function ligarManutencao() {
  if (_ligado || !manutencao()) return; _ligado = true;
  travarEscritas(document);
  let pend = false;
  new MutationObserver(() => {
    if (pend) return; pend = true;
    requestAnimationFrame(() => { pend = false; travarEscritas(document); });
  }).observe(document.body, {childList: true, subtree: true});
  /* `<a role=button>` não tem `disabled`: o clique em controle travado para aqui (fase de captura) */
  document.addEventListener('click', ev => {
    const el = ev.target && ev.target.closest && ev.target.closest('[data-manut]');
    if (el) { ev.preventDefault(); ev.stopImmediatePropagation(); }
  }, true);
}
