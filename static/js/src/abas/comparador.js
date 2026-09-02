/* O COMPARADOR DE PREÇOS — para o MESMO item, quanto cada órgão paga e quanto cada fornecedor
 * cobra. Saiu de `abas/index.js` na v59 (§6.2-B do PAINEL-v58).
 *
 * É o exemplo que mostra por que o eixo do corte é DOMÍNIO e não esfera: esta tela é consumida
 * por `e_comp` (Estado) E por `p_comp` (Prefeitura). Num corte por esfera ela seria um dos seis
 * casos "compartilhados" que o plano apontava como obstáculo, e alguém teria de escolher um dono
 * arbitrário. Como domínio, ela é simplesmente um módulo que dois lugares importam.
 *
 * OS SETE ESTADOS DE VISÃO VIERAM JUNTO, e isso não é arrumação: `_compView`, `_compTermo`,
 * `_compGrupo`, `_compCat`, `_compEsf`, `_compDisp` e `_compOrd` são ESCRITOS de dentro de
 * atributos `on*` do HTML, e por isso cada um tem um `_set_*` que o entrypoint instala na ponte
 * com `defineProperty`. Variável e setter têm de morar no MESMO módulo — `import` é imutável em
 * JavaScript, então um setter separado da variável nem compila. Separá-los seria pedir para o
 * esbuild recusar a build; mantê-los juntos põe o estado ao lado de quem o usa.
 *
 * Cuidado documentado do arquivo original, que continua valendo: a declaração é MÚLTIPLA
 * (`let a=..., b=..., c=...`) e regex de `^export let X` só casa o PRIMEIRO nome. Isso já cegou
 * duas ferramentas desta casa numa sessão só.
 *
 * Sem efeito de topo.
 */
import {$, esc, svgIco, card, kpi, sec, cover, leitura, corta, clk} from '../nucleo/dom.js';
import {drillSeCompleto, registrarDrill} from '../nucleo/drill.js';
import {fmtN, fmtD, fmtR, fmtRc, rot} from '../nucleo/formato.js';
import {J, erroHumano} from '../nucleo/http.js';
import {buscaPag, listaPaginada} from '../nucleo/lista.js';
import {aba} from '../app/estado.js';

// ═══ COMPARADOR DE PREÇOS (quem paga mais/menos pelo mesmo item) ═══
export let _compView='catalogo', _compTermo='', _compGrupo=null, _compCat=null, _compEsf='todas', _compDisp=0, _compOrd='dispersao';
export async function renderComparador(){
  // aba da prefeitura abre já filtrada na esfera municipal (o chip continua trocável)
  if(aba==='p_comp'&&_compEsf==='todas')_compEsf='prefeitura';
  let h=cover(aba==='p_comp'?'prefeitura':'estado','Comparador de preços — quem paga mais e quem paga menos','Para o <b>mesmo item</b> (aluguel de carro, medicamento, refeição…), quanto cada <b>órgão</b> paga e quanto cada <b>fornecedor</b> cobra. E o ranking transversal: quais órgãos <b>gastam melhor</b> o recurso público e quais fornecedores são <b>caros ou baratos</b> vs o mercado. Fonte: preço unitário homologado do PNCP.','💰');
  h+=`<div class="chips" style="margin:6px 0 14px">
    <button type="button" class="chip ${_compView==='catalogo'?'on':''}" onclick="_compView='catalogo';_compGrupo=null;ir(aba)">🗂️ Catálogo por categoria</button>
    <button type="button" class="chip ${_compView==='buscar'?'on':''}" onclick="_compView='buscar';_compGrupo=null;ir(aba)">Buscar item</button>
    <button type="button" class="chip ${_compView==='economia'?'on':''}" onclick="_compView='economia';ir(aba)">Economia possível</button>
    <button type="button" class="chip ${_compView==='dossie'?'on':''}" onclick="_compView='dossie';ir(aba)">Caro + fornecedor suspeito</button>
    <button type="button" class="chip ${_compView==='orgaos'?'on':''}" onclick="_compView='orgaos';ir(aba)">Órgãos que gastam melhor</button>
    <button type="button" class="chip ${_compView==='forn'?'on':''}" onclick="_compView='forn';ir(aba)">Fornecedores caros/baratos</button></div>`;
  if(_compView==='economia')return h+await _compEconomia();
  if(_compView==='dossie')return h+await _compDossie();
  if(_compView==='orgaos')return h+await _compOrgaos();
  if(_compView==='forn')return h+await _compForn();
  if(_compView==='catalogo')return h+await _compCatalogo();
  return h+await _compBuscar();
}
// esfera do comparador (todas as visões respeitam)
export const _compEsfChips=()=>`<div class="chips" style="margin:0 0 10px">
  ${['todas','estado','prefeitura'].map(e=>`<button type="button" class="chip ${_compEsf===e?'on':''}" onclick="_compEsf='${e}';ir(aba)">${e==='todas'?'🌐 Todas as esferas':e==='estado'?'🏛️ Estado':'🏙️ Prefeitura·Rio'}</button>`).join('')}</div>`;
