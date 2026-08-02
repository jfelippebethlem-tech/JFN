/* A CENA — tudo que o painel desenha por quadro: os dois canvas de fundo, a mesa de vigilia com
 * projecao 3D do territorio, os videos de esfera e o portal de ignicao em WebGL.
 *
 * POR QUE UM MODULO SO, e nao os cinco do plano (fundo, mesa, malha, video, portal). No arquivo
 * original a cena esta INTERLEAVADA com o cockpit: `netbgStart` termina e o `_ckCount` comeca na
 * linha seguinte; `nucleoStart` termina e o `ckCard` comeca na seguinte. Sao quatro faixas puras
 * separadas por codigo que nao e cena. Junta-las num modulo e uma operacao textual, verificavel.
 * Subdividir exigiria resolver dezenas de referencias cruzadas (`nucleoStart` usa `_holoProj`,
 * `_rjCarregar`, `_rjBuild`, `_holoPiso`, `HOLO`) — isso e reescrita, nao mudanca de arquivo, e
 * fica para um corte proprio.
 *
 * TRES INVARIANTES QUE ESTE MODULO CARREGA e que nao podem se perder no proximo corte:
 *   1. Todo laco de canvas consulta `_sobrio` antes de reagendar quadro. Sem isso o painel mede o
 *      orcamento, diz "nao cabe" e gasta igual.
 *   2. Todo laco tem `visibilitychange`: aba oculta nao desenha.
 *   3. A mesa tem `IntersectionObserver` — fora da viewport ela nao paga quadro.
 *
 * Nao ha efeito de topo aqui. Quem liga a cena e a sequencia de boot do entrypoint.
 */
import {$, esc, svgIco, card, kpi, sec, spin, corta, clk} from '../nucleo/dom.js';
import {fmtN, fmtD, fmtR, fmtRc, rot} from '../nucleo/formato.js';
import {J} from '../nucleo/http.js';
import {_redMotion, _sobrio} from '../capacidade/estado.js';
import {esfera, aba} from '../app/estado.js';

/* PARALAXE DO PONTEIRO. A posicao normalizada do mouse mora AQUI porque quem a consome e a cena
   (o `netbg` desloca a malha com ela). O listener que a escreve continua na sequencia de boot do
   entrypoint — efeito de topo nao mora em modulo — e chama `cenaPonteiro`. Antes desta extracao
   as duas variaveis viviam no entrypoint e a cena as lia como global; depois do IIFE isso virou
   `_ckMX is not defined` no primeiro quadro, pego pelo boot_check. */
export let _ckMX = .5, _ckMY = .5;
export function cenaPonteiro(x, y) { _ckMX = x; _ckMY = y; }

/* ══ CACHES DE SONDA ══ */
var _nebVid={};   // cache das sondas HEAD da nebulosa — lido no boot, antes da def
var _nuVid={};    // idem para o núcleo holográfico (um loop por esfera)
var _rjCbs=[],_rjLoading=false;   // carregador da malha do RJ — declarado no topo (o init usa antes da def de _rjCarregar)

/* ─────────────────────────────────────────────────────────────────────────── */

/* ══ FUNDO: RJBG E NETBG ══ */
export let _rjbgTinge=()=>{};
export function rjbgStart(){
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
    if(!mapC){raf=requestAnimationFrame(draw);return;}   // ainda carregando a malha: espera (limitado)
    if(document.hidden){if(!_sobrio)raf=requestAnimationFrame(draw);return;}
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
    /* Reagendava INCONDICIONALMENTE — redesenhava a malha inteira por quadro mesmo sob
       reduced-motion, que só tirava a varredura de radar. No modo sóbrio o mapa fica pintado e
       parado: mesma imagem, zero quadro. */
    if(!_sobrio)raf=requestAnimationFrame(draw);
  }
  _rjbgTinge=()=>{if(!window.RJ_MALHA)return;if(corEsf()!==corAtual)build();};
  size();
  addEventListener('resize',()=>{cancelAnimationFrame(raf);size();draw(performance.now());},{passive:true});
  /* uma repintura ao voltar para a aba; o `_sobrio` dentro de draw() garante que ela não reacende
     o laço — repinta o quadro estático e para. */
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){cancelAnimationFrame(raf);draw(performance.now());}});
  /* pinta assim que a malha chega: no modo sóbrio o laço já parou e ninguém mais chamaria draw(). */
  _rjCarregar(()=>{build();draw(performance.now());});
  draw(performance.now());
}
export function netbgStart(){
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
    /* `_sobrio` congela a malha no último quadro (fica campo estático, ainda bonito) em vez de
       recalcular O(n²) por quadro numa máquina que já se declarou sem orçamento. */
    if(!rm&&!_sobrio)raf=requestAnimationFrame(draw);}
  addEventListener('resize',()=>{cancelAnimationFrame(raf);size();draw();});
  document.addEventListener('visibilitychange',()=>{cancelAnimationFrame(raf);if(!document.hidden&&!_sobrio)draw();});
  size();draw();
}

