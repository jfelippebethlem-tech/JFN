// ═══ GOVERNO COUTO — a gestão do governador em exercício, de 23/03/2026 até hoje (13/11/2026) ═══
// Sub-aba de Estado. Pedido do dono: "uma aba especialmente pra tudo que foi feito durante a gestão".
// Dados: GET /api/governo_couto (compliance_agent/governo_couto.py). Cada bloco declara fonte e cobertura;
// bloco que falha diz INDISPONÍVEL (≠ zero). Pagamento = só OB Contabilizada do SIAFE; contrato = valor contratado.
//
// v62 (13/11/2026) — "A ABA NÃO ABRE DIREITO". Medido no Chromium em modo celular: o render montava ~720 KB de
// HTML e ~10.700 nós de uma vez (205 decretos, 300 contratações, 184 pontos, 80 perícias… todas as linhas, com
// os blocos abertos). Só o `innerHTML` + layout levava 19,6 s na VM — a tela ficava no "Carregando…" e, quem
// trocava de aba no meio, voltava para o spinner de novo. Agora cada tabela entra com as primeiras linhas e um
// "Mostrar mais"; o filtro por órgão varre TODAS as linhas em memória (não só as que estão na tela) e repinta.
import {esc, card, kpi, sec, cover, avisoDemora} from '../nucleo/dom.js';
import {J, erroHumano} from '../nucleo/http.js';
import {fmtN, fmtR, fmtData, fmtPct} from '../nucleo/formato.js';

const _norm = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toUpperCase();
const _ind = v => (v == null ? '<span class="dim">INDISPONÍVEL</span>' : v);
const _fonte = b => `<div class="dim" style="font-size:12px;margin:6px 0 10px"><b>Fonte:</b> ${esc(b.fonte || '—')}
  <br><b>Cobertura:</b> ${esc(b.cobertura || '—')}</div>`;
const _indisp = b => card(`<div class="warn">INDISPONÍVEL — ${esc(b.erro || 'bloco sem dado')}. Não é zero.</div>${_fonte(b)}`);
const _link = (u, t) => (u ? `<a href="${esc(u)}" target="_blank" rel="noopener">${t}</a>` : t);

// ── tabelas em lotes ─────────────────────────────────────────────────────────────────────────────────
// Cada linha vive em memória como {h: html da <tr>, o: órgão normalizado, c: camada, g: grau, k: categoria};
// só `mostr` linhas (das que passam no filtro) vão para o DOM.
const _LOTE = 20;
let _T = {};
let _F = {q: '', cam: '', gr: '', cat: ''};
const _passa = r => (!_F.q || r.o == null || r.o.includes(_F.q))
  && (r.c == null || ((!_F.cam || r.c === _F.cam) && (!_F.gr || r.g === _F.gr)))
  && (r.k == null || !_F.cat || r.k === _F.cat);
function _corpo(id){
  const t = _T[id], vis = t.rows.filter(_passa);
  if (!vis.length) return `<tr><td colspan="9" class="dim">${t.rows.length ? 'Nenhuma linha neste filtro.' : 'Sem linhas.'}</td></tr>`;
  return vis.slice(0, t.mostr).map(r => r.h).join('');
}
function _pe(id){
  const t = _T[id], n = t.rows.filter(_passa).length, resta = n - t.mostr;
  if (resta <= 0) return n > _LOTE ? `<div class="dim" style="font-size:12px;margin-top:4px">${fmtN(n)} linha(s).</div>` : '';
  return `<div style="margin-top:6px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
    <span class="dim" style="font-size:12px">Mostrando ${fmtN(t.mostr)} de ${fmtN(n)}</span>
    <button type="button" class="btn ghost" data-gc-mais="${id}">Mostrar mais ${fmtN(Math.min(resta, _LOTE * 2))}</button>
    <button type="button" class="btn ghost" data-gc-mais="${id}" data-gc-todas="1">Mostrar todas (${fmtN(n)})</button></div>`;
}
function _tabela(id, cab, rows, alto){
  _T[id] = {rows, mostr: _LOTE};
  const tb = `<table class="tb gc-txt"><thead><tr>${cab}</tr></thead><tbody data-gc-tb="${id}">${_corpo(id)}</tbody></table>`;
  return `<div style="overflow-x:auto${alto ? `;max-height:${alto}px;overflow-y:auto` : ''}">${tb}</div><div data-gc-pe="${id}">${_pe(id)}</div>`;
}
function _repintar(id){
  const tb = document.querySelector(`#gc-raiz [data-gc-tb="${id}"]`), pe = document.querySelector(`#gc-raiz [data-gc-pe="${id}"]`);
  if (tb) tb.innerHTML = _corpo(id);
  if (pe) pe.innerHTML = _pe(id);
}

