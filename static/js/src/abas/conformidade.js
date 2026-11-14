// ═══ CONFORMIDADE — Transversal › Conformidade: as regras de qualidade do próprio JFN, por sistema ═══
// Dados: GET /api/qualidade/conformidade (rotas/qualidade.py → compliance_agent/qualidade/estado.py::painel).
// A rota só LÊ a fotografia dos sensores, o juiz e as catracas — não mede na hora. Sem fotografia = INDISPONÍVEL,
// e o painel diz isso em vez de mostrar "0 violações". Sem delegação de eventos: a linha do sistema abre a lista
// de itens alternando a linha seguinte (handler inline sem nome global — nada novo no `window`).
import {esc, card, kpi, sec, cover} from '../nucleo/dom.js';
import {J, erroHumano} from '../nucleo/http.js';
import {fmtN} from '../nucleo/formato.js';

const _IND = '<span class="dim">indisponível</span>';
const _txt = '<style>.cf-txt th,.cf-txt td{text-align:left;vertical-align:top}.cf-txt th.right,.cf-txt td.right{text-align:right}.cf-lin{cursor:pointer}</style>';
const _SEV = {bloqueante: 'var(--rose)', alta: 'var(--amber)'};
const _sev = s => `<b style="color:${_SEV[s] || 'inherit'}">${esc(s || '—')}</b>`;
const _hora = s => (s ? esc(String(s).replace('T', ' ').slice(0, 16)) : '—');
const _sinal = v => (v == null ? '<span class="dim">—</span>' : (v > 0 ? `<b style="color:var(--rose)">+${fmtN(v)}</b>` : v < 0 ? `<b style="color:var(--green)">${fmtN(v)}</b>` : '0'));
const _nota = v => (v == null ? '—' : Number(v).toLocaleString('pt-BR', {maximumFractionDigits: 2}));

function _itens(s){
  const it = s.itens || [];
  if (!it.length) return `<div class="dim" style="font-size:12px">${s.violacoes_abertas == null ? 'Sem fotografia dos sensores — não há como listar.' : 'Nenhuma violação aberta neste sistema.'}</div>`;
  const lin = it.map(a => `<tr><td style="white-space:nowrap"><b>${esc(a.regra)}</b></td>
      <td style="font-size:13px"><b>${esc(a.titulo)}</b><div class="dim" style="font-size:12px">${esc(a.titulo_regra || '')}</div></td>
      <td style="font-size:13px">${esc(a.detalhe || '')}</td><td>${_sev(a.severidade)}</td>
      <td style="font-size:13px">${esc(a.acao_humana || '')}<div class="dim" style="font-size:11px">sensor ${esc(a.sensor || '—')}</div></td></tr>`).join('');
  const corte = s.itens_total > it.length ? `<div class="dim" style="font-size:12px;margin-top:4px">Listados ${fmtN(it.length)} de ${fmtN(s.itens_total)} (bloqueantes primeiro).</div>` : '';
  return `<div style="max-height:520px;overflow:auto"><table class="tb cf-txt"><thead><tr><th>Regra</th><th>Violação</th><th>Detalhe</th><th>Severidade</th><th>Ação</th></tr></thead><tbody>${lin}</tbody></table></div>${corte}`;
}

function _sistemas(d){
  const lin = (d.sistemas || []).map(s => {
    const serie = (s.tendencia || []).slice(-7).map(t => fmtN(t.abertas)).join(' · ');
    const sem = (s.sem_verificador_automatico || []).length ? `<div class="dim" style="font-size:11px">${fmtN(s.sem_verificador_automatico.length)} sem verificação automática</div>` : '';
    return `<tr class="cf-lin" title="Ver as violações de ${esc(s.nome)}" onclick="this.nextElementSibling.hidden=!this.nextElementSibling.hidden">
        <td><b>${esc(s.nome)}</b>${sem}</td><td class="right">${fmtN(s.regras)}</td>
        <td class="right">${s.violacoes_abertas == null ? _IND : `<b>${fmtN(s.violacoes_abertas)}</b>`}</td>
        <td class="right">${s.bloqueantes == null ? _IND : (s.bloqueantes ? `<b style="color:var(--rose)">${fmtN(s.bloqueantes)}</b>` : '0')}</td>
        <td style="font-size:12px">${(s.regras_violadas || []).map(esc).join(', ') || '<span class="dim">—</span>'}</td>
        <td style="font-size:12px;white-space:nowrap">${serie || '<span class="dim">sem série</span>'} <span class="dim">(7 d:</span> ${_sinal(s.variacao_7d)}<span class="dim">)</span></td></tr>
      <tr hidden><td colspan="6">${_itens(s)}</td></tr>`;
  }).join('');
  return card(`<div class="dim" style="font-size:12px;margin-bottom:6px">Clique na linha para ver as violações daquele sistema. Tendência = violações abertas na última leitura de cada dia (até 7 dias); variação 7 d com sinal (+ piorou).</div>
    <div style="overflow:auto"><table class="tb cf-txt"><thead><tr><th>Sistema</th><th class="right">Regras</th><th class="right">Violações abertas</th><th class="right">Bloqueantes</th><th>Regras violadas</th><th>Tendência</th></tr></thead><tbody>${lin}</tbody></table></div>`);
}

