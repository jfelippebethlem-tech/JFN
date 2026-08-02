/* A CAMADA DE INTERACAO — tudo que responde ao usuario e nao e dado.
 *
 * Acessibilidade (`a11yfy` torna qualquer `[onclick]` operavel por teclado), a holografia dos
 * numeros, o spotlight que segue o ponteiro, a malha viva entre os cards, o contador animado, o
 * glossario, o dossie com armadilha de foco, a arvore do SEI e a folha de certame.
 *
 * DUAS COISAS AQUI NAO SAO ENFEITE e nao podem sumir num corte futuro:
 *   `a11yfy` e o que faz o painel ser operavel sem mouse. O painel monta HTML com `onclick` em
 *   `<div>`, que o teclado nao alcanca; ela poe `tabindex`, `role` e o handler de Enter/Espaco.
 *   `_ovTecla` e a armadilha de foco do dossie. Sem ela o Tab sai do dialogo e passeia pela
 *   pagina atras dele — o leitor de tela le duas telas ao mesmo tempo.
 *
 * Sem efeito de topo: quem liga isto e a sequencia de boot do entrypoint.
 */
import {$, esc, corta, card, spin, clk, svgIco} from '../nucleo/dom.js';
import {fmtN, fmtD, fmtR, fmtRc, rot} from '../nucleo/formato.js';
import {J, _jCache, erroHumano} from '../nucleo/http.js';
import {_redMotion, _sobrio} from '../capacidade/estado.js';
import {esfera, aba} from '../app/estado.js';