const _verifTag = x => (x.verificacao === 'VERIFICADO'
  ? '<span class="tag teal">VERIFICADO</span>'
  : `<span class="tag amber">PENDENTE</span>`) + `<div class="dim" style="font-size:11px;margin-top:2px">${esc(x.verificacao_motivo || '')}</div>`;

function _placar(p, d){
  const ant = p.pago_anterior != null ? `mesma janela de ${d.execucao.anterior.inicio.slice(0, 4)}: ${fmtR(p.pago_anterior)} (${fmtPct(p.variacao_pct)})` : '';
  return `<div class="grid g2" style="margin-top:12px">
    ${kpi(_ind(p.pago == null ? null : fmtR(p.pago)), 'Pago no período (OB SIAFE contabilizada)', null, '💳',
      {sobre: `Soma das Ordens Bancárias com status Contabilizado no SIAFE, de ${d.gestao.inicio} a ${d.gestao.ate}. ${fmtN(p.n_obs)} OB. ${ant}. Inclui repasses entre UGs; empenho não entra.`})}
    ${kpi(_ind(p.contratacoes == null ? null : fmtN(p.contratacoes)), 'Contratações assinadas (TCE-RJ)', null, '📑',
      {sobre: `Valor CONTRATADO: ${fmtR(p.valor_contratado)} — não é pagamento. Canceladas fora.`})}
    ${kpi(_ind(p.diretas == null ? null : fmtN(p.diretas)), 'Dispensas e inexigibilidades', 'var(--amber)', '⚠️',
      {sobre: `Contratações diretas cruzadas pelo nº SEI com as compras diretas do TCE-RJ: ${fmtR(p.valor_diretas)} contratados.`})}
    ${kpi(_ind(p.decretos == null ? null : fmtN(p.decretos)), 'Decretos numerados (DOERJ)', null, '📜',
      {sobre: `${fmtN(p.decretos_orcamentarios)} orçamentários. Só os localizados no texto do DOERJ coletado.`})}
    ${kpi(_ind(p.nomeacoes == null ? null : `${fmtN(p.nomeacoes)} / ${fmtN(p.exoneracoes)}`), 'Nomeações / exonerações (1º escalão)', null, '👤',
      {sobre: 'Secretários de Estado, subsecretários, presidentes, procurador-geral e controlador-geral casados pelo extrator.'})}
    ${kpi(_ind(p.auditorias_50254 == null ? null : fmtN(p.auditorias_50254)), 'Publicações do Decreto 50.254 (auditorias)', null, '🔎',
      {sobre: 'Atos no DOERJ que citam o Decreto 50.254/2026 (auditoria na gestão das secretarias e entidades).'})}
    ${kpi(_ind(p.penalidades_tce == null ? null : fmtN(p.penalidades_tce)), 'Penalidades do TCE-RJ no período', null, '⚖️',
      {sobre: 'Penalidades aplicadas pelo TCE-RJ com data de sessão a partir do início da gestão.'})}
    ${kpi(p.pontos_atencao == null ? '<span class="dim">em andamento</span>' : fmtN(p.pontos_atencao), 'Pontos de atenção', 'var(--rose)', '🟡',
      {sobre: 'Análise em duas camadas (determinística e subjetiva). Indício não é acusação; cada ponto traz a explicação inocente e diz se está VERIFICADO ou PENDENTE.'})}
  </div>`;
}

