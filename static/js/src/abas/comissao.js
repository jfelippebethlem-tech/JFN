// ═══ COMISSÃO DE ORÇAMENTO, FINANÇAS, FISCALIZAÇÃO FINANCEIRA E CONTROLE (ALERJ) — 13/11/2026 ═══
// Sub-aba de Estado. Pedido do dono: peças da Comissão geradas automaticamente e, órgão a órgão, os
// problemas encontrados nos fornecedores de cada um — Governo do Estado, TJRJ, Defensoria, MPRJ, TCE-RJ (e ALERJ).
// Dados: GET /api/comissao/orgaos (compliance_agent/comissao_orcamento.py) e /api/comissao/pecas.
// Indício não é acusação; valor = OB Contabilizado do SIAFE (empenho nunca é "pago").
import {esc, card, kpi, sec, cover} from '../nucleo/dom.js';
import {J, erroHumano} from '../nucleo/http.js';
import {fmtN, fmtR} from '../nucleo/formato.js';

const _ROT = {
  'T07-DUPLICIDADE-COMP': 'Competência paga 2×',
  'T02-STATUS-PAGO': 'OB anulada sem reemissão',
  'T04-REAJUSTE-MO-CCT': 'Reajuste acima da CCT',
  'T08-GAP-COMPETENCIA': 'Mês sem pagamento (serviço contínuo)',
  'T01-3WAY': 'Cadeia NL→RE→PD→OB',
};

function _rotulo(a){ return _ROT[a.codigo] || a.titulo || a.codigo; }

function _dup(d){
  if(!d) return '';
  const p=[];
  if(d.AFASTADO) p.push(`${fmtN(d.AFASTADO)} afastada(s)`);
  if(d.PENDENTE_CAPTURA) p.push(`${fmtN(d.PENDENTE_CAPTURA)} aguardando NF`);
  if(d.INDETERMINADO) p.push(`${fmtN(d.INDETERMINADO)} sem processo/NF`);
  if(d.CONFIRMADO) p.push(`<b style="color:var(--rose)">${fmtN(d.CONFIRMADO)} confirmada(s)</b>`);
  return p.length?`<div class="dim" style="font-size:12px;margin-top:4px">Duplicidade por competência: ${p.join(' · ')}</div>`:'';
}

function _linhaProblema(p){
  const nome = esc(p.fornecedor||p.cnpj);
  const link = String(p.cnpj||'').replace(/\D/g,'').length===14
    ? `<a href="#" onclick="abrirDossie('${esc(p.cnpj)}','${esc((p.fornecedor||'').replace(/'/g,''))}');return false">${nome}</a>` : nome;
  const ach = (p.achados||[]).map(a=>`<div style="margin-top:4px"><b>${a.status==='CONFIRMADO'?'🔴':'🟡'} ${esc(_rotulo(a))}</b>${a.fonte==='detector'?` <span class="dim" style="font-size:11px">(detector ${esc(a.codigo)})</span>`:''}
      <span class="dim" style="font-size:12px"> — ${esc(String(a.evidencia||'').slice(0,260))}</span></div>`).join('');
  return `<tr>
    <td style="min-width:200px">${link}<div class="dim" style="font-size:11px">${esc(p.tipo_doc||'CNPJ')} ${esc(p.cnpj)} · UG ${esc(p.ug)}</div></td>
    <td class="right" style="white-space:nowrap">${esc(p.grau||'')} ${fmtR(p.total_pago||0)}</td>
    <td style="font-size:13px;text-align:left">${ach}${_dup(p.duplicidade)}</td></tr>`;
}

