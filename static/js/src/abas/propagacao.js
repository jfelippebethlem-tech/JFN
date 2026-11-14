// ═══ PROPAGAÇÃO — Sistema › Propagação: o que ficou velho, o que foi recalculado e o que falhou ═══
// Pedido do dono (14/11/2026): "uma alteração ou leitura tem que puxar outras para atualizar tudo automaticamente".
// Dados: GET /api/sistema/propagacao (rotas/propagacao.py → compliance_agent/propagacao.py::estado). A rota só LÊ
// o estado que o despachante grava (cron a cada 5 min, fora do processo do painel) — não dispara nada daqui.
// Base ausente ou despachante parado = INDISPONÍVEL/PARADO, nunca "nada sujo". Custo de API/assinatura não aparece.
import {esc, card, kpi, sec, cover} from '../nucleo/dom.js';
import {J, erroHumano} from '../nucleo/http.js';
import {fmtN} from '../nucleo/formato.js';

const _css = '<style>.pg-txt th,.pg-txt td{text-align:left;vertical-align:top}.pg-txt th.right,.pg-txt td.right{text-align:right}</style>';
const _hora = t => (t ? new Date(t * 1000).toLocaleString('pt-BR', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}) : '—');
const _dur = (a, b) => (a && b ? `${fmtN(Math.max(0, Math.round(b - a)))} s` : '—');
const _ha = (t, agora) => {
  if (!t) return '—';
  const m = Math.max(0, Math.round((agora - t) / 60));
  return m < 60 ? `há ${fmtN(m)} min` : m < 2880 ? `há ${fmtN(Math.round(m / 60))} h` : `há ${fmtN(Math.round(m / 1440))} dias`;
};

/* O estado traz o motivo como "id-da-fonte: o que mudou". Na tela vai o NOME da fonte (ou do derivado que foi
   recalculado), sem repetição. */
function _nomes(d){
  const n = {};
  for (const f of d.fontes || []) n[f.id] = f.nome;
  for (const x of d.derivados || []) n[x.id] = x.nome;
  return n;
}
function _motivos(lista, nomes, max){
  const vistos = new Set(), out = [];
  for (const m of lista || []) {
    const i = m.indexOf(': ');
    const id = i > 0 ? m.slice(0, i) : '';
    const txt = nomes[id] ? `<b>${esc(nomes[id])}</b> — ${esc(m.slice(i + 2))}` : esc(m);
    if (!vistos.has(txt)) { vistos.add(txt); out.push(txt); }
  }
  return out.slice(0, max).join('<br>');
}

function _situacao(x, agora){
  if (x.ultimo_estado === 'rodando') return '<b style="color:var(--accent)">recalculando agora</b>';
  if (x.ultimo_estado === 'falhou') return `<b style="color:var(--rose)">falhou</b> (${fmtN(x.falhas)}×)${x.proxima_tentativa ? ` · nova tentativa ${_hora(x.proxima_tentativa)}` : ''}`;
  if (x.sujo) return `<b style="color:var(--amber)">desatualizado</b> ${_ha(x.sujo_desde, agora)}${x.adiado ? `<div class="dim" style="font-size:11px">${esc(x.adiado)}</div>` : ''}`;
  if (x.ultimo_estado === 'ok') return '<b style="color:var(--green)">em dia</b>';
  return '<span class="dim">sem evento desde que a propagação foi ligada</span>';
}

function _derivados(d){
  const nomes = _nomes(d);
  const lin = (d.derivados || []).map(x => `<tr>
      <td><b>${esc(x.nome)}</b><div class="dim" style="font-size:11px">${esc(x.onde || '')}</div></td>
      <td>${_situacao(x, d.gerado_em)}${x.ultimo_erro ? `<div style="font-size:12px;color:var(--rose)">${esc(x.ultimo_erro)}</div>` : ''}</td>
      <td style="font-size:12px">${_motivos(x.motivos, nomes, 4) || '<span class="dim">—</span>'}${x.eventos_pendentes > (x.motivos || []).length ? `<div class="dim" style="font-size:11px">${fmtN(x.eventos_pendentes)} evento(s) pendente(s) no total</div>` : ''}</td>
      <td style="white-space:nowrap;font-size:13px">${_hora(x.ultimo_fim)}<div class="dim" style="font-size:11px">${x.ultimo_fim ? `levou ${_dur(x.ultimo_inicio, x.ultimo_fim)} · ${fmtN(x.execucoes)} execução(ões)` : 'ainda não recalculado pela propagação'}</div></td>
      <td style="font-size:12px">${esc(x.antes || '—')}</td></tr>`).join('');
  return card(`<div class="dim" style="font-size:12px;margin-bottom:6px">Cada linha é um derivado: algo que o painel mostra e que fica velho quando a fonte muda. "Antes" = como se atualizava até 14/11/2026 (esses agendamentos continuam como rede de segurança).</div>
    <div style="overflow:auto"><table class="tb pg-txt"><thead><tr><th>Derivado</th><th>Situação</th><th>O que o deixou desatualizado</th><th>Último recálculo</th><th>Antes</th></tr></thead><tbody>${lin}</tbody></table></div>`);
}