// Diretriz do dono (13/11/2026): estado VERIFICADO/PENDENTE visível em cada ponto, com a prova primária citada.
// Arquivo antigo sem o campo → "não declarada" (não se presume verificado).
function _verif(x){
  const v = x.verificacao || 'NÃO DECLARADA';
  const cor = v === 'VERIFICADO' ? 'var(--green)' : (v === 'INDISPONÍVEL' ? 'var(--dim)' : 'var(--amber)');
  const prova = (x.prova_primaria || []).map(p => `<div>· ${esc(p)}</div>`).join('');
  return `<div style="font-size:12px;margin-top:3px"><b style="color:${cor}">${esc(v)}</b>${x.grau_proposto ? ` <span class="dim">(grau proposto ${esc(x.grau_proposto)}, rebaixado até a verificação)</span>` : ''}${x.natureza ? ` <span class="dim">· ${esc(x.natureza)}</span>` : ''}
    ${prova ? `<details><summary style="cursor:pointer" class="dim">prova primária citada</summary><div class="dim">${prova}</div></details>` : ''}</div>`;
}

function _pontos(b){
  if (b.estado === 'em_andamento') return card(`<div class="warn">${esc(b.mensagem || 'Análise em andamento.')}</div>${_fonte(b)}`);
  if (b.estado !== 'ok') return card(`<div class="warn">Pontos de atenção INDISPONÍVEIS — ${esc(b.erro || '')}. Não é "nenhum ponto".</div>${_fonte(b)}`);
  if (!b.itens.length) return card(`<div class="dim">A análise foi gravada (${esc(b.atualizado_em || '')}) e não registrou ponto de atenção.</div>${_fonte(b)}`);
  const pc = b.por_camada || {}, pg = b.por_grau || {};
  const nv = b.itens.filter(x => x.verificacao === 'VERIFICADO').length;
  const chip = (k, v, t, on) => `<button type="button" class="chip${on ? ' on' : ''}" data-gc-pt="${k}:${v}">${t}</button>`;
  const rows = b.itens.map(x => ({c: x.camada, g: x.grau, o: _norm(x.orgao), h: `<tr>
      <td style="min-width:150px">${esc(x.grau)} <span class="dim" style="font-size:11px">· ${x.camada === 'deterministica' ? 'determinística' : 'subjetiva'}</span><div style="margin-top:4px">${_verifTag(x)}</div></td>
      <td style="min-width:220px"><b>${esc(x.regra_ou_hipotese || '')}</b><div class="dim" style="font-size:12px">${esc(x.orgao || '')}${x.processo ? ' · ' + esc(x.processo) : ''}${x.fonte ? ' · fonte: ' + esc(x.fonte) : ''}</div>${_verif(x)}</td>
      <td class="right" style="white-space:nowrap">${x.valor_ob == null ? '<span class="dim">—</span>' : fmtR(x.valor_ob)}</td>
      <td style="font-size:13px;min-width:160px">${esc(x.explicacao_inocente)}</td>
      <td style="font-size:13px;min-width:140px">${esc(x.proximo_passo || '')}</td></tr>`}));
  return card(`<div class="dim" style="font-size:12px;margin-bottom:6px"><b>${fmtN(nv)}</b> verificados (credor identificado por CNPJ na fonte) · <b>${fmtN(b.itens.length - nv)}</b> pendentes (agregado, hipótese ou casamento por nome — possível homônimo, não verificado).</div>
    <div class="chips">${chip('camada', '', 'Todas as camadas', 1)}${chip('camada', 'deterministica', `Determinística (${fmtN(pc.deterministica || 0)})`)}${chip('camada', 'subjetiva', `Subjetiva (${fmtN(pc.subjetiva || 0)})`)}</div>
    <div class="chips">${chip('grau', '', 'Todos os graus', 1)}${['🔴', '🟡', '⚪'].map(g => chip('grau', g, `${g} ${fmtN(pg[g] || 0)}`)).join('')}</div>
    <div style="margin-top:8px">${_tabela('pt', '<th>Grau e verificação</th><th>Indício (regra ou hipótese)</th><th class="right">OB</th><th>Explicação inocente</th><th>Próximo passo</th>', rows)}</div>
    <div class="dim" style="font-size:12px;margin-top:6px">Atualizado em ${esc(b.atualizado_em || '—')}. Indício não é acusação: a explicação inocente fica sempre ao lado. VERIFICADO = o fato está na fonte citada; não é juízo de irregularidade.</div>
    ${b.por_verificacao ? `<div class="dim" style="font-size:12px;margin-top:4px"><b>Verificação:</b> ${Object.entries(b.por_verificacao).map(([k, v]) => `${esc(k)} ${fmtN(v)}`).join(' · ')}${b.camada_subjetiva ? ` · camada subjetiva: ${esc(b.camada_subjetiva.estado || '')}${b.camada_subjetiva.motivo ? ' (' + esc(b.camada_subjetiva.motivo) + ')' : ''}` : ''}</div>
      <div class="dim" style="font-size:12px;margin-top:2px">${esc(b.verificacao_definicao || '')}</div>` : '<div class="warn" style="font-size:12px;margin-top:4px">Arquivo sem estado de verificação por ponto — tratar todos como PENDENTES.</div>'}${_fonte(b)}`);
}

