/* O PORTAL DE IGNIÇÃO — cena WebGL de passe único, 1× por sessão.
 *
 * Saiu de `cena/index.js` na v59 (§6.2-B do PAINEL-v58). É o pedaço mais isolado da cena e por
 * isso foi o primeiro a sair: nada no painel lê nada daqui, e daqui só se lê `$`, a bandeira de
 * movimento reduzido e a malha do Estado (`cena/malha-rj.js`).
 *
 * Fragment shader num triângulo de tela cheia: campo de estrelas com rastro radial no salto,
 * reator de anéis de íon com núcleo laranja incandescente, varredura de guardião. Por cima, em
 * Canvas2D, a malha REAL do RJ sendo revelada pela varredura.
 *
 * Por que shader e NÃO Three.js: 0 KB de dependência e tudo na GPU — a VM tem 2 vCPU e não pode
 * gastar CPU com cenografia. Sem contexto WebGL o portal degrada sozinho (fica só o texto sobre
 * fundo escuro) e ninguém vê erro.
 *
 * Regra de produto: NÃO é sequência de load obrigatória. Toca por cima do painel que já está
 * buscando dado atrás, e qualquer toque pula.
 *
 * Sem efeito de topo: quem liga é a sequência de boot do entrypoint.
 */
import {$} from '../nucleo/dom.js';
import {_redMotion} from '../capacidade/estado.js';
import {_rjCarregar, _rjBuild} from './malha-rj.js';

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
