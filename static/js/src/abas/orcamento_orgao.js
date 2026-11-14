// ═══ ORÇAMENTO POR ÓRGÃO — Estado › Orçamento por órgão (14/11/2026) ═══
// Pedido do dono: "quais órgãos têm orçamento e quanto executou… tem orçamento, tem empenho e tem execução
// (pagamento), assim sabemos quais órgãos performam."
// Dados: GET /api/orcamento_orgao?ano=&mes= (compliance_agent/orcamento_orgao.py). Nada é somado aqui: o número
// vem fechado do servidor, com a fonte, o estado (VERIFICADO/PENDENTE/INDISPONÍVEL) e o que ficou de fora.
//  · Empenho ≠ liquidação ≠ pagamento. "Pago" = Ordem Bancária do SIAFE; o pago do balancete é referência, e a
//    diferença entre os dois fica à vista.
//  · Valor que a fonte não tem aparece como INDISPONÍVEL — nunca como R$ 0,00 (por isso `_r`, e não `fmtR`,
//    que escreve "0,00" para nulo).
//  · As unidades de cada órgão só entram no DOM quando o órgão é aberto (são ~300 linhas).
import {esc, card, kpi, sec, cover} from '../nucleo/dom.js';
import {J, erroHumano} from '../nucleo/http.js';
import {fmtN, fmtR, fmtData} from '../nucleo/formato.js';
import {periodoAtual} from './periodo.js';

const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro',
  'novembro', 'dezembro'];
const _norm = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toUpperCase();
const _ind = t => `<span class="dim" title="${esc(t || 'a fonte não tem este valor neste período — não é zero')}">INDISPONÍVEL</span>`;
const _r = (v, t) => (v == null ? _ind(t) : fmtR(v));
const _p = v => (v == null ? '<span class="dim">—</span>'
  : Number(v).toLocaleString('pt-BR', {minimumFractionDigits: 1, maximumFractionDigits: 1}) + '%');
const _TAG = {VERIFICADO: 'teal', PENDENTE: 'amber', INDISPONIVEL: ''};
const _est = e => `<span class="tag ${_TAG[e] || ''}">${e === 'INDISPONIVEL' ? 'INDISPONÍVEL' : esc(e)}</span>`;
const _COL = [['dotacao_inicial', 'Dotação inicial'], ['dotacao_atualizada', 'Dotação atualizada'],
  ['empenhado', 'Empenhado'], ['liquidado', 'Liquidado'], ['pago_siafe', 'Pago (OB do SIAFE)'],
  ['pago_balancete', 'Pago do balancete']];
const _CRIT = {taxa_empenho: 'Empenhado ÷ dotação atualizada', taxa_pago_balancete: 'Pago do balancete ÷ dotação atualizada',
  taxa_pago: 'Pago (OB do SIAFE) ÷ dotação atualizada', taxa_pago_empenhado: 'Pago (OB do SIAFE) ÷ empenhado',
  taxa_empenho_inicial: 'Empenhado ÷ dotação INICIAL'};

let _D = null;                                    // último payload
let _S = {ano: '', mes: '', crit: '', q: '', qTexto: ''};   // o que o usuário escolheu nesta aba

const _falta = (x, k) => ((x.faltam || {})[k] ? ` <span class="tag amber" title="soma incompleta: ${x.faltam[k]} unidade(s) sem este valor — não é o total">parcial</span>` : '');

function _divergencia(x){
  if (x.divergencia == null) return '<span class="dim">—</span>';
  const base = x.divergencia_base === 'total_com_restos' ? 'total de OB × total desembolsado (com restos a pagar)' : 'OB orçamentária × pago do balancete';
  return `<span title="${esc(base)}">${fmtR(x.divergencia)}<div class="dim" style="font-size:11px">${_p(x.divergencia_pct)}</div></span>`;
}

function _pagoSiafe(x){
  if (x.pago_siafe != null) return fmtR(x.pago_siafe) + _falta(x, 'pago_siafe');
  if (x.ob_total != null) return `${_ind('a coleta deste exercício não separa OB orçamentária de restos a pagar')}<div class="dim" style="font-size:11px">total de OB (com restos): ${fmtR(x.ob_total)}</div>`;
  return _ind((x.motivos || {}).pago_siafe);
}