function _orgao(d){
  const g=d.graus||{};
  const cab=`<summary style="cursor:pointer;display:flex;gap:12px;align-items:baseline;flex-wrap:wrap">
      <b style="font-size:15px">${esc(d.nome)}</b>
      <span class="dim" style="font-size:12px">${esc(d.poder)}${d.nome_oficial&&d.nome_oficial!==d.nome?' · '+esc(d.nome_oficial):''}</span>
      <span style="margin-left:auto;font-size:13px"><b>${fmtN(d.n_problemas)}</b> fornecedor(es) com problema ·
        ${fmtR(d.valor_com_problema)} de ${fmtR(d.total_pago)} pagos · ${fmtN(d.fornecedores)} periciados
        ${g['🔴']?` · <b style="color:var(--rose)">${fmtN(g['🔴'])} 🔴</b>`:''}</span></summary>`;
  const corpo = (d.problemas||[]).length
    ? `<table class="tb" style="margin-top:10px"><thead><tr><th>Fornecedor</th><th class="right">Grau · pago</th><th style="text-align:left">Problemas encontrados</th></tr></thead>
       <tbody>${d.problemas.map(_linhaProblema).join('')}</tbody></table>
       ${d.n_problemas>d.problemas.length?`<div class="dim" style="font-size:12px;margin-top:6px">Mostrando ${fmtN(d.problemas.length)} de ${fmtN(d.n_problemas)} (maior valor pago primeiro).
          <button class="btn ghost" style="margin-left:8px" data-com-mais="${esc(d.orgao)}">Ver todos os ${fmtN(d.n_problemas)}</button></div>`:''}`
    : `<div class="dim" style="margin-top:8px">Nenhum fornecedor com indício neste órgão.</div>`;
  // <summary> tem de ser filho DIRETO do <details>: dentro do card() o navegador mostrava um "▼ Details" solto
  return `<details class="card com-org" data-inst="${d.instituicao_da_comissao?1:0}" ${d.instituicao_da_comissao?'open':''}
     style="margin:12px 0">${cab}${corpo}</details>`;
}

async function _pecas(){
  const p = await J('/api/comissao/pecas');
  if(!p || p.ok===false || !(p.pecas||[]).length) return '';
  const auto = p.pecas.filter(x=>x.gerar), outras = p.pecas.filter(x=>!x.gerar);
  let h = sec('Peças geradas pelo sistema')+`<div class="grid two">`+auto.map(x=>card(
    `<div style="display:flex;gap:8px;align-items:baseline"><span class="dim" style="font-size:12px">${esc(x.id)}</span>
       <div style="font-weight:700">${esc(x.titulo)}</div></div>
     <div class="dim" style="font-size:12px;margin-top:4px">Prazo: ${esc(x.prazo||'—')}</div>
     <div class="dim" style="font-size:11px;margin-top:2px">${esc(x.base||'')}</div>
     <div class="btns">${x.url?`<a class="btn accent" href="${esc(x.url)}" target="_blank" rel="noopener">Abrir última versão</a>`:''}
       <button class="btn ghost" data-com-gerar="${esc(x.id)}">${x.url?'Gerar de novo':'Gerar agora'}</button></div>`)).join('')+`</div>`;
  h += sec('Demais peças da Comissão')+card(`<table class="tb com-txt"><thead><tr><th>Peça</th><th>Base legal</th><th>Prazo</th><th>Para gerar falta</th></tr></thead><tbody>`
    +outras.map(x=>`<tr><td><b>${esc(x.id)}</b> ${esc(x.titulo)}</td><td class="dim" style="font-size:12px">${esc(x.base||'')}</td>
      <td style="font-size:12px">${esc(x.prazo||'')}</td><td class="dim" style="font-size:12px">${esc(x.falta||'')}</td></tr>`).join('')+`</tbody></table>`);
  if((p.calendario||[]).length) h += sec('Calendário da Comissão')+card(`<table class="tb com-txt"><thead><tr><th>Quando</th><th>Evento</th><th>Peças</th></tr></thead><tbody>`
    +p.calendario.map(c=>`<tr><td style="white-space:nowrap"><b>${esc(c.quando)}</b></td><td>${esc(c.evento)}</td><td class="dim">${esc(c.pecas)}</td></tr>`).join('')+`</tbody></table>`);
  // tabela de TEXTO: a classe .tb alinha à direita (feita para número); aqui tudo à esquerda
  h += `<style>.com-txt th,.com-txt td{text-align:left!important;vertical-align:top}</style>`;
  return h;
}

