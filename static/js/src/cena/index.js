/* A CENA — o que sobrou da mesa de vigília e os vídeos de esfera.
 *
 * O CORTE DA v59 (§6.2-B) tirou daqui, um por um, os pedaços que não precisavam saber do resto:
 *   `cena/malha-rj.js` — o carregador do território do RJ (folha);
 *   `cena/fundo.js`    — os dois canvas de fundo;
 *   `cena/portal.js`   — a abertura (desde a v63 só chama `cena/abertura.js`);
 *   `cena/energia.js`  — as linhas da órbita do cockpit.
 * A câmera 3D (`cena/holomesa.js`) e o laço da mesa (`nucleoStart`, ~650 linhas) saíram no untangle
 * de 20/11/2026: desde a v61 o cockpit monta o reator e o mapa no lugar da mesa e só chamava
 * `nucleoStart` no ramo "v61 desligada", que não existe mais.
 *
 * Fica: os chips/HUD da mesa (`nuSet`, `nucleoPulse` — o `#ck-nucleo` segue no DOM do cockpit, oculto
 * pelo CSS), as tabelas de evento que a órbita compartilha (`EV_COR`, `EV_DOMINIO`), o vídeo do núcleo
 * (`nucleoViva`) e o vídeo de esfera (`nebulaViva`, morto desde a v63 e mantido porque
 * `tests/test_painel_vida_viva.py` o exige pelo nome — ver `docs/untangle/painel.md` §9.6).
 *
 * Invariantes que valem para todo vídeo daqui: consulta `_sobrio` e `_redMotion` antes de tocar; sonda
 * HEAD uma vez por nome; `.on` só no evento `playing`.
 *
 * Nao ha efeito de topo aqui. Quem liga a cena e a sequencia de boot do entrypoint.
 */
import {$} from '../nucleo/dom.js';
import {fmtN} from '../nucleo/formato.js';
import {_redMotion, _sobrio, _v60, _v61, _v63} from '../capacidade/estado.js';
import {esfera} from '../app/estado.js';

/* ══ CACHES DE SONDA ══ */
var _nebVid={};   // cache das sondas HEAD da nebulosa — lido no boot, antes da def
var _nuVid={};    // idem para o núcleo holográfico (um loop por esfera)
/* Quais núcleos TÊM poster no disco. Nem toda esfera tem: `nucleo-holo-rj` nunca teve .jpg.
   Conferida contra `static/assets/` por `tests/test_painel_assets.py` — ver `nucleoViva`. */
export const NUCLEO_COM_POSTER=new Set(['nucleo-holo-rj','nucleo-holo-prefeitura','nucleo-holo-transversal']);   // v60: o .jpg do RJ é um quadro do próprio vídeo (ffmpeg), poster do celular

/* ─────────────────────────────────────────────────────────────────────────── */

/* ══ MESA DE VIGILIA ══ */
export const NU_NODES=[
  {id:'alertas',lab:'alertas',        tab:'e_alertas',cor:'#ff7a8a', orb:.66, sp:-.7},
  // 19/11/2026: radar, mesma sala e caro + suspeito saíram da mesa com os cards (FP medida em fonte primária, COR-04)
  {id:'fenix',  lab:'empresa morta',  tab:'g_fenix',  cor:'#ff9a6a', orb:.6,  sp:1.15},
  {id:'com',    lab:'comunidades',    tab:'g_comun',  cor:'#c096ff', orb:.92, sp:-.55},
  {id:'compras',lab:'compras auditáveis',tab:'e_comp',cor:'#eec276', orb:.68, sp:.9},
];
let _nuVals={};
export function nuSet(id,val){
  const el=$('nu-'+id);if(el==null)return;const n=el.querySelector('.n');
  const prev=_nuVals[id];_nuVals[id]=val;
  n.textContent=val==null?'—':(typeof val==='number'?fmtN(val):val);
  if(typeof val==='number'&&typeof prev==='number'&&val!==prev){   // delta REAL desde a última amostra
    const d=val-prev,s=document.createElement('em');s.className='nu-delta';
    s.textContent=(d>0?'+':'')+fmtN(d);el.appendChild(s);setTimeout(()=>s.remove(),4000);}
}
/* De que DOMINIO veio o evento, e de que cor ele e. As duas tabelas eram literais dentro do
   `nucleoPulse`; passam a ser exportadas porque a orbita do cockpit (v59, `cena/energia.js`)
   precisa exatamente das mesmas respostas — a linha de energia que acende tem de ser a do mesmo
   dominio que a onda do piso, senao a tela conta duas histórias sobre o mesmo evento. Copiar as
   tabelas para o modulo novo seria a quinta cicatriz de lista duplicada divergindo em silencio. */
