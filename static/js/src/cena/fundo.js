/* OS DOIS CANVAS DE FUNDO — o território do Estado e a malha de rede, atrás de TODA aba.
 *
 * Saiu de `cena/index.js` na v59 (§6.2-B do PAINEL-v58).
 *
 *   `rjbgStart` desenha a malha REAL do IBGE num offscreen (uma vez por tamanho e por cor),
 *   tingida pela cor da esfera ativa; no quadro passa só uma varredura de radar e a respiração,
 *   que é barato. Re-tinge quando a esfera muda, por `_rjbgTinge`.
 *   `netbgStart` é a malha de rede, deslocada pela paralaxe do ponteiro.
 *
 * O dado sempre lê primeiro: opacidade baixa, e os dois pausam em `document.hidden` e em modo
 * sóbrio — nenhum laço daqui reagenda quadro sem consultar `_sobrio` antes.
 *
 * `_ckMX`/`_ckMY` (a posição do ponteiro) vêm da FOLHA `cena/ponteiro.js` e são lidas, nunca
 * escritas: quem escreve é `cenaPonteiro`, chamada pelo ouvinte da sequência de boot. `export let`
 * dá binding vivo, então ler daqui vê o valor do quadro corrente sem nenhuma cópia.
 *
 * Sem efeito de topo.
 */
import {$} from '../nucleo/dom.js';
import {_sobrio} from '../capacidade/estado.js';
import {esfera} from '../app/estado.js';
import {_rjCarregar} from './malha-rj.js';
import {_ckMX, _ckMY} from './ponteiro.js';

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