function _seletor(d){
  const anos = (d.exercicios || []).map(e => `<option value="${e.ano}"${e.ano === d.exercicio ? ' selected' : ''}>${e.ano}${e.tfe_mes === 12 ? '' : (e.tfe_mes ? ` (TFE até ${e.tfe_posicao})` : ' (só Executivo, painel CGE)')}</option>`).join('');
  const com = new Set(d.meses_com_execucao || []);
  const meses = '<option value="">Exercício inteiro</option>' + MESES.map((m, i) => `<option value="${i + 1}"${d.mes === i + 1 ? ' selected' : ''}>até ${m}${com.has(i + 1) ? '' : ' (só OB do SIAFE)'}</option>`).join('');
  return card(`<div class="per-sel" role="group" aria-label="Escolher exercício e mês">
      <label>Exercício <select class="inp" data-oo-ano>${anos}</select></label>
      <label>Acumulado <select class="inp" data-oo-mes>${meses}</select></label>
      <span class="dim per-nota">O mês é o acumulado de janeiro até ele. Execução por mês existe só para o Poder Executivo (painel da CGE, 2024 em diante); o TFE publica a posição do ano.</span></div>
    <div style="font-size:13px"><b>Período:</b> ${esc(d.periodo)} · <b>Visão:</b> ${esc(d.visao_descricao)}</div>
    <div class="dim" style="font-size:12px;margin-top:4px"><b>Fonte:</b> ${esc(d.proveniencia.fonte)}<br><b>Cobertura:</b> ${esc(d.proveniencia.cobertura)}</div>
    ${d.dotacao_defasada ? `<div class="warn" style="margin-top:8px">A dotação atualizada publicada é da posição ${esc(d.dotacao_posicao)} — anterior ao fim deste período. Taxa sobre dotação atualizada fica INDISPONÍVEL (crédito aberto depois faria a taxa passar de 100%).</div>` : ''}
    ${d.execucao_parcial ? `<div class="warn" style="margin-top:8px">O balancete deste exercício parou num dia de dentro do mês. As OB do SIAFE aparecem até o fim do mês e NÃO são comparadas com ele.</div>` : ''}`);
}

function _placar(d){
  const t = d.total || {}, f = t.faltam || {};
  const parc = k => (f[k] ? ` Soma incompleta: ${f[k]} unidade(s) sem este valor.` : '');
  const ob = t.ob || {};
  return `<div class="grid g2" style="margin-top:12px">
    ${kpi(_r(t.dotacao_atualizada), 'Dotação atualizada', null, '🏦', {sobre: `Dotação inicial ${t.dotacao_inicial == null ? 'INDISPONÍVEL' : fmtR(t.dotacao_inicial)} mais créditos adicionais, menos anulações, na posição publicada. ${d.colunas.dotacao_atualizada}${parc('dotacao_atualizada')}`})}
    ${kpi(_r(t.empenhado), 'Empenhado' + (t.taxa_empenho == null ? '' : ` — ${_p(t.taxa_empenho)} da dotação`), null, '📝', {sobre: `${d.colunas.empenhado} Período: ${d.periodo}.${parc('empenhado')}`})}
    ${kpi(_r(t.liquidado), 'Liquidado', null, '📦', {sobre: `${d.colunas.liquidado}${parc('liquidado')}`})}
    ${kpi(_pagoSiafe(t), 'Pago — OB do SIAFE', 'var(--teal)', '💳', {sobre: `${d.colunas.pago_siafe} ${fmtN(ob.n)} OB; fora da soma: ${fmtN(ob.devolvidas_n)} devolvidas pelo banco (${fmtR(ob.devolvidas_valor || 0)}) e ${fmtN(ob.devolucao_sem_valor_n)} com devolução parcial de valor não coletado (${fmtR(ob.devolucao_sem_valor_bruto || 0)} brutos) — por isso o número é PISO.${parc('pago_siafe')}`})}
    ${kpi(_r(t.pago_balancete), 'Pago do balancete (referência)' + (t.taxa_pago_balancete == null ? '' : ` — ${_p(t.taxa_pago_balancete)} da dotação`), null, '📒', {sobre: `${d.colunas.pago_balancete}${parc('pago_balancete')}`})}
    ${kpi(t.divergencia == null ? _ind('sem os dois valores no mesmo período') : `${fmtR(t.divergencia)}`, 'OB do SIAFE menos balancete' + (t.divergencia_pct == null ? '' : ` — ${_p(t.divergencia_pct)}`), 'var(--amber)', '⚖️', {sobre: `${d.colunas.divergencia} Medida em ${fmtN(t.divergencia_n)} UG, contra ${t.ref_pago_balancete == null ? '—' : fmtR(t.ref_pago_balancete)} do balancete nessas mesmas UG. ${d.ressalva}`})}
  </div>`;
}