export function a11yfy(root){
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
export function holografar(root){
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
/* Estes dois eram efeito de TOPO. O observador e o que faz a holografia valer para o painel
   INTEIRO e nao so para o que estava na tela no boot; o keydown e o que torna qualquer
   `[role=button][tabindex]` operavel por Enter e Espaco — sem ele metade do painel fica
   inalcancavel sem mouse. Viram funcao pelo mesmo motivo dos demais. */
export function uiLigarA11y(){
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
}

// ═══ SPOTLIGHT + TILT 3D — a luz E o plano seguem o cursor (1 listener global) ═══
const _rmGlobal=matchMedia('(prefers-reduced-motion:reduce)').matches;
/* v49: coalescido por quadro e com o retângulo em cache, pela mesma razão do handler de controles
   (ver `_I3D`, mais abaixo): `getBoundingClientRect()` por evento de mouse é leitura de layout
   forçada, e o painel foi medido a 1-2 FPS. Os dois handlers cobrem conjuntos DISJUNTOS de
   elementos — controles ali, cards aqui — de propósito; não são duplicados. */
let _spotEl=null,_spotRect=null,_spotEv=null,_spotRaf=0;
/* Os quatro ouvintes do spotlight eram efeito de TOPO. Efeito de topo em modulo roda na
   ordem do IMPORT, nao na do entrypoint — reordena o boot em silencio. Viram funcao; quem
   chama e a sequencia de boot, que e o unico lugar onde o boot acontece. */
export function _spotPinta(){
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

/* Os quatro ouvintes do spotlight eram efeito de TOPO. Efeito de topo em modulo roda na
   ordem do IMPORT, nao na do entrypoint — reordena o boot em silencio. Viram funcao; quem
   chama e a sequencia de boot, o unico lugar onde o boot acontece. */
export function uiLigarSpotlight(){
  addEventListener('scroll',()=>{_spotRect=null;},{passive:true});
  addEventListener('resize',()=>{_spotRect=null;},{passive:true});
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
}

// ═══ VIDA GLOBAL — o cockpit em toda aba (cascata · contagem · malha de luz) ═══
let _wireRAF=0;
export function vivo(){
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
export function _countUp(el){
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
export function _wire(nodes,rm){
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
export function glossario(){
  const ov=$('ov'),sh=$('sheet');ov.classList.add('on');
  sh.innerHTML=`<span class="x" onclick="fecharDossie()">✕ fechar</span><div class="grab"></div>
   <div style="font-weight:800;font-size:17px;margin-bottom:4px">ⓘ Entenda os termos</div>
   <div class="muted" style="font-size:13px;margin-bottom:14px">O que cada conceito do painel significa, em linguagem simples.</div>
   <div class="grid">`+TERMOS.map(([ic,t,d])=>card(`<div style="display:flex;gap:11px;align-items:flex-start"><span class="term-ico">${svgIco(ic)}</span><div><div style="font-weight:700">${t}</div><div class="muted" style="font-size:13px;margin-top:3px;line-height:1.55">${d}</div></div></div>`)).join('')+`</div>`;
  a11yfy(sh);
}

// ═══ DOSSIÊ modal ═══
export function fecharDossie(){$('ov').classList.remove('on');}

/* ═══ v54 — O #ov VIRA DIÁLOGO DE VERDADE ═════════════════════════════════════════
   Medido pelo it-campo: com o dossiê aberto, Esc não fechava (`#ov` seguia com
   class="ov on", display flex) e `document.activeElement` continuava sendo o gatilho
   LÁ FORA — quem navega por teclado ou leitor de tela abria uma folha em que não
   entrava. Faltavam ainda role/aria-modal e a trava de rolagem do fundo.
   POR QUE UM OBSERVER, e não seis edições: são ~6 pontos que abrem a folha
   (abrirDossie, glossario, certame, sei, o diálogo do 4251…) e todos fazem a MESMA
   coisa — `ov.classList.add('on')`. Observar a classe põe o comportamento de diálogo
   num lugar só; qualquer ponto novo que abrir a folha já nasce correto, em vez de
   herdar o defeito. O listener de teclado é de CAPTURA para chegar antes dos
   handlers dos componentes de dentro. */
let _ovGatilho=null;
const _ovFocaveis=r=>[...r.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select,textarea,[tabindex]:not([tabindex="-1"])')]
  .filter(e=>e.offsetWidth||e.offsetHeight||e.getClientRects().length);
export function _ovTecla(e){
  const ov=document.getElementById('ov');
  if(!ov||!ov.classList.contains('on'))return;
  if(e.key==='Escape'){e.preventDefault();e.stopPropagation();fecharDossie();return;}
  if(e.key!=='Tab')return;
  const f=_ovFocaveis(ov),sh=document.getElementById('sheet');
  if(!f.length){e.preventDefault();sh&&sh.focus();return;}
  const pri=f[0],ult=f[f.length-1],at=document.activeElement;
  if(!ov.contains(at)){e.preventDefault();(e.shiftKey?ult:pri).focus();}
  else if(e.shiftKey&&at===pri){e.preventDefault();ult.focus();}
  else if(!e.shiftKey&&at===ult){e.preventDefault();pri.focus();}
}
export function uiLigarDialogo(){
  const ov=document.getElementById('ov');if(!ov)return;
  ov.setAttribute('role','dialog');ov.setAttribute('aria-modal','true');
  ov.setAttribute('aria-label','Dossiê');
  document.addEventListener('keydown',_ovTecla,true);
  new MutationObserver(()=>{
    const on=ov.classList.contains('on');
    document.body.classList.toggle('ov-aberto',on);
    if(on){
      if(!_ovGatilho)_ovGatilho=document.activeElement;
      /* o miolo da folha chega depois (fetch): o foco vai para a própria folha, que é
         o container do diálogo, e o trap segura o resto quando o conteúdo pintar. */
      requestAnimationFrame(()=>{const sh=document.getElementById('sheet');
        if(!sh)return;sh.setAttribute('tabindex','-1');sh.focus();});
    }else{
      const g=_ovGatilho;_ovGatilho=null;
      if(g&&document.contains(g))try{g.focus()}catch(_){}
    }
  }).observe(ov,{attributes:true,attributeFilter:['class']});
}

/* v54 — CORTE POR PALAVRA. `esc(t).slice(0,n)` decepava no meio ("…do relatorio do o")
   e ainda podia partir uma entidade HTML ao meio (`&amp;` → `&am`). Corta no texto CRU,
   na última fronteira de palavra, e só então escapa. */

export async function abrirDossie(cnpj,nome){
  const dig=String(cnpj||'').replace(/\D/g,'');if(dig.length!==14)return;
  const ov=$('ov'),sh=$('sheet');ov.classList.add('on');
  sh.innerHTML=`<span class="x" onclick="fecharDossie()">✕ fechar</span><div class="grab"></div>${spin('Montando dossiê de '+esc(nome||dig)+'…')}`;
  a11yfy(sh);
  const d=await J('/api/perfil?cnpj='+dig);
  if(!d.ok){sh.innerHTML=`<span class="x" aria-label="Fechar" onclick="fecharDossie()">✕</span><div class="grab"></div>`+card(`<div class="warn">${erroHumano(d.erro)}</div>`);a11yfy(sh);return;}
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
  if((d.achados||[]).length)h+=`<div style="height:12px"></div>`+sec('Achados da perícia',d.achados.length)+`<div class="grid">`+d.achados.map(a=>card(`<div style="display:flex;gap:9px;align-items:flex-start"><span class="tag ${a.status==='CONFIRMADO'?'rose':a.status==='INDICIO'?'amber':a.status==='AFASTADO'?'green':'accent'}">${esc(a.status||'')}</span><div><div style="font-weight:650;font-size:13.5px">${esc(a.codigo||'')} — ${esc(a.titulo||'')}</div>${a.evidencia?`<div class="muted ev-clamp" style="font-size:12.5px;margin-top:3px" title="clique para ver completo" onclick="this.classList.toggle('aberto')">${esc(a.evidencia)}</div>`:''}</div></div>`)).join('')+`</div>`;
  h+=`<div style="height:14px"></div><div class="btns">
      <button class="btn accent" onclick="fecharDossie();esfera='geral';aba='g_acoes';montarSpheres();montarTabs();ir('g_acoes').then(()=>{const e=$('ac-emp');if(e)e.value='${d.cnpj}';})">Relatório + Lex</button>
      <button class="btn ghost" onclick="verCruzamento('${d.cnpj}')">Cruzamento</button>
      <button class="btn ghost" onclick="seiArvore('${d.cnpj}')">🗂️ Árvore SEI completa</button>
      <a class="btn ghost" href="/graph?cnpj=${d.cnpj}" target="_blank">Grafo societário</a></div>
      <pre id="dos-cruz" style="margin-top:10px;display:none"></pre>
      <div id="sei-arvore-box" style="margin-top:10px"></div>`;
  h+=`<div class="note">Dossiê do banco local — indício a verificar, presunção de legitimidade. CPF de sócio mascarado (LGPD).</div>`;
  sh.innerHTML=h;
  a11yfy(sh);
}
// ═══ ÁRVORE SEI completa de uma empresa (busca + download em lote) ═══
let _seiArvoreTimer=null;
export async function seiArvore(cnpj){
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
export async function seiBaixarZip(cnpj){
  const r=await J('/api/sei/empresa/zip?cnpj='+cnpj);
  if(!r.ok){jfnToast('Não consegui montar o ZIP agora — '+(r.erro||'tente de novo em instantes.'),'rose');return;}
  window.open(r.url,'_blank');
}
export async function verCruzamento(cnpj){const out=$('dos-cruz');out.style.display='block';out.textContent='cruzando…';
  const r=await J('/api/cruzamento?cnpj='+cnpj);if(r.erro){out.textContent='⚠ '+r.erro;return;}
  const dd=r.dados||r;out.textContent=`co-endereço: ${(dd.coendereco||[]).length} · indícios: ${(dd.indicios||[]).length}\n`+(dd.socios||[]).slice(0,6).map(s=>'• '+(s.nome||s)).join('\n');}

// ═══ CERTAME — Índice de Direcionamento por temas (7 famílias) ═══
const _CERT_FAM={transparencia:['📋','Transparência'],competicao:['⚔️','Competição'],conluio:['🤝','Conluio'],
  fraude_cadastral:['🎭','Fraude cadastral'],preco:['💰','Preço'],execucao:['📈','Execução'],
  certame_ata:['⚖️','Ata de julgamento']};
export function jsq(s){return String(s==null?'':s).replace(/\\/g,'\\\\').replace(/'/g,"\\'");}
export function fecharCertame(){$('ov').classList.remove('on');}
export async function abrirCertame(certame){
  if(!certame)return;
  const ov=$('ov'),sh=$('sheet');ov.classList.add('on');
  sh.innerHTML=`<span class="x" onclick="fecharCertame()">✕ fechar</span><div class="grab"></div>${spin('Calculando índice de '+esc(certame)+'…')}`;
  a11yfy(sh);
  const d=await J('/api/certame/indice?certame='+encodeURIComponent(certame));
  if(!d.ok){sh.innerHTML=`<span class="x" aria-label="Fechar" onclick="fecharCertame()">✕</span><div class="grab"></div>`+card(`<div class="warn">${erroHumano(d.erro)}</div>`);a11yfy(sh);return;}
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
    return card(`<div style="display:flex;gap:9px;align-items:flex-start"><span class="tag rose">${esc(lbl)}</span><div><div style="font-weight:650;font-size:13.5px">${esc(dr.flag||'')} — ${(dr.valor*100).toFixed(0)}%</div>${dr.evidencia?`<div class="muted ev-clamp" style="font-size:12.5px;margin-top:3px" title="clique para ver completo" onclick="this.classList.toggle('aberto')">${esc(dr.evidencia)}</div>`:''}</div></div>`);
  }).join('')+`</div>`;
  if(d.narrativa)h+=`<div style="height:12px"></div>`+card(`<div style="font-size:13.5px;color:var(--mut);white-space:pre-wrap">${esc(d.narrativa).slice(0,1500)}</div>`);
  h+=`<div class="note">Índice de Direcionamento — indício a apurar, nunca acusação. Fonte: ${esc(d.fonte||'calculado')}${d.gerado_em?', gerado em '+esc(d.gerado_em):''}.</div>`;
  sh.innerHTML=h;
  a11yfy(sh);
}


/* TOAST E CONFIRM com a cara do painel — alert/confirm nativos quebravam a imersao.
   Vieram do entrypoint na etapa 7: quem os chama sao as TELAS, e tela nao deve importar
   do entrypoint. */

// Erro de rede NUNCA chega cru ao usuário (era `TypeError: Failed to fetch` na tela).

// Toast e confirm com a cara do painel (alert/confirm nativos quebravam a imersão).
export function jfnToast(msg,tipo){
  let box=$('v10toasts');if(!box){box=document.createElement('div');box.id='v10toasts';document.body.appendChild(box);}
  const t=document.createElement('div');t.className='v10toast '+(tipo||'');
  t.innerHTML=(tipo==='rose'?svgIco('§alert'):tipo==='green'?svgIco('§ok'):'')+`<span>${msg}</span>`;
  box.appendChild(t);requestAnimationFrame(()=>t.classList.add('on'));
  setTimeout(()=>{t.classList.remove('on');setTimeout(()=>t.remove(),250);},4600);
}
export function jfnConfirm(msg,rotuloOk){
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
