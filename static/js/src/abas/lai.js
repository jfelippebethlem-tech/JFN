// ═══ LAI AUTOMATIZADA — um botão e o requerimento sai (15/09/2026) ═══
// Alvo (processo SEI/Processo.rio, contrato CCON, CNPJ ou nome) → POST /api/lai/gerar → .docx/.md em
// reports/ + registro com prazo em data/lai.db. O protocolo no e-SIC é humano (gov.br do requerente):
// o painel entrega o texto pronto para colar e acompanha o prazo de 20 dias.
import {$, esc, card, kpi, sec, cover} from '../nucleo/dom.js';
import {J, erroHumano} from '../nucleo/http.js';
import {fmtN} from '../nucleo/formato.js';

function _linha(it){
  const venc = it.vencido ? '<span class="warn"> vencido</span>' : '';
  const links = [it.url_docx?`<a href="${esc(it.url_docx)}" target="_blank" rel="noopener">docx</a>`:'', it.url_md?`<a href="${esc(it.url_md)}" target="_blank" rel="noopener">md</a>`:''].filter(Boolean).join(' · ');
  return `<tr><td>#${it.id}</td><td>${esc(it.alvo)}</td><td>${esc(it.esfera||'')}</td><td>${esc(it.status)}${venc}</td>`+
    `<td>${esc(it.protocolo||'—')}</td><td>${esc(it.prazo_resposta||'—')}</td><td>${links||'—'}</td>`+
    `<td><button type="button" class="btn ghost" data-lai="status" data-id="${it.id}" data-st="protocolado">protocolado</button> `+
    `<button type="button" class="btn ghost" data-lai="status" data-id="${it.id}" data-st="respondido">respondido</button> `+
    `<button type="button" class="btn ghost" data-lai="status" data-id="${it.id}" data-st="negado">negado</button></td></tr>`;
}

export async function renderLai(){
  const [d, pz, sd, em] = await Promise.all([J('/api/lai/lista?limite=100', {tetoMs: 15000}),
                                          J('/api/lai/prazos?dias=3', {tetoMs: 15000}),
                                          J('/api/pcrj/saude', {tetoMs: 60000}),
                                          J('/api/pcrj/emergencias?top=40', {tetoMs: 20000})]);
  const itens = (d && d.itens) || [];
  const prot = itens.filter(x=>x.status==='protocolado'), venc = (pz && pz.itens) || itens.filter(x=>x.vencido);
  let h = cover('prefeitura','LAI automatizada','Um botão e o requerimento sai: o alvo vira pedido de acesso à informação fundamentado (Lei 12.527/2011), com os documentos SEI nomeados pelo número e os contratos do ContasRio. O protocolo no e-SIC é humano; aqui fica o texto pronto e o prazo.','📨');
  h += `<div class="grid">
    ${kpi(fmtN(itens.length),'Requerimentos gerados',null,null,{sobre:'Registros em data/lai.db (rascunho → protocolado → respondido/negado/recurso).'})}
    ${kpi(fmtN(prot.length),'Protocolados (aguardando)',null,null,{sobre:'Prazo legal: 20 dias, prorrogável por 10 (art. 11, LAI).'})}
    ${kpi(fmtN(venc.length),'Prazo vencido','var(--rose)',null,{sobre:'Cabe recurso (art. 15) ou reclamação à CGM/CGE.'})}
  </div>`;
  if(sd && sd.ok){
    h += sec('Saúde dos pipelines da Prefeitura', sd.grau_geral);
    h += `<div style="overflow-x:auto"><table class="tb"><thead><tr><th>etapa</th><th>registros</th><th>último</th><th>estado</th><th>se parar</th></tr></thead><tbody>`
      + (sd.etapas||[]).map(e=>`<tr><td>${esc(e.etapa)}</td><td>${fmtN(e.n)}</td><td>${esc((e.ultimo||'—').slice(0,16))}</td><td>${esc(e.grau)} ${esc(e.leitura||'')}</td><td class="dim">${esc(e.acao||'')}</td></tr>`).join('')
      + `</tbody></table></div>`;
  }
  h += sec('Gerar requerimento');
  h += card(`<div class="grid" style="grid-template-columns:2fr 1fr 1fr auto;gap:8px;align-items:end">
      <label>Alvo<br><input id="lai-alvo" class="inp" placeholder="SME-PRO-2025/38233 · 000700.007924/2026-97 · 2509437 · CNPJ · nome" style="width:100%"></label>
      <label>Esfera<br><select id="lai-esfera" class="inp"><option value="">auto</option><option value="prefeitura">Prefeitura do Rio</option><option value="estado">Estado do RJ</option></select></label>
      <label>Telegram<br><select id="lai-tg" class="inp"><option value="1">enviar docx+md</option><option value="0">não enviar</option></select></label>
      <button type="button" class="btn" data-lai="gerar">📨 Gerar requerimento</button>
    </div>
    <label style="display:block;margin-top:8px">Contexto do pedido (opcional)<br><input id="lai-motivo" class="inp" style="width:100%" placeholder="ex.: dispensa por emergência à incumbente enquanto lote do pregão estava sub judice"></label>
    <div id="lai-out" style="margin-top:10px"></div>`);
  const emItens = (em && em.itens) || [];
  if(emItens.length){
    h += sec('Emergências à incumbente (autos lidos) — alvos de LAI', emItens.length);
    h += `<div class="dim" style="margin-bottom:6px">Dispensa por emergência (art. 75, VIII) para quem já era contratado do mesmo órgão; 🔴 = com certame citado ou prorrogação. Indício, não acusação: o botão gera o pedido dos autos.</div>`;
    h += `<div style="overflow-x:auto"><table class="tb"><thead><tr><th></th><th>fornecedor</th><th>órgão</th><th>processo</th><th>pago</th><th>leitura</th><th></th></tr></thead><tbody>`
      + emItens.map(e=>`<tr><td>${esc(e.grau)}</td><td>${esc((e.favorecido_nome||'').slice(0,40))}</td><td>${esc((e.orgao||'').slice(0,34))}</td><td>${esc(e.processo||'')}</td><td>${fmtN(Math.round(e.total_pago||0))}</td><td class="dim">${esc((e.detalhe||'').slice(0,120))}</td>`
        + `<td><button type="button" class="btn ghost" data-lai="alvo" data-alvo="${esc(e.processo||e.contrato)}">📨 LAI</button></td></tr>`).join('')
      + `</tbody></table></div>`;
  }
  h += sec('Requerimentos', itens.length);
  h += itens.length
    ? `<div style="overflow-x:auto"><table class="tb"><thead><tr><th>#</th><th>alvo</th><th>esfera</th><th>status</th><th>protocolo</th><th>prazo</th><th>arquivos</th><th>marcar</th></tr></thead><tbody>${itens.map(_linha).join('')}</tbody></table></div>`
    : card('<div class="dim">Nenhum requerimento ainda. Informe um alvo acima.</div>');
  h += `<div class="dim" style="margin-top:8px">Requerente: <code>data/lai_requerente.json</code> (nome, cargo, CPF, e-mail) — sem ele o texto sai com «placeholders». Canais: Carioca Digital → Acesso à Informação (PCRJ); e-SIC RJ (Estado).</div>`;
  return h;
}