function _ranking(d){
  const ks = Object.keys(d.rankings || {});
  if (!ks.length) return '';
  if (!ks.includes(_S.crit)) _S.crit = ks[0];
  const r = d.rankings[_S.crit];
  const chips = ks.map(k => `<button type="button" class="chip${k === _S.crit ? ' on' : ''}" data-oo-crit="${k}">${esc(_CRIT[k])} (${fmtN(d.rankings[k].elegiveis)})</button>`).join('');
  const tb = (itens, tit) => `<div><div style="font-weight:700;margin-bottom:4px">${tit}</div>
    <table class="tb oo-txt"><thead><tr><th>Órgão</th><th class="right">Taxa</th></tr></thead><tbody>${itens.map(x => `<tr>
      <td><a href="#" data-oo-ir="${esc(x.orgao)}">${esc(x.nome)}</a> <span class="dim" style="font-size:11px">órgão ${esc(x.orgao)}</span>
        ${(x.notas || []).map(n => `<div class="dim" style="font-size:11px">${esc(n)}</div>`).join('')}</td>
      <td class="right" style="white-space:nowrap"><b>${_p(x.taxa)}</b></td></tr>`).join('') || '<tr><td colspan="2" class="dim">Nenhum órgão comparável neste critério.</td></tr>'}</tbody></table></div>`;
  return sec('Ranking de execução') + card(`<div class="chips">${chips}</div>
    <div class="dim" style="font-size:12px;margin:6px 0 10px"><b>${fmtN(r.elegiveis)} de ${fmtN(r.total_orgaos)}</b> órgãos entram neste ranking: os que têm a taxa calculável (nenhuma parcela faltando, OB e dotação no mesmo universo) e dotação a partir de ${fmtR(d.piso_ranking)}. ${_S.crit === 'taxa_empenho_inicial' ? 'Sem dotação atualizada utilizável neste recorte, o ranking usa a dotação INICIAL — crédito adicional pode levar a taxa acima de 100%.' : ''}</div>
    <div class="grid two">${tb(r.mais, `Maiores taxas (${fmtN(r.mais.length)})`)}${tb(r.menos, `Menores taxas (${fmtN(r.menos.length)})`)}</div>
    <div class="dim" style="font-size:12px;margin-top:8px">Taxa baixa é indício para perguntar, não conclusão: contingenciamento, receita vinculada que não entrou e reserva de contingência reduzem a taxa sem irregularidade.</div>`);
}

const _CAB = `<th>Órgão</th><th class="right">Dotação inicial</th><th class="right">Dotação atualizada</th><th class="right">Empenhado</th>
  <th class="right">Liquidado</th><th class="right">Pago (OB do SIAFE)</th><th class="right">Pago do balancete (ref.)</th><th class="right">OB − balancete</th>
  <th class="right" title="empenhado ÷ dotação atualizada">Emp. ÷ dot.</th><th class="right" title="pago por OB do SIAFE ÷ dotação atualizada">Pago ÷ dot.</th><th class="right" title="pago por OB do SIAFE ÷ empenhado">Pago ÷ emp.</th>`;

function _valores(x){
  return `<td class="right">${_r(x.dotacao_inicial)}${_falta(x, 'dotacao_inicial')}</td><td class="right">${_r(x.dotacao_atualizada, (x.motivos || {}).dotacao_atualizada)}${_falta(x, 'dotacao_atualizada')}</td>
    <td class="right">${_r(x.empenhado, (x.motivos || {}).execucao)}${_falta(x, 'empenhado')}</td><td class="right">${_r(x.liquidado, (x.motivos || {}).execucao)}</td>
    <td class="right">${_pagoSiafe(x)}</td><td class="right">${_r(x.pago_balancete, (x.motivos || {}).execucao)}</td><td class="right">${_divergencia(x)}</td>
    <td class="right"><b>${_p(x.taxa_empenho)}</b></td><td class="right">${_p(x.taxa_pago)}<div class="dim" style="font-size:11px" title="pago do balancete ÷ dotação atualizada (referência)">bal. ${_p(x.taxa_pago_balancete)}</div></td><td class="right">${_p(x.taxa_pago_empenhado)}</td>`;
}

