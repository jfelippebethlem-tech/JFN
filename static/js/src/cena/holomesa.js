/* A HOLOMESA — a câmera 3D que projeta o território do Estado no piso da mesa de vigília.
 *
 * Saiu de `cena/index.js` na v59 (§6.2-B do PAINEL-v58). O plano dizia que este corte era
 * "reescrita, não mudança de arquivo", porque `nucleoStart` usa `_holoProj`, `_rjCarregar`,
 * `_rjBuild`, `_holoPiso` e `HOLO`. A afirmação estava certa sobre o SENTIDO e errada sobre o
 * TAMANHO: as cinco referências são todas de mão única — a mesa chama a câmera, a câmera nunca
 * chama a mesa. Uma dependência que só anda num sentido é exatamente a que vira `import` sem
 * reescrever nada, e é isso que este arquivo é.
 *
 * O núcleo deixou de ser um círculo visto de frente e passou a ser uma MESA DE HOLOGRAMA: o
 * território do RJ é o CHÃO (perspectiva com divisão por z), os domínios flutuam acima dele em
 * três altitudes, cada um ancorado ao piso por um feixe vertical e uma pegada de luz.
 *
 * Aqui mora só a MATEMÁTICA e o traçado: projeção mundo→tela, a placa do território, o contorno em
 * unidade de mundo e o desenho do piso em fatias. Nada aqui sabe o que é um domínio, um evento ou
 * um chip — quem sabe é `nucleoStart`, e é essa ignorância que torna o módulo testável de fora.
 *
 * Sem efeito de topo.
 */
import {_rjBuild} from './malha-rj.js';

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
export const _hex2=a=>Math.max(0,Math.min(255,Math.round(a*255))).toString(16).padStart(2,'0');
export const HOLO={PL:1.10, ELEV:0.56, CAMD:3.15, SZ:520,    // piso, elevação (rad), distância, resolução do bitmap
            ESP:0.045, ARO:1.11, GIRO:-0.28,          // espessura da laje · aro · giro do território (rad)
            /* ALT = teto da cena: altura do reator e do anel mais alto. Era 0.60 solto em
               três lugares (o HT do enquadramento e os dois P(0,0.60,0) do reator), e
               esse ar reservado acima do piso era o que fazia o TERRITÓRIO ficar numa
               faixa fina no meio do card — o "pequeno e vazio" que o dono viu. Baixar
               para 0.46 devolve a altura ao piso e mantém a escada de três degraus. */
            ALT:0.46};
export function _holoProj(x,y,z,c){                          // mundo → tela (x direita, y altura, z profundidade)
  const X=x*c.cy_ - z*c.sy_, Z=x*c.sy_ + z*c.cy_;     // giro em torno do eixo vertical (yaw)
  const Y2=y*c.cp + Z*c.sp;                           // inclinação da câmera (elevação)
  const Z2=Math.max(0.42, Z*c.cp - y*c.sp + c.camd);  // distância à câmera (nunca atrás do olho)
  const k=c.camd/Z2;                                  // perspectiva: k=1 no centro da mesa
  return {x:c.cx + X*k*c.s, y:c.cy - Y2*k*c.s, k, z:Z2};
}
/* território assado em vista ORTOGONAL de cima, num quadrado que cobre o piso
   inteiro. É este bitmap que depois vira chão em perspectiva. */
export function _rjPlaca(M,SZ){
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
export function _rjContornoMundo(M){
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
export function _holoPiso(g,bmp,c,W,H,alt){
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