export const EV_COR={alerta:'255,122,138',radar:'255,122,138',ob_siafe:'238,194,118',
  ob_tfe:'238,194,118',clausula:'192,150,255',pericia:'95,224,161',ata:'125,175,255'};
export const EV_DOMINIO={alerta:'alertas',radar:'radar',ob_siafe:'compras',ob_tfe:'compras',
  clausula:'dossie',pericia:'fenix',ata:'com'};

export function nucleoPulse(tipo){
  if(_redMotion||!$('ck-nucleo'))return;
  // HUD: telemetria REAL da vigília (contagem de eventos do barramento — nada sintético)
  _nuEvTotal++;const hud=$('nu-hud');
  if(hud)hud.innerHTML=`<b>${_nuEvTotal}</b> evento${_nuEvTotal===1?'':'s'} reais do barramento nesta vigília`;
}
let _nuEvTotal=0;
export let _nuHover=null;
/* `_nuHover` e um dos 19 estados que o HTML ESCREVE de dentro de um atributo on*
   (`onpointerenter="_nuHover='...'"`). Depois que a cena virou modulo, a ponte nao pode
   mais fechar sobre a variavel: `v=>{_nuHover=v}` escrito no entrypoint resolveria
   `_nuHover` para o proprio getter do window e entraria em recursao infinita — foi
   exatamente o que o boot_check pegou. Quem escreve, chama esta funcao. */
export function _setNuHover(v){_nuHover=v;}
/* v41: NUCLEO-HOLO — o arc reactor que projeta o holograma (arte do it-campo) entra
   como corpo de video SOB o canvas; o procedural (feixes, chips, dados reais) segue
   por cima. Progressivo: sem arquivo, nada muda.
   v53: o loop deixa de ser fixo no rj — cada esfera tem o seu (ambar na prefeitura,
   violeta no transversal), no MESMO padrao da nebulosa: webm antes do mp4, poster
   .jpg por baixo, sonda HEAD uma vez por nome, reduced-motion e modo sobrio apagam.
   Estado e Inicio seguem no nucleo-holo-rj, que NAO tem .jpg: o poster so entra para os nomes de
   `NUCLEO_COM_POSTER`, sem sondagem nenhuma — sondar por HEAD tambem produz 404. */
/* v60 · A MISTURA SAI DO VIDEO (2026-11-09). `mix-blend-mode` aplicado no PROPRIO <video> nao e
   desenhado de forma consistente pelo compositor por software (SwiftShader — o Chromium sem GPU, e
   qualquer Chrome com aceleracao desligada ou GPU na lista negra): em regime o video simplesmente
   nao aparece, e durante o fade de entrada um PEDACO dele aparece cru, sem mistura — o retangulo
   com um fragmento do holograma sobre o mapa do RJ (medido: o conteudo do retangulo bate quadro a
   quadro com `nucleo-holo-rj.webm` naquela posicao; com `mix-blend-mode:normal` o video inteiro
   aparece, com a mistura nada aparece). Com a mistura num EMBRULHO (<div>) e o video normal la
   dentro, o mesmo compositor desenha a mistura certa e estavel — e o mesmo padrao que a nebulosa
   (#esfnebula) sempre usou. O CSS do embrulho mora em `98-nucleo-video.css`. */
function _nuEmbrulhar(box,v,tipo){
  const w=document.createElement('div');w.className='nu-vid nu-vid-'+tipo;
  w.setAttribute('aria-hidden','true');w.appendChild(v);box.insertBefore(w,box.firstChild);
}
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
  /* v60: no celular o núcleo é POSTER estático e só toca se a pessoa tocar na mesa — decodificar
     vídeo sem ninguém pedir é o custo que o celular menos aguenta. Desktop segue em autoplay. */
  const semAuto=matchMedia('(max-width:760px)').matches;
  if(!v){v=document.createElement('video');v.className='holo';
    v.muted=true;v.loop=true;v.playsInline=true;v.autoplay=!semAuto;
    if(semAuto){v.preload='none';v.classList.add('on');
      box.title='Toque na mesa para animar o holograma (toque de novo para pausar)';
      box.addEventListener('click',e=>{
        if(e.target.closest('.nu-chip,button,a'))return;
        const vv=box.querySelector('video.holo');if(!vv)return;
        if(vv.paused)vv.play().catch(()=>{});else vv.pause();});}
    v.setAttribute('aria-hidden','true');
    /* .on so quando ha QUADRO de verdade — play() que resolve sem codec deixaria
       o veu ligado sobre video preto. */
    v.addEventListener('playing',()=>v.classList.add('on'));
    _nuEmbrulhar(box,v,'holo');}
  if(v.dataset.nu!==nome){v.classList.remove('on');v.dataset.nu=nome;
    /* O comentario acima dizia "sem poster, sem erro" e a linha original dizia o contrario: o
       poster era atribuido SEM condicao, e `nucleo-holo-rj.jpg` nao existe — 404 em toda carga
       das esferas Inicio e Estado, as duas mais visitadas.

       A PRIMEIRA CORRECAO NAO CORRIGIU: ela sondava o .jpg por HEAD antes de usar, e um HEAD
       para um arquivo que nao existe e um 404 igual. Trocar GET por HEAD limpa a rede, nao o
       console — e era o console que a correcao existia para limpar. Medido depois de commitada:
       o 404 continuava la.

       Agora a lista e EXPLICITA, e `test_painel_assets` a confronta com o disco: se alguem gerar
       o .jpg que falta e esquecer de anotar aqui, o teste falha dizendo o nome. Lista que o teste
       vigia nao envelhece calada, e custa zero requisicao. */
    if(NUCLEO_COM_POSTER.has(nome))v.poster='/static/assets/'+nome+'.jpg';
    else v.removeAttribute('poster');
    /* v41.1: par de sources — webm primeiro (Chromium sem H.264 decodifica VP9;
       o Chrome real pega qualquer um). O que faltar cai pro proximo. */
    v.innerHTML='<source src="'+url.replace('.mp4','.webm')+'" type="video/webm">'
               +'<source src="'+url+'" type="video/mp4">';
    v.load();}
  if(semAuto){v.classList.add('on');return;}   // poster à vista; o play é do toque
  v.play().catch(()=>{});
}