function _cegos(c){
  const ks = Object.keys(c || {});
  if (!ks.length) return '';
  return sec('Sensores cegos', ks.length) + card(`<div class="warn"><b>Estes sensores não conseguiram medir</b> — o que eles cobrem está INDISPONÍVEL, não conforme.</div>
    <table class="tb cf-txt" style="margin-top:6px"><thead><tr><th>Sensor</th><th>Motivo</th></tr></thead><tbody>${ks.map(k => `<tr><td><b>${esc(k)}</b></td><td style="font-size:13px">${esc(c[k])}</td></tr>`).join('')}</tbody></table>`);
}

function _juiz(j){
  if (!j || j.media == null) return sec('Juiz subjetivo') + card(`<div class="dim">Sem rodada do juiz${j && j.motivo ? ` — ${esc(j.motivo)}` : ''}. Isso não é nota boa: as regras subjetivas (SUB) ainda não foram avaliadas.</div>`);
  const crit = Object.entries(j.por_criterio || {}).map(([c, n]) => `<tr><td>${esc(c)}</td><td class="right">${_nota(n)}</td></tr>`).join('');
  const baixas = [];
  for (const a of j.avaliacoes || []) {
    for (const [c, n] of Object.entries(a.notas || {})) {
      if (n != null && n <= 2) baixas.push({a, c, n});
    }
  }
  const lin = baixas.map(({a, c, n}) => `<tr><td style="font-size:13px"><b>${esc(a.rotulo || a.id)}</b><div class="dim" style="font-size:11px">${esc(a.sistema || '')} · ${esc(a.veredito || '')}</div></td>
      <td>${esc(c)}</td><td class="right"><b style="color:${n <= 1 ? 'var(--rose)' : 'var(--amber)'}">${fmtN(n)}</b></td>
      <td style="font-size:13px">${esc((a.motivos || {})[c] || '')}</td><td style="font-size:13px">${esc(a.o_que_falta || '')}</td>
      <td style="font-size:12px">${a.escalar ? `<b>sim</b>${a.motivo_escalar ? ` — ${esc(a.motivo_escalar)}` : ''}` : 'não'}</td></tr>`).join('');
  return sec('Juiz subjetivo', fmtN(j.vigentes)) + card(`<div style="font-size:13px">Rodada de ${_hora(j.em)} · média geral <b>${_nota(j.media)}</b> (escala 0–4) · ${fmtN((j.reprovadas || []).length)} reprovada(s) · ${fmtN((j.a_escalar || []).length)} a escalar ao dono</div>
    <table class="tb cf-txt" style="margin-top:8px;max-width:420px"><thead><tr><th>Critério</th><th class="right">Média</th></tr></thead><tbody>${crit}</tbody></table>
    <details style="margin-top:10px"${baixas.length ? ' open' : ''}><summary style="cursor:pointer"><b>Notas ≤ 2</b> (${fmtN(baixas.length)})</summary>
      ${baixas.length ? `<div style="max-height:520px;overflow:auto"><table class="tb cf-txt"><thead><tr><th>Afirmação</th><th>Critério</th><th class="right">Nota</th><th>Motivo</th><th>O que falta</th><th>Escala ao dono</th></tr></thead><tbody>${lin}</tbody></table></div>` : '<div class="dim" style="font-size:12px">Nenhuma nota ≤ 2 nas avaliações vigentes.</div>'}</details>`);
}