function _linhaOrgao(o){
  const aberto = _aberto.has(o.orgao);
  return `<tr id="oo-o-${esc(o.orgao)}"><td style="min-width:230px"><b>${esc(o.nome)}</b> <span class="dim" style="font-size:11px">órgão ${esc(o.orgao)} · ${fmtN(o.n_ugs)} UG${o.executivo === false ? ' · fora do Executivo' : ''}</span>
      ${(o.notas || []).map(n => `<div class="dim" style="font-size:11px">${esc(n)}</div>`).join('')}
      <div style="margin-top:4px"><button type="button" class="btn ghost" data-oo-abrir="${esc(o.orgao)}" aria-expanded="${aberto}">${aberto ? 'Fechar unidades' : 'Ver unidades'}</button></div></td>${_valores(o)}</tr>
    <tr data-oo-det="${esc(o.orgao)}"${aberto ? '' : ' hidden'}><td colspan="11" style="background:var(--bg2,transparent)">${aberto ? _detalhe(o) : ''}</td></tr>`;
}

function _detalhe(o){
  const uos = (o.uos || []).map(u => `<tr><td>${esc(u.nome)} <span class="dim" style="font-size:11px">UO ${esc(u.uo)}</span></td><td class="right">${fmtR(u.dotacao_inicial)}</td><td class="right">${fmtR(u.dotacao_atualizada)}</td>
      <td class="right">${fmtR(u.empenhado)}</td><td class="right">${fmtR(u.liquidado)}</td><td class="right">${fmtR(u.pago_balancete)}</td><td class="right"><b>${_p(u.taxa_empenho)}</b></td><td class="right">${_p(u.taxa_pago_balancete)}</td></tr>`).join('');
  const ugs = (o.ugs || []).map(x => `<tr><td style="min-width:220px">${esc(x.nome)} <span class="dim" style="font-size:11px">UG ${esc(x.ug)}</span>
      ${(x.notas || []).map(n => `<div class="dim" style="font-size:11px">${esc(n)}</div>`).join('')}
      <div style="font-size:11px;margin-top:2px">${_COL.map(([k, t]) => `<span title="${esc((x.motivos || {})[k] || (x.motivos || {}).execucao || '')}">${esc(t)} ${_est(x.estados[k])}</span>`).join(' ')}</div></td>
      <td class="right">${_r(x.empenhado, (x.motivos || {}).execucao)}</td><td class="right">${_r(x.liquidado, (x.motivos || {}).execucao)}</td><td class="right">${_pagoSiafe(x)}</td>
      <td class="right">${_r(x.pago_balancete, (x.motivos || {}).execucao)}</td><td class="right">${_divergencia(x)}</td><td class="right">${_p(x.taxa_pago_empenhado)}</td></tr>`).join('');
  return `${uos ? `<div style="font-weight:700;margin:6px 0 4px">Unidades orçamentárias — onde está a dotação (${fmtN(o.uos.length)})</div>
      <div style="overflow-x:auto"><table class="tb oo-txt"><thead><tr><th>Unidade orçamentária</th><th class="right">Dotação inicial</th><th class="right">Dotação atualizada</th><th class="right">Empenhado</th><th class="right">Liquidado</th><th class="right">Pago do balancete (ref.)</th><th class="right">Emp. ÷ dot.</th><th class="right">Pago bal. ÷ dot.</th></tr></thead><tbody>${uos}</tbody></table></div>` : ''}
    <div style="font-weight:700;margin:10px 0 4px">Unidades gestoras — quem executa e emite a OB (${fmtN((o.ugs || []).length)})</div>
    <div class="dim" style="font-size:12px;margin-bottom:4px">A dotação é da unidade orçamentária; qualquer UG pode executar o crédito dela. Por isso aqui não há taxa sobre dotação — só pago por OB ÷ empenhado, e só quando a UG executa crédito de um único órgão. A diferença OB − balancete é da UG inteira.</div>
    <div style="overflow-x:auto"><table class="tb oo-txt"><thead><tr><th>Unidade gestora e estado de cada número</th><th class="right">Empenhado</th><th class="right">Liquidado</th><th class="right">Pago (OB do SIAFE)</th><th class="right">Pago do balancete (ref.)</th><th class="right">OB − balancete</th><th class="right">Pago ÷ emp.</th></tr></thead><tbody>${ugs}</tbody></table></div>`;
}

