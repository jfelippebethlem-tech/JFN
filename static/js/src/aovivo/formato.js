/* AO VIVO — como um motor é DITO na tela. Folha pura (não importa nada, não toca o DOM): a
 * abertura, o ticker, os cartões de Motores e o reator dizem o estado com as MESMAS palavras.
 *
 * Contrato de `/api/ao-vivo/estado` (router `compliance_agent/aovivo/api.py`):
 *   motor = {id, nome, estado: 'rodando'|'ocioso'|'agendado'|'falhou'|'indisponivel', efeito: {ultimo, horas, parado}|null,
 *            desde: ISO|null, proxima: ISO|null, progresso: 0..1|null, ultimo_evento: {t, texto}|null}
 */

/** "há 2h", "há 12 min", "há 3 d" — sem data → '' (nunca inventa). */
export function haQuanto(iso, agora = Date.now()) {
  const t = iso ? Date.parse(iso) : NaN; if (!isFinite(t)) return '';
  const s = Math.max(0, (agora - t) / 1000);
  if (s < 90) return 'há instantes';
  if (s < 3600) return `há ${Math.round(s / 60)} min`;
  if (s < 86400) return `há ${Math.round(s / 3600)}h`;
  return `há ${Math.round(s / 86400)} d`;
}

/** "03:00" se for hoje; "12/11 03:00" se for outro dia; sem data → ''. */
export function quando(iso, agora = new Date()) {
  const d = iso ? new Date(iso) : null; if (!d || isNaN(d)) return '';
  const p = n => String(n).padStart(2, '0'), hm = `${p(d.getHours())}:${p(d.getMinutes())}`;
  return d.toDateString() === agora.toDateString() ? hm : `${p(d.getDate())}/${p(d.getMonth() + 1)} ${hm}`;
}

/** Rótulo humano do estado: "rodando · 99%", "agendado · próx. 03:00", "falhou há 2h". */
export function rotuloEstado(m) {
  if (!m) return 'INDISPONÍVEL';
  const r = _rotuloBase(m);
  /* SINAL DE EFEITO (11/11/2026): systemd diz "rodando", mas o produto não avança — o bombeiros relia os
     mesmos processos há 48 h e a tela o pintava de verde. O rótulo diz as DUAS coisas. */
  return semEfeito(m) ? `${r} · sem efeito há ${Math.round(m.efeito.horas)}h` : r;
}
/** O motor roda mas o que ele produz parou (`efeito.parado` do `motores.yaml`). */
export function semEfeito(m) { return !!(m && m.efeito && m.efeito.parado && typeof m.efeito.horas === 'number'); }
function _rotuloBase(m) {
  if (m.estado === 'rodando') return 'rodando' + (typeof m.progresso === 'number' ? ` · ${Math.round(m.progresso * 100)}%` : '');
  if (m.estado === 'falhou') { const h = haQuanto(m.desde); return 'falhou' + (h ? ' ' + h : ''); }
  if (m.estado === 'agendado') { const q = quando(m.proxima); return 'agendado' + (q ? ` · próx. ${q}` : ''); }
  if (m.estado === 'ocioso') return 'ocioso';
  return 'INDISPONÍVEL';
}

/** Lê o snapshot. Falha de rede/401/JSON torto → null (quem chama escreve INDISPONÍVEL). */
export async function lerEstado(ms = 4000) {
  const c = new AbortController(), t = setTimeout(() => c.abort(), ms);
  try {
    const r = await fetch('/api/ao-vivo/estado', {credentials: 'same-origin', signal: c.signal});
    if (!r.ok) return null;
    const j = await r.json();
    return j && Array.isArray(j.motores) ? j : null;
  } catch (_) { return null; } finally { clearTimeout(t); }
}