function _atos(b){
  if (b.estado === 'indisponivel') return _indisp(b);
  const cat = Object.entries(b.por_categoria || {}).map(([k, v]) => `${esc(k)}: <b>${fmtN(v)}</b>`).join(' · ');
  const decs = (b.decretos || []).map(d => ({k: d.categoria || '', h: `<tr>
      <td style="white-space:nowrap">${_link(d.url, `<b>${esc(d.numero)}</b>`)}<div class="dim" style="font-size:11px">${fmtData(d.data)}</div></td>
      <td style="font-size:13px;min-width:200px">${esc(d.ementa)}</td>
      <td style="white-space:nowrap;font-size:12px">${esc(d.categoria)}${d.valor_ementa ? `<div>${fmtR(d.valor_ementa)}</div>` : ''}</td></tr>`}));
  const pes = (b.pessoal || []).map(a => ({o: _norm(a.orgao), h: `<tr><td style="white-space:nowrap">${fmtData(a.data)}</td>
      <td><b>${a.ato === 'NOMEAR' ? 'Nomeação' : 'Exoneração'}</b></td><td>${esc(a.nome)}</td>
      <td style="font-size:13px;min-width:180px">${esc(a.cargo)} — ${esc(a.orgao)}</td><td>${_link(a.url, 'DOERJ')}</td></tr>`}));
  return card(`${_fonte(b)}<div style="font-size:13px">${cat}</div>
    <div class="dim" style="font-size:12px;margin-top:4px">Orçamentários: ${fmtN(b.n_orcamentarios)} decreto(s); soma dos valores escritos nas ementas ${fmtR(b.valor_orcamentario_ementas)} (crédito aberto ≠ gasto).</div>
    <div class="chips" style="margin-top:8px"><button type="button" class="chip on" data-gc-cat-f="">Todos</button>${Object.keys(b.por_categoria || {}).map(k => `<button type="button" class="chip" data-gc-cat-f="${esc(k)}">${esc(k)}</button>`).join('')}</div>
    <details style="margin-top:8px" open><summary style="cursor:pointer"><b>Decretos numerados</b> (${fmtN((b.decretos || []).length)})</summary>
      ${_tabela('dec', '<th>Decreto</th><th>Ementa</th><th>Tipo</th>', decs)}</details>
    <details style="margin-top:8px" open><summary style="cursor:pointer"><b>Nomeações e exonerações do 1º escalão</b> (${fmtN((b.pessoal || []).length)}) — o próprio ato no DOERJ é a fonte</summary>
      ${_tabela('pes', '<th>Data</th><th>Ato</th><th>Nome</th><th>Cargo — órgão</th><th>Fonte</th>', pes)}</details>`);
}

function _marcas(m){
  return (m || []).map(x => `<div style="font-size:12px">${esc(x.grau)} ${esc(x.rotulo)}</div>`).join('');
}