/* ─────────────────────────────────────────────────────────────────────────── */

/* ══ VIDEO DAS ESFERAS ══ */
export async function nebulaViva(){
  if(_v63)return;   // v63: o fundo é um só, o das fitas (`v63/fundo.js`) — nenhum vídeo de esfera é criado
  /* v61: as peças claras de `assets/v61/` (loop por esfera; Início = a sala de comando) */
  const mapa=_v61?{estado:'v61/estado',prefeitura:'v61/prefeitura',geral:'v61/transversal',inicio:'v61/sala'}   // sistema: imagem própria, sem vídeo (14/11)
                 :{estado:'nebula-estado',prefeitura:'nebula-prefeitura',
                   geral:'nebula-transversal',sistema:'nebula-transversal',inicio:'portal-hero'};
  const _cel=matchMedia('(max-width:760px)').matches,_eco=!!(navigator.connection&&navigator.connection.saveData);
  const nome=mapa[esfera],host=$('esfnebula');
  /* esfera sem vídeo próprio (Sistema, 14/11): apaga o vídeo da esfera anterior para a imagem dela aparecer */
  if(!nome&&host){const v0=host.querySelector('video');if(v0){v0.classList.remove('on');v0.pause();}}
  if(!nome||!host||_redMotion)return;
  /* v51: modo sobrio (FPS MEDIDO < 24) tambem apaga a nebulosa viva. Decodificar video
     de faixa inteira a cada quadro e exatamente o custo que a maquina ja nao estava
     dando conta — some o veu, o JPG do pai reaparece por baixo e o quadro fica igual. */
  if(_sobrio){const v0=host.querySelector('video');
    if(v0){v0.classList.remove('on');v0.pause();}return;}
  /* v60: no celular e com economia de dados o backdrop é SÓ o poster (o JPG que o CSS já pinta no
     pai, por esfera). Nenhum vídeo é criado nem baixado — é a tela onde decodificar custa mais. */
  /* v61: o celular TOCA a versão leve (`-m`, 854×480); só a economia de dados fica no pôster. */
  if(_v61?_eco:(_v60&&(_cel||_eco))){
    const v0=host.querySelector('video');
    if(v0){v0.classList.remove('on');v0.pause();v0.removeAttribute('autoplay');}return;}
  const _m=_v61&&_cel?'-m':'';
  const url='/static/assets/'+nome+_m+'.mp4';
  if(_nebVid[nome]===undefined){
    try{_nebVid[nome]=(await fetch(url,{method:'HEAD'})).ok}
    catch(e){_nebVid[nome]=false}}
  /* a sonda é assíncrona: se a esfera trocou enquanto ela voltava, esta chamada é a VELHA e não pode
     pôr o vídeo dela por cima do da esfera atual (visto no v61: `sala` tocando sob a aba Estado). */
  if(mapa[esfera]!==nome)return;
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
    v.poster=_v61?'/static/assets/'+nome+(_cel?'-sm':'')+'.webp'
                 :'/static/assets/'+nome+'.jpg';   // v51: mesmo quadro do JPG do pai enquanto nao toca
    /* v41.1: webm primeiro (harness sem H.264), mp4 como caminho canonico */
    v.innerHTML='<source src="'+url.replace('.mp4','.webm')+'" type="video/webm">'
               +'<source src="'+url+'" type="video/mp4">';
    v.load();}
  v.play().catch(()=>{});
}