function _divida(d){
  const cat = (d.dividas_catraca || []).map(x => `<tr><td>${esc(x.catraca)}</td><td class="right">${fmtN(x.ocorrencias)}</td><td class="right">${fmtN(x.itens)}</td></tr>`).join('');
  const reg = (d.dividas_regra || []).map(x => `<tr><td style="white-space:nowrap"><b>${esc(x.regra)}</b></td><td style="font-size:13px">${esc(x.titulo)}</td><td style="font-size:13px">${(x.falta || []).map(esc).join('<br>')}</td></tr>`).join('');
  return sec('Dívida') + card(`<div class="dim" style="font-size:12px">Por catraca: o que já existia quando a catraca foi travada — só pode descer.</div>
    ${cat ? `<table class="tb cf-txt" style="margin-top:6px"><thead><tr><th>Catraca</th><th class="right">Ocorrências travadas</th><th class="right">Itens</th></tr></thead><tbody>${cat}</tbody></table>` : '<div class="dim" style="font-size:12px">Nenhuma dívida travada em catraca.</div>'}
    <div class="dim" style="font-size:12px;margin-top:12px">Regras ainda com verificação manual — o que falta para a máquina cobrar.</div>
    ${reg ? `<table class="tb cf-txt" style="margin-top:6px"><thead><tr><th>Regra</th><th>Título</th><th>O que falta</th></tr></thead><tbody>${reg}</tbody></table>` : '<div class="dim" style="font-size:12px">Nenhuma.</div>'}`);
}

export async function renderConformidade(){
  const d = await J('/api/qualidade/conformidade');
  let h = cover('geral', 'Conformidade — regras de qualidade do JFN',
    'Por sistema do JFN: as regras de qualidade que valem, as violações abertas medidas pelos sensores, a tendência, a avaliação do juiz subjetivo e a dívida. Lê a última fotografia; não mede na hora. INDISPONÍVEL não é zero.', '✅');
  if (!d || (d.ok === false && !d.estado)) return h + card(`<div class="warn">${erroHumano(d && (d.erro || d))}</div>`);
  const medido = d.estado === 'MEDIDO';
  const r = d.regras || {}, j = d.juiz;
  h += card(medido
    ? `<div style="font-size:14px"><b style="color:var(--green)">MEDIDO</b> em ${_hora(d.medido_em)}</div>`
    : `<div class="warn"><b>INDISPONÍVEL</b> — ${esc(d.motivo || 'sem fotografia dos sensores')}. Não é zero: a tela não está dizendo que não há violação, e sim que não tem como saber.</div>`);
  h += `<div class="grid g2" style="margin-top:8px">
    ${kpi(r.total == null ? _IND : fmtN(r.total), `Regras (${fmtN(r.automaticas)} com verificação automática)`, null, '✅', {sobre: 'Regras de qualidade registradas em config/qualidade_regras.yaml (famílias PAD, CNF, COR, CST, SUB). Automática = tem catraca, sensor ou juiz que a cobra sem leitura humana.'})}
    ${kpi(medido ? fmtN(d.total_violacoes) : _IND, 'Violações abertas', null, '⚠️', {sobre: 'Violações abertas na última fotografia dos sensores (data/qualidade_estado.json). Sem fotografia = indisponível, nunca zero. Indício de defeito de qualidade, não acusação.'})}
    ${kpi(medido ? fmtN(d.total_bloqueantes) : _IND, 'Bloqueantes', medido && d.total_bloqueantes ? 'var(--rose)' : null, '🚨', {sobre: 'Violações de severidade bloqueante na mesma fotografia — as que impedem uma afirmação de sair do JFN como está.'})}
    ${kpi(j && j.media != null ? _nota(j.media) : '<span class="dim">sem rodada</span>', 'Nota média do juiz (0–4)', null, '🎯', {sobre: 'Média das notas do juiz subjetivo (data/qualidade_juiz.json) nas avaliações vigentes, escala 0 a 4. Sem rodada = não avaliado, não é nota boa.'})}
  </div>`;
  // falha de leitura: não há sistemas, juiz nem dívida para mostrar — listas vazias aqui seriam "zero" inventado
  if (d.ok === false) return `<div id="cf-raiz">${h}</div>`;
  h += sec('Por sistema', fmtN((d.sistemas || []).length)) + _sistemas(d);
  h += _cegos(d.sensores_cegos);
  h += _juiz(j);
  h += _divida(d);
  h += card(`<div class="dim" style="font-size:12px">Regras: <code>${esc(d.documento || 'docs/REGRAS-DE-QUALIDADE.md')}</code> · Indício ≠ acusação · INDISPONÍVEL ≠ zero${d.gerado_em ? ` · lido em ${_hora(d.gerado_em)}` : ''}</div>`);
  return `<div id="cf-raiz">${h}${_txt}</div>`;
}