function _contratacoes(b){
  if (b.estado === 'indisponivel') return _indisp(b);
  const mod = (b.por_modalidade || []).map(m => `<tr><td>${esc(m.modalidade)}</td><td class="right">${fmtN(m.n)}</td><td class="right">${fmtR(m.valor)}</td></tr>`).join('');
  const org = (b.por_orgao || []).map(o => ({o: _norm(o.orgao), h: `<tr><td>${esc(o.orgao)}</td><td class="right">${fmtN(o.n)}</td>
      <td class="right">${fmtN(o.n_diretas)}</td><td class="right">${fmtR(o.valor)}</td></tr>`}));
  const dest = (b.lista || []).map(x => ({o: _norm(x.orgao), h: `<tr><td style="white-space:nowrap">${fmtData(x.data)}<div class="dim" style="font-size:11px">${esc(x.processo || '')}</div></td>
      <td style="font-size:13px;min-width:220px"><b>${esc(x.fornecedor)}</b> <span class="dim" style="font-size:11px">${esc(x.doc_tipo)} ${esc(x.doc)}</span>
        <div>${esc(x.objeto)}</div><div class="dim" style="font-size:11px">${esc(x.orgao)}</div></td>
      <td style="font-size:12px">${esc(x.modalidade)}${x.emergencial_no_objeto ? '<div>objeto cita emergência</div>' : ''}${_marcas(x.marcas)}</td>
      <td class="right" style="white-space:nowrap">${fmtR(x.valor)}</td></tr>`}));
  const ad = b.aditivos || {};
  const adit = (ad.lista || []).map(a => `<tr><td style="white-space:nowrap">${fmtData(a.data)}</td><td>${esc(a.termo || '')} <span class="dim" style="font-size:11px">${esc(a.processo || a.pncp || '')}</span></td>
      <td style="font-size:13px">${esc(a.objeto)}</td><td class="right">${a.valor_acrescido == null ? '—' : fmtR(a.valor_acrescido)}</td></tr>`).join('');
  return card(`${_fonte(b)}
    <div style="font-size:13px"><b>${fmtN(b.n)}</b> contratações · ${fmtR(b.valor)} contratados · <b>${fmtN(b.n_diretas)}</b> diretas (${fmtR(b.valor_diretas)}) ·
      ${fmtN(b.n_marcadas)} com marca de perícia/detector · ${fmtN(b.n_cancelados)} canceladas fora do total</div>
    <div class="grid two" style="margin-top:10px">
      <div style="overflow-x:auto"><table class="tb gc-txt"><thead><tr><th>Modalidade</th><th class="right">Nº</th><th class="right">Contratado</th></tr></thead><tbody>${mod}</tbody></table></div>
      <div>${_tabela('corg', '<th>Órgão</th><th class="right">Nº</th><th class="right">Diretas</th><th class="right">Contratado</th>', org)}</div>
    </div>
    <details style="margin-top:10px" open><summary style="cursor:pointer"><b>Destaques</b> — diretas, emergenciais e marcadas pelos detectores (${fmtN((b.lista || []).length)} de ${fmtN(b.n_destaques)}, maior valor primeiro)</summary>
      ${_tabela('dest', '<th>Data</th><th>Fornecedor e objeto</th><th>Modalidade e marcas</th><th class="right">Contratado</th>', dest)}</details>
    <details style="margin-top:8px"><summary style="cursor:pointer"><b>Termos aditivos publicados no PNCP</b> (${fmtN(ad.n)} · ${fmtR(ad.valor_acrescido)} acrescidos · último coletado ${fmtData(ad.ultimo_coletado)})</summary>
      <div style="overflow-x:auto"><table class="tb gc-txt"><thead><tr><th>Data</th><th>Termo</th><th>Objeto</th><th class="right">Acréscimo</th></tr></thead><tbody>${adit}</tbody></table></div></details>`);
}

