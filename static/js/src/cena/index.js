/* A CENA — tudo que o painel desenha por quadro: os dois canvas de fundo, a mesa de vigilia com
 * projecao 3D do territorio, os videos de esfera e o portal de ignicao em WebGL.
 *
 * O CORTE DA v59 (§6.2-B). Ate aqui era um modulo so, e a razao estava escrita: no arquivo
 * original a cena vinha INTERLEAVADA com o cockpit, entao junta-las foi uma operacao textual e
 * verificavel, enquanto subdividir exigiria resolver as referencias cruzadas.
 *
 * Elas foram resolvidas, uma de cada vez, do pedaco mais isolado para o mais preso — e o criterio
 * de cada corte e sempre o mesmo: sai o que nao precisa saber do resto.
 *   `cena/malha-rj.js` — o carregador e o tracador do territorio do RJ. Folha: nao importa cena
 *                      nenhuma. Tres consumidores (fundo, mesa, portal) passam a importar dela.
 *   `cena/portal.js`  — a cena WebGL de ignicao. So le `$`, a bandeira de movimento e a malha.
 *   `cena/holomesa.js`— a camera 3D: projecao mundo->tela, placa do territorio, desenho do piso.
 *                      O plano dizia que este corte era reescrita porque `nucleoStart` usa cinco
 *                      simbolos dela. Certo sobre o sentido, errado sobre o tamanho: as cinco
 *                      referencias andam num sentido so, e dependencia de mao unica vira `import`
 *                      sem reescrever nada.
 *   `cena/energia.js` — as linhas da orbita do cockpit (nasceu ja separada, na mesma versao).
 * O que sobra aqui e o que de fato compartilha estado por quadro: os dois canvas de fundo e a
 * mesa de vigilia com a projecao 3D.
 *
 * O reexport no fim do arquivo mantem a porta de entrada: `entrada.js` continua importando
 * `portalStart` e `_rjCarregar` daqui. Mudar o corte E a lista de imports de todo mundo na mesma
 * passada e como se perde a capacidade de dizer o que quebrou.
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
/* A malha do Estado saiu para `cena/malha-rj.js` (v59). O `import` E o reexport lá no fim são as
   duas metades da mesma decisão: aqui ela é USADA (fundo e mesa a pedem), e lá embaixo ela é
   REPASSADA para que os chamadores de fora não mudem de porta. */
import {_rjCarregar} from './malha-rj.js';
/* A câmera 3D saiu para `cena/holomesa.js` (v59). A dependência anda num sentido só — a mesa
   chama a câmera, a câmera nunca chama a mesa — e é por isso que o corte coube num `import`. */
import {HOLO, _holoProj, _rjPlaca, _rjContornoMundo, _holoPiso, _hex2} from './holomesa.js';

/* A paralaxe do ponteiro virou FOLHA em `cena/ponteiro.js` (v59): o fundo a lê e este arquivo a
   reexporta, e nenhum dos dois enxerga o outro. Ver o cabeçalho de lá para o ciclo que ela
   quebrou — o mesmo que `capacidade/estado.js` já tinha quebrado antes. */
export {_ckMX, _ckMY, cenaPonteiro} from './ponteiro.js';

/* ══ CACHES DE SONDA ══ */
var _nebVid={};   // cache das sondas HEAD da nebulosa — lido no boot, antes da def
var _nuVid={};    // idem para o núcleo holográfico (um loop por esfera)
/* Quais núcleos TÊM poster no disco. Nem toda esfera tem: `nucleo-holo-rj` nunca teve .jpg.
   Conferida contra `static/assets/` por `tests/test_painel_assets.py` — ver `nucleoViva`. */
export const NUCLEO_COM_POSTER=new Set(['nucleo-holo-prefeitura','nucleo-holo-transversal']);