function _fontes(d){
  const nomes = _nomes(d);
  const lin = (d.fontes || []).map(f => `<tr><td><b>${esc(f.nome)}</b></td>
      <td style="font-size:13px">${f.manual ? '<span class="dim">manual</span>' : f.erro ? `<b style="color:var(--rose)">INDISPONÍVEL</b><div style="font-size:12px">${esc(f.erro)}</div>` : (f.visto_em ? `conferida ${_ha(f.visto_em, d.gerado_em)}` : '<span class="dim">ainda não conferida</span>')}</td>
      <td style="font-size:13px;white-space:nowrap">${f.mudou_em ? _hora(f.mudou_em) : '<span class="dim">sem mudança desde a ligação</span>'}</td>
      <td style="font-size:12px">${(f.alimenta || []).map(x => esc(nomes[x] || x)).join(', ') || '<span class="dim">só o segundo cérebro</span>'}</td></tr>`).join('');
  return card(`<div style="overflow:auto"><table class="tb pg-txt"><thead><tr><th>Fonte / evento</th><th>Sonda</th><th>Última mudança percebida</th><th>Suja</th></tr></thead><tbody>${lin}</tbody></table></div>
    <div class="dim" style="font-size:12px;margin-top:6px">Sonda que não consegue medir aparece como INDISPONÍVEL — isso não quer dizer que a fonte não mudou.</div>`);
}

function _execucoes(d){
  const ex = d.execucoes || [], nomes = _nomes(d);
  if (!ex.length) return card('<div class="dim">Nenhum recálculo feito pela propagação até agora.</div>');
  const lin = ex.map(e => `<tr><td style="white-space:nowrap">${_hora(e.inicio)}</td><td><b>${esc(nomes[e.derivado] || e.derivado)}</b></td>
      <td>${e.estado === 'ok' ? '<b style="color:var(--green)">recalculado</b>' : '<b style="color:var(--rose)">falhou</b>'}</td>
      <td class="right">${_dur(e.inicio, e.fim)}</td>
      <td style="font-size:12px">${_motivos(e.motivos, nomes, 3)}${e.erro ? `<div style="color:var(--rose)">${esc(e.erro)}</div>` : ''}</td></tr>`).join('');
  return card(`<div style="max-height:420px;overflow:auto"><table class="tb pg-txt"><thead><tr><th>Início</th><th>Derivado</th><th>Resultado</th><th class="right">Duração</th><th>Motivo / erro</th></tr></thead><tbody>${lin}</tbody></table></div>`);
}

function _eventos(d){
  const ev = d.eventos || [], nomes = _nomes(d);
  if (!ev.length) return card('<div class="dim">Nenhum evento registrado ainda.</div>');
  return card(`<div style="max-height:360px;overflow:auto"><table class="tb pg-txt"><thead><tr><th>Quando</th><th>Fonte</th><th>O que mudou</th></tr></thead><tbody>${ev.map(e => `<tr><td style="white-space:nowrap">${_hora(e.quando)}</td><td><b>${esc(nomes[e.fonte] ? (e.detalhe.startsWith('recalculado') ? 'Derivado: ' : '') + nomes[e.fonte] : e.fonte)}</b></td><td style="font-size:13px">${esc(e.detalhe)}</td></tr>`).join('')}</tbody></table></div>`);
}

function _cerebro(c, agora){
  if (!c) return '';
  const ult = (c.ultimas || []).map(m => `<tr><td style="white-space:nowrap">${_hora(m.quando)}</td><td>${esc(m.kind)}</td><td style="font-size:13px"><b>${esc(m.assunto || m.chave)}</b><div style="font-size:12px">${esc(m.texto)}</div></td><td class="right">#${fmtN(m.id)}</td></tr>`).join('');
  return sec('Segundo cérebro', fmtN(c.gravadas)) + card(`<div style="font-size:13px">Descobertas duráveis (número de manchete corrigido, correção de regra, alerta verificado, decisão e lição registradas) seguem para a memória comum dos agentes. <b>${fmtN(c.gravadas)}</b> gravada(s) · <b>${fmtN(c.pendentes)}</b> na fila · ${fmtN(c.recusadas)} recusada(s) por conter dado pessoal ou segredo · último envio ${c.ultimo_envio ? _ha(c.ultimo_envio, agora) : '—'}.</div>
    ${c.pendentes && c.ultimo_erro ? `<div class="warn" style="margin-top:6px">Fila parada: ${esc(c.ultimo_erro)}. As descobertas ficam guardadas e seguem quando o cérebro responder.</div>` : ''}
    ${ult ? `<div style="max-height:320px;overflow:auto;margin-top:8px"><table class="tb pg-txt"><thead><tr><th>Enviada</th><th>Tipo</th><th>Memória</th><th class="right">Nº</th></tr></thead><tbody>${ult}</tbody></table></div>` : ''}`);
}