const _aberto = new Set();
const _visiveis = d => (d.orgaos || []).filter(o => !_S.q || _norm(o.nome).includes(_S.q) || o.orgao === _S.q
  || (o.ugs || []).some(x => _norm(x.nome).includes(_S.q) || x.ug === _S.q));

function _tabela(d){
  const vis = _visiveis(d), t = d.total || {};
  const corpo = vis.map(_linhaOrgao).join('') || '<tr><td colspan="11" class="dim">Nenhum órgão neste filtro.</td></tr>';
  const pe = `<tfoot><tr><td><b>Estado — soma de todos os órgãos</b><div class="dim" style="font-size:11px">${fmtN(t.n_orgaos)} órgãos · ${fmtN(t.n_ugs)} UG${d.controles.intraorcamentario_empenhado ? ` · inclui ${fmtR(d.controles.intraorcamentario_empenhado)} de empenho intraorçamentário (modalidade 91)` : ''}</div></td>${_valores(t)}</tr></tfoot>`;
  return `<div style="overflow-x:auto"><table class="tb oo-txt"><thead><tr>${_CAB}</tr></thead><tbody data-oo-corpo>${corpo}</tbody>${pe}</table></div>
    <div class="dim" style="font-size:12px;margin-top:6px" data-oo-cont>${fmtN(vis.length)} de ${fmtN((d.orgaos || []).length)} órgãos, do maior orçamento para o menor.</div>`;
}

function _fontes(d){
  const ec = d.estados_por_coluna || {};
  const linhas = _COL.map(([k, t]) => `<tr><td><b>${esc(t)}</b></td><td style="font-size:13px">${esc(d.colunas[k] || '')}</td>
    <td style="white-space:nowrap">${['VERIFICADO', 'PENDENTE', 'INDISPONIVEL'].filter(e => (ec[k] || {})[e]).map(e => `${_est(e)} ${fmtN(ec[k][e])} UG`).join('<br>')}</td></tr>`).join('');
  const c = d.controles || {};
  return sec('De onde vem cada coluna') + card(`<div style="overflow-x:auto"><table class="tb oo-txt"><thead><tr><th>Coluna</th><th>Fonte e regra</th><th>Estado, por UG</th></tr></thead><tbody>${linhas}</tbody></table></div>
    <div class="dim" style="font-size:12px;margin-top:8px"><b>VERIFICADO</b> = duas publicações oficiais independentes dão o mesmo número no centavo (TFE e painel da CGE; para a OB, diferença de até ${fmtN(d.tolerancias.pago_pct)}% contra o balancete da UG). <b>PENDENTE</b> = fonte única ou fontes que divergem. <b>INDISPONÍVEL</b> = a fonte não tem o valor — não é zero.</div>
    <div class="dim" style="font-size:12px;margin-top:6px">${esc(d.colunas.divergencia)} ${esc(d.ressalva)}</div>
    <div class="dim" style="font-size:12px;margin-top:6px">${c.empenhado_que_cruza_de_orgao == null ? '' : `Crédito que cruza de órgão (UG de um órgão executando crédito de outro): ${fmtR(c.empenhado_que_cruza_de_orgao)} do empenhado, medido no TFE na posição ${esc(d.cruzado_posicao_ref || '—')}. `}OB sem número (linha repetida da coleta) fora da soma: ${fmtN((c.ob_sem_numero_fora || {}).n)}. OB do SIAFE emitidas até ${c.ob_emitida_ate ? fmtData(c.ob_emitida_ate) : '—'}; nesta tela, contadas até ${esc(MESES[(d.ob_ate_mes || 12) - 1])}.</div>
    <div class="dim" style="font-size:12px;margin-top:6px">Calculado em ${esc(d.gerado_em || '—')} (a base de cada exercício fica em cache por 1 hora).</div>`);
}

function _corpo(d){
  let h = _seletor(d);
  h += sec('Estado do Rio de Janeiro — ' + esc(d.periodo)) + _placar(d) + _ranking(d);
  h += sec('Órgão a órgão', (d.orgaos || []).length) + card(`<label style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px"><b>Filtrar</b>
      <input type="search" data-oo-filtro value="${esc(_S.qTexto || '')}" placeholder="órgão, unidade ou código — ex.: Saúde, DETRAN, 296100" style="flex:1;min-width:200px"></label>
    <div data-oo-tabela>${_tabela(d)}</div>`);
  h += _fontes(d);
  return h + '<style>.oo-txt th,.oo-txt td{text-align:left;vertical-align:top}.oo-txt th.right,.oo-txt td.right{text-align:right;white-space:nowrap}</style>';
}