async function laiGerar(){
  const alvo = ($('lai-alvo')?.value||'').trim(); const o = $('lai-out');
  if(!alvo){ o.innerHTML = card('<div class="warn">Informe o alvo.</div>'); return; }
  o.innerHTML = card('<div class="dim">reunindo contratos, documentos SEI e fiscais… (alguns segundos)</div>');
  try{
    const d = await J('/api/lai/gerar',{method:'POST',headers:{'Content-Type':'application/json'},tetoMs:90000,
      body: JSON.stringify({alvo, esfera:$('lai-esfera')?.value||'', motivo:$('lai-motivo')?.value||'', telegram: Number($('lai-tg')?.value||'1')})});
    if(!d || !d.ok){ o.innerHTML = card(`<div class="warn">${erroHumano((d||{}).erro||'a API não respondeu')}</div>`); return; }
    const avisos = (d.avisos||[]).map(a=>`<div class="warn">${esc(a)}</div>`).join('');
    o.innerHTML = card(`<div class="ok">${esc(d.resumo)}</div>${avisos}
      <div class="dim" style="margin-top:6px">Destinatário: ${esc(d.destinatario)}<br>Canal: ${esc(d.canal)}</div>
      <div style="margin-top:8px">${d.url_docx?`<a class="btn ghost" href="${esc(d.url_docx)}" target="_blank" rel="noopener">⬇ .docx</a> `:''}${d.url_md?`<a class="btn ghost" href="${esc(d.url_md)}" target="_blank" rel="noopener">⬇ .md</a> `:''}
        <button type="button" class="btn ghost" data-lai="copiar">📋 copiar texto</button></div>
      <details style="margin-top:8px"><summary>texto do requerimento</summary><pre id="lai-texto" style="white-space:pre-wrap;font-size:12px">${esc(d.texto||'')}</pre></details>`);
    const tb = document.querySelector('table.tb tbody'); if(tb){ tb.insertAdjacentHTML('afterbegin', _linha({...d, status:'rascunho', vencido:false})); }
  }catch(e){ o.innerHTML = card(`<div class="warn">${erroHumano(String(e))}</div>`); }
}

async function laiStatus(id, status){
  let protocolo = null;
  if(status==='protocolado'){ protocolo = window.prompt('Nº do protocolo no e-SIC (opcional):','') || null; }
  try{
    const d = await J('/api/lai/status',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id, status, protocolo})});
    if(!d || !d.ok){ alert(erroHumano((d||{}).erro||'falhou')); return; }
    const it = d.item||{}; const cel = [...document.querySelectorAll('table.tb tbody tr')].find(tr=>tr.firstElementChild && tr.firstElementChild.textContent===`#${id}`);
    if(cel){ cel.outerHTML = _linha({...it, vencido:false}); }
  }catch(e){ alert(erroHumano(String(e))); }
}

/* Delegação por data-lai — sem nome novo no window (teto de globais do painel). */
export function ligarLai(){
  document.addEventListener('click', ev=>{
    const b = ev.target.closest && ev.target.closest('[data-lai]');
    if(!b) return;
    ev.preventDefault();
    const a = b.dataset.lai;
    if(a==='gerar') laiGerar();
    else if(a==='status') laiStatus(Number(b.dataset.id), b.dataset.st);
    else if(a==='copiar'){ const t=$('lai-texto'); if(t && navigator.clipboard) navigator.clipboard.writeText(t.textContent); }
    else if(a==='alvo'){ const i=$('lai-alvo'); if(i){ i.value=b.dataset.alvo||''; i.scrollIntoView({behavior:'smooth',block:'center'}); } laiGerar(); }
  });
}
