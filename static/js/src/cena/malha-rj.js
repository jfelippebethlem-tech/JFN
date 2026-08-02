/* A MALHA DO ESTADO — o carregador e o traçador do território do RJ (IBGE, estado 33).
 *
 * Saiu de `cena/index.js` na v59 (§6.2-B do PAINEL-v58). É a folha da cena: não importa nenhum
 * outro módulo de cena, e é isso que torna o corte seguro — os três consumidores (`rjbgStart`, a
 * mesa de vigília e o portal de ignição) passam a importar daqui em vez de dividirem um escopo.
 *
 * UM SÓ FETCH SERVE OS TRÊS. `_rjCarregar` guarda os pedidos numa fila enquanto o script de 21 KB
 * está a caminho e chama todo mundo quando ele chega — se cada consumidor buscasse por conta,
 * seriam três downloads da mesma malha no primeiro segundo do painel.
 *
 * `_rjCbs`/`_rjLoading` moram no topo porque o `rjbgStart` chama `_rjCarregar` ANTES da definição
 * dela na ordem do arquivo original; com o módulo isso deixa de importar (declaração de função
 * sobe), mas a fila continua sendo estado de módulo e é aqui que ela pertence.
 *
 * Sem efeito de topo.
 */
import {$} from '../nucleo/dom.js';

var _rjCbs=[],_rjLoading=false;

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
export function _rjBuild(M,W,H,dpr,modo){
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