export async function renderPropagacao(){
  const d = await J('/api/sistema/propagacao');
  let h = cover('sistema', 'Propagação — o que mudou puxa o que depende',
    'Quando uma fonte muda (OB nova, status recoletado, processo SEI capturado, contrato novo, regra corrigida), tudo o que depende dela é marcado como desatualizado e recalculado sozinho, um trabalho pesado por vez. Aqui se vê o que está desatualizado, o que foi recalculado e o que falhou.', '🔁');
  if (!d || (d.ok === false && !d.estado)) return h + card(`<div class="warn">${erroHumano(d && (d.erro || d))}</div>`);
  if (d.ok === false) return h + card(`<div class="warn"><b>INDISPONÍVEL</b> — ${esc(d.motivo || 'sem estado da propagação')}. Não quer dizer que está tudo em dia: a tela não tem como saber.</div>`);
  const r = d.resumo || {}, u = d.ultimo_ciclo;
  h += card(d.estado === 'ok'
    ? `<div style="font-size:14px"><b style="color:var(--green)">LIGADA</b> — último ciclo ${_hora(u.quando)} (${fmtN(u.segundos)} s, ${fmtN(u.eventos)} evento(s) novo(s), ${fmtN((u.feitos || []).length)} recálculo(s))</div>`
    : `<div class="warn"><b>PARADA</b> — o despachante não completa um ciclo ${u ? `desde ${_hora(u.quando)}` : 'desde que foi instalado'}. O que aparece abaixo é a última fotografia, não o estado de agora.</div>`);
  h += `<div class="grid g2" style="margin-top:8px">
    ${kpi(fmtN(r.sujos), `Desatualizados agora (de ${fmtN(r.derivados)} derivados)`, r.sujos ? 'var(--amber)' : null, '🔁', {sobre: 'Derivados com evento pendente em data/propagacao.db: a fonte mudou e o recálculo ainda não terminou (juntando eventos, intervalo mínimo, carga da máquina ou a vez na fila). Fonte: compliance_agent/propagacao.py.'})}
    ${kpi(fmtN(r.com_falha), 'Com falha no último recálculo', r.com_falha ? 'var(--rose)' : null, '⚠️', {sobre: 'Derivados cujo último recálculo falhou (saída com erro, teto de tempo, ou rodou sem regravar o arquivo que o painel lê). O despachante tenta de novo com intervalo crescente; o valor anterior segue no painel.'})}
    ${kpi(fmtN(r.fontes_com_erro), `Fontes sem leitura (de ${fmtN(r.fontes)})`, r.fontes_com_erro ? 'var(--rose)' : null, '📡', {sobre: 'Fontes cuja sonda não conseguiu medir no último ciclo. INDISPONÍVEL: não se sabe se a fonte mudou.'})}
    ${kpi(fmtN((d.cerebro || {}).gravadas), 'Descobertas no segundo cérebro', null, '🧠', {sobre: 'Memórias gravadas no cérebro compartilhado dos agentes a partir desta máquina, com resposta do cérebro confirmando a gravação (tabela cerebro de data/propagacao.db).'})}
  </div>`;
  h += sec('Derivados', fmtN(r.derivados)) + _derivados(d);
  h += sec('Recálculos recentes', fmtN((d.execucoes || []).length)) + _execucoes(d);
  h += sec('Fontes e eventos', fmtN(r.fontes)) + _fontes(d);
  h += sec('Últimos eventos', fmtN((d.eventos || []).length)) + _eventos(d);
  h += _cerebro(d.cerebro, d.gerado_em);
  h += card(`<div class="dim" style="font-size:12px">Mapa de dependências: <code>config/propagacao.yaml</code> · estado lido em ${_hora(d.gerado_em)} · INDISPONÍVEL ≠ zero</div>`);
  return `<div id="pg-raiz">${h}${_css}</div>`;
}
