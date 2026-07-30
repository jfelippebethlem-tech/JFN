
const $=id=>document.getElementById(id);
// ícone da aba = glifo SVG sci-fi (Lucide/ISC), tingido pela esfera. Fallback: emoji.
const svgIco=e=>{const g=window.JFN_ICO&&window.JFN_ICO[e];
  return g?`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" class="jico" aria-hidden="true">${g}</svg>`:e;};
/* v45: _redMotion vive no TOPO. Estava declarado 2.800 linhas abaixo e o boot
   (nucleoStart, canvas do nucleo) o lia antes — ReferenceError de TDZ que
   matava a montagem do nucleo em toda carga. Mesmo motivo do _rjCbs. */
var _redMotion=matchMedia('(prefers-reduced-motion: reduce)').matches;
var _nebVid={};   // cache das sondas HEAD da nebulosa — lido no boot, antes da def
var _rjCbs=[],_rjLoading=false;   // carregador da malha do RJ — declarado no topo (o init usa antes da def de _rjCarregar)
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmtN=n=>(n==null?'—':Number(n).toLocaleString('pt-BR'));
/* pct assinado: o + so aparece quando e positivo — '+-8%' era bug em e_adit */
const fmtPct=p=>(p==null?'—':(p>0?'+':'')+fmtN(p)+'%');
const fmtR=v=>'R$ '+(v==null?'0,00':Number(v).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2}));
const fmtRc=v=>{v=Number(v||0);const a=Math.abs(v);
  if(a>=1e9)return 'R$ '+(v/1e9).toLocaleString('pt-BR',{maximumFractionDigits:1})+' bi';
  if(a>=1e6)return 'R$ '+(v/1e6).toLocaleString('pt-BR',{maximumFractionDigits:1})+' mi';
  if(a>=1e3)return 'R$ '+(v/1e3).toLocaleString('pt-BR',{maximumFractionDigits:0})+' mil';return fmtR(v);};
// 1 retry (só GET) — rede/DB ocupado num instante não pode virar aba "zerada" pro usuário.
// + cache de navegação (TTL 90s, só GET): voltar numa aba já vista abre INSTANTÂNEO sem perder
// informação — o dado expira sozinho e re-busca. Fora do cache: SSE e os status de polling.
const _jCache=new Map();
async function J(ep,opt){
  const isGet=!opt||!opt.method||opt.method==='GET';
  const cacheavel=isGet&&!/\/stream|\/status|\/api\/eventos/.test(ep);
  if(cacheavel){const c=_jCache.get(ep);if(c&&Date.now()-c.t<90000)return c.d;}
  /* TETO DE ESPERA: `fetch` sem AbortController espera para SEMPRE. Uma rota lenta não
     virava erro — virava um card parado em "—" sem explicação nenhuma, indistinguível de
     "não há dado". Foi assim que o "ninhos de fachada" ficou mudo. Agora estoura em 30 s
     e vira mensagem humana, que é honesto: INDISPONÍVEL ≠ 0, mas silêncio ≠ INDISPONÍVEL. */
  const TETO=(opt&&opt.tetoMs)||30000;
  for(let t=0;;t++){
    const ac=('AbortController' in window)?new AbortController():null;
    const relogio=ac?setTimeout(()=>ac.abort(),TETO):0;
    try{const r=await fetch(ep,ac?Object.assign({},opt,{signal:ac.signal}):opt);
      const d=await r.json();
      if(cacheavel&&d&&d.ok!==false)_jCache.set(ep,{t:Date.now(),d});
      return d;}
    catch(e){
      const estourou=e&&e.name==='AbortError';
      if(!isGet||t>=1)return{erro:estourou?`a rota ${ep} não respondeu em ${TETO/1000}s`:String(e)};
      await new Promise(rs=>setTimeout(rs,1200));}
    finally{if(relogio)clearTimeout(relogio);}
  }
}
const card=(h,cls)=>`<div class="card ${cls||''}">${h}</div>`;
// ícone semântico do KPI, deduzido da cor: crítico/dinheiro/ok/info
const _kpiIco=cor=>{const c=String(cor||'');
  if(/rose/.test(c))return'§alert'; if(/gold|amber/.test(c))return'§money';
  if(/green/.test(c))return'§ok'; if(/accent|teal|blue|violet|purple/.test(c))return'§info'; return'';};
// dest (opcional) = id de aba: torna o KPI clicável e leva à aba (ir() troca de esfera sozinho;
// a11yfy() já torna qualquer [onclick] operável por teclado). Ex.: kpi(n,'Alertas ativos',cor,'🚨','e_alertas').
const kpi=(v,l,cor,gl,dest)=>{const ik=_kpiIco(cor);
  const go=dest?` kpi-go" onclick="ir('${dest}')" title="Abrir: ${l}`:'';
  return `<div class="card kpi${go}"><div class="l">${l}</div><div class="v" ${cor?`style="color:${cor}"`:''}>${v}</div>${gl?`<span class="gl">${gl}</span>`:''}${ik?`<span class="kpi-ico" style="color:${cor}" aria-hidden="true">${svgIco(ik)}</span>`:''}</div>`;};
const sec=(t,cnt)=>`<h2 class="sec">${t}${cnt!=null?`<span class="cnt">${cnt}</span>`:''}</h2>`;
const spin=t=>`<div class="skel"><span class="sp"></span>${t||'Carregando…'}</div>`;
const cover=(sph,t,s,ic)=>`<div class="cover ${sph}"><div class="cover-row">${ic?`<span class="cover-seal" aria-hidden="true">${svgIco(ic)}</span>`:''}<div class="cover-tx"><div class="t">${t}</div><div class="s">${s}</div></div></div></div>`;
const leitura=t=>`<div class="leitura">${t}</div>`;
// botão "Gerar PDF" (padrão Kroll) para qualquer aba de inteligência
const btnPdf=tipo=>`<button class="btn ghost" style="flex:0 0 auto;min-width:120px" onclick="gerarPdfIntel('${tipo}',this)">Gerar PDF</button>`;
async function gerarPdfIntel(tipo,el){
  const txt=el.innerHTML;el.innerHTML='<span class="sp" style="width:12px;height:12px"></span> gerando…';el.disabled=true;
  const r=await J('/api/intel/pdf?tipo='+encodeURIComponent(tipo));
  el.disabled=false;el.innerHTML=txt;
  if(r.ok&&r.url){window.open(r.url,'_blank');}
  else{jfnToast('Falha ao gerar o PDF — '+(r.erro||'o servidor não respondeu. Tente de novo em instantes.'),'rose');}
}
// barra de ação da aba (PDF + eventuais extras), colocada logo após o cover
const acoesAba=(tipo,extra)=>`<div class="btns" style="margin:-4px 0 14px">${btnPdf(tipo)}${extra||''}</div>`;
function toggle(el){el.classList.toggle('open');}
function filtrar(inp,sel){const q=inp.value.toLowerCase();document.querySelectorAll(sel).forEach(c=>{c.style.display=c.textContent.toLowerCase().includes(q)?'':'none';});}
// ═══ LISTA PAGINADA incremental — nunca trava o DOM (lote pequeno por vez) e nunca esconde
// dado atrás de um cap fixo (o resto sempre alcançável via "carregar mais", não perdido) ═══
let _pagState={};
function _pagFiltrados(st){
  if(!st.filtro)return st.itens;
  if(!st._idx)st._idx=st.itens.map(x=>JSON.stringify(x).toLowerCase());  // índice 1×, filtra em ms
  return st.itens.filter((_,i)=>st._idx[i].includes(st.filtro));
}
function _pagRenderInner(id){
  const st=_pagState[id];if(!st)return'';
  const itens=_pagFiltrados(st);
  const corpo=itens.slice(0,st.mostrados).map(st.montarCard).join('');
  const restam=itens.length-st.mostrados;
  const nota=st.filtro?`<div class="dim" style="margin:4px 2px 8px">${fmtN(itens.length)} de ${fmtN(st.itens.length)} no filtro — buscando em <b>tudo</b>, não só no que está na tela.</div>`:'';
  const mais=restam>0?`<div style="text-align:center;margin:14px 0"><button class="btn ghost" onclick="_pagMais('${id}')">Carregar mais (${fmtN(restam)} restante${restam===1?'':'s'} de ${fmtN(itens.length)})</button></div>`:'';
  return `${nota}<div class="grid">${corpo}</div>${mais}`;
}
function _pagMais(id){
  const st=_pagState[id];if(!st)return;
  st.mostrados=st.mostrados+st.lote;
  const wrap=$(id+'-wrap');if(wrap)wrap.innerHTML=_pagRenderInner(id);
}
// filtro paginado: varre o DATASET COMPLETO em memória (não só os cards já no DOM)
function filtrarPag(inp,id){
  const st=_pagState[id];if(!st){filtrar(inp,'#'+id+'-wrap .card');return;}
  st.filtro=inp.value.trim().toLowerCase();st.mostrados=st.lote;
  const wrap=$(id+'-wrap');if(wrap)wrap.innerHTML=_pagRenderInner(id);
  _acPagSugerir(inp,id);
}
// autocomplete CONTEXTUAL da seção: sugere nomes que existem NESTA aba (dataset em memória)
function _acPagSugerir(inp,id){
  const st=_pagState[id],box=$(id+'-ac');if(!st||!box)return;
  const q=st.filtro;if(!q||q.length<2||!st.campoSug){box.classList.remove('on');return;}
  const vistos=new Set(),sug=[];
  for(const x of st.itens){
    const v=st.campoSug(x);if(!v)continue;
    const lv=String(v);if(vistos.has(lv))continue;
    if(lv.toLowerCase().includes(q)){vistos.add(lv);sug.push(lv);if(sug.length>=8)break;}
  }
  if(!sug.length){box.classList.remove('on');return;}
  box.innerHTML=sug.map(s=>`<div class="ac-item" onmousedown="event.preventDefault();_acPagPick('${id}',${JSON.stringify(s).replace(/"/g,'&quot;')})">${esc(s)}</div>`).join('');
  box.classList.add('on');
}
function _acPagPick(id,valor){
  const box=$(id+'-ac');if(box)box.classList.remove('on');
  const inp=box&&box.parentElement.querySelector('input');if(!inp)return;
  inp.value=valor;filtrarPag(inp,id);
}
// barra de busca padrão das listas paginadas (filtro no dataset todo + sugestões da própria aba)
const buscaPag=(id,ph)=>`<div class="search" style="margin-top:14px;position:relative"><span class="mag"></span><input placeholder="${ph}" oninput="filtrarPag(this,'${id}')" onblur="setTimeout(()=>{const b=$('${id}-ac');if(b)b.classList.remove('on')},150)"><div class="ac-box" id="${id}-ac"></div></div>`;
function listaPaginada(id,itens,montarCard,lote,campoSug){
  lote=lote||60;
  _pagState[id]={itens,montarCard,lote,mostrados:Math.min(lote,itens.length),filtro:'',campoSug:campoSug||null};
  return `<div id="${id}-wrap">${_pagRenderInner(id)}</div>`;
}
// ordena qualquer lista por NOME do fornecedor (A→Z) e volta à ordem original (por risco/valor)
function ordenar(sel,btn){
  const cont=document.querySelector(String(sel).split(' ')[0]); if(!cont)return;
  const cards=[...cont.querySelectorAll(':scope > .card')]; if(!cards.length)return;
  const chave=c=>((c.querySelector('.clk,b,strong,a')||c).textContent||'').trim().toLowerCase();
  const az=btn.classList.toggle('on');
  if(az){cards.forEach((c,i)=>{if(c.dataset.ord0==null)c.dataset.ord0=i;});
         cards.sort((a,b)=>chave(a).localeCompare(chave(b),'pt'));btn.textContent='A-Z ativo';}
  else{cards.sort((a,b)=>(+a.dataset.ord0)-(+b.dataset.ord0));btn.textContent='A-Z';}
  cards.forEach(c=>cont.appendChild(c));
  const cv=document.querySelector('#view .view-wire'); if(cv)cv.remove();   // posições mudaram → tira malha estática
}
// rótulos humanos p/ ids técnicos de sinal/detector — snake_case NUNCA chega ao usuário
const ROTULOS={conluio_forte:'conluio societário',conluio_qsa:'conluio societário',sancao_a_epoca:'sanção vigente à época',
  sancao_fora_vigencia:'sanção fora da vigência',sancionada:'sancionada (CEIS/CNEP)',socio_servidor:'sócio na folha pública',
  fantasma_alto:'perfil fantasma (alto)',fantasma_medio:'perfil fantasma (médio)',fantasma_baixo:'perfil fantasma (baixo)',
  perdedora_contumaz:'perdedora contumaz',fenix:'empresa fênix',empresa_fenix:'empresa fênix',escalada_preco:'escalada de preço',
  sobrepreco:'sobrepreço unitário',fracionamento:'fracionamento de despesa',capital_incompativel:'capital incompatível',
  fornecedor_dependente:'fornecedor cativo',corrida_dezembro:'corrida de dezembro',socio_oculto:'sócio oculto',
  hub_massa:'membro de ninho (contato/endereço)',capital_irrisorio:'capital irrisório',conluio_medio:'conluio societário (médio)',
  nepotismo:'nepotismo',nepotismo_cruzado:'nepotismo cruzado',porta_giratoria:'porta giratória',
  situacao_irregular:'situação irregular na Receita',endereco_compartilhado:'endereço-ninho',endereco_residencial:'endereço residencial',
  aberta_as_vesperas:'aberta às vésperas',socio_unico_capital_baixo:'sócio único + capital baixo',cnae_incompativel:'CNAE incompatível',
  radar_risco:'radar de risco',prioridade_valor:'prioridade por valor',grafo_familias:'grafo de famílias',aditivos:'aditivos'};
const rot=id=>ROTULOS[id]||String(id||'').replace(/_/g,' ');
const clk=(cnpj,txt)=>{const d=String(cnpj||'').replace(/\D/g,'');return d.length===14?`<button type="button" class="clk" onclick="abrirDossie('${d}','${esc(String(txt)).replace(/'/g,'')}')">${esc(txt)}</button>`:`<b>${esc(txt)}</b>`;};

// ═══ ESFERAS ═══
const SPHERES=[
  {id:'inicio',    ic:'◎', tl:'Início',        c:'command deck ao vivo'},
  {id:'estado',    ic:'🏛️', tl:'Estado',       c:'órgãos estaduais (SIAFE + PNCP)'},
  {id:'prefeitura',ic:'🏙️', tl:'Prefeitura·Rio',c:'município do Rio (PNCP + folha)'},
  {id:'geral',     ic:'🌐', tl:'Transversal',  c:'riscos, busca, poder, ferramentas'},
];
// ═══ RESPONSÁVEIS pelo processo (ordenador · gestor · fiscal) ═══
// Declarado ANTES de TABS de propósito: TABS é `const` e referencia o render na avaliação —
// um `const renderX` declarado depois daria TDZ e mataria o boot em silêncio (já aconteceu).
// `async function` é hoisted, mas a ordem aqui é explícita para quem vier depois.
let _respProc='';
// O payload traz `cargo`, e o extrator às vezes deposita ali o e-mail da assinatura do
// documento. E-mail pessoal de servidor não vai para a tela: mostra-se o cargo só quando é
// cargo. O dado continua no banco; o que não se faz é publicá-lo.
const _ehEmail=s=>/@/.test(String(s||''));
async function renderResponsaveis(){
  let h=cover('estado','Responsáveis pelo processo','Quem responde por um processo SEI: ordenador de despesa, gestor e fiscal do contrato, com ID funcional quando o documento o traz.','🧑‍⚖️');
  h+=`<div class="search"><span class="mag"></span><input id="resp-proc" placeholder="número SEI (ex.: SEI-070002/006145/2024)…" value="${esc(_respProc)}" onchange="_respProc=this.value;ir('e_resp')" onkeydown="if(event.key==='Enter'){_respProc=this.value;ir('e_resp')}"></div>`;
  if(!_respProc.trim())return h+card('<div class="muted">Informe o número do processo. A busca lê o que já foi capturado — ela responde uma pergunta, não varre o acervo.</div>');
  let d;
  try{ d=await J('/api/responsaveis?processo='+encodeURIComponent(_respProc.trim())); }
  catch(e){ return h+card(`<div class="muted">Não foi possível consultar: ${esc(String(e&&e.message||e))}</div>`); }
  if(!d||d.ok===false)return h+card(`<div class="muted">${esc((d&&d.erro)||'consulta sem resposta')}</div>`);
  const ag=d.agentes||[];
  h+=card(`<div style="font-weight:700">${esc(d.processo||_respProc)}</div><div class="dim">${ag.length} responsável(is) identificado(s) nos documentos capturados</div>`);
  if(!ag.length){
    // LACUNA declarada, nunca "não há responsável": em 97% dos processos o ato de designação
    // vive no processo de contratação, não no de pagamento. Confundir os dois produziria
    // acusação falsa de execução sem fiscal.
    return h+card('<div class="muted">Nenhum responsável identificado <b>nos documentos capturados</b>. Isso é lacuna de captura ou de instrução — <b>não</b> afirmação de que o processo corra sem responsável designado: o ato de designação costuma viver no processo de contratação, não no de pagamento.</div>');
  }
  h+=`<div class="grid">`+ag.map(a=>card(
    `<div><div style="font-weight:700">${esc(a.nome||'—')}</div>
     <div class="dim">${esc(String(a.papel||'').replace(/_/g,' '))}${a.id_funcional?` · ID ${esc(a.id_funcional)}`:''}${a.cargo&&!_ehEmail(a.cargo)?` — ${esc(a.cargo)}`:''}</div>
     <div class="dim" style="font-size:12px">origem: ${esc(a.origem||'—')}${a.documento?` · ${esc(a.documento)}`:''}</div></div>`)).join('')+`</div>`;
  const lac=d.lacunas||[];
  if(lac.length)h+=card(`<div style="font-weight:700">Lacunas apontadas</div><ul style="margin:6px 0 0 18px">${lac.slice(0,5).map(l=>`<li>${esc(l.descricao||l.tipo||'—')}</li>`).join('')}</ul>`);
  return h;
}

// ═══════════════════════════════════════════════════════════════════════════════════════════════
// ABAS NOVAS (2026-07-29) — o que estava implementado no backend e invisível para quem decide.
//
// A auditoria mediu: 57 de 158 rotas não tinham NENHUM ponto de entrada no painel, incluindo o
// dossiê completo, o dossiê mestre, a minuta .docx pronta para o gabinete assinar, e todo o eixo
// de vínculos. Rota órfã não é detalhe de UI: é trabalho feito que não vira decisão de fiscalização.
// A catraca que impede isso de voltar a crescer é tests/test_rotas_sem_orfa.py.
//
// ⚠️ Estes renders ficam ANTES de `const TABS` de propósito: TABS é const e referencia o render na
// avaliação — declarar depois daria TDZ e mataria o boot em silêncio (já custou 13 versões).
// ═══════════════════════════════════════════════════════════════════════════════════════════════

// ═══ VÍNCULOS — beneficiário final · parentesco · histórico societário ═══
async function renderVinculos(){
  const s=await J('/api/osint/serie_societaria');
  let h=cover('geral','Vínculos — quem está atrás da empresa, e desde quando',
    'Sobe a cadeia societária de PJ em PJ até chegar à pessoa física (<b>beneficiário final</b>), infere <b>parentesco</b> por eixos calibrados na própria base, e responde <b>desde quando</b> cada vínculo existe — usando a série de snapshots mensais da Receita. Vínculo é indício; parentesco só se prova por certidão.','🕸️');

  // Estado da série: é o denominador. Sem ele, o leitor supõe que o vínculo é atual.
  if(s.ok){
    const n=s.n_snapshots||0, st=s.vinculos_por_status||{};
    h+=`<div class="grid g2">${kpi(fmtN(n),'Snapshots mensais na série',n>=2?'var(--emerald)':'var(--rose)','📅')}
        ${kpi(esc(s.cobertura||'—'),'Janela observada',null,'🗓️')}
        ${kpi(fmtN(st.saiu||0),'Saídas de sócio detectadas','var(--amber)','🚪')}
        ${kpi(fmtN(st.ativo||0),'Vínculos vistos no último mês',null,'✅')}</div>`;
    h+=leitura(n<2
      ? `<b>Série com ${n} snapshot(s).</b> Com menos de dois meses observados, <b>saída de sócio é inobservável</b> — a base da Receita traz data de entrada e nenhuma de saída. Toda pergunta do tipo "era sócio na data do certame?" sai como INDISPONÍVEL, nunca como afastada.`
      : `Série de <b>${n} meses</b> (${esc(s.cobertura)}). Saída de sócio é inferida por <b>diferença entre snapshots</b>: precisão máxima de um mês. Sócio ausente num mês <b>não ingerido</b> não saiu — o mês não foi observado.`);
    h+=`<div class="note" style="margin-top:8px">Fonte: ${esc(s.fonte||'')}</div>`;
  }else{
    h+=card(`<div class="warn">${erroHumano(s.erro)}</div>`);
  }

  h+=sec('Consultar uma empresa');
  h+=card(`<div class="search"><span class="mag"></span>
      <input id="vinc-cnpj" placeholder="CNPJ da empresa (com ou sem pontuação)…"
             onkeydown="if(event.key==='Enter')vincConsultar()"></div>
    <div class="btns" style="margin-top:10px">
      <button type="button" class="btn" onclick="vincConsultar()">Beneficiário final</button>
      <button type="button" class="btn ghost" onclick="vincParentesco()">Parentesco no QSA</button>
      <button type="button" class="btn ghost" onclick="vincTrocas()">Trocas de quadro</button>
      <button type="button" class="btn ghost" onclick="vincGrafo()">Rede de poder</button>
      <button type="button" class="btn ghost" onclick="vincFtm()">Exportar FollowTheMoney</button>
    </div>
    <div class="btns" style="margin-top:8px">
      <button type="button" class="btn ghost" onclick="vincConluioMunicipal()">Conluio municipal (vencedor × perdedora)</button>
      <button type="button" class="btn ghost" onclick="vincResolucao()">Resolução nome → CNPJ</button>
      <button type="button" class="btn ghost" onclick="vincInterposicao()">Perfil de laranja</button>
      <button type="button" class="btn ghost" onclick="vincPatrimonio()">Capacidade × recebido</button>
    </div>
    <div class="dim" style="margin-top:8px">Histórico de uma <b>pessoa</b> (de quais empresas foi sócia):
      <input id="vinc-pessoa" placeholder="nome do sócio…" style="margin-left:6px">
      <button type="button" class="btn ghost" style="margin-left:6px" onclick="vincHistoricoPessoa()">Ver histórico</button>
    </div>
    <div class="dim" style="margin-top:8px">Para <b>"era sócio nesta data?"</b> informe também a data:
      <input id="vinc-data" type="date" style="margin-left:6px">
      <button type="button" class="btn ghost" style="margin-left:6px" onclick="vincNaData()">Verificar na data</button>
    </div>`);
  h+=`<div id="vinc-out"></div>`;

  h+=sec('Calibração dos eixos de parentesco');
  h+=card(`<div class="dim">Nenhuma base aberta brasileira publica filiação. O que sai daqui é
      inferência, e a única forma honesta de inferir é medir a <b>prevalência de cada eixo na própria
      base</b> antes de deixá-lo pesar — um eixo que acende na maioria mede a base, não o alvo.</div>
    <div class="btns" style="margin-top:10px"><button type="button" class="btn ghost" onclick="vincPrevalencia()">Medir na base de hoje</button></div>
    <div id="vinc-prev"></div>`);
  return h;
}

function _vincCnpj(){const v=($('vinc-cnpj')?.value||'').replace(/\D/g,'');return v.length>=8?v:'';}

async function vincConsultar(){
  const c=_vincCnpj(); const o=$('vinc-out'); if(!c){o.innerHTML=card('<div class="warn">Informe um CNPJ.</div>');return;}
  o.innerHTML=card('<div class="dim">subindo a cadeia societária…</div>');
  const d=await J('/api/osint/beneficiario_final?cnpj='+encodeURIComponent(c));
  if(d.ok===false){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const cob=d.cobertura||{}, ps=d.pessoas||[];
  let h=sec('Beneficiário final — '+esc(d.pj||c));
  h+=`<div class="grid g2">${kpi(fmtN(d.n_pessoas),'Pessoas físicas na cadeia',ps.length?'var(--emerald)':'var(--amber)','👤')}
      ${kpi((cob.pct==null?'—':cob.pct+'%'),'Cobertura de QSA da cadeia',cob.pct>=80?null:'var(--amber)','🔍')}
      ${kpi(fmtN(d.saltos_max),'Degraus até a pessoa física')}
      ${kpi(fmtN((d.ciclos||[]).length),'Participações cruzadas circulares',(d.ciclos||[]).length?'var(--rose)':null,'🔄')}</div>`;
  h+=leitura(esc(d.motivo||''));
  if(ps.length){
    h+=`<div class="grid">`+ps.map(p=>card(
      `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
         <div style="min-width:0"><div style="font-weight:700">${esc(p.rotulo)}
           ${p.documentado?'<span class="tag">documento confirmado</span>':'<span class="tag amber">CPF mascarado na fonte</span>'}</div>
           <div class="muted" style="font-size:12.5px;margin-top:3px">${esc((p.caminho||[]).join(' → '))}</div></div>
         <div class="right"><div class="num" style="font-weight:800;font-size:20px">${(p.confianca*100).toFixed(0)}%</div>
           <div class="dim">confiança · ${p.saltos} degrau(s)</div></div></div>`,
      p.confianca>=0.85?'hl':'')).join('')+`</div>`;
  }
  if((d.ciclos||[]).length){
    h+=card(`<div style="font-weight:700">Participação cruzada circular</div>`+
      (d.ciclos||[]).map(c=>`<div class="muted" style="font-size:12.5px">${esc((c||[]).join(' → '))}</div>`).join('')+
      leitura('Empresa A sócia da B, que é sócia da A. É lícito, e é também a estrutura que mais dificulta identificar quem manda — cabe olhar o contrato social.'));
  }
  h+=`<div class="note">${esc((d.documentacao||{}).nota||'')}</div>`;
  h+=`<div class="note">${esc((d.temporalidade||{}).nota||'')}</div>`;
  h+=`<div class="note">${esc(cob.nota||'')}</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  o.innerHTML=h;
}

async function vincParentesco(){
  const c=_vincCnpj(); const o=$('vinc-out'); if(!c){o.innerHTML=card('<div class="warn">Informe um CNPJ.</div>');return;}
  o.innerHTML=card('<div class="dim">medindo eixos…</div>');
  const d=await J('/api/osint/parentesco?cnpj='+encodeURIComponent(c));
  if(!d.ok){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const cor={indicio:'var(--rose)',hipotese:'var(--amber)',hipotese_fraca:null}[d.grau]||null;
  let h=sec('Parentesco inferido — CNPJ raiz '+esc(d.cnpj_basico));
  h+=`<div class="grid g2">${kpi(esc(d.grau||'nenhum eixo'),'Grau',cor,'👪')}
      ${kpi(fmtN(d.n_hipoteses),'Hipóteses')}
      ${kpi(d.falso_positivo_esperado_pct+'%','Falso positivo esperado',d.falso_positivo_esperado_pct>=10?'var(--amber)':null,'📉')}
      ${kpi(fmtN(d.n_socios_pf),'Sócios PF no QSA')}</div>`;
  h+=leitura(esc(d.leitura||''));
  if((d.eixos_acionados||[]).length){
    h+=`<div class="grid">`+(d.eixos_acionados||[]).map(e=>card(
      `<div style="font-weight:700">${esc(e.descricao)}
         ${e.pode_acender_sozinho?'<span class="tag">eixo forte</span>':'<span class="tag amber">não acende sozinho</span>'}</div>
       <div class="dim" style="margin-top:4px">Prevalência na base: <b>${e.prevalencia_na_base_pct}%</b></div>
       ${leitura('Explicação inocente: '+esc(e.explicacao_inocente))}`)).join('')+`</div>`;
  }
  if((d.hipoteses||[]).length){
    h+=sec('Pessoas',d.hipoteses.length);
    h+=`<div class="grid">`+d.hipoteses.map(x=>card(
      `<div style="font-weight:700">${esc((x.pessoas||[]).join('  ·  '))}</div>
       <div class="dim" style="margin-top:3px">${esc(x.onde||'')}${x.familia?' · família '+esc(x.familia):''}
         · hipótese: <b>${esc(x.tipo_provavel)}</b></div>
       <div class="dim">eixos: ${esc((x.eixos||[]).join(', '))}</div>`)).join('')+`</div>`;
  }
  if(d.diligencia){
    h+=card(`<div style="font-weight:700">Diligência que fecha a questão</div>
      <div class="dim" style="margin-top:4px">${esc(d.diligencia.por_que)}</div>
      <ul class="dim">`+(d.diligencia.fontes||[]).map(f=>`<li>${esc(f)}</li>`).join('')+`</ul>
      <div class="note">${esc(d.diligencia.metodologia_citavel)}</div>`);
  }
  o.innerHTML=h;
}

async function vincNaData(){
  const c=_vincCnpj(), dt=($('vinc-data')?.value||''); const o=$('vinc-out');
  if(!c||!dt){o.innerHTML=card('<div class="warn">Informe CNPJ e data.</div>');return;}
  o.innerHTML=card('<div class="dim">consultando a série…</div>');
  const d=await J(`/api/osint/vinculo_na_data?cnpj=${encodeURIComponent(c)}&data=${encodeURIComponent(dt)}`);
  if(!d.ok){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const cor={SIM:'var(--rose)',NAO:null,INDISPONIVEL:'var(--amber)'}[d.resposta]||null;
  let h=sec('Havia vínculo societário em '+esc(dt)+'?');
  h+=`<div class="grid g2">${kpi(esc(d.resposta),'Resposta',cor,'⚖️')}
      ${kpi(esc(d.mes_observado||'—'),'Mês efetivamente observado')}
      ${kpi(d.defasagem_meses==null?'—':d.defasagem_meses,'Defasagem (meses)')}
      ${kpi(fmtN((d.serie||{}).n_meses),'Meses na série')}</div>`;
  if(d.resposta==='INDISPONIVEL') h+=leitura('<b>INDISPONÍVEL não é NÃO.</b> '+esc(d.motivo||''));
  else h+=leitura(esc(d.ressalva||''));
  if((d.socios||[]).length){
    h+=`<div class="grid">`+d.socios.map(s=>card(
      `<div style="font-weight:700">${esc(s.nome)}</div>
       <div class="dim">${esc(s.qualificacao||'—')} · entrada declarada ${esc(s.data_entrada||'—')}</div>`)).join('')+`</div>`;
  }
  if(d.diligencia){
    h+=card(`<div style="font-weight:700">${esc(d.diligencia.orgao)}</div>
      <div class="dim" style="margin-top:4px">${esc(d.diligencia.documento)}</div>
      <div class="note">${esc(d.diligencia.por_que)}</div>
      <div class="note">${esc(d.diligencia.como)}</div>`);
  }
  o.innerHTML=h;
}

async function vincTrocas(){
  const c=_vincCnpj(), dt=($('vinc-data')?.value||''); const o=$('vinc-out');
  if(!c){o.innerHTML=card('<div class="warn">Informe um CNPJ.</div>');return;}
  if(!dt){o.innerHTML=card('<div class="warn">Informe a data de referência (homologação, assinatura ou pagamento).</div>');return;}
  o.innerHTML=card('<div class="dim">procurando trocas de quadro…</div>');
  const d=await J(`/api/osint/trocas_societarias?cnpj=${encodeURIComponent(c)}&data=${encodeURIComponent(dt)}`);
  if(!d.ok){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro||d.motivo)}</div>`);return;}
  let h=sec('Trocas de quadro societário perto de '+esc(dt));
  h+=`<div class="grid g2">${kpi(fmtN(d.n_entradas),'Entradas na janela',d.n_entradas?'var(--amber)':null,'➡️')}
      ${kpi(fmtN(d.n_saidas),'Saídas na janela',d.n_saidas?'var(--amber)':null,'🚪')}
      ${kpi(fmtN(d.janela_meses),'Janela (meses)')}</div>`;
  h+=leitura(esc(d.leitura||''));
  const linhas=[...(d.entradas||[]).map(x=>['entrada',x]),...(d.saidas||[]).map(x=>['saída',x])];
  if(linhas.length){
    h+=`<div class="grid">`+linhas.map(([tipo,x])=>card(
      `<div style="font-weight:700">${esc(x.nome_norm)} <span class="tag ${tipo==='saída'?'amber':''}">${tipo}</span></div>
       <div class="dim">${esc(x.qualificacao||'—')} · visto de ${esc(x.visto_de)} a ${esc(x.visto_ate)}
         ${x.saiu_entre?' · saiu entre '+esc(x.saiu_entre):''}
         ${x.janela_confiavel===0?' · <b>janela com mês não observado</b>':''}</div>`)).join('')+`</div>`;
  }
  o.innerHTML=h;
}

async function vincPrevalencia(){
  const o=$('vinc-prev'); o.innerHTML='<div class="dim">medindo na base…</div>';
  const d=await J('/api/osint/parentesco/prevalencia');
  if(!d.ok){o.innerHTML=`<div class="warn">${erroHumano(d.erro)}</div>`;return;}
  const dec=d.declarado||{};
  let h=`<table class="tb" style="margin-top:10px"><thead><tr><th>Eixo</th><th class="r">Prevalência hoje</th><th class="r">Calibração declarada</th><th>Acende sozinho?</th></tr></thead><tbody>`;
  for(const [k,v] of Object.entries(d.eixos||{})){
    const dd=dec[k]||{}, alerta=v>(dd.prevalencia_medida||0)*1.5;
    h+=`<tr><td>${esc(dd.descricao||k)}</td><td class="r ${alerta?'bad':''}"><b>${v}%</b></td>
        <td class="r dim">${dd.prevalencia_medida==null?'—':dd.prevalencia_medida+'%'}</td>
        <td>${dd.pode_acender_sozinho?'sim':'<span class="dim">não — mede a base</span>'}</td></tr>`;
  }
  h+=`</tbody></table><div class="note">${esc(d.regra||'')}</div>`;
  o.innerHTML=h;
}

// ═══ PEÇAS — os produtos entregáveis que não tinham botão ═══
async function renderPecas(){
  let h=cover('geral','Peças — o que sai daqui assinável',
    'Os produtos completos do motor: <b>dossiê completo</b> por CNPJ, <b>dossiê mestre</b> de licitações por órgão, <b>minuta em .docx</b> pronta para o gabinete assinar (requerimento ALERJ ou representação ao TCE), dossiê pericial de PPP, auditoria de acatamento de parecer e avaliação de conjunto dos certames. Geração assíncrona: o arquivo chega no Telegram e aparece em Relatórios.','📜');
  h+=card(`<div class="search"><span class="mag"></span>
      <input id="pc-alvo" placeholder="CNPJ, nome de fornecedor, órgão ou UG…"></div>
    <div class="dim" style="margin-top:8px">Para acatamento de parecer, informe o número do processo SEI.</div>`);
  const b=(rota,rot,desc,campo)=>card(
    `<div style="font-weight:700">${esc(rot)}</div><div class="dim" style="margin-top:4px">${desc}</div>
     <div class="btns" style="margin-top:10px"><button type="button" class="btn" onclick="pecaGerar('${rota}','${campo}')">Gerar</button></div>`);
  h+=`<div class="grid g2" style="margin-top:12px">`+[
    b('/api/dossie/completo','Dossiê completo (CNPJ)','360 + fachada + cláusulas na íntegra + suspeitas + árvore SEI + parecer + planilha.','cnpj'),
    b('/api/dossie/mestre','Dossiê mestre de licitações','Portfólio de certames do órgão, com ranking por dano e escalada sugerida.','orgao'),
    b('/api/mandato/minuta','Minuta .docx para assinar','Requerimento de informação (ALERJ) ou representação ao TCE-RJ, já fundamentado.','alvo'),
    b('/api/ppp','Dossiê pericial de PPP/concessão','Perícia de parceria público-privada: equilíbrio, aportes, matriz de risco.','alvo'),
    b('/api/sei/acatamento','Acatamento de parecer (art. 53)','O gestor seguiu o parecer jurídico? Divergência não motivada é achado.','processo'),
    b('/api/conjunto/orgao','Avaliação de conjunto dos certames','Lê o órgão como conjunto, não certame a certame — §5 da metodologia.','orgao'),
  ].join('')+`</div><div id="pc-out"></div>`;
  h+=`<div class="note">Toda peça passa pelo gate de neutralidade (nenhum nome interno) e pelo gate de citações (nenhum acórdão inexistente).</div>`;
  return h;
}

async function pecaGerar(rota,campo){
  const v=($('pc-alvo')?.value||'').trim(); const o=$('pc-out');
  if(!v){o.innerHTML=card('<div class="warn">Informe o alvo acima.</div>');return;}
  o.innerHTML=card('<div class="dim">acionando… a geração é assíncrona; o arquivo chega no Telegram e em Relatórios.</div>');
  try{
    const d=await J(rota,{method:'POST',headers:{'Content-Type':'application/json'},
                          body:JSON.stringify({[campo]:v,alvo:v})});
    if(d&&d.ambiguo){
      o.innerHTML=card(`<div style="font-weight:700">${esc(d.pergunta||'Alvo ambíguo')}</div>`+
        `<div class="grid" style="margin-top:8px">`+(d.candidatos||[]).map(c=>
          `<button type="button" class="btn ghost" onclick="$('pc-alvo').value='${esc(c.cnpj||c.ug||c.nome)}';pecaGerar('${rota}','${campo}')">${esc(c.nome||c.razao||c.cnpj)}</button>`).join('')+`</div>`);
      return;
    }
    o.innerHTML=card(`<div class="ok">Acionado.</div><div class="dim" style="margin-top:6px">${esc(d.mensagem||d.status||'A peça chega no Telegram quando terminar.')}</div>`);
  }catch(e){ o.innerHTML=card(`<div class="warn">${erroHumano(String(e))}</div>`); }
}

// ═══ FONTES EXTERNAS — os seis providers que ninguém alcançava ═══
async function renderFontesExternas(){
  let h=cover('geral','Fontes externas — o que se sabe fora da nossa base',
    'Consulta pontual às fontes abertas já integradas: cadastro da Receita, idoneidade (CEIS/CNEP), estrutura societária global (GLEIF), vazamentos indexados (ICIJ), rastro na web e diário oficial municipal. Todas gratuitas; nenhuma exige chave paga.','🛰️');
  h+=card(`<div class="search"><span class="mag"></span>
      <input id="fx-alvo" placeholder="CNPJ, CPF mascarado, nome ou domínio…"
             onkeydown="if(event.key==='Enter')fxConsultar('/api/empresa')"></div>
    <div class="btns" style="margin-top:10px;flex-wrap:wrap">
      <button type="button" class="btn" onclick="fxConsultar('/api/empresa')">Cadastro (Receita)</button>
      <button type="button" class="btn ghost" onclick="fxConsultar('/api/idoneidade')">Idoneidade</button>
      <button type="button" class="btn ghost" onclick="fxConsultar('/api/ownership')">Estrutura (GLEIF)</button>
      <button type="button" class="btn ghost" onclick="fxConsultar('/api/leaks')">Vazamentos (ICIJ)</button>
      <button type="button" class="btn ghost" onclick="fxConsultar('/api/links')">Rastro na web</button>
      <button type="button" class="btn ghost" onclick="fxConsultar('/api/diario')">Diário oficial</button>
    </div>`);
  h+=`<div id="fx-out"></div>`;
  h+=`<div class="note">Ausência de resultado numa fonte externa é <b>INDISPONÍVEL</b>, não prova de inexistência: a cobertura de cada base é parcial e declarada por ela mesma.</div>`;
  /* v49: o que cada fonte NÃO tem deixa de viver só em prosa de handoff. Fonte que falha calada
     devolve lista vazia, e lista vazia vira "nada encontrado" no parecer — afirmação falsa por
     omissão. Aqui o limite é DADO, e a tabela diz se é bloqueio (contornável) ou limite da fonte. */
  const lim=await J('/api/fontes/limites');
  if(lim&&lim.ok&&(lim.itens||[]).length){
    h+=sec(`Limites conhecidos das fontes — ${lim.bloqueios} bloqueio(s), ${lim.limites_de_dado} limite(s) de dado`);
    h+=card(`<table><thead><tr><th>Fonte</th><th>Tipo</th><th>O que acontece</th><th>Caminho alternativo</th><th>Medido</th></tr></thead><tbody>`
      +lim.itens.map(x=>`<tr>
          <td><b>${esc(x.fonte)}</b></td>
          <td><span class="pill ${x.tipo==='bloqueio'?'medio':'alto'}">${x.tipo==='bloqueio'?'bloqueio':'limite da fonte'}</span></td>
          <td>${esc(x.o_que_acontece)}</td>
          <td class="dim">${esc(x.caminho_alternativo)}</td>
          <td class="dim">${esc(x.medido_em)}</td></tr>`).join('')
      +`</tbody></table>
        <div class="note">Um <b>bloqueio</b> pode cair amanhã e vale retentar; um <b>limite da fonte</b> não —
        a base simplesmente não tem aquele campo, e insistir é queimar sessão. Este quadro existe para
        a peça escrever <b>LACUNA nomeada</b> em vez de "nada encontrado".</div>`);
  }
  return h;
}

async function fxConsultar(rota){
  const v=($('fx-alvo')?.value||'').trim(); const o=$('fx-out');
  if(!v){o.innerHTML=card('<div class="warn">Informe o alvo.</div>');return;}
  o.innerHTML=card('<div class="dim">consultando…</div>');
  const d=await J(rota+'?alvo='+encodeURIComponent(v)+'&cnpj='+encodeURIComponent(v)+'&q='+encodeURIComponent(v));
  if(d&&d.ok===false){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  o.innerHTML=sec(esc(rota.replace('/api/','')))+card(
    `<pre style="white-space:pre-wrap;font-size:12px;margin:0">${esc(JSON.stringify(d,null,1))}</pre>`);
}

// ═══ HUB FÍSICO — uma âncora, vários CNPJs (detector novo que nasceu sem aba) ═══
async function renderHubFisico(){
  const d=await J('/api/intel/hub_compartilhado?limite=150');
  if(!d.ok)return sec('Hub compartilhado')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||d.hubs||[];
  let h=cover('geral','Hub físico — uma âncora, vários fornecedores',
    'Endereço, telefone ou e-mail <b>idêntico</b> em empresas distintas que vendem ao Estado. A lição já paga: <b>mesma sala</b> significa muito, <b>mesmo prédio</b> quase nada — o topo do acervo por prédio é um endereço com 318 CNPJs. Só a âncora com complemento (sala/andar) pesa.','🏢')+acoesAba('hub_compartilhado');
  h+=`<div class="grid g2">${kpi(fmtN(a.length),'Hubs','var(--amber)','🏢')}
      ${kpi(fmtN(a.reduce((s,x)=>s+(x.n_cnpjs||x.n||0),0)),'CNPJs envolvidos')}
      ${kpi(fmtN(a.filter(x=>(x.tipo||'').includes('sala')||x.complemento).length),'Com complemento (sala/andar)','var(--rose)','🚪')}</div>`;
  h+=`<div class="search" style="margin-top:12px"><span class="mag"></span><input placeholder="filtrar por âncora ou empresa…" oninput="filtrar(this,'#hub-list .card')"></div>`;
  h+=`<div id="hub-list" class="grid">`+a.map(x=>card(
    `<div style="font-weight:700">${esc(x.ancora||x.endereco||x.valor||'—')} <span class="tag">${esc(x.tipo||'endereço')}</span></div>
     <div class="muted" style="font-size:12.5px;margin-top:3px">${esc((x.empresas||x.cnpjs||[]).join(' · '))}</div>
     <div class="dim" style="margin-top:4px">${fmtN(x.n_cnpjs||x.n||(x.empresas||[]).length)} empresas</div>`,
    (x.n_cnpjs||x.n||0)>=4?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'Coworking, escritório virtual e prédio comercial hospedam empresas sem relação — a âncora é indício, não prova.')}</div>`;
  return h;
}

// ═══ ACURÁCIA — o motor medido, publicado junto do produto ═══
async function renderAcuracia(){
  let h=cover('geral','Acurácia — o quanto o juízo do motor acerta',
    'Publica a métrica do próprio motor: acurácia do juízo jurídico contra o conjunto-ouro de casos do TCU (F1 macro contra baseline burro) e o <b>lift</b> de cada detector — quantas vezes ele acerta acima da taxa-base. Detector com lift abaixo de 1 é <b>anti-preditivo</b>: acende mais no regular que no irregular.','🎯');
  const [he,lf]=await Promise.all([J('/api/eval/hermeneutica'),J('/api/eval/lift')]);
  if(he&&he.ok!==false){
    h+=sec('Juízo jurídico (conjunto-ouro TCU)');
    h+=`<div class="grid g2">${kpi(he.f1_macro==null?'—':Number(he.f1_macro).toFixed(3),'F1 macro',null,'⚖️')}
        ${kpi(he.baseline_f1==null?'—':Number(he.baseline_f1).toFixed(3),'F1 do baseline burro')}
        ${kpi(he.acuracia==null?'—':(100*he.acuracia).toFixed(1)+'%','Acurácia')}
        ${kpi(he.n==null?'—':fmtN(he.n),'Casos rotulados')}</div>`;
    if(he.alucinacao_citacao!=null)
      h+=leitura(`Alucinação de citação: <b>${(100*he.alucinacao_citacao).toFixed(1)}%</b>. Abstenção: ${he.abstencao==null?'—':(100*he.abstencao).toFixed(0)+'%'} — abster-se é resultado honesto, não falha.`);
  }else h+=card(`<div class="dim">Acurácia do juízo indisponível nesta execução${he&&he.erro?': '+esc(he.erro):''}.</div>`);

  if(lf&&lf.ok!==false){
    const ds=lf.detectores||lf.itens||[];
    h+=sec('Lift por detector',ds.length);
    if(lf.taxa_base!=null) h+=`<div class="dim">Taxa-base do acervo: <b>${(100*lf.taxa_base).toFixed(2)}%</b>. Lift 1,0 = o detector não informa nada.</div>`;
    h+=`<table class="tb" style="margin-top:10px"><thead><tr><th>Detector</th><th class="r">Lift</th><th class="r">n</th><th>Leitura</th></tr></thead><tbody>`;
    for(const d of ds){
      const L=Number(d.lift||0);
      const cls=L<1?'bad':(L>=3?'ok':'');
      const lei=L<1?'ANTI-preditivo — acende mais no regular':(d.circular?'lift alto porém CIRCULAR (usa sanção como insumo)':(L>=3?'discrimina bem':'informa pouco'));
      h+=`<tr><td>${esc(d.detector||d.id)}</td><td class="r ${cls}"><b>${L.toFixed(2)}</b></td>
          <td class="r dim">${fmtN(d.n)}</td><td class="dim">${esc(lei)}</td></tr>`;
    }
    h+=`</tbody></table>`;
    h+=`<div class="note">Lift alto por circularidade não é mérito: se o detector usa sanção como insumo e a sanção é o alvo, ele está prevendo o passado.</div>`;
  }else h+=card(`<div class="dim">Lift indisponível nesta execução${lf&&lf.erro?': '+esc(lf.erro):''}.</div>`);
  return h;
}


async function vincGrafo(){
  const c=_vincCnpj(); const o=$('vinc-out'); if(!c){o.innerHTML=card('<div class="warn">Informe um CNPJ.</div>');return;}
  o.innerHTML=card('<div class="dim">montando a rede…</div>');
  const d=await J('/api/grafo?alvo='+encodeURIComponent(c)+'&saltos=2');
  if(d&&d.ok===false){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const nos=d.nos||[], ar=d.arestas||[];
  o.innerHTML=sec('Rede de poder — 2 saltos')+
    `<div class="grid g2">${kpi(fmtN(nos.length),'Nós')}${kpi(fmtN(ar.length),'Arestas')}
      ${kpi(fmtN((d.comunidades||[]).length),'Comunidades')}</div>`+
    card(`<div class="dim">A rede completa, navegável, abre em tela própria.</div>
      <div class="btns" style="margin-top:8px"><a class="btn ghost" target="_blank" href="/graph?alvo=${encodeURIComponent(c)}">Abrir grafo</a></div>`)+
    leitura('A aresta por <b>nome sem documento</b> vale pouco (homonímia). Para vínculo que pesa numa peça, use o beneficiário final — ele sobe a cadeia por documento.');
}
async function vincFtm(){
  const c=_vincCnpj(); const o=$('vinc-out'); if(!c){o.innerHTML=card('<div class="warn">Informe um CNPJ.</div>');return;}
  o.innerHTML=card('<div class="dim">exportando…</div>');
  const d=await J('/api/grafo/ftm?alvo='+encodeURIComponent(c)+'&saltos=2');
  if(d&&d.ok===false){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const ents=d.entidades||d.entities||[];
  o.innerHTML=sec('FollowTheMoney')+card(
    `<div class="dim">${fmtN(ents.length)} entidade(s) no vocabulário FtM — interopera com Aleph e Gephi sem migrar nada.</div>
     <pre style="white-space:pre-wrap;font-size:11.5px;margin-top:8px;max-height:300px;overflow:auto">${esc(JSON.stringify(ents.slice(0,20),null,1))}</pre>`);
}
async function vincHistoricoPessoa(){
  const n=($('vinc-pessoa')?.value||'').trim(); const o=$('vinc-out');
  if(!n){o.innerHTML=card('<div class="warn">Informe o nome do sócio.</div>');return;}
  o.innerHTML=card('<div class="dim">consultando a série…</div>');
  const d=await J('/api/osint/historico_socio?nome='+encodeURIComponent(n));
  if(!d.ok){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const vs=d.vinculos||[];
  if(!vs.length){o.innerHTML=card(`<div class="note">Nenhum vínculo desta pessoa na série. <b>INDISPONÍVEL não é ausência</b>: a série cobre só as raízes-alvo do acervo, não o Brasil inteiro.</div>`);return;}
  let h=sec('Sociedades de '+esc(n),vs.length)+`<table class="tb"><thead><tr><th>CNPJ raiz</th><th>Qualificação</th><th>Visto de</th><th>até</th><th>Situação</th></tr></thead><tbody>`;
  for(const v of vs)
    h+=`<tr><td>${esc(v.cnpj_basico)}</td><td class="dim">${esc(v.qualificacao||'—')}</td>
        <td>${esc(v.visto_de)}</td><td>${esc(v.visto_ate)}</td>
        <td class="${v.status==='saiu'?'bad':''}">${esc(v.status)}${v.saiu_entre?' ('+esc(v.saiu_entre)+')':''}${v.janela_confiavel===0?' ⚠ janela com mês não observado':''}</td></tr>`;
  h+=`</tbody></table>`;
  o.innerHTML=h;
}


async function vincConluioMunicipal(){
  const o=$('vinc-out'); o.innerHTML=card('<div class="dim">cruzando QSA de vencedores e perdedoras…</div>');
  const d=await J('/api/osint/conluio_municipal?limite=400');
  if(!d.ok){o.innerHTML=card(`<div class="warn">${erroHumano(d.motivo||d.erro)}</div>`);return;}
  const c=d.cobertura||{};
  let h=sec('Conluio municipal — sócio em comum entre vencedor e perdedora');
  h+=`<div class="grid g2">${kpi(fmtN(d.n_certames_com_achado),'Certames com achado',d.n_certames_com_achado?'var(--rose)':null,'🤝')}
      ${kpi(fmtN(d.n_pares),'Pares vencedor × perdedora')}
      ${kpi(fmtN(c.cruzaveis_com_qsa_dos_dois_lados),'Certames efetivamente cruzados')}
      ${kpi((c.taxa_de_achado_pct==null?'—':c.taxa_de_achado_pct+'%'),'Taxa de achado')}</div>`;
  h+=leitura(`O eixo devolvia zero por falta de <b>dado</b>, não de motor: eram <b>114</b> certames com
     classificado além do 1º lugar em todo o acervo. Hoje são <b>${fmtN(c.com_vencedor_e_perdedora_resolvidos)}</b>
     com vencedor e perdedora resolvidos, e <b>${fmtN(c.cruzaveis_com_qsa_dos_dois_lados)}</b> com QSA dos dois lados.
     ${esc(c.nota||'')}`);
  if((d.achados||[]).length){
    h+=`<div class="search" style="margin-top:12px"><span class="mag"></span><input placeholder="filtrar por município, CNPJ ou sócio…" oninput="filtrar(this,'#cm-list .card')"></div>`;
    h+=`<div id="cm-list" class="grid">`+d.achados.map(a=>card(
      `<div style="font-weight:700">${esc(a.certame)}</div>
       <div class="dim" style="margin-top:3px">vencedor <b>${esc(a.vencedor_raiz)}</b> × perdedora <b>${esc(a.perdedora_raiz)}</b>
         · aresta ${esc(a.tipo_aresta)} (força ${a.forca_aresta})</div>
       <div style="margin-top:4px">Sócio(s) em comum: <b>${esc((a.socios_em_comum||[]).join(' · '))}</b></div>
       ${leitura('Veredito: <b>'+esc(a.veredito)+'</b>. '+esc(a.explicacao_inocente))}`,'hl')).join('')+`</div>`;
  }else{
    h+=card('<div class="note">Nenhum par com sócio em comum nos certames cruzados. Isso vale só para os cruzados — o resto é INDISPONÍVEL.</div>');
  }
  h+=(d.ressalvas||[]).map(r=>`<div class="note">${esc(r)}</div>`).join('');
  o.innerHTML=h;
}

async function vincResolucao(){
  const o=$('vinc-out'); o.innerHTML=card('<div class="dim">consultando…</div>');
  const d=await J('/api/osint/resolucao_nome_cnpj');
  if(!d.ok){o.innerHTML=card(`<div class="warn">${erroHumano(d.motivo||d.erro)}</div>`);return;}
  o.innerHTML=sec('Resolução razão social → CNPJ (catálogo nacional da Receita)')+
    `<div class="grid g2">${kpi(fmtN(d.nomes),'Nomes no universo')}
      ${kpi(fmtN(d.resolvidos),'Resolvidos','var(--emerald)','✅')}
      ${kpi(fmtN(d.ambiguos),'Ambíguos (CNPJ nulo)','var(--amber)','⚖️')}
      ${kpi(d.pct_resolvido+'%','Taxa de resolução')}</div>`+
    leitura('Contra o catálogo LOCAL a taxa era de <b>13,9%</b>. O problema nunca foi a técnica de comparação — era o tamanho do catálogo: a maioria dos licitantes municipais nunca vendeu ao Estado e não estava nas nossas raízes.')+
    `<div class="note">${esc(d.nota||'')}</div>`;
}


async function vincInterposicao(){
  const c=_vincCnpj(); const o=$('vinc-out'); if(!c){o.innerHTML=card('<div class="warn">Informe um CNPJ.</div>');return;}
  o.innerHTML=card('<div class="dim">medindo os eixos de interposição…</div>');
  const d=await J('/api/osint/interposicao?cnpj='+encodeURIComponent(c));
  if(!d.ok){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const socios=d.socios||d.perfis||[];
  let h=sec('Perfil de laranja (interposição) — CNPJ raiz '+esc(c.slice(0,8)));
  h+=leitura('Este módulo marcava <b>55%</b> da base até a prevalência de cada eixo ser medida: empresa com um só sócio é <b>54,9%</b> do normal, e sócio com mais de 80 anos é <b>1,87%</b>. Depois da calibragem, 1,4%. Eixo que acende na maioria mede a base, não o alvo.');
  h+=card(`<pre style="white-space:pre-wrap;font-size:12px;margin:0">${esc(JSON.stringify(d,null,1)).slice(0,4000)}</pre>`);
  o.innerHTML=h;
}
async function vincPatrimonio(){
  const c=_vincCnpj(); const o=$('vinc-out'); if(!c){o.innerHTML=card('<div class="warn">Informe um CNPJ.</div>');return;}
  o.innerHTML=card('<div class="dim">comparando capacidade declarada e recebimento…</div>');
  const d=await J('/api/osint/patrimonio?cnpj='+encodeURIComponent(c));
  if(!d.ok){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  let h=sec('Capacidade declarada × recebimento público');
  h+=leitura('Sem renda conhecida o veredito é <b>não aferível</b>, nunca "renda incompatível" — a distinção entre fachada e enriquecimento depende de saber o que se declara, e quase sempre não se sabe.');
  h+=card(`<pre style="white-space:pre-wrap;font-size:12px;margin:0">${esc(JSON.stringify(d,null,1)).slice(0,3000)}</pre>`);
  o.innerHTML=h;
}

// ═══ DETECTORES ÓRFÃOS — segunda onda do "ligar tudo" (2026-07-29) ═══
// Cada um destes existia no backend, com teste, e sem uma tela: anomalias por PyOD, rodízio
// temporal, conflito doador↔contrato, sobrepreço contra mediana de mercado, co-endereço,
// concentração geográfica e as duas leituras do D.O. do Rio.
const _DETS_ORFAOS=[
  {id:'anomalias', rota:'/api/anomalias?top=40', tl:'Anomalias nos pagamentos',
   ic:'🌡️', desc:'Ordens bancárias que fogem do padrão do próprio órgão (ensemble de detecção de outlier + Benford). Outlier não é irregularidade: é onde vale olhar primeiro.', campo:'alertas'},
  {id:'rodizio', rota:'/api/rodizio?top=40', tl:'Rodízio de vencedores',
   ic:'🔄', desc:'Empresas que se revezam nas vitórias do mesmo órgão. Alternância pode ser mercado pequeno — ou combinação. O sinal está na regularidade do revezamento.', campo:'achados'},
  {id:'conflito', rota:'/api/conflito', tl:'Conflito doador ↔ contrato',
   ic:'🗳️', desc:'Doador de campanha (TSE) que é sócio de empresa paga pelo Estado. Doação é lícita e pública; a questão é o que veio depois dela.', campo:'achados'},
  {id:'doador_contrato', rota:'/api/doador_contrato', tl:'Doador × contrato (via QSA)',
   ic:'💸', desc:'Mesma pergunta pelo outro lado: partindo do contrato, chega-se a um doador no quadro societário?', campo:'achados'},
  {id:'sobrepreco', rota:'/api/sobrepreco?top=40', tl:'Sobrepreço vs mercado',
   ic:'📈', desc:'Preço unitário acima da mediana de mercado para item comparável. Só vale sobre item homogêneo — descrição genérica compara produtos diferentes.', campo:'itens'},
  {id:'coendereco', rota:'/api/coendereco/clusters?limite=80', tl:'Co-endereço (grupos por sede)',
   ic:'🏠', desc:'Empresas que dividem a mesma sede. Mesma SALA significa muito; mesmo PRÉDIO quase nada — o topo do acervo por prédio tem 318 CNPJs.', campo:'clusters'},
  {id:'cidades', rota:'/api/orgao/cidades', tl:'Concentração geográfica',
   ic:'🗺️', desc:'De onde vêm os fornecedores do órgão. Concentração num município distante do objeto é indício a explicar.', campo:'cidades'},
  {id:'doe_conc', rota:'/api/pcrj/doe_concentracao', tl:'D.O. Rio — concentração em atas',
   ic:'📰', desc:'Concentração de fornecedores nas atas de registro de preço publicadas no Diário Oficial do Rio.', campo:'achados'},
  {id:'doe_canal', rota:'/api/pcrj/doe_canal_informal', tl:'D.O. Rio — canal informal',
   ic:'📧', desc:'Contratação cujo canal de propostas é e-mail pessoal (gmail e afins) em vez de sistema oficial.', campo:'achados'},
  {id:'tse_ano', rota:'/api/compliance/tse/2022', tl:'Doações eleitorais (TSE) por ano',
   ic:'🗳️', desc:'Doações declaradas ao TSE no exercício. Base pública e lícita — serve para cruzar com quadro societário de fornecedor.', campo:'doacoes'},
  {id:'sei_direc', rota:'/api/sei/direcionamento', tl:'Direcionamento em editais (SEI)',
   ic:'🎯', desc:'Varre os autos do SEI procurando cláusula restritiva de competição, item a item, com a base legal de cada uma.', campo:'achados'},
  {id:'sancoes_det', rota:'/api/sancoes/detalhar', tl:'Sanção — veda de fato?',
   ic:'🚫', desc:'Detalha a sanção: qual cadastro, qual abrangência, qual vigência. Nem toda sanção impede contratar com o Estado.', campo:'sancoes'},
];

async function renderDetectoresOrfaos(){
  let h=cover('geral','Detectores — leituras que não tinham tela',
    'Dez leituras já implementadas e testadas no motor que nunca tiveram um botão: anomalia em pagamento, rodízio de vencedores, doador que virou fornecedor, sobrepreço contra mercado, sede compartilhada, concentração geográfica e as duas varreduras do Diário Oficial do Rio. Toda leitura aqui é <b>indício</b> — a explicação inocente vem junto.','🧪');
  h+=`<div class="grid g2">`+_DETS_ORFAOS.map(d=>card(
    `<div style="font-weight:700">${svgIco(d.ic)} ${esc(d.tl)}</div>
     <div class="dim" style="margin-top:5px">${d.desc}</div>
     <div class="btns" style="margin-top:10px"><button type="button" class="btn ghost" onclick="detRodar('${d.id}')">Rodar</button></div>
     <div id="det-${d.id}"></div>`)).join('')+`</div>`;
  return h;
}

async function detRodar(id){
  const d=_DETS_ORFAOS.find(x=>x.id===id); const o=$('det-'+id);
  o.innerHTML='<div class="dim" style="margin-top:8px">lendo…</div>';
  const r=await J(d.rota);
  if(r&&r.ok===false){o.innerHTML=`<div class="warn" style="margin-top:8px">${erroHumano(r.erro)}</div>`;return;}
  const itens=(r&&(r[d.campo]||r.achados||r.itens||r.clusters||r.alertas))||[];
  if(!itens.length){
    o.innerHTML=`<div class="note" style="margin-top:8px">Nada retornado nesta execução. <b>INDISPONÍVEL não é zero</b> — pode ser cobertura parcial da fonte, não ausência do fato.</div>`;
    return;
  }
  let h=`<div class="dim" style="margin-top:8px"><b>${fmtN(itens.length)}</b> linha(s)</div>`;
  h+=`<div style="max-height:320px;overflow:auto;margin-top:6px"><table class="tb"><tbody>`;
  for(const it of itens.slice(0,60)){
    const txt=typeof it==='object'
      ? Object.entries(it).filter(([k,v])=>v!=null&&typeof v!=='object').slice(0,5)
          .map(([k,v])=>`<b>${esc(k)}</b> ${esc(String(v)).slice(0,60)}`).join(' · ')
      : esc(String(it));
    h+=`<tr><td style="font-size:12px">${txt}</td></tr>`;
  }
  h+=`</tbody></table></div>`;
  if(itens.length>60) h+=`<div class="note">60 de ${fmtN(itens.length)} linhas acima — a lista completa sai no relatório do órgão.</div>`;
  if(r.ressalva) h+=`<div class="note">${esc(r.ressalva)}</div>`;
  o.innerHTML=h;
}

// ═══ INSTRUMENTAÇÃO — agenda, pipelines, memória, UGs, SIAFE, radar, núcleo ═══
async function renderInstrumentacao(){
  let h=cover('geral','Instrumentação — o estado da máquina, sem abrir terminal',
    'Timers e crons agendados, frescor de cada pipeline, aprendizados na memória, catálogo de UGs, estado do SIAFE, radar de vigilância e o comando do núcleo de perícia. Tudo isto era alcançável só por curl.','🔧');
  const [ag,pp,mm,ug,sf,rd]=await Promise.all([
    J('/api/agenda'),J('/api/pipelines'),J('/api/memoria'),J('/api/ugs?limite=15'),
    J('/api/siafe/status'),J('/api/radar/status')]);

  h+=sec('Frescor das fontes (SLO por pipeline)');
  const ps=(pp&&(pp.pipelines||pp.itens))||[];
  if(ps.length){
    h+=`<table class="tb"><thead><tr><th>Pipeline</th><th>Estado</th><th class="r">Idade</th></tr></thead><tbody>`;
    for(const p of ps){
      const ok=String(p.estado||'').toLowerCase().startsWith('ok');
      h+=`<tr><td>${esc(p.nome||p.id)}</td><td class="${ok?'ok':'bad'}">${esc(p.estado||'—')}</td>
          <td class="r dim">${p.idade_dias==null?'—':p.idade_dias+' d'}</td></tr>`;
    }
    h+=`</tbody></table>`;
  }else h+=card(`<div class="dim">Pipelines indisponíveis nesta execução.</div>`);

  h+=sec('Agenda (timers e crons)');
  const js=(ag&&(ag.jobs||ag.itens||ag.agenda))||[];
  if(js.length){
    h+=`<table class="tb"><thead><tr><th>Job</th><th>Quando</th><th>Último</th></tr></thead><tbody>`;
    for(const j of js.slice(0,40))
      h+=`<tr><td>${esc(j.nome||j.id||'—')}</td><td class="dim">${esc(j.quando||j.cron||j.schedule||'—')}</td>
          <td class="dim">${esc(j.ultimo||j.last||'—')}</td></tr>`;
    h+=`</tbody></table>`;
  }else h+=card(`<div class="dim">Agenda indisponível nesta execução.</div>`);

  h+=sec('SIAFE e radar');
  h+=`<div class="grid g2">
    ${kpi(esc((sf&&(sf.estado||sf.status))||'—'),'SIAFE',null,'💵')}
    ${kpi(fmtN(sf&&(sf.n_obs||sf.obs)),'OBs coletadas')}
    ${kpi(esc((rd&&(rd.estado||rd.status))||'—'),'Radar',null,'🎯')}
    ${kpi(fmtN(mm&&(mm.n||mm.total||mm.aprendizados)),'Itens na memória','var(--accent)','🧠')}</div>`;
  h+=card(`<div class="btns" style="flex-wrap:wrap">
      <button type="button" class="btn ghost" onclick="instAcionar('/api/siafe/status','GET')">Status SIAFE</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/siafe/atualizar','POST')">Atualizar SIAFE</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/siafe/sweep','POST')">Sweep SIAFE</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/radar/status','GET')">Status radar</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/radar/ciclo','POST')">Ciclo do radar</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/radar/vigiar','POST')">Colocar sob vigilância</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/compliance/stats','GET')">Estatísticas</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/compliance/alerts','GET')">Alertas</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/compliance/relatorio_30d','GET')">Relatório 30 dias</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/nucleo/comando','POST')">Núcleo de perícia</button>
    </div><div id="inst-out"></div>`);

  h+=sec('Catálogo de UGs');
  const us=(ug&&(ug.ugs||ug.itens))||[];
  if(us.length){
    h+=card(`<div class="search"><span class="mag"></span>
        <input id="inst-ug" placeholder="filtrar UG por nome ou código…" onkeydown="if(event.key==='Enter')instUgs()"></div>
      <div id="inst-ugs" style="margin-top:10px">`+us.map(u=>
        `<div class="kv"><span class="k">${esc(u.codigo||u.ug)} — ${esc(u.nome||'')}</span><b>${fmtRc(u.total||u.total_pago)}</b></div>`).join('')+`</div>
      <div class="dim" style="margin-top:6px">${fmtN(ug.n_total||us.length)} UGs no catálogo.</div>`);
  }else h+=card(`<div class="dim">Catálogo de UGs indisponível.</div>`);

  h+=sec('Fila do fiscal (flags e restritos)');
  h+=card(`<div class="btns">
      <button type="button" class="btn ghost" onclick="instAcionar('/api/flags','GET')">Flags de triagem</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/restritos','GET')">Processos restritos</button>
    </div><div class="dim" style="margin-top:6px">A página <code>/controle</code> mostra o mesmo em tela dedicada.</div>`);
  return h;
}

async function instUgs(){
  const f=($('inst-ug')?.value||'').trim();
  const d=await J('/api/ugs?limite=40&filtro='+encodeURIComponent(f));
  const us=(d&&(d.ugs||d.itens))||[];
  $('inst-ugs').innerHTML=us.length
    ? us.map(u=>`<div class="kv"><span class="k">${esc(u.codigo||u.ug)} — ${esc(u.nome||'')}</span><b>${fmtRc(u.total||u.total_pago)}</b></div>`).join('')
    : '<div class="dim">Nenhuma UG com esse filtro.</div>';
}

async function instAcionar(rota,metodo){
  const o=$('inst-out'); o.innerHTML='<div class="dim" style="margin-top:8px">acionando…</div>';
  try{
    const d=await J(rota, metodo==='POST'?{method:'POST'}:undefined);
    o.innerHTML=sec(esc(rota))+card(
      `<pre style="white-space:pre-wrap;font-size:12px;margin:0">${esc(JSON.stringify(d,null,1)).slice(0,4000)}</pre>`);
  }catch(e){ o.innerHTML=card(`<div class="warn">${erroHumano(String(e))}</div>`); }
}

// ═══ MISSÕES DO HERMES — a fila paralela que só existia no backend ═══
async function renderMissoes(){
  let h=cover('geral','Missões — a fila do auditor autônomo',
    'O Hermes aceita <b>várias missões em paralelo</b> desde sempre no backend; a tela só sabia operar uma. Aqui a fila fica visível: o que está rodando, o que já terminou, e o resultado de cada uma.','🛰️');
  h+=card(`<div class="search"><span class="mag"></span>
      <input id="ms-txt" placeholder="descreva a missão (ex.: audite os pagamentos do ITERJ em 2025)…"
             onkeydown="if(event.key==='Enter')missaoCriar()"></div>
    <div class="btns" style="margin-top:10px">
      <button type="button" class="btn" onclick="missaoCriar()">Enfileirar missão</button>
      <button type="button" class="btn ghost" onclick="missaoListar()">↻ Atualizar fila</button>
    </div>`);
  h+=`<div id="ms-out"></div>`;
  setTimeout(missaoListar,50);
  return h;
}

async function missaoListar(){
  const o=$('ms-out'); if(!o)return;
  const d=await J('/api/hermes/missoes');
  const ms=(d&&(d.missoes||d.itens))||[];
  if(!ms.length){o.innerHTML=card('<div class="dim">Nenhuma missão na fila.</div>');return;}
  o.innerHTML=sec('Fila',ms.length)+`<div class="grid">`+ms.map(m=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
       <div style="min-width:0"><div style="font-weight:700">${esc(m.titulo||m.objetivo||m.id)}</div>
         <div class="dim" style="margin-top:3px">${esc(m.estado||m.status||'—')}${m.criada_em?' · '+esc(m.criada_em):''}</div></div>
       <button type="button" class="btn ghost" onclick="missaoVer('${esc(m.id)}')">Ver</button></div>
     <div id="ms-${esc(m.id)}"></div>`)).join('')+`</div>`;
}

async function missaoCriar(){
  const t=($('ms-txt')?.value||'').trim(); if(!t)return;
  await J('/api/hermes/missoes',{method:'POST',headers:{'Content-Type':'application/json'},
                                body:JSON.stringify({objetivo:t,titulo:t})});
  jfnToast('Missão enfileirada.','green'); $('ms-txt').value=''; setTimeout(missaoListar,400);
}

async function missaoVer(id){
  const o=$('ms-'+id); if(!o)return;
  o.innerHTML='<div class="dim" style="margin-top:8px">lendo…</div>';
  const d=await J('/api/hermes/missoes/'+encodeURIComponent(id));
  o.innerHTML=`<pre style="white-space:pre-wrap;font-size:12px;margin-top:8px">${esc(JSON.stringify(d,null,1)).slice(0,3000)}</pre>`;
}

const TABS={
  inicio:[
    {id:'i_cockpit', ic:'◎',tl:'Cockpit', render:renderCockpit},
  ],
  estado:[
    {id:'e_panorama',ic:'📊',tl:'Panorama',render:renderPanoramaEstado},
    {id:'e_pericias',ic:'⚖️',tl:'Perícias',render:renderPericias},
    {id:'e_sanc',    ic:'🚫',tl:'Sancionadas',render:()=>renderSancionadas('estado')},
    {id:'e_frac',    ic:'✂️',tl:'Fracion.',render:renderFracionamento},
    {id:'e_sobre',   ic:'📈',tl:'Sobrepreço',render:renderSobrepreco},
    {id:'e_escal',   ic:'🪜',tl:'Escalada', render:renderEscalada},
    {id:'e_comp',    ic:'💰',tl:'Comparador',render:renderComparador},
    {id:'e_adit',    ic:'📑',tl:'Aditivos',render:renderAditivos},
    {id:'e_certames',ic:'🧮',tl:'Certames',render:renderCertames},
    {id:'e_cartel',  ic:'🔗',tl:'Cartel',  render:renderCartel},
    {id:'e_conluio', ic:'🕸️',tl:'Conluio', render:()=>renderConluio('estado')},
    {id:'e_poder',   ic:'🏛️',tl:'Nomeados',render:renderPoder},
    {id:'e_alertas', ic:'🚨',tl:'Alertas', render:renderAlertas},
    {id:'e_resp',    ic:'🧑‍⚖️',tl:'Responsáveis',render:renderResponsaveis},
    {id:'e_siafe',   ic:'💵',tl:'SIAFE',   render:renderSiafe},
  ],
  prefeitura:[
    {id:'p_panorama',ic:'📊',tl:'Panorama',render:renderPanoramaPref},
    {id:'p_gastos',  ic:'✂️',tl:'Gastos', render:renderGastosPref},
    {id:'p_sanc',    ic:'🚫',tl:'Sancionadas',render:renderSancionadasMun},
    {id:'p_sobre',   ic:'📈',tl:'Sobrepreço',render:()=>renderSobrepreco('prefeitura')},
    {id:'p_escal',   ic:'🪜',tl:'Escalada',render:()=>renderEscalada('prefeitura')},
    {id:'p_comp',    ic:'💰',tl:'Comparador',render:renderComparador},
    {id:'p_adit',    ic:'📑',tl:'Aditivos',render:()=>renderAditivos('prefeitura')},
    {id:'p_cartel',  ic:'🔗',tl:'Concentração',render:renderCartelMun},
    {id:'p_comis',   ic:'🎖️',tl:'Comissionados',render:renderComissionadosPref},
    {id:'p_benef',   ic:'🍞',tl:'Benefícios',render:()=>renderBeneficiosPref('')},
    {id:'p_fant',    ic:'👻',tl:'Fantasmas',render:renderFantasmasPref},
    {id:'p_ppp',     ic:'🏗️',tl:'PPP',     render:renderPPPPref},
    {id:'p_conluio', ic:'🕸️',tl:'Conluio', render:()=>renderConluio('prefeitura')},
    {id:'p_contr',   ic:'📄',tl:'Contratos',render:renderContratosPref},
  ],
  geral:[
    {id:'g_buscar',  ic:'🔎',tl:'Buscar',  render:renderBuscar},
    {id:'g_radar',   ic:'🎯',tl:'Radar',   render:renderRadar},
    {id:'g_prioridade',ic:'⚡',tl:'Prioridade',render:renderPrioridade},
    {id:'g_vinculos', ic:'🕸️',tl:'Vínculos', render:renderVinculos},
    {id:'g_pecas',    ic:'📜',tl:'Peças',    render:renderPecas},
    {id:'g_fontes',   ic:'🛰️',tl:'Fontes externas',render:renderFontesExternas},
    {id:'g_hub',      ic:'🏢',tl:'Hub físico',render:renderHubFisico},
    {id:'g_acuracia', ic:'🎯',tl:'Acurácia', render:renderAcuracia},
    {id:'g_dets',     ic:'🧪',tl:'Detectores',render:renderDetectoresOrfaos},
    {id:'g_instr',    ic:'🔧',tl:'Instrumentação',render:renderInstrumentacao},
    {id:'g_missoes',  ic:'🛰️',tl:'Missões',  render:renderMissoes},
    {id:'g_conluioq',ic:'🤝',tl:'Conluio QSA',render:renderConluioQSA},
    {id:'g_comun',   ic:'🧩',tl:'Comunidades',render:renderComunidades},
    {id:'g_retro',   ic:'🔮',tl:'Retro',   render:renderRetro},
    {id:'g_riscos',  ic:'👻',tl:'Riscos',  render:renderRiscos},
    {id:'g_dep',     ic:'🔗',tl:'Cativos', render:renderFornecedorDependente},
    {id:'g_capital', ic:'🫧',tl:'Capital irrisório',render:renderCapital},
    {id:'g_dez',     ic:'📅',tl:'Dezembro',render:renderCorridaDezembro},
    {id:'g_ocult',   ic:'🫥',tl:'Sócio oculto',render:renderSocioOculto},
    {id:'g_nep',     ic:'👪',tl:'Nepotismo',render:renderNepotismo},
    {id:'g_nepx',    ic:'🔀',tl:'Nepot. cruzado',render:renderNepotismoCruzado},
    {id:'g_fenix',   ic:'🦅',tl:'Fênix',   render:renderFenix},
    {id:'g_porta',   ic:'🚪',tl:'Porta giratória',render:renderPortaGiratoria},
    {id:'g_laranjas',ic:'🎭',tl:'Laranjas',render:renderLaranjas},
    {id:'g_socserv', ic:'🕴️',tl:'Servidor-sócio',render:renderSocioServidor},
    {id:'g_poder',   ic:'🏛️',tl:'Poder',   render:renderPoder},
    {id:'g_conluio', ic:'🕸️',tl:'Conluio', render:()=>renderConluio(_cjEsf)},
    {id:'g_validar', ic:'🏢',tl:'Validar', render:renderValidar},
    {id:'g_sweeps',  ic:'🛰️',tl:'Sistema', render:renderSweeps},
    {id:'g_acoes',   ic:'☑️',tl:'Ações',   render:renderAcoes},
  ],
};
let esfera='inicio',aba='i_cockpit';
const sessaoReports=new Set();

function montarSpheres(){
  $('spheres').innerHTML=SPHERES.map(s=>`<button type="button" class="sph ${s.id} ${s.id===esfera?'on':''}" aria-pressed="${s.id===esfera}" onclick="trocarEsfera('${s.id}')"><span class="i">${svgIco(s.ic)}</span><div><div>${s.tl}</div><div class="c">${s.c}</div></div></button>`).join('');
}
/* v49 — A BARRA DESLOCAVA A CADA NAVEGAÇÃO, e o motivo era esta função.
   Ela reescrevia o `innerHTML` da nav INTEIRA (até 30 botões na esfera "Transversal") a cada `ir()`,
   mesmo quando a esfera não mudou e a única diferença era QUAL botão tem a classe `.on`. Com
   `flex:1 0 auto` dentro de `overflow-x:auto`, recriar os nós faz o navegador re-resolver a largura
   de todos eles — e a barra se desloca sob o cursor. Trocar de aba mexia a aba que você ia clicar.
   Agora: reconstrói só quando a ESFERA troca (aí o conjunto de botões é outro de verdade); dentro da
   mesma esfera, só alterna a classe. Nada de layout novo, e a posição de scroll horizontal também
   deixa de ser perdida. */
let _tabsEsfera=null;
function montarTabs(){
  const nav=$('tabs');
  nav.style.display=TABS[esfera].length<2?'none':'';
  if(_tabsEsfera!==esfera){
    _tabsEsfera=esfera;
    nav.innerHTML=TABS[esfera].map(t=>`<button class="${t.id===aba?'on':''}" onclick="ir('${t.id}')" title="${t.tl}" data-aba="${t.id}"><span class="ti">${svgIco(t.ic)}</span><span class="tl">${t.tl}</span></button>`).join('');
    return;
  }
  for(const b of nav.children)b.classList.toggle('on',b.dataset.aba===aba);
}
/* v36: NAO pre-atribuir `aba` aqui — o ir() ja seta aba e monta as tabs, e a
   pre-atribuicao apagava o sentido do giro na troca de esfera (_abaAntes
   ficava igual ao destino). */
function trocarEsfera(id){esfera=id;montarSpheres();ir(TABS[id][0].id);}
let _nav=0; // token anti-corrida
async function ir(id){
  const _abaAntes=aba; // v36: quem eu era antes da troca decide o sentido do giro
  // blindagem: se o id não é da esfera atual, procura a esfera dona e troca (evita crash)
  let t=TABS[esfera].find(x=>x.id===id);
  if(!t){for(const e of Object.keys(TABS)){const cand=TABS[e].find(x=>x.id===id);if(cand){esfera=e;t=cand;montarSpheres();break;}}}
  if(!t)return;
  aba=id;montarTabs();
  /* v36: sentido da navegacao — a faceta do cristal gira PARA o lado do
     destino (aba a direita gira num sentido, a esquerda no outro). Sem
     sentido (primeira carga, mesma aba) o atributo sai e vale o v31. */
  {const _flat=Object.values(TABS).flat().map(x=>x.id);
   const _da=_flat.indexOf(_abaAntes),_pa=_flat.indexOf(id);
   if(_da<0||_pa<0||_da===_pa)document.documentElement.removeAttribute('data-nav-dir');
   else document.documentElement.setAttribute('data-nav-dir',_pa>_da?'fwd':'back');}
  /* o fio corre na barra de abas durante a troca — o mesmo feixe do
     cabecalho, agora reagindo a navegacao em vez de so decorar. */
  document.body.classList.remove('navegando');void document.body.offsetWidth;
  document.body.classList.add('navegando');
  setTimeout(()=>document.body.classList.remove('navegando'),560);
  document.body.setAttribute('data-esf',esfera);   // tinge hovers/energia com a cor da esfera
  if(typeof _rjbgTinge==='function')_rjbgTinge();   // território de fundo re-tinge na cor da esfera
  if(typeof nebulaViva==='function')nebulaViva();   // v37: liga o loop de video da esfera, se existir
  const meu=++_nav;
  const v=$('view');v.innerHTML=spin();
  /* v31: a troca era um corte — spinner sai, conteudo novo entra, e cada aba
     nascia e morria isolada. Com startViewTransition o navegador fotografa o
     antes e o depois e INTERPOLA entre os dois: o que existe nas duas abas
     (cabecalho, barra de abas, o proprio quadro do conteudo) se move em vez
     de piscar, e a navegacao le como um movimento so.
     O render assincrono termina ANTES de abrir a transicao — senao o
     navegador congelaria a tela durante o fetch.                          */
  try{const html=await t.render();if(meu!==_nav)return;
    const pintar=()=>{v.innerHTML=`<div class="fade">${html}</div>`;if(typeof marcarValores==='function')marcarValores(v);};
    if(document.startViewTransition&&!_redMotion){
      await document.startViewTransition(pintar).updateCallbackDone;
    }else{pintar();}}
  catch(e){if(meu!==_nav)return;v.innerHTML=card(`<div class="warn">Falha: ${esc(e)}</div>`);}
  window.scrollTo(0,0);
  if(aba!=='i_cockpit')vivo();   // cockpit tem animação própria; demais abas herdam a "vida"
  else if(typeof ckBoot==='function')ckBoot();   // v48: monta o cockpit DEPOIS do paint
  a11yfy(document.body);         // torna chips/spheres/.clk operáveis por teclado (audit a11y #1)
}

// ═══ A11Y — restam apenas cards <div onclick> e links <a> sem href: padrão ARIA button (foco+teclado).
//    (chips, spheres e .clk já são <button> semânticos.) ═══
function a11yfy(root){
  (root||document).querySelectorAll('[onclick]:not(button):not(input):not([tabindex]):not(a[href])').forEach(el=>{
    el.tabIndex=0; if(!el.hasAttribute('role'))el.setAttribute('role','button');
  });
  holografar(root);
}

/* ═══ HOLOGRAMA UNIVERSAL — a camada viva de cada acionável ═══════════════════════
   Injeta um `<i class="hlx">` em todo botão/chip/aba/atalho. Três decisões que valem
   ser lidas antes de mexer:
   1. É elemento REAL, não pseudo: em `.btn` e `.chip` os dois pseudos já estão
      ocupados desde o v7/v9. A camada traz os seus próprios.
   2. `--hd` (atraso) sai de um contador global — cada peça respira num tempo
      diferente. Botão pulsando junto lê como pisca-pisca; pulsando desencontrado lê
      como sistema com muitas partes vivas.
   3. `aria-hidden` + `pointer-events:none`: é decoração e não pode aparecer para
      leitor de tela nem roubar clique. Marca `data-hlx` para nunca duplicar. */
const HLX_SEL='.btn,.chip,.tab,.lnk,.ck-inst,.nu-chip,.htop a';
let _hlxN=0;
function holografar(root){
  const alvo=root||document;
  let els;
  try{els=alvo.querySelectorAll(HLX_SEL);}catch(_){return;}
  els.forEach(el=>{
    if(el.dataset.hlx)return;
    el.dataset.hlx='1';
    const i=document.createElement('i');
    i.className='hlx';i.setAttribute('aria-hidden','true');
    i.style.setProperty('--hd',(((_hlxN++)*0.37)%4.2).toFixed(2)+'s');
    el.appendChild(i);
  });
}
/* As abas são renderizadas depois — e algumas nem existem no boot. O observador é o
   que faz isto valer para o painel INTEIRO, e não só para o que estava na tela. */
addEventListener('DOMContentLoaded',()=>{
  holografar(document);
  try{
    new MutationObserver(ms=>{
      for(const m of ms)for(const nó of m.addedNodes)
        if(nó.nodeType===1)holografar(nó.matches&&nó.matches(HLX_SEL)?nó.parentNode:nó);
    }).observe(document.body,{childList:true,subtree:true});
  }catch(_){}
});
document.addEventListener('keydown',e=>{
  const el=e.target;
  if((e.key==='Enter'||e.key===' ')&&el.matches&&el.matches('[role="button"][tabindex]:not(button)')){
    e.preventDefault(); el.click();
  }
});

// ═══ SPOTLIGHT + TILT 3D — a luz E o plano seguem o cursor (1 listener global) ═══
const _rmGlobal=matchMedia('(prefers-reduced-motion:reduce)').matches;
/* v49: coalescido por quadro e com o retângulo em cache, pela mesma razão do handler de controles
   (ver `_I3D`, mais abaixo): `getBoundingClientRect()` por evento de mouse é leitura de layout
   forçada, e o painel foi medido a 1-2 FPS. Os dois handlers cobrem conjuntos DISJUNTOS de
   elementos — controles ali, cards aqui — de propósito; não são duplicados. */
let _spotEl=null,_spotRect=null,_spotEv=null,_spotRaf=0;
addEventListener('scroll',()=>{_spotRect=null;},{passive:true});
addEventListener('resize',()=>{_spotRect=null;},{passive:true});
function _spotPinta(){
  _spotRaf=0;
  const t=_spotEl,e=_spotEv;if(!t||!e)return;
  if(!_spotRect)_spotRect=t.getBoundingClientRect();
  const r=_spotRect;if(!r.width||!r.height)return;
  const x=e.x-r.left,y=e.y-r.top;
  t.style.setProperty('--mx',x.toFixed(0)+'px');
  t.style.setProperty('--my',y.toFixed(0)+'px');
  if(!_rmGlobal&&(t.classList.contains('card')||t.classList.contains('ck-inst'))&&r.width<620){
    t.style.setProperty('--rx',((y/r.height-.5)*-6.5).toFixed(2)+'deg');   // tilt mais dramático
    t.style.setProperty('--ry',((x/r.width-.5)*8.5).toFixed(2)+'deg');
  }
}
document.addEventListener('pointermove',e=>{
  const t=e.target.closest&&e.target.closest('.card,.lnk,.ck-inst,.ck-hero');
  if(!t)return;
  if(t!==_spotEl){_spotEl=t;_spotRect=null;}
  _spotEv={x:e.clientX,y:e.clientY};
  if(!_spotRaf)_spotRaf=requestAnimationFrame(_spotPinta);
},{passive:true});
document.addEventListener('pointerout',e=>{
  const t=e.target.closest&&e.target.closest('.card,.ck-inst');
  if(!t||t.contains(e.relatedTarget))return;
  t.style.removeProperty('--rx');t.style.removeProperty('--ry');
},{passive:true});

// ═══ VIDA GLOBAL — o cockpit em toda aba (cascata · contagem · malha de luz) ═══
let _wireRAF=0;
function vivo(){
  const v=$('view'); if(!v) return;
  const rm=matchMedia('(prefers-reduced-motion:reduce)').matches;
  const top=[...v.querySelectorAll('.card,.cover')].filter(el=>!el.parentElement.closest('.card,.cover'));
  // 1) cascata de entrada + pulso "ao vivo" no 1º KPI
  top.forEach((el,i)=>{el.classList.add('rise');el.style.setProperty('--d',Math.min(i*18,220)+'ms');});
  if(!rm){const k=v.querySelector('.kpi');if(k)setTimeout(()=>k.classList.add('beat'),700);}
  // 2) números que sobem
  if(!rm)v.querySelectorAll('.kpi .v').forEach(_countUp);
  // 3) A→Z em TODA busca de lista (vale pra tudo; padrão continua por risco/valor)
  v.querySelectorAll('.search').forEach(box=>{
    const inp=box.querySelector('input[oninput*="filtrar"]'); if(!inp||box.querySelector('.az'))return;
    const m=(inp.getAttribute('oninput')||'').match(/filtrar\(this,\s*'([^']+)'\)/); if(!m)return;
    const b=document.createElement('button');b.type='button';b.className='az';b.textContent='A→Z';
    b.title='Ordenar por nome do fornecedor (A→Z) · clique de novo p/ voltar à ordem por risco';
    b.setAttribute('onclick',`ordenar('${m[1]}',this)`);box.appendChild(b);
  });
  // 4) malha de luz ligando os cards
  _wire(top,rm);
}
function _countUp(el){
  const raw=(el.textContent||'').trim();
  const m=raw.match(/^([^\d]*?)(\d[\d.\s]*(?:,\d+)?)(.*)$/); if(!m)return;
  const pre=m[1],suf=m[3],dec=(m[2].split(',')[1]||'').length;
  const val=parseFloat(m[2].replace(/[.\s]/g,'').replace(',','.'));
  if(!isFinite(val)||val===0)return;
  el.classList.add('counting');const t0=performance.now(),dur=850;
  (function step(t){const p=Math.min(1,(t-t0)/dur),e=1-Math.pow(1-p,3);
    el.textContent=pre+(val*e).toLocaleString('pt-BR',{minimumFractionDigits:dec,maximumFractionDigits:dec})+suf;
    if(p<1)requestAnimationFrame(step);else{el.textContent=raw;el.classList.remove('counting');}})(t0);
}
const _ESF_RGB={inicio:'99,224,255',estado:'125,175,255',prefeitura:'235,190,105',geral:'200,150,255'};
function _wire(nodes,rm){
  cancelAnimationFrame(_wireRAF);
  const C=_ESF_RGB[esfera]||_ESF_RGB.inicio;
  const v=$('view'),fade=v&&v.querySelector('.fade'); if(!v||!fade||nodes.length<2)return;
  let cv=v.querySelector('.view-wire');
  if(!cv){cv=document.createElement('canvas');cv.className='view-wire';v.insertBefore(cv,fade);}
  const cx=cv.getContext('2d'),dpr=Math.min(2,devicePixelRatio||1),vr=v.getBoundingClientRect();
  const W=v.clientWidth,H=Math.max(v.scrollHeight,fade.scrollHeight);
  cv.width=W*dpr;cv.height=H*dpr;cv.style.width=W+'px';cv.style.height=H+'px';cx.scale(dpr,dpr);
  const pts=nodes.slice(0,46).map(el=>{const r=el.getBoundingClientRect();
    return {x:r.left-vr.left+Math.min(r.width/2,80),y:r.top-vr.top+9};});
  // arestas: cada nó liga aos 2 vizinhos mais próximos (grafo esparso, sem cruzar tudo)
  const edges=[];
  pts.forEach((a,i)=>{const d=pts.map((b,j)=>({j,d:(a.x-b.x)**2+(a.y-b.y)**2})).filter(o=>o.j!==i).sort((p,q)=>p.d-q.d).slice(0,2);
    d.forEach(o=>{const k=i<o.j?i+'-'+o.j:o.j+'-'+i;if(!edges.some(e=>e.k===k))edges.push({k,a:i,b:o.j});});});
  function draw(t){
    cx.clearRect(0,0,W,H);
    edges.forEach(e=>{const A=pts[e.a],B=pts[e.b];
      cx.strokeStyle='rgba('+C+',.15)';cx.lineWidth=1;
      cx.beginPath();cx.moveTo(A.x,A.y);cx.lineTo(B.x,B.y);cx.stroke();});
    pts.forEach(p=>{cx.fillStyle='rgba('+C+',.35)';cx.beginPath();cx.arc(p.x,p.y,1.6,0,6.283);cx.fill();});
    if(!rm){edges.forEach((e,i)=>{const A=pts[e.a],B=pts[e.b],ph=((t/1400)+i*0.16)%1;
      const x=A.x+(B.x-A.x)*ph,y=A.y+(B.y-A.y)*ph;
      const g=cx.createRadialGradient(x,y,0,x,y,8);g.addColorStop(0,'rgba('+C+',.8)');g.addColorStop(1,'rgba('+C+',0)');
      cx.fillStyle=g;cx.beginPath();cx.arc(x,y,8,0,6.283);cx.fill();});
      _wireRAF=requestAnimationFrame(draw);}
  }
  draw(rm?0:performance.now());
}

// ═══ GLOSSÁRIO ═══
const TERMOS=[
 ['🎯','Captura de órgão','Uma única empresa vence 80% ou mais das licitações de um órgão. Sinal de mercado fechado — merece verificação de propostas e sócios.'],
 ['🔁','Rodízio de vencedores','2 ou 3 empresas se revezam nas vitórias de licitações PARECIDAS (mesmo tipo de objeto). Padrão clássico de combinação de propostas (OCDE).'],
 ['🎭','Perdedora contumaz','Empresa que participa de várias licitações e NUNCA vence. Perfil de "proposta de cobertura": existe para dar aparência de disputa e legitimar o vencedor combinado.'],
 ['👻','Empresa fantasma','Score 0-100 por 8 sinais objetivos (situação irregular na Receita, capital incompatível, endereço-ninho, aberta às vésperas do contrato, sanção…). "Sem cadastro" = ainda não consultada — não é nem regular nem fantasma.'],
 ['🚫','Sancionada à época','Empresa punida no CEIS/CNEP (impedimento, suspensão, inidoneidade) cujo contrato/pagamento ocorreu DENTRO do período da punição — vedação legal direta.'],
 ['📄','Certame','Cada licitação (disputa pública de compra) publicada no PNCP, o Portal Nacional de Contratações Públicas.'],
 ['🏢','Órgão × Ente × Esfera','O ENTE é o dono do CNPJ (ex.: Estado do RJ); o ÓRGÃO é quem compra (ex.: Sec. de Saúde). A ESFERA (federal/estadual/municipal) vem do cadastro OFICIAL do PNCP — o painel separa Estado, Prefeitura do Rio, demais municípios e federais.'],
 ['💳','Ordem Bancária (OB)','O pagamento de fato — dinheiro que saiu do caixa. Diferente de EMPENHO, que é só reserva de verba e pode ser cancelado.'],
 ['🎖️','Comissionado','Servidor nomeado sem concurso (cargo de confiança). Cruzado com candidaturas (TSE) e com benefícios sociais para mapear aparelhamento e incompatibilidade de renda.'],
 ['🎭','Laranja','Pessoa usada como sócia de fachada. Indício aqui: sócio de empresa que fatura com o Estado e ao mesmo tempo recebe benefício social de subsistência.'],
 ['🟢','Frescor de fonte','Cada base tem um LED: verde = coletada há ≤3 dias; âmbar ≤10; vermelho = parada (investigar o coletor). Defasagem nunca mais passa despercebida.'],
 ['⚖️','Indício ≠ prova','Tudo neste painel é INDÍCIO para apuração interna — não é acusação. Presunção de regularidade até verificação documental.'],
];
function glossario(){
  const ov=$('ov'),sh=$('sheet');ov.classList.add('on');
  sh.innerHTML=`<span class="x" onclick="fecharDossie()">✕ fechar</span><div class="grab"></div>
   <div style="font-weight:800;font-size:17px;margin-bottom:4px">ⓘ Entenda os termos</div>
   <div class="muted" style="font-size:13px;margin-bottom:14px">O que cada conceito do painel significa, em linguagem simples.</div>
   <div class="grid">`+TERMOS.map(([ic,t,d])=>card(`<div style="display:flex;gap:11px;align-items:flex-start"><span style="font-size:20px">${ic}</span><div><div style="font-weight:700">${t}</div><div class="muted" style="font-size:13px;margin-top:3px;line-height:1.55">${d}</div></div></div>`)).join('')+`</div>`;
}

// ═══ DOSSIÊ modal ═══
function fecharDossie(){$('ov').classList.remove('on');}
async function abrirDossie(cnpj,nome){
  const dig=String(cnpj||'').replace(/\D/g,'');if(dig.length!==14)return;
  const ov=$('ov'),sh=$('sheet');ov.classList.add('on');
  sh.innerHTML=`<span class="x" onclick="fecharDossie()">✕ fechar</span><div class="grab"></div>${spin('Montando dossiê de '+esc(nome||dig)+'…')}`;
  const d=await J('/api/perfil?cnpj='+dig);
  if(!d.ok){sh.innerHTML=`<span class="x" onclick="fecharDossie()">✕</span><div class="grab"></div>`+card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const per=d.pericia||{},ob=d.ob||{},pncp=d.pncp||{},sede=d.sede||{};
  const sv=(sede.lat&&sede.lon)?`https://www.google.com/maps?layer=c&cbll=${sede.lat},${sede.lon}`:(sede.endereco?`https://www.google.com/maps/search/${encodeURIComponent(sede.endereco+', '+(sede.municipio||''))}`:null);
  let h=`<span class="x" onclick="fecharDossie()">✕ fechar</span><div class="grab"></div>`;
  h+=`<div style="display:flex;gap:12px;align-items:center"><span class="badge-grau">${per.grau||'⚪'}</span>
      <div style="min-width:0"><div style="font-weight:800;font-size:17px;line-height:1.2">${esc(d.nome)}</div>
      <div class="dim">${esc(d.cnpj_fmt)}${per.score!=null?` · score perícia ${per.score}`:''}</div></div></div>`;
  h+=`<div class="mini">
      <div class="b"><div class="v">${fmtRc(ob.total)}</div><div class="l">Pago pelo Estado (OB)</div></div>
      <div class="b"><div class="v">${fmtN(ob.orgaos)}</div><div class="l">Órgãos pagadores</div></div>
      <div class="b"><div class="v">${fmtN(pncp.certames||0)}</div><div class="l">Vitórias no PNCP</div></div>
      <div class="b"><div class="v" style="color:${(per.indicios||0)?'var(--amber)':'#fff'}">${fmtN(per.indicios||0)}</div><div class="l">Indícios na perícia</div></div></div>`;
  if(d.resumo)h+=card(`<div style="font-size:13.5px;color:var(--mut)">${esc(d.resumo).slice(0,600)}</div>`);
  if((d.socios||[]).length)h+=`<div style="height:12px"></div>`+sec('Quadro societário (QSA)',d.socios.length)+card(`<table><tbody>${d.socios.map(s=>`<tr><td>${esc(s.nome)}${s.servidor?' <span class="tag rose">servidor</span>':''}</td><td class="dim">${esc(s.qualificacao||'')}</td></tr>`).join('')}</tbody></table>`);
  if((d.orgaos||[]).length)h+=`<div style="height:12px"></div>`+sec('Órgãos que mais pagaram')+card(`<table><tbody>${d.orgaos.map(o=>`<tr><td>${esc(o.nome||o.ug)}</td><td>${fmtRc(o.total)}</td></tr>`).join('')}</tbody></table>`);
  if(sede.endereco)h+=`<div style="height:12px"></div>`+sec('Sede / fachada')+card(`<div class="kv"><span class="k">Endereço</span><b class="right" style="max-width:64%">${esc(sede.endereco)}, ${esc(sede.municipio||'')}/${esc(sede.uf||'')}</b></div>${sede.status?`<div class="kv"><span class="k">Verificação</span><b>${esc(sede.status)}${sede.nivel?' · '+esc(sede.nivel):''}</b></div>`:''}${sede.residencial?`<div class="kv"><span class="k">Natureza</span><b style="color:var(--amber)">endereço residencial</b></div>`:''}${sv?`<div class="btns"><a class="btn ghost" href="${sv}" target="_blank">Street View</a></div>`:''}`);
  const est=d.estab;
  if(est){const hb=est.hub_compartilhado||{};const hbk=Object.keys(hb);
    h+=`<div style="height:12px"></div>`+sec('Contato & rede (Receita)')+card(
      `<div class="kv"><span class="k">Situação cadastral</span><b>${esc(est.situacao||'—')}</b></div>`+
      `<div class="kv"><span class="k">Contato declarado</span><b>${est.tem_telefone?'telefone':'—'}${est.tem_email?' · e-mail':''}${!est.tem_telefone&&!est.tem_email?'sem telefone nem e-mail':''}</b></div>`+
      (hbk.length?`<div class="kv"><span class="k">Compartilhado com</span><b class="right" style="color:var(--amber)">${hbk.map(k=>fmtN(hb[k])+' CNPJs no mesmo '+k).join(' · ')}</b></div>${leitura('Contato/endereço compartilhado por vários CNPJs é assinatura de ninho de fachada — verificar se são do mesmo grupo ou laranjas. Endereço comercial de grande porte (galeria/coworking) explica volumes altos.')}`:`<div class="dim" style="margin-top:6px">Telefone/e-mail/endereço não coincidem em massa com outros CNPJs.</div>`));}
  if((d.achados||[]).length)h+=`<div style="height:12px"></div>`+sec('Achados da perícia',d.achados.length)+`<div class="grid">`+d.achados.map(a=>card(`<div style="display:flex;gap:9px;align-items:flex-start"><span class="tag ${a.status==='CONFIRMADO'?'rose':a.status==='INDICIO'?'amber':a.status==='AFASTADO'?'green':'accent'}">${esc(a.status||'')}</span><div><div style="font-weight:650;font-size:13.5px">${esc(a.codigo||'')} — ${esc(a.titulo||'')}</div>${a.evidencia?`<div class="muted" style="font-size:12.5px;margin-top:3px">${esc(a.evidencia).slice(0,260)}</div>`:''}</div></div>`)).join('')+`</div>`;
  h+=`<div style="height:14px"></div><div class="btns">
      <button class="btn accent" onclick="fecharDossie();esfera='geral';aba='g_acoes';montarSpheres();montarTabs();ir('g_acoes').then(()=>{const e=$('ac-emp');if(e)e.value='${d.cnpj}';})">Relatório + Lex</button>
      <button class="btn ghost" onclick="verCruzamento('${d.cnpj}')">Cruzamento</button>
      <button class="btn ghost" onclick="seiArvore('${d.cnpj}')">🗂️ Árvore SEI completa</button>
      <a class="btn ghost" href="/graph?cnpj=${d.cnpj}" target="_blank">Grafo societário</a></div>
      <pre id="dos-cruz" style="margin-top:10px;display:none"></pre>
      <div id="sei-arvore-box" style="margin-top:10px"></div>`;
  h+=`<div class="note">Dossiê do banco local — indício a verificar, presunção de legitimidade. CPF de sócio mascarado (LGPD).</div>`;
  sh.innerHTML=h;
}
// ═══ ÁRVORE SEI completa de uma empresa (busca + download em lote) ═══
let _seiArvoreTimer=null;
async function seiArvore(cnpj){
  clearInterval(_seiArvoreTimer);
  const box=$('sei-arvore-box');if(!box)return;
  box.innerHTML=spin('Consultando processos SEI conhecidos…');
  const s0=await J('/api/sei/empresa/status?cnpj='+cnpj);
  if(!s0.ok){box.innerHTML=`<div class="warn">${esc(s0.erro||'indisponível')}</div>`;return;}
  if(!s0.rodando&&!s0.concluido){
    box.innerHTML=spin('Iniciando busca — pode levar minutos a horas (baixa cada processo pelo SEI)…');
    const r=await fetch('/api/sei/empresa/iniciar',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({cnpj})}).then(x=>x.json()).catch(e=>({ok:false,erro:String(e)}));
    if(!r.ok){box.innerHTML=`<div class="warn">${esc(r.erro||'falha ao iniciar')}</div>`;return;}
  }
  _seiArvorePoll(cnpj);
}
async function _seiArvorePoll(cnpj){
  const tick=async()=>{
    const box=$('sei-arvore-box');if(!box){clearInterval(_seiArvoreTimer);return;}
    const s=await J('/api/sei/empresa/status?cnpj='+cnpj);
    if(!s.ok){box.innerHTML=`<div class="warn">${esc(s.erro||'indisponível')}</div>`;clearInterval(_seiArvoreTimer);return;}
    const pct=s.n_processos?Math.round(100*s.n_arquivados/s.n_processos):0;
    box.innerHTML=`<div class="dim">${fmtN(s.n_arquivados)} de ${fmtN(s.n_processos)} processo(s) SEI arquivado(s)${s.rodando?' · buscando/baixando… (pode fechar e conferir depois)':''}</div>
      <div style="background:var(--card2);border-radius:6px;height:6px;margin-top:6px;overflow:hidden"><div style="background:var(--accent);width:${pct}%;height:100%"></div></div>
      ${s.pronto?`<div class="btns" style="margin-top:8px"><button class="btn accent" onclick="seiBaixarZip('${cnpj}')">Baixar ZIP (${fmtN(s.n_arquivados)} de ${fmtN(s.n_processos)})</button>${!s.rodando&&!s.concluido?`<button class="btn ghost" onclick="seiArvore('${cnpj}')">Continuar buscando</button>`:''}</div>`:''}
      ${s.concluido?'<div class="note" style="margin-top:6px">✅ completo — todos os processos conhecidos (via OB paga) foram arquivados.</div>':''}
      ${!s.n_processos?'<div class="note" style="margin-top:6px">Nenhum processo SEI conhecido via OB paga para este CNPJ ainda.</div>':''}`;
    if(s.concluido||!s.rodando)clearInterval(_seiArvoreTimer);
  };
  await tick();
  clearInterval(_seiArvoreTimer);
  _seiArvoreTimer=setInterval(tick,8000);
}
async function seiBaixarZip(cnpj){
  const r=await J('/api/sei/empresa/zip?cnpj='+cnpj);
  if(!r.ok){jfnToast('Não consegui montar o ZIP agora — '+(r.erro||'tente de novo em instantes.'),'rose');return;}
  window.open(r.url,'_blank');
}
async function verCruzamento(cnpj){const out=$('dos-cruz');out.style.display='block';out.textContent='cruzando…';
  const r=await J('/api/cruzamento?cnpj='+cnpj);if(r.erro){out.textContent='⚠ '+r.erro;return;}
  const dd=r.dados||r;out.textContent=`co-endereço: ${(dd.coendereco||[]).length} · indícios: ${(dd.indicios||[]).length}\n`+(dd.socios||[]).slice(0,6).map(s=>'• '+(s.nome||s)).join('\n');}

// ═══ CERTAME — Índice de Direcionamento por temas (7 famílias) ═══
const _CERT_FAM={transparencia:['📋','Transparência'],competicao:['⚔️','Competição'],conluio:['🤝','Conluio'],
  fraude_cadastral:['🎭','Fraude cadastral'],preco:['💰','Preço'],execucao:['📈','Execução'],
  certame_ata:['⚖️','Ata de julgamento']};
function jsq(s){return String(s==null?'':s).replace(/\\/g,'\\\\').replace(/'/g,"\\'");}
function fecharCertame(){$('ov').classList.remove('on');}
async function abrirCertame(certame){
  if(!certame)return;
  const ov=$('ov'),sh=$('sheet');ov.classList.add('on');
  sh.innerHTML=`<span class="x" onclick="fecharCertame()">✕ fechar</span><div class="grab"></div>${spin('Calculando índice de '+esc(certame)+'…')}`;
  const d=await J('/api/certame/indice?certame='+encodeURIComponent(certame));
  if(!d.ok){sh.innerHTML=`<span class="x" onclick="fecharCertame()">✕</span><div class="grab"></div>`+card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const ix=d.indice||{},fam=ix.familias||{},sv=ix.matriz_sv||{},drivers=ix.drivers||[];
  const cor=ix.faixa==='EXTREMO'||ix.faixa==='ALTO'?'var(--rose)':ix.faixa==='MEDIO'?'var(--amber)':'var(--tx2)';
  let h=`<span class="x" onclick="fecharCertame()">✕ fechar</span><div class="grab"></div>`;
  h+=`<div style="display:flex;gap:12px;align-items:center"><div style="font-weight:800;font-size:28px;color:${cor}">${(ix.score||0).toFixed(0)}</div>
      <div style="min-width:0"><div style="font-weight:800;font-size:15px;line-height:1.2">${esc(certame)}</div>
      <div class="dim">faixa <b>${esc(ix.faixa||'—')}</b> · confiança ${((ix.confianca||0)*100).toFixed(0)}% (${Object.values(fam).filter(f=>f.apuravel).length}/7 famílias apuráveis)</div></div></div>`;
  if(sv.nivel)h+=`<div style="height:12px"></div>`+card(`<div class="kv"><span class="k">Matriz S×V</span><b>${esc(sv.nivel)} (${sv.severidade}×${sv.verossimilhanca}=${sv.produto})</b></div><div class="kv"><span class="k">Ação recomendada</span><b class="right" style="max-width:64%">${esc(sv.acao||'')}</b></div><div class="dim" style="margin-top:4px">${esc(sv.regua||'')}</div>`);
  h+=`<div style="height:12px"></div>`+sec('As 7 famílias')+`<div class="grid">`+Object.entries(_CERT_FAM).map(([k,[ic,lbl]])=>{
    const f=fam[k]||{};
    if(!f.apuravel)return card(`<div style="display:flex;justify-content:space-between;gap:8px"><div>${ic} ${lbl}</div><div class="dim">INDISPONÍVEL</div></div>`);
    const v=f.valor||0,cor2=v>=0.5?'var(--rose)':v>=0.25?'var(--amber)':'var(--teal)';
    return card(`<div style="display:flex;justify-content:space-between;gap:8px;align-items:center"><div>${ic} ${lbl}</div><div style="font-weight:700;color:${cor2}">${(v*100).toFixed(0)}%</div></div>
      <div style="background:var(--card2);border-radius:6px;height:6px;margin-top:6px;overflow:hidden"><div style="background:${cor2};width:${(v*100).toFixed(0)}%;height:100%"></div></div>`);
  }).join('')+`</div>`;
  if(drivers.length)h+=`<div style="height:12px"></div>`+sec('O que disparou (drivers)',drivers.length)+`<div class="grid">`+drivers.map(dr=>{
    const lbl=(_CERT_FAM[dr.familia]||['📌',dr.familia])[1];
    return card(`<div style="display:flex;gap:9px;align-items:flex-start"><span class="tag rose">${esc(lbl)}</span><div><div style="font-weight:650;font-size:13.5px">${esc(dr.flag||'')} — ${(dr.valor*100).toFixed(0)}%</div>${dr.evidencia?`<div class="muted" style="font-size:12.5px;margin-top:3px">${esc(dr.evidencia).slice(0,260)}</div>`:''}</div></div>`);
  }).join('')+`</div>`;
  if(d.narrativa)h+=`<div style="height:12px"></div>`+card(`<div style="font-size:13.5px;color:var(--mut);white-space:pre-wrap">${esc(d.narrativa).slice(0,1500)}</div>`);
  h+=`<div class="note">Índice de Direcionamento — indício a apurar, nunca acusação. Fonte: ${esc(d.fonte||'calculado')}${d.gerado_em?', gerado em '+esc(d.gerado_em):''}.</div>`;
  sh.innerHTML=h;
}

// ═══ FRESCOR DE FONTES (LEDs) ═══
async function frescorHtml(){
  const d=await J('/api/fontes/frescor');
  if(!d.ok)return '';
  const rows=(d.fontes||[]).map(f=>{
    const idade=f.idade_dias==null?'sem dado':f.idade_dias===0?'hoje':f.idade_dias+'d atrás';
    return `<div class="f"><span class="led ${f.estado}"></span><span class="nome">${esc(f.fonte)}</span><span class="idade">${idade}</span></div>`;}).join('');
  return sec('Fontes & frescor')+card(`<div class="fresh">${rows}</div><div class="dim" style="margin-top:8px">≤3 dias · 🟡 ≤10 · 🔴 parada — vermelho significa coletor quebrado: investigar, não ignorar.</div>`);
}

// ═══ ESTADO ═══
async function renderPanoramaEstado(){
  const [st,p,cj,sc]=await Promise.all([J('/status'),J('/api/compliance/painel'),J('/api/pncp/conluio?esfera=estado'),J('/api/intel/sancionadas?limite=1')]);
  const a=p.alertas||{},o=p.obs||{};const coletaErro=/erro/i.test(p.ultima_coleta||'');
  const nc=(cj.captura||[]).length+(cj.rodizio_vencedores||[]).length;
  let h=cover('estado','Estado do Rio de Janeiro','Ordens Bancárias do SIAFE, concentração de fornecedores, sancionadas, perícias e conluio — somente órgãos ESTADUAIS (esfera oficial do PNCP; federais e municípios ficam em Transversal).','🏛️');
  if(coletaErro)h+=`<div class="warn">Última coleta SIAFE falhou — <b>${esc(p.ultima_coleta)}</b>.</div>`;
  h+=`<div class="grid g2">
    ${kpi(fmtN(o.total),'Ordens Bancárias',null,'💳')}${kpi(fmtRc(o.valor_total),'Valor fiscalizado',null,'💰')}
    ${kpi(fmtN(a.total??0),'Alertas ativos',(a.alta?'var(--rose)':'#fff'),'🚨','e_alertas')}${kpi(nc,'Conluio (estado)','var(--purple)','🕸️','e_conluio')}
    ${kpi(fmtN(sc.n_a_epoca??'—'),'Sancionadas à época','var(--rose)','🚫','e_sanc')}${kpi(fmtN(a.alta??0),'🔴 Alta','var(--rose)',null,'e_alertas')}
    ${kpi(st.logged_in?'🟢 ok':'🔴 off','SIAFE · '+esc(st.exercicio||'—'))}${kpi(fmtN(o.hoje??0),'OBs hoje')}</div>`;
  h+=`<div style="height:16px"></div>`+sec('Ir para')+`<div class="grid two">
    ${card(`<div style="font-weight:700">Sancionadas contratadas</div><div class="muted" style="font-size:13px">CEIS/CNEP × pagamentos, com teste "à época"</div><div class="btns"><button class="btn accent" onclick="ir('e_sanc')">Abrir</button></div>`)}
    ${card(`<div style="font-weight:700">Perícias de fornecedor</div><div class="muted" style="font-size:13px">8.648 periciados, pesquisável</div><div class="btns"><button class="btn ghost" onclick="ir('e_pericias')">Abrir</button></div>`)}</div>`;
  h+=`<div style="height:16px"></div>`+await frescorHtml();
  h+=`<div style="height:14px"></div>`+card(`<div class="kv"><span class="k">Última atualização</span><b>${esc(p.atualizado||'—')}</b></div><div class="kv"><span class="k">Última coleta SIAFE</span><b style="${coletaErro?'color:#f0c078':''}">${esc(p.ultima_coleta||'—')}</b></div>`);
  return h;
}

// ═══ SANCIONADAS (Estado e Transversal) ═══
async function renderSancionadas(esf){
  const d=await J('/api/intel/sancionadas?limite=100');
  if(!d.ok)return sec('Sancionadas')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  let emp=d.empresas||[];
  if(esf==='estado')emp=emp.filter(e=>e.estado.obs>0);
  const aepoca=emp.filter(e=>e.estado.obs_durante>0||e.pncp.vitorias_durante>0);
  let h=cover(esf==='estado'?'estado':'geral','Sancionadas que contratam com o poder público',
    'Empresas punidas no CEIS/CNEP (impedimento, suspensão, inidoneidade) que receberam pagamento (OB SIAFE) ou venceram licitação (PNCP). <b>À ÉPOCA</b> = o ato ocorreu DENTRO da vigência da punição — vedação legal direta (Lei 14.133, art. 156).','🚫')+acoesAba('sancionadas');
  h+=`<div class="grid g2">${kpi(fmtN(emp.length),'Empresas sancionadas c/ contrato',null,'🚫')}${kpi(fmtN(aepoca.length),'Com ato À ÉPOCA','var(--rose)','⚠️')}
      ${kpi(fmtRc(aepoca.reduce((s,e)=>s+e.estado.valor_durante,0)),'Pago durante sanção (OB)','var(--rose)','💸')}${kpi(fmtN(aepoca.reduce((s,e)=>s+e.pncp.vitorias_durante,0)),'Vitórias durante sanção','var(--amber)','🏆')}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por nome ou CNPJ…" oninput="filtrar(this,'#san-list .card')"></div>`;
  h+=`<div id="san-list" class="grid">`+emp.slice(0,80).map(e=>{
    const grave=e.estado.obs_durante>0||e.pncp.vitorias_durante>0;
    const s0=(e.sancoes||[])[0]||{};
    const ex=(e.estado.exemplos_durante||[])[0]||(e.pncp.exemplos_durante||[])[0];
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0">${clk(e.cnpj,e.nome||e.cnpj)}<div class="dim">${esc(e.cnpj)}</div>
      <div class="muted" style="font-size:12.5px;margin-top:4px">${esc(s0.cadastro||'')} · ${esc((s0.categoria||'').slice(0,60))}<br>vigência ${esc(s0.data_inicio||'?')} → ${esc(s0.data_fim||'?')} · ${esc((s0.orgao||'').slice(0,50))}</div></div>
      <div class="right">${grave?'<span class="sev alta">à época</span>':'<span class="sev baixa">fora da vigência</span>'}
      <div style="margin-top:6px" class="num"><b>${fmtRc(e.estado.valor_durante+e.pncp.valor_durante||e.estado.valor+e.pncp.valor)}</b></div>
      <div class="dim">${grave?'durante a sanção':'total recebido'}</div></div></div>
      ${grave&&ex?leitura(`Exemplo: ${ex.ob?('OB <b>'+esc(ex.ob)+'</b> paga em '):'certame homologado em '}<b>${esc(ex.data)}</b> (${fmtRc(ex.valor)}) — a sanção ${esc(ex.sancao)} vigia de ${esc(ex.vigencia)}. Pagamento/contratação DENTRO do período vedado.`):''}`,grave?'hl':'');}).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}

// ═══ FRACIONAMENTO (Estado) ═══
async function renderFracionamento(){
  const d=await J('/api/intel/fracionamento?limite=120');
  if(!d.ok)return sec('Fracionamento')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const g=d.grupos||[];
  let h=cover('estado','Fracionamento de despesa — fatiar para não licitar',
    'Mesmo favorecido, mesma unidade gestora e mesmo mês, com várias Ordens Bancárias <b>coladas no teto de dispensa</b> de licitação. É o padrão de dividir a compra para caber embaixo do limite e não licitar (Lei 14.133, art. 75 §1º). Quanto maior a <b>concentração</b> (% de OBs coladas no teto), mais deliberado o indício.','✂️')+acoesAba('fracionamento');
  const alta=g.filter(x=>x.concentracao>=0.5).length;
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Grupos sinalizados','var(--amber)','✂️')}${kpi(fmtN(alta),'Concentração ≥50%','var(--rose)','🎯')}
      ${kpi(fmtRc(g.reduce((s,x)=>s+x.soma,0)),'Soma dos grupos exibidos',null,'💰')}${kpi(g.length?Math.round(Math.max(...g.map(x=>x.concentracao))*100)+'%':'—','Pior concentração','var(--rose)')}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por favorecido, UG ou mês…" oninput="filtrar(this,'#frac-list .card')"></div>`;
  h+=`<div id="frac-list" class="grid">`+g.map(x=>{
    const pct=Math.round(x.concentracao*100);
    const cor=pct>=60?'var(--rose)':pct>=40?'var(--amber)':'var(--tx2)';
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0">${clk(x.credor,x.nome||x.cnpj_fmt)}<div class="dim">${esc(x.cnpj_fmt)} · UG ${esc(String(x.ug_emitente))} · ${esc(x.mes)}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:19px;color:${cor}">${pct}%</div><div class="dim">colado no teto</div></div></div>
      <div class="kv" style="margin-top:8px"><span class="k">${x.n_colado} de ${x.n} OBs em 85–100% do teto (R$ ${Number(x.teto).toLocaleString('pt-BR',{maximumFractionDigits:0})})</span><b>${fmtRc(x.soma)}</b></div>
      ${leitura(`${x.n_colado} das ${x.n} OBs deste favorecido para a UG ${esc(String(x.ug_emitente))} em ${esc(x.mes)} ficaram logo abaixo do teto de dispensa. Somadas dão ${fmtRc(x.soma)} — acima do limite, o que exigiria licitação. Cruzar com os empenhos/processos do mês.`)}`,
      pct>=50?'hl':'');}).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}

// ═══ CERTAMES — conjunto por órgão (Estado) ═══
async function renderCertames(){
  const d=await J('/api/conjunto/portfolio?min_certames=3');
  if(!d.ok)return sec('Certames')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const o=d.orgaos||[];
  let h=cover('estado','Certames — o padrão de cada órgão licitante',
    'Todos os certames indexados de cada órgão, avaliados <b>como conjunto</b>: mediana do Índice de Direcionamento (0-100, 7 famílias — inclui o que <b>ocorreu na sessão</b>: eliminações em massa ou por motivo trivial sem saneamento, art. 64 §1º), <b>reincidência</b> da mesma cláusula restritiva (≥3 certames = auditoria temática) e <b>desvio frente aos pares</b>. Um certame ruim pode ser acaso; um padrão de órgão nunca é.','🧮')+acoesAba('certames');
  const piores=o.filter(x=>(x.desvio_vs_pares||0)>10).length, aud=o.filter(x=>x.auditoria_tematica&&x.auditoria_tematica.length).length;
  h+=`<div class="grid g2">${kpi(fmtN(d.n_orgaos),'Órgãos avaliados (≥3 certames)',null,'🏢')}${kpi(d.mediana_pares!=null?d.mediana_pares.toFixed(0):'—','Mediana dos pares',null,'📏')}
      ${kpi(fmtN(piores),'Acima dos pares (+10)','var(--amber)','📈')}${kpi(fmtN(aud),'Com gatilho de auditoria temática','var(--rose)','🎯')}</div>`;
  h+=`<div class="grid" style="margin-top:14px">`+o.map(x=>{
    const md=x.score_mediana!=null?x.score_mediana:0, dv=x.desvio_vs_pares;
    const cor=md>=50?'var(--rose)':md>=25?'var(--amber)':'var(--tx2)';
    const nome=x.orgao_nome||x.orgao_cnpj;
    const audit=(x.auditoria_tematica||[]).map(a=>`<span class="tag rose">${esc(a.subtipo)} × ${a.certames} certames</span>`).join(' ');
    const ancoras=(x.casos_ancora||[]).slice(0,3).map(c=>`<span class="tag ${c.faixa==='ALTO'||c.faixa==='EXTREMO'?'rose':'accent'}" style="cursor:pointer" title="${esc(c.certame)} — clique p/ ver as 7 famílias" onclick="abrirCertame('${jsq(c.certame)}')">${c.score.toFixed(0)}·${esc(c.faixa)}</span>`).join(' ');
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><b>${esc(nome)}</b><div class="dim">${esc(x.orgao_cnpj)} · ${fmtN(x.n_avaliados??x.n_certames_indexados)} avaliados de ${fmtN(x.n_certames_indexados)} indexados</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:${cor}">${md.toFixed(0)}</div><div class="dim">mediana · p90 ${x.score_p90!=null?x.score_p90.toFixed(0):'—'}</div></div></div>
      <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">${dv!=null?`<span class="tag ${dv>10?'rose':dv>0?'amber':'teal'}">${dv>0?'+':''}${dv.toFixed(0)} vs pares</span>`:''}
        ${x.violacoes_saneamento?`<span class="tag rose">${x.violacoes_saneamento} eliminação(ões) trivial(is) sem saneamento</span>`:''}
        ${x.hhi_concentrado?`<span class="tag amber">vitórias concentradas (HHI ${x.hhi_vitorias})</span>`:''}${audit}</div>
      ${ancoras?`<div style="margin-top:6px" class="dim">casos-âncora: ${ancoras}</div>`:''}
      ${leitura(`A mediana <b>${md.toFixed(0)}/100</b> sobre os <b>${fmtN(x.n_avaliados??x.n_certames_indexados)}</b> certames com análise real (dos ${fmtN(x.n_certames_indexados)} indexados — o resto ainda sem família analisável, INDISPONÍVEL ≠ 0) ${dv!=null&&dv>10?`está <b>${dv.toFixed(0)} pontos acima</b> dos pares — o padrão do órgão destoa`:dv!=null&&dv>0?'fica levemente acima dos pares':'acompanha os pares'}.${(x.auditoria_tematica||[]).length?` A <b>mesma cláusula restritiva reincide</b> em ${x.auditoria_tematica[0].certames} certames — caso de <b>auditoria temática</b>, não de representação avulsa.`:''} Quanto menos certames indexados, menor a confiança — toque nos casos-âncora para ver o índice de cada um.`)}`,
      (dv!=null&&dv>10)||(x.auditoria_tematica||[]).length?'hl':'');}).join('')+`</div>`;
  // ── granularidade por UNIDADE/secretaria (o CNPJ guarda-chuva esconde a secretaria real) ──
  const u=await J('/api/conjunto/unidades?min_certames=3');
  if(u.ok&&(u.unidades||[]).length){
    h+=`<h3 style="margin:22px 0 4px">Por unidade / secretaria</h3>`;
    h+=`<div class="dim" style="margin-bottom:10px">O CNPJ guarda-chuva do Estado/Município esconde a secretaria real. Aqui, ${fmtN(u.n_unidades)} unidades com ≥3 certames (mediana dos pares ${u.mediana_pares!=null?u.mediana_pares.toFixed(0):'—'}). Cobertura cresce com o PNCP/enxame.</div>`;
    h+=`<div class="grid">`+u.unidades.map(x=>{
      const md=x.score_mediana!=null?x.score_mediana:0, dv=x.desvio_vs_pares;
      const cor=md>=50?'var(--rose)':md>=25?'var(--amber)':'var(--tx2)';
      const anc=(x.casos_ancora||[]).slice(0,3).map(c=>`<span class="tag ${c.faixa==='ALTO'||c.faixa==='EXTREMO'?'rose':'accent'}" style="cursor:pointer" title="${esc(c.certame)} — clique p/ ver as 7 famílias" onclick="abrirCertame('${jsq(c.certame)}')">${c.score.toFixed(0)}·${esc(c.faixa)}</span>`).join(' ');
      return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
        <div style="min-width:0"><b>${esc(x.unidade)}</b><div class="dim">${fmtN(x.n_avaliados??x.n_certames)} avaliados de ${fmtN(x.n_certames)} · ${x.n_alto_extremo} ALTO/EXTREMO</div></div>
        <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:${cor}">${md.toFixed(0)}</div><div class="dim">mediana · p90 ${x.score_p90!=null?x.score_p90.toFixed(0):'—'}</div></div></div>
        ${dv!=null?`<div style="margin-top:8px"><span class="tag ${dv>10?'rose':dv>0?'amber':'teal'}">${dv>0?'+':''}${dv.toFixed(0)} vs pares</span>${x.n_alto_extremo>0?` <span class="tag rose">${x.n_alto_extremo} certame(s) de alto risco</span>`:''}</div>`:''}
        ${anc?`<div style="margin-top:6px" class="dim">casos-âncora: ${anc}</div>`:''}
        ${leitura(`<b>${esc(x.unidade)}</b>: mediana ${md.toFixed(0)}/100 em ${fmtN(x.n_certames)} certames${x.n_alto_extremo>0?`, com <b>${x.n_alto_extremo}</b> de alto risco`:''}. ${dv!=null&&dv>10?'Padrão acima dos pares — prioridade de auditoria.':'Acompanha os pares.'} Toque nos casos-âncora para o índice de cada certame.`)}`,
        (dv!=null&&dv>10)||x.n_alto_extremo>0?'hl':'');}).join('')+`</div>`;
  }
  h+=`<div class="note">Determinístico e auditável (indício ≠ acusação; órgão/unidade sem certame indexado não aparece — INDISPONÍVEL ≠ 0). Fontes: certame_indice + clausula_veredito + certame_julgamento + PNCP.</div>`;
  return h;
}

// ═══ ADITIVOS (Estado) ═══
// ═══ CONCENTRAÇÃO × PREFEITURA (HHI por ramo de objeto — análogo municipal do Cartel) ═══
async function renderCartelMun(){
  const d=await J('/api/intel/concentracao_municipio?limite=60');
  if(!d.ok)return sec('Concentração — Prefeitura')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.orgaos||[];
  let h=cover('prefeitura','Concentração de fornecedor por mercado municipal',
    'Para cada <b>ramo de objeto</b> (limpeza, TI, veículos…), quem domina os contratos do Município do Rio: <b>top-share</b> (≥60% forte · ≥40% médio — régua R8) e <b>HHI</b> (>2.500 = mercado altamente concentrado, referência CADE). <b>Base = valor CONTRATADO</b> do PNCP — a PCRJ não publica pagamento por credor 2024+; concentração de contrato é screen de captura, não medida de execução.','🔗');
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Mercados analisados',null,'🧺')}${kpi(fmtN(d.n_criticos||0),'Concentrados (share ≥40%)','var(--rose)','🚨')}
      ${kpi(a.length?fmtN(a[0].hhi):'—','Maior HHI','var(--rose)')}${kpi(a.length?a[0].top_share+'%':'—','Maior top-share','var(--rose)')}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por ramo ou fornecedor…" oninput="filtrar(this,'#cmun-list .card')"></div>`;
  h+=`<div id="cmun-list" class="grid">`+a.map(o=>{
    const forte=o.grav>=3;
    const selo=o.ramo_canonico?'':' <span class="tag" title="agrupamento heurístico de 2 palavras — conferir o objeto real">heurístico</span>';
    const top3=(o.top3||[]).map(f=>`${esc((f.nome||f.cnpj).slice(0,34))} <b>${f.share}%</b>`).join(' <span class="dim">·</span> ');
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:700">${esc(o.orgao)}${selo} ${forte?`<span class="tag ${o.grav>=4?'rose':'amber'}">top ${o.top_share}%</span>`:''}</div>
      <div class="muted" style="font-size:12.5px;margin-top:3px">líder: ${clk(o.top_fornecedor.cnpj,o.top_fornecedor.nome||o.top_fornecedor.cnpj)} — ${fmtRc(o.top_fornecedor.valor)} em ${o.top_fornecedor.n} contrato(s)</div>
      <div class="dim" style="margin-top:2px">top 3: ${top3}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:${forte?'var(--rose)':'var(--tx2)'}">${fmtN(o.hhi)}</div><div class="dim">HHI</div></div></div>
      <div class="kv" style="margin-top:8px"><span class="k">${fmtN(o.n_contratos)} contratos · ${fmtN(o.n_fornecedores)} fornecedores · ${fmtRc(o.total)} contratados</span></div>
      ${forte?leitura(`No mercado municipal de <b>${esc(o.orgao)}</b>, <b>${esc(o.top_fornecedor.nome||'—')}</b> detém <b>${o.top_share}%</b> do valor contratado (HHI ${fmtN(o.hhi)}). Concentração nesse nível é screen de captura/R8 — verificar se decorre de ata de RP legítima, estatal prestadora ou de barreiras de entrada nos editais do ramo.`):''}`,
    forte?'hl':'');}).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}

// ═══ SANCIONADAS × PREFEITURA (contrato municipal DURANTE sanção impeditiva — TCM-RJ) ═══
async function renderSancionadasMun(){
  const d=await J('/api/intel/sancionadas_municipio?limite=100');
  if(!d.ok)return sec('Sancionadas — Prefeitura')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const emp=d.empresas||[];const aepoca=emp.filter(e=>(e.contratos_durante||0)>0);
  let h=cover('prefeitura','Sancionadas contratadas pela Prefeitura do Rio',
    'Empresas com sanção <b>impeditiva</b> (CEIS: impedimento, suspensão, inidoneidade) que assinaram contrato com o <b>Município do Rio</b>. <b>À ÉPOCA</b> = assinatura DENTRO da vigência da punição — vedação legal direta (Lei 14.133, art. 156 §§4º-5º). Competência: <b>TCM-RJ</b>. Órgãos federais/estaduais são excluídos do corte.','🚫')+acoesAba('sancionadas_municipio');
  h+=`<div class="grid g2">${kpi(fmtN(emp.length),'Sancionadas c/ contrato municipal',null,'🚫')}${kpi(fmtN(aepoca.length),'Com contrato À ÉPOCA','var(--rose)','⚠️')}
      ${kpi(fmtRc(aepoca.reduce((s,e)=>s+(e.valor_durante||0),0)),'Contratado durante sanção','var(--rose)','💸')}${kpi(fmtN(Object.values(d.descartados_outra_esfera||{}).reduce((s,v)=>s+v,0)),'Descartados (outra esfera)',null,'🧹')}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por nome ou CNPJ…" oninput="filtrar(this,'#sanm-list .card')"></div>`;
  h+=`<div id="sanm-list" class="grid">`+emp.map(e=>{
    const s0=(e.sancoes||[])[0]||{};const forte=(e.contratos_durante||0)>0;
    const ex=(e.exemplos_durante||[])[0];
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:700">${clk(e.cnpj,e.nome||e.cnpj)} ${forte?`<span class="tag rose">à época</span>`:''}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">${esc(s0.cadastro||'')}: ${esc(s0.categoria||'—')} · ${esc(s0.data_inicio||'?')} → ${esc(s0.data_fim||'sem prazo')}</div>
      <div class="dim" style="margin-top:2px">sancionador: ${esc((s0.orgao||'—').slice(0,60))}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:${forte?'var(--rose)':'var(--tx2)'}">${fmtN(e.contratos_durante||0)}/${fmtN(e.contratos||0)}</div><div class="dim">durante/total</div></div></div>
      <div class="kv" style="margin-top:8px"><span class="k">Contratado total ${fmtRc(e.valor||0)}</span><b style="color:${forte?'var(--rose)':'inherit'}">${fmtRc(e.valor_durante||0)} durante</b></div>
      ${forte&&ex?leitura(`Contrato <b>${esc(ex.contrato||'')}</b> (${esc(ex.data||'?')}, ${fmtRc(ex.valor||0)}) assinado <b>dentro da vigência</b> da sanção ${esc(ex.sancao||'')} (${esc(ex.vigencia||'')}) — "${esc((ex.objeto||'').slice(0,90))}". Vedação objetiva: matéria para representação ao TCM-RJ com pedido de apuração da habilitação.`):''}`,
    forte?'hl':'');}).join('')+`</div>`;
  h+=`<div class="note">${esc(d.explicacao||'')}</div>`;
  return h;
}

async function renderAditivos(esf='estado'){
  const d=await J('/api/intel/aditivos?limite=120&esfera='+esf);
  if(!d.ok)return sec('Aditivos')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover(esf,'Aditivos que estouram o limite legal',
    'Contrato cujo valor cresceu <b>acima do limite de acréscimo</b> (25% em regra; 50% p/ reforma — Lei 14.133 art. 125), ou com <b>change orders em série</b> (≥3 aditivos, red-flag OCDE/Banco Mundial de fraude por aditivos).','📑')+acoesAba('aditivos');
  h+=`<div class="grid g2">${kpi(fmtN(d.n_estoura_teto),'Estouram o teto legal','var(--rose)','🚨')}${kpi(fmtN(d.n_serie),'3+ aditivos em série','var(--amber)','📑')}
      ${kpi(fmtN(d.contratos_analisados),'Contratos analisados',null,'📄')}${kpi(a.length?fmtPct(a[0].pct):'—','Pior acréscimo','var(--rose)')}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por fornecedor, órgão ou objeto…" oninput="filtrar(this,'#adt-list .card')"></div>`;
  h+=`<div id="adt-list" class="grid">`+a.map(x=>{
    const forte=x.estoura_teto;
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:700">${clk(x.cnpj,x.fornecedor||x.cnpj_fmt)} ${forte?`<span class="tag rose">${fmtPct(x.pct)}</span>`:`<span class="tag amber">${x.num_aditivos} aditivos</span>`}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">${esc((x.orgao||'—').slice(0,46))}</div>
      <div class="dim" style="margin-top:2px">${esc((x.objeto||'').slice(0,90))}</div></div>
      <div class="right"><div class="num" style="font-weight:800;color:${forte?'var(--rose)':'var(--tx2)'}">${forte?fmtPct(x.pct):x.num_aditivos+'×'}</div><div class="dim">${forte?'acréscimo':'aditivos'}</div></div></div>
      <div class="kv" style="margin-top:8px"><span class="k">R$ inicial ${fmtRc(x.valor_inicial)} → global ${fmtRc(x.valor_global)}${x.acrescimo_real!=null?` · acréscimo real ${fmtRc(x.acrescimo_real)}`:''}</span><b>teto ${x.teto_pct}%</b></div>
      ${leitura(forte?`Contrato de <b>${esc(x.fornecedor||'—')}</b> saiu de ${fmtRc(x.valor_inicial)} para ${fmtRc(x.valor_global)} — <b>${fmtPct(x.pct)}</b>, acima do teto de ${x.teto_pct}% de acréscimo (${x.num_aditivos} aditivo(s)). ${x.acrescimo_real!=null?'Acréscimo classificado no termo: '+fmtRc(x.acrescimo_real)+'.':'Separar reajuste do acréscimo no termo aditivo.'}`:`${x.num_aditivos} aditivos no mesmo contrato de ${esc(x.fornecedor||'—')} (${fmtRc(x.valor_global)}). Aditamento em série é red-flag de fraude — verificar se cada termo tem justificativa e se somados estouram o limite.`)}`,
    forte?'hl':'');}).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}

// ═══ SOBREPREÇO (Estado) ═══
async function renderSobrepreco(esf='estado'){
  const d=await J('/api/intel/sobrepreco?limite=120&esfera='+esf);
  if(!d.ok)return sec('Sobrepreço')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover(esf,'Sobrepreço — pagou muito acima da mediana',
    'Mesmo item (descrição normalizada) comprado por vários órgãos: sinaliza quem pagou o preço <b>unitário</b> muito acima da mediana do grupo (≥ 2× a mediana e fora de mediana+3·MAD, medida robusta a outliers). Fonte: preço unitário homologado do PNCP.','📈')+acoesAba('sobrepreco');
  if(!a.length){
    h+=`<div class="warn" style="margin-top:12px">Base de preços unitários em formação: ${fmtN(d.itens_com_preco)} itens com preço, ${fmtN(d.grupos_comparaveis)} grupos comparáveis (≥5 compras do mesmo item). O backfill do PNCP popula o preço unitário item a item; a aba acende conforme a cobertura cresce.</div>`;
    return h+`<div class="note">${esc(d.ressalva||'')}</div>`;
  }
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Itens com sobrepreço','var(--rose)','📈')}${kpi(fmtN(d.grupos_comparaveis),'Grupos comparáveis',null,'🧺')}
      ${kpi(a.length?a[0].razao+'×':'—','Pior caso (× mediana)','var(--rose)')}${kpi(fmtRc(a.reduce((s,x)=>s+(x.sobrepreco_est*(x.amostra?1:1)),0)),'Δ acima da mediana (unit.)',null,'💸')}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por item, órgão ou fornecedor…" oninput="filtrar(this,'#sob-list .card')"></div>`;
  h+=`<div id="sob-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:700">${esc(x.item)}${x.unidade_medida?` <span class="dim">/ ${esc(x.unidade_medida)}</span>`:''}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">${esc((x.orgao||'—').slice(0,48))}${x.municipio?' · '+esc(x.municipio):''}</div>
      <div class="dim" style="margin-top:2px">venc.: ${clk(x.fornecedor_cnpj,x.fornecedor||'—')}${x.data?' · '+esc(x.data):''}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:var(--rose)">${x.razao}×</div><div class="dim">a mediana</div></div></div>
      <div class="kv" style="margin-top:8px"><span class="k">Pagou <b style="color:var(--rose)">${fmtR(x.preco)}</b> · mediana ${fmtR(x.mediana)} (n=${x.amostra})</span><b>z ${x.z_robusto}</b></div>
      ${leitura(`Este órgão pagou <b>${fmtR(x.preco)}</b> por unidade de "${esc(x.item)}", enquanto a mediana de ${x.amostra} compras do mesmo item foi <b>${fmtR(x.mediana)}</b> — <b>${x.razao}× mais caro</b> (z robusto ${x.z_robusto}). Sobrepreço unitário estimado: ${fmtR(x.sobrepreco_est)}. Confirmar marca/especificação no termo de referência.`)}`,
    'hl')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}

// ═══ ESCALADA DE PREÇO (mesmo fornecedor sobe o preço do mesmo item no tempo) ═══
async function renderEscalada(esf='estado'){
  const d=await J('/api/intel/escalada?limite=120&esfera='+esf);
  if(!d.ok)return sec('Escalada')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover(esf,'Escalada de preço — o mesmo fornecedor sobe o preço no tempo','Diferente do sobrepreço (que compara entre órgãos), aqui é <b>longitudinal</b>: o <b>mesmo fornecedor</b> vende o <b>mesmo item</b> ao poder público por preços cada vez <b>maiores</b> (≥3 compras, ≥45 dias, alta ≥3×). É o padrão de <b>preço dirigido/captura</b> — o fornecedor aprende que o comprador aceita aumentos. Cruza com a mediana de mercado dos outros fornecedores.','🪜')+acoesAba('escalada');
  if(!a.length){
    h+=`<div class="warn" style="margin-top:12px">Sem escalada detectada na janela atual de preços do PNCP — a base de preço unitário ainda é estreita no tempo. Acende conforme o histórico cresce.</div>`;
    return h+`<div class="note">${esc(d.ressalva||'')}</div>`;
  }
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Escaladas detectadas','var(--rose)','📈')}${kpi(a.filter(x=>x.final_vs_mercado&&x.final_vs_mercado>=2).length,'Também acima do mercado','var(--rose)','🎯')}
      ${kpi(a.length?a[0].razao+'×':'—','Maior escalada','var(--rose)')}${kpi(a.length?a[0].span_dias+'d':'—','Janela do pior caso',null,'📅')}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por item ou fornecedor…" oninput="filtrar(this,'#escal-list .card')"></div>`;
  h+=`<div id="escal-list" class="grid">`+a.map(x=>{
    const serie=(x.serie||[]).map(s=>`<span title="${esc(s.orgao||'')} ${esc(s.data)}">${fmtR(s.preco)}</span>`).join(' <span class="dim">→</span> ');
    const mkt=x.final_vs_mercado?`<span class="tag rose">${x.final_vs_mercado}× o mercado</span>`:'';
    return card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:700">${esc(x.item)}${x.unidade_medida?` <span class="dim">/ ${esc(x.unidade_medida)}</span>`:''}</div>
      <div class="dim" style="margin-top:2px">${clk(x.fornecedor_cnpj,x.fornecedor||'—')} · ${x.n_compras} compras em ${x.span_dias} dias ${mkt}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:var(--rose)">${x.razao}×</div><div class="dim">${fmtR(x.preco_inicial)} → ${fmtR(x.preco_final)}</div></div></div>
      <div class="kv" style="margin-top:8px"><span class="k">série: ${serie}</span></div>
      ${leitura(`<b>${esc(x.fornecedor)}</b> vendeu "${esc(x.item)}" começando em <b>${fmtR(x.preco_inicial)}</b> e chegando a <b>${fmtR(x.preco_final)}</b> (<b>${x.razao}× mais caro</b>) em ${x.span_dias} dias${x.final_vs_mercado?`, hoje <b>${x.final_vs_mercado}× a mediana de mercado</b> do item`:''}. Nenhum reajuste legítimo triplica preço nessa janela — indício de preço dirigido. Confirmar especificação no termo de referência.`)}`,
    'hl');}).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}

// ═══ COMPARADOR DE PREÇOS (quem paga mais/menos pelo mesmo item) ═══
let _compView='catalogo', _compTermo='', _compGrupo=null, _compCat=null, _compEsf='todas', _compDisp=0, _compOrd='dispersao';
async function renderComparador(){
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
const _compEsfChips=()=>`<div class="chips" style="margin:0 0 10px">
  ${['todas','estado','prefeitura'].map(e=>`<button type="button" class="chip ${_compEsf===e?'on':''}" onclick="_compEsf='${e}';ir(aba)">${e==='todas'?'🌐 Todas as esferas':e==='estado'?'🏛️ Estado':'🏙️ Prefeitura·Rio'}</button>`).join('')}</div>`;
// visão de UM item (órgãos × fornecedores) — usada pelo catálogo E pela busca
async function _compItemView(voltar){
  const d=await J('/api/comparador/item?esfera='+(_compEsf==='todas'?'':_compEsf)+'&grupo='+encodeURIComponent(_compGrupo.grupo)+'&unidade='+encodeURIComponent(_compGrupo.un||''));
  let h=`<div style="margin:4px 0 10px"><a onclick="_compGrupo=null;ir(aba)">← ${voltar}</a></div>`;
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  h+=`<h3 style="margin:6px 0">${esc(d.exemplo)} <span class="dim">/ ${esc(d.unidade_medida||'')}</span></h3>`;
  h+=`<div class="grid g2">${kpi(fmtR(d.mediana_geral),'Mediana do item','var(--amber)','⚖️')}${kpi(fmtN(d.n_orgaos),'Órgãos',null,'🏛️')}${kpi(fmtN(d.n_fornecedores),'Fornecedores',null,'🏢')}${kpi(fmtN(d.n_compras),'Compras',null,'🧾')}</div>`;
  const linha=x=>{const c=x.vs_geral>=1.5?'var(--rose)':(x.vs_geral<=0.75?'var(--green)':'var(--amber)');
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:center">
      <div style="min-width:0;flex:1"><div style="font-weight:600">${x.id?clk(x.id,x.nome):esc(x.nome||'—')}</div><div class="dim" style="font-size:12px">n=${x.n}</div></div>
      <div class="right"><div class="num" style="font-weight:800;color:${c}">${fmtR(x.mediana)}</div><div class="dim">${x.vs_geral}× a mediana</div></div></div>`,x.vs_geral>=1.5?'hl':'');};
  h+=sec('Órgãos — do que paga MAIS ao que paga MENOS')+`<div class="grid">`+d.orgaos.map(linha).join('')+`</div>`;
  h+=sec('Fornecedores — do mais caro ao mais barato')+`<div class="grid">`+d.fornecedores.slice(0,30).map(linha).join('')+`</div>`;
  return h+`<div class="note">${esc(d.ressalva||'')}</div>`;
}
const _montarGrupoCard=g=>card(
  `<div onclick='_compGrupo=${JSON.stringify({grupo:g.grupo,un:_unOf(g)})};ir("e_comp")' style="cursor:pointer;display:flex;justify-content:space-between;gap:10px;align-items:center">
    <div style="min-width:0"><div style="font-weight:600">${esc(g.exemplo)} <span class="dim">/ ${esc(g.unidade_medida||'')}</span></div>
    <div class="dim" style="font-size:12.5px">${g.n_orgaos} órgãos · ${g.n_compras} compras · mediana ${fmtR(g.mediana)}</div></div>
    <div class="right"><div class="num" style="font-weight:800;color:${g.dispersao>=5?'var(--rose)':'var(--amber)'}">${g.dispersao!=null?g.dispersao+'×':'—'}</div><div class="dim">${fmtR(g.min)}–${fmtR(g.max)}</div></div></div>`,
  g.dispersao>=10?'hl':'');
async function _compCatalogo(){
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
async function _compBuscar(){
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
function _unOf(g){return '';}  // unidade já embutida no grupo; comparar aceita todas as unidades do grupo
async function _compOrgaos(){
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
async function _compEconomia(){
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
  h+=bloco('🏢 Por FORNECEDOR (quem cobrou o excedente)', d.por_fornecedor, 'fornecedor', x=>x.fornecedor_cnpj?clk(x.fornecedor_cnpj,x.fornecedor):esc(x.fornecedor||'—'));
  return h+`<div class="note">${esc(d.ressalva||'')}</div>`;
}
async function _blocoVedada(){
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
async function _compDossie(){
  const d=await J('/api/comparador/dossie?esfera='+(_compEsf==='todas'?'':_compEsf)+'');
  if(!d.ok)return card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=`<div class="dim" style="margin-bottom:8px">${esc(d.explicacao)}</div>`;
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Casos caro + suspeito','var(--rose)','🚨')}${kpi(fmtN(d.n_sancionada),'Fornecedor SANCIONADO','var(--rose)','⚖️')}
      ${kpi(a.length?a[0].vs_mediana+'×':'—','Pior caso (× mediana)','var(--rose)')}${kpi(a.filter(x=>x.sinais.length>=2).length,'Com ≥2 sinais',null,'🎯')}</div>`;
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
async function _compForn(){
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

// ═══ RISCOS (Transversal): fantasmas · sancionadas · nunca ganham ═══
let _riscoView='fantasmas';
async function renderRiscos(){
  const chips=`<div class="chips">
    <button type="button" class="chip ${_riscoView==='fantasmas'?'on':''}" onclick="_riscoView='fantasmas';ir('g_riscos')">Fantasmas</button>
    <button type="button" class="chip ${_riscoView==='sanc'?'on':''}" onclick="_riscoView='sanc';ir('g_riscos')">Sancionadas</button>
    <button type="button" class="chip ${_riscoView==='cover'?'on':''}" onclick="_riscoView='cover';ir('g_riscos')">Nunca ganham</button></div>`;
  if(_riscoView==='sanc')return chips+acoesAba('sancionadas')+(await renderSancionadas(''));
  if(_riscoView==='cover'){
    const d=await J('/api/intel/perdedoras');
    let h=cover('geral','Perdedoras contumazes — participam e NUNCA vencem',
      'Empresa que compete "sempre" e nunca vence é o perfil clássico de <b>proposta de cobertura</b> (OCDE bid rigging): existe para dar aparência de disputa e legitimar o vencedor combinado. Quanto mais vezes perde junto do MESMO vencedor, mais forte o indício.','🎭')+chips+acoesAba('perdedoras');
    if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
    const cov=d.cobertura_extracao||{};
    h+=`<div class="grid g2">${kpi(fmtN(d.n),'Perdedoras contumazes','var(--amber)','🎭')}${kpi(fmtN(cov.atas_entrada),'Atas no corpus',null,'📄')}${kpi(fmtN(cov.atas_avaliaveis),'Atas avaliáveis',null,'✅')}${kpi(fmtN(cov.certames_no_grafo),'Certames no grafo',null,'🕸️')}</div>`;
    if((cov.atas_avaliaveis||0)<50)h+=`<div class="warn" style="margin-top:12px">Cobertura ainda pequena: só ${fmtN(cov.atas_avaliaveis)} de ${fmtN(cov.atas_entrada)} atas têm participantes+resultado extraíveis. O PNCP publica apenas o vencedor; os perdedores vêm do texto das atas — a extração é conservadora de propósito (zero falso-positivo) e cresce com o corpus.</div>`;
    h+=`<div class="grid" style="margin-top:12px">`+(d.perdedoras||[]).map(p=>card(
      `<div style="display:flex;justify-content:space-between;gap:10px"><div style="min-width:0">${clk(p.cnpj,p.nome!=='—'?p.nome:p.cnpj_fmt)}<div class="dim">${esc(p.cnpj_fmt)}</div></div>
       <div class="right"><div class="num" style="font-weight:800;font-size:19px;color:var(--amber)">${p.participou}×</div><div class="dim">participou · 0 vitórias</div></div></div>
       ${(p.perde_junto_com||[]).length?leitura('Perde junto com: '+(p.perde_junto_com||[]).map(x=>`<b>${esc(x.nome!=='—'?x.nome:x.cnpj)}</b> (${x.vezes}×)`).join(' · ')+' — o co-participante mais frequente é o beneficiário provável da cobertura.'):''}`)).join('')+`</div>`;
    h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
    return h;
  }
  // fantasmas
  const d=await J('/api/intel/fantasmas?limite=60');
  let h=cover('geral','Radar de empresas-fantasma',
    'Score 0-100 por <b>8 sinais objetivos</b> (situação irregular na Receita, capital incompatível com o que recebe, endereço-ninho, endereço residencial, aberta às vésperas do 1º contrato, sócio único + capital baixo, CNAE incompatível, sanção). Aplicado ao conjunto-alvo: vencedoras de captura/rodízio, perdedoras contumazes, sancionadas e top favorecidos.','👻')+chips+acoesAba('fantasmas');
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const emp=(d.empresas||[]).filter(e=>e.classificacao!=='sem_cadastro');
  h+=`<div class="grid g2">${kpi(fmtN(d.total_alvo),'Empresas no alvo',null,'🎯')}${kpi(fmtN(emp.filter(e=>e.classificacao==='alto').length),'Risco ALTO','var(--rose)','🔴')}
      ${kpi(fmtN(emp.filter(e=>e.classificacao==='medio').length),'Risco médio','var(--amber)','🟡')}${kpi(fmtN(d.sem_cadastro),'Sem cadastro ainda','var(--dim)','⏳')}</div>`;
  if(d.sem_cadastro>0)h+=`<div class="warn" style="margin-top:12px"><b>${fmtN(d.sem_cadastro)}</b> empresas do alvo ainda sem cadastro da Receita na base (fila de enriquecimento). "Sem cadastro" NÃO significa regular — significa não-avaliada.</div>`;
  h+=`<div class="grid" style="margin-top:12px">`+emp.slice(0,50).map(e=>{
    const cor=e.classificacao==='alto'?'var(--rose)':e.classificacao==='medio'?'var(--amber)':'var(--green)';
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0">${clk(e.cnpj,e.razao_social||e.cnpj)}<div class="dim">${esc(e.cnpj)} · no alvo por: ${rot(e.origem||'—')}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:${cor}">${e.score??'—'}</div><div class="dim">/100 ${esc(e.classificacao)}</div></div></div>
      ${(e.sinais||[]).length?`<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">${e.sinais.map(s=>`<span class="tag ${e.classificacao==='alto'?'rose':'amber'}" title="${esc(s.detalhe||'')}">${rot(s.id)} +${s.peso}</span>`).join('')}</div>`:''}
      ${(e.sinais||[]).length?leitura(esc((e.sinais[0]||{}).detalhe||'')+((e.sinais||[]).length>1?' — e mais '+(e.sinais.length-1)+' sinal(is); toque no nome para o dossiê completo.':'')):''}`,e.classificacao==='alto'?'hl':'');}).join('')+`</div>`;
  h+=`<div class="note">${esc(d.explicacao||'')} ${esc(d.ressalva||'')}</div>`;
  return h;
}

// ═══ PREFEITURA DO RIO ═══
async function renderPanoramaPref(){
  const [cj,cc,bv]=await Promise.all([J('/api/pncp/conluio?esfera=prefeitura'),J('/api/pcrj/comissionados_candidatos?limite=1'),J('/api/pcrj/beneficios_vinculo')]);
  const cov=cj.cobertura||{},cap=cj.captura||[],rod=cj.rodizio_vencedores||[];
  let h=cover('prefeitura','Prefeitura do Rio de Janeiro','Licitações do MUNICÍPIO do Rio pelo PNCP (esfera oficial), folha de comissionados, candidaturas e benefícios sociais. Os demais municípios do RJ ficam em Transversal → Conluio → chip "Municípios".','🏙️');
  h+=`<div class="grid g2">
    ${kpi(fmtN(cov.certames_com_resultado),'Certames do município',null,'📄','p_contr')}${kpi(fmtN(cov.orgaos),'Órgãos compradores',null,'🏢','p_gastos')}
    ${kpi(cap.length+rod.length,'Conluio (capturas+rodízios)','var(--purple)','🕸️','p_conluio')}${kpi(fmtN(cc.n_pessoas??cc.n??'—'),'Comissionados ex-candidatos','var(--amber)','🎖️','p_comis')}
    ${kpi(fmtN((bv.resumo||{}).n_alta??'—'),'Benefício DURANTE vínculo (certeza alta)','var(--rose)','🚨','p_benef')}${kpi(fmtN((bv.resumo||{}).n_ainda??'—'),'Ainda recebendo','var(--rose)','⏰','p_benef')}</div>`;
  h+=`<div style="height:16px"></div>`+sec('Ir para')+`<div class="grid two">
    ${card(`<div style="font-weight:700">Perícia de gastos D7–D10</div><div class="muted" style="font-size:13px">fracionamento, credor recém-aberto, sócio na folha, rede entre concorrentes</div><div class="btns"><button class="btn accent" onclick="ir('p_gastos')">Abrir</button></div>`)}
    ${card(`<div style="font-weight:700">Comissionados</div><div class="muted" style="font-size:13px">ex-candidatos + benefício social durante o vínculo</div><div class="btns"><button class="btn accent" onclick="ir('p_comis')">Abrir</button></div>`)}
    ${card(`<div style="font-weight:700">Servidor-fantasma</div><div class="muted" style="font-size:13px">8 sinais determinísticos, faixas forte/verificar/fraco</div><div class="btns"><button class="btn ghost" onclick="ir('p_fant')">Abrir</button></div>`)}
    ${card(`<div style="font-weight:700">PPPs e concessões</div><div class="muted" style="font-size:13px">triagem de red flags CCPAR + dossiê Souza Aguiar</div><div class="btns"><button class="btn ghost" onclick="ir('p_ppp')">Abrir</button></div>`)}
    ${card(`<div style="font-weight:700">Conluio municipal</div><div class="muted" style="font-size:13px">${cap.length+rod.length} indícios · nomes e objetos</div><div class="btns"><button class="btn ghost" onclick="ir('p_conluio')">Abrir</button></div>`)}</div>`;
  h+=`<div class="note">${esc(cj.aviso||'')}</div>`;
  return h;
}
let _comisView='cand';
async function renderComissionadosPref(){
  const chips=`<div class="chips">
    <button type="button" class="chip ${_comisView==='cand'?'on':''}" onclick="_comisView='cand';ir('p_comis')">Foram candidatos</button>
    <button type="button" class="chip ${_comisView==='benef'?'on':''}" onclick="_comisView='benef';ir('p_comis')">Benefício × vínculo</button></div>`;
  if(_comisView==='benef')return renderBeneficiosPref(chips);
  const d=await J('/api/pcrj/comissionados_candidatos?limite=1000');
  let h=cover('prefeitura','Comissionados da Prefeitura que foram candidatos',
    'Cruzamento da folha de cargos de confiança da Prefeitura do Rio com as candidaturas registradas no TSE. Cargo de confiança ocupado por quem disputa eleição é o retrato do aparelhamento político da máquina. Cada card é <b>uma pessoa</b>, com o histórico completo de nomeações — não mais uma linha por vínculo.','🗳️')+chips+acoesAba('comissionados');
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const it=d.comissionados||[];  // agora 1 item por PESSOA, com postos[] e candidaturas[]
  const nCidades=new Set(it.flatMap(x=>(x.candidaturas||[]).map(c=>c.cidade)).filter(Boolean)).size;
  h+=`<div class="grid g2">${kpi(fmtN(d.n_pessoas||it.length),'Pessoas ex-candidatas','var(--amber)','🎖️')}${kpi(fmtN(nCidades),'Cidades de candidatura',null,'🗺️')}</div>`;
  h+=buscaPag('cc-list','filtrar por nome, cargo, órgão, cidade — busca em TODAS as pessoas…');
  if(d.truncado)h+=`<div class="note" style="margin-top:8px">Base tem mais pessoas do que o teto do servidor (1000) — caso raro; avise se precisar de mais.</div>`;
  const _montarCC=x=>{
    const postos=(x.postos||[]).map(p=>`<div class="dim" style="margin-top:2px">${esc(p.cargo||'—')} @ ${esc((p.orgao||'—').slice(0,50))} — ${esc(p.admissao||'?')}${p.exoneracao?' → '+esc(p.exoneracao):' · ativo'}</div>`).join('');
    const cands=(x.candidaturas||[]).map(c=>`<span class="tag amber">${esc(c.cargo||'?')} ${esc(String(c.ano||''))}${c.cidade?' · '+esc(c.cidade):''}</span>`).join(' ');
    const homon=x.homonimo_provavel?` <span class="tag" title="candidatou em 3+ cidades — provável homônimo, não a mesma pessoa">homônimo provável</span>`:'';
    return card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">
      <div style="font-weight:700">${esc(x.nome_pcrj)}${x.n_postos>1?` <span class="tag" style="font-weight:400">${x.n_postos} nomeações</span>`:''}${homon}</div>
      ${postos}</div>
      <div class="right" style="text-align:right">${cands}</div></div>`);
  };
  h+=listaPaginada('cc-list',it,_montarCC,60,x=>x.nome_pcrj);
  h+=`<div class="note">${esc(d.explicacao||'')} ${esc(d.ressalva||'')}</div>`;
  return h;
}
async function renderBeneficiosPref(chips){
  const d=await J('/api/pcrj/beneficios_vinculo');
  chips=(chips||'')+acoesAba('beneficios');
  let h=cover('prefeitura','Servidores × benefício social — DURANTE o vínculo',
    'Pessoas que recebiam <b>Bolsa Família, BPC, Auxílio Brasil ou Auxílio Emergencial</b> (programas para quem tem baixa renda) <b>no mesmo mês</b> em que tinham salário como servidor/comissionado da Prefeitura ou Câmara do Rio. Meses fora do vínculo NÃO entram (justiça na contagem). É <b>indício de renda incompatível a apurar</b> — nunca acusação: pode haver dependente no mesmo CPF, homônimo ou erro de base. Cada linha traz o <b>nome</b>, o órgão, o cargo e o período.','🍞')+(chips||'');
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const r=d.resumo||{};
  // legenda dos dois eixos que confundiam: IDENTIDADE (quem é a pessoa) × BENEFÍCIO (o que recebeu)
  h+=`<div class="note" style="margin:10px 0 4px"><b>Como ler:</b> <span class="sev alta" style="padding:1px 7px">identidade confirmada</span> = há UM só servidor com esse nome na folha e o fragmento de CPF bate (é mesmo esta pessoa). <span class="sev media" style="padding:1px 7px">conferir homônimo</span> = nome comum, confirmar o CPF antes de usar. Isso é sobre <b>QUEM é a pessoa</b> — separado de <span class="tag rose">ainda recebe</span>, que diz que o benefício <b>continua ativo</b> hoje.</div>`;
  h+=`<div class="grid g2">${kpi(fmtN(d.n_casos),'Pessoas identificadas','var(--amber)','👥')}${kpi(fmtN(r.n_alta),'Identidade confirmada (nome único + CPF)','var(--rose)','🪪')}
      ${kpi(fmtN(r.n_nomeados),'Comissionados/nomeados','var(--amber)','🎖️')}${kpi(fmtN(r.n_ainda),'Benefício ainda ativo','var(--rose)','⏰')}
      ${kpi(fmtN(r.n_bf),'Bolsa Família',null,'🍞')}${kpi(fmtN(r.n_bpc),'BPC',null,'♿')}
      ${kpi(esc(r.cobertura_benef||'—'),'Cobertura benefícios',null,'📅')}${kpi(esc(r.ultima||'—'),'Última competência',null,'🗓️')}</div>`;
  h+=buscaPag('bv-list','filtrar por nome, órgão, cargo, partido — busca em TODOS os casos…');
  const _montarBV=x=>{
    const idOk=x.certeza==='ALTA';
    const selo=idOk?'<span class="sev alta" title="um só servidor com este nome + CPF bate — é esta pessoa">identidade confere</span>'
                  :'<span class="sev media" title="nome comum — confirmar CPF antes de usar">conferir homônimo</span>';
    return card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">
      <div style="font-weight:800;font-size:15px">${esc(x.nome)}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">${[x.poder,(x.orgao||'').slice(0,44),(x.cargo||'').slice(0,30),x.partido].filter(Boolean).map(esc).join(' · ')}</div>
      <div class="dim" style="margin-top:3px">${[x.natureza,x.situacao,x.cargo?'':'cargo não informado pela fonte'].filter(Boolean).map(esc).join(' · ')}</div></div>
      <div class="right">${selo}
      ${x.ainda_recebe?'<div style="margin-top:5px"><span class="tag rose" title="o benefício continua ativo na última competência">ainda recebe</span></div>':''}</div></div>
    <div class="kv" style="margin-top:8px"><span class="k">${esc(x.beneficios_str||'benefício')}</span><b>${esc(x.desde||'')} → ${esc(x.ate||'')} · ${fmtN(x.n_meses)} meses no vínculo</b></div>`,
    idOk?'hl':'');};
  h+=listaPaginada('bv-list',d.casos||[],_montarBV,60,x=>x.nome);
  h+=`<div class="note">${esc(d.explicacao||'')} ${esc(d.ressalva||'')}</div>`;
  return h;
}
const _DET_ROTULO={d7_fracionamento:['✂️','Fracionamento de despesa','sucessão de contratações do mesmo objeto/credor somando acima do teto de dispensa (Lei 14.133 art. 75)'],
  d8_credor_recem_aberto:['🐣','Credor recém-aberto','empresa criada há <180 dias já recebendo da Prefeitura'],
  d9_socio_na_folha:['👔','Sócio de credor na folha','sócio de empresa contratada com vínculo na folha municipal (Lei 14.133 art. 9º)'],
  d10_rede_concorrentes:['🕸️','Rede entre concorrentes','sócios em comum entre empresas que disputam os mesmos certames'],
  d11_aditivo_estourado:['📈','Aditivo acima do limite','acréscimo contratual além dos 25%/50% do art. 125'],
  d12_coendereco_concorrentes:['📍','Co-endereço (OCDE)','fornecedores concorrentes do mesmo órgão no mesmo CEP']};
let _gastosDet='';
async function renderGastosPref(){
  const d=await J('/api/pcrj/gastos_achados');
  let h=cover('prefeitura','Perícia de gastos — detectores D7–D12',
    'Detectores determinísticos sobre a despesa por credor (ContasRio 2019-2023) e contratos/licitações municipais (PNCP 2024+): fracionamento, credor recém-aberto, sócio na folha, rede societária, aditivo acima do limite e co-endereço entre concorrentes (red flag OCDE 2025). Cada achado carrega a evidência e a base normativa; a perícia completa em PDF sai pelo runner com o colegiado de 5 lentes.','✂️')+acoesAba('gastos_pcrj');
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)} — rode tools/pcrj_pericia_gastos.py</div>`);
  const dets=Object.keys(d.detectores||{});
  h+=`<div class="grid g2">`+dets.map(k=>{const m=_DET_ROTULO[k]||['📌',k,''];
    return kpi(fmtN(d.detectores[k]),m[1],k==='d9_socio_na_folha'?'var(--rose)':null,m[0]);}).join('')+`</div>`;
  h+=`<div class="chips" style="margin-top:12px"><button type="button" class="chip ${_gastosDet===''?'on':''}" onclick="_gastosDet='';ir('p_gastos')">Todos</button>`+
    dets.map(k=>`<button type="button" class="chip ${_gastosDet===k?'on':''}" onclick="_gastosDet='${k}';ir('p_gastos')">${(_DET_ROTULO[k]||['📌',k])[0]} ${(_DET_ROTULO[k]||['',k])[1]}</button>`).join('')+`</div>`;
  h+=`<div class="search"><span class="mag"></span><input placeholder="filtrar por credor, órgão, objeto…" oninput="filtrar(this,'#pg-list .card')"></div>`;
  const mostrar=_gastosDet?{[_gastosDet]:(d.achados||{})[_gastosDet]||[]}:(d.achados||{});
  let cards='';
  for(const [det,lista] of Object.entries(mostrar)){
    const m=_DET_ROTULO[det]||['📌',det,''];
    cards+=(lista||[]).slice(0,_gastosDet?200:12).map(a=>card(
      `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">
        <div style="font-weight:700">${m[0]} ${esc((a.titulo||'').slice(0,90))}</div>
        <div class="muted" style="font-size:12.5px;margin-top:4px">${esc((a.descricao||'').slice(0,260))}</div></div>
        <span class="sev ${a.severidade==='alta'?'alta':'media'}">${esc(a.severidade||'')}</span></div>`,
      a.severidade==='alta'?'hl':'')).join('');
  }
  h+=`<div id="pg-list" class="grid">`+cards+`</div>`;
  if(!cards)h+=card('<div class="muted">Nenhum achado deste detector na última corrida — a base é revarrida a cada sweep; um resultado limpo aqui é um resultado, não um vazio.</div>');
  h+=`<div class="note">${esc(d.explicacao||'')} ${esc(d.ressalva||'')}</div>`;
  return h;
}
let _fantFaixa='';
async function renderFantasmasPref(){
  const qsF=new URLSearchParams({limite:800});  // 800 = teto real do servidor (rotas/investigacao.py)
  if(_fantFaixa)qsF.set('faixa',_fantFaixa);
  const d=await J('/api/pcrj/fantasmas?'+qsF.toString());
  let h=cover('prefeitura','Sinais de servidor-fantasma — Câmara/Prefeitura',
    'Oito sinais determinísticos (múltiplos gabinetes, cargo incompatível, vínculos concomitantes, geografia impossível…) somados em escore. É funil de priorização OSINT: a prova definitiva é o ponto/frequência interno, que só a apuração formal alcança.','👻')+acoesAba('fantasmas_pcrj');
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const fx=d.faixas||{};
  h+=`<div class="grid g2">${kpi(fmtN(fx.forte),'Faixa FORTE','var(--rose)','🔴')}${kpi(fmtN(fx.verificar),'Verificar','var(--amber)','🟡')}${kpi(fmtN(fx.fraco),'Fraco',null,'🟢')}${kpi(esc((d.gerado_em||'').slice(0,10)),'Gerado em',null,'🗓️')}</div>`;
  h+=`<div class="chips" style="margin-top:12px">`+['','forte','verificar','fraco'].map(f=>
    `<button type="button" class="chip ${_fantFaixa===f?'on':''}" onclick="_fantFaixa='${f}';ir('p_fant')">${f||'Todas as faixas'}</button>`).join('')+`</div>`;
  h+=buscaPag('pf-list','filtrar por nome ou gabinete — busca em TODOS os servidores…');
  const _itF=d.itens||[];
  const _montarF=x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">
      <div style="font-weight:700">${esc(x.nome)}${x.homonimo?' <span class="tag amber" title="nome existe em ≥3 municípios — confirmar por CPF/matrícula">homônimo?</span>':''}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">${esc((x.gabinetes||'—').slice(0,60))} · ${esc((x.cargos_camara||'—').slice(0,40))}</div>
      <div class="dim" style="margin-top:4px">${esc((x.sinais||'').slice(0,200))}</div></div>
      <div class="right"><span class="sev ${x.faixa==='forte'?'alta':'media'}">${esc(x.faixa)}</span><div class="dim" style="margin-top:4px">score ${x.score}</div></div></div>`,
    x.faixa==='forte'?'hl':'');
  h+=listaPaginada('pf-list',_itF,_montarF,60,x=>x.nome);
  h+=`<div class="note">${esc(d.explicacao||'')} ${esc(d.ressalva||'')}</div>`;
  return h;
}
async function renderPPPPref(){
  const d=await J('/api/ppp/triagem');
  let h=cover('prefeitura','PPPs e concessões — triagem de red flags',
    'Lente determinística sobre editais/anexos de PPP da CCPAR: garantia com receita de saúde, aporte público, PMI-captura, prazo, valor vs RCL. O dossiê pericial completo (perícia mestre, íntegras normativas) sai por /ppp no Yoda.','🏗️');
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const r=d.resumo||{};
  h+=`<div class="grid g2">${kpi(fmtN(r.projetos),'Projetos triados',null,'🏗️')}${kpi(fmtN(r.alto),'Grau ALTO','var(--rose)','🔴')}${kpi(fmtN(r.medio),'Grau médio','var(--amber)','🟡')}${kpi(fmtN(r.cobertura_doe_ppp),'Matérias D.O. PPP',null,'📰')}</div>`;
  h+=`<div class="grid" style="margin-top:14px">`+(d.itens||[]).map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">
      <div style="font-weight:700">${esc(x.nome)}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">fase: ${esc(x.fase||'—')} · fonte: ${esc(x.fonte||'—')}</div>
      <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">${(x.flags||[]).map(f=>`<span class="tag ${['garantia_receita_saude','aporte_publico','pmi_privado_ressarcimento'].includes(f)?'rose':'accent'}">${esc(f.replace(/_/g,' '))}</span>`).join('')}</div></div>
      <div class="right"><span class="sev ${(x.grau||'').includes('alto')?'alta':'media'}">${esc(x.grau||'')}</span><div class="dim" style="margin-top:4px">${x.n_altas} flag(s) alta(s)</div></div></div>`,
    (x.grau||'').includes('alto')?'hl':'')).join('')+`</div>`;
  h+=leitura('PPP transfere risco de décadas para o ente público. As três flags vermelhas — garantia com receita da saúde (CF art. 167 IV), aporte público e PMI ressarcida pelo vencedor — são as que a jurisprudência trata como as mais graves.');
  return h;
}
const _TEMA_ROTULO={transparencia:'transparência',competicao:'competição',conluio:'conluio',fraude_cadastral:'fraude cadastral',preco:'preço',execucao:'execução',certame_ata:'sessão/ata'};
let _ctrView='analise';
async function renderContratosPref(){
  const chips=`<div class="chips">
    <button type="button" class="chip ${_ctrView==='analise'?'on':''}" onclick="_ctrView='analise';ir('p_contr')">Com análise (base local)</button>
    <button type="button" class="chip ${_ctrView==='vivo'?'on':''}" onclick="_ctrView='vivo';ir('p_contr')">Publicadas agora (PNCP ao vivo)</button></div>`;
  if(_ctrView==='vivo'){
    const r=await J('/api/pncp?uf=RJ&dias=45&esfera=prefeitura');const its=(r.contratacoes||r.dados||r.itens||[]);
    let h=cover('prefeitura','Contratações recentes (PNCP ao vivo)','Últimas licitações da PREFEITURA DO RIO publicadas no PNCP (esfera oficial do ente). Fonte pública, sem login — pode demorar: é a API nacional ao vivo.','📄')+chips;
    h+=sec('Publicadas (45 dias)',its.length);
    if(!its.length)return h+card('<div class="muted">Sem contratações no período (ou API do PNCP indisponível agora — a visão "Com análise" usa a base local e sempre responde).</div>');
    h+=buscaPag('ctr-list','filtrar por objeto ou órgão…');
    h+=listaPaginada('ctr-list',its,c=>card(`<div style="font-weight:650;font-size:13.5px">${esc((c.objeto||c.objetoCompra||'—')).slice(0,140)}</div><div class="muted" style="font-size:12.5px;margin-top:3px">${esc((c.orgao||c.orgaoNome||c.unidade||'')).slice(0,60)} ${c.valor||c.valorTotal?'· '+fmtRc(c.valor||c.valorTotal):''}</div>`),60);
    return h;
  }
  const d=await J('/api/certames/lista?esfera=prefeitura&limite=600');
  let h=cover('prefeitura','Contratações do município — cada uma com a sua análise','Certames da PREFEITURA DO RIO na base local, cada um com o <b>Índice de Direcionamento</b> (0-100) e os <b>temas</b> (7 famílias: transparência, competição, conluio, fraude cadastral, preço, execução, sessão/ata) onde acendeu sinal. Toque num card para a análise completa das 7 famílias. Certame sem análise = INDISPONÍVEL (≠ 0) — a cobertura cresce com o enxame.','📄')+chips+acoesAba('contratos_analise');
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const its=d.itens||[],rs=d.resumo||{};
  h+=`<div class="grid g2">${kpi(fmtN(rs.total),'Certames na base',null,'📄')}${kpi(fmtN(rs.analisados),'Com análise (índice calculado)','var(--amber)','🧮')}</div>`;
  h+=buscaPag('ctr-list','filtrar por objeto ou nº de controle — busca em TODOS os certames…');
  const _montarCtr=c=>{
    const cor=c.faixa==='EXTREMO'||c.faixa==='ALTO'?'var(--rose)':c.faixa==='MEDIO'?'var(--amber)':'var(--tx2)';
    const temas=(c.temas||[]).slice(0,4).map(t=>`<span class="tag ${t.valor>=0.6?'rose':t.valor>=0.3?'amber':'accent'}">${esc(_TEMA_ROTULO[t.familia]||t.familia)} ${(t.valor*100).toFixed(0)}%</span>`).join(' ');
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:650;font-size:13.5px">${esc((c.objeto||'—')).slice(0,140)}</div>
      <div class="muted" style="font-size:12.5px;margin-top:3px">${esc(c.nc)} · ${c.ano||''}${c.valor_estimado?' · estimado '+fmtRc(c.valor_estimado):''}</div>
      ${temas?`<div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">${temas}</div>`:''}</div>
      <div class="right" style="text-align:right">${c.analisado
        ?`<div class="num" style="font-weight:800;font-size:19px;color:${cor}">${c.score.toFixed(0)}</div><div class="dim">${esc(c.faixa||'')} · conf. ${((c.confianca||0)*100).toFixed(0)}%</div>`
        :`<span class="tag" title="nenhuma das 7 famílias era analisável ainda — INDISPONÍVEL, não zero">sem análise</span>`}</div></div>`,
      c.faixa==='EXTREMO'||c.faixa==='ALTO'?'hl':'');
  };
  h+=`<div onclick="const c=event.target.closest('.card');if(!c)return;const nc=c.dataset.nc;if(nc)abrirCertame(nc);">`;
  // listaPaginada não injeta data-attrs — embrulha cada card com o nc pro clique
  const _wrap=c=>_montarCtr(c).replace('<div class="card','<div data-nc="'+esc(c.nc)+'" style="cursor:pointer" class="card');
  h+=listaPaginada('ctr-list',its,_wrap,60,c=>(c.objeto||'').slice(0,70))+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}

// ═══ CONLUIO (esfera-aware; no Transversal tem chips de esfera) ═══
let _cjEsf='';
async function renderConluio(esf){
  const d=await J('/api/pncp/conluio'+(esf?'?esfera='+esf:''));
  const rotulos={estado:'órgãos estaduais',prefeitura:'Prefeitura do Rio',municipios:'demais municípios do RJ',federal:'órgãos federais no RJ','':'todas as esferas'};
  const rot=rotulos[esf]??esf;
  if(!d.ok)return sec('Conluio')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const cov=d.cobertura||{},cap=d.captura||[],rod=d.rodizio_vencedores||[],esfs=d.esferas||{};
  let h=cover(esf==='prefeitura'?'prefeitura':esf==='estado'?'estado':'geral','Conluio em licitações · '+rot,
    'Vencedor homologado de cada item (fonte: PNCP, esfera OFICIAL do ente). <b>Captura</b>: uma empresa vence quase tudo num órgão. <b>Rodízio</b>: 2-3 empresas se revezam em compras parecidas. Toque num card para ver o que foi comprado — cada achado explica por que importa.','🕸️')+acoesAba('conluio');
  // chips de esfera (só na visão Transversal, onde a comparação faz sentido)
  if(esfera==='geral'){
    const chip=(id,tl)=>`<button type="button" class="chip ${(_cjEsf===id)?'on':''}" onclick="_cjEsf='${id}';ir('g_conluio')">${tl}${esfs[id]!=null?` <span class="dim">${fmtN(esfs[id])}</span>`:''}</button>`;
    h+=`<div class="chips">${chip('','🌐 Todas')}${chip('estado','🏛️ Estado')}${chip('prefeitura','🏙️ Pref. Rio')}${chip('municipios','🏘️ Municípios')}${chip('federal','🏦 Federais')}</div>`;
  }
  h+=`<div class="grid g2">${kpi(fmtN(cov.certames_com_resultado),'Certames analisados',null,'📄')}${kpi(fmtN(cov.orgaos),'Órgãos compradores',null,'🏢')}${kpi(cap.length,'Capturas','var(--rose)','🎯')}${kpi(rod.length,'Rodízios','var(--amber)','🔁')}</div>`;
  if(cov.certames_sem_unidade>0)h+=`<div class="warn" style="margin-top:12px"><span>Identificação do órgão comprador em andamento: <b>${fmtN(cov.certames_sem_unidade)}</b> de ${fmtN(cov.certames_com_resultado)} certames ainda aparecem no nome do ente (ex.: "Estado do Rio de Janeiro"). O backfill do PNCP completa isso automaticamente.</span></div>`;
  const orgHead=x=>`<div style="font-weight:700">${esc(x.orgao_nome)}</div>${x.ente_nome&&x.ente_nome!==x.orgao_nome?`<div class="dim" style="margin-top:1px">${esc(x.ente_nome)} · ${esc(x.orgao_cnpj_fmt||'')}</div>`:''}`;
  if(cap.length){h+=`<div style="height:16px"></div>`+sec('Captura de órgão · 1 empresa vence ≥80%',cap.length)+`<div class="grid">`+cap.map(c=>card(
    `<div class="exp" onclick="toggle(this)"><div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0">${orgHead(c)}<div class="muted" style="font-size:13px;margin-top:4px">quem venceu: ${clk(c.fornecedor_cnpj_fmt,c.nome)}</div><div class="dim" style="margin-top:2px">${esc(c.fornecedor_cnpj_fmt)}</div></div>
      <div class="right"><div class="num" style="font-weight:800;color:var(--rose);font-size:20px">${Math.round(c.share*100)}%</div><div class="dim">das vitórias</div></div></div>
      ${leitura(`<b>${esc(c.nome)}</b> venceu ${Math.round(c.share*100)}% dos <b>${c.certames}</b> certames deste órgão (${c.distintos||'—'} concorrentes distintos apareceram no período). Concentração ≥80% é o gatilho OCDE de <b>mercado capturado</b>: pode ser mérito ou mercado raso — o próximo passo é comparar as propostas perdedoras e o QSA dos concorrentes.`)}
      <div class="objs">${(c.objetos||[]).map(o=>`<div class="obj">${esc(o)}</div>`).join('')||'<div class="dim">sem objeto</div>'}</div>
      <div class="dim" style="margin-top:8px"><span class="chev">▸</span> o que foi comprado</div></div>`,'hl')).join('')+`</div>`;}
  if(rod.length){h+=`<div style="height:16px"></div>`+sec('Rodízio de vencedores · revezamento em objeto parecido',rod.length)+`<div class="grid">`+rod.map(r=>{
    const nomes=(r.membros_nome||[]).map(m=>`<b>${esc(m.nome)}</b> (${m.vitorias}×)`).join(' · ');
    return card(
    `<div class="exp" onclick="toggle(this)"><div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0">${orgHead(r)}<div class="muted" style="font-size:13px;margin-top:4px">${r.certames} certames · o grupo levou ${Math.round(r.cobertura_grupo*100)}% deles</div></div>
      <span class="tag amber">${(r.membros_nome||[]).length} empresas</span></div>
      ${r.coesao_objeto!=null?`<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;align-items:center"><span class="tag ${r.coesao_objeto>=0.6?'rose':'teal'}" title="quão parecidos são os objetos dos certames deste grupo">compras ${Math.round(r.coesao_objeto*100)}% parecidas</span>${(r.termos_comuns||[]).slice(0,4).map(t=>`<span class="tag accent">${esc(t)}</span>`).join('')}</div>`:'<div class="dim" style="margin-top:6px">sem objeto comparável (rodízio no nível do órgão)</div>'}
      ${leitura(`${nomes} se revezam nas vitórias de compras ${r.coesao_objeto!=null?`<b>${Math.round(r.coesao_objeto*100)}% parecidas</b>`:'deste órgão'}${(r.termos_comuns||[]).length?` (em comum: ${r.termos_comuns.slice(0,3).map(esc).join(', ')})`:''}. Revezamento equilibrado no MESMO tipo de objeto é o padrão nº 1 de <b>combinação de propostas</b> (OCDE) — verificar QSA, endereços e quem mais participou de cada certame.`)}
      <table style="margin-top:10px"><tbody>${(r.membros_nome||[]).map(m=>`<tr><td>${clk(m.cnpj,m.nome)}<div class="dim">${esc(m.cnpj)}</div></td><td class="num"><b>${m.vitorias}</b> <span class="dim">vitórias</span></td></tr>`).join('')}</tbody></table>
      <div class="objs">${(r.objetos||[]).map(o=>`<div class="obj">${esc(o)}</div>`).join('')||'<div class="dim">sem objeto</div>'}</div>
      <div class="dim" style="margin-top:8px"><span class="chev">▸</span> o que foi comprado</div></div>`);}).join('')+`</div>`;}
  if(!cap.length&&!rod.length)h+=card('<div class="muted">Nenhum padrão de captura ou rodízio com o volume atual desta esfera. A base cresce a cada coleta do PNCP.</div>');
  if(esfera==='geral')h+=`<div style="height:14px"></div>`+card(`<div style="font-weight:700">E quem participa e NUNCA vence?</div><div class="muted" style="font-size:13px;margin-top:3px">As perdedoras contumazes (candidatas a proposta de cobertura) estão em Riscos.</div><div class="btns"><button class="btn ghost" onclick="_riscoView='cover';ir('g_riscos')">Abrir perdedoras</button></div>`);
  h+=`<div class="note">${esc(d.aviso||'')}</div>`;
  return h;
}

// ═══ PERÍCIAS ═══
let _perOrdem='score',_perGrau='';
async function renderPericias(){
  const d=await J('/api/pericias?limite=80&ordem='+_perOrdem+(_perGrau?'&grau='+encodeURIComponent(_perGrau):''));
  const it=d.itens||[];
  let h=cover('estado','Perícias de fornecedor','8.648 fornecedores periciados (grau 🟢🟡🔴 + achados). Clique num nome para o dossiê 360.','⚖️');
  h+=`<div class="chips">
    <button type="button" class="chip ${_perGrau===''?'on':''}" onclick="_perGrau='';ir('e_pericias')">Todos</button>
    <button type="button" class="chip ${_perGrau==='🟡'?'on':''}" onclick="_perGrau='🟡';ir('e_pericias')">Atenção</button>
    <button type="button" class="chip ${_perGrau==='🔴'?'on':''}" onclick="_perGrau='🔴';ir('e_pericias')">Grave</button>
    <button type="button" class="chip ${_perOrdem==='total'?'on':''}" onclick="_perOrdem=_perOrdem==='total'?'score':'total';ir('e_pericias')">↕ ${_perOrdem==='total'?'ordenar: R$':'ordenar: score'}</button></div>`;
  h+=`<div class="search"><span class="mag"></span><input placeholder="filtrar por nome ou CNPJ…" oninput="filtrar(this,'#per-list .card')"></div>`;
  h+=`<div id="per-list" class="grid">`+it.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:center"><div style="min-width:0"><div>${clk(x.cnpj,x.favorecido||x.cnpj)}</div>
      <div class="dim">${(x.indicios||0)} indício(s) · ${x.ugs} órgão(s) · ${fmtN(x.n_obs)} OBs</div></div>
      <div class="right"><div style="font-size:18px">${x.grau||'⚪'}</div><div class="dim">${fmtRc(x.total)}</div></div></div>`)).join('')+`</div>`;
  if(!it.length)h+=card('<div class="muted">Nenhum fornecedor casa esse filtro — a busca varre nome, CNPJ e objeto; tente um pedaço do nome ou só os dígitos do CNPJ.</div>');
  return h;
}

// ═══ AUTOCOMPLETE genérico (empresas + nomeados, /api/sugestoes) ═══
let _acTimer=null,_acItens=[],_acCb=null,_acSelIdx=-1;
function _acRenderSel(box){[...box.querySelectorAll('.ac-item')].forEach((el,i)=>el.classList.toggle('sel',i===_acSelIdx));}
function _acPick(i){const it=_acItens[i];if(!it)return;document.querySelectorAll('.ac-box.on').forEach(b=>b.classList.remove('on'));if(_acCb)_acCb(it);}
function autocompletar(input,boxSel,onPick){
  clearTimeout(_acTimer);
  const box=document.querySelector(boxSel);if(!box)return;
  const q=input.value.trim();_acSelIdx=-1;
  if(q.length<2){box.classList.remove('on');return;}
  _acTimer=setTimeout(async()=>{
    const d=await J('/api/sugestoes?q='+encodeURIComponent(q));
    if(input.value.trim()!==q)return;  // resposta atrasada de digitação antiga — descarta
    const emp=(d.empresas||[]).map(e=>({tipo:'empresa',nome:e.nome,cnpj:e.cnpj,sub:e.cnpj||'',...e}));
    const nom=(d.nomeados||[]).map(n=>({tipo:'nomeado',nome:n.nome,sub:`${n.cargo||''} · ${(n.orgao||'').slice(0,30)} (${n.esfera})`,...n}));
    _acItens=[...emp,...nom];_acCb=onPick;
    if(!_acItens.length){box.classList.remove('on');return;}
    box.innerHTML=_acItens.map((it,i)=>`<div class="ac-item" data-i="${i}" onmousedown="event.preventDefault();_acPick(${i})">${it.tipo==='empresa'?'🏢':'👤'} <b>${esc(it.nome||'')}</b><span class="dim">${esc(it.sub||'')}</span></div>`).join('');
    box.classList.add('on');
  },250);
}
function acKeydown(ev,input,boxSel,onEnterSemSelecao){
  const box=document.querySelector(boxSel);
  if(!box||!box.classList.contains('on')){if(ev.key==='Enter')onEnterSemSelecao();return;}
  if(ev.key==='ArrowDown'){ev.preventDefault();_acSelIdx=Math.min(_acSelIdx+1,_acItens.length-1);_acRenderSel(box);}
  else if(ev.key==='ArrowUp'){ev.preventDefault();_acSelIdx=Math.max(_acSelIdx-1,0);_acRenderSel(box);}
  else if(ev.key==='Enter'){if(_acSelIdx>=0){ev.preventDefault();_acPick(_acSelIdx);}else{box.classList.remove('on');onEnterSemSelecao();}}
  else if(ev.key==='Escape'){box.classList.remove('on');}
}
// ═══ BUSCA universal ═══
let _bq='';
async function renderBuscar(){
  return cover('geral','Busca universal','Procure por empresa, CNPJ, órgão, contrato ou termo. Clique num resultado para o dossiê 360.','🔎')+
    `<div class="search"><span class="mag"></span><input id="bq" placeholder="nome, CNPJ ou objeto — ex.: engenharia, limpeza, 42498733000148…" value="${esc(_bq)}"
       oninput="autocompletar(this,'#bq-ac',(it)=>{$('bq').value=it.nome;if(it.tipo==='empresa'&&it.cnpj)abrirDossie(it.cnpj,it.nome);else fazBusca();})"
       onkeydown="acKeydown(event,this,'#bq-ac',fazBusca)">
     <div id="bq-ac" class="ac-box"></div></div>
     <div class="btns" style="margin-top:-2px"><button class="btn accent" onclick="fazBusca()">Buscar</button></div>
     <div id="bres" style="margin-top:14px">${_bq?spin():'<div class="dim" style="text-align:center;padding:20px">Digite acima e toque em Buscar (ou escolha uma sugestão).</div>'}</div>`;
}
async function fazBusca(){
  const q=($('bq')||{}).value?.trim()||'';if(!q)return;_bq=q;const box=$('bres');box.innerHTML=spin('Buscando "'+esc(q)+'"…');
  const r=await J('/api/compliance/buscar?q='+encodeURIComponent(q));
  if(r.error){box.innerHTML=card(`<div class="warn">${esc(r.error)}</div>`);return;}
  const forn=r.fornecedores||[],ctr=r.contratos||[],doe=r.doerj||[],alt=r.alertas||[];let h='';
  if(forn.length){h+=sec('Fornecedores',forn.length)+`<div class="grid">`+forn.slice(0,30).map(f=>{const cnpj=(f.cnpj||'').replace(/\D/g,'');
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:center"><div style="min-width:0">${clk(cnpj,f.nome||f.razao_social||cnpj)}<div class="dim">${esc(f.cnpj_fmt||f.cnpj||'')}</div></div>${f.total_pago!=null?`<div class="right"><b>${fmtRc(f.total_pago)}</b><div class="dim">${fmtN(f.n_obs||0)} OBs</div></div>`:''}</div>`);}).join('')+`</div>`;}
  if(ctr.length)h+=`<div style="height:14px"></div>`+sec('Contratos',ctr.length)+`<div class="grid">`+ctr.slice(0,20).map(c=>card(`<div style="font-weight:650;font-size:13.5px">${esc((c.objeto||c.descricao||'contrato')).slice(0,140)}</div><div class="muted" style="font-size:12.5px;margin-top:3px">${esc(c.fornecedor||c.contratado||'')} ${c.valor?'· '+fmtRc(c.valor):''}</div>`)).join('')+`</div>`;
  if(doe.length)h+=`<div style="height:14px"></div>`+sec('Diário Oficial',doe.length)+`<div class="grid">`+doe.slice(0,12).map(x=>card(`<div style="font-size:13px">${esc((x.texto||x.trecho||JSON.stringify(x)).slice(0,220))}</div>`)).join('')+`</div>`;
  if(alt.length)h+=`<div style="height:14px"></div>`+sec('Alertas',alt.length)+`<div class="grid">`+alt.slice(0,12).map(x=>card(`<div style="font-size:13px">${esc(x.titulo||x.tipo||JSON.stringify(x).slice(0,180))}</div>`)).join('')+`</div>`;
  box.innerHTML=h||card('<div class="muted">Nada encontrado. Tente nome parcial, CNPJ ou objeto.</div>');
}

// ═══ PODER / LARANJAS / CARTEL / ALERTAS / SIAFE / SWEEPS / VALIDAR / AÇÕES ═══
async function renderPoder(){
  const d=await J('/api/poder/nomeados_candidatos?limite=1000');
  if(!d.ok)return sec('Poder')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const it=d.itens||[];
  let h=cover('estado','Nomeados × candidatos (Estado)','Servidor público estadual (folhas: Defensoria/RJ + Câmara Municipal do Rio + TJRJ) que também foi candidato a cargo eletivo, sobretudo cargo em comissão. Cruzamento por nome (verificar homônimo). Os comissionados da PREFEITURA estão na esfera Prefeitura → Comissionados.','🏛️')+acoesAba('nomeados');
  h+=`<div class="grid g2">${kpi(it.length,'Cruzamentos',null,'🏛️')}${kpi(d.n_comissionados,'Comissionados','var(--rose)','🎖️')}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por nome, cargo, partido…" oninput="filtrar(this,'#pod-list .card')"></div>`;
  h+=`<div id="pod-list" class="grid">`+it.map(x=>card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0"><div style="font-weight:700">${esc(x.nome)}</div><div class="muted" style="font-size:13px;margin-top:2px">${esc(x.orgao||'—')} · ${esc(x.cargo_folha||'—')}</div></div>${x.comissionado?'<span class="tag rose">comissão</span>':'<span class="tag accent">efetivo</span>'}</div><div class="kv" style="margin-top:8px"><span class="k">Disputou</span><b>${esc(x.cargo_disputado||'—')} · ${esc(x.partido||'—')} · ${esc(x.ano||'—')}</b></div>`)).join('')+`</div>`;
  h+=`<div class="note">${esc(d.aviso||'')}</div>`;return h;
}
async function renderSocioServidor(){
  const d=await J('/api/intel/socio_servidor?limite=150');
  if(!d.ok)return sec('Servidor-sócio')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Servidor público sócio de fornecedor do Estado',
    'Servidor que aparece nas folhas coletadas e também é sócio de empresa que recebeu do Estado. Servidor <b>administrador/diretor</b> de empresa privada viola a vedação estatutária de gerência; se a empresa contrata com o órgão dele, há impedimento (Lei 14.133 art. 9). <b>Confiança ALTA</b> = nome e fragmento de CPF batem; <b>MÉDIA</b> = só o nome.','🕴️')+acoesAba('socio_servidor');
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Servidores sócios','var(--rose)','🕴️')}${kpi(fmtN(d.n_gerencia),'Com gerência (vedada)','var(--rose)','⚖️')}
      ${kpi(fmtN(d.n_art9||0),'Art. 9 (mesmo órgão)','var(--rose)','🎯')}${kpi(fmtN(d.n_alta),'Confiança ALTA (CPF)','var(--amber)','🔎')}</div>`;
  h+=`<div class="dim" style="margin-top:8px">Folhas cruzadas: ${esc((d.folhas||[]).join(', '))||'—'}. Homônimos descartados por CPF: ${fmtN(d.homonimos_descartados)}. Art. 9 = empresa paga pela própria repartição do servidor (impedimento direto).</div>`;
  h+=`<div class="search" style="margin-top:12px"><span class="mag"></span><input placeholder="filtrar por servidor, empresa, órgão ou cargo…" oninput="filtrar(this,'#ss-list .card')"></div>`;
  h+=`<div id="ss-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:700">${esc(x.socio)} ${x.mesmo_orgao?'<span class="tag rose">art. 9 · mesmo órgão</span>':x.gerencia?'<span class="tag rose">gerência</span>':'<span class="tag amber">sócio</span>'}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">${esc(x.qualificacao)} de ${clk(x.cnpj,x.empresa)}</div>
      <div class="dim" style="margin-top:2px">servidor: ${esc(x.servidor_cargo||'—')} · ${esc((x.servidor_orgao||'').slice(0,40))} · ${esc(x.vinculo||'')}</div>
      ${(x.ugs_pagadoras||[]).length&&x.ugs_pagadoras[0].nome?`<div class="dim" style="margin-top:2px">paga por: ${(x.ugs_pagadoras||[]).filter(u=>u.nome).map(u=>esc(u.nome)+' ('+fmtRc(u.valor)+')').join(' · ')}</div>`:''}</div>
      <div class="right"><span class="tag ${x.confianca==='ALTA'?'rose':'accent'}">${esc(x.confianca)}</span>
      <div class="num" style="margin-top:6px;font-weight:800">${fmtRc(x.total_pago)}</div><div class="dim">recebido · ${fmtN(x.n_obs)} OBs</div></div></div>
      ${leitura(`<b>${esc(x.socio)}</b> é <b>${esc(x.qualificacao)}</b> da empresa <b>${esc(x.empresa)}</b> (recebeu ${fmtRc(x.total_pago)} do Estado) e consta na folha como <b>${esc(x.servidor_cargo||'servidor')}</b> ${esc(x.servidor_orgao?('do '+x.servidor_orgao):'')}.${x.mesmo_orgao?' <b>A empresa é paga pela PRÓPRIA repartição do servidor — impedimento direto do art. 9.</b>':x.gerencia?' Cargo de gerência em empresa privada é vedado ao servidor (estatuto).':''} ${x.confianca==='ALTA'?'Nome e fragmento de CPF coincidem.':'Casamento por nome — confirmar CPF.'}`)}`,
    x.mesmo_orgao||x.confianca==='ALTA'||x.gerencia?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}
// ═══ FORNECEDOR DEPENDENTE / CATIVO ═══
async function renderCapital(){
  const d=await J('/api/intel/capital_incompativel?limite=150');
  if(!d.ok)return sec('Capital irrisório')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Capital irrisório — sem lastro para o que faturou','Empresa com <b>capital social ínfimo</b> (&lt; R$50 mil) que recebeu do Estado <b>≥100× o próprio capital</b> (e mais de R$1 mi). Subcapitalização crônica frente ao volume faturado é indício de <b>fachada/interposição</b> — falta capacidade econômico-financeira para executar contratos vultosos (Lei 14.133 art. 5º, 62-63). Capital: dump da Receita.','🫧')+acoesAba('capital_incompativel');
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Empresas','var(--rose)','🫧')}${kpi(a.length?fmtN(a[0].razao)+'×':'—','Pior razão (recebido/capital)','var(--rose)')}
      ${kpi(fmtRc(a.reduce((s,x)=>s+(x.total_recebido||0),0)),'Volume recebido',null,'💰')}${kpi(a.filter(x=>x.capital<=1000).length,'Capital ≤ R$1k','var(--amber)','⚠️')}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por empresa…" oninput="filtrar(this,'#cap-list .card')"></div>`;
  h+=`<div id="cap-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">${clk(x.cnpj,x.nome||x.cnpj_fmt)}<div class="dim">${esc(x.cnpj_fmt)} · ${fmtN(x.n_obs)} OBs</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:var(--rose)">${fmtN(x.razao)}×</div><div class="dim">o capital</div></div></div>
      <div class="kv" style="margin-top:8px"><span class="k">capital <b>${fmtR(x.capital)}</b></span><b>recebeu ${fmtRc(x.total_recebido)}</b></div>
      ${leitura(`<b>${esc(x.nome)}</b> tem capital social de apenas <b>${fmtR(x.capital)}</b> mas recebeu <b>${fmtRc(x.total_recebido)}</b> do Estado — <b>${fmtN(x.razao)}× o próprio capital</b>. Capital irrisório frente ao volume faturado é indício de subcapitalização/fachada. Confirmar o capital ATUAL (o dump é de um mês) e a capacidade econômico-financeira.`)}`,
    x.razao>=1000?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}
async function renderPrioridade(){
  const d=await J('/api/intel/prioridade_valor?limite=80');
  if(!d.ok)return sec('Prioridade por valor em risco')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Prioridade — onde a auditoria rende mais','Fila que cruza <b>risco × dinheiro</b>: fornecedores que o <b>radar</b> já marca (sinal aceso) <b>E</b> que têm <b>economia recuperável</b> (pagaram acima da mediana de mercado do item). Risco alto sem dinheiro pode esperar; dinheiro alto sem sinal pode ser variação legítima — o cruzamento dos dois no mesmo CNPJ é a fila que rende mais por hora de apuração.','⚡')+acoesAba('prioridade_valor');
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Na interseção','var(--teal)','⚡')}${kpi(fmtRc(d.economia_em_risco),'Economia em risco',null,'💰')}
      ${kpi(a.filter(x=>x.score>=25).length,'Sinal médio+ (🟡🔴)','var(--amber)')}${kpi(a.length?fmtRc(a[0].economia):'—','Maior isolado','var(--rose)')}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por empresa ou sinal…" oninput="filtrar(this,'#pri-list .card')"></div>`;
  h+=`<div id="pri-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">${clk(x.cnpj,x.nome||x.cnpj_fmt)}<div class="dim">${esc(x.cnpj_fmt)} · ${fmtN(x.n_compras)} compra(s) acima da mediana</div>
      <div style="margin-top:6px;display:flex;gap:5px;flex-wrap:wrap">${(x.sinais||[]).slice(0,4).map(s=>`<span class="tag teal">${rot(s)}</span>`).join('')}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:var(--teal)">${fmtRc(x.economia)}</div><div class="dim">${x.rating} score ${fmtN(x.score)}</div></div></div>
      ${leitura(`<b>${esc(x.nome)}</b> junta <b>sinal de risco</b> (${(x.sinais||[]).map(rot).join(', ')||'—'}, score ${fmtN(x.score)}/100) com <b>${fmtRc(x.economia)}</b> de sobrepreço recuperável sobre ${fmtN(x.n_compras)} compra(s) acima da mediana de mercado. Priorizar: risco + dinheiro no mesmo fornecedor. Economia é teto teórico (mediana atingível), não valor a ressarcir.`)}`,
    x.score>=50?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.escala||'')} — ${esc(d.ressalva||'')}</div>`;
  return h;
}
async function renderFornecedorDependente(){
  const d=await J('/api/intel/fornecedor_dependente?limite=150');
  if(!d.ok)return sec('Cativos')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Fornecedor cativo — "empresa do órgão"','Empresa comercial que recebe <b>quase tudo (≥90%)</b> de UMA única unidade gestora do Estado. Dependência total de um comprador é o perfil de fornecedor cativo — mercado fechado, risco de direcionamento.','🔗')+acoesAba('fornecedor_dependente');
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Fornecedores cativos','var(--amber)','🔗')}${kpi(fmtRc(a.reduce((s,x)=>s+x.total,0)),'Volume dependente',null,'💰')}
      ${kpi(a.filter(x=>x.share>=0.99).length,'100% de 1 órgão','var(--rose)','🎯')}${kpi(a.length?Math.round(a[0].share*100)+'%':'—','Maior dependência')}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por empresa ou UG…" oninput="filtrar(this,'#dep-list .card')"></div>`;
  h+=`<div id="dep-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">${clk(x.cnpj,x.nome||x.cnpj_fmt)}<div class="dim">${esc(x.cnpj_fmt)}</div>
      <div class="muted" style="font-size:12.5px;margin-top:3px">UG ${esc(String(x.ug))} ${esc(x.ug_nome||'')} · aparece em ${x.n_ugs} órgão(s)</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:${x.share>=0.99?'var(--rose)':'var(--amber)'}">${Math.round(x.share*100)}%</div><div class="dim">de ${fmtRc(x.total)}</div></div></div>
      ${leitura(`<b>${esc(x.nome)}</b> recebeu <b>${Math.round(x.share*100)}%</b> de tudo (${fmtRc(x.total)}) da UG ${esc(String(x.ug))} ${esc(x.ug_nome||'')}. Empresa comercial dependente de um só comprador é o perfil de fornecedor cativo — checar o histórico de licitações desse órgão.`)}`,
    x.share>=0.99?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

// ═══ CORRIDA DE DEZEMBRO ═══
async function renderCorridaDezembro(){
  const d=await J('/api/intel/corrida_dezembro?limite=150');
  if(!d.ok)return sec('Dezembro')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Corrida do empenho de dezembro','Fornecedor comercial que recebeu <b>a maior parte do ano em dezembro</b> (≥75%). Concentração no fim do exercício é red-flag de "corrida do empenho" — verba usada às pressas antes de perder o orçamento, terreno fértil para dispensa e direcionamento.','📅')+acoesAba('corrida_dezembro');
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Fornecedores concentrados','var(--amber)','📅')}${kpi(fmtRc(a.reduce((s,x)=>s+x.dezembro,0)),'Pago em dezembro',null,'💰')}
      ${kpi(a.filter(x=>x.share>=0.99).length,'100% em dezembro','var(--rose)','🎯')}${kpi(a.length?Math.round(a[0].share*100)+'%':'—','Maior concentração')}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por empresa…" oninput="filtrar(this,'#dez-list .card')"></div>`;
  h+=`<div id="dez-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">${clk(x.cnpj,x.nome||x.cnpj_fmt)}<div class="dim">${esc(x.cnpj_fmt)} · ${fmtN(x.n_obs)} OBs</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:${x.share>=0.99?'var(--rose)':'var(--amber)'}">${Math.round(x.share*100)}%</div><div class="dim">em dezembro</div></div></div>
      <div class="kv" style="margin-top:8px"><span class="k">${fmtRc(x.dezembro)} em dezembro</span><b>de ${fmtRc(x.total)} no ano</b></div>
      ${leitura(`<b>${esc(x.nome)}</b> recebeu <b>${Math.round(x.share*100)}%</b> do valor do ano (${fmtRc(x.total)}) só em dezembro. Concentração no fim do exercício sugere corrida do empenho — verificar se houve planejamento ou uso apressado da verba.`)}`,
    x.share>=0.99?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

// ═══ RADAR DE RISCO (score composto) ═══
async function renderRadar(){
  const d=await J('/api/intel/radar?limite=150');
  if(!d.ok)return sec('Radar')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Radar de risco — todos os detectores somados','Score <b>0-100</b> por fornecedor somando sinais independentes de todos os detectores (conluio societário, sanção à época, fantasma, servidor-sócio, perdedora contumaz, fênix). Um detector isolado é indício fraco; <b>vários acesos no mesmo CNPJ raramente são coincidência</b> — esta é a fila de apuração priorizada.','🎯')+acoesAba('radar_risco');
  // a cor era 'var(--rose)' FIXA: com zero críticos o painel mostrava "0" em vermelho
  // com triângulo de alerta — boa notícia vestida de alarme, e o oposto de "coisas
  // graves brilham graves" (se tudo grita, nada grita). A cor segue o número contra
  // o limiar que a própria escala declara; abaixo dele, neutro e sem ícone.
  const _nVerm=Number(d.n_vermelho||0), _maior=a.length?Number(a[0].score):null;
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Fornecedores com sinal',null)}${kpi(fmtN(_nVerm),'Score ≥50 (crítico)',_nVerm>0?'var(--rose)':null)}
      ${kpi(_maior!=null?_maior:'—','Maior score',_maior!=null&&_maior>=50?'var(--rose)':null)}${kpi(a.filter(x=>x.n_sinais>=3).length,'Com ≥3 sinais',null)}</div>`;
  h+=`<div class="dim" style="margin-top:8px">${esc(d.escala||'').replace(/\b([a-z]+_[a-z_]+)\b/g,m=>rot(m))}</div>`;
  h+=`<div class="search" style="margin-top:12px"><input placeholder="filtrar por empresa ou sinal…" oninput="filtrar(this,'#radar-tbl tbody tr')"></div>`;
  h+=`<div class="card" style="padding:4px 15px;overflow-x:auto"><table id="radar-tbl"><thead><tr><th>Fornecedor</th><th style="text-align:left">Sinais que dispararam</th><th class="right">Nº</th><th class="right">Score</th></tr></thead><tbody>`+
    a.map(x=>`<tr><td style="min-width:180px">${clk(x.cnpj,x.nome||x.cnpj_fmt)}<div class="dim mono" style="font-size:11px">${esc(x.cnpj_fmt)}</div></td>
      <td style="text-align:left;max-width:520px" title="${esc((x.sinais||[]).map(s=>rot(s.sinal)+(s.detalhe?' — '+s.detalhe:'')).join(' · '))}">${(x.sinais||[]).map(s=>`<span class="tag ${s.peso>=25?'rose':'amber'}">${rot(s.sinal)} +${s.peso}</span>`).join('')}</td>
      <td class="num">${x.n_sinais}</td>
      <td style="white-space:nowrap"><span class="meter ${x.score>=50?'crit':''}"><i style="width:${Math.min(100,x.score)}%"></i></span><b class="num" style="color:${x.score>=50?'var(--rose)':'var(--amber)'}">${x.score}</b></td></tr>`).join('')+
    `</tbody></table></div>`;
  h+=`<div class="note">${esc(d.ressalva||'')} Score sempre acompanhado das regras que o dispararam — clique no nome para a trilha completa no dossiê.</div>`;return h;
}

// ═══ CONLUIO DIRETO (vencedor × perdedora × QSA) ═══
async function renderConluioQSA(){
  const d=await J('/api/intel/conluio_qsa');
  if(!d.ok)return sec('Conluio QSA')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.pares||[];const cob=d.cobertura||{};
  let h=cover('geral','Conluio direto — vencedor × perdedora do mesmo dono','Vencedor e perdedora do <b>MESMO certame</b> com <b>sócio em comum</b> no QSA da Receita (ou matriz×filial "concorrendo" entre si). A perdedora do mesmo dono existe para dar aparência de disputa — <b>proposta de cobertura</b> (OCDE bid rigging; art. 337-F do CP). Fontes: resultados PNCP + atas de julgamento do corpus.','🤝')+acoesAba('conluio_qsa');
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Pares vencedor×perdedora','var(--rose)','🤝')}${kpi(fmtN(d.n_forte||0),'Fortes (QSA/matriz-filial)','var(--rose)','🚨')}
      ${kpi(fmtN(cob.certames_com_perdedora||0),'Certames com perdedora conhecida',null,'⚖️')}${kpi(fmtN(cob.pares_sem_qsa||0),'Pares sem QSA local (INDISPONÍVEL ≠ 0)','var(--amber)','❓')}</div>`;
  h+=`<div class="search" style="margin-top:12px"><span class="mag"></span><input placeholder="filtrar por empresa ou sócio…" oninput="filtrar(this,'#cq-list .card')"></div>`;
  h+=`<div id="cq-list" class="grid">`+a.map(x=>{
    const socios=(x.socios_comuns||[]).map(s=>esc(s.nome)).slice(0,3).join(', ')||'matriz × filial (mesmo CNPJ-raiz)';
    const tcls=x.tier==='MEDIA'?'amber':'rose';
    return card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">
      <div style="font-weight:700">${clk(x.vencedor.cnpj,x.vencedor.nome)} <span class="dim">venceu</span></div>
      <div style="font-weight:700">${clk(x.perdedora.cnpj,x.perdedora.nome)} <span class="dim">perdeu</span></div>
      <div class="muted" style="font-size:12.5px;margin-top:4px"><span class="tag ${tcls}">${esc(x.tier)}</span> sócio(s) em comum: ${socios}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:var(--rose)">${x.n_certames}</div><div class="dim">certame(s) · ${fmtRc(x.valor_vencido)}</div></div></div>
      ${leitura(`<b>${esc(x.vencedor.nome)}</b> venceu ${x.n_certames} certame(s) (${fmtRc(x.valor_vencido)}) em que <b>${esc(x.perdedora.nome)}</b> — ${x.tier==='MESMA_EMPRESA'?'a PRÓPRIA empresa (outra filial)':'empresa com sócio em comum'} — aparecia como concorrente. Disputa de fachada: o dono ganha dos dois lados. Confirmar CPF completo do sócio antes de citar.`)}`,
    x.tier!=='MEDIA'?'hl':'');}).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

// ═══ COMUNIDADES (Louvain) ═══
async function renderComunidades(){
  const d=await J('/api/intel/comunidades');
  if(!d.ok)return sec('Comunidades')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.comunidades||[];const g=d.grafo||{};
  let h=cover('geral','Comunidades — clusters família-empresa-órgão (Louvain)','Algoritmo de comunidades (Louvain) sobre o grafo de <b>sócios (QSA), disputas em comum e dinheiro dos mesmos órgãos</b>. O cluster denso pessoa+empresa+órgão é o desenho clássico do grupo econômico oculto atrás de licitações. Score 0-100 por sinais objetivos dentro do cluster.','🧩')+acoesAba('comunidades',`<a class="btn ghost" style="flex:0 0 auto;min-width:150px" href="/graph?fonte=comunidades" target="_blank">Grafo das comunidades</a>`);
  // mesmo conserto do radar: zero cluster crítico não é alarme (cor e 🚨 eram fixos)
  const _nCrit=a.filter(x=>x.score>=50).length;
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Comunidades relevantes','var(--amber)','🧩')}${kpi(fmtN(_nCrit),'Score ≥50 (🔴)',_nCrit>0?'var(--rose)':null,_nCrit>0?'🚨':'')}
      ${kpi(fmtN(g.nos||0),'Nós no grafo',null,'🕸️')}${kpi(fmtN(g.arestas||0),'Arestas',null,'🔗')}</div>`;
  h+=`<div class="dim" style="margin-top:8px">${esc(d.escala||'').replace(/\b([a-z]+_[a-z_]+)\b/g,m=>rot(m))}</div>`;
  h+=`<div class="search" style="margin-top:12px"><span class="mag"></span><input placeholder="filtrar por empresa, pessoa ou órgão…" oninput="filtrar(this,'#com-list .card')"></div>`;
  h+=`<div id="com-list" class="grid">`+a.map(x=>{
    const emp=(x.membros||[]).filter(m=>m.tipo==='empresa').slice(0,4).map(m=>esc(m.label));
    const pes=(x.membros||[]).filter(m=>m.tipo==='pessoa').slice(0,3).map(m=>esc(m.label));
    const org=(x.membros||[]).filter(m=>m.tipo==='orgao').slice(0,2).map(m=>esc(m.label));
    return card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">
      <div style="font-weight:700">${x.rating} Comunidade #${x.id} · ${x.n_empresas} empresa(s), ${x.n_pessoas} pessoa(s), ${x.n_orgaos} órgão(s)</div>
      <div class="muted" style="font-size:12.5px;margin-top:3px">${emp.join(' · ')||'—'}</div>
      <div class="muted" style="font-size:12.5px">${pes.join(' · ')||'—'} &nbsp; 🏛️ ${org.join(' · ')||'—'}</div>
      <div class="muted" style="font-size:12.5px;margin-top:4px">${(x.sinais||[]).map(s=>`<span class="tag ${s.peso>=20?'rose':'amber'}">${esc(s.sinal)} +${s.peso}</span>`).join(' ')}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:22px;color:${x.score>=50?'var(--rose)':'var(--amber)'}">${x.score}</div><div class="dim">${fmtRc(x.valor_total)}</div></div></div>
      ${leitura(`Cluster com <b>${x.n_empresas}</b> empresa(s) e <b>${x.n_pessoas}</b> pessoa(s) movimentando <b>${fmtRc(x.valor_total)}</b>${(x.sinais||[]).length?', com sinais: '+esc(x.sinais.map(s=>s.sinal+(s.detalhe?' ('+s.detalhe+')':'')).join('; ')):''}. Densidade ${x.densidade}. Mapa de onde olhar — não prova de conluio.`)}`,
    x.score>=50?'hl':'');}).join('')+`</div>`;
  if(d.articuladores&&d.articuladores.length){
    h+=sec('Articuladores (pontes entre grupos)')+`<div class="grid">`+d.articuladores.slice(0,10).map(x=>card(
      `<div style="display:flex;justify-content:space-between;gap:10px"><div><b>${esc(x.label)}</b> <span class="dim">${esc(x.tipo)}</span></div>
       <div class="right"><span class="num">${x.grau}</span> <span class="dim">conexões</span></div></div>`)).join('')+`</div>`;}
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

// ═══ RETRO-AUDITORIA (hindsight) ═══
async function renderRetro(){
  const d=await J('/api/intel/retro');
  if(!d.ok)return sec('Retro')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const ps=d.por_sinal||{};const ex=d.exemplos||[];const j=d.janela||{};
  const nsin=Object.values(ps).reduce((s,x)=>s+x.n_sinais,0);
  const ncor=Object.values(ps).reduce((s,x)=>s+x.n_sancao_depois,0);
  const pago=Object.values(ps).reduce((s,x)=>s+x.pago_depois,0);
  let h=cover('geral','Retro-auditoria — o que aconteceu DEPOIS do alerta','Para cada detector, o <b>ledger de sinais</b> guarda a data do 1º alerta por empresa (nunca regravada). Aqui medimos o que veio depois: <b>sanção federal posterior</b> (corroboração independente do detector) e <b>R$ que o Estado continuou pagando após o alerta</b> — o custo da inação. A janela cresce todo dia com o timer.','🔮')+acoesAba('retro');
  h+=`<div class="grid g2">${kpi(fmtN(nsin),'Sinais no ledger','var(--amber)','📒')}${kpi(fmtN(ncor),'Sanção DEPOIS do sinal','var(--rose)','⚖️')}
      ${kpi(fmtRc(pago),'Pago APÓS o alerta','var(--rose)','💸')}${kpi((j.sinal_mais_antigo_dias??'—')+'d','Idade do sinal mais antigo',null,'📅')}</div>`;
  h+=`<div class="dim" style="margin-top:8px">Janela retro de ${j.sinal_mais_antigo_dias??'—'} dia(s) — zeros são esperados no começo (sanção demora); a leitura fica forte com semanas de ledger.</div>`;
  h+=sec('Por detector')+`<div class="grid">`+Object.entries(ps).map(([s,v])=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px"><div><b>${esc(s)}</b>
      <div class="muted" style="font-size:12.5px;margin-top:3px">${fmtN(v.n_sinais)} empresa(s) sinalizadas · ${fmtN(v.vitorias_depois)} vitória(s) PNCP depois</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:${v.n_sancao_depois?'var(--rose)':'var(--amber)'}">${v.n_sancao_depois}</div><div class="dim">sanção depois · ${fmtRc(v.pago_depois)} pago depois</div></div></div>`)).join('')+`</div>`;
  if(ex.length){h+=sec('Casos (sanção posterior ou pagamento pós-alerta)')+`<div class="grid">`+ex.slice(0,20).map(e=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px"><div style="min-width:0">${clk(e.cnpj,e.cnpj)}
      <div class="muted" style="font-size:12.5px">[${esc(e.sinal)}] desde ${esc(e.desde)} · ${esc(e.detalhe||'')}</div>
      ${e.sancao_depois?`<div class="muted" style="font-size:12.5px;margin-top:2px"><span class="tag rose">sancionada em ${esc(e.sancao_depois.data_inicio)}</span> ${esc(e.sancao_depois.cadastro||'')}</div>`:''}</div>
      <div class="right"><div class="num" style="font-weight:800;color:var(--rose)">${fmtRc(e.pago_depois)}</div><div class="dim">pago após o alerta</div></div></div>`,
    e.sancao_depois?'hl':'')).join('')+`</div>`;}
  h+=await _liftBloco();
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

// bloco de LIFT: valida cada detector contra o gabarito objetivo (sanções)
async function _liftBloco(){
  const d=await J('/api/intel/lift');
  if(!d.ok)return '';
  const det=d.detectores||[];
  const barra=(l,circ)=>{const w=Math.min(100,(l||0)/15*100);const col=circ?'var(--muted)':(l>=2?'var(--rose)':(l>=1?'var(--amber)':'var(--green,var(--green))'));
    return `<div style="background:rgba(255,255,255,.06);border-radius:4px;height:8px;overflow:hidden"><div style="width:${w}%;height:100%;background:${col}"></div></div>`;};
  let h=sec('Validação contra o gabarito objetivo (sanções) — lift por detector');
  h+=`<div class="dim" style="margin-bottom:8px">Taxa-base do universo: <b>${(d.taxa_base*100).toFixed(1)}%</b> dos ${fmtN(d.universo)} fornecedores são sancionados. <b>Lift</b> = quantas vezes o detector concentra sancionados acima disso. <b>lift ≥ 2</b> = sinal forte · <b>~1</b> = ruído · <b>&lt; 1</b> = anti-sinal · <span class="dim">circular</span> = usa sanção como input (não é corroboração independente).</div>`;
  h+=`<div class="grid">`+det.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:12px;align-items:center">
      <div style="min-width:0;flex:1"><div style="font-weight:700">${rot(x.detector)} ${x.circular?'<span class="tag" style="opacity:.6">circular</span>':''}${x.n_pequeno?'<span class="tag amber">n<10</span>':''}</div>
      <div class="muted" style="font-size:12.5px;margin:3px 0">${x.sancionados}/${x.n} marcados são sancionados (${(x.taxa*100).toFixed(1)}%)</div>
      ${barra(x.lift,x.circular)}</div>
      <div class="right"><div class="num" style="font-weight:800;font-size:22px;color:${x.circular?'var(--muted)':(x.lift>=2?'var(--rose)':(x.lift>=1?'var(--amber)':'var(--green)'))}">${x.lift}×</div><div class="dim">lift</div></div></div>`)).join('')+`</div>`;
  return h;
}

// ═══ SÓCIO OCULTO ═══
async function renderSocioOculto(){
  const d=await J('/api/intel/socio_oculto?limite=150');
  if(!d.ok)return sec('Sócio oculto')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Sócio oculto — um dono, vários fornecedores','Mesma pessoa (ou holding) sócia de <b>várias empresas</b> que vendem ao Estado. Um dono por trás de vários fornecedores permite simular concorrência entre empresas do mesmo grupo (fracionamento, propostas de cobertura) e concentrar contratos disfarçadamente.','🫥')+acoesAba('socio_oculto');
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Sócios com ≥3 empresas','var(--amber)','🕸️')}${kpi(fmtRc(a.reduce((s,x)=>s+x.total,0)),'Volume das empresas',null,'💰')}
      ${kpi(a.length?a[0].n_empresas:'—','Mais empresas (1 sócio)','var(--rose)')}${kpi(a.filter(x=>x.holding).length,'Holdings/PJ',null,'🏢')}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por sócio ou empresa…" oninput="filtrar(this,'#ocult-list .card')"></div>`;
  h+=`<div id="ocult-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0"><div style="font-weight:700">${esc(x.socio)} ${x.holding?'<span class="tag purple">holding/PJ</span>':''}</div>
      <div class="muted" style="font-size:12.5px;margin-top:3px">${esc((x.empresas||[]).slice(0,4).join(' · '))}${(x.empresas||[]).length>4?' …':''}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:var(--amber)">${x.n_empresas}</div><div class="dim">empresas · ${fmtRc(x.total)}</div></div></div>
      ${leitura(`<b>${esc(x.socio)}</b> é sócio de <b>${x.n_empresas}</b> empresas que receberam do Estado (${fmtRc(x.total)} somados). Um mesmo dono em vários fornecedores permite simular concorrência entre empresas do próprio grupo — cruzar se disputam os mesmos certames/órgãos.`)}`,
    x.n_empresas>=5?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

// ═══ NEPOTISMO ═══
async function renderNepotismo(){
  const d=await J('/api/intel/nepotismo?limite=150');
  if(!d.ok)return sec('Nepotismo')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Nepotismo — parentes em cargo de confiança','Duas ou mais pessoas de nomes distintos com o <b>mesmo sobrenome de família raro</b>, ambas em cargo de confiança no mesmo órgão. É o perfil de nepotismo — a <b>Súmula Vinculante 13 do STF</b> proíbe nomear parente para cargo em comissão. O fragmento de CPF confirma que são pessoas distintas.','👪')+acoesAba('nepotismo',`<a class="btn ghost" style="flex:0 0 auto;min-width:150px" href="/graph?fonte=familias" target="_blank">Grafo de famílias</a>`);
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Clusters familiares','var(--rose)','👪')}${kpi(fmtN(d.n_com_autoridade),'Com autoridade nomeante','var(--rose)','⚖️')}
      ${kpi(a.filter(x=>x.concentracao>=1).length,'100% do sobrenome','var(--amber)','🎯')}${kpi(a.length?a[0].n_membros:'—','Maior cluster')}</div>`;
  h+=`<div class="dim" style="margin-top:8px">Folhas cruzadas: ${esc((d.folhas||[]).join(', '))||'—'}. Cobertura cresce com novas folhas.</div>`;
  h+=`<div class="search" style="margin-top:12px"><span class="mag"></span><input placeholder="filtrar por sobrenome, órgão ou nome…" oninput="filtrar(this,'#nep-list .card')"></div>`;
  h+=`<div id="nep-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0"><div style="font-weight:700">${esc(x.sobrenome)} ${x.tem_autoridade?'<span class="tag rose">autoridade no cluster</span>':''}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">${esc((x.orgao||'').slice(0,44))}</div>
      <div class="dim" style="margin-top:2px">${Math.round(x.concentracao*100)}% das ${x.total_folha} pessoas desse sobrenome na folha</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:var(--rose)">${x.n_membros}</div><div class="dim">parentes?</div></div></div>
      <table style="margin-top:10px"><tbody>${(x.membros||[]).map(m=>`<tr><td>${esc(m.nome)}</td><td class="dim">${esc(m.cargo||'')}${m.cpf_frag?' · CPF …'+esc(m.cpf_frag):''}</td></tr>`).join('')}</tbody></table>
      ${leitura(`<b>${x.n_membros}</b> pessoas com o sobrenome <b>${esc(x.sobrenome)}</b> (${Math.round(x.concentracao*100)}% de todos com esse sobrenome na folha) ocupam cargo de confiança no mesmo órgão. Sobrenome raro concentrado em cargos comissionados é o perfil de nepotismo (SV13). ${x.membros.some(m=>m.cpf_frag)?'Fragmentos de CPF distintos confirmam pessoas diferentes.':''} Confirmar o parentesco e a cadeia de nomeação.`)}`,
    'hl')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}
// ═══ EMPRESA FÊNIX ═══
async function renderFenix(){
  const d=await J('/api/intel/fenix?limite=150');
  if(!d.ok)return sec('Fênix')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  // O texto de cada item pedia ao leitor "verificar se os pagamentos são posteriores à
  // baixa" — pergunta que o dado JÁ responde desde que a data da baixa entrou no detector.
  // E citava o total recebido de TODOS os tempos como se fosse o valor pago à empresa
  // morta: a IDESI aparecia com "R$ 508,1 mi", quando o que veio depois da baixa foi
  // R$ 1,33 mi. Agora afirma o que sabe e diz INDISPONÍVEL quando não sabe.
  const _fenixLeitura=x=>{
    const quem=`<b>${esc(x.nome)}</b> está <b>${esc(x.situacao)}</b> na Receita`;
    if(x.pagou_apos_baixa===true)
      return `${quem} desde <b>${esc(x.data_baixa)}</b> e ainda assim recebeu `
        +`<b>${fmtRc(x.valor_apos_baixa)}</b> em <b>${fmtN(x.n_ob_apos_baixa)} OB posteriores à baixa</b> `
        +`(de ${fmtRc(x.total_recebido)} no total). Pagamento a empresa baixada/inapta é irregular — indício forte.`;
    if(x.pagou_apos_baixa===false)
      return `${quem} desde <b>${esc(x.data_baixa)}</b>, mas <b>todos</b> os ${fmtRc(x.total_recebido)} `
        +`foram pagos <b>antes</b> da baixa — situação comum, <b>não é</b> pagamento a empresa morta. `
        +`Fica na lista como contexto do fornecedor, não como indício.`;
    return `${quem} e recebeu ${fmtRc(x.total_recebido)} do Estado. A <b>data da baixa</b> não está `
      +`na base da Receita local, então não dá para dizer se os pagamentos são posteriores — `
      +`<b>INDISPONÍVEL</b>, que não é o mesmo que regular.`;
  };
  let h=cover('geral','Empresa fênix — morta que recebe, ou nascida para faturar','Empresa <b>BAIXADA/INAPTA</b> na Receita que mesmo assim recebeu do Estado (pagamento a empresa morta), ou <b>aberta poucos meses antes</b> do primeiro pagamento (nasceu já para faturar — perfil de laranja).','🦅')+acoesAba('fenix');
  // o KPI vermelho é o CONFIRMADO (recebeu depois da baixa); "baixada hoje" fica neutro,
  // porque estar baixada hoje e ter recebido antes disso não é indício de nada.
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Empresas fênix','var(--rose)','🦅')}${kpi(fmtN(d.n_defunta_confirmada||0),'Recebeu DEPOIS da baixa',(d.n_defunta_confirmada?'var(--rose)':null),'💀')}
      ${kpi(fmtRc(d.total_apos_baixa||0),'Pago após a baixa',(d.total_apos_baixa?'var(--rose)':null),'💰')}${kpi(fmtN(d.n_defunta||0),'Baixada hoje (recebeu antes)',null,'🗓️')}</div>`;
  h+=`<div class="note" style="margin-top:8px">Só o pagamento <b>posterior à baixa</b> caracteriza "pagamento a empresa morta". Estar baixada hoje e ter recebido antes disso é situação comum e não é indício — por isso os dois números aparecem separados.</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por empresa…" oninput="filtrar(this,'#fenix-list .card')"></div>`;
  h+=`<div id="fenix-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">${clk(x.cnpj,x.nome||x.cnpj)}<div class="dim">${esc(x.cnpj)}</div>
      <div class="muted" style="font-size:12.5px;margin-top:3px">${x.tipo==='defunta'?`<span class="tag rose">${esc(x.situacao)}</span>`:'<span class="tag amber">recém-aberta</span>'} · aberta ${esc(x.data_abertura)} · 1ª OB ${esc(x.primeira_ob)}</div></div>
      <div class="right"><div class="num" style="font-weight:800">${fmtRc(x.total_recebido)}</div><div class="dim">recebido</div></div></div>
      ${leitura(x.tipo==='defunta'?_fenixLeitura(x):`<b>${esc(x.nome)}</b> foi aberta em ${esc(x.data_abertura)} e recebeu o 1º pagamento ${x.meses_ate_ob} meses depois. Empresa que nasce e já fatura com o Estado é perfil de laranja/fachada.`)}`,
    x.tipo==='defunta'?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

// ═══ PORTA GIRATÓRIA ═══
async function renderPortaGiratoria(){
  const d=await J('/api/intel/porta_giratoria?limite=150');
  if(!d.ok)return sec('Porta giratória')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Porta giratória — ex-servidor virou fornecedor','Ex-servidor público (vínculo inativo/exonerado/sem lotação nas folhas) que hoje é <b>sócio de empresa fornecedora do Estado</b>. Sair do serviço público e virar fornecedor pode violar a quarentena e indica captura do ex-órgão.','🚪')+acoesAba('porta_giratoria');
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Ex-servidores fornecedores','var(--rose)','🚪')}${kpi(fmtRc(a.reduce((s,x)=>s+(x.total_pago||0),0)),'Volume recebido',null,'💰')}
      ${kpi(fmtN(a.filter(x=>x.confianca==='ALTA').length),'Confiança ALTA (CPF)','var(--amber)','🔎')}${kpi(fmtN(d.homonimos_descartados),'Homônimos descartados',null,'🚮')}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por nome, empresa ou órgão…" oninput="filtrar(this,'#porta-list .card')"></div>`;
  h+=`<div id="porta-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0"><div style="font-weight:700">${esc(x.socio)}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">${esc(x.qualificacao)} de ${clk(x.cnpj,x.empresa)}</div>
      <div class="dim" style="margin-top:2px">ex: ${esc(x.ex_cargo||'—')} · ${esc((x.ex_orgao||'').slice(0,34))} <span class="tag amber">${esc(x.vinculo)}</span></div></div>
      <div class="right"><span class="tag ${x.confianca==='ALTA'?'rose':'accent'}">${esc(x.confianca)}</span><div class="num" style="margin-top:6px;font-weight:800">${fmtRc(x.total_pago)}</div></div></div>
      ${leitura(`<b>${esc(x.socio)}</b> consta na folha como ex-servidor (${esc(x.vinculo)}, ${esc(x.ex_orgao||'')}) e hoje é ${esc(x.qualificacao)} de <b>${esc(x.empresa)}</b>, que recebeu ${fmtRc(x.total_pago)} do Estado. Porta giratória — confirmar as datas de saída e do contrato (quarentena).`)}`,
    x.confianca==='ALTA'?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

// ═══ NEPOTISMO CRUZADO ═══
async function renderNepotismoCruzado(){
  const d=await J('/api/intel/nepotismo_cruzado?limite=80');
  if(!d.ok)return sec('Nepotismo cruzado')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Nepotismo cruzado — troca de favores entre órgãos','A família X manda no órgão A e coloca um parente no órgão B, enquanto a família Y manda no órgão B e coloca um parente no A. A <b>reciprocidade</b> dribla a Súmula Vinculante 13, que só proíbe nomear parente no PRÓPRIO órgão.','🔀')+acoesAba('nepotismo_cruzado');
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Pares recíprocos','var(--rose)','🔀')}</div>`;
  if(!a.length)return h+card('<div class="muted">Nenhum par recíproco com o padrão rigoroso nas folhas atuais. Cresce com mais folhas. 🟢</div>')+`<div class="note">${esc(d.ressalva||'')}</div>`;
  h+=`<div class="grid" style="margin-top:14px">`+a.map(x=>card(
    `<div style="font-weight:700">${esc(x.sobrenome_a)} ⇄ ${esc(x.sobrenome_b)}</div>
     <div class="kv" style="margin-top:8px"><span class="k">${esc((x.orgao_a||'').slice(0,30))}</span><b>autoridade: ${esc(x.autoridade_a)}</b></div>
     <div class="kv"><span class="k">${esc((x.orgao_b||'').slice(0,30))}</span><b>autoridade: ${esc(x.autoridade_b)}</b></div>
     ${leitura(`No órgão <b>${esc((x.orgao_a||'').slice(0,26))}</b> manda um <b>${esc(x.sobrenome_a)}</b> e há um <b>${esc(x.sobrenome_b)}</b> colocado; no <b>${esc((x.orgao_b||'').slice(0,26))}</b> é o inverso. Padrão de troca recíproca de parentes entre órgãos — confirmar parentesco e nomeações.`)}`,
    'hl')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

async function renderLaranjas(){
  const d=await J('/api/laranjas');if(!d.ok)return sec('Laranjas')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const it=d.itens||[];
  let h=cover('geral','Laranjas — sócio que recebe benefício','Sócio de empresa que recebe do Estado e ao mesmo tempo recebe benefício social de subsistência — indício de interposição (art. 337-F CP).','🎭');
  if(!it.length)return h+card('<div class="muted">Nenhum sócio-beneficiário confirmado. A resolução CPF×benefício é conservadora (evita homônimo). 🟢</div>')+`<div class="note">${esc(d.aviso||'')}</div>`;
  h+=`<div class="grid">`+it.map(x=>card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div><div style="font-weight:700">${esc(x.socio||'—')}</div><div class="dim">${esc(x.cpf||'')}</div></div><span class="tag rose">laranja?</span></div><div class="kv" style="margin-top:6px"><span class="k">Benefícios</span><b>${(x.beneficios||[]).map(esc).join(', ')||'—'}</b></div>${x.motivo?`<div class="muted" style="font-size:12.5px;margin-top:4px">${esc(x.motivo)}</div>`:''}`,'hl')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.aviso||'')}</div>`;return h;
}
async function renderCartel(){
  const c=await J('/api/cartel');const d=(c.dados||[]).slice(0,20);
  let h=cover('estado','Concentração & cartel · SIAFE','Órgãos onde um fornecedor concentra a maior fatia do valor pago (top share por UG). Complementa o conluio do PNCP com o lado do pagamento.','🔗');
  if(!d.length)return h+card('<div class="muted">Sem dados de concentração.</div>');
  const maxS=Math.max(1,...d.map(u=>u.top_share||0));
  h+=card(`<div class="barw">`+d.slice(0,10).map(u=>{const cor=u.top_share>=90?'var(--rose-d)':u.top_share>=70?'var(--amber-d)':null;
    return `<div><div class="row"><span class="lab">${esc((u.ug_nome||u.ug||'').slice(0,58))}</span><span class="num" style="font-weight:700;color:${cor?(u.top_share>=90?'var(--rose)':'var(--amber)'):'#fff'}">${u.top_share}%</span></div><div class="track"><span class="fill" style="width:${Math.max(4,(u.top_share/maxS)*100)}%${cor?`;background:${cor}`:''}"></span></div></div>`;}).join('')+`</div>`);
  h+=`<div style="height:14px"></div><div class="grid">`+d.map(u=>card(`<div style="display:flex;justify-content:space-between;gap:12px;align-items:center"><div style="min-width:0"><div style="font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(u.ug_nome||'')} <span class="dim">(${esc(u.ug||'')})</span></div><div class="muted" style="font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${u.n_fornecedores} fornec. · top: ${esc(u.top_fornecedor||'—')}</div></div><div class="right"><div style="font-weight:800;color:${u.top_share>=90?'var(--rose)':u.top_share>=70?'var(--amber)':'#fff'}">${u.top_share}%</div><div class="dim">${fmtRc(u.total)}</div></div></div>`)).join('')+`</div>`;
  return h;
}
// glossário: traduz os CÓDIGOS crípticos dos alertas p/ linguagem simples
const TIPO_ALERTA={
  pcrj_d7_fracionamento:['✂️','Fracionamento de despesa','Compras fatiadas em várias notas para caber abaixo do limite e não fazer licitação.'],
  pcrj_d10_rede_concorrentes:['🕸️','Rede de concorrentes','Empresas ligadas entre si (mesmo sócio/endereço) que disputam as mesmas licitações — concorrência de fachada.'],
  pcrj_d9_socio_na_folha:['🕴️','Sócio na folha','Sócio de empresa fornecedora que também é servidor público — conflito de interesse.'],
  fracionamento:['✂️','Fracionamento de despesa','Compras fatiadas para não licitar.'],
  sobrepreco:['📈','Sobrepreço','Preço muito acima da mediana de mercado.'],
};
const SEV_LEGENDA={
  alta:['🔴','Alta','Indício forte — priorize a verificação.'],
  media:['🟡','Média','Merece checagem, mas o sinal é mais fraco ou depende de confirmação documental.'],
  baixa:['⚪','Baixa','Sinal fraco / informativo.'],
};
async function renderAlertas(){
  const p=await J('/api/compliance/painel');const lst=p.lista_alertas||[];
  if(!lst.length)return sec('Auditoria')+card('<div class="muted">Sem alertas no momento. 🟢</div>');
  // legenda da escala (o que 🔴/🟡 significam) — resolve "não entendo o amarelo"
  let h=cover('estado','Alertas de auditoria','Sinais automáticos de irregularidade nas contas. A <b>cor</b> indica a força do indício, não uma acusação.','🚨');
  h+=card(`<div style="font-weight:700;margin-bottom:8px">Como ler as cores</div>`+
    Object.values(SEV_LEGENDA).map(([ic,nome,desc])=>`<div class="kv"><span class="k" style="min-width:110px"><span class="sev ${nome.toLowerCase()==='alta'?'alta':nome.toLowerCase()==='média'?'media':'baixa'}">${ic} ${nome}</span></span><b style="font-weight:500;color:var(--tx2);text-align:right">${desc}</b></div>`).join(''));
  // agrupa por TIPO, com contagem e explicação em português
  const porTipo={};lst.forEach(a=>{(porTipo[a.tipo]=porTipo[a.tipo]||[]).push(a);});
  h+=`<div style="height:14px"></div>`+sec('Alertas por tipo',lst.length);
  h+=`<div class="grid">`+Object.entries(porTipo).map(([tipo,alertas])=>{
    const[ic,nome,desc]=TIPO_ALERTA[tipo]||['🚩',tipo,''];
    const nAlta=alertas.filter(a=>a.severidade==='alta').length,nMed=alertas.length-nAlta;
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:700">${ic} ${esc(nome)}</div><div class="muted" style="font-size:12.5px;margin-top:3px">${esc(desc)}</div></div>
      <div class="right">${nAlta?`<span class="sev alta">${nAlta} 🔴</span> `:''}${nMed?`<span class="sev media">${nMed} 🟡</span>`:''}</div></div>
      <div class="exp" onclick="toggle(this)" style="margin-top:8px"><div class="dim"><span class="chev">▸</span> ver os ${alertas.length} casos</div>
      <div class="objs">${alertas.slice(0,40).map(a=>`<div class="obj">${a.severidade==='alta'?'🔴':'🟡'} <b>${esc((a.titulo||'').replace(/^[^—]*—\\s*/,''))}</b>${a.descricao?` — <span class="muted">${esc(a.descricao)}</span>`:''}</div>`).join('')}</div></div>`);
  }).join('')+`</div>`;
  h+=`<div class="note">Indício para apuração interna — não é acusação. 🔴 = sinal forte; 🟡 = merece checagem.</div>`;
  return h;
}
async function renderSiafe(){
  const s=await J('/api/siafe/stats');if(!s.ok)return sec('SIAFE')+card('<div class="muted">SIAFE indisponível.</div>');
  const linhas=(s.por_ano||[]).filter(x=>x.valor>0).map(x=>`<tr><td>${x.exercicio}</td><td>${fmtN(x.n)}</td><td>${fmtR(x.valor)}</td></tr>`).join('');
  let h=sec('SIAFE · ordens bancárias')+`<div class="grid g2">${kpi(fmtN(s.total),'OBs ingeridas')}${kpi(fmtRc(s.valor_total),'Valor total')}</div><div style="height:12px"></div>`+card(`<table><thead><tr><th>Exercício</th><th>OBs</th><th>Valor</th></tr></thead><tbody>${linhas||'<tr><td colspan=3 class="muted">sem dados</td></tr>'}</tbody></table>`);
  h+=`<div style="height:16px"></div>`+await frescorHtml();
  return h;
}
async function renderSweeps(){
  // Cockpit do SISTEMA (pedido do dono 2026-07-26): sweeps, fila SEI com barra,
  // arquivo compacto, pipelines e aprendizados — vivo, atualizando em 30s.
  const [d,a]=await Promise.all([J('/api/sweeps/status'),J('/api/sistema/atividade')]);
  const sei=a.sei||{},apr=a.aprendizados||{};
  const gb=v=>v==null?'—':(v/1e9).toFixed(2)+' GB';
  const idade=st=>st==null?'—':(st<90?'agora':(st<5400?Math.round(st/60)+' min atrás':Math.round(st/3600)+' h atrás'));
  const aprTotal=(apr.memoria_db||0)+(apr.fichas_sei||0)+(apr.direcionamentos||0)+(apr.vault_notas||0);
  let h=cover('geral','Sistema — a atividade de toda a máquina',
    'O que está coletando agora, quanto da fila SEI já virou <b>arquivo compacto</b>, o estado de cada pipeline e quantos <b>aprendizados</b> a leitura já produziu. Atualiza sozinho a cada 30s.','🛰️');
  h+=`<div class="grid g2" id="sis-live">
    ${kpi(sei.pct_lido==null?'—':sei.pct_lido+'%','Fila SEI já lida',null,'📄')}
    ${kpi(fmtN(sei.arquivados),'Processos no arquivo compacto')}
    ${kpi(gb(sei.arquivo_bytes),'Espaço do arquivo (texto+fases+fotos)')}
    ${kpi(fmtN(aprTotal),'Aprendizados acumulados','var(--accent)','🧠')}</div>`;
  const falta=(sei.fila_total!=null&&sei.arquivados!=null)?sei.fila_total-sei.arquivados:null;
  h+=card(`<div class="kv"><span class="k">Fila SEI por dinheiro — lidos × restantes</span><b><span class="num" id="sis-lidos">${fmtN(sei.arquivados)}</span> de ${fmtN(sei.fila_total)}${falta!=null?` · faltam <span class="num" id="sis-falta">${fmtN(falta)}</span>`:''}</b></div>
    <div class="sisbar bar" title="${sei.pct_lido==null?'fila total indisponível':sei.pct_lido+'% lido'}"><i id="sis-barra" style="width:${sei.pct_lido==null?0:Math.max(1.2,sei.pct_lido)}%"></i></div>
    ${sei.pct_lido==null?leitura('Total da fila <b>INDISPONÍVEL</b> agora (não é zero) — a barra volta quando o compliance.db responder.'):''}`);
  h+=`<div style="height:14px"></div>`+sec('Sweeps de coleta',(a.sweeps||[]).length);
  h+=card((a.sweeps||[]).map(s0=>{
    const on=s0.vivo,sup=s0.supervisor;
    const est=a.pausado?'pausado':(on?'rodando':(sup?'supervisionado (aguardando janela)':'parado'));
    const cor=a.pausado?'var(--amber)':(on?'var(--green)':(sup?'var(--accent)':'var(--rose)'));
    return `<div class="kv"><span class="k"><span class="sinal" style="background:${cor};box-shadow:0 0 8px ${cor}"></span> ${esc(s0.nome)}</span><b>${est} · <span class="num">${idade(s0.atividade_s)}</span></b></div>`;}).join('')
    +`<div class="btns" style="margin-top:10px"><button class="btn red" onclick="sweep('pausar')">⏸ Pausar</button><button class="btn green" onclick="sweep('retomar')">▶ Retomar</button><button class="btn ghost" onclick="ir(aba)">↻ Atualizar</button></div>`);
  if((a.pipelines||[]).length){
    h+=`<div style="height:14px"></div>`+sec('Pipelines (SLO)',a.pipelines.length);
    h+=card(`<div style="display:flex;flex-wrap:wrap;gap:8px">`+a.pipelines.map(p0=>{
      const ok=String(p0.estado).toLowerCase().startsWith('ok');
      return `<span class="tag ${ok?'green':'amber'}" title="${esc(p0.estado)}"><span class="sinal" style="background:${ok?'var(--green)':'var(--amber)'}"></span>${esc(p0.nome)}</span>`;}).join('')+`</div>`);}
  h+=`<div style="height:14px"></div>`+sec('Aprendizados — o que a leitura já produziu');
  h+=card(`<div class="kv"><span class="k">Fichas SEI montadas</span><b class="num">${fmtN(apr.fichas_sei)}</b></div>
    <div class="kv"><span class="k">Análises de direcionamento</span><b class="num">${fmtN(apr.direcionamentos)}</b></div>
    <div class="kv"><span class="k">Árvores de processo capturadas</span><b class="num">${fmtN(apr.arvores_sei)}</b></div>
    <div class="kv"><span class="k">Memória de aprendizado (DB)</span><b class="num">${fmtN(apr.memoria_db)}</b></div>
    <div class="kv"><span class="k">Notas de aprendizado no vault</span><b class="num">${fmtN(apr.vault_notas)}</b></div>`);
  h+=(d.sei?.ultima?`<div style="height:12px"></div><pre>${esc((d.sei.ultima||'').replace(/\*\*/g,''))}</pre>`:'');
  h+=`<div style="height:16px"></div>`+await frescorHtml();
  clearInterval(window._sisTick);
  window._sisTick=setInterval(async()=>{
    if(aba!=='g_sweeps'||!document.getElementById('sis-live')){clearInterval(window._sisTick);return;}
    try{const n=await J('/api/sistema/atividade');const ns=n.sei||{};
      const up=(id,v)=>{const e=document.getElementById(id);if(e&&v!=null&&e.textContent!==String(v))e.textContent=v;};
      up('sis-lidos',fmtN(ns.arquivados));
      if(ns.fila_total!=null&&ns.arquivados!=null)up('sis-falta',fmtN(ns.fila_total-ns.arquivados));
      const b=document.getElementById('sis-barra');
      if(b&&ns.pct_lido!=null)b.style.width=Math.max(1.2,ns.pct_lido)+'%';
    }catch(e){}
  },30000);
  return h;
}
async function sweep(a){if(a==='pausar'&&!await jfnConfirm('Pausar <b>todos</b> os sweeps de coleta? O painel continua no ar — só a alimentação de dados novos para até você retomar.','⏸ Pausar tudo'))return;await J('/api/sweeps/'+a,{method:'POST'});jfnToast(a==='pausar'?'Sweeps pausados.':'Sweeps retomados.','green');setTimeout(()=>ir(aba),500);}
let _valLista=[],_valIdx=0;
async function renderValidar(){
  const d=await J('/api/fachada/revisar?limite=200');_valLista=(d&&d.fachadas)||[];_valIdx=0;
  return cover('geral','Validador de fachada','Fachadas flagradas p/ revisão humana. Veja o Street View, decida, e a base atualiza.','🏢')+`<div id="val-card">${_valCard()}</div>`;
}
function _valCard(){
  if(_valIdx>=_valLista.length)return card('<div class="muted">Tudo revisado nesta sessão. Recarregue p/ mais.</div>');
  const f=_valLista[_valIdx];
  const maps=(f.geo_lat&&f.geo_lon)?`https://www.google.com/maps/@${f.geo_lat},${f.geo_lon},19z`:`https://www.google.com/maps/search/${encodeURIComponent((f.endereco||'')+', '+(f.municipio||''))}`;
  const sv=(f.geo_lat&&f.geo_lon)?`https://www.google.com/maps?layer=c&cbll=${f.geo_lat},${f.geo_lon}`:maps;
  const motivo=f.nivel==='SEM_GOOGLE'?'Sem marcação no Google':f.nivel==='FECHADO_GOOGLE'?'Fechado no Google':'Revisar fachada';
  return card(`<div class="dim">${_valIdx+1} de ${_valLista.length}</div><div style="font-weight:700;font-size:16px;margin:4px 0">${esc(f.razao||f.cnpj)}</div>
     <div class="kv"><span class="k">Motivo</span><b style="color:var(--rose)">${esc(motivo)}</b></div><div class="kv"><span class="k">Recebido do Estado</span><b>${fmtR(f.total_recebido)}</b></div>
     <div class="kv"><span class="k">Endereço</span><b class="right" style="max-width:60%">${esc(f.endereco||'—')}, ${esc(f.municipio||'')}/${esc(f.uf||'')}</b></div><div class="kv"><span class="k">CNPJ</span><b>${esc(f.cnpj)}</b></div>
     <div class="btns"><a class="btn ghost" href="${sv}" target="_blank">Street View</a><a class="btn ghost" href="${maps}" target="_blank">Maps</a></div>
     <input id="val-nota" placeholder="nota p/ o Claude (opcional)" style="margin-top:10px">
     <div class="btns" style="margin-top:8px"><button class="btn red" onclick="validar('suspeito')">Suspeito</button><button class="btn green" onclick="validar('ok')">Legítima</button><button class="btn ghost" onclick="validar('mais_info')">Mais info</button></div>`);
}
async function validar(v){const f=_valLista[_valIdx];if(!f)return;const nota=($('val-nota')||{}).value||'';
  await J('/api/fachada/veredito',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cnpj:f.cnpj,veredito:v,nota})});
  _valIdx++;const el=$('val-card');if(el)el.innerHTML=_valCard();}
async function renderAcoes(){
  const reps=await J('/api/compliance/reports');const pdfs=((reps&&reps.length?reps:[])||[]).filter(x=>x.type==='pdf').slice(0,12);
  const repsHtml=pdfs.length?`<div class="lnks">`+pdfs.map(f=>`<a class="lnk" href="${f.url}" target="_blank"><span class="ic"></span><div><div class="t">${esc(f.name)}</div></div><span class="ar">→</span></a>`).join('')+`</div>`:card('<div class="muted">Nenhum relatório gerado ainda — peça um pelo botão "Gerar PDF" de qualquer aba, ou pelo /relatorio no Telegram; ele aparece aqui na hora.</div>');
  return cover('geral','Gerar relatórios & atalhos','Relatório de fornecedor/órgão com Lex forense, dossiê 360, cruzamento e painéis.','☑️')+
    card(`<label class="fld">Relatório de fornecedor (+ Lex forense)</label><div style="display:flex;gap:8px"><input id="ac-emp" placeholder="nome ou CNPJ"><button class="btn accent" style="flex:0 0 auto;min-width:82px" onclick="acao('relatorio')">Gerar</button></div>
      <div style="height:11px"></div><label class="fld">Relatório de órgão (+ Lex)</label><div style="display:flex;gap:8px"><input id="ac-org" placeholder="órgão ou UG (ex: 133100)"><button class="btn accent" style="flex:0 0 auto;min-width:82px" onclick="acao('orgao')">Gerar</button></div>
      <div style="height:11px"></div><label class="fld">Dossiê 360</label><div style="display:flex;gap:8px"><input id="ac-dos" placeholder="nome ou CNPJ do alvo"><button class="btn accent" style="flex:0 0 auto;min-width:82px" onclick="acao('dossie')">Gerar</button></div>
      <pre id="ac-out" style="margin-top:13px;display:none"></pre>`)+
    `<div style="height:18px"></div>`+sec('Relatórios gerados')+repsHtml+
    `<div style="height:18px"></div>`+sec('Painéis')+`<div class="lnks">
      <a class="lnk" href="/auditoria"><span class="ic"></span><div><div class="t">Painel de Auditoria</div><div class="d">KPIs clássicos</div></div><span class="ar">→</span></a>
      <a class="lnk" href="/graph"><span class="ic"></span><div><div class="t">Grafo de fraude</div><div class="d">relações entre entes</div></div><span class="ar">→</span></a>
      <a class="lnk" href="/graph?fonte=familias" target="_blank"><span class="ic"></span><div><div class="t">Grafo de famílias</div><div class="d">clãs em cargos + suas empresas</div></div><span class="ar">→</span></a>
      <a class="lnk" href="/hermes"><span class="ic"></span><div><div class="t">Yoda / Hermes</div><div class="d">chat e relatórios</div></div><span class="ar">→</span></a></div>`;
}
async function acao(tipo){
  const out=$('ac-out');out.style.display='block';let url,body,val;
  if(tipo==='relatorio'){val=$('ac-emp').value.trim();if(!val)return;url='/api/relatorio/inteligencia';body={empresa:val};}
  if(tipo==='orgao'){val=$('ac-org').value.trim();if(!val)return;url='/api/relatorio/orgao';body={orgao:val};}
  if(tipo==='dossie'){val=$('ac-dos').value.trim();if(!val)return;url='/api/dossie';body={alvo:val};}
  out.textContent=`processando "${val}"… (até ~1 min)`;const t0=Date.now()/1000;
  const antes=new Set(((await J('/api/compliance/reports'))||[]).filter(x=>x.type==='pdf').map(x=>x.name));
  const d=await J(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(d.erro){out.textContent='⚠ erro: '+d.erro;return;}
  if(d.ambiguo){out.textContent=`❓ ambíguo: ${d.pergunta}\ncandidatos: ${(d.candidatos||[]).map(c=>c.nome||c).join(' · ')}`;return;}
  if(d.status==='gerando'||(d.msg&&d.path_pdf==null&&d.resumo==null)){out.textContent=(d.msg||'⏳ Gerando…').replace(/\*/g,'');return pollarPdf(out,val,t0,antes);}
  const pdf=d.path_pdf||d.path_lex||d.path_xlsx;
  const linha=[d.empresa||d.orgao||val,d.risco?('risco '+d.risco):'',d.grau_lex?('Lex '+d.grau_lex):'',d.score!=null?('score '+d.score):''].filter(Boolean).join(' · ');
  out.innerHTML=`✅ ${esc(linha)}\n${esc((d.resumo||'').slice(0,500))}`+(pdf?`\n\n📄 <a href="/${pdf.replace(/^\//,'')}" target="_blank" style="color:var(--accent)">abrir PDF</a>`:'');
}
async function pollarPdf(out,termo,t0,antes){
  const slug=(termo||'').toLowerCase().replace(/[^a-z0-9]+/g,'_').slice(0,12);
  for(let i=0;i<36;i++){await new Promise(r=>setTimeout(r,5000));
    const pdfs=((await J('/api/compliance/reports'))||[]).filter(x=>x.type==='pdf');
    let novos=pdfs.filter(x=>x.mtime&&x.mtime>t0);if(!novos.length)novos=pdfs.filter(x=>!antes.has(x.name));
    const alvo=novos.find(x=>slug&&x.name.toLowerCase().includes(slug))||novos[0];
    if(alvo){sessaoReports.add(alvo.name);out.innerHTML='✅ pronto: '+esc(alvo.name)+`\n\n📄 <a href="${alvo.url}" target="_blank" style="color:var(--accent)">abrir PDF</a> (apaga ao sair)`;return;}}
  out.textContent='⏳ Ainda gerando — confira no Telegram ou em Relatórios.';
}
function limparEfemeros(){if(!sessaoReports.size)return;const body=JSON.stringify({nomes:[...sessaoReports]});
  try{navigator.sendBeacon('/api/compliance/reports/limpar',new Blob([body],{type:'application/json'}));}
  catch(e){fetch('/api/compliance/reports/limpar',{method:'POST',headers:{'Content-Type':'application/json'},body,keepalive:true});}}
window.addEventListener('pagehide',limparEfemeros);window.addEventListener('beforeunload',limparEfemeros);

// ═══ COCKPIT (aba Início) — command deck ao vivo ═══
let _ckMX=.5,_ckMY=.5,_ckTimer=null;
addEventListener('pointermove',e=>{_ckMX=e.clientX/innerWidth;_ckMY=e.clientY/innerHeight;},{passive:true});
/* ── TERRITÓRIO GLOBAL — o Estado do RJ atrás de toda aba ──────────────────
   Desenha a malha REAL do IBGE num offscreen (1× por tamanho/cor), tingida pela
   cor da esfera ativa, e no RAF passa só uma varredura de radar + respiração
   (barato). Pausa em document.hidden e reduced-motion. O território re-tinge
   quando a esfera muda (rjbgTinge). O dado sempre lê primeiro: opacity baixa. */
let _rjbgTinge=()=>{};
function rjbgStart(){
  const cv=$('rjbg');if(!cv)return;
  const rm=matchMedia('(prefers-reduced-motion:reduce)').matches;
  const ctx=cv.getContext('2d');
  let W,H,dpr,mapC=null,raf=0,corAtual='';
  const corEsf=()=>getComputedStyle(document.body).getPropertyValue('--esf').trim()||'oklch(0.72 0.175 258)';
  function build(){
    const M=window.RJ_MALHA;if(!M)return;
    const cor=corEsf();corAtual=cor;
    mapC=document.createElement('canvas');mapC.width=cv.width;mapC.height=cv.height;
    const x=mapC.getContext('2d');x.scale(dpr,dpr);
    // território grande, empurrado à direita: "mapa na parede da sala de comando"
    const s=Math.min(W/M.w,H/M.h)*1.04;
    const ox=W-M.w*s*0.66, oy=(H-M.h*s)/2;
    const mk=flat=>{const p=new Path2D();let X=flat[0],Y=flat[1];
      p.moveTo(ox+X/M.q*s,oy+Y/M.q*s);
      for(let i=2;i<flat.length;i+=2){X+=flat[i];Y+=flat[i+1];p.lineTo(ox+X/M.q*s,oy+Y/M.q*s);}
      p.closePath();return p;};
    x.lineJoin=x.lineCap='round';
    // divisas: teia fria na cor da esfera
    x.strokeStyle=`color-mix(in oklch, ${cor} 34%, transparent)`;x.lineWidth=0.6;
    M.m.forEach(f=>x.stroke(mk(f)));
    // contorno: a fronteira sob vigília, com halo
    x.shadowColor=cor;x.shadowBlur=12;
    x.strokeStyle=`color-mix(in oklch, ${cor} 78%, white 12%)`;x.lineWidth=1.5;
    M.o.forEach(f=>x.stroke(mk(f)));
    cv._ox=ox;cv._oy=oy;cv._s=s;cv._M=M;
  }
  function size(){
    dpr=Math.min(1.5,devicePixelRatio||1);W=innerWidth;H=innerHeight;
    cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);
    cv.style.width=W+'px';cv.style.height=H+'px';
    build();
  }
  function draw(t){
    if(!mapC){raf=requestAnimationFrame(draw);return;}
    if(document.hidden){raf=requestAnimationFrame(draw);return;}
    const g=ctx;g.setTransform(1,0,0,1,0,0);g.clearRect(0,0,cv.width,cv.height);
    g.drawImage(mapC,0,0);
    // respiração + varredura de radar girando a partir do centro do território
    if(!rm){
      g.setTransform(dpr,0,0,dpr,0,0);
      const M=cv._M,s=cv._s;
      const cx=cv._ox+M.w*s*0.42/1, cy=cv._oy+M.h*s*0.5;
      const ang=t*0.00016, R=Math.hypot(W,H);
      const grad=g.createConicGradient?g.createConicGradient(ang,cx,cy):null;
      if(grad){grad.addColorStop(0,`color-mix(in oklch, ${corAtual} 22%, transparent)`);
        grad.addColorStop(0.06,'transparent');grad.addColorStop(1,'transparent');
        g.globalCompositeOperation='source-atop';g.fillStyle=grad;
        g.beginPath();g.arc(cx,cy,R,0,6.283);g.fill();
        g.globalCompositeOperation='source-over';}
      g.setTransform(1,0,0,1,0,0);
    }
    raf=requestAnimationFrame(draw);
  }
  _rjbgTinge=()=>{if(!window.RJ_MALHA)return;if(corEsf()!==corAtual)build();};
  size();
  addEventListener('resize',()=>{cancelAnimationFrame(raf);size();draw(performance.now());},{passive:true});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){cancelAnimationFrame(raf);draw(performance.now());}});
  _rjCarregar(()=>{build();});
  draw(performance.now());
}
function netbgStart(){
  const cv=$('netbg');if(!cv)return;const ctx=cv.getContext('2d');let W,H,pts,raf;
  const rm=matchMedia('(prefers-reduced-motion:reduce)').matches;
  function size(){const d=Math.min(2,devicePixelRatio);W=cv.width=innerWidth*d;H=cv.height=innerHeight*d;
    cv.style.width=innerWidth+'px';cv.style.height=innerHeight+'px';cv._d=d;
    const n=Math.min(76,Math.floor(innerWidth/20));
    pts=Array.from({length:n},()=>({x:Math.random()*W,y:Math.random()*H,z:Math.random()*.8+.2,
      vx:(Math.random()-.5)*.11*d,vy:(Math.random()-.5)*.11*d,r:(Math.random()*1.5+.6)*d}));}
  function draw(){const d=cv._d,D=150*d;ctx.clearRect(0,0,W,H);const px=(_ckMX-.5)*26*d,py=(_ckMY-.5)*26*d;
    for(let i=0;i<pts.length;i++){const p=pts[i];if(!rm){p.x+=p.vx;p.y+=p.vy;if(p.x<0||p.x>W)p.vx*=-1;if(p.y<0||p.y>H)p.vy*=-1;}
      const ox=p.x+px*p.z,oy=p.y+py*p.z;p._ox=ox;p._oy=oy;
      for(let j=i+1;j<pts.length;j++){const q=pts[j],qx=q.x+px*q.z,qy=q.y+py*q.z,dx=ox-qx,dy=oy-qy,dd=Math.hypot(dx,dy);
        if(dd<D){ctx.strokeStyle='rgba(90,210,255,'+((1-dd/D)*.24)+')';ctx.lineWidth=d*.55;ctx.beginPath();ctx.moveTo(ox,oy);ctx.lineTo(qx,qy);ctx.stroke();}}
      ctx.beginPath();ctx.arc(ox,oy,p.r,0,7);ctx.fillStyle='rgba(140,228,255,'+(.38+p.z*.4)+')';ctx.fill();}
    if(!rm)raf=requestAnimationFrame(draw);}
  addEventListener('resize',()=>{cancelAnimationFrame(raf);size();draw();});
  document.addEventListener('visibilitychange',()=>{cancelAnimationFrame(raf);if(!document.hidden)draw();});
  size();draw();
}
/* v10: _ckSpark/_ckSynth removidos — gerador de série sintética (Math.random) sem caller,
   proibido pelo PRODUCT.md ("dado sintético = proibido"). Sparkline real, quando vier, nasce de série da API. */
function _ckCount(el,to,fmt,ms=1000){if(!el)return;const rm=matchMedia('(prefers-reduced-motion:reduce)').matches;if(rm||to==null){el.textContent=fmt(to);return;}
  const t0=performance.now();(function s(t){const p=Math.min(1,(t-t0)/ms),e=1-Math.pow(1-p,3);el.textContent=fmt(to*e);if(p<1)requestAnimationFrame(s);else el.textContent=fmt(to);})(performance.now());}
const _CK={teal:'#5fd9ff',gold:'#eec276',good:'#5fe0a1',amber:'#f2b544',rose:'#ff7a8a'};

/* ══ v49 · UM BOTÃO POR FUNÇÃO MESTRA (pedido do dono) ══════════════════════════════════════════
   A lista vem de `CAPS_MESTRAS` (static/js/caps.js), GERADA de capabilities.yaml pelo
   tools/gerar_superficie_caps.py. Escrever os botões aqui à mão criaria a quinta cópia da mesma
   lista — e a casa já tem cicatriz de lista duplicada divergindo em silêncio.

   As rotas aparecem como string literal no arquivo gerado de propósito: é assim que as duas
   catracas de rota (órfãs, teto 0; e sem-superfície) enxergam que a capacidade tem porta de
   entrada. Fosse `fetch('/api/lista')` em runtime, elas acusariam órfãs que não são órfãs. */
function blocoComandosMestres(){
  if(typeof CAPS_MESTRAS==='undefined'||!CAPS_MESTRAS.length)return '';
  const grupos={};
  for(const c of CAPS_MESTRAS)(grupos[c.grupo]=grupos[c.grupo]||[]).push(c);
  let h=`<div class="ck-caps"><div class="ck-eye">Funções mestras — ${CAPS_MESTRAS.length} comandos, um clique cada</div>`;
  for(const g of Object.keys(grupos)){
    h+=`<div class="caps-g"><div class="caps-gt">${esc(g)}</div><div class="btns" style="flex-wrap:wrap">`;
    for(const c of grupos[g]){
      const dica=esc(`${c.descricao||c.nome}${c.exemplo?'\n\nex.: '+c.exemplo:''}${c.rota?'\n\n'+c.metodo+' '+c.rota:''}`);
      h+=`<button type="button" class="btn ghost" title="${dica}" onclick="abrirCapMestra('${esc(c.id)}')">`
        +`${esc(c.nome)}${c.cmd?`<span class="caps-cmd">${esc(c.cmd)}</span>`:''}</button>`;
    }
    h+=`</div></div>`;
  }
  h+=`<div class="note">Cada botão é uma capacidade com <b>status PRONTO</b> em <code>capabilities.yaml</code>.
      O mesmo <code>cmd</code> serve o Telegram e o painel — uma fonte, várias superfícies.</div></div>`;
  return h;
}

/* O clique abre a ficha da capacidade com a rota, o método e um exemplo. NÃO dispara sozinho:
   várias destas geram peça pesada (PDF, planilha) ou escrevem no banco, e disparo acidental num
   painel de auditoria é caro — o botão leva ao comando, quem decide é a pessoa. */
function abrirCapMestra(id){
  const c=(typeof CAPS_MESTRAS!=='undefined'?CAPS_MESTRAS:[]).find(x=>x.id===id);
  if(!c)return;
  const linha=(r,v)=>`<div style="display:flex;gap:10px;margin:6px 0"><b style="min-width:104px">${r}</b><span>${v}</span></div>`;
  const ov=$('ov'),sh=$('sheet');ov.classList.add('on');
  sh.innerHTML=`<span class="x" onclick="fecharDossie()">✕ fechar</span><div class="grab"></div>
    <div style="font-weight:800;font-size:17px;margin-bottom:4px">${esc(c.nome)}</div>
    <div class="muted" style="font-size:13px;margin-bottom:14px">${esc(c.grupo)}</div>`
    +card((c.descricao?`<p style="margin:0 0 10px">${esc(c.descricao)}</p>`:'')
      +(c.rota?linha('Rota',`<code>${esc(c.metodo)} ${esc(c.rota)}</code>`):'')
      +(c.cmd?linha('No Telegram',`<code>${esc(c.cmd)}</code>`):'')
      +(c.exemplo?linha('Exemplo',`<code>${esc(c.exemplo)}</code>`):''))
    +`<div class="note">Nada foi disparado. Vários destes comandos geram peça pesada (PDF, planilha)
      ou escrevem no banco — o painel mostra o caminho, o disparo é decisão sua.</div>`;
}

async function renderCockpit(){
  const html=`<div class="ck">
    <div class="ck-ticker"><div class="lane" id="ck-lane"><span>◉ sincronizando o barramento — os primeiros sinais chegam em segundos…</span></div></div>
    <div class="ck-hero">
      <div class="ck-lead"><div class="ck-eye">Economia potencial identificada</div>
      <div class="ck-big" id="ck-econ">R$ ——</div>
      <div class="ck-sub" id="ck-sub">Quanto os cofres públicos deixariam de gastar se cada compra acima da mediana tivesse pago a <b>mediana de mercado</b> do item.</div></div>
      <div class="ck-ved" id="ck-vedbox" hidden><span class="n" id="ck-ved">R$ —</span>
        <span class="l">pago <b style="color:var(--rose)">acima do mercado a fornecedor juridicamente vedado</b> (inidôneo), à época — o alvo mais forte.</span></div>
    </div>
    <div class="ck-nucleo" id="ck-nucleo"><canvas id="nucleo-cv" aria-hidden="true"></canvas>
      <div class="nu-legend">Mesa de vigília · cada feixe = um domínio · onda no piso = evento real</div>
      <div class="nu-hud" id="nu-hud" aria-live="polite">vigília armada — aguardando o primeiro evento do barramento</div>
      <div class="nu-sweep" id="nu-sweep" aria-live="polite"></div>
      <div id="nu-chips"></div></div>
    <div class="ck-grid" id="ck-grid"></div>
    ${blocoComandosMestres()}
    <div class="ck-fontes" id="ck-fontes"></div></div>`;
  /* v48: quem monta o cockpit e o ir(), DEPOIS de pintar — nao um timer daqui.
     O v44 reagendava ate achar o ck-grid, mas o grid que ele achava era o do
     quadro ANTERIOR: o innerHTML final entrava depois e jogava fora o que
     havia sido montado (canvas voltava a 300x150, os 7 nos do mapa sumiam).
     Timer nao serializa com paint assincrono; chamada apos o paint, sim. */
  return html;
}

// ═══ NÚCLEO ORGÂNICO — a mesma informação do cockpit em forma viva (dados/eventos REAIS) ═══
const NU_NODES=[
  {id:'radar',  lab:'radar de risco', tab:'g_radar', cor:'#5fd9ff', orb:.9,  sp:1},
  {id:'alertas',lab:'alertas',        tab:'e_alertas',cor:'#ff7a8a', orb:.66, sp:-.7},
  // "ninhos" agora é a MESMA SALA, não o mesmo prédio: dividir 'Rua da Assembleia 10'
  // (318 CNPJs, edifício comercial) não diz nada; dividir a SALA com 2+ recebendo é a
  // assinatura de interposição. Rótulo mudou junto — o número é outro e menor, de propósito.
  {id:'ninho',  lab:'mesma sala',     tab:'g_riscos', cor:'#f2b544', orb:.88, sp:.8},
  {id:'fenix',  lab:'empresa morta',  tab:'g_fenix',  cor:'#ff9a6a', orb:.6,  sp:1.15},
  {id:'com',    lab:'comunidades',    tab:'g_comun',  cor:'#c096ff', orb:.92, sp:-.55},
  {id:'compras',lab:'compras auditáveis',tab:'e_comp',cor:'#eec276', orb:.68, sp:.9},
  {id:'dossie', lab:'caro + suspeito',tab:'e_comp',   cor:'#ff7ab8', orb:.86, sp:-.95},
];
let _nuRAF=0,_nuPulses=[],_nuVals={},_nuFlux=[],_sweepAtivo=null,_swInt=0;
/* v23 CARCACA REAL — a arte do reator vem do gerador (Firefly Image 5), nao do
   codigo. Ela entra como TEXTURA por baixo do instrumento vivo: a peca usinada,
   o god-ray e o flare sao fotografia; os aneis, bobinas e o triangulo continuam
   procedurais por cima, porque so eles sabem a carga real da VM. Composicao
   aditiva ('lighter'): os cantos pretos da arte somam zero, entao nao ha caixa. */
const _reatorArt=new Image();_reatorArt.src='/static/assets/reator-core.webp';
// qual sweep alimenta o sistema agora → mostra no reator e o acelera
async function nuSweepPoll(){
  const el=$('nu-sweep');if(!el)return;
  const d=await J('/api/sweeps/status');
  const seiRun=d&&d.sei&&d.sei.rodando, siafeRun=d&&d.siafe&&d.siafe.rodando;
  if(!d||d.erro||d.pausado||!(seiRun||siafeRun)){_sweepAtivo=null;el.classList.remove('on');el.innerHTML='';return;}
  _sweepAtivo={sei:!!seiRun,siafe:!!siafeRun};
  let det='';
  if(seiRun&&d.sei.ultima){const m=String(d.sei.ultima).match(/UG\s*(\d+)/);if(m)det=` · UG ${m[1]}`;}
  const nome=seiRun?'SEI · itkava':'SIAFE 2';
  const cnt=seiRun?`<small>${fmtN(d.sei.feitos)} lidos</small>`:`<small>${fmtN(d.siafe.ob_orcamentaria)} OBs</small>`;
  el.innerHTML=`<span class="dot"></span><span>alimentando · <b>${nome}</b>${det}</span>${cnt}`;
  el.classList.add('on');
}
function nuSet(id,val){
  const el=$('nu-'+id);if(el==null)return;const n=el.querySelector('.n');
  const prev=_nuVals[id];_nuVals[id]=val;
  n.textContent=val==null?'—':(typeof val==='number'?fmtN(val):val);
  if(typeof val==='number'&&typeof prev==='number'&&val!==prev){   // delta REAL desde a última amostra
    const d=val-prev,s=document.createElement('em');s.className='nu-delta';
    s.textContent=(d>0?'+':'')+fmtN(d);el.appendChild(s);setTimeout(()=>s.remove(),4000);}
}
function nucleoPulse(tipo){
  if(_redMotion||!$('ck-nucleo'))return;
  const c={alerta:'255,122,138',radar:'255,122,138',ob_siafe:'238,194,118',ob_tfe:'238,194,118',
           clausula:'192,150,255',pericia:'95,224,161',ata:'125,175,255'}[tipo]||'95,217,255';
  _nuPulses.push({r:0.14,a:.85,c});   // v12: raio em UNIDADE DE MUNDO (onda no piso), não em pixel
  // o evento também VIAJA: sai do domínio que o produziu e entra no núcleo.
  // É o barramento ficando visível — mesma metáfora do Conduíte, em órbita.
  const alvo={alerta:'alertas',radar:'radar',ob_siafe:'compras',ob_tfe:'compras',
              clausula:'dossie',pericia:'fenix',ata:'com'}[tipo];
  if(alvo)_nuFlux.push({id:alvo,p:0,c});
  if(_nuFlux.length>24)_nuFlux.splice(0,_nuFlux.length-24);   // teto: rajada não vira enxame
  // HUD: telemetria REAL da vigília (contagem de eventos do barramento — nada sintético)
  _nuEvTotal++;const hud=$('nu-hud');
  if(hud)hud.innerHTML=`<b>${_nuEvTotal}</b> evento${_nuEvTotal===1?'':'s'} reais do barramento nesta vigília`;
}
let _nuEvTotal=0,_nuHover=null;
/* ═══════════════ v12 "HOLOMESA" — câmera 3D de verdade ═══════════════
   O núcleo deixa de ser um círculo visto de frente e passa a ser uma MESA DE
   HOLOGRAMA: o território do RJ é o CHÃO (perspectiva com divisão por z), os
   domínios FLUTUAM acima dele em três altitudes, cada um ancorado ao piso por
   um feixe vertical e uma pegada de luz. No centro, o projetor.

   Por que profundidade de verdade aparece: (a) divisão por z — o que está longe
   encolhe; (b) oclusão por ordem de pintura; (c) paralaxe — a câmera responde ao
   cursor; (d) contato com um plano (feixe + pegada). Sem os quatro, objeto
   flutuando lê como adesivo colado na tela — é o erro que faz 3D parecer amador.

   Custo (a VM tem 2 vCPU): o piso é assado UMA vez em bitmap ortogonal e
   deformado para a perspectiva em faixas afins; o resultado fica em cache e só
   é refeito quando a câmera realmente se move. Em repouso, o piso custa um
   drawImage por quadro. */
/* alfa 0..1 -> par hexadecimal, para concatenar em '#rrggbb' sem montar rgba() */
const _hex2=a=>Math.max(0,Math.min(255,Math.round(a*255))).toString(16).padStart(2,'0');
const HOLO={PL:1.10, ELEV:0.56, CAMD:3.15, SZ:520,    // piso, elevação (rad), distância, resolução do bitmap
            ESP:0.045, ARO:1.11, GIRO:-0.28,          // espessura da laje · aro · giro do território (rad)
            /* ALT = teto da cena: altura do reator e do anel mais alto. Era 0.60 solto em
               três lugares (o HT do enquadramento e os dois P(0,0.60,0) do reator), e
               esse ar reservado acima do piso era o que fazia o TERRITÓRIO ficar numa
               faixa fina no meio do card — o "pequeno e vazio" que o dono viu. Baixar
               para 0.46 devolve a altura ao piso e mantém a escada de três degraus. */
            ALT:0.46};
function _holoProj(x,y,z,c){                          // mundo → tela (x direita, y altura, z profundidade)
  const X=x*c.cy_ - z*c.sy_, Z=x*c.sy_ + z*c.cy_;     // giro em torno do eixo vertical (yaw)
  const Y2=y*c.cp + Z*c.sp;                           // inclinação da câmera (elevação)
  const Z2=Math.max(0.42, Z*c.cp - y*c.sp + c.camd);  // distância à câmera (nunca atrás do olho)
  const k=c.camd/Z2;                                  // perspectiva: k=1 no centro da mesa
  return {x:c.cx + X*k*c.s, y:c.cy - Y2*k*c.s, k, z:Z2};
}
/* território assado em vista ORTOGONAL de cima, num quadrado que cobre o piso
   inteiro. É este bitmap que depois vira chão em perspectiva. */
function _rjPlaca(M,SZ){
  const c=document.createElement('canvas');c.width=c.height=SZ;
  const x=c.getContext('2d');
  /* GIRO DO TERRITÓRIO (v12.2) — o RJ é largo no eixo leste-oeste e a placa é redonda:
     alinhado ao eixo x ele deixava vazias as duas pontas da elipse. Girado, usa a
     DIAGONAL, que é o maior diâmetro aparente da mesa em perspectiva. E a ocupação
     sobe de 0,92 para 0,99 porque o cálculo agora usa a caixa DEPOIS do giro. */
  const GIRO=HOLO.GIRO;
  const cg=Math.abs(Math.cos(GIRO)),sg=Math.abs(Math.sin(GIRO));
  const lw=M.w*cg+M.h*sg,lh=M.w*sg+M.h*cg;
  const s=Math.min(SZ*0.99/lw,SZ*0.99/lh),ox=(SZ-M.w*s)/2,oy=(SZ-M.h*s)/2;
  const mk=flat=>{const p=new Path2D();let X=flat[0],Y=flat[1];
    p.moveTo(ox+X/M.q*s,oy+Y/M.q*s);
    for(let i=2;i<flat.length;i+=2){X+=flat[i];Y+=flat[i+1];p.lineTo(ox+X/M.q*s,oy+Y/M.q*s);}
    p.closePath();return p;};
  x.translate(SZ/2,SZ/2);x.rotate(GIRO);x.translate(-SZ/2,-SZ/2);
  x.lineJoin=x.lineCap='round';
  x.strokeStyle='rgba(120,170,245,0.22)';x.lineWidth=0.9;      // as 92 divisas municipais
  M.m.forEach(f=>x.stroke(mk(f)));
  x.shadowColor='rgba(140,196,255,0.95)';x.shadowBlur=10;      // fronteira sob vigília
  x.strokeStyle='rgba(186,218,255,0.62)';x.lineWidth=1.7;
  M.o.forEach(f=>x.stroke(mk(f)));
  x.shadowBlur=16;x.shadowColor='rgba(255,150,60,0.8)';        // o litoral pega o calor do reator
  x.strokeStyle='rgba(255,190,120,0.26)';x.lineWidth=1.1;
  M.o.forEach(f=>x.stroke(mk(f)));
  return c;
}
/* deforma a placa ortogonal para o chão em perspectiva, em faixas de profundidade
   constante. Cada faixa é fina o bastante para que a projeção seja afim dentro
   dela — que é o que setTransform sabe fazer. Do fundo para a frente. */
/* Contorno do RJ em coordenadas de MUNDO (calculado uma vez). São 294 pontos — projetar
   isso por quadro é irrisório, e é o que permite dar ESPESSURA ao território: sem parede
   lateral a malha é um decalque deitado no chão, e o olho lê desenho, não objeto. */
function _rjContornoMundo(M){
  const PL=HOLO.PL, SZ=HOLO.SZ, GIRO=HOLO.GIRO;
  const cg=Math.abs(Math.cos(GIRO)), sg=Math.abs(Math.sin(GIRO));
  const lw=M.w*cg+M.h*sg, lh=M.w*sg+M.h*cg;
  const s=Math.min(SZ*0.99/lw,SZ*0.99/lh), ox=(SZ-M.w*s)/2, oy=(SZ-M.h*s)/2;
  return M.o.map(flat=>{
    const pts=[];let X=flat[0],Y=flat[1];
    /* o MESMO giro da placa: sem ele a parede lateral da laje descola da malha */
    const põe=()=>{const rx=ox+X/M.q*s-SZ/2, ry=oy+Y/M.q*s-SZ/2;
      const sx=SZ/2+rx*Math.cos(GIRO)-ry*Math.sin(GIRO);
      const sy=SZ/2+rx*Math.sin(GIRO)+ry*Math.cos(GIRO);
      pts.push([sx/SZ*2*PL-PL, PL-sy/SZ*2*PL]);};   // inverso exato do mapeamento da placa
    põe();
    for(let i=2;i<flat.length;i+=2){X+=flat[i];Y+=flat[i+1];põe();}
    return pts;
  });
}
function _holoPiso(g,bmp,c,W,H,alt){
  const PL=HOLO.PL,SZ=bmp.width,NF=26,dz=2*PL/NF,y=alt||0;
  g.clearRect(0,0,W,H);
  for(let i=0;i<NF;i++){
    const zF=PL-i*dz, zN=zF-dz, sy0=i*SZ/NF, sy1=(i+1)*SZ/NF, hs=sy1-sy0;
    const P00=_holoProj(-PL,y,zF,c), P10=_holoProj(PL,y,zF,c), P01=_holoProj(-PL,y,zN,c);
    const a=(P10.x-P00.x)/SZ, b=(P10.y-P00.y)/SZ, cc=(P01.x-P00.x)/hs, d=(P01.y-P00.y)/hs;
    if(!isFinite(a)||!isFinite(d)||Math.abs(a*d-b*cc)<1e-9)continue;
    g.save();g.transform(a,b,cc,d,P00.x-cc*sy0,P00.y-d*sy0);
    g.drawImage(bmp,0,sy0,SZ,Math.min(SZ-sy0,hs+1),0,sy0,SZ,Math.min(SZ-sy0,hs+1));
    g.restore();
  }
}
function nucleoStart(){
  const box=$('ck-nucleo'),cv=$('nucleo-cv');if(!box||!cv)return;
  /* v41: NUCLEO-HOLO — o arc reactor que projeta o holograma do RJ (arte do
     it-campo) entra como corpo de video SOB o canvas; o procedural (feixes,
     chips, dados reais) segue por cima. Progressivo: sem arquivo, nada muda. */
  /* matchMedia direto: nucleoStart roda no boot ANTES do const _redMotion
     (TDZ) — referencia-lo aqui matava a funcao inteira em ReferenceError. */
  if(!matchMedia('(prefers-reduced-motion: reduce)').matches)
    fetch('/static/assets/nucleo-holo-rj.mp4',{method:'HEAD'}).then(r=>{
    if(!r.ok)return;
    let v=box.querySelector('video.holo');
    if(!v){v=document.createElement('video');v.className='holo';
      v.muted=true;v.loop=true;v.playsInline=true;v.autoplay=true;
      v.setAttribute('aria-hidden','true');
      v.addEventListener('playing',()=>v.classList.add('on'));
      /* v41.1: par de sources — webm primeiro (Chromium sem H.264 decodifica
         VP9; o Chrome real pega qualquer um). O que faltar cai pro proximo. */
      v.innerHTML='<source src="/static/assets/nucleo-holo-rj.webm" type="video/webm">'
                 +'<source src="/static/assets/nucleo-holo-rj.mp4" type="video/mp4">';
      box.insertBefore(v,box.firstChild);}
    v.play().catch(()=>{});
  }).catch(()=>{});
  const rm=_redMotion,ctx=cv.getContext('2d'),dpr=Math.min(2,devicePixelRatio||1),N=NU_NODES.length;
  $('nu-chips').innerHTML=NU_NODES.map(n=>
    `<button type="button" class="nu-chip" id="nu-${n.id}" style="--nc:${n.cor}" onclick="ir('${n.tab}')"
       onpointerenter="_nuHover='${n.id}'" onpointerleave="_nuHover=null">
      <small>${n.lab}</small><span class="n">—</span></button>`).join('');
  /* três altitudes em vez de sete órbitas quase iguais: a mesa lê como escada
     holográfica e os rótulos param de brigar. Raio e altura andam juntos —
     quanto mais perto do reator, mais alto. */
  const ANEIS=[{r:0.46,h:0.48},{r:0.74,h:0.32},{r:1.00,h:0.18}];  // escalados por HOLO.ALT/0.60
  NU_NODES.forEach((n,i)=>{n._an=n.orb<=0.7?0:(n.orb<=0.88?1:2);n._idx=i;});
  /* FASE FIXA E DISTRIBUÍDA dentro do próprio anel, com UMA velocidade para todos.
     Antes cada domínio tinha velocidade própria: eles derivavam, formavam aglomerado
     e os rótulos se empilhavam de um lado da mesa enquanto o outro ficava vazio.
     Com fase homogênea por anel a distribuição é estável para sempre — e é ela, não
     um algoritmo de colisão, que resolve o empilhamento na raiz. */
  [0,1,2].forEach(a=>{const nós=NU_NODES.filter(n=>n._an===a);
    nós.forEach((n,i)=>{n._fase=(i/nós.length)*2*Math.PI + a*0.7;});});
  const ESP=HOLO.ESP, ARO=HOLO.ARO;
  /* `_nuVisivel` fica AQUI, com o resto do estado, e nao junto do observador la
     embaixo: `repinta()` chama `draw()` antes daquele ponto e um `let` ainda em zona
     morta temporal derrubava a mesa inteira com ReferenceError — mas SO em
     reduced-motion, que e o unico caminho em que `repinta()` desenha. */
  let W,H,placa=null,contorno=null,piso=null,pisoG=null,pisoSujo=true,_nuVisivel=true;
  const cam={cx:0,cy:0,s:1,camd:HOLO.CAMD,yaw:0,tyaw:0,elev:HOLO.ELEV,telev:HOLO.ELEV,
             cp:0,sp:0,cy_:1,sy_:0};
  window.__holoCam=cam;      // gancho de auditoria: o screenshot sozinho não diz onde a câmera está
  window.__nuEstado=()=>({vis:_nuVisivel,raf:_nuRAF});   // idem para o orçamento de vida
  function setCam(){cam.cp=Math.cos(cam.elev);cam.sp=Math.sin(cam.elev);
    cam.cy_=Math.cos(cam.yaw);cam.sy_=Math.sin(cam.yaw);}
  /* TRILHOS DE CHAMADA: metade dos domínios à esquerda, metade à direita, em
     fatias verticais fixas. Rótulo parado = número legível; quem se move é a
     linha-guia até o nó. Também é o que devolve as laterais vazias ao trabalho. */
  let _railW=182,_compacto=false,_gradeH=0;
  function trilhos(){
    /* Abaixo de 720px o trilho lateral é a decisão errada: dois trilhos comem a
       largura toda e a mesa vira um borrão de 120px (medido no emulador a 390px).
       Nesse regime os rótulos descem para uma GRADE sob a mesa e a cena fica com a
       largura inteira — a linha-guia perde a função e sai. */
    _compacto=W<720;
    box.classList.toggle('compacto',_compacto);
    if(_compacto){
      const cols=W<430?2:3, gap=8, marg=12;
      const cw=Math.floor((W-marg*2-gap*(cols-1))/cols);
      let ch=0;
      NU_NODES.forEach((no,i)=>{
        const el=$('nu-'+no.id);if(!el)return;
        el.classList.remove('r');
        el.style.width=cw+'px';el.style.minWidth='0';el.style.maxWidth='none';
        el.style.transform='none';el.style.right='auto';no._tf=null;no._z=null;
        ch=el.offsetHeight||34;
        el.style.left=(marg+(i%cols)*(cw+gap))+'px';
        no._ax=null;                        // sem trilho, sem linha-guia
      });
      const linhas=Math.ceil(NU_NODES.length/cols);
      _gradeH=linhas*(ch+gap)+gap;
      NU_NODES.forEach((no,i)=>{const el=$('nu-'+no.id);if(!el)return;
        el.style.top=Math.round(H-_gradeH+gap+Math.floor(i/cols)*(ch+gap))+'px';});
      box.style.setProperty('--grade-h',_gradeH+'px');
      return;
    }
    _gradeH=0;
    /* Fora do regime compacto o rótulo não mora mais num trilho: ele é ancorado ao
       próprio nó, quadro a quadro, no passo 11 do desenho. Aqui só se limpa o que o
       trilho havia deixado inline — sem isso um `right:14px` sobrevive e prega o
       rótulo na borda para sempre. */
    NU_NODES.forEach(no=>{const el=$('nu-'+no.id);if(!el)return;
      el.classList.remove('r');
      el.style.width='';el.style.minWidth='';el.style.maxWidth='';el.style.right='auto';
      /* left/top do regime compacto TÊM de sair: eles são inline, vencem o `left:0`
         do CSS e somariam ao translate3d — o rótulo sairia deslocado ao atravessar
         o limiar de 720px de volta para a cena. */
      el.style.left='';el.style.top='';no._tf=null;no._z=null;
      no._rail=null;});
  }
  function size(){
    W=box.clientWidth;H=box.clientHeight;cv.width=W*dpr;cv.height=H*dpr;
    cv.style.width=W+'px';cv.style.height=H+'px';ctx.setTransform(dpr,0,0,dpr,0,0);
    setCam();trilhos();
    /* escala: o piso é um trapézio (borda perto × borda longe) e ainda há o que
       FLUTUA acima dele — a cena a enquadrar é piso + altura do projetor. */
    const PL=HOLO.PL, kN=cam.camd/Math.max(.42,cam.camd-PL*cam.cp), kF=cam.camd/(cam.camd+PL*cam.cp);
    const A=PL*cam.sp*kF, B=PL*cam.sp*kN, HT=HOLO.ALT*cam.cp*1.14;
    /* A faixa lateral era 132px de cada lado e era a LARGURA que limitava a mesa:
       medido a 1440, o território ocupava só 77% do card (894 de 1158px) enquanto a
       altura sobrava 9%. E a reserva nem estava em uso — o rótulo mais externo parava
       a 170px da borda, ou seja, DENTRO da mesa. 48px basta para o empurrão radial e
       devolve ~140px de território ao quadrado. */
    const gut=_compacto?10:48;       // faixa em volta da mesa: é onde os rótulos pousam
    const Hu=Math.max(150,H-_gradeH);                      // altura util: a grade tem a dela
    cam.s=Math.min(Hu*0.965/(A+B+HT), Math.max(140,W-2*gut)/(2*PL*kN));
    cam.cx=W/2;
    cam.cy=(Hu-(A+B+HT)*cam.s)/2+(A+HT)*cam.s;             // centraliza a CENA, não só o piso
    piso=document.createElement('canvas');piso.width=W*dpr;piso.height=H*dpr;
    pisoG=piso.getContext('2d');pisoG.setTransform(dpr,0,0,dpr,0,0);
    pisoSujo=true;
    if(window.RJ_MALHA&&!placa){placa=_rjPlaca(window.RJ_MALHA,HOLO.SZ);
      contorno=_rjContornoMundo(window.RJ_MALHA);}
  }
  /* Em reduced-motion NAO ha laco de animacao: a cena e pintada UMA vez. Mas
     `size()` faz `canvas.width=...`, que LIMPA o bitmap — entao qualquer resize (ou
     a malha do RJ chegando depois) apagava a mesa para sempre e o usuario ficava com
     uma caixa preta. Toda vez que a geometria muda, repinta explicitamente. */
  const repinta=()=>{if(rm&&cv.isConnected)draw(performance.now());};
  size();repinta();
  /* v28.7: `size()` faz cv.width=..., e atribuir width a um canvas LIMPA o
     bitmap E invalida a placa/contorno ja rasterizados para o tamanho velho.
     O handler so chamava repinta(), que redesenha as camadas dinamicas mas
     nao reconstroi o que e cache — entao o primeiro resize depois da pintura
     inicial apagava a mesa e nada a trazia de volta. Medido no Chrome do
     dono: getImageData no canvas devolvia opacas=0, canvas inteiramente
     vazio, enquanto o piso visivel na tela vinha do CSS.
     _rjMontar reconstroi placa e contorno no tamanho novo e marca o piso
     sujo antes de repintar.                                              */
  addEventListener('resize',()=>{if(cv.isConnected){size();_rjMontar();}});
  const _rjMontar=()=>{if(!cv.isConnected||!window.RJ_MALHA)return;
    placa=_rjPlaca(window.RJ_MALHA,HOLO.SZ);
    contorno=_rjContornoMundo(window.RJ_MALHA);pisoSujo=true;repinta();};
  _rjCarregar(_rjMontar);
  /* v28.6: a malha chega por <script async> e o callback agenda o quadro no
     rAF. Se a aba estiver em segundo plano nesse instante o rAF esta
     congelado: o quadro nunca sai e NADA re-agenda quando a aba volta — a
     mesa de vigilia ficava so com o piso, sem o mapa nem os marcadores.
     Medido no Chrome do dono: RJ_MALHA carregada, _rjPlaca devolvendo
     object, canvas conectado. Nao faltava dado; faltava um quadro.
     Mesma familia do portal preso (3cf2a6a1).                          */
  document.addEventListener('visibilitychange',()=>{
    if(document.visibilityState==='visible'&&cv.isConnected)_rjMontar();});
  // PARALAXE: o cursor gira a mesa. É o que transforma "desenho" em "objeto".
  cv.style.pointerEvents='auto';
  cv.onpointermove=e=>{const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
    if(!rm){cam.tyaw=((mx/W)-0.5)*0.46; cam.telev=HOLO.ELEV+((my/H)-0.5)*0.20;}
    _nuHover=null;let best=520;
    NU_NODES.forEach(n=>{if(n._x==null)return;const d=(n._x-mx)**2+(n._y-my)**2;
      if(d<best){best=d;_nuHover=n.id;}});
    cv.style.cursor=_nuHover?'pointer':'default';};
  cv.onpointerleave=()=>{_nuHover=null;cam.tyaw=0;cam.telev=HOLO.ELEV;};
  cv.onclick=()=>{const n=NU_NODES.find(q=>q.id===_nuHover);if(n)ir(n.tab);};
  /* ORÇAMENTO DE VIDA — a mesa é a cena mais cara do painel e continuava desenhando a
     60fps depois que o usuário rolou para as tabelas: trabalho inteiramente jogado fora
     numa VM de 2 vCPU. `document.hidden` já cobria a aba oculta; faltava o SCROLL.
     Aqui o laço PARA de vez quando a caixa sai da viewport e o próprio observador o
     retoma na volta — não é um rAF que acorda 60×/s só para desistir. */
  if('IntersectionObserver' in window){
    new IntersectionObserver(es=>{
      const antes=_nuVisivel;
      _nuVisivel=es.some(e=>e.isIntersecting);
      if(_nuVisivel&&!antes&&!rm&&cv.isConnected){cancelAnimationFrame(_nuRAF);draw(performance.now());}
    },{rootMargin:'80px'}).observe(box);      // margem: retoma um pouco antes de aparecer
  }
  function draw(t){
    if(!cv.isConnected){cancelAnimationFrame(_nuRAF);_nuRAF=0;return;}
    if(!_nuVisivel){_nuRAF=0;return;}                  // fora da viewport: o observador retoma
    if(document.hidden){_nuRAF=requestAnimationFrame(draw);return;}
    // câmera com inércia (ease exponencial, sem mola nem bounce)
    if(Math.abs(cam.tyaw-cam.yaw)>2e-4||Math.abs(cam.telev-cam.elev)>2e-4){
      cam.yaw+=(cam.tyaw-cam.yaw)*0.075; cam.elev+=(cam.telev-cam.elev)*0.075;
      setCam();pisoSujo=true;
    }
    const P=(x,y,z)=>_holoProj(x,y,z,cam);
    ctx.clearRect(0,0,W,H);
    /* 1 · A MESA — grade de alcance no tampo: 4 anéis + 12 raios. Dá escala ao
       território e é o que faz o olho aceitar o plano como plano. */
    ctx.lineWidth=1;
    for(let a=0;a<4;a++){
      const r=0.30+a*0.27;
      ctx.strokeStyle=`rgba(130,180,255,${a===3?0.16:0.085})`;
      ctx.beginPath();
      for(let i=0;i<=64;i++){const th=i/64*6.283,p=P(Math.cos(th)*r,0,Math.sin(th)*r);
        i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y);}
      ctx.stroke();
    }
    /* 1b · ARO DA MESA — o piso antes só esmaecia, e sem limite físico o olho não
       aceita a coisa como objeto: aceita como fundo. O aro é a borda do tampo. */
    ctx.beginPath();
    for(let i=0;i<=96;i++){const th=i/96*6.283,p=P(Math.cos(th)*ARO,0,Math.sin(th)*ARO);
      i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y);}
    ctx.strokeStyle='rgba(120,175,255,0.30)';ctx.lineWidth=1.6;ctx.stroke();
    ctx.strokeStyle='rgba(150,205,255,0.10)';ctx.lineWidth=5;ctx.stroke();   // halo do aro
    ctx.strokeStyle='rgba(130,180,255,0.06)';
    for(let i=0;i<12;i++){const th=i/12*6.283,A=P(Math.cos(th)*0.2,0,Math.sin(th)*0.2),
      B=P(Math.cos(th)*1.11,0,Math.sin(th)*1.11);
      ctx.beginPath();ctx.moveTo(A.x,A.y);ctx.lineTo(B.x,B.y);ctx.stroke();}
    /* 2 · O TERRITÓRIO TEM ESPESSURA — antes ele era um contorno deitado no tampo, e
       contorno deitado o olho lê como decalque, não como coisa. Agora é uma laje:
         a) parede lateral, de ESP até o tampo (anel por anel, para o `evenodd` não
            cancelar ilha com continente);
         b) superfície de vidro fumê, que ESCONDE a parede de trás (que deve estar
            oculta) e ainda deixa a grade da mesa aparecer por baixo;
         c) a malha assada por cima, agora projetada na ALTURA da laje.
       São 294 pontos de contorno: o custo disso é ruído perto do orçamento de quadro. */
    if(contorno){
      contorno.forEach(anel=>{                                   // a) parede
        ctx.beginPath();
        anel.forEach(([x,z],i)=>{const p=P(x,ESP,z);i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y);});
        for(let i=anel.length-1;i>=0;i--){const p=P(anel[i][0],0,anel[i][1]);ctx.lineTo(p.x,p.y);}
        ctx.closePath();
        ctx.fillStyle='rgba(34,62,112,0.62)';ctx.fill();
        ctx.strokeStyle='rgba(110,165,240,0.20)';ctx.lineWidth=0.7;ctx.stroke();
      });
      ctx.beginPath();                                           // b) tampo de vidro fumê
      contorno.forEach(anel=>{
        anel.forEach(([x,z],i)=>{const p=P(x,ESP,z);i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y);});
        ctx.closePath();});
      ctx.fillStyle='rgba(9,19,40,0.66)';ctx.fill('evenodd');
    }
    if(placa&&pisoG){                                            // c) a malha, na altura da laje
      if(pisoSujo){_holoPiso(pisoG,placa,cam,W,H,ESP);pisoSujo=false;}
      ctx.drawImage(piso,0,0,W,H);
    }
    /* 3 · TRILHAS — um anel por altitude, metade de trás apagada por profundidade */
    ANEIS.forEach(an=>{
      for(let s=0;s<8;s++){
        ctx.beginPath();let zm=0;
        for(let i=0;i<=8;i++){const th=(s*8+i)/64*6.283,p=P(Math.cos(th)*an.r,an.h,Math.sin(th)*an.r);
          zm+=p.z;i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y);}
        const prox=1-Math.min(1,Math.max(0,(zm/9-(cam.camd-1.1))/2.2));   // 1 = frente
        ctx.strokeStyle=`rgba(150,200,255,${(0.03+0.13*prox).toFixed(3)})`;
        ctx.lineWidth=0.6+0.7*prox;ctx.stroke();
      }
    });
    /* 4 · posição 3D de cada domínio (o ângulo continua girando devagar) */
    const pos=NU_NODES.map((n,i)=>{
      const an=ANEIS[n._an],a=-Math.PI/2+(n._fase||0)+(rm?0:t*0.000030);
      const wx=Math.cos(a)*an.r, wz=Math.sin(a)*an.r;
      const p=P(wx,an.h,wz), pe=P(wx,ESP,wz);               // nó no ar · pé na laje
      return {n,a,wx,wz,h:an.h,x:p.x,y:p.y,k:p.k,z:p.z,px:pe.x,py:pe.y,pk:pe.k};
    });
    pos.forEach(p=>{p.n._x=p.x;p.n._y=p.y;p.n._k=p.k;});
    /* 4b · IDENTIFICAÇÃO NO LUGAR — o rótulo fica junto do próprio nó, que é onde o
       olho procura e onde a mão clica. Os três defeitos que o trilho lateral havia
       curado por layout ficam curados aqui por código:
         · empurrão RADIAL para fora (o rótulo sai de cima da mesa e usa a faixa vazia);
         · anti-colisão contra os já posicionados, com o mais PRÓXIMO decidindo primeiro
           (quem está perto do olho não cede lugar);
         · trava dentro da caixa — era assim que o "empresa morta" saía clipado no v11.
       Posicionado ANTES do desenho para que o conector do passo 11 use a posição
       desta volta, não a da anterior. */
    if(!_compacto){
      /* O REATOR É ÁREA RESERVADA: entra na lista de colisão antes de qualquer rótulo,
         então nada pousa em cima dele. Foi o defeito que escondeu o projetor no v12. */
      const _hc=P(0,HOLO.ALT,0), _hr=64*_hc.k*Math.min(1.5,cam.s/240);
      const _cx=[{x:_hc.x,y:_hc.y,w:_hr*2,h:_hr*2}];
      /* A PÍLULA DE SWEEP também é território ocupado quando está acesa. Ela vive no
         topo e ao centro; um rótulo empurrado para cima cobria o "alimentando · SEI".
         Só restringe quem de fato cruza a faixa horizontal dela — quem está na
         lateral continua podendo subir. */
      /* Toda leitura de geometria (offset*) entra no MESMO cache de 45 quadros. Ler
         `offset*` depois de escrever estilo força LAYOUT SÍNCRONO: medir a pílula a
         cada quadro levou o teto do desenho de 5,7 ms para 44,7 ms. */
      /* `classList.contains` não custa layout — então a MUDANÇA de estado da pílula
         força a remedição na hora, em vez de esperar o ciclo de 45 quadros. Nesta VM,
         a 3 fps, esperar o ciclo significava até 15 s com o rótulo em cima do sweep. */
      const _pOn=(()=>{const e=$('nu-sweep');return !!(e&&e.classList.contains('on'));})();
      if(_pOn!==draw._pOn){draw._pOn=_pOn;draw._m=999;}
      if(!draw._m||draw._m>45){
        draw._m=0;
        NU_NODES.forEach(n=>{const e=$('nu-'+n.id);
          if(e){n._w=e.offsetWidth||96;n._h=e.offsetHeight||34;}});
        const pil=$('nu-sweep');
        if(pil&&pil.classList.contains('on')){
          /* pela CAIXA RENDERIZADA, não por `offsetLeft`: a pílula é centrada com
             `left:50%` + `translateX(-50%)`, e offsetLeft ignora o transform — a faixa
             reservada saía deslocada meia largura e o rótulo cobria o sweep assim mesmo. */
          const rb=box.getBoundingClientRect(), rp=pil.getBoundingClientRect();
          draw._pX=[rp.left-rb.left,rp.right-rb.left];
          draw._pB=rp.bottom-rb.top+10;
        }else{draw._pX=null;draw._pB=0;}
      }
      draw._m=(draw._m||0)+1;
      const _pX=draw._pX, _pB=draw._pB||0;
      pos.slice().sort((a,b)=>b.k-a.k).forEach(o=>{
        const n=o.n,el=$('nu-'+n.id);if(!el)return;
        /* empurrão radial a partir do centro do PRÓPRIO ANEL do nó, não do centro do
           piso: todo nó flutua acima do piso, então usar o piso como eixo empurrava
           todos para CIMA e eles se empilhavam no topo. O centro do anel devolve o
           anel de rótulos em volta da órbita — que era o comportamento do v11. */
        const rc=P(0,o.h,0);
        const dx=o.x-rc.x, dy=o.y-rc.y, d=Math.hypot(dx,dy)||1;
        const sc=Math.max(.84,Math.min(1.06,o.k));
        const w=(n._w||96)*sc, h=(n._h||34)*sc;
        let x=o.x+dx/d*54, y=o.y+dy/d*34-18;
        for(const c of _cx){
          if(Math.abs(x-c.x)<(w+c.w)/2+8 && Math.abs(y-c.y)<(h+c.h)/2+8)
            y=(y<=c.y)?c.y-(h+c.h)/2-9:c.y+(h+c.h)/2+9;
        }
        x=Math.max(w/2+8,Math.min(W-w/2-8,x));      // nunca sai da caixa
        const cruzaPilula=_pX&&(x-w/2)<_pX[1]+6&&(x+w/2)>_pX[0]-6;
        y=Math.max(h+(cruzaPilula?_pB:8),Math.min(H-8,y));
        _cx.push({x,y,w,h});
        const tf='translate3d('+Math.round(x)+'px,'+Math.round(y)+'px,0) '
                +'translate(-50%,-100%) scale('+sc.toFixed(2)+')';
        if(n._tf!==tf){n._tf=tf;el.style.transform=tf;}       // só escreve o que mudou
        const z=String(2+Math.round(40*o.k));
        if(n._z!==z){n._z=z;el.style.zIndex=z;}
        n._lx=x;n._ly=y-h/2;                        // âncora do conector até o nó
      });
    }
    /* 5 · LIGAÇÕES entre domínios vizinhos: nenhum indício vive isolado */
    for(let i=0;i<pos.length;i++){
      const A=pos[i],B=pos[(i+1)%pos.length];
      ctx.strokeStyle='rgba(150,190,255,'+(0.03+0.07*Math.min(A.k,B.k)).toFixed(3)+')';
      ctx.lineWidth=.7;ctx.beginPath();ctx.moveTo(A.x,A.y);ctx.lineTo(B.x,B.y);ctx.stroke();
    }
    /* 6 · CENA ORDENADA POR PROFUNDIDADE — nós e projetor entram na MESMA fila e
       são pintados do fundo para a frente. É isso que faz um domínio passar por
       TRÁS da coluna do projetor em vez de sempre por cima: oclusão é metade da
       leitura de 3D; sem ela, o olho lê adesivo colado na tela. */
    const sw=!!_sweepAtivo;
    const pulse=rm?1:((sw?0.76:0.86)+(sw?0.24:0.14)*Math.sin(t*(sw?0.0042:0.0021)));
    const spin=rm?0:t*0.0004*(sw?2.3:1);
    /* um domínio: pegada de luz no piso + feixe vertical + o próprio nó.
       O feixe é a assinatura do holograma — é ele que prende o objeto ao chão. */
    const desenhaNo=o=>{
      const {n,x,y,k,px,py,pk}=o, viva=_nuHover===n.id;
      const rp=(viva?18:13)*pk;                             // pegada de luz no piso
      const pg=ctx.createRadialGradient(px,py,0,px,py,rp);
      pg.addColorStop(0,n.cor+(viva?'8a':'55'));pg.addColorStop(.5,n.cor+'1e');pg.addColorStop(1,n.cor+'00');
      ctx.fillStyle=pg;ctx.save();ctx.translate(px,py);ctx.scale(1,Math.max(.18,cam.sp));
      ctx.beginPath();ctx.arc(0,0,rp,0,6.283);ctx.fill();ctx.restore();
      const bg=ctx.createLinearGradient(px,py,x,y);         // feixe: acende no contato e no topo
      bg.addColorStop(0,n.cor+(viva?'77':'44'));bg.addColorStop(.45,n.cor+(viva?'33':'1c'));
      bg.addColorStop(1,n.cor+(viva?'ee':'99'));
      ctx.strokeStyle=bg;ctx.lineWidth=Math.max(.9,(viva?2.4:1.7)*k);
      ctx.beginPath();ctx.moveTo(px,py);ctx.lineTo(x,y);ctx.stroke();
      const R=(viva?18:13)*k;                                // perto = maior e mais aceso
      const rg=ctx.createRadialGradient(x,y,0,x,y,R);
      rg.addColorStop(0,n.cor+'e6');rg.addColorStop(.35,n.cor+'4a');rg.addColorStop(1,n.cor+'00');
      ctx.fillStyle=rg;ctx.beginPath();ctx.arc(x,y,R,0,6.283);ctx.fill();
      /* ── APARELHAGEM DO NÓ (v12.3) ────────────────────────────────────────────
         O domínio era um ponto de luz num palito: ao lado do reator detalhado ele
         lia como marcador de mapa, não como instrumento da mesma máquina.

         RELÓGIO PRÓPRIO: cada domínio respira no SEU tempo — período e fase derivados
         do índice (determinístico; a casa proíbe gerador aleatório em cena). Sete
         pulsos em compassos diferentes é o que faz a mesa parecer VIVA; sete pulsos
         no mesmo compasso é uma luz de natal piscando junta.

         Custo: dois Path2D por nó (estrutura e ping), não um traço por elemento. */
      const S=v=>v*k, idx=n._idx||0;
      const per=1+((idx*7)%5)*0.34;                          // 1,00 · 1,34 · 1,68 · 2,02 · 2,36
      const fase=idx*1.97;
      const pul=rm?0.55:0.5+0.5*Math.sin(t*0.0017/per+fase); // respiração do nó
      const gir=rm?0:t*0.00040/per+fase;                     // e ele gira no próprio ritmo
      const ap=new Path2D();

      // brackets de mira: 4 cantos que ABREM e FECHAM com a respiração (o gesto que
      // um retículo de Star Wars faz ao travar o alvo)
      const rb1=S((viva?17:13)+4.5*pul);
      for(let q=0;q<4;q++){
        const a0=gir*0.6+q*1.5708-0.34;
        ap.moveTo(x+Math.cos(a0)*rb1,y+Math.sin(a0)*rb1);
        ap.arc(x,y,rb1,a0,a0+0.68);
        const ae=a0+0.68;                                    // perninhas do bracket
        ap.moveTo(x+Math.cos(ae)*rb1,y+Math.sin(ae)*rb1);
        ap.lineTo(x+Math.cos(ae)*(rb1+S(3.4)),y+Math.sin(ae)*(rb1+S(3.4)));
      }
      // câmara de contenção hexagonal, girando ao contrário
      const rh=S((viva?9.5:7.4)+1.3*pul);
      for(let q=0;q<6;q++){
        const a=-gir*1.7+q*1.0472, hx=x+Math.cos(a)*rh, hy=y+Math.sin(a)*rh;
        q?ap.lineTo(hx,hy):ap.moveTo(hx,hy);
      }
      ap.closePath();
      // travessas do feixe + pacote de energia subindo (cada nó no seu passo)
      const dxb=px-x, dyb=py-y;
      for(let q=1;q<=4;q++){
        const u=q/5, bx=x+dxb*u, by=y+dyb*u, lw2=S(4.2)*(1-u*0.45);
        ap.moveTo(bx-lw2,by);ap.lineTo(bx+lw2,by);
      }
      const rb2=S(7.5);                                      // suporte no pé, sobre a laje
      ap.moveTo(px-rb2,py);ap.arc(px,py,rb2,Math.PI,Math.PI+1.05);
      ap.moveTo(px+rb2,py);ap.arc(px,py,rb2,0,-1.05,true);
      ctx.strokeStyle=n.cor+(viva?'dd':'7a');
      ctx.lineWidth=Math.max(.5,S(viva?1.2:0.85));
      ctx.stroke(ap);

      if(!rm){
        // PING: um anel que sai do nó e some — o radar de cada domínio, no seu período
        const png=((t*0.00034/per)+idx*0.37)%1;
        const rp2=S(11+34*png);
        ctx.strokeStyle=n.cor+_hex2(0.42*(1-png)*(viva?1.6:1));
        ctx.lineWidth=Math.max(.4,S(1.1*(1-png)));
        ctx.beginPath();ctx.arc(x,y,rp2,0,6.283);ctx.stroke();
        // PACOTE: uma centelha sobe o feixe do pé até o nó, no passo do domínio
        const u2=1-(((t*0.00052/per)+idx*0.29)%1);
        const cx2=x+dxb*u2, cy2=y+dyb*u2;
        const gp=ctx.createRadialGradient(cx2,cy2,0,cx2,cy2,S(4.4));
        gp.addColorStop(0,'rgba(255,255,255,.92)');gp.addColorStop(.4,n.cor+'aa');
        gp.addColorStop(1,n.cor+'00');
        ctx.fillStyle=gp;ctx.beginPath();ctx.arc(cx2,cy2,S(4.4),0,6.283);ctx.fill();
      }
      // coração do nó: ponto branco-quente que INCHA com a respiração
      ctx.fillStyle='rgba(255,255,255,'+Math.min(.98,0.34+0.55*k).toFixed(2)+')';
      ctx.beginPath();ctx.arc(x,y,(1.1+1.5*k)*(0.82+0.32*pul),0,6.283);ctx.fill();
    };
    /* 7 · EVENTOS EM TRÂNSITO — cada pacote saiu de um domínio REAL e cai no
       reator, agora em 3D. Vida só com evento do barramento: nada é sintético. */
    if(!rm){
      _nuFlux=_nuFlux.filter(f=>f.p<1);
      _nuFlux.forEach(f=>{
        const o=pos.find(q=>q.n.id===f.id);if(!o)return;
        f.p+=0.022;
        const e=1-Math.pow(1-f.p,2),e2=Math.max(0,e-0.10);
        const at=u=>P(o.wx*(1-u),o.h+(0.60-o.h)*u,o.wz*(1-u));
        const a=at(e),b=at(e2);
        ctx.strokeStyle='rgba('+f.c+','+(0.34*(1-f.p)).toFixed(2)+')';ctx.lineWidth=1.2;
        ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
        ctx.fillStyle='rgba('+f.c+','+(1-f.p*0.75).toFixed(2)+')';
        ctx.beginPath();ctx.arc(a.x,a.y,2.4*a.k,0,6.283);ctx.fill();
      });
    }
    /* 8 · PROJETOR — coluna de energia do piso até o coração, e o coração no ar.
       É a fonte de luz da mesa: tudo que flutua vem daqui. */
    const base=P(0,ESP,0), heart=P(0,HOLO.ALT,0);            // o projetor nasce DA laje
    const desenhaProjetor=()=>{
    for(let a=0;a<3;a++){                                    // anéis do reator, deitados no piso
      const rad=0.10+a*0.055, seg=10+a*5, dir=(a%2?-1:1);
      ctx.strokeStyle=`rgba(150,200,255,${((.34-a*.07)*pulse).toFixed(3)})`;
      ctx.lineWidth=Math.max(.7,1.7-a*.35);
      for(let s=0;s<seg;s++){
        const a0=s/seg*6.283+spin*22*dir;
        ctx.beginPath();
        for(let i=0;i<=6;i++){const th=a0+i/6*(6.283/seg*0.62),p=P(Math.cos(th)*rad,ESP+0.012,Math.sin(th)*rad);
          i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y);}
        ctx.stroke();
      }
    }
    /* a coluna: um cone de luz, não um risco. Larga e difusa na base (onde toca a
       mesa), estreita e quente no coração — é assim que projetor de holograma lê. */
    const col=ctx.createLinearGradient(base.x,base.y,heart.x,heart.y);
    col.addColorStop(0,'rgba(255,176,96,'+(0.30*pulse).toFixed(2)+')');
    col.addColorStop(.55,'rgba(255,190,120,'+(0.20*pulse).toFixed(2)+')');
    col.addColorStop(1,'rgba(255,226,170,'+(0.62*pulse).toFixed(2)+')');
    const poça=ctx.createRadialGradient(base.x,base.y,0,base.x,base.y,74*cam.s/240);
    poça.addColorStop(0,'rgba(255,190,120,'+(0.30*pulse).toFixed(2)+')');
    poça.addColorStop(.45,'rgba(255,170,90,'+(0.10*pulse).toFixed(2)+')');
    poça.addColorStop(1,'rgba(255,160,80,0)');
    ctx.save();ctx.translate(base.x,base.y);ctx.scale(1,Math.max(.18,cam.sp));
    ctx.fillStyle=poça;ctx.beginPath();ctx.arc(0,0,74*cam.s/240,0,6.283);ctx.fill();ctx.restore();
    const meia=30*cam.s/240*pulse;                        // meia-largura do cone na base
    ctx.fillStyle=col;ctx.globalAlpha=.13;ctx.beginPath();
    ctx.moveTo(base.x-meia,base.y);ctx.lineTo(base.x+meia,base.y);
    ctx.lineTo(heart.x+2.4,heart.y);ctx.lineTo(heart.x-2.4,heart.y);ctx.closePath();ctx.fill();
    ctx.globalAlpha=1;
    ctx.strokeStyle=col;ctx.lineWidth=2.6;ctx.beginPath();
    ctx.moveTo(base.x,base.y);ctx.lineTo(heart.x,heart.y);ctx.stroke();
    /* ARC REACTOR — o coração É o reator, e reator se lê DE FRENTE. Deitado no piso
       (como ficou quando a cena virou mesa) ele era só mais um anel de chão: perdeu a
       silhueta que o identifica. Aqui os anéis são desenhados voltados para a câmera
       (billboard) em volta do núcleo, girando em sentidos alternados, e a escala
       respeita a perspectiva pelo `heart.k`. O anel de graduação de 72 ticks devolve
       a leitura de instrumento — precisão, não enfeite. */
    const RR=heart.k*Math.min(1.5,cam.s/240), R=v=>v*RR;
    ctx.save();ctx.translate(heart.x,heart.y);
    /* a0 · CARCACA FOTOGRAFICA — a arte entra ANTES de tudo e um pouco maior que a
       carcaca procedural (R(43.7)), para ler como o corpo da maquina em volta do
       instrumento, nao como um segundo anel disputando o mesmo raio. Nao gira: o
       flare anamorfico e da CAMERA, e camera nao roda junto com a peca. */
    if(_reatorArt.complete&&_reatorArt.naturalWidth){
      const DA=R(104);
      ctx.globalCompositeOperation='lighter';
      ctx.globalAlpha=Math.min(1,0.50*pulse);
      ctx.drawImage(_reatorArt,-DA/2,-DA/2,DA,DA);
      ctx.globalAlpha=1;ctx.globalCompositeOperation='source-over';
    }
    /* Nota de custo: TUDO aqui é batelado em Path2D — um traço por camada, não um por
       segmento. A versão anterior gastava 72 `stroke()` só no anel de graduação; esta
       tem muito mais detalhe e custa MENOS, porque 56 arcos + 72 ticks viraram 6 traços. */

    // a · CARCAÇA — anel espesso com bisel claro por dentro e sombra por fora: é o
    //     bisel que dá espessura de peça usinada em vez de círculo desenhado.
    ctx.lineWidth=R(5.5);ctx.strokeStyle=`rgba(104,150,215,${(0.30*pulse).toFixed(3)})`;
    ctx.beginPath();ctx.arc(0,0,R(41),0,6.283);ctx.stroke();
    ctx.lineWidth=Math.max(.6,R(1));
    ctx.strokeStyle=`rgba(198,228,255,${(0.34*pulse).toFixed(3)})`;
    ctx.beginPath();ctx.arc(0,0,R(38.4),0,6.283);ctx.stroke();
    ctx.strokeStyle=`rgba(24,44,86,${(0.62*pulse).toFixed(3)})`;
    ctx.beginPath();ctx.arc(0,0,R(43.7),0,6.283);ctx.stroke();

    // b · BOBINAS — 10 segmentos radiais (o enrolamento). É o que enche o vazio entre
    //     o núcleo e a carcaça, que antes era só ar.
    const NB=10, folga=0.13, giroB=spin*9;
    const pb=new Path2D();
    for(let k=0;k<NB;k++){
      const a0=k/NB*6.283+giroB, a1=a0+6.283/NB-folga;
      pb.moveTo(Math.cos(a0)*R(23),Math.sin(a0)*R(23));
      pb.arc(0,0,R(23),a0,a1);
      pb.arc(0,0,R(36.5),a1,a0,true);
      pb.closePath();
    }
    const gb=ctx.createRadialGradient(0,0,R(21),0,0,R(37));
    gb.addColorStop(0,`rgba(150,205,255,${(0.30*pulse).toFixed(3)})`);
    gb.addColorStop(.55,`rgba(110,165,235,${(0.16*pulse).toFixed(3)})`);
    gb.addColorStop(1,`rgba(70,115,190,${(0.07*pulse).toFixed(3)})`);
    ctx.fillStyle=gb;ctx.fill(pb);
    ctx.lineWidth=Math.max(.5,R(0.75));
    ctx.strokeStyle=`rgba(186,222,255,${(0.30*pulse).toFixed(3)})`;ctx.stroke(pb);

    // c · ANEL DE ENTALHES — 24 dentes curtos entre bobina e carcaça
    const pe=new Path2D();
    for(let k=0;k<24;k++){
      const a=k/24*6.283-giroB*1.6, cx0=Math.cos(a), sy0=Math.sin(a);
      pe.moveTo(cx0*R(37.6),sy0*R(37.6));pe.lineTo(cx0*R(40.4),sy0*R(40.4));
    }
    ctx.lineWidth=Math.max(.5,R(1.1));
    ctx.strokeStyle=`rgba(160,205,255,${(0.26*pulse).toFixed(3)})`;ctx.stroke(pe);

    // c2 · BRASA INTERNA — o reator estava inteiro em azul-íon, e íon é o polo do
    //      CONSOLE. Sem a chama por dentro ele lê como instrumento, não como fonte de
    //      energia. É a única entrada de laranja aqui, e ela fica ATRÁS do triângulo.
    const gq=ctx.createRadialGradient(0,0,0,0,0,R(22));
    gq.addColorStop(0,`rgba(255,214,150,${(0.34*pulse).toFixed(3)})`);
    gq.addColorStop(.45,`rgba(255,150,70,${(0.15*pulse).toFixed(3)})`);
    gq.addColorStop(1,'rgba(255,130,50,0)');
    ctx.fillStyle=gq;ctx.beginPath();ctx.arc(0,0,R(22),0,6.283);ctx.fill();

    // d · TRIÂNGULO — a silhueta que faz o objeto ser lido como REATOR e não como
    //     alvo de mira. Gira devagar no sentido contrário ao das bobinas.
    const pt=new Path2D(), aT=-Math.PI/2-spin*5;
    for(let k=0;k<3;k++){
      const a=aT+k*2.0944, x0=Math.cos(a)*R(15.5), y0=Math.sin(a)*R(15.5);
      k?pt.lineTo(x0,y0):pt.moveTo(x0,y0);
    }
    pt.closePath();
    ctx.lineJoin='round';
    ctx.lineWidth=Math.max(.8,R(1.9));
    ctx.strokeStyle=`rgba(214,238,255,${(0.52*pulse).toFixed(3)})`;ctx.stroke(pt);
    ctx.lineWidth=Math.max(1.4,R(5));
    ctx.strokeStyle=`rgba(120,190,255,${(0.13*pulse).toFixed(3)})`;ctx.stroke(pt);

    // e · FILAMENTOS — do núcleo até a base de cada bobina. Determinísticos (nada de
    //     Math.random: a casa proíbe gerador sintético) e modulados pelo mesmo pulso.
    if(!rm){
      const pf=new Path2D();
      for(let k=0;k<NB;k++){
        const a=(k+0.5)/NB*6.283+giroB;
        const v=0.55+0.45*Math.sin(t*0.0026+k*1.7);
        pf.moveTo(Math.cos(a)*R(7),Math.sin(a)*R(7));
        pf.lineTo(Math.cos(a)*R(7+15*v),Math.sin(a)*R(7+15*v));
      }
      ctx.lineWidth=Math.max(.5,R(0.9));
      ctx.strokeStyle=`rgba(226,244,255,${(0.30*pulse).toFixed(3)})`;ctx.stroke(pf);
    }

    // f · GRADUAÇÃO — 72 ticks, cardeais mais longos. Dois traços, não 72.
    if(!rm){
      const gir=spin*7, pc=new Path2D(), pn=new Path2D();
      for(let k=0;k<72;k++){
        const a=k/72*6.283+gir, card=k%18===0, len=(card?6:(k%6===0?4:2.4))*RR;
        const c0=Math.cos(a), s0=Math.sin(a);
        (card?pc:pn).moveTo(c0*R(46),s0*R(46));
        (card?pc:pn).lineTo(c0*(R(46)+len),s0*(R(46)+len));
      }
      ctx.lineWidth=Math.max(.4,R(0.7));
      ctx.strokeStyle=`rgba(150,200,255,${(0.16*pulse).toFixed(3)})`;ctx.stroke(pn);
      ctx.lineWidth=Math.max(.7,R(1.3));
      ctx.strokeStyle=`rgba(180,220,255,${(0.40*pulse).toFixed(3)})`;ctx.stroke(pc);
    }
    ctx.restore();
    const cr=38*pulse*heart.k*Math.min(1.4,cam.s/240);
    const cg=ctx.createRadialGradient(heart.x,heart.y,0,heart.x,heart.y,cr);
    cg.addColorStop(0,'rgba(255,244,226,1)');cg.addColorStop(.16,'rgba(255,192,120,.92)');
    cg.addColorStop(.40,'rgba(150,220,255,.70)');cg.addColorStop(.7,'rgba(120,150,255,.22)');
    cg.addColorStop(1,'rgba(120,140,255,0)');
    ctx.fillStyle=cg;ctx.beginPath();ctx.arc(heart.x,heart.y,cr,0,6.283);ctx.fill();
    ctx.fillStyle='rgba(255,255,255,'+(0.9*pulse).toFixed(2)+')';
    ctx.beginPath();ctx.arc(heart.x,heart.y,3.4,0,6.283);ctx.fill();
    };
    /* a fila única: cada nó com a sua profundidade, o projetor com a do centro */
    pos.map(o=>({z:o.z,f:()=>desenhaNo(o)}))
       .concat([{z:cam.camd,f:desenhaProjetor}])
       .sort((a,b)=>b.z-a.z).forEach(it=>it.f());
    /* 9 · evento real = onda de choque percorrendo o PISO (não um círculo na tela) */
    _nuPulses=_nuPulses.filter(p=>p.a>.02);
    _nuPulses.forEach(p=>{p.r+=0.019;p.a*=.965;
      ctx.strokeStyle=`rgba(${p.c},${p.a.toFixed(3)})`;ctx.lineWidth=1.5;
      ctx.beginPath();
      for(let i=0;i<=48;i++){const th=i/48*6.283,q=P(Math.cos(th)*p.r,ESP+0.008,Math.sin(th)*p.r);
        i?ctx.lineTo(q.x,q.y):ctx.moveTo(q.x,q.y);}
      ctx.stroke();});
    /* 10 · MIRA no nó sob o cursor: o domínio é um alvo travável */
    if(_nuHover){const o=pos.find(q=>q.n.id===_nuHover);
      if(o){
        ctx.strokeStyle=o.n.cor+'cc';ctx.lineWidth=1.2;
        ctx.beginPath();ctx.arc(o.x,o.y,16*o.k,0,6.283);ctx.stroke();
        ctx.strokeStyle=o.n.cor+'55';ctx.setLineDash([4,5]);
        ctx.beginPath();ctx.arc(o.x,o.y,23*o.k,0,6.283);ctx.stroke();ctx.setLineDash([]);
      }}
    /* 11 · LINHAS-GUIA — o trilho fica parado; o que se move é a linha até o nó.
       Cotovelo curto na saída do rótulo (leitura de chamada técnica) e reta até o
       objeto. Sem elas o trilho seria uma legenda solta; com elas, o número na
       lateral e o ponto de luz na mesa são a MESMA coisa. */
    pos.forEach(o=>{
      const n=o.n, el=$('nu-'+n.id), viva=_nuHover===n.id;
      if(el)el.classList.toggle('viva',viva);
      if(_compacto||n._lx==null)return;
      /* conector CURTO: o rótulo já está junto do nó, então basta o traço que diz
         "esta etiqueta é DESTE ponto". Linha longa cruzando a mesa era ruído. */
      ctx.strokeStyle=n.cor+(viva?'bb':'3a');
      ctx.lineWidth=viva?1.4:0.9;
      ctx.beginPath();ctx.moveTo(n._lx,n._ly);ctx.lineTo(o.x,o.y);ctx.stroke();
    });
    if(!rm)_nuRAF=requestAnimationFrame(draw);
  }
  cancelAnimationFrame(_nuRAF);if(!rm)draw(performance.now());
  // qual sweep alimenta o sistema — pinga já e a cada 15s enquanto o núcleo vive
  nuSweepPoll();clearInterval(_swInt);
  _swInt=setInterval(()=>{cv.isConnected?nuSweepPoll():clearInterval(_swInt);},15000);
}
function ckCard(id,lab,valc,dotc,href,spark){return `<div class="ck-inst" id="cki-${id}" onclick="ir('${href}')">
  <div class="k"><span class="lab">${lab}</span><span class="dot ${dotc}"></span></div>
  <div class="val ${valc}">—</div><div class="meta esperando">lendo o barramento — o número aparece aqui</div>
  </div>`;}
function ckFill(id,{num,txt,meta}={}){const el=$('cki-'+id);if(!el)return;const v=el.querySelector('.val'),m=el.querySelector('.meta');
  if(num!=null&&isFinite(num))_ckCount(v,num,x=>fmtN(Math.round(x)));else if(txt!=null)v.textContent=txt;
  if(meta!=null){m.innerHTML=meta;m.classList.remove("esperando");}
  nuSet(id,num!=null&&isFinite(num)?Math.round(num):txt);   // espelha no Núcleo orbital
}
let _ckTick=[];
function ckPush(items){items.forEach(x=>_ckTick.push(x));const L=$('ck-lane');if(L&&_ckTick.length)L.innerHTML=_ckTick.concat(_ckTick).map(x=>`<span class="${x.c||''}">${x.h}</span>`).join('');}
function ckBoot(){
  const g=$('ck-grid');if(!g)return;
  g.innerHTML=[ckCard('radar','Radar de risco','','bgteal','g_radar'),
    ckCard('com','Comunidades','','bgteal','g_comun'),
    ckCard('dossie','Caro + suspeito','ckrose','bgrose','e_comp'),
    ckCard('lift','Melhor detector (lift)','','bgteal','g_retro'),
    ckCard('fenix','Pago a empresa morta','ckrose','bgrose','g_fenix'),
    ckCard('compras','Compras auditáveis','','bgteal','e_comp'),
    ckCard('orgao','Órgão que mais economiza','ckgood','bgteal','e_comp'),
    ckCard('ninho','Ninhos de fachada','ckamber','bgamber','g_riscos')].join('');
  a11yfy(g);   // ck-grid é preenchido após o a11yfy do ir() → operar os cards por teclado aqui
  nucleoStart();
  ckPull(true);
  clearInterval(_ckTimer);_ckTimer=setInterval(()=>{if(!document.hidden&&aba==='i_cockpit')ckPull(false);},30000);
}
function ckPull(first){
  _ckTick=[];
  J('/api/compliance/painel').then(d=>{const n=(d&&d.lista_alertas||[]).length;
    if(n)nuSet('alertas',n);});
  if(first)J('/api/intel/ninho_sala?limite=60').then(d=>{
    /* Falhar em SILÊNCIO deixava o card em "—" — indistinguível de "não há ninho".
       Silêncio ≠ INDISPONÍVEL: se a rota não respondeu, o card diz isso. */
    if(!d||!d.ok){ckFill('ninho',{txt:'—',meta:erroHumano(d&&d.erro)});return;}
    /* Passou a ser MESMA SALA (endereço + complemento), não mesmo prédio: 'Rua da
       Assembleia 10' tem 318 CNPJs e é edifício comercial. E o grau vem do ACÚMULO de
       fatores — 2+ recebendo, maioria baixada, abertura em lote, telefone comum —,
       nunca de um sinal só. Por isso o número é menor: ele agora sustenta o que diz. */
    const gs=(d.grupos||[]),altos=gs.filter(g=>g.grau==='alto');
    ckFill('ninho',{num:altos.length,
      meta:`grupos na <b>MESMA SALA</b> com 2+ CNPJs recebendo e <b>3+ fatores</b> de fachada`
           +(gs.length>altos.length?` · outros ${fmtN(gs.length-altos.length)} com menos fatores`:'')
           +` — <b>${fmtRc(d.total_recebido_ob||0)}</b> em OB no conjunto`});
    ckPush(altos.slice(0,3).map(g=>({c:'a',h:`◉ mesma sala — <b>${fmtN(g.n_recebem_ob)} de ${fmtN(g.n_cnpjs)} CNPJs recebem</b> · ${esc((g.fatores||[])[1]||'')} · ${fmtRc(g.total_recebido_ob)}`})));});
  J('/api/comparador/economia').then(d=>{if(!d||!d.ok){
      // herói nunca fica preso no placeholder: erro vira mensagem humana + retry
      const big=$('ck-econ');if(big&&/—/.test(big.textContent)){big.textContent='—';
        if($('ck-sub'))$('ck-sub').innerHTML=erroHumano(d&&d.erro);}
      return;}
    // A manchete passa a ser a economia HOMOGÊNEA — a que se apoia em comparação de
    // produto igual. Medido em 25/07/2026: dos R$ 15,6 mi, R$ 9,4 mi (60,4%) vinham de
    // grupos cuja descrição do PNCP mistura produtos diferentes ('Locação de Veículos -
    // Leves / Pesados', dispersão 300,9×; 'peça de veículo', onde parafuso e motor têm a
    // mesma descrição, 1292,5×). O total não some: vira o teto da faixa, ao lado.
    const _eco=(d.economia_homogenea!=null?d.economia_homogenea:d.economia_total);
    const _nc =(d.n_compras_homogeneas!=null?d.n_compras_homogeneas:d.n_compras_acima_mediana);
    _ckCount($('ck-econ'),_eco,fmtRc,first?1300:900);
    if($('ck-sub'))$('ck-sub').innerHTML=
      `Se cada uma das <b>${fmtN(_nc)}</b> compras acima da mediana tivesse pago a <b>mediana de mercado</b> do item`
      +(d.economia_descricao_generica>0
        ? ` — contando só itens de <b>descrição consistente</b>. Há mais <b>${fmtRc(d.economia_descricao_generica)}</b>`
          +` em itens de descrição genérica (ex.: "peça de veículo"), onde a mediana pode comparar produtos diferentes.`
        : `.`);
    ckFill('compras',{num:_nc,meta:'acima da mediana, em itens de descrição consistente'});
    const o=d.por_orgao&&d.por_orgao[0],onm=o?(o.orgao||''):'';
    // o valor grande é a caixa do NÚMERO: um nome de órgão cortado duas vezes (25 chars
    // no JS + reticências do CSS a 26px) virava "PREFEITURA …", que não informa nada.
    // O número é a economia; o nome do órgão vive inteiro na linha de baixo.
    ckFill('orgao',{txt:o?fmtRc(o.economia):'—',meta:o?`<b>${esc(onm)}</b> — potencial a recuperar`:'—'});
    // economia_total (15,6 mi/337) compara produtos DIFERENTES sob rótulo genérico — o herói
    // desta mesma tela já publica a homogênea (6,2 mi/106). O ticker ficou com o número velho:
    // duas manchetes contraditórias a 30px uma da outra. Uma fonte só, a defensável.
    ckPush([{c:'g',h:`✦ economia potencial <b>${fmtRc(d.economia_homogenea)}</b> em ${fmtN(d.n_compras_homogeneas)} compras`}]);});
  J('/api/comparador/vedada').then(d=>{if(d&&d.ok&&d.economia_vedada_total){const b=$('ck-vedbox');if(b)b.hidden=false;_ckCount($('ck-ved'),d.economia_vedada_total,fmtRc);}});
  J('/api/intel/radar?limite=6').then(d=>{if(!d||!d.ok)return;ckFill('radar',{num:d.n,meta:`fornecedores com sinal · <b class="ckrose">${fmtN(d.n_vermelho)}</b> em nível crítico`});
    ckPush((d.achados||[]).slice(0,5).map(a=>({c:'',h:`▸ RADAR ${a.score} — <b>${(a.nome||'').slice(0,30)}</b> · ${(a.sinais||[]).map(s=>rot(s.sinal)).slice(0,2).join(', ')}`})));});
  J('/api/intel/comunidades').then(d=>{if(!d||!d.ok)return;ckFill('com',{num:d.n,meta:'clusters família-empresa-órgão (Louvain)'});});
  J('/api/intel/lift').then(d=>{if(!d||!d.ok)return;const b=(d.detectores||[]).filter(x=>!x.circular).sort((a,c)=>(c.lift||0)-(a.lift||0))[0];
    ckFill('lift',{txt:b?b.lift+'×':'—',meta:b?`<b>${rot(b.detector)}</b> concentra fraude ${b.lift}× acima da base`:'—'});});
  J('/api/comparador/dossie').then(d=>{if(!d||!d.ok)return;ckFill('dossie',{num:d.n,meta:'itens pagos caro a fornecedor sancionado/fantasma'});
    ckPush((d.achados||[]).slice(0,6).map(a=>({c:'a',h:`◉ ${(a.orgao||'').slice(0,24)} pagou <b>${a.vs_mediana}× a mediana</b> — ${(a.fornecedor||'').slice(0,24)} (sancionada)`})));});
  J('/api/intel/fenix').then(d=>{if(!d||!d.ok)return;
    // "Pago a empresa MORTA" só vale para quem recebeu DEPOIS da baixa. O card mostrava
    // `total_defunta` — o conjunto AMPLO de "hoje está baixada e um dia recebeu" — e dizia
    // R$ 4 bi. Medido: só R$ 18,3 mi (54 empresas) foram pagos APÓS a baixa; os outros
    // R$ 2,56 bi são pagamentos anteriores à morte, que não têm nada de irregular (a Cruz
    // Vermelha, baixada em 2005, sozinha respondia por R$ 305 mi). O número da manchete
    // passa a ser o confirmado; o amplo vira contexto na linha de baixo, sem sumir.
    ckFill('fenix',{txt:fmtRc(d.total_apos_baixa||0),
      meta:`<b>${fmtN(d.n_defunta_confirmada||0)}</b> empresas receberam <b>depois</b> da baixa na Receita`
           +` · outras ${fmtN((d.n_defunta||0)-(d.n_defunta_confirmada||0))} estão baixadas hoje mas só receberam antes`});
    if(d.n_defunta_confirmada)ckPush([{c:'a',h:`◉ <b>${fmtRc(d.total_apos_baixa)}</b> pagos a ${fmtN(d.n_defunta_confirmada)} empresas DEPOIS da baixa na Receita`}]);});
  J('/api/fontes/frescor').then(d=>{const box=$('ck-fontes');if(!box||!d||!d.fontes)return;
    const cor=f=>{const s=(f.estado||'').toLowerCase();if(s.includes('verde')||s.includes('ok')||s.includes('fresc'))return '#5fe0a1';
      if(s.includes('amar')||s.includes('aten')||s.includes('velh'))return '#f2b544';if(s.includes('verm')||s.includes('erro')||s.includes('crit'))return '#ff7a8a';
      return f.idade_dias==null?'#63718f':(f.idade_dias<=2?'#5fe0a1':(f.idade_dias<=10?'#f2b544':'#ff7a8a'));};
    box.innerHTML=`<div class="ck-flabel">Fontes de dados — frescor ao vivo</div><div class="ck-fgrid">`+
      d.fontes.map(f=>`<div class="ck-fchip" title="${esc(f.detalhe||'')}"><span class="fled" style="background:${cor(f)}"></span>
        <span class="fnm">${esc((f.fonte||'').replace(/·/g,'·'))}</span><span class="fage">${f.idade_dias==null?'—':f.idade_dias+'d'}</span></div>`).join('')+`</div>`;});
}

(async()=>{montarSpheres();montarTabs();netbgStart();rjbgStart();await ir('i_cockpit');marcarValores(document.getElementById('view'));
  const st=await J('/status');
  if(st.exercicio){
    /* v27: estado do SIAFE era um dingbat. Medido: nenhuma das tres fontes
       embarcadas tem U+2717, e U+2713 a 10px le como a letra "v". Estado de
       sistema e SINAL, nao caractere — e sinal nao depende de fonte. */
    const hs=$('hsub'); hs.textContent='';
    hs.append('CENTRAL DE INTELIGÊNCIA · SIAFE ');
    const pt=document.createElement('i');
    pt.className='sinal '+(st.logged_in?'ok':'off');
    pt.title=st.logged_in?'SIAFE conectado':'SIAFE sem sessão';
    pt.setAttribute('role','img');
    pt.setAttribute('aria-label',pt.title);
    hs.append(pt,' · '+st.exercicio);
  }})();

/* ── SABRE: motor do Conduíte + Kyber core + holofeed ─────────────────────────
   Assina /api/eventos/stream (SSE). Cada evento REAL vira: (a) pulso de plasma
   viajando na lâmina, (b) linha no holofeed. O pulso de 4s do backend rege a cor
   da lâmina (estado) e o arco do Kyber (carga da VM). Se o SSE cair, o EventSource
   reconecta sozinho; o badge diz a verdade ("reconectando"), e o painel segue no
   polling de 30s que sempre existiu — tempo real é elevação, não dependência. */
/* v45: declarado no TOPO — ver comentario da declaracao. */

/* v37: NEBULOSA VIVA — o fundo da esfera deixa de ser foto parada quando o
   loop de video existe em /static/assets/<nome>.mp4. Encaixe progressivo:
   o JPG segue por baixo como poster; se o arquivo nao existe (HEAD != 200),
   nada muda — os loops encomendados ao it-campo acendem sozinhos ao chegar.
   portal-hero.mp4 ja existe: o inicio acende hoje. */
/* v45: _nebVid vive no TOPO (mesmo TDZ do _redMotion). */
async function nebulaViva(){
  const mapa={estado:'nebula-estado',prefeitura:'nebula-prefeitura',
              geral:'nebula-transversal',inicio:'portal-hero'};
  const nome=mapa[esfera],host=$('esfnebula');
  if(!nome||!host||_redMotion)return;
  const url='/static/assets/'+nome+'.mp4';
  if(_nebVid[nome]===undefined){
    try{_nebVid[nome]=(await fetch(url,{method:'HEAD'})).ok}
    catch(e){_nebVid[nome]=false}}
  let v=host.querySelector('video');
  if(!_nebVid[nome]){if(v)v.classList.remove('on');return;}
  if(!v){v=document.createElement('video');
    v.muted=true;v.loop=true;v.playsInline=true;v.autoplay=true;
    v.setAttribute('aria-hidden','true');
    /* .on so quando ha QUADRO de verdade — play() que resolve sem codec
       (Chromium sem H.264) deixaria o veu ligado sobre video preto. */
    v.addEventListener('playing',()=>v.classList.add('on'));
    host.appendChild(v);}
  if(v.dataset.neb!==nome){v.classList.remove('on');v.dataset.neb=nome;
    /* v41.1: webm primeiro (harness sem H.264), mp4 como caminho canonico */
    v.innerHTML='<source src="'+url.replace('.mp4','.webm')+'" type="video/webm">'
               +'<source src="'+url+'" type="video/mp4">';
    v.load();}
  v.play().catch(()=>{});
}
/* v38: se o corpo do no (anel usinado) ja chegou do it-campo, liga a camada.
   Checagem unica no boot — 404 hoje significa "segue procedural", sem erro. */
fetch('/static/assets/no-energia.png',{method:'HEAD'})
  .then(r=>{if(r.ok)document.body.classList.add('art-no')}).catch(()=>{});
const _saberCor={ok:'var(--teal)',carga:'var(--amber)',critico:'var(--rose)'};
let _hfN=0;
function hfToggle(){$('holofeed').classList.toggle('open');}
const _EV_COR={ob_siafe:'var(--gold)',ob_tfe:'var(--gold)',alerta:'var(--rose)',radar:'var(--rose)',
  clausula:'var(--violet)',pericia:'var(--green)',ata:'var(--blue)',sei_doc:'var(--teal)'};
function _hfAdd(ev,crit){
  const ul=$('hflist');if(!ul)return;
  $('hfvazio').style.display='none';
  const li=document.createElement('li');if(crit)li.className='crit';
  li.style.setProperty('--evc',_EV_COR[ev.tipo]||'var(--saber)');
  li.innerHTML=`<span class="t">${esc(ev.t||'')}</span><span class="d">${ev.delta>1?'×'+fmtN(ev.delta):'◈'}</span><span>${esc(ev.rotulo||ev.tipo)}</span>`;
  ul.prepend(li);
  while(ul.children.length>10)ul.lastChild.remove();
  _hfN++;
}
function _pulso(ev,crit){
  if(_redMotion)return;
  const c=$('conduit');if(!c)return;
  const p=document.createElement('span');p.className='cpulse'+(crit?' crit':'');
  p.addEventListener('animationend',()=>p.remove());c.appendChild(p);
  if(ev.rotulo){const l=document.createElement('span');l.className='clabel';
    l.textContent=(ev.delta>1?ev.delta+'× ':'')+ev.rotulo;
    l.addEventListener('animationend',()=>l.remove());c.appendChild(l);}
}
function _kyber(load1,sweeps,mem){
  const arc=$('karc');if(!arc)return;
  const frac=Math.min(1,(load1||0)/5);          // 2 vCPU: load 5 = teto crítico do arco
  arc.style.strokeDashoffset=(72.3*(1-frac)).toFixed(1);
  $('kyber').classList.toggle('sweep',!!(sweeps&&(sweeps.sei||sweeps.siafe)));
  $('hfload').textContent='load '+(load1==null?'—':load1.toFixed(2))+(mem!=null?' · ram '+mem+'%':'');
}
function sabreStart(){
  if(!window.EventSource)return;               // navegador antigo: polling de sempre
  const es=new EventSource('/api/eventos/stream');
  es.onopen=()=>{$('livetxt').textContent='ao vivo';};
  es.onerror=()=>{$('livetxt').textContent='reconectando…';};
  es.onmessage=m=>{
    let ev;try{ev=JSON.parse(m.data);}catch(_){return;}
    if(ev.tipo==='pulse'){
      document.documentElement.style.setProperty('--saber',_saberCor[ev.estado]||_saberCor.ok);
      _kyber(ev.load1,ev.sweeps,ev.mem);
      return;                                   // batimento não polui o feed nem pulsa a lâmina
    }
    const crit=(ev.tipo==='alerta'||ev.tipo==='radar');
    _pulso(ev,crit);_hfAdd(ev,crit);nucleoPulse(ev.tipo);
  };
}
sabreStart();

/* ═══ v9 "ÍON" — 3D em todo controle + PORTAL DE IGNIÇÃO ══════════════════ */

/* ── 3D universal nos controles ───────────────────────────────────────────
   UM listener delegado no documento alimenta --rx/--ry (inclinação na direção
   do cursor) e --mx/--my (specular). 300+ botões não podem virar 300 listeners:
   o custo é O(1) e só existe enquanto o cursor está sobre um controle.
   Card/lnk/ck-inst ficam de fora — já têm o motor de tilt do v7 (em px).   */
const _I3D='.btn,.chip,.sph,nav.tabs button,.htop a,.search .az,.sheet .x,.nu-chip,.cover-seal';
let _i3dEl=null;
function _i3dClear(){if(!_i3dEl)return;const e=_i3dEl;
  ['--rx','--ry','--mx','--my'].forEach(p=>e.style.removeProperty(p));_i3dEl=null;}
/* v49 — DOIS CUSTOS REAIS, MEDIDOS (e uma hipótese minha que o código refutou).
   O que eu supunha: que este handler escrevia transform em 300+ controles. FALSO — ele toca UM
   elemento por vez (`_i3dEl`), e o comentário acima já explicava isso. O custo verdadeiro é outro:
     (a) `getBoundingClientRect()` a CADA evento de pointermove = leitura de layout forçada, dezenas
         de vezes por segundo. Num painel medido a 1-2 FPS, é o pior lugar possível para gastar.
         Agora o retângulo é cacheado enquanto o cursor não troca de elemento (e invalidado em
         scroll/resize, que são as únicas coisas que o movem).
     (b) as escritas eram síncronas ao evento. Agora são coalescidas em UM quadro por rAF: o mouse
         pode disparar 10 eventos entre dois quadros e só o último importa — os 9 anteriores nunca
         chegariam à tela de qualquer forma.
   Amplitude: para `nav.tabs button` o teto caiu de 15° para 9°. Numa aba estreita de ~60px a
   fórmula dava ±17° de rotateY, e é isso que faz a barra "sambar" quando o cursor a atravessa. */
if(!_redMotion){
  let _i3dRect=null,_i3dEv=null,_i3dRaf=0;
  const _i3dInvalida=()=>{_i3dRect=null;};
  addEventListener('scroll',_i3dInvalida,{passive:true});
  addEventListener('resize',_i3dInvalida,{passive:true});
  const _i3dPinta=()=>{
    _i3dRaf=0;
    const ev=_i3dEv;if(!ev)return;
    const el=_i3dEl;if(!el)return;
    if(!_i3dRect){_i3dRect=el.getBoundingClientRect();}
    const r=_i3dRect;if(!r.width||!r.height)return;
    const px=(ev.x-r.left)/r.width,py=(ev.y-r.top)/r.height;
    el.style.setProperty('--mx',(px*100).toFixed(1)+'%');
    el.style.setProperty('--my',(py*100).toFixed(1)+'%');
    // controle estreito tomba mais que controle largo — senão a barra de abas ondula
    const teto=el.matches('nav.tabs button')?9:15;
    const amp=Math.max(6,Math.min(teto,520/Math.max(r.width,60)));
    el.style.setProperty('--ry',((px-.5)*amp*2).toFixed(2)+'deg');
    el.style.setProperty('--rx',((py-.5)*-amp*1.35).toFixed(2)+'deg');
  };
  addEventListener('pointermove',ev=>{
    if(ev.pointerType==='touch')return;
    const el=ev.target&&ev.target.closest?ev.target.closest(_I3D):null;
    if(el!==_i3dEl){_i3dClear();_i3dRect=null;}
    if(!el)return;
    _i3dEl=el;_i3dEv={x:ev.clientX,y:ev.clientY};
    if(!_i3dRaf)_i3dRaf=requestAnimationFrame(_i3dPinta);
  },{passive:true});
  addEventListener('blur',_i3dClear);
  document.addEventListener('pointerleave',_i3dClear,{passive:true});
}

/* ── PORTAL DE IGNIÇÃO ────────────────────────────────────────────────────
   Cena WebGL de passe único (fragment shader num triângulo de tela cheia):
   campo de estrelas com rastro radial no salto, reator de anéis de íon com
   núcleo laranja incandescente, varredura de guardião. Por cima, em Canvas2D,
   a malha REAL do Estado do RJ (IBGE) sendo revelada pela varredura.

   Por que shader e NÃO Three.js: 0 KB de dependência, tudo roda na GPU — a VM
   tem 2 vCPU e não pode gastar CPU com cenografia. Sem contexto WebGL, o
   portal degrada sozinho (fica só o texto sobre fundo escuro) e ninguém vê erro.

   Regra de produto: NÃO é sequência de load obrigatória. Toca 1× por sessão,
   por cima do painel que já está buscando dado atrás, e qualquer toque pula. */
const _PORTAL_VS='attribute vec2 a;void main(){gl_Position=vec4(a,0.0,1.0);}';
const _PORTAL_FS=`precision highp float;
uniform vec2 u_res;uniform float u_t,u_ign,u_jump;uniform vec2 u_m;
float h21(vec2 p){p=fract(p*vec2(127.31,311.7));p+=dot(p,p+34.23);return fract(p.x*p.y);}
float stars(vec2 p,float sc,float th){
  vec2 q=p*sc;vec2 id=floor(q);vec2 f=fract(q)-0.5;
  float r=h21(id+sc);
  if(r<th)return 0.0;
  vec2 o=(vec2(h21(id+3.7),h21(id+9.1))-0.5)*0.70;
  return smoothstep(0.055,0.0,length(f-o))*(0.25+(r-th)/(1.0-th)*0.85);
}
void main(){
  vec2 p=(gl_FragCoord.xy-0.5*u_res)/u_res.y+u_m*0.045;
  float r=length(p);
  /* reator sobe 9% da altura: fica no MESMO centro do território (faixa
     superior de 82%) e sai de cima da fala, que vive no terço inferior. */
  vec2 pr=p-vec2(0.0,0.09);
  float rr=length(pr),a=atan(pr.y,pr.x);
  vec3 col=vec3(0.0);
  /* estrelas PEQUENAS e esparsas: o espaço tem que ser preto, não azul lavado.
     Acumular ao longo do raio dá o rastro de verdade no salto.              */
  float sf=0.0;
  for(int i=0;i<5;i++){
    float t=float(i)/4.0;float k=1.0-u_jump*0.55*t;
    sf+=(stars(p*k,15.0,0.905)+stars(p*k,27.0,0.935)*0.45)*(1.0-t*0.8);
  }
  col+=mix(vec3(0.55,0.72,1.05),vec3(1.0,0.72,0.38),0.16+0.5*u_jump)*sf*0.7;
  /* reator: anéis de íon + segmentos girando (compacto — o herói é o território) */
  float ig=max(u_ign,0.0001);
  float R=smoothstep(0.010,0.0,abs(rr-0.112*ig))*1.05
         +smoothstep(0.0050,0.0,abs(rr-0.168*ig))*0.68
         +smoothstep(0.0026,0.0,abs(rr-0.218*ig))*0.44;
  R+=smoothstep(0.008,0.0,abs(rr-0.168*ig))*step(0.45,fract((a/6.28318)*26.0+u_t*0.22))*0.6;
  col+=vec3(0.30,0.62,1.30)*R*ig;
  /* núcleo incandescente + bloom contido */
  col+=vec3(1.30,0.56,0.16)*exp(-rr*rr*(230.0/ig))*ig*1.15;
  col+=vec3(1.00,0.46,0.13)*exp(-rr*8.5)*ig*0.13;
  /* varredura do guardião */
  col+=vec3(0.34,0.70,1.30)*pow(1.0-fract((a+3.14159)/6.28318-u_t*0.40),26.0)
       *smoothstep(0.85,0.05,rr)*ig*0.38;
  /* clarão do salto: quente e CONTIDO no centro (não lava o campo inteiro —
     esse foi o erro da 1ª volta, o flash azul apagava o espaço). */
  col+=mix(vec3(0.5,0.7,1.15),vec3(1.15,0.7,0.35),0.5)*u_jump*u_jump
       *smoothstep(0.9,0.0,r)*0.32;
  col*=1.0-0.82*smoothstep(0.20,1.05,r);
  /* alpha = luminância: espaço vazio fica TRANSPARENTE (mostra a nebulosa de
     fundo), reator/estrelas/território ficam opacos por cima. */
  float a=clamp(max(col.r,max(col.g,col.b))*1.25+0.12,0.0,1.0);
  gl_FragColor=vec4(col,a);
}`;

/* desenha a malha do RJ UMA vez num canvas fora de tela; a animação depois é
   só máscara + composite (2 operações por quadro), não re-traçado.          */
/* carrega a malha do RJ sob demanda (21 KB) e avisa quem pediu. Um só fetch
   serve o portal e o núcleo do cockpit.                                     */
// _rjCbs/_rjLoading declarados no topo do script (init os usa antes desta def).
function _rjCarregar(cb){
  if(window.RJ_MALHA){try{cb();}catch(_){}return;}
  _rjCbs.push(cb);
  if(_rjLoading)return;
  _rjLoading=true;
  const s=document.createElement('script');
  s.src='/static/assets/rj-malha.js';s.async=true;
  s.onload=()=>{const l=_rjCbs.slice();_rjCbs.length=0;
    /* era `catch(_){}` — um catch vazio. Se o desenho da malha falhasse, a
       falha sumia sem rastro e o mapa ficava vazio sem nada no console.  */
    l.forEach(fn=>{try{fn();}catch(e){console.warn('[rj] callback da malha falhou:',e);}});};
  s.onerror=()=>{_rjLoading=false;};             // sem malha o painel segue igual
  document.head.appendChild(s);
}

/* modo 'portal' = herói em tela cheia (faixa superior de 82%).
   modo 'nucleo' = pano de fundo discreto do cockpit: o dado lê primeiro. */
function _rjBuild(M,W,H,dpr,modo){
  const c=document.createElement('canvas');
  c.width=Math.round(W*dpr);c.height=Math.round(H*dpr);
  const x=c.getContext('2d');x.scale(dpr,dpr);
  const nu=modo==='nucleo';
  const FX=nu?0.94:0.88,FY=nu?0.96:0.82;
  const s=Math.min(W*FX/M.w,H*FY/M.h);
  const ox=(W-M.w*s)/2,oy=nu?(H-M.h*s)/2:(H*FY-M.h*s)/2;
  const mk=flat=>{const p=new Path2D();let X=flat[0],Y=flat[1];
    p.moveTo(ox+X/M.q*s,oy+Y/M.q*s);
    for(let i=2;i<flat.length;i+=2){X+=flat[i];Y+=flat[i+1];p.lineTo(ox+X/M.q*s,oy+Y/M.q*s);}
    p.closePath();return p;};
  // divisas municipais: a teia de 92 células que forma o estado
  x.lineJoin=x.lineCap='round';
  x.strokeStyle=nu?'rgba(120,170,245,0.16)':'rgba(126,178,250,0.52)';
  x.lineWidth=nu?0.55:0.75;
  M.m.forEach(f=>x.stroke(mk(f)));
  // contorno do estado: a fronteira sob vigília — halo de íon
  x.shadowColor='rgba(140,196,255,0.95)';x.shadowBlur=nu?9:18;
  x.strokeStyle=nu?'rgba(176,210,255,0.42)':'rgba(214,234,255,1)';
  x.lineWidth=nu?1.1:2.1;
  M.o.forEach(f=>x.stroke(mk(f)));
  // segundo passe quente: o litoral pega o calor do reator
  x.shadowBlur=nu?14:30;x.shadowColor='rgba(255,150,60,0.8)';
  x.strokeStyle=nu?'rgba(255,190,120,0.20)':'rgba(255,196,124,0.72)';
  x.lineWidth=nu?0.7:1.1;
  M.o.forEach(f=>x.stroke(mk(f)));
  return c;
}

function portalStart(){
  const el=$('portal');if(!el)return;
  let pular=false;
  try{pular=sessionStorage.getItem('jfn_v9_portal')==='1'||localStorage.getItem('jfn_portal_off')==='1';}catch(_){}
  if(pular||_redMotion){el.remove();return;}
  try{sessionStorage.setItem('jfn_v9_portal','1');}catch(_){}
  el.hidden=false;

  const cv=$('pcv'),pm=$('pmap');
  const dpr=Math.min(devicePixelRatio||1,1.5);   // 4K real na GPU da VM não paga o pixel
  let gl=null,U={},raf=0,morto=false,mapC=null,mx=0,my=0;
  const t0=performance.now(),IGN=[80,560],JUMP=[1320,1780],FIM=1960;   /* v27: era 3520+760=4,3s de espera. Medido no Chrome do dono a pagina
      carrega em 612ms — quem segurava a tela era a propria abertura. */

  try{gl=cv.getContext('webgl',{antialias:false,alpha:true,premultipliedAlpha:false})||cv.getContext('experimental-webgl');}catch(_){}
  if(gl)try{
    const sh=(tp,src)=>{const s=gl.createShader(tp);gl.shaderSource(s,src);gl.compileShader(s);
      if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s));return s;};
    const pr=gl.createProgram();
    gl.attachShader(pr,sh(gl.VERTEX_SHADER,_PORTAL_VS));
    gl.attachShader(pr,sh(gl.FRAGMENT_SHADER,_PORTAL_FS));
    gl.linkProgram(pr);
    if(!gl.getProgramParameter(pr,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(pr));
    gl.useProgram(pr);
    gl.bindBuffer(gl.ARRAY_BUFFER,gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),gl.STATIC_DRAW);
    const loc=gl.getAttribLocation(pr,'a');
    gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,2,gl.FLOAT,false,0,0);
    ['u_res','u_t','u_ign','u_jump','u_m'].forEach(n=>U[n]=gl.getUniformLocation(pr,n));
  }catch(_){gl=null;}                            // shader recusado → degrada, sem erro visível

  const mctx=pm.getContext('2d');
  function medir(){
    const W=innerWidth,H=innerHeight;
    if(gl){cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);gl.viewport(0,0,cv.width,cv.height);}
    pm.width=Math.round(W*dpr);pm.height=Math.round(H*dpr);mctx.setTransform(dpr,0,0,dpr,0,0);
    if(window.RJ_MALHA)mapC=_rjBuild(window.RJ_MALHA,W,H,dpr,'portal');
  }
  medir();
  addEventListener('resize',medir,{passive:true});
  addEventListener('pointermove',e=>{if(morto)return;
    mx=(e.clientX/innerWidth-.5)*2;my=-(e.clientY/innerHeight-.5)*2;},{passive:true});

  // a malha entra sob demanda: quem já viu o portal nesta sessão nunca baixa esses 21 KB
  _rjCarregar(()=>{if(!morto)medir();});

  function quadro(agora){
    if(morto)return;
    const t=agora-t0;
    const ign=Math.min(1,Math.max(0,(t-IGN[0])/(IGN[1]-IGN[0])));
    const jmp=Math.min(1,Math.max(0,(t-JUMP[0])/(JUMP[1]-JUMP[0])));
    if(gl){
      gl.uniform2f(U.u_res,cv.width,cv.height);
      gl.uniform1f(U.u_t,t/1000);
      gl.uniform1f(U.u_ign,ign*ign*(3-2*ign));    // smoothstep: ignição com inércia
      gl.uniform1f(U.u_jump,jmp*jmp);
      gl.uniform2f(U.u_m,mx,my);
      gl.drawArrays(gl.TRIANGLES,0,3);
    }
    // território: revelado por um disco que cresce junto com a varredura
    if(mapC){
      const W=innerWidth,H=innerHeight;
      const rev=Math.min(1,Math.max(0,(t-620)/1650));
      mctx.clearRect(0,0,W,H);
      if(rev>0){
        const cx=W/2,cy=H*0.41;                      // nasce no núcleo do reator
        const R=Math.max(1,rev*Math.hypot(W,H)*0.66);
        const g=mctx.createRadialGradient(cx,cy,0,cx,cy,R);
        g.addColorStop(0,'rgba(255,255,255,1)');
        g.addColorStop(.74,'rgba(255,255,255,1)');
        g.addColorStop(1,'rgba(255,255,255,0)');
        mctx.globalCompositeOperation='source-over';
        mctx.fillStyle=g;mctx.fillRect(0,0,W,H);
        mctx.globalCompositeOperation='source-in';
        mctx.globalAlpha=Math.min(1,rev*1.6)*(1-jmp*0.85);
        mctx.drawImage(mapC,0,0,W,H);
        mctx.globalAlpha=1;
      }
    }
    if(t>=FIM){portalFim();return;}
    raf=requestAnimationFrame(quadro);
  }
  raf=requestAnimationFrame(quadro);

  function portalFim(){
    if(morto)return;morto=true;cancelAnimationFrame(raf);
    // handoff: o núcleo encolhe até o Kyber do header — portal e painel são o
    // MESMO reator, não duas telas.
    /* v49 — A "BOLA DO NADA NO MEIO", parte 2 de 3. Este handoff era o proprio bug.
       Uma esfera de 190px nascia no CENTRO EXATO da tela, em opacidade cheia, e devia voar ate o
       Kyber do header. Tres defeitos somados:
         (a) a transicao dura 620ms e o `setTimeout(...,420)` arrancava o elemento do DOM aos 420ms:
             ela NUNCA chegava — desaparecia no meio do voo;
         (b) o `transform` era aplicado no rAF SEGUINTE. Medido nesta VM: o painel roda a 1-2 FPS,
             logo "o proximo quadro" pode levar meio segundo ou mais. Nesse intervalo a esfera fica
             PARADA no meio da tela, opaca. É literalmente uma bola do nada no meio;
         (c) no mesmo instante rodam `el.classList.add('off')` (opacity+blur na tela cheia) e um
             reflow forcado em `.cblade` — competindo pelo mesmo quadro que faltava.
       Agora: dois rAF encadeados garantem que o estado inicial foi para a tela antes de mudar
       (um rAF só não garante flush de estilo), a remocao segue o `transitionend` com rede de
       seguranca folgada, e em maquina medida como lenta o floreio é PULADO — a 1 FPS ele nao lê
       como movimento, lê como artefato. */
    const k=$('kyber'), lento=_redMotion||document.body.classList.contains('fps-baixo');
    if(k&&!lento){
      const kr=k.getBoundingClientRect(),S=190;
      const h=document.createElement('div');h.id='phand';
      h.style.cssText=`width:${S}px;height:${S}px;left:${innerWidth/2-S/2}px;top:${innerHeight/2-S/2}px`;
      document.body.appendChild(h);
      let saiu=false;
      const tirar=()=>{if(saiu)return;saiu=true;h.remove();};
      h.addEventListener('transitionend',tirar,{once:true});
      requestAnimationFrame(()=>requestAnimationFrame(()=>{
        h.style.transform=`translate(${kr.left+kr.width/2-innerWidth/2}px,`+
          `${kr.top+kr.height/2-innerHeight/2}px) scale(${(kr.width/S).toFixed(4)})`;
        h.style.opacity='0';}));
      setTimeout(tirar,900);   // > 620ms da transicao + folga p/ o quadro atrasado
    }
    el.classList.add('off');
    // a lâmina do Conduíte reacende: o portal entrega a energia ao painel
    const b=document.querySelector('.cblade');
    if(b){b.style.animation='none';void b.offsetWidth;
      b.style.animation='ignicao .5s cubic-bezier(.2,.9,.25,1.2) 1,respira 4.5s ease-in-out .5s infinite';}
    setTimeout(()=>{el.remove();
      if(gl){const x=gl.getExtension('WEBGL_lose_context');if(x)x.loseContext();}},420);
  }
  el.addEventListener('click',portalFim);
  addEventListener('keydown',portalFim);

  /* v28.3: a abertura media o tempo com performance.now() mas so AVANCAVA dentro
     do requestAnimationFrame. O Chrome congela rAF em aba de segundo plano — quem
     abria o painel e trocava de aba voltava e achava o portal ainda na tela (nao
     termina), e no instante em que a aba volta ao foco o rAF dispara com `t` ja
     muito alem de FIM: a cena corre todos os quadros de uma vez, que e o
     "rapidas e embaralhadas" que o dono viu.

     Duas travas, as duas independentes de quadro (portalFim ja e idempotente
     pela guarda `morto`, entao chamar duas vezes nao custa nada):
       1. um relogio de verdade fecha a abertura mesmo se nenhum quadro rodar;
       2. ao voltar de segundo plano, se o tempo ja passou, fecha SEM correr o
          atraso acumulado — melhor entregar o painel do que exibir a animacao
          em avanco rapido.                                                     */
  setTimeout(portalFim,FIM+90);
  /* v45: as aspas destes dois literais foram comidas pelo shell no patch que
     criou a trava (armadilha ja documentada: heredoc com aspas duplas por
     fora). O ReferenceError matava o RESTO do bloco do portal — o segundo
     guarda-corpo da abertura nunca existiu. */
  document.addEventListener('visibilitychange',()=>{
    if(document.visibilityState==='visible'&&performance.now()-t0>=FIM)portalFim();});
}
portalStart();

/* ══ v49 · MEDIR A MÁQUINA E RECUAR ═════════════════════════════════════════════════════════════
   Mede quadros por segundo com a página em repouso e, se a máquina não sustenta animação, liga
   `body.fps-baixo` — que desliga as 15 animações infinitas que animam `filter`, spread de
   `box-shadow` ou `background-position` (as que forçam repintura por quadro). Ver o bloco
   "MODO SÓBRIO MEDIDO" no CSS.

   POR QUE MEDIDO E NÃO ADIVINHADO. Sniff de user-agent, contagem de núcleos e `deviceMemory` erram
   feio (esta VM tem 11 GB e 2 vCPU sem GPU; um celular tem 8 núcleos e compõe melhor). O que
   importa é uma coisa só: esta máquina, agora, entrega quadro? Então conta quadro.

   Roda DEPOIS da intro (a intro é o pico de carga e mediria o transiente, não o regime), amostra
   1 s e não repete — medir de novo em loop seria gastar exatamente o que se quer economizar.
   `_redMotion` continua um eixo separado: preferência declarada do usuário, não capacidade. */
function _medirFps(){
  if(_redMotion)return;                       // quem já pediu menos movimento não precisa da medição
  let n=0;const t0=performance.now();
  const passo=()=>{n++;
    if(performance.now()-t0<1000){requestAnimationFrame(passo);return;}
    const fps=n*1000/(performance.now()-t0);
    window._jfnFps=Math.round(fps);
    if(fps<24){
      document.body.classList.add('fps-baixo');
      /* aviso VISÍVEL: degradação calada é como ninguém descobre que o painel não é o desenhado. */
      const alvo=document.querySelector('.htop')||document.querySelector('header');
      if(alvo&&!$('modo-sobrio')){
        const s=document.createElement('span');s.id='modo-sobrio';
        s.textContent='modo sóbrio · '+Math.round(fps)+' fps';
        s.title='Esta máquina entregou '+Math.round(fps)+' quadros por segundo com a tela parada.\n'
               +'As animações que exigem repintura por quadro foram desligadas para o painel ficar '
               +'legível. O dado e as funções são os mesmos.';
        alvo.appendChild(s);}
    }};
  requestAnimationFrame(passo);
}
/* 2,6 s = fim da intro (1,96 s) + folga para o primeiro render de conteúdo assentar. */
setTimeout(_medirFps,2600);

/* ═══════════ v10 "AGÊNCIA" — avisos da casa, erro humano, orçamento de vida ═══════════ */
// Erro de rede NUNCA chega cru ao usuário (era `TypeError: Failed to fetch` na tela).
function erroHumano(e){
  const s=String(e||'');
  let msg='Este dado não respondeu agora.';
  if(/failed to fetch|networkerror|load failed/i.test(s))msg='Sem resposta do servidor — a VM pode estar ocupada com um sweep.';
  else if(/timeout|timed out/i.test(s))msg='O servidor demorou demais para responder.';
  else if(/json|unexpected token/i.test(s))msg='O servidor respondeu em formato inesperado.';
  else if(s&&!/^indispon/i.test(s))msg=esc(s);   // mensagem de negócio vinda da API passa direto
  return `${msg} <button class="btn ghost v10retry" onclick="_jCache.clear();ir(aba)">↻ Tentar de novo</button>`;
}
// Toast e confirm com a cara do painel (alert/confirm nativos quebravam a imersão).
function jfnToast(msg,tipo){
  let box=$('v10toasts');if(!box){box=document.createElement('div');box.id='v10toasts';document.body.appendChild(box);}
  const t=document.createElement('div');t.className='v10toast '+(tipo||'');
  t.innerHTML=(tipo==='rose'?svgIco('§alert'):tipo==='green'?svgIco('§ok'):'')+`<span>${msg}</span>`;
  box.appendChild(t);requestAnimationFrame(()=>t.classList.add('on'));
  setTimeout(()=>{t.classList.remove('on');setTimeout(()=>t.remove(),250);},4600);
}
function jfnConfirm(msg,rotuloOk){
  return new Promise(res=>{
    const sh=$('sheet'),ov=$('ov');
    sh.innerHTML=`<div class="v10confirm"><div class="grab"></div><p>${msg}</p>
      <div class="btns"><button class="btn red" id="v10ok">${rotuloOk||'Confirmar'}</button>
      <button class="btn ghost" id="v10no">Cancelar</button></div></div>`;
    ov.classList.add('on');
    const fim=v=>{ov.classList.remove('on');ov.onclick=e=>{if(e.target===ov)fecharDossie();};res(v);};  // devolve o comportamento do dossiê
    $('v10ok').onclick=()=>fim(true);$('v10no').onclick=()=>fim(false);
    ov.onclick=e=>{if(e.target===ov)fim(false);};
  });
}
// Orçamento de vida: aba do navegador oculta → toda animação CSS pausa (os canvas já pausam).
document.addEventListener('visibilitychange',()=>document.documentElement.classList.toggle('rest',document.hidden));
// Esferas roláveis sem scrollbar: fade lateral só quando há conteúdo escondido.
function _sphMask(){const s=document.querySelector('.spheres');if(!s)return;
  s.classList.toggle('scrollx',s.scrollWidth>s.clientWidth+4&&s.scrollLeft<s.scrollWidth-s.clientWidth-4);}
addEventListener('resize',_sphMask);
document.addEventListener('scroll',e=>{if(e.target&&e.target.classList&&e.target.classList.contains('spheres'))_sphMask();},true);
setTimeout(_sphMask,600);

/* ── v27 TATO: a onda nasce onde o dedo tocou ────────────────────────────
   Um listener so, delegado no documento, em vez de um por controle: o painel
   troca o innerHTML de #view a cada aba, entao listener por elemento morreria
   junto com a aba. Delegacao sobrevive a troca.
   `pointerdown` e nao `click`: a resposta tem que sair no TOQUE, nao na
   soltura — 100ms de atraso ja le como travado.                            */
(function(){
  const ALVO='.btn,.chip,.tab,.lnk,.ck-inst,nav.tabs button,.sph,.htop a,.kpi';
  let ultima=0;
  addEventListener('pointerdown',ev=>{
    const agora=performance.now();
    if(agora-ultima<60)return;                       // teto: nao empilha onda
    const el=ev.target&&ev.target.closest&&ev.target.closest(ALVO);
    if(!el)return;
    if(matchMedia('(prefers-reduced-motion:reduce)').matches)return;
    ultima=agora;
    const r=el.getBoundingClientRect();
    const cs=getComputedStyle(el);
    if(cs.position==='static')el.style.position='relative';
    if(cs.overflow==='visible')el.style.overflow='hidden';
    const d=Math.max(r.width,r.height)*2.1;
    const o=document.createElement('span');
    o.className='onda';
    o.style.cssText='width:'+d+'px;height:'+d+'px;left:'+(ev.clientX-r.left)+'px;top:'+(ev.clientY-r.top)+'px';
    el.appendChild(o);
    setTimeout(()=>o.remove(),560);
  },{passive:true});

  /* linha de tabela e card: carimbo da esfera ao serem acionados */
  addEventListener('click',ev=>{
    const l=ev.target&&ev.target.closest&&ev.target.closest('tr,.card');
    if(!l||matchMedia('(prefers-reduced-motion:reduce)').matches)return;
    l.classList.remove('carimbo');void l.offsetWidth;l.classList.add('carimbo');
    setTimeout(()=>l.classList.remove('carimbo'),620);
  },{passive:true});
})();

/* ── v33: o numero que muda avisa. Um MutationObserver so, em #view, olhando
   characterData: quando o texto de um valor troca, a classe acende por 1,1s e
   sai sozinha. NAO observa childList — foi observar mutacao de no que derrubou
   a montagem do painel numa tentativa anterior desta sessao.                */
(function(){
  const v=document.getElementById('view');if(!v)return;
  if(matchMedia('(prefers-reduced-motion:reduce)').matches)return;
  new MutationObserver(ms=>{
    ms.forEach(m=>{
      const el=m.target.parentElement;
      if(!el||!el.matches)return;
      if(!el.matches('.num,.val,b'))return;
      el.classList.remove('mudou');void el.offsetWidth;el.classList.add('mudou');
      setTimeout(()=>el.classList.remove('mudou'),1150);
    });
  }).observe(v,{characterData:true,subtree:true});
})();

/* ── v34 MARCACAO AUTOMATICA DE VALOR ───────────────────────────────────────
   O numero e o assunto do painel, mas vinha renderizado como texto solto — sem
   marcacao, as regras de vida da v33 nao tinham onde pegar. Marcar a mao em
   cada funcao de render seria lento e quebraria na proxima aba nova.

   Esta passada roda depois de cada render e reconhece valor pelo FORMATO:
     R$ 6,2 mi · 2.193 · 15,9% · 2.15x · 54
   So marca no de TEXTO (sem filhos), entao nunca etiqueta um container inteiro,
   e ignora o que ja tem classe de valor. Custo: uma varredura de TreeWalker por
   troca de aba — em pericias, a aba mais pesada, sao ~750 nos.

   Nao usa MutationObserver: observar mutacao dentro de #view ja derrubou a
   montagem do painel uma vez nesta sessao.                                   */
function marcarValores(raiz){
  if(!raiz)raiz=document.getElementById('view');
  if(!raiz)return;
  /* R$ / milhar / decimal / percentual / multiplicador — com ou sem sufixo */
  const EH_VALOR=/^(R\$\s*)?-?\d{1,3}([.\s]\d{3})*(,\d+)?\s*(mi|bi|mil|%|x|×)?$/i;
  const it=document.createTreeWalker(raiz,NodeFilter.SHOW_ELEMENT,{
    acceptNode(e){
      if(e.children.length)return NodeFilter.FILTER_SKIP;      /* so folha */
      if(e.closest('nav,header,.ck-ticker'))return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    }});
  let e,n=0;
  while((e=it.nextNode())){
    if(e.classList.contains('num')||e.classList.contains('val'))continue;
    const t=(e.textContent||'').trim();
    if(t.length>18||t.length<1)continue;
    if(!EH_VALOR.test(t))continue;
    e.classList.add('num');n++;
    if(n>400)break;               /* teto: aba gigante nao paga varredura infinita */
  }
  /* severidade textual vira severidade marcada, para o ritmo poder ordenar a
     fila no canto do olho (a regra .sev da v33 faz o resto).                 */
  raiz.querySelectorAll('.tag,.chip,.badge,.pill').forEach(x=>{
    const t=(x.textContent||'').trim().toLowerCase();
    if(x.classList.contains('sev'))return;
    if(/^(grave|alta|alto|crítico|critico)$/.test(t))x.classList.add('sev','alta');
    else if(/^(m[ée]dia|m[ée]dio|aten[çc][ãa]o)$/.test(t))x.classList.add('sev','media');
  });
}