// ═══ PULOS DO GATO — detectores orçamentários com o manual ao lado (13/11/2026) ═══
// GET /api/comissao/pulos?ano=&mes= (compliance_agent/pulos_do_gato.py; rotina semanal tools/pulos_do_gato_semanal.py).
// ESTADO fala do NÚMERO (conferido ou não), nunca da irregularidade. Empenho/dotação/RP nunca aparecem como "pago".
const _MES = ['','jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];
const _EST = {'VERIFICADO':['var(--ok,#1f9d55)','número conferido'],'PENDENTE':['var(--amber,#b7791f)','número a conferir'],'INDISPONÍVEL':['var(--dim,#888)','a fonte não tem o dado']};
const _md = t => esc(t).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/`(.+?)`/g,'<code>$1</code>');

function _selo(e){ const c=_EST[e]||_EST['PENDENTE']; return `<span title="${esc(c[1])}" style="font-size:11px;font-weight:700;color:${c[0]};white-space:nowrap">${esc(e)}</span>`; }

function _pgAchado(a, i){
  const quando = a.ano ? (a.mes?_MES[a.mes]+'/':'')+a.ano : '—';
  return `<tr${i>=25?' class="pg-mais" hidden':''}>
    <td style="white-space:nowrap;text-align:left">${esc(quando)}</td>
    <td style="text-align:left"><b>${esc(a.titulo)}</b>${a.url?` <a href="${esc(a.url)}" target="_blank" rel="noopener" style="font-size:11px">DOERJ</a>`:''}
      <div class="dim" style="font-size:12px;margin-top:2px">${esc(a.detalhe)}</div>
      <div class="dim" style="font-size:11px;margin-top:2px">Fonte: ${esc(a.proveniencia)}</div></td>
    <td class="right" style="white-space:nowrap">${a.valor==null?'—':fmtR(a.valor)}<div class="dim" style="font-size:11px;white-space:normal;max-width:190px">${esc(a.estagio)}</div></td>
    <td style="text-align:left;max-width:200px">${_selo(a.estado)}<div class="dim" style="font-size:11px">${esc(a.por_que_estado)}</div></td></tr>`;
}

function _pgManual(d){
  const m=d.manual, c=(m&&m.campos)||{};
  const campos=Object.keys(c).map(k=>`<div style="margin-top:6px"><b>${esc(k)}.</b> ${_md(c[k])}</div>`).join('');
  const lista=(t,xs)=>(xs||[]).length?`<div style="margin-top:8px"><b>${t}</b><ul style="margin:4px 0 0 18px;padding:0">${xs.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`:'';
  const pv=d.prevalencia||{};
  const taxa=pv.taxa==null?'não medida':(100*pv.taxa).toFixed(2).replace('.',',')+'%';
  return `<div style="font-size:12.5px;line-height:1.45">
    <div class="dim" style="font-size:11px;text-transform:uppercase;letter-spacing:.04em">Manual de orçamento · Pulo ${esc(d.pulo)}</div>
    ${m?`<div style="font-weight:700;margin-top:2px">${esc(m.titulo)}</div>${campos}`:`<div class="dim">Texto do manual não disponível nesta rodada.</div>`}
    <div style="margin-top:10px;padding-top:8px;border-top:1px solid var(--line,#ddd)"><b>Regra do detector.</b> ${esc(d.regra)}</div>
    <div style="margin-top:6px"><b>Dispositivo.</b> ${esc(d.dispositivo)}</div>
    <div style="margin-top:6px"><b>Prevalência medida.</b> ${fmtN(pv.acionados||0)} de ${fmtN(pv.base||0)} (${taxa}) · unidade: ${esc(pv.unidade||'—')}.
      ${pv.acende_sozinho?'Abaixo de 10%: o padrão é raro na base e vale como sinal.':'Em 10% ou mais da base (ou sem base): não acende sozinho, serve de contexto.'}
      ${pv.contexto?esc(pv.contexto):''}</div>
    ${lista('Explicações inocentes a afastar antes de afirmar',d.explicacao_inocente)}${lista('O que a base não vê',d.limites)}
    <div class="dim" style="margin-top:6px;font-size:11px">Dados: ${esc(d.fonte)}</div></div>`;
}