// visão de UM item (órgãos × fornecedores) — usada pelo catálogo E pela busca
export async function _compItemView(voltar){
  const d=await J('/api/comparador/item?esfera='+(_compEsf==='todas'?'':_compEsf)+'&grupo='+encodeURIComponent(_compGrupo.grupo)+'&unidade='+encodeURIComponent(_compGrupo.un||''));
  let h=`<div style="margin:4px 0 10px"><a onclick="_compGrupo=null;ir(aba)">← ${voltar}</a></div>`;
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  h+=`<h3 style="margin:6px 0">${esc(d.exemplo)} <span class="dim">/ ${esc(d.unidade_medida||'')}</span></h3>`;
  h+=`<div class="grid g2">${kpi(fmtR(d.mediana_geral),'Mediana do item','var(--amber)','⚖️',{sobre:'Mediana do preço unitário do MESMO item, entre todos os compradores públicos com compra registrada. Mediana e não média porque uma compra atípica desloca a média e não desloca a mediana. <b>Item diferente não compara</b>: 60% da \'economia\' de uma medição anterior desta casa vinha de comparar produtos que só tinham a descrição parecida.'})}${kpi(fmtN(d.n_orgaos),'Órgãos',null,'🏛️',
        {sobre:'Quantos compradores públicos distintos têm compra registrada deste item. É o que dá sustentação à mediana: mediana calculada sobre poucos órgãos descreve aqueles órgãos, não o mercado.'})}${kpi(fmtN(d.n_fornecedores),'Fornecedores',null,'🏢',
        {sobre:'Quantos fornecedores distintos venderam este item. Número baixo pode significar mercado concentrado — e nesse caso preço acima da mediana diz menos sobre sobrepreço e mais sobre falta de concorrência.'})}${kpi(fmtN(d.n_compras),'Compras',null,'🧾',
        {sobre:'Registros de compra que entraram no cálculo. É o tamanho da amostra: com poucas compras, a mediana é frágil e a razão "× mediana" precisa ser lida com essa reserva.'})}</div>`;
  const linha=x=>{const c=x.vs_geral>=1.5?'var(--rose)':(x.vs_geral<=0.75?'var(--green)':'var(--amber)');
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:center">
      <div style="min-width:0;flex:1"><div style="font-weight:600">${x.id?clk(x.id,x.nome):esc(x.nome||'—')}</div><div class="dim" style="font-size:12px">n=${x.n}</div></div>
      <div class="right"><div class="num" style="font-weight:800;color:${c}">${fmtR(x.mediana)}</div><div class="dim">${x.vs_geral}× a mediana</div></div></div>`,x.vs_geral>=1.5?'hl':'');};
  h+=sec('Órgãos — do que paga MAIS ao que paga MENOS')+`<div class="grid">`+d.orgaos.map(linha).join('')+`</div>`;
  h+=sec('Fornecedores — do mais caro ao mais barato')+`<div class="grid">`+d.fornecedores.slice(0,30).map(linha).join('')+`</div>`;
  return h+`<div class="note">${esc(d.ressalva||'')}</div>`;
}
export const _montarGrupoCard=g=>card(
  `<div onclick='_compGrupo=${JSON.stringify({grupo:g.grupo,un:_unOf(g)})};ir("e_comp")' style="cursor:pointer;display:flex;justify-content:space-between;gap:10px;align-items:center">
    <div style="min-width:0"><div style="font-weight:600">${esc(g.exemplo)} <span class="dim">/ ${esc(g.unidade_medida||'')}</span></div>
    <div class="dim" style="font-size:12.5px">${g.n_orgaos} órgãos · ${g.n_compras} compras · mediana ${fmtR(g.mediana)}</div></div>
    <div class="right"><div class="num" style="font-weight:800;color:${g.dispersao>=5?'var(--rose)':'var(--amber)'}">${g.dispersao!=null?g.dispersao+'×':'—'}</div><div class="dim">${fmtR(g.min)}–${fmtR(g.max)}</div></div></div>`,
  g.dispersao>=10?'hl':'');
export async function _compCatalogo(){
  let h=_compEsfChips();
  if(_compGrupo)return h+await _compItemView('voltar ao catálogo');
  const d=await J('/api/comparador/catalogo?esfera='+(_compEsf==='todas'?'':_compEsf));
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const cats=d.categorias||[];
  if(!_compCat||!cats.find(c=>c.id===_compCat)){
    // MENU: categorias com contagem e amostra do que tem dentro
    h+=`<div class="dim" style="margin:0 0 10px">${fmtN(d.n_grupos)} itens com preço comparável, por categoria — toque para abrir o submenu:</div>`;
    h+=`<div class="grid two">`+cats.map(c=>card(
      `<div onclick="_compCat='${c.id}';ir(aba)" style="cursor:pointer">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
          <div style="font-weight:700;font-size:14.5px">${c.icone} ${esc(c.rotulo)}</div>
          <span class="cnt">${fmtN(c.n)}</span></div>
        <div class="dim" style="margin-top:6px;font-size:12px">${c.grupos.slice(0,3).map(g=>esc((g.exemplo||'').slice(0,38))).join(' · ')}…</div></div>`)).join('')+`</div>`;
    return h+`<div class="note">${esc(d.explicacao||'')}</div>`;
  }
  // SUBMENU: itens da categoria com filtros (dispersão / ordenação / busca no dataset todo)
  const cat=cats.find(c=>c.id===_compCat);
  let gs=cat.grupos.filter(g=>!_compDisp||(g.dispersao||0)>=_compDisp);
  if(_compOrd==='mediana')gs=[...gs].sort((a,b)=>(b.mediana||0)-(a.mediana||0));
  else if(_compOrd==='compras')gs=[...gs].sort((a,b)=>(b.n_compras||0)-(a.n_compras||0));
  h+=`<div style="margin:4px 0 10px"><a onclick="_compCat=null;ir(aba)">← todas as categorias</a></div>`;
  h+=`<h3 style="margin:6px 0 10px">${cat.icone} ${esc(cat.rotulo)} <span class="cnt">${fmtN(gs.length)} de ${fmtN(cat.n)}</span></h3>`;
  h+=`<div class="chips" style="margin:0 0 4px">
    ${[[0,'toda dispersão'],[2,'≥2× (paga o dobro)'],[5,'≥5×'],[10,'≥10× (grave)']].map(([v,r])=>`<button type="button" class="chip ${_compDisp===v?'on':''}" onclick="_compDisp=${v};ir(aba)">${r}</button>`).join('')}</div>
  <div class="chips" style="margin:0 0 6px">
    ${[['dispersao','↕ por dispersão'],['mediana','R$ por mediana'],['compras','nº de compras']].map(([v,r])=>`<button type="button" class="chip ${_compOrd===v?'on':''}" onclick="_compOrd='${v}';ir(aba)">${r}</button>`).join('')}</div>`;
  h+=buscaPag('cat-list','filtrar item dentro da categoria — busca em todos…');
  h+=listaPaginada('cat-list',gs,_montarGrupoCard,60,g=>(g.exemplo||'').slice(0,60));
  return h+`<div class="note">${esc(d.ressalva||'')}</div>`;
}
export async function _compBuscar(){
  let h=_compEsfChips();
  h+=`<div class="search"><span class="mag"></span><input id="comp-in" placeholder="digite o item: luva, computador, café, cimento, detergente…" value="${esc(_compTermo)}" onkeydown="if(event.key==='Enter'){_compTermo=this.value;_compGrupo=null;ir(aba)}"></div>
    <div class="dim" style="margin:6px 0">Enter para buscar. Exemplos que existem na base: <a onclick="_compTermo='luva';_compGrupo=null;ir(aba)">luva</a> · <a onclick="_compTermo='computador';_compGrupo=null;ir(aba)">computador</a> · <a onclick="_compTermo='cafe';_compGrupo=null;ir(aba)">café</a> · <a onclick="_compTermo='cimento';_compGrupo=null;ir(aba)">cimento</a> — ou navegue pelo <a onclick="_compView='catalogo';_compCat=null;ir(aba)">🗂️ Catálogo</a>, sem precisar adivinhar o termo.</div>`;
  if(_compGrupo)return h+await _compItemView('voltar à busca');
  if(!_compTermo)return h;
  const d=await J('/api/comparador/buscar?esfera='+(_compEsf==='todas'?'':_compEsf)+'&termo='+encodeURIComponent(_compTermo));
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  if(!d.grupos.length){
    h+=card(`<div class="warn">Nenhum item casa TODAS as palavras de "${esc(_compTermo)}".</div>`);
    if((d.parecidos||[]).length){
      h+=`<div class="dim" style="margin:10px 0 8px">Mas estes itens casam PARTE do termo — talvez seja um destes:</div>`;
      h+=`<div class="grid">`+d.parecidos.map(_montarGrupoCard).join('')+`</div>`;
    }else h+=`<div class="dim" style="margin:8px 0">Dica: o <a onclick="_compView='catalogo';_compCat=null;ir(aba)">🗂️ Catálogo</a> lista tudo o que é comparável, por categoria.</div>`;
    return h;
  }
  h+=`<div class="dim" style="margin-bottom:8px">${d.n} grupo(s) — clique para ver quem paga mais/menos:</div>`;
  h+=`<div class="grid">`+d.grupos.map(_montarGrupoCard).join('')+`</div>`;
  return h+`<div class="note">${esc(d.ressalva||'')}</div>`;
}
export function _unOf(g){return '';}  // unidade já embutida no grupo; comparar aceita todas as unidades do grupo
export async function _compOrgaos(){
  const d=await J('/api/comparador/orgaos?esfera='+(_compEsf==='todas'?'':_compEsf)+'');
  if(!d.ok)return card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const linha=(x,bom)=>card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:center">
    <div style="min-width:0;flex:1"><div style="font-weight:600">${esc(x.nome||'—')}</div><div class="dim" style="font-size:12px">${x.n_itens} itens comparáveis · ${x.n_compras} compras</div></div>
    <div class="right"><div class="num" style="font-weight:800;color:${bom?'var(--green)':'var(--rose)'}">${x.razao_mediana}×</div><div class="dim">${bom?'abaixo':'acima'} do mercado</div></div></div>`,!bom?'hl':'');
  let h=`<div class="dim" style="margin-bottom:8px">${esc(d.explicacao)}</div>`;
  h+=sec('🟢 Gastam MELHOR (pagam abaixo do mercado)')+`<div class="grid">`+(d.melhores||[]).slice(0,20).map(x=>linha(x,true)).join('')+`</div>`;
  h+=sec('🔴 Pagam ACIMA do mercado (auditar preços)')+`<div class="grid">`+(d.piores||[]).slice(0,20).map(x=>linha(x,false)).join('')+`</div>`;
  return h+`<div class="note">${esc(d.ressalva||'')}</div>`;
}
export async function _compEconomia(){
  const d=await J('/api/comparador/economia?esfera='+(_compEsf==='todas'?'':_compEsf)+'');
  if(!d.ok)return card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  let h=`<div style="text-align:center;margin:10px 0 18px">
    <div class="dim" style="font-size:13px;letter-spacing:.5px">ECONOMIA POTENCIAL IDENTIFICADA (itens comparáveis do PNCP)</div>
    <div style="font-weight:800;font-size:46px;color:var(--green);line-height:1.1;margin:4px 0">${fmtRc(d.economia_total)}</div>
    <div class="dim">se cada compra acima da mediana tivesse pago a <b>mediana de mercado</b> do item · ${fmtN(d.n_compras_acima_mediana)} compras acima da mediana · o número cresce conforme a base de preços do PNCP é coletada</div></div>`;
  const bloco=(titulo,arr,campo,fn)=>{
    let s=sec(titulo)+`<div class="grid">`;
    s+=(arr||[]).slice(0,12).map(x=>card(
      `<div style="display:flex;justify-content:space-between;gap:10px;align-items:center">
        <div style="min-width:0;flex:1"><div style="font-weight:600">${fn(x)}</div><div class="dim" style="font-size:12px">${x.n} compra(s) acima da mediana</div></div>
        <div class="right"><div class="num" style="font-weight:800;color:var(--green)">${fmtRc(x.economia)}</div><div class="dim">economizável</div></div></div>`)).join('');
    return s+`</div>`;
  };
  // destaque: sobrepreço pago a fornecedor JURIDICAMENTE VEDADO (o número mais forte)
  h+=await _blocoVedada();
  h+=bloco('🏛️ Onde a economia está — por ÓRGÃO', d.por_orgao, 'orgao', x=>esc(x.orgao||'—'));
  h+=bloco('📦 Por ITEM', d.por_item, 'item', x=>esc(x.item||'—')+(x.unidade_medida?` <span class="dim">/ ${esc(x.unidade_medida)}</span>`:''));
  h+=bloco(svgIco('🏢')+' Por FORNECEDOR (quem cobrou o excedente)', d.por_fornecedor, 'fornecedor', x=>x.fornecedor_cnpj?clk(x.fornecedor_cnpj,x.fornecedor):esc(x.fornecedor||'—'));
  return h+`<div class="note">${esc(d.ressalva||'')}</div>`;
}
export async function _blocoVedada(){
  const d=await J('/api/comparador/vedada?esfera='+(_compEsf==='todas'?'':_compEsf)+'');
  if(!d.ok||!d.economia_vedada_total)return '';
  const ABR={total:'inidôneas (veda todos)',ente:'impedidas no ente',orgao:'órgão'};
  let h=`<div class="card hl" style="border-color:color-mix(in oklch,var(--rose) 45%,transparent);background:color-mix(in oklch,var(--rose) 6%,var(--card));margin:8px 0 18px">
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap">
      <div style="min-width:0"><div style="font-weight:800;font-size:17px">Destes, pago a fornecedor JURIDICAMENTE VEDADO</div>
      <div class="dim" style="margin-top:3px">Sobrepreço pago a empresa que estava <b>proibida de contratar</b> com aquele ente, <b>vigente à época</b> — o alvo mais forte. Por abrangência: ${Object.entries(d.por_abrangencia).filter(([k,v])=>v>0).map(([k,v])=>`${ABR[k]||k} ${fmtRc(v)}`).join(' · ')||'—'}.</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:30px;color:var(--rose)">${fmtRc(d.economia_vedada_total)}</div><div class="dim">${d.n_compras} compra(s) · ${d.n_fornecedores} fornecedor(es)</div></div>
    </div>`;
  h+=`<div class="grid" style="margin-top:10px">`+(d.por_fornecedor||[]).slice(0,8).map(f=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:center">
      <div style="min-width:0;flex:1">${clk(f.fornecedor_cnpj,f.fornecedor||'—')} <span class="tag ${f.abrangencia==='total'?'rose':'amber'}">${esc(ABR[f.abrangencia]||f.abrangencia)}</span>
      <div class="dim" style="font-size:12px">${(f.exemplos||[]).slice(0,1).map(e=>esc(e.item)+' — pagou '+fmtR(e.preco)+' vs mediana '+fmtR(e.mediana)+' @ '+esc((e.orgao||'').slice(0,30))).join('')}</div></div>
      <div class="right"><div class="num" style="font-weight:800;color:var(--rose)">${fmtRc(f.economia_vedada)}</div></div></div>`)).join('')+`</div></div>`;
  return h;
}
export async function _compDossie(){
  const d=await J('/api/comparador/dossie?esfera='+(_compEsf==='todas'?'':_compEsf)+'');
  if(!d.ok)return card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=`<div class="dim" style="margin-bottom:8px">${esc(d.explicacao)}</div>`;
  registrarDrill('compDoisSinais',{titulo:'Casos com dois ou mais sinais',itens:a.filter(x=>x.sinais.length>=2),nota:'Sinal isolado explica-se; dois pedem verificação.'});
  // total do servidor: só ganha gaveta se a página trouxer o universo
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Casos caro + suspeito','var(--rose)','🚨',drillSeCompleto('compCaroSuspeito',d.n,a,{titulo:'Casos caros E com sinal',nota:'Preço acima da mediana E sinal aceso no mesmo fornecedor — o cruzamento é a fila que rende.'})
        ||{sobre:'Casos em que o preço está acima da mediana E há sinal aceso no mesmo fornecedor. O cruzamento é a fila que rende; nenhum dos dois lados sozinho basta. A gaveta está desligada porque a tela recebe uma página.'})}${kpi(fmtN(d.n_sancionada),'Fornecedor SANCIONADO','var(--rose)','⚖️',
        {sobre:'Casos em que o fornecedor caro também tem registro de sanção. A abrangência importa e viaja em cada linha: sanção de um órgão não alcança toda a Administração, e sanção posterior à compra não a contamina.'})}
      ${kpi(a.length?a[0].vs_mediana+'×':'—','Pior caso (× mediana)','var(--rose)',null,
        {sobre:'O maior múltiplo da mediana entre os casos caro + suspeito. Só vale entre produtos equivalentes: 60% da "economia" de uma medição anterior desta casa vinha de comparar itens diferentes sob descrição parecida.'})}${kpi(a.filter(x=>x.sinais.length>=2).length,'Com ≥2 sinais',null,'🎯',{drill:'compDoisSinais'})}</div>`;
  h+=`<div class="search" style="margin-top:12px"><span class="mag"></span><input placeholder="filtrar por item, órgão ou fornecedor…" oninput="filtrar(this,'#dossie-list .card')"></div>`;
  h+=`<div id="dossie-list" class="grid">`+a.map(x=>{
    const ABR={total:'toda a Adm.',ente:'ente federativo',orgao:'órgão sancionador'};
    const tags=(x.sinais||[]).map(s=>{const ab=s.abrangencia?` (${ABR[s.abrangencia]||s.abrangencia})`:'';
      return `<span class="tag ${s.sinal==='sancionada'?'rose':'amber'}">${esc(s.sinal)}${esc(ab)}</span>`;}).join(' ');
    return card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:700">${esc(x.item)}${x.unidade_medida?` <span class="dim">/ ${esc(x.unidade_medida)}</span>`:''}</div>
      <div class="dim" style="margin-top:2px">venc.: ${clk(x.fornecedor_cnpj,x.fornecedor||'—')} · ${esc((x.orgao||'').slice(0,42))}</div>
      <div class="muted" style="font-size:12.5px;margin-top:4px">${tags}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:var(--rose)">${x.vs_mediana}×</div><div class="dim">${fmtR(x.preco)} vs ${fmtR(x.mediana)}</div></div></div>
      ${leitura(`O órgão <b>${esc(x.orgao)}</b> pagou <b>${fmtR(x.preco)}</b> por "${esc(x.item)}" — <b>${x.vs_mediana}× a mediana</b> de mercado (${fmtR(x.mediana)}) — ao fornecedor <b>${esc(x.fornecedor)}</b>, que é ${esc((x.sinais||[]).map(s=>rot(s.sinal)).join(', '))} por fonte INDEPENDENTE do preço. Preço fora da curva + fornecedor marcado = alvo forte para auditoria. Confirmar o termo de referência.`)}`,
    'hl');}).join('')+`</div>`;
  return h+`<div class="note">${esc(d.ressalva||'')}</div>`;
}
export async function _compForn(){
  const d=await J('/api/comparador/fornecedores?esfera='+(_compEsf==='todas'?'':_compEsf)+'');
  if(!d.ok)return card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const linha=(x,caro)=>card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:center">
    <div style="min-width:0;flex:1"><div style="font-weight:600">${x.id?clk(x.id,x.nome):esc(x.nome||'—')}</div><div class="dim" style="font-size:12px">${x.n_itens} itens · ${x.n_compras} compras</div></div>
    <div class="right"><div class="num" style="font-weight:800;color:${caro?'var(--rose)':'var(--green)'}">${x.razao_mediana}×</div><div class="dim">${caro?'acima':'abaixo'} do mercado</div></div></div>`,caro?'hl':'');
  let h=`<div class="dim" style="margin-bottom:8px">${esc(d.explicacao)}</div>`;
  h+=sec('🔴 Mais CAROS (cobram acima do mercado)')+`<div class="grid">`+(d.mais_caros||[]).slice(0,20).map(x=>linha(x,true)).join('')+`</div>`;
  h+=sec('🟢 Mais BARATOS (cobram abaixo do mercado)')+`<div class="grid">`+(d.mais_baratos||[]).slice(0,20).map(x=>linha(x,false)).join('')+`</div>`;
  return h+`<div class="note">${esc(d.ressalva||'')}</div>`;
}


/* SETTERS DA PONTE — o mesmo mecanismo descrito em `abas/index.js`, para os estados deste domínio. */
export function _set_compView(v){_compView=v;}
export function _set_compCat(v){_compCat=v;}
export function _set_compDisp(v){_compDisp=v;}
export function _set_compEsf(v){_compEsf=v;}
export function _set_compGrupo(v){_compGrupo=v;}
export function _set_compOrd(v){_compOrd=v;}
export function _set_compTermo(v){_compTermo=v;}