function _execucao(b){
  if (b.estado === 'indisponivel') return _indisp(b);
  const a = b.anterior || {};
  const org = (b.por_orgao || []).map(o => ({o: _norm(o.nome), h: `<tr><td style="min-width:180px">${esc(o.nome)} <span class="dim" style="font-size:11px">órgão ${esc(o.orgao)}</span>
      <div class="dim" style="font-size:11px">UG ${(o.ugs || []).map(u => `${esc(u.ug)}: ${fmtR(u.pago)}`).join(' · ')}</div></td>
      <td class="right">${fmtN(o.n_obs)}</td><td class="right" style="white-space:nowrap">${fmtR(o.pago)}</td>
      <td class="right" style="white-space:nowrap">${o.pago_anterior == null ? '<span class="dim">sem OB</span>' : fmtR(o.pago_anterior)}</td>
      <td class="right">${o.variacao_pct == null ? '—' : fmtPct(o.variacao_pct)}</td></tr>`}));
  const cred = (b.credores || []).map(c => ({h: `<tr><td><b>${esc(c.nome)}</b> <span class="dim" style="font-size:11px">${esc(c.tipo)} ${esc(c.doc)}</span></td>
      <td class="right">${fmtN(c.n_obs)}</td><td class="right" style="white-space:nowrap">${fmtR(c.pago)}</td></tr>`}));
  const fora = (b.nao_contabilizadas || []).map(x => `${esc(x.status)}: ${fmtN(x.n)} OB (${fmtR(x.valor)})`).join(' · ');
  return card(`${_fonte(b)}
    <div style="font-size:13px"><b>${fmtR(b.pago)}</b> em ${fmtN(b.n_obs)} OB contabilizadas de ${fmtData(b.inicio)} a ${fmtData(b.fim)} ·
      mesma janela de ${esc(String(a.inicio || '').slice(0, 4))} (gestão anterior): ${fmtR(a.pago)} em ${fmtN(a.n_obs)} OB (${fmtPct(b.variacao_pct)})</div>
    ${fora ? `<div class="dim" style="font-size:12px;margin-top:4px">Fora da soma (não é pagamento): ${fora}</div>` : ''}
    <details style="margin-top:10px" open><summary style="cursor:pointer"><b>Por órgão</b> (${fmtN((b.por_orgao || []).length)})</summary>
      ${_tabela('eorg', `<th>Órgão</th><th class="right">OB</th><th class="right">Pago (gestão)</th><th class="right">Mesma janela ${esc(String(a.inicio || '').slice(0, 4))}</th><th class="right">Variação</th>`, org)}</details>
    <details style="margin-top:8px"><summary style="cursor:pointer"><b>Maiores credores</b> (${fmtN((b.credores || []).length)}; inclui UGs e repasses)</summary>
      ${_tabela('cred', '<th>Credor</th><th class="right">OB</th><th class="right">Pago</th>', cred)}</details>`);
}

