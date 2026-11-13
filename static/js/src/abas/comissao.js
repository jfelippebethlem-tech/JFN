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
    const b = ev.target && ev.target.closest && ev.target.closest('[data-com-gerar],[data-com-mais]');
    if(!b) return;
    ev.preventDefault();
    if(b.dataset.comGerar) comissaoGerar(b.dataset.comGerar, b);
    else comissaoMais(b.dataset.comMais, b);
  });
}

export async function renderComissao(){
  let h=cover('estado','Comissão de Orçamento, Finanças, Fiscalização Financeira e Controle',
    'ALERJ · contas do Governo do Estado, TJRJ, MPRJ, Defensoria Pública e TCE-RJ. Peças geradas pelo sistema e, órgão a órgão, os problemas encontrados nos fornecedores. Indício não é acusação.','🏛️');
  h+=await _pecas();
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