/* ─────────────────────────────────────────────────────────────────────────── */

/* ══ MESA DE VIGILIA ══ */
export const NU_NODES=[
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
export const _reatorArt=new Image();_reatorArt.src='/static/assets/reator-core.webp';
// qual sweep alimenta o sistema agora → mostra no reator e o acelera
export async function nuSweepPoll(){
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
export function nuSet(id,val){
  const el=$('nu-'+id);if(el==null)return;const n=el.querySelector('.n');
  const prev=_nuVals[id];_nuVals[id]=val;
  n.textContent=val==null?'—':(typeof val==='number'?fmtN(val):val);
  if(typeof val==='number'&&typeof prev==='number'&&val!==prev){   // delta REAL desde a última amostra
    const d=val-prev,s=document.createElement('em');s.className='nu-delta';
    s.textContent=(d>0?'+':'')+fmtN(d);el.appendChild(s);setTimeout(()=>s.remove(),4000);}
}
export function nucleoPulse(tipo){
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
export let _nuEvTotal=0,_nuHover=null;
/* `_nuHover` e um dos 19 estados que o HTML ESCREVE de dentro de um atributo on*
   (`onpointerenter="_nuHover='...'"`). Depois que a cena virou modulo, a ponte nao pode
   mais fechar sobre a variavel: `v=>{_nuHover=v}` escrito no entrypoint resolveria
   `_nuHover` para o proprio getter do window e entraria em recursao infinita — foi
   exatamente o que o boot_check pegou. Quem escreve, chama esta funcao. */
export function _setNuHover(v){_nuHover=v;}
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
/* v41: NUCLEO-HOLO — o arc reactor que projeta o holograma (arte do it-campo) entra
   como corpo de video SOB o canvas; o procedural (feixes, chips, dados reais) segue
   por cima. Progressivo: sem arquivo, nada muda.
   v53: o loop deixa de ser fixo no rj — cada esfera tem o seu (ambar na prefeitura,
   violeta no transversal), no MESMO padrao da nebulosa: webm antes do mp4, poster
   .jpg por baixo, sonda HEAD uma vez por nome, reduced-motion e modo sobrio apagam.
   Estado e Inicio seguem no nucleo-holo-rj (que nao tem .jpg — sem poster, sem erro). */
export async function nucleoViva(){
  const box=$('ck-nucleo');if(!box)return;
  const mapa={inicio:'nucleo-holo-rj',estado:'nucleo-holo-rj',
              prefeitura:'nucleo-holo-prefeitura',geral:'nucleo-holo-transversal'};
  const nome=mapa[esfera]||'nucleo-holo-rj';
  let v=box.querySelector('video.holo');
  /* mesma regra da nebulosa: decodificar video por quadro e exatamente o custo que a
     maquina em modo sobrio ja nao estava dando conta. */
  if(_redMotion||_sobrio){if(v){v.classList.remove('on');v.pause();}return;}
  const url='/static/assets/'+nome+'.mp4';
  if(_nuVid[nome]===undefined){
    try{_nuVid[nome]=(await fetch(url,{method:'HEAD'})).ok}
    catch(e){_nuVid[nome]=false}}
  if(!_nuVid[nome]){if(v)v.classList.remove('on');return;}
  if(!v){v=document.createElement('video');v.className='holo';
    v.muted=true;v.loop=true;v.playsInline=true;v.autoplay=true;
    v.setAttribute('aria-hidden','true');
    /* .on so quando ha QUADRO de verdade — play() que resolve sem codec deixaria
       o veu ligado sobre video preto. */
    v.addEventListener('playing',()=>v.classList.add('on'));
    box.insertBefore(v,box.firstChild);}
  if(v.dataset.nu!==nome){v.classList.remove('on');v.dataset.nu=nome;
    v.poster='/static/assets/'+nome+'.jpg';
    /* v41.1: par de sources — webm primeiro (Chromium sem H.264 decodifica VP9;
       o Chrome real pega qualquer um). O que faltar cai pro proximo. */
    v.innerHTML='<source src="'+url.replace('.mp4','.webm')+'" type="video/webm">'
               +'<source src="'+url+'" type="video/mp4">';
    v.load();}
  v.play().catch(()=>{});
}
export function nucleoStart(){
  const box=$('ck-nucleo'),cv=$('nucleo-cv');if(!box||!cv)return;
  nucleoViva();
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
     Com fase homogênea por anel a distribuição é estável para sempre.
     v53: mas distribuir NÃO é o mesmo que separar — este comentário afirmava que a fase
     homogênea resolvia "o empilhamento na raiz" e o it-campo mediu que não: sem detecção
     de colisão os rótulos se cobriam do mesmo jeito, e a colisão ia e voltava conforme a
     mesa gira. Quem separa é o passo 4b (busca em órbita contra as caixas já ocupadas);
     esta fase só garante um ponto de partida bem espalhado. */
  [0,1,2].forEach(a=>{const nós=NU_NODES.filter(n=>n._an===a);
    nós.forEach((n,i)=>{n._fase=(i/nós.length)*2*Math.PI + a*0.7;});});
  const ESP=HOLO.ESP, ARO=HOLO.ARO;
  /* `_nuVisivel` fica AQUI, com o resto do estado, e nao junto do observador la
     embaixo: `repinta()` chama `draw()` antes daquele ponto e um `let` ainda em zona
     morta temporal derrubava a mesa inteira com ReferenceError — mas SO em
     reduced-motion, que e o unico caminho em que `repinta()` desenha. */
  let W,H,placa=null,contorno=null,piso=null,pisoG=null,pisoSujo=true,_nuVisivel=true,_nuPintou=false;
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
    /* v52: SÓ pula o quadro se a mesa JÁ tem um quadro na tela. Antes, aba oculta no boot
       significava mesa em branco: os 7 `.nu-chip` existem no DOM mas ficam empilhados em
       (0,0) até `draw` posicioná-los, e o canvas nunca recebia um traço. Um quadro custa
       ~15 ms e é a diferença entre cockpit e tela vazia. */
    if(document.hidden&&_nuPintou){_nuRAF=0;return;}    // o ouvinte de visibilitychange retoma
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
      /* A PÍLULA DE SWEEP e o HUD também são território ocupado — e agora entram como
         CAIXAS, não como faixa. A regra anterior reservava só a faixa ACIMA da pílula
         porque a supunha no topo; no desktop ela vive em `bottom:14px` (painel.css:128 —
         o `top:10px` é do regime compacto). O piso `y>=h+_pB` caía então FORA da caixa e
         empurrava o rótulo justamente para cima do "alimentando · SEI". Como caixa, vale
         onde quer que o CSS a ponha, e o HUD (canto inferior direito) enfim é respeitado. */
      /* Toda leitura de geometria (offsetWidth / getBoundingClientRect) entra no MESMO
         cache de 45 quadros. Ler geometria depois de escrever estilo força LAYOUT
         SÍNCRONO: medir a pílula a cada quadro levou o teto do desenho de 5,7 para 44,7 ms. */
      /* `classList.contains` não custa layout — então a MUDANÇA de estado da pílula
         força a remedição na hora, em vez de esperar o ciclo de 45 quadros. Nesta VM,
         a 3 fps, esperar o ciclo significava até 15 s com o rótulo em cima do sweep. */
      const _pOn=(()=>{const e=$('nu-sweep');return !!(e&&e.classList.contains('on'));})();
      if(_pOn!==draw._pOn){draw._pOn=_pOn;draw._m=999;}
      if(!draw._m||draw._m>45){
        draw._m=0;
        NU_NODES.forEach(n=>{const e=$('nu-'+n.id);
          if(e){n._w=e.offsetWidth||96;n._h=e.offsetHeight||34;}});
        /* pela CAIXA RENDERIZADA, não por `offsetLeft`: a pílula é centrada com
           `left:50%` + `translateX(-50%)`, e offsetLeft ignora o transform. */
        const rb=box.getBoundingClientRect();
        const _caixa=e=>{const r=e.getBoundingClientRect();
          return {x:r.left-rb.left+r.width/2, y:r.top-rb.top+r.height/2, w:r.width, h:r.height};};
        draw._fix=[];
        const pil=$('nu-sweep');
        if(pil&&pil.classList.contains('on'))draw._fix.push(_caixa(pil));
        const hud=$('nu-hud');
        if(hud&&hud.offsetWidth)draw._fix.push(_caixa(hud));
      }
      draw._m=(draw._m||0)+1;
      for(const c of (draw._fix||[]))_cx.push(c);
      pos.slice().sort((a,b)=>b.k-a.k).forEach(o=>{
        const n=o.n,el=$('nu-'+n.id);if(!el)return;
        /* empurrão radial a partir do centro do PRÓPRIO ANEL do nó, não do centro do
           piso: todo nó flutua acima do piso, então usar o piso como eixo empurrava
           todos para CIMA e eles se empilhavam no topo. O centro do anel devolve o
           anel de rótulos em volta da órbita — que era o comportamento do v11. */
        const rc=P(0,o.h,0);
        const sc=Math.max(.84,Math.min(1.06,o.k));
        const w=(n._w||96)*sc, h=(n._h||34)*sc;
        const a0=Math.atan2(o.y-rc.y, o.x-rc.x);
        /* DETECÇÃO DE COLISÃO DE VERDADE. As três altitudes distribuem, mas nada IMPEDIA
           duas caixas de ocupar o mesmo pixel — e como as posições giram, a colisão ia e
           voltava ("radar de risco" sob "empresa morta", o HUD sob "caro + suspeito").
           O empurrão de antes era uma passada só, em Y, e os `clamp` seguintes podiam
           devolver a caixa para dentro de quem ela acabara de evitar.
           Agora: o rótulo tenta o lugar canônico e, se estiver ocupado, ANDA EM ÓRBITA em
           volta do próprio nó e sobe de raio (altura junto, pelo fator .62 do elipsóide)
           até achar vaga. Vence a PRIMEIRA vaga livre; se nenhuma estiver, fica na de menor
           sobreposição — nunca pior que o comportamento antigo. Reusa as caixas de `_cx`. */
        let melhor=null;
        for(const rad of [54,76,100,128]){
          for(const gir of [0,.3,-.3,.62,-.62,.95,-.95,1.3,-1.3,1.7,-1.7,2.2,-2.2,Math.PI]){
            const a=a0+gir;
            let x=o.x+Math.cos(a)*rad, y=o.y+Math.sin(a)*rad*0.62-18;
            x=Math.max(w/2+8,Math.min(W-w/2-8,x));      // nunca sai da caixa
            y=Math.max(h+8,Math.min(H-8,y));
            const cy=y-h/2;             // `y` é a BASE (translate -100%); colisão é por centro
            let ov=0;
            for(const c of _cx){
              const px=(w+c.w)/2+8-Math.abs(x-c.x), py=(h+c.h)/2+8-Math.abs(cy-c.y);
              if(px>0&&py>0)ov+=px*py;
            }
            if(!melhor||ov<melhor.ov)melhor={x,y,ov};
            if(!ov)break;
          }
          if(!melhor.ov)break;
        }
        const x=melhor.x, y=melhor.y;
        _cx.push({x,y:y-h/2,w,h});
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
    _nuPintou=true;
    /* v52: em modo sóbrio a mesa fica no ÚLTIMO quadro — campo estático com nós, rótulos e
       conectores. Sóbrio barateia a animação; entregar tela vazia nunca foi o combinado. */
    _nuRAF=(rm||_sobrio||document.hidden)?0:requestAnimationFrame(draw);
  }
  document.addEventListener('visibilitychange',()=>{
    if(document.hidden||!cv.isConnected||!_nuVisivel)return;
    cancelAnimationFrame(_nuRAF);draw(performance.now());});   // volta da aba (e saída do sóbrio)
  cancelAnimationFrame(_nuRAF);draw(performance.now());
  // qual sweep alimenta o sistema — pinga já e a cada 15s enquanto o núcleo vive
  nuSweepPoll();clearInterval(_swInt);
  _swInt=setInterval(()=>{cv.isConnected?nuSweepPoll():clearInterval(_swInt);},15000);
}

/* ─────────────────────────────────────────────────────────────────────────── */

/* ══ VIDEO DAS ESFERAS ══ */
export async function nebulaViva(){
  const mapa={estado:'nebula-estado',prefeitura:'nebula-prefeitura',
              geral:'nebula-transversal',inicio:'portal-hero'};
  const nome=mapa[esfera],host=$('esfnebula');
  if(!nome||!host||_redMotion)return;
  /* v51: modo sobrio (FPS MEDIDO < 24) tambem apaga a nebulosa viva. Decodificar video
     de faixa inteira a cada quadro e exatamente o custo que a maquina ja nao estava
     dando conta — some o veu, o JPG do pai reaparece por baixo e o quadro fica igual. */
  if(_sobrio){const v0=host.querySelector('video');
    if(v0){v0.classList.remove('on');v0.pause();}return;}
  const url='/static/assets/'+nome+'.mp4';
  if(_nebVid[nome]===undefined){
    try{_nebVid[nome]=(await fetch(url,{method:'HEAD'})).ok}
    catch(e){_nebVid[nome]=false}}
  let v=host.querySelector('video');
  if(!_nebVid[nome]){if(v)v.classList.remove('on');return;}
  if(!v){v=document.createElement('video');
    v.muted=true;v.loop=true;v.playsInline=true;v.autoplay=true;
    v.preload='metadata';   // v51: nao puxar 1-2 MB antes de a esfera pedir
    v.setAttribute('aria-hidden','true');
    /* .on so quando ha QUADRO de verdade — play() que resolve sem codec
       (Chromium sem H.264) deixaria o veu ligado sobre video preto. */
    v.addEventListener('playing',()=>v.classList.add('on'));
    host.appendChild(v);}
  if(v.dataset.neb!==nome){v.classList.remove('on');v.dataset.neb=nome;
    v.poster='/static/assets/'+nome+'.jpg';   // v51: mesmo quadro do JPG do pai enquanto nao toca
    /* v41.1: webm primeiro (harness sem H.264), mp4 como caminho canonico */
    v.innerHTML='<source src="'+url.replace('.mp4','.webm')+'" type="video/webm">'
               +'<source src="'+url+'" type="video/mp4">';
    v.load();}
  v.play().catch(()=>{});
}
/* v55 — HOLOGRAMA DO ESTADO (assinatura). Mesmo encaixe progressivo da nebulosa: sonda HEAD
   uma vez, webm antes do mp4, .on só quando há QUADRO ('playing'), reduced-motion e modo
   sóbrio apagam. Vive na esfera Estado e em TODA aba dela — por isso é assinatura, não enfeite
   de uma tela. `body.holo-on` faz o #rjbg recuar: a malha do IBGE e o holograma desenham a
   mesma geografia, e dois Estados sobrepostos viram ruído em cima do dado. */
export async function holoRJ(){
  const host=$('holorj');if(!host)return;
  let v=host.querySelector('video');
  const apaga=()=>{document.body.classList.remove('holo-on');if(v){v.classList.remove('on');v.pause();}};
  if(esfera!=='estado'||_redMotion||_sobrio){apaga();return;}
  const url='/static/assets/holo-rj-estado.mp4';
  if(_nebVid.holorj===undefined){
    try{_nebVid.holorj=(await fetch(url,{method:'HEAD'})).ok}
    catch(e){_nebVid.holorj=false}}
  if(!_nebVid.holorj){apaga();return;}
  if(esfera!=='estado')return;                      // esfera trocou durante o HEAD
  if(!v){v=document.createElement('video');
    v.muted=true;v.loop=true;v.playsInline=true;v.autoplay=true;v.preload='metadata';
    v.poster='/static/assets/holo-rj-estado.jpg';
    v.setAttribute('aria-hidden','true');
    v.addEventListener('playing',()=>{v.classList.add('on');document.body.classList.add('holo-on');});
    v.innerHTML='<source src="'+url.replace('.mp4','.webm')+'" type="video/webm">'
               +'<source src="'+url+'" type="video/mp4">';
    host.appendChild(v);}
  v.play().catch(()=>{});
}

/* ─────────────────────────────────────────────────────────────────────────── */

/* ══ PORTAL E MALHA ══ */
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
export function _rjCarregar(cb){
  if(window.RJ_MALHA){try{cb();}catch(_){}return;}
  _rjCbs.push(cb);
  if(_rjLoading)return;
  _rjLoading=true;
  const s=document.createElement('script');
  s.src='/static/assets/rj-malha.js?v=c6127f36';s.async=true;
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

export function portalStart(){
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