function _controle(b){
  if (b.estado === 'indisponivel') return _indisp(b);
  const au = b.auditorias_50254 || {}, tce = b.tce || {}, per = b.pericias || {}, det = b.detectores || {}, cs = b.casos || {};
  const aud = (au.itens || []).map(x => ({o: _norm(x.orgao), h: `<tr><td style="white-space:nowrap">${fmtData(x.data)}</td>
      <td style="font-size:13px;min-width:220px"><b>${esc(x.titulo)}</b>${x.instaura ? ' <span class="dim">· instaura auditoria/comissão</span>' : ''}<div class="dim" style="font-size:12px">… ${esc(x.trecho)} …</div></td>
      <td>${_link(x.url, 'DOERJ')}</td></tr>`}));
  const pen = (tce.itens || []).map(x => ({o: _norm(x.orgao), h: `<tr><td style="white-space:nowrap">${fmtData(x.data)}</td><td>${esc(x.orgao || '')}</td>
      <td>${esc(x.tipo || '')} <span class="dim" style="font-size:11px">${esc(x.processo || '')}</span></td><td class="right">${x.valor == null ? '—' : fmtR(x.valor)}</td></tr>`}));
  const pr = (per.itens || []).map(x => ({h: `<tr><td>${esc(x.grau)} <a href="#" data-gc-dossie="${esc(x.cnpj)}" data-gc-nome="${esc(x.favorecido)}">${esc(x.favorecido)}</a>
      <span class="dim" style="font-size:11px">CNPJ ${esc(x.cnpj)}</span></td><td class="right">${fmtN(x.n_ugs)}</td><td class="right">${fmtR(x.total_pago_pericia)}</td></tr>`}));
  const dt = (det.itens || []).map(x => ({h: `<tr><td>${esc(x.detector)} · UG ${esc(x.ug)}</td><td>${esc(x.cnpj)}</td><td style="font-size:13px">${esc(x.motivo)}</td></tr>`}));
  const casos = cs.estado === 'ok'
    ? ((cs.itens || []).map(x => `<li>${esc(x.grau || x.nivel || '')} <b>${esc(x.titulo)}</b> <span class="dim" style="font-size:12px">— ${esc(x.motivo)}</span></li>`).join('') || '<li class="dim">Nenhum caso do vault cita processo da gestão ou o Decreto 50.254.</li>')
    : `<li class="dim">Casos do vault INDISPONÍVEIS — ${esc(cs.erro || '')}</li>`;
  const td = b.tce_decisoes || {};
  return card(`${_fonte(b)}
    <details open><summary style="cursor:pointer"><b>Auditorias do Decreto 50.254/2026 no DOERJ</b> (${fmtN(au.n)} publicações; ${fmtN(au.n_instauracoes)} instauram auditoria/comissão)</summary>
      ${_tabela('aud', '<th>Data</th><th>Ato</th><th>Fonte</th>', aud)}</details>
    <details style="margin-top:8px"><summary style="cursor:pointer"><b>TCE-RJ — penalidades com sessão no período</b> (${fmtN(tce.n)} · ${fmtR(tce.valor)} · última sessão coletada ${fmtData(tce.ultima_sessao)})</summary>
      ${_tabela('tce', '<th>Sessão</th><th>Órgão</th><th>Tipo</th><th class="right">Valor</th>', pen)}</details>
    ${td.estado === 'indisponivel' ? `<div class="dim" style="font-size:12px;margin-top:6px">Acórdãos do TCE-RJ: INDISPONÍVEL — ${esc(td.motivo || '')}</div>` : ''}
    <details style="margin-top:8px"><summary style="cursor:pointer"><b>Perícias do JFN sobre credores pagos no período</b> (${fmtN(per.n)}; ${fmtN(per.n_vermelho)} 🔴) — credor casado por CNPJ</summary>
      ${_tabela('per', '<th>Fornecedor</th><th class="right">UGs</th><th class="right">Pago (perícia, todo o histórico)</th>', pr)}</details>
    <details style="margin-top:8px"><summary style="cursor:pointer"><b>Achados confirmados dos detectores</b> sobre credores do período (${fmtN(det.n)}) — credor casado por CNPJ</summary>
      ${_tabela('det', '<th>Detector</th><th>CNPJ</th><th>Motivo</th>', dt)}</details>
    <div style="margin-top:10px"><b>Casos do vault</b><ul style="margin:6px 0 0 18px">${casos}</ul></div>`);
}

function _filtrar(){
  const raiz = document.getElementById('gc-raiz'); if (!raiz) return;
  const on = (sel, ds, pad) => { const el = raiz.querySelector(sel); return el ? el.dataset[ds] : pad; };
  _F = {q: _norm((raiz.querySelector('[data-gc-filtro]') || {}).value),
    cam: (on('[data-gc-pt^="camada:"].on', 'gcPt', 'camada:') || 'camada:').split(':')[1],
    gr: (on('[data-gc-pt^="grau:"].on', 'gcPt', 'grau:') || 'grau:').split(':')[1],
    cat: on('[data-gc-cat-f].on', 'gcCatF', '') || ''};
  for (const id of Object.keys(_T)) { _T[id].mostr = _LOTE; _repintar(id); }
}