async function _buscar(){
  const q = [];
  if (_S.ano) q.push('ano=' + encodeURIComponent(_S.ano));
  if (_S.mes) q.push('mes=' + encodeURIComponent(_S.mes));
  return J('/api/orcamento_orgao' + (q.length ? '?' + q.join('&') : ''), {tetoMs: 120000});
}

const _erro = d => card(`<div class="warn">${erroHumano(d && (d.erro || d))}</div><div class="dim" style="font-size:12px;margin-top:6px">Orçamento por órgão INDISPONÍVEL agora — não é zero.</div>`);

async function _repintar(){
  const raiz = document.getElementById('oo-raiz'); if (!raiz) return;
  raiz.setAttribute('aria-busy', 'true');
  const d = await _buscar();
  const r2 = document.getElementById('oo-raiz'); if (!r2) return;          // trocou de aba durante a espera
  r2.removeAttribute('aria-busy');
  if (!d || d.ok === false || !d.orgaos) { r2.innerHTML = _erro(d); return; }
  _D = d; _aberto.clear();
  r2.innerHTML = _corpo(d);
}

function _repintarTabela(){
  const el = document.querySelector('#oo-raiz [data-oo-tabela]');
  if (el && _D) el.innerHTML = _tabela(_D);
}

// Delegação por data-* (catraca do painel: nada de função nova em `window`); ligada no boot por `ligarOrcamentoOrgao()`.
let _ligado = false;
export function ligarOrcamentoOrgao(){
  if (_ligado) return; _ligado = true;
  document.addEventListener('change', ev => {
    const t = ev.target; if (!t || !t.matches) return;
    if (t.matches('[data-oo-ano]')) { _S.ano = t.value; _S.mes = ''; _repintar(); }
    else if (t.matches('[data-oo-mes]')) { _S.mes = t.value; _repintar(); }
  });
  document.addEventListener('click', ev => {
    const b = ev.target && ev.target.closest && ev.target.closest('[data-oo-crit],[data-oo-abrir],[data-oo-ir]');
    if (!b || !_D) return;
    ev.preventDefault();
    if (b.dataset.ooCrit) {
      _S.crit = b.dataset.ooCrit;
      const raiz = document.getElementById('oo-raiz'); if (raiz) raiz.innerHTML = _corpo(_D);
      return;
    }
    const cod = b.dataset.ooAbrir || b.dataset.ooIr;
    if (b.dataset.ooIr) { _S.q = ''; _S.qTexto = ''; _aberto.add(cod); const f = document.querySelector('#oo-raiz [data-oo-filtro]'); if (f) f.value = ''; }
    else if (_aberto.has(cod)) _aberto.delete(cod); else _aberto.add(cod);
    _repintarTabela();
    if (b.dataset.ooIr) { const alvo = document.getElementById('oo-o-' + cod); if (alvo) alvo.scrollIntoView({block: 'center'}); }
  });
  let tm = 0;   // digitação no celular: repinta depois de uma pausa, não a cada tecla
  document.addEventListener('input', ev => {
    const t = ev.target;
    if (!t || !t.matches || !t.matches('[data-oo-filtro]')) return;
    clearTimeout(tm);
    tm = setTimeout(() => { _S.qTexto = t.value; _S.q = _norm(t.value.trim()); _repintarTabela(); }, 180);
  });
}

export async function renderOrcamentoOrgao(){
  const p = periodoAtual();                      // o filtro Ano/Mês do painel, se o dono já escolheu um
  if (!_S.ano && p.ano) { _S.ano = p.ano; _S.mes = p.mes || ''; }
  let d = await _buscar();
  if (d && d.ok === false && d.exercicios && _S.ano) { _S.ano = ''; _S.mes = ''; d = await _buscar(); }   // ano do filtro fora desta base
  const h = cover('estado', 'Orçamento por órgão',
    'Quanto cada órgão tem de orçamento e quanto executou: dotação, empenho, liquidação e pagamento, com as taxas de execução. Empenho não é pagamento; o pago é a Ordem Bancária do SIAFE. Taxa baixa é ponto de pergunta, não acusação.', '🏦');
  if (!d || d.ok === false || !d.orgaos) return h + `<div id="oo-raiz">${_erro(d)}</div>`;
  _D = d; _aberto.clear();
  return h + `<div id="oo-raiz">${_corpo(d)}</div>`;
}
