/* O7.3 · MANCHETE SÓ TIER 1 — a catraca do registro (`manchete_efetiva`) aplicada NA TELA.
 *
 * Fonte: `/api/manchetes/estado` (compliance_agent/qualidade/manchete_painel.py) — para cada superfície do
 * inventário (`config/qualidade_inventario.yaml`, `manchetes`) diz se o número pode ir para a capa: medição do
 * próprio sistema (detector null) sim; número de detector só com `manchete_efetiva` (manchete declarada E Tier 1,
 * calculado hoje). Para os Sinais críticos, o mesmo vale por detector (`detectores`).
 *
 * FALHA FECHADA: enquanto o estado não chegou, ou se a rota falhar, NADA que é gated vira manchete — a superfície
 * mostra "estado de calibração indisponível" com o motivo. Nunca uma manchete por omissão, nunca vazio silencioso.
 *
 * Quem usa: o cockpit (herói + cartões + chips da mesa), o Início v63 (números), os Sinais críticos, a capa de
 * Alertas e o dossiê. `manchete_painel` + este módulo = o único lugar que decide.
 */
import {J, erroHumano} from '../nucleo/http.js';
import {esc} from '../nucleo/dom.js';
import {fmtN} from '../nucleo/formato.js';

let _estado = null, _prom = null;

/** Lê o estado uma vez por carga (o registro muda por commit, não por minuto). */
export function mancheteEstado() {
  if (!_prom) _prom = J('/api/manchetes/estado', {tetoMs: 20000}).then(d => {
    _estado = d && d.ok ? d : {ok: false, erro: (d && d.erro) || 'sem resposta'};
    return _estado;
  });
  return _prom;
}

function _sup(id) { return _estado && _estado.ok ? (_estado.superficies || []).find(s => s.id === id) : null; }

/** A superfície `id` (id do inventário) pode exibir o número como manchete? Falha fechada. */
export function mancheteLiberada(id) { const s = _sup(id); return !!(s && s.liberada); }

/** O detector `det` (id do registro) pode virar manchete? Fora do registro ou sem estado: não. */
export function detectorLiberado(det) {
  const d = _estado && _estado.ok && _estado.detectores ? _estado.detectores[det] : null;
  return !!(d && d.manchete_efetiva);
}

/** Frase curta do porquê (para o cartão bloqueado). */
export function mancheteMotivo(id) {
  if (!_estado) return 'lendo o estado de calibração…';
  if (!_estado.ok) return 'estado de calibração INDISPONÍVEL — nenhuma manchete de detector é exibida';
  const s = _sup(id);
  if (!s) return 'superfície fora do inventário de manchetes — não é exibida como manchete';
  return s.motivo || '';
}

export function detectorMotivo(det) {
  if (!_estado || !_estado.ok) return 'estado de calibração INDISPONÍVEL';
  const d = (_estado.detectores || {})[det];
  if (!d) return `${det}: fora do registro de detectores — não é manchete`;
  return `${det}: Tier ${d.tier ?? '—'} (${d.tier_motivo || ''}) — não é manchete`;
}

/** Conteúdo do cartão bloqueado: sem o número; o motivo e para onde o dado foi. */
export function mancheteBloqueioHtml(id, ondeEsta) {
  return `<span class="mch-bloq"><b>não é manchete</b> — ${esc(mancheteMotivo(id))}${ondeEsta ? ` · ${esc(ondeEsta)}` : ''}</span>`;
}

/** O painel "nenhuma manchete calibrada" (ou a lista das calibradas) — topo do Início. Nunca vazio. */
export function mancheteAvisoHtml() {
  if (!_estado) return `<div class="mch-aviso" id="mch-aviso" role="status"><b>Manchetes</b> · lendo o estado de calibração…</div>`;
  if (!_estado.ok) return `<div class="mch-aviso mch-indisp" id="mch-aviso" role="status"><b>Manchetes: estado de calibração INDISPONÍVEL.</b>
    Sem ele, nenhum número de detector vai para a capa (falha fechada). ${erroHumano(_estado.erro)}</div>`;
  const e = _estado, pt = e.por_tier || {};
  const efet = e.manchetes_efetivas || [];
  const bloq = (e.superficies || []).filter(s => s.detector && !s.liberada);
  const titulo = efet.length ? `${fmtN(efet.length)} manchete(s) calibrada(s) (Tier 1)` : 'Nenhuma manchete calibrada';
  return `<div class="mch-aviso${efet.length ? '' : ' mch-zero'}" id="mch-aviso" role="status">
    <div class="mch-t"><b>${titulo}</b> <span class="mch-tiers">Tier 1: ${fmtN(pt['1'] || 0)} · Tier 2: ${fmtN(pt['2'] || 0)} · Tier 3: ${fmtN(pt['3'] || 0)} de ${fmtN(e.n_detectores)} detectores</span></div>
    <p>${esc(e.explicacao)}</p>
    <details><summary>Por que cada número saiu da capa (${fmtN(bloq.length)})</summary>
      <ul>${bloq.map(s => `<li><b>${esc(s.superficie || s.id)}</b>: ${esc(s.motivo)}</li>`).join('')}</ul>
      <p class="mch-regra">${esc(e.explica_tier1)}</p></details>
  </div>`;
}