function _pgDetector(d){
  const e=d.estados||{}, n=(d.achados||[]).length;
  const est=Object.keys(e).map(k=>`${fmtN(e[k])} ${k.toLowerCase()}`).join(' · ');
  const corpo = n ? `<table class="tb com-txt"><thead><tr><th>Quando</th><th>Achado</th><th class="right">Valor · o que é</th><th>Estado do número</th></tr></thead>
      <tbody>${d.achados.map(_pgAchado).join('')}</tbody></table>
      ${n>25?`<button class="btn ghost" style="margin-top:6px" data-com-pg-mais="1">Ver os ${fmtN(n)}</button>`:''}`
    : `<div class="dim">Nenhum achado neste recorte${d.n_total?` (${fmtN(d.n_total)} no total, em outros períodos)`:''}.</div>`;
  return `<details class="card com-pg" style="margin:12px 0"><summary style="cursor:pointer;display:flex;gap:12px;align-items:baseline;flex-wrap:wrap">
      <span class="dim" style="font-size:12px">${esc(d.id)}</span><b style="font-size:15px">${esc(d.titulo)}</b>
      <span style="margin-left:auto;font-size:13px"><b>${fmtN(n)}</b> achado(s)${d.n_total!=null&&d.n_total!==n?` de ${fmtN(d.n_total)}`:''} <span class="dim">· ${esc(est||'—')}</span></span></summary>
    <div class="com-pg-grid" style="margin-top:10px">${_pgManual(d)}<div style="min-width:0;overflow-x:auto">${corpo}</div></div></details>`;
}

async function _pulosCorpo(ano, mes){
  const d=await J('/api/comissao/pulos?ano='+encodeURIComponent(ano||0)+'&mes='+encodeURIComponent(mes||0));
  if(!d||d.ok===false) return card(`<div class="warn">${erroHumano(d)}</div>`);
  const anos=(d.anos||[]).map(a=>`<option value="${esc(a)}"${String(a)===String(ano)?' selected':''}>${esc(a)}</option>`).join('');
  const meses=_MES.map((m,i)=>i?`<option value="${i}"${String(i)===String(mes)?' selected':''}>${m}</option>`:'').join('');
  return `<div class="chips" style="align-items:center;gap:8px">
      <label class="dim" style="font-size:12px">Ano <select data-com-pg-f="ano"><option value="0">todos</option>${anos}</select></label>
      <label class="dim" style="font-size:12px">Mês <select data-com-pg-f="mes"><option value="0">todos</option>${meses}</select></label>
      <span class="dim" style="font-size:12px">Achado anual aparece em qualquer mês do seu ano. Gerado em ${esc(d.gerado_em||'')}.</span></div>
    ${card(`<div class="dim" style="font-size:12px">${esc(d.ressalva||'')}</div>`)}
    ${(d.detectores||[]).map(_pgDetector).join('')}
    <style>.com-pg-grid{display:grid;grid-template-columns:minmax(260px,1fr) minmax(0,2fr);gap:18px;align-items:start}
      @media(max-width:900px){.com-pg-grid{grid-template-columns:1fr}}</style>`;
}

async function pulosFiltrar(){
  const box=document.getElementById('com-pulos'); if(!box) return;
  const v=k=>{ const s=box.querySelector(`[data-com-pg-f="${k}"]`); return s?s.value:0; };
  const ano=v('ano'), mes=v('mes');
  box.style.opacity='.5';
  box.innerHTML=await _pulosCorpo(ano, mes);
  box.style.opacity='';
}

async function comissaoMais(orgao, btn){
  if(btn){ btn.disabled=true; btn.textContent='Carregando…'; }
  const d=await J('/api/comissao/orgaos?limite=1000&orgao='+encodeURIComponent(orgao));
  const o=(d&&d.orgaos||[])[0];
  const det=btn&&btn.closest('details');
  if(!o||!det){ if(btn){btn.disabled=false;btn.textContent='Falhou — tentar de novo';} return; }
  const tb=det.querySelector('tbody'); if(tb) tb.innerHTML=o.problemas.map(_linhaProblema).join('');
  btn.parentNode.textContent=`Todos os ${fmtN(o.problemas.length)} fornecedores com problema deste órgão.`;
}

async function comissaoGerar(id, btn){
  if(btn){ btn.disabled=true; btn.textContent='Gerando…'; }
  const r = await J('/api/comissao/pecas/gerar?id='+encodeURIComponent(id), {tetoMs:240000});
  if(btn){ btn.disabled=false; btn.textContent=(r&&r.ok)?'Gerada — abrir':'Falhou'; }
  if(r && r.ok && r.url) window.open(r.url,'_blank','noopener');
}