// Delegação por data-* (catraca do painel: nada de função nova em `window`); ligada no boot por `ligarGovernoCouto()`.
let _ligado = false;
export function ligarGovernoCouto(){
  if (_ligado) return; _ligado = true;
  document.addEventListener('click', ev => {
    const b = ev.target && ev.target.closest && ev.target.closest('[data-gc-pt],[data-gc-cat-f],[data-gc-dossie],[data-gc-mais]');
    if (!b) return;
    ev.preventDefault();
    if (b.dataset.gcDossie) { if (typeof window.abrirDossie === 'function') window.abrirDossie(b.dataset.gcDossie, b.dataset.gcNome || ''); return; }
    if (b.dataset.gcMais) {
      const t = _T[b.dataset.gcMais]; if (!t) return;
      t.mostr = b.dataset.gcTodas ? Infinity : t.mostr + _LOTE * 2;
      _repintar(b.dataset.gcMais); return;
    }
    b.parentNode.querySelectorAll('.chip').forEach(c => c.classList.remove('on'));
    b.classList.add('on');
    _filtrar();
  });
  let _tm = 0;   // digitação no celular: repinta depois de uma pausa, não a cada tecla
  document.addEventListener('input', ev => {
    if (ev.target && ev.target.matches && ev.target.matches('[data-gc-filtro]')) { clearTimeout(_tm); _tm = setTimeout(_filtrar, 180); }
  });
}

export async function renderGovernoCouto(){
  const demora = avisoDemora('e_couto', 4000, 'Montando a aba: OB do SIAFE de dois exercícios, DOERJ e contratações. Logo após um reinício do servidor a primeira montagem leva até ~30 s; depois abre na hora.');
  const d = await J('/api/governo_couto', {tetoMs: 240000});
  clearTimeout(demora);
  _T = {}; _F = {q: '', cam: '', gr: '', cat: ''};
  let h = cover('estado', 'Governo Couto — gestão do governador em exercício',
    'Tudo o que a base do JFN tem sobre a gestão iniciada em 23/03/2026 (interina): atos no DOERJ, contratações, pagamentos por OB do SIAFE e controle. Cada bloco declara fonte e cobertura. Indício não é acusação.', '📜');
  if (!d || d.ok === false) return h + card(`<div class="warn">${erroHumano(d && (d.erro || d))}</div>`);
  const g = d.gestao || {};
  h += card(`<div style="font-size:14px"><b>Período:</b> ${fmtData(g.inicio)} a ${fmtData(g.ate)} · ${g.interina ? '<b>gestão interina</b>' : ''}</div>
    <div class="dim" style="font-size:12px;margin-top:4px"><b>Início:</b> ${esc(g.fonte || '')}</div>
    <div class="dim" style="font-size:12px;margin-top:2px">${esc(g.transicao || '')}</div>`);
  h += sec('Placar do período') + _placar(d.placar || {}, d);
  const ex = d.execucao || {}, ct = d.contratacoes || {};
  const orgs = [...new Set([...(ex.por_orgao || []).map(o => o.nome), ...(ct.por_orgao || []).map(o => o.orgao)])].filter(Boolean).sort();
  h += card(`<label style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><b>Filtrar por órgão</b>
      <input type="search" data-gc-filtro list="gc-orgaos" placeholder="ex.: Saúde, SEPM, Polícia…" style="flex:1;min-width:200px">
      <datalist id="gc-orgaos">${orgs.map(o => `<option value="${esc(o)}">`).join('')}</datalist></label>
    <div class="dim" style="font-size:12px;margin-top:4px">Filtra as linhas de todos os blocos pelo nome do órgão — em TODAS as linhas, não só nas que estão na tela. O placar continua sendo do Estado inteiro.</div>`);
  const pa = d.pontos_atencao || {};
  h += sec('Pontos de atenção', pa.estado === 'ok' ? pa.itens.length : null) + _pontos(pa);
  h += sec('1. Atos do governador e do primeiro escalão') + _atos(d.atos || {});
  h += sec('2. Contratações da gestão') + _contratacoes(ct);
  h += sec('3. Execução financeira — pagamentos por OB do SIAFE') + _execucao(ex);
  h += sec('4. Controle — auditorias, TCE-RJ e JFN') + _controle(d.controle || {});
  h += card(`<div class="dim" style="font-size:12px">${esc(d.ressalva || '')} Gerado em ${esc(d.gerado_em || '')}.</div>`);
  // tabela de TEXTO: .tb alinha à direita (feita para número); aqui texto à esquerda — mesmo ajuste da Comissão
  h += `<style>.gc-txt th,.gc-txt td{text-align:left;vertical-align:top}.gc-txt th.right,.gc-txt td.right{text-align:right}</style>`;
  return `<div id="gc-raiz">${h}</div>`;
}