/* ─────────────────────────────────────────────────────────────────────────── */


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
  const c=EV_COR[tipo]||'95,217,255';
  _nuPulses.push({r:0.14,a:.85,c});   // v12: raio em UNIDADE DE MUNDO (onda no piso), não em pixel
  // o evento também VIAJA: sai do domínio que o produziu e entra no núcleo.
  // É o barramento ficando visível — mesma metáfora do Conduíte, em órbita.
  const alvo=EV_DOMINIO[tipo];
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
/* v41: NUCLEO-HOLO — o arc reactor que projeta o holograma (arte do it-campo) entra
   como corpo de video SOB o canvas; o procedural (feixes, chips, dados reais) segue
   por cima. Progressivo: sem arquivo, nada muda.
   v53: o loop deixa de ser fixo no rj — cada esfera tem o seu (ambar na prefeitura,
   violeta no transversal), no MESMO padrao da nebulosa: webm antes do mp4, poster
   .jpg por baixo, sonda HEAD uma vez por nome, reduced-motion e modo sobrio apagam.
   Estado e Inicio seguem no nucleo-holo-rj, que NAO tem .jpg: o poster so entra para os nomes de
   `NUCLEO_COM_POSTER`, sem sondagem nenhuma — sondar por HEAD tambem produz 404. */
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
  v.play().catch(()=>{});
}
/* A MESA VIVA. O piso de projecao sob o nucleo era um JPG estatico: uma foto de mesa embaixo de
   um nucleo que respira. Agora e um loop de 6 s — ondas concentricas de luz saindo do centro,
   emenda medida (delta 2,689 contra passo normal de 2,327 naquele trecho do clipe).

   Segue LETRA POR LETRA a receita do `nucleoViva`, e isso e de proposito: sonda HEAD antes de
   inserir (404 hoje significa 'segue com o JPG', sem erro), par de sources webm+mp4, `.on` so no
   evento `playing` (um `play()` que resolve sem codec deixaria o veu ligado sobre video preto), e
   a MESMA guarda de sobriedade — decodificar video por quadro e exatamente o custo que a maquina
   em modo sobrio ja nao estava dando conta. Inventar um segundo mecanismo aqui seria criar uma
   segunda porta de degradacao para manter. */
export async function mesaViva(){
  const box=$('ck-nucleo');if(!box)return;
  let v=box.querySelector('video.mesa');
  if(_redMotion||_sobrio){if(v){v.classList.remove('on');v.pause();}return;}
  const url='/static/assets/mesa-projecao.mp4';
  if(_nuVid.mesa===undefined){
    try{_nuVid.mesa=(await fetch(url,{method:'HEAD'})).ok}
    catch(e){_nuVid.mesa=false}}
  if(!_nuVid.mesa){if(v)v.classList.remove('on');return;}
  if(!v){v=document.createElement('video');v.className='mesa';
    v.muted=true;v.loop=true;v.playsInline=true;v.autoplay=true;
    v.setAttribute('aria-hidden','true');
    v.poster='/static/assets/mesa-projecao.jpg';
    v.addEventListener('playing',()=>v.classList.add('on'));
    v.innerHTML='<source src="/static/assets/mesa-projecao.webm" type="video/webm">'
               +'<source src="'+url+'" type="video/mp4">';
    box.insertBefore(v,box.firstChild);v.load();}
  v.play().catch(()=>{});
}
export function nucleoStart(){
  const box=$('ck-nucleo'),cv=$('nucleo-cv');if(!box||!cv)return;
  nucleoViva();
  mesaViva();      // o piso vivo entra junto com o nucleo — a mesa e o nucleo sao um so objeto
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

/* ── O PORTAL E A MALHA SAÍRAM (v59, §6.2-B) ──────────────────────────────────────────────────
   `portalStart` e a malha do Estado viraram `cena/portal.js` e `cena/malha-rj.js`. O reexport abaixo
   existe para que NENHUM chamador mude: `entrada.js` continua importando `portalStart` e
   `_rjCarregar` de `cena/index.js`, e o contrato da sequência de boot fica igual. Trocar o corte
   de arquivo E a lista de imports de todo mundo na mesma passada é como se perde a capacidade de
   dizer o que quebrou. */
export {portalStart} from './portal.js';
export {_rjCarregar} from './malha-rj.js';
export {rjbgStart, netbgStart, _rjbgTinge} from './fundo.js';
