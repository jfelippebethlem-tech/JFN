/* AO VIVO — a interface dos motores (v61). O estado mora em `aovivo/estado.js`; aqui é só tela. */
import {$, esc} from '../nucleo/dom.js';
import {aoVivo, aoVivoLigar, aoVivoOuvir, motoresRodando} from '../aovivo/estado.js';
import {rotuloEstado, quando, haQuanto} from '../aovivo/formato.js';

/** Cartão de UM motor na folha (toque no nó em órbita, no cartão da grade ou no ticker). */
export function abrirMotor(id) {
  const m = aoVivo.motores.find(x => x.id === id), ov = $('ov'), sh = $('sheet');
  if (!m || !ov || !sh) return;
  const evs = aoVivo.eventos.filter(e => e.motor === id).slice(-8).reverse();
  const linha = (r, v) => v ? `<div class="mt-l"><span>${r}</span><b>${esc(v)}</b></div>` : '';
  sh.innerHTML = `<span class="x" onclick="fecharDossie()">✕ fechar</span><div class="grab"></div>
    <div class="mt-ficha e-${esc(m.estado)}">
      <h3 class="v61-disp"><i class="mt-pt" aria-hidden="true"></i>${esc(m.nome)}</h3>
      <div class="mt-estado">${esc(rotuloEstado(m))}</div>
      ${typeof m.progresso === 'number' ? `<div class="mt-barra" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(m.progresso * 100)}"><i style="width:${Math.round(m.progresso * 100)}%"></i></div>` : ''}
      ${linha('O que faz', m.descricao)}
      ${linha('Desde', m.desde ? `${quando(m.desde)} (${haQuanto(m.desde)})` : '')}
      ${linha('Próxima execução', quando(m.proxima))}
      ${linha('Unidade', m.unidade)}
      ${linha('Último código de saída', m.saida == null ? '' : String(m.saida))}
      <h4>Últimos eventos</h4>
      ${evs.length ? `<ul class="mt-evs">${evs.map(e => `<li><span class="num">${esc(quando(e.t))}</span>${esc(e.texto)}</li>`).join('')}</ul>`
                   : '<div class="dim">Sem evento registrado nesta janela.</div>'}
    </div>`;
  ov.classList.add('on');
}

const _hm = iso => { const d = iso ? new Date(iso) : null; if (!d || isNaN(d)) return '';
  const p = n => String(n).padStart(2, '0'); return `${p(d.getHours())}:${p(d.getMinutes())}`; };
const _nome = id => (aoVivo.motores.find(m => m.id === id) || {}).nome || id;

/* ── TICKER: faixa de 28px sob o cabeçalho, em todas as abas ─────────────────────────────────────
   Os eventos entram pela direita (o mais novo é o último à direita). Toque = pausa e abre o
   histórico. Sem dado, a faixa DIZ o porquê — nunca fica vazia fingindo normalidade. */
let _pausado = false;
export function tickerMontar() {
  if ($('v61-ticker')) return;
  const cab = document.querySelector('.wrap > header'); if (!cab) return;
  const t = document.createElement('div');
  t.id = 'v61-ticker'; t.setAttribute('role', 'button'); t.tabIndex = 0;
  t.title = 'Atividade dos motores ao vivo — toque para pausar e ver o histórico';
  t.innerHTML = '<span class="tk-selo" id="tk-selo"><i aria-hidden="true"></i><b>AO VIVO</b></span><ul class="tk-lane" id="tk-lane" aria-live="off"></ul>';
  cab.insertAdjacentElement('afterend', t);
  const abrir = () => { _pausado = true; t.classList.add('pausado'); abrirHistorico(); };
  t.addEventListener('click', abrir);
  t.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); abrir(); } });
  /* a folha fechou → o ticker volta a correr */
  const ov = $('ov');
  if (ov) new MutationObserver(() => { if (!ov.classList.contains('on') && _pausado) { _pausado = false; t.classList.remove('pausado'); _tickerPinta(); } })
    .observe(ov, {attributes: true, attributeFilter: ['class']});
  aoVivoOuvir(() => _tickerPinta());
  aoVivoLigar();
  _tickerPinta();
}
let _ultimoNoTicker = 0;
function _tickerPinta() {
  const selo = $('tk-selo'), lane = $('tk-lane'); if (!selo || !lane) return;
  const est = aoVivo.disponivel === false ? 'indisp' : aoVivo.disponivel === null ? 'lendo' : aoVivo.conectado ? 'vivo' : 'pausa';
  selo.className = 'tk-selo tk-' + est;
  selo.querySelector('b').textContent = {vivo: 'AO VIVO', pausa: 'ao vivo pausado · reconectando', lendo: 'ao vivo: lendo…', indisp: 'ao vivo: INDISPONÍVEL'}[est];
  if (_pausado) return;
  const evs = aoVivo.eventos.slice(-6);
  if (!evs.length) {
    lane.innerHTML = `<li class="tk-vz">${est === 'indisp' ? 'a API dos motores não respondeu' : est === 'lendo' ? '' : 'sem evento na última hora — os motores seguem como estão'}</li>`;
    return;
  }
  const novo = evs[evs.length - 1].id !== _ultimoNoTicker;
  _ultimoNoTicker = evs[evs.length - 1].id;
  lane.innerHTML = evs.map((e, i) => `<li class="t-${esc(e.tipo)}${novo && i === evs.length - 1 ? ' novo' : ''}"><span class="num">${_hm(e.t)}</span><b>${esc(_nome(e.motor))}</b>${esc(e.texto)}</li>`).join('');
}

/** Histórico do fio (até 60 eventos), na folha. */
export function abrirHistorico() {
  const ov = $('ov'), sh = $('sheet'); if (!ov || !sh) return;
  const evs = aoVivo.eventos.slice(-60).reverse();
  const r = motoresRodando().length, f = aoVivo.motores.filter(m => m.estado === 'falhou').length;
  sh.innerHTML = `<span class="x" onclick="fecharDossie()">✕ fechar</span><div class="grab"></div>
    <div class="mt-ficha"><h3 class="v61-disp">Atividade dos motores</h3>
      <div class="mt-estado">${aoVivo.disponivel === false ? 'ao vivo: INDISPONÍVEL' : `${r} rodando · ${f} com falha · ${aoVivo.conectado ? 'fio conectado' : 'fio caído — relendo a cada 30 s'}`}</div>
      ${evs.length ? `<ul class="mt-evs">${evs.map(e => `<li class="t-${esc(e.tipo)}"><span class="num">${esc(quando(e.t))}</span><span><b>${esc(_nome(e.motor))}</b> — ${esc(e.texto)}</span></li>`).join('')}</ul>`
                   : '<div class="dim">Nenhum evento registrado na última hora.</div>'}
    </div>`;
  ov.classList.add('on');
}

/* ── MOTORES: grade de cartões no Início ─────────────────────────────────────────────────────── */
export function motoresMontar(host) {
  if (!host) return;
  host.innerHTML = `<h2 class="sec" id="c61-motores-t">Motores <span class="cnt" id="mt-cnt"></span></h2><div class="mt-grade" id="mt-grade"></div>`;
  const pinta = () => { if (!host.isConnected) { parar(); return; } _motoresPinta(host); };
  const parar = aoVivoOuvir(pinta);
  host.addEventListener('click', e => { const c = e.target.closest('[data-motor]'); if (c) abrirMotor(c.dataset.motor); });
  host.addEventListener('keydown', e => { const c = e.target.closest('[data-motor]');
    if (c && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); abrirMotor(c.dataset.motor); } });
  pinta();
}
const _ORDEM = {rodando: 0, falhou: 1, agendado: 2, ocioso: 3, indisponivel: 4};
function _motoresPinta(host) {
  const g = host.querySelector('#mt-grade'), cnt = host.querySelector('#mt-cnt'); if (!g) return;
  if (aoVivo.disponivel !== true) {
    cnt.textContent = '';
    g.innerHTML = `<div class="mt-indisp">${aoVivo.disponivel === null ? 'Lendo o estado dos motores…'
      : '<b>motores: INDISPONÍVEL</b> — a API <code>/api/ao-vivo/estado</code> não respondeu (a rota entra no próximo reinício do serviço).'}</div>`;
    return;
  }
  const ms = [...aoVivo.motores].sort((a, b) => (a.classe === 'infra') - (b.classe === 'infra') || _ORDEM[a.estado] - _ORDEM[b.estado] || a.nome.localeCompare(b.nome, 'pt-BR'));
  const n = c => ms.filter(m => m.classe !== 'infra' && m.estado === c).length;
  cnt.textContent = `${n('rodando')} rodando · ${n('falhou')} com falha · ${n('agendado')} agendados`;
  let infra = false;
  g.innerHTML = ms.map(m => {
    const sep = (!infra && m.classe === 'infra') ? (infra = true, '<div class="mt-sep">Serviços de apoio</div>') : '';
    const pr = typeof m.progresso === 'number' ? Math.round(m.progresso * 100) : null;
    return `${sep}<article class="mt-card e-${esc(m.estado)}" data-motor="${esc(m.id)}" tabindex="0" role="button" aria-label="${esc(m.nome)}: ${esc(rotuloEstado(m))}">
      <header><i class="mt-pt" aria-hidden="true"></i><b>${esc(m.nome)}</b><span class="mt-rot">${esc(rotuloEstado(m))}</span></header>
      ${pr != null ? `<div class="mt-barra" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pr}"><i style="width:${pr}%"></i></div>` : ''}
      <canvas class="mt-spark" width="240" height="28" data-at="${(m.atividade || []).join(',')}" aria-hidden="true"></canvas>
      <div class="mt-ult">${m.ultimo_evento ? `<span class="num">${_hm(m.ultimo_evento.t)}</span> ${esc(m.ultimo_evento.texto)}` : 'sem evento na última hora'}</div>
      <div class="mt-prox">${m.proxima ? 'próxima: <span class="num">' + esc(quando(m.proxima)) + '</span>' : (m.estado === 'falhou' && m.desde ? 'desde <span class="num">' + esc(quando(m.desde)) + '</span>' : '&nbsp;')}</div>
    </article>`; }).join('');
  g.querySelectorAll('canvas.mt-spark').forEach(_spark);
}
/* sparkline de atividade: 60 barras = eventos por minuto na última hora (desenho único, sem laço) */
function _spark(cv) {
  const at = (cv.dataset.at || '').split(',').map(Number), ctx = cv.getContext('2d'), W = cv.width, H = cv.height;
  const mx = Math.max(1, ...at), w = W / 60;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = 'rgba(30,110,220,.16)'; ctx.fillRect(0, H - 1, W, 1);
  ctx.fillStyle = '#1E7BF0';
  at.forEach((v, i) => { if (v > 0) { const h = Math.max(2, v / mx * (H - 3)); ctx.fillRect(i * w + 0.5, H - 1 - h, Math.max(1, w - 1), h); } });
}
