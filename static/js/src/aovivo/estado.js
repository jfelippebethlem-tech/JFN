/* AO VIVO — o estado dos motores e o fio de eventos, num lugar só.
 *
 * Fonte: `/api/ao-vivo/estado` (snapshot) e `/api/ao-vivo/stream` (SSE; o navegador reconecta
 * sozinho e reenvia `Last-Event-ID`). Só leitura: aqui não existe botão de ligar/desligar motor.
 *
 * TRÊS VERDADES DISTINTAS, e a tela tem de dizer qual vale:
 *   disponivel === null   ainda não se sabe (primeira leitura em curso)
 *   disponivel === false  a API não respondeu → "INDISPONÍVEL" (≠ zero motores)
 *   conectado === false   já houve dado, o fio caiu → "ao vivo pausado · reconectando"
 * Nada aqui inventa evento: sem fio, a lista para onde parou.
 */
import {lerEstado} from './formato.js';

export const aoVivo = {motores: [], eventos: [], disponivel: null, conectado: false, atualizadoEm: null,
                       fontes: null};
const _ouv = new Set();
const JANELA = 5 * 60 * 1000, TETO = 120;
let _ligado = false, _es = null, _poll = 0;

/** Ouve mudanças: `fn(tipo, dado)` com tipo 'estado' | 'evento' | 'fio'. Devolve o cancelador. */
export function aoVivoOuvir(fn) { _ouv.add(fn); return () => _ouv.delete(fn); }
function _avisa(tipo, dado) { for (const fn of [..._ouv]) { try { fn(tipo, dado); } catch (_) {} } }

/** Eventos por minuto, média móvel de 5 min — só dos eventos que de fato chegaram. */
export function eventosPorMinuto(motor) {
  const de = Date.now() - JANELA;
  let n = 0;
  for (const e of aoVivo.eventos) if (e._ms >= de && (!motor || e.motor === motor)) n++;
  return n / 5;
}
/* só a classe `motor` (coleta/análise): serviço de apoio sempre ligado não acelera o reator */
export const motoresRodando = () => aoVivo.motores.filter(m => m.estado === 'rodando' && m.classe !== 'infra');

function _snapshot(j) {
  if (!j) { if (aoVivo.disponivel === null) aoVivo.disponivel = false; _avisa('estado'); return; }
  aoVivo.disponivel = true; aoVivo.motores = j.motores; aoVivo.atualizadoEm = j.atualizado_em || null;
  aoVivo.fontes = j.fontes || null;
  if (Array.isArray(j.eventos)) for (const e of j.eventos) _entra(e, false);
  _avisa('estado');
}
function _entra(e, avisar) {
  if (!e || !e.id || aoVivo.eventos.some(x => x.id === e.id)) return;
  e._ms = Date.parse(e.t) || Date.now();
  aoVivo.eventos.push(e); aoVivo.eventos.sort((a, b) => a._ms - b._ms);
  if (aoVivo.eventos.length > TETO) aoVivo.eventos.splice(0, aoVivo.eventos.length - TETO);
  if (avisar) _avisa('evento', e);
}
function _fio(ok) { if (aoVivo.conectado !== ok) { aoVivo.conectado = ok; _avisa('fio', ok); } }

/** Liga uma vez por carga de página. Idempotente. */
export function aoVivoLigar() {
  if (_ligado) return; _ligado = true;
  lerEstado().then(_snapshot);
  const abrir = () => {
    if (!window.EventSource || _es) return;
    try { _es = new EventSource('/api/ao-vivo/stream'); } catch (_) { _es = null; return; }
    _es.addEventListener('open', () => _fio(true));
    _es.addEventListener('estado', ev => { try { _snapshot(JSON.parse(ev.data)); _fio(true); } catch (_) {} });
    _es.addEventListener('evento', ev => { try { _entra(JSON.parse(ev.data), true); _fio(true); } catch (_) {} });
    /* erro: o EventSource tenta de novo sozinho (readyState 0). Se FECHOU (2 — ex.: 404/401, rota
       ainda não publicada), não insiste a cada segundo: a leitura por snapshot abaixo cobre. */
    _es.addEventListener('error', () => { _fio(false); if (_es && _es.readyState === 2) { _es = null; } });
  };
  abrir();
  /* rede de segurança: sem fio, o snapshot é relido a cada 30 s (e tenta reabrir o fio) */
  _poll = setInterval(() => {
    if (document.hidden || aoVivo.conectado) return;
    lerEstado().then(j => { _snapshot(j); if (j) abrir(); });
  }, 30000);
}