// Delegação por data-* (catraca do painel: nada de função nova em `window`). Um ouvinte só, no documento,
// ligado pela sequência de boot (`ligarComissao()` em entrada.js) — módulo não tem efeito de topo.
let _ligado = false;
export function ligarComissao(){
  if(_ligado) return; _ligado = true;
  document.addEventListener('click', ev=>{
    const b = ev.target && ev.target.closest && ev.target.closest('[data-com-gerar],[data-com-mais],[data-com-pg-mais]');
    if(!b) return;
    ev.preventDefault();
    if(b.dataset.comGerar) comissaoGerar(b.dataset.comGerar, b);
    else if(b.dataset.comPgMais){ b.closest('details').querySelectorAll('.pg-mais').forEach(e=>e.hidden=false); b.remove(); }
    else comissaoMais(b.dataset.comMais, b);
  });
  document.addEventListener('change', ev=>{
    if(ev.target && ev.target.matches && ev.target.matches('[data-com-pg-f]')) pulosFiltrar();
  });
}

export async function renderComissao(){
  let h=cover('estado','Comissão de Orçamento, Finanças, Fiscalização Financeira e Controle',
    'ALERJ · contas do Governo do Estado, TJRJ, MPRJ, Defensoria Pública e TCE-RJ. Peças geradas pelo sistema e, órgão a órgão, os problemas encontrados nos fornecedores. Indício não é acusação.','🏛️');
  h+=await _pecas();
  h+=sec('Pulos do gato: onde o orçamento esconde, adia ou maquia')+`<div id="com-pulos">${await _pulosCorpo(0,0)}</div>`;
  const d=await J('/api/comissao/orgaos?limite=15');
  if(!d||d.ok===false){ return h+card(`<div class="warn">${erroHumano(d)}</div>`); }
  const t=d.totais||{};
  h+=`<div class="grid g2" style="margin-top:12px">
    ${kpi(fmtN(t.orgaos),'Órgãos com fornecedor periciado',null,'🏛️',{sobre:'Órgãos (UG do SIAFE) que pagaram por OB Contabilizada a ao menos um fornecedor com perícia 🔴/🟡. Mede exposição do órgão, não irregularidade do órgão.'})}
    ${kpi(fmtN(t.fornecedores_com_problema),'Fornecedores com problema','var(--rose)','🟡',{sobre:'Fornecedores com perícia 🔴/🟡 pagos por esses órgãos. Indício a apurar, não conclusão: o grau vem da perícia de fornecedor e pode ser de outro órgão.'})}
    ${kpi(fmtR(t.valor_com_problema),'Pago a fornecedor com problema',null,'💳',
      {sobre:'Soma das OB Contabilizadas no SIAFE aos pares fornecedor×UG com indício. É o valor EXPOSTO, não o valor irregular.'})}
  </div>`;
  h+=sec('Problemas por fornecedor, órgão a órgão')+
    `<div class="chips">
      <button type="button" class="chip on" onclick="this.parentNode.querySelectorAll('.chip').forEach(c=>c.classList.remove('on'));this.classList.add('on');document.querySelectorAll('.com-org').forEach(e=>e.hidden=false)">Todos</button>
      <button type="button" class="chip" onclick="this.parentNode.querySelectorAll('.chip').forEach(c=>c.classList.remove('on'));this.classList.add('on');document.querySelectorAll('.com-org').forEach(e=>e.hidden=e.dataset.inst!=='1')">TJRJ · MPRJ · DPRJ · TCE-RJ · ALERJ</button>
      <button type="button" class="chip" onclick="this.parentNode.querySelectorAll('.chip').forEach(c=>c.classList.remove('on'));this.classList.add('on');document.querySelectorAll('.com-org').forEach(e=>e.hidden=e.dataset.inst==='1')">Governo do Estado (Executivo)</button>
    </div>`;
  h+=(d.orgaos||[]).map(_orgao).join('');
  h+=card(`<div class="dim" style="font-size:12px">${esc(d.ressalva||'')} Gerado em ${esc(d.gerado_em||'')}.</div>`);
  return h;
}
