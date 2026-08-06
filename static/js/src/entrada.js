/* TESTEMUNHA DO BOOT — precisa ser a PRIMEIRA instrução executada do painel, e não é decoração.
   O HTML carrega este script sem `type=module` e sem `defer` de propósito: ele tem de bloquear o
   parser e rodar ANTES do DOMContentLoaded (mudar isso é o vetor que já matou este boot três
   vezes). Até agora essa propriedade era defendida por um COMENTÁRIO. Aqui ela vira um fato
   observável: com script clássico bloqueante, `document.readyState` é 'loading'; com defer ou
   module, vira 'interactive'. `painel_boot_check` afirma 'loading' e falha se alguém mexer. */
window.__jfnBootReadyState=document.readyState;

/* O NUCLEO — primitivas puras, extraidas do monolito na etapa 3 da quebra em modulos.
   Nada aqui toca DOM montado nem estado de navegacao; e o que ~40 dos 59 renders consomem.
   Sao os primeiros a sair de proposito: se algo neles quebrar, quebra tudo, e e melhor
   descobrir enquanto ainda ha pouco em jogo. */
import {$, esc, svgIco, card, kpi, sec, spin, cover, leitura, semMedicao, btnPdf, acoesAba,
        toggle, corta, clk} from './nucleo/dom.js';
import {ligarDrill} from './nucleo/drill.js';
import {fmtN, fmtD, fmtPct, fmtR, fmtRc, ROTULOS, rot} from './nucleo/formato.js';
import {J, _jCache, erroHumano} from './nucleo/http.js';
import {filtrar, filtrarPag, _pagMais, _acPagPick, buscaPag, listaPaginada, ordenar,
        _pagState} from './nucleo/lista.js';

/* O RELOGIO DO PAINEL. Modulo sem efeito de topo: quem o liga sao os dois pontos do SSE abaixo —
   o batimento (carga + sweep) e o evento. Sem barramento, ele nunca acorda e o painel respira
   devagar, que e a leitura honesta. */
import {ritmoTelemetria, ritmoEvento} from './ritmo.js';
import {sabreStart, hfToggle} from './barramento/sabre.js';
/* O DECK DA CONSCIENCIA. Modulo sem efeito de topo; quem o liga e a sequencia de boot abaixo, e
   quem o alimenta sao os mesmos ganchos do barramento — uma conexao SSE so, dois ouvintes. */
import {conscienciaLigar, conscienciaEvento, conscienciaBatimento,
        conscienciaToggle, conscienciaRever} from './consciencia.js';
import {ritmoEstado} from './ritmo.js';

/* CAPACIDADE. `estado.js` e uma FOLHA de proposito — nao importa nada. E o que quebra o ciclo:
   `cena/*` le `_sobrio` para parar de agendar quadro, e quem ESCREVE `_sobrio` precisa dos videos
   da cena para pausa-los. Com a bandeira na folha, os dois lados a leem sem se enxergarem.
   As ~40 leituras espalhadas pelo painel nao mudaram: `export let` da binding VIVO. */
import {_redMotion, _sobrio} from './capacidade/estado.js';
import {_medirFps, sobrioAoMudar} from './capacidade/sobrio.js';
/* A CENA — canvas de fundo, mesa de vigilia, videos de esfera e portal. Sem efeito de topo:
   quem a liga e a sequencia de boot abaixo. */
import {rjbgStart, netbgStart, _rjbgTinge, nucleoStart, nucleoPulse, nuSet, nuSweepPoll,
        NU_NODES, nucleoViva, nebulaViva, holoRJ, mesaViva, portalStart, _rjCarregar,
        _nuHover, _setNuHover, cenaPonteiro} from './cena/index.js';
import {energiaPacote, energiaRever, energiaParar, energiaCenso} from './cena/energia.js';
import {a11yfy, holografar, glossario, fecharDossie, abrirDossie, seiArvore, seiBaixarZip,
        verCruzamento, fecharCertame, abrirCertame, jsq, _wire,
        uiLigarSpotlight, uiLigarDialogo, uiLigarA11y, vivo, revelacaoCenso} from './ui/index.js';

/* AS TELAS — 59 renders. Ver `abas/index.js`. */
import {ligarVinculos, SEV_LEGENDA, TIPO_ALERTA, _CK, _DETS_ORFAOS, _DET_ROTULO, _TEMA_ROTULO, _acPick, _acRenderSel, _acTimer, _acuLiftHtml, _blocoVedada, _bq, _cjEsf, _ckCount, _ckTick, _ckTimer, _comisView, _compBuscar, _compCatalogo, _compDossie, _compEconomia, _compEsfChips, _compForn, _compItemView, _compOrgaos, _compView, _ctrView, _ehEmail, _fantFaixa, _gastosDet, _liftBloco, _montarGrupoCard, _perOrdem, _respProc, _riscoView, _unOf, _valCard, _valLista, _vincCnpj, abrirCapMestra, acKeydown, acao, autocompletar, blocoComandosMestres, ckBoot, ckCard, ckFill, ckPull, ckPush, detRodar, fazBusca, frescorHtml, fxConsultar, instAcionar, instUgs, limparEfemeros, missaoCriar, missaoListar, missaoVer, pecaGerar, sinteseProcesso, pollarPdf, renderAcoes, renderAcuracia, renderAditivos, renderAlertas, renderBeneficiosPref, renderBuscar, renderCapital, renderCartel, renderCartelMun, renderCertames, renderCockpit, renderComissionadosPref, renderComparador, renderComunidades, renderConluio, renderConluioQSA, renderContratosPref, renderCorridaDezembro, renderDetectoresOrfaos, renderEscalada, renderFantasmasPref, renderFenix, renderFontesExternas, renderFornecedorDependente, renderFracionamento, renderGastosPref, renderHubFisico, renderInstrumentacao, renderLaranjas, renderMissoes, renderNepotismo, renderNepotismoCruzado, renderPPPPref, renderPanoramaEstado, renderPanoramaPref, renderPecas, renderPericias, renderPoder, renderPortaGiratoria, renderPrioridade, renderRadar, renderResponsaveis, renderRetro, renderRiscos, renderSancionadas, renderSancionadasMun, renderSiafe, renderSobrepreco, renderSocioOculto, renderSocioServidor, renderSweeps, renderValidar, renderVinculos, sweep, validar, _set_cjEsf, _set_comisView, _set_compView, _set_ctrView, _set_fantFaixa, _set_gastosDet, _set_perOrdem, _set_respProc, _set_riscoView, _set_compCat, _set_compDisp, _set_compEsf, _set_compGrupo, _set_compOrd, _set_compTermo, _set_perGrau, _compCat, _compDisp, _compEsf, _compGrupo, _compOrd, _compTermo, _perGrau} from './abas/index.js';

async function gerarPdfIntel(tipo,el){
  const txt=el.innerHTML;el.innerHTML='<span class="sp" style="width:12px;height:12px"></span> gerando…';el.disabled=true;
  const r=await J('/api/intel/pdf?tipo='+encodeURIComponent(tipo));
  el.disabled=false;el.innerHTML=txt;
  if(r.ok&&r.url){window.open(r.url,'_blank');}
  else{jfnToast('Falha ao gerar o PDF — '+(r.erro||'o servidor não respondeu. Tente de novo em instantes.'),'rose');}
}

// ═══ ESFERAS ═══
const SPHERES=[
  {id:'inicio',    ic:'◎', tl:'Início',        c:'command deck ao vivo'},
  /* v58: a esfera Estado deixa de usar o templo grego genérico e passa a usar `§rj` — a silhueta
     REAL do território, derivada da mesma malha IBGE que a mesa de vigília projeta. O templo
     continua sendo de `e_poder`/`g_poder`, onde o desenho quer dizer instituição, não território. */
  {id:'estado',    ic:'§rj', tl:'Estado',       c:'órgãos estaduais (SIAFE + PNCP)'},
  {id:'prefeitura',ic:'🏙️', tl:'Prefeitura·Rio',c:'município do Rio (PNCP + folha)'},
  {id:'geral',     ic:'🌐', tl:'Transversal',  c:'riscos, busca, poder, ferramentas'},
];

const TABS={
  inicio:[
    {id:'i_cockpit', ic:'◎',tl:'Cockpit', render:renderCockpit},
  ],
  estado:[
    {id:'e_panorama',ic:'📊',tl:'Panorama',render:renderPanoramaEstado},
    {id:'e_pericias',ic:'⚖️',tl:'Perícias',render:renderPericias},
    {id:'e_sanc',    ic:'🚫',tl:'Sancionadas',render:()=>renderSancionadas('estado')},
    {id:'e_frac',    ic:'§frac',tl:'Fracion.',render:renderFracionamento},
    {id:'e_sobre',   ic:'📈',tl:'Sobrepreço',render:renderSobrepreco},
    {id:'e_escal',   ic:'🪜',tl:'Escalada', render:renderEscalada},
    {id:'e_comp',    ic:'💰',tl:'Comparador',render:renderComparador},
    {id:'e_adit',    ic:'📑',tl:'Aditivos',render:renderAditivos},
    {id:'e_certames',ic:'🧮',tl:'Certames',render:renderCertames},
    {id:'e_cartel',  ic:'§cartel',tl:'Cartel',  render:renderCartel},
    {id:'e_conluio', ic:'§conluio',tl:'Conluio', render:()=>renderConluio('estado')},
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
    {id:'p_cartel',  ic:'§cartel',tl:'Concentração',render:renderCartelMun},
    {id:'p_comis',   ic:'🎖️',tl:'Comissionados',render:renderComissionadosPref},
    {id:'p_benef',   ic:'🍞',tl:'Benefícios',render:()=>renderBeneficiosPref('')},
    {id:'p_fant',    ic:'§fant',tl:'Fantasmas',render:renderFantasmasPref},
    {id:'p_ppp',     ic:'🏗️',tl:'PPP',     render:renderPPPPref},
    {id:'p_conluio', ic:'§conluio',tl:'Conluio', render:()=>renderConluio('prefeitura')},
    {id:'p_contr',   ic:'📄',tl:'Contratos',render:renderContratosPref},
  ],
  geral:[
    {id:'g_buscar',  ic:'🔎',tl:'Buscar',  render:renderBuscar},
    {id:'g_radar',   ic:'§radar',tl:'Radar',   render:renderRadar},
    {id:'g_prioridade',ic:'⚡',tl:'Prioridade',render:renderPrioridade},
    {id:'g_vinculos', ic:'🕸️',tl:'Vínculos', render:renderVinculos},
    {id:'g_pecas',    ic:'📜',tl:'Peças',    render:renderPecas},
    {id:'g_fontes',   ic:'§fonte',tl:'Fontes externas',render:renderFontesExternas},
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
    {id:'g_conluio', ic:'§conluio',tl:'Conluio', render:()=>renderConluio(_cjEsf)},
    {id:'g_validar', ic:'🏢',tl:'Validar', render:renderValidar},
    {id:'g_sweeps',  ic:'🛰️',tl:'Sistema', render:renderSweeps},
    {id:'g_acoes',   ic:'☑️',tl:'Ações',   render:renderAcoes},
  ],
};
/* `esfera` e `aba` vivem em `app/estado.js` — folha que a cena tambem importa. Enquanto
   moravam aqui, o IIFE do bundle as fechava e a cena quebrava com `esfera is not defined`. */
import {esfera, aba, setEsfera, setAba} from './app/estado.js';
/* Movido para `abas/index.js` na v59 — ver a razão lá. Este comentário fica porque a linha que
   estava aqui era um bug de verdade: `const` no entrypoint, USADA em `abas/`, e o esbuild podava
   a declaração (nada no entrypoint a referenciava) deixando três usos órfãos no bundle. O sintoma
   era `sessaoReports is not defined` ao gerar uma peça e a cada `pagehide`. */

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
    _tabsMais();
    return;
  }
  for(const b of nav.children)b.classList.toggle('on',b.dataset.aba===aba);
  /* v57: a aba ativa não pode ficar do lado de fora. `block:'nearest'` é o que impede
     o scrollIntoView de mexer na página (a nav é fixa no rodapé) — só rola a própria barra. */
  const _on=nav.querySelector('button.on');
  if(_on)_on.scrollIntoView({block:'nearest',inline:'nearest',behavior:_redMotion?'auto':'smooth'});
  _tabsMaisPintar();
}
/* ═══ v57 — A BARRA DE ABAS ESCONDIA METADE DE SI ══════════════════════════════════════════
   Medido pelo it-campo: 15 abas, scrollWidth 1260 para clientWidth 818 — 442px fora da tela,
   com `overflow-x:auto` e nenhuma pista. O esmaecimento do v51 (mask-image na nav) apagava a
   borda mas não DIZIA "role"; e mouse comum não tem eixo horizontal. Agora cada ponta ganha um
   sinal com DIREÇÃO, que só acende quando existe conteúdo daquele lado e, clicado, rola ~70%
   da barra. São elementos reais e não pseudo pelo mesmo motivo do v56 (`.hlx`): o `::after` da
   nav já é o fio que corre na navegação e o `::before` é do v14. Ficam DENTRO da nav de
   propósito — `transform:translateX(-50%)` faz dela o bloco contentor de `position:fixed`,
   então eles não rolam junto com o conteúdo. O loop de `.on` acima os ignora (sem `data-aba`). */
function _tabsMais(){
  const nav=$('tabs');if(!nav)return;
  if(!nav.querySelector('.tmais')){
    for(const lado of ['e','d']){
      const i=document.createElement('i');
      i.className='tmais '+lado;i.setAttribute('aria-hidden','true');
      i.onclick=()=>nav.scrollBy({left:(lado==='d'?1:-1)*Math.round(nav.clientWidth*.7),
                                 behavior:_redMotion?'auto':'smooth'});
      nav.appendChild(i);
    }
    nav.addEventListener('scroll',_tabsMaisPintar,{passive:true});
    addEventListener('resize',_tabsMaisPintar,{passive:true});
  }
  _tabsMaisPintar();
}
function _tabsMaisPintar(){
  const nav=$('tabs');if(!nav)return;
  const sobra=nav.scrollWidth-nav.clientWidth-nav.scrollLeft;
  nav.classList.toggle('mais-e',nav.scrollLeft>4);
  nav.classList.toggle('mais-d',sobra>4);
}
/* v36: NAO pre-atribuir `aba` aqui — o ir() ja seta aba e monta as tabs, e a
   pre-atribuicao apagava o sentido do giro na troca de esfera (_abaAntes
   ficava igual ao destino). */
/* v55 — VIAGEM DE CÂMERA entre esferas. As quatro esferas eram quatro páginas: o fundo
   TROCAVA (nebulosa some, nebulosa aparece) e a cabeça lia "recarreguei". Agora a cena
   VIAJA: a câmera desliza no sentido da esfera de destino (fundo, malha e nebulosa
   parallaxam em `transform`, que o compositor faz de graça — nada de repintura), e a
   lâmina do conduíte que já existe corta a transição, tingida na cor da esfera nova.
   Sem recarregar, sem piscar: é a mesma sala vista de outro ponto. */
function _esfViagem(destino){
  if(_redMotion||_sobrio)return;
  const ord=SPHERES.map(s=>s.id),de=ord.indexOf(esfera),pa=ord.indexOf(destino);
  if(de<0||pa<0||de===pa)return;
  const b=document.body;
  b.style.setProperty('--viagem',pa>de?'1':'-1');
  b.classList.remove('viajando');void b.offsetWidth;
  b.classList.add('viajando');
  setTimeout(()=>b.classList.remove('viajando'),720);
  const c=$('conduit');
  if(c){const w=document.createElement('span');w.className='cwipe'+(pa>de?'':' back');
    w.addEventListener('animationend',()=>w.remove());c.appendChild(w);}
}
function trocarEsfera(id){_esfViagem(id);setEsfera(id);montarSpheres();ir(TABS[id][0].id);}
let _nav=0; // token anti-corrida
/* ═══ v57 — A ABA PASSA A EXISTIR NA URL ══════════════════════════════════════════════════
   O painel tinha 60+ abas e UM endereço: `location.hash` vazio, sem link para "abra ISTO",
   e o Voltar do navegador saía do painel inteiro em vez de desfazer a última troca. Como o
   `ir()` já sabe achar a esfera dona de qualquer id, o hash é a chave suficiente: `#g_radar`
   abre a esfera Transversal na aba Radar. `_hashMeu` evita o eco (escrevo o hash → o
   navegador dispara hashchange → eu reentrava em ir()). */
let _hashMeu=false;
function _abaValida(id){return !!id&&Object.values(TABS).some(l=>l.some(t=>t.id===id));}
/* Endereço inexistente era FALHA MUDA: `#e_escalada` (id que não existe — o real é `e_escal`)
   caía no cockpit, reescrevia a URL e a aba anterior ficava na tela. Quem varreu o painel por
   hash leu a MESMA página quatro vezes achando que eram quatro abas. Endereço quebrado tem de
   dizer que está quebrado — e dizer QUAL era o id certo, quando dá para adivinhar. */
function _hashInvalido(id){
  const alvos=Object.values(TABS).flat();
  const perto=alvos.filter(t=>t.id.startsWith(id.slice(0,4))||id.startsWith(t.id)).slice(0,6);
  const v=$('view'); if(!v)return;
  const d=document.createElement('div');
  d.innerHTML=card(`<div class="warn"><b>Endereço inexistente:</b> <code>#${esc(id)}</code> não é uma aba deste painel.`
    +(perto.length?` Você quis dizer ${perto.map(t=>`<a href="#${t.id}">#${t.id}</a>`).join(' · ')}?`:'')
    +` Abri o cockpit no lugar.</div>`);
  v.prepend(d.firstElementChild||d);
}
addEventListener('hashchange',()=>{
  if(_hashMeu){_hashMeu=false;return;}
  const id=decodeURIComponent(location.hash.slice(1));
  if(!id)return;
  if(!_abaValida(id)){ir('i_cockpit').then(()=>_hashInvalido(id));return;}
  if(id!==aba)ir(id);
});
async function ir(id){
  const _abaAntes=aba; // v36: quem eu era antes da troca decide o sentido do giro
  // blindagem: se o id não é da esfera atual, procura a esfera dona e troca (evita crash)
  let t=TABS[esfera].find(x=>x.id===id);
  if(!t){for(const e of Object.keys(TABS)){const cand=TABS[e].find(x=>x.id===id);if(cand){setEsfera(e);t=cand;montarSpheres();break;}}}
  if(!t)return;
  setAba(id);montarTabs();
  if(location.hash.slice(1)!==id){_hashMeu=true;location.hash=id;}
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
  if(typeof nucleoViva==='function')nucleoViva();   // v53: idem para o nucleo holografico da mesa
  if(typeof holoRJ==='function')holoRJ();           // v55: assinatura holografica do Estado
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
  /* v59: sair do cockpit SOLTA o laço da órbita. Sem isto o `requestAnimationFrame` das linhas de
     energia continuaria vivo atrás de uma aba que nem tem o canvas — o mesmo desperdício que o
     deck da Consciência evita fechando o `setInterval` ao fechar. */
  if(aba!=='i_cockpit'){energiaParar();vivo();}   // cockpit tem animação própria; demais herdam
  else ckBoot();                 // v48: monta o cockpit DEPOIS do paint
  a11yfy(document.body);         // torna chips/spheres/.clk operáveis por teclado (audit a11y #1)
}

// ═══ A11Y — restam apenas cards <div onclick> e links <a> sem href: padrão ARIA button (foco+teclado).
//    (chips, spheres e .clk já são <button> semânticos.) ═══

// ═══ FRESCOR DE FONTES (LEDs) ═══
/* v38: se o corpo do no (anel usinado) ja chegou do it-campo, liga a camada.
   Checagem unica no boot — 404 hoje significa "segue procedural", sem erro. */
fetch('/static/assets/no-energia.png',{method:'HEAD'})
  .then(r=>{if(r.ok)document.body.classList.add('art-no')}).catch(()=>{});
/* O BARRAMENTO vive em `barramento/sabre.js`. Ele recebe GANCHOS em vez de importar o que
   precisa, e isso e desenho, nao contorcao: pulsar a mesa (`nucleoPulse`) e saber se pode animar
   sao coisas de FORA do barramento. Importa-las la criaria um ciclo com este arquivo; recebe-las
   aqui diz a verdade — o barramento nao conhece a cena, ele avisa quem quiser ouvir.

   `_hfN` foi embora no caminho: era um contador incrementado a cada linha do holofeed e lido por
   ninguem, em nenhum lugar do repo. */
/* Os tres videos da cena reagem a virada do modo sobrio. Injetados por gancho em vez de
   importados dentro de `capacidade/sobrio.js`, que criaria ciclo com a folha das bandeiras. */
window.addEventListener('pagehide',limparEfemeros);window.addEventListener('beforeunload',limparEfemeros);
addEventListener('pointermove',e=>{cenaPonteiro(e.clientX/innerWidth,e.clientY/innerHeight);},{passive:true});
(async()=>{montarSpheres();montarTabs();netbgStart();rjbgStart();
  /* v57: a URL manda no boot — `#g_radar` abre direto na aba, e o Voltar volta pra cá. */
  const _h=decodeURIComponent(location.hash.slice(1));
  await ir(_abaValida(_h)?_h:'i_cockpit');
  if(_h&&!_abaValida(_h))_hashInvalido(_h);
  marcarValores(document.getElementById('view'));
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
uiLigarA11y();
uiLigarSpotlight();
uiLigarDialogo();
/* v59 · o primeiro domínio delegado por `data-*`, em vez de citar 12 nomes globais em `onclick`.
   Vem junto dos outros "ligar" e ANTES do primeiro render de propósito: o ouvinte mora no
   `document`, então precisa existir antes de qualquer tela que use `data-vinc` ser pintada.
   Ver o bloco `VINC_ACOES` em `abas/index.js` para a razão de ser Vínculos o primeiro. */
ligarVinculos();
/* Um ouvinte para TODAS as métricas clicáveis do painel — ver nucleo/drill.js. */
ligarDrill();
sobrioAoMudar(() => { nebulaViva(); nucleoViva(); holoRJ(); mesaViva(); conscienciaRever();
                      energiaRever(); });
conscienciaLigar(ritmoEstado);
sabreStart({
  /* v59 · `energiaPacote` entra no MESMO gancho da onda do piso e usa a MESMA tabela de domínio:
     um evento real, um pacote viajando do instrumento até o núcleo. Não é uma taxa imitada — é a
     taxa, porque cada traço na tela corresponde a uma linha que entrou no banco. Barramento
     calado = nada se move, e o laço de animação nem chega a existir. */
  aoEvento: ev => { nucleoPulse(ev.tipo); energiaPacote(ev.tipo); ritmoEvento();
                    conscienciaEvento(ev, ev.tipo === 'alerta' || ev.tipo === 'radar'); },
  aoBatimento: ev => { ritmoTelemetria(ev.load1, ev.sweeps); conscienciaBatimento(ev); },
  podeAnimar: () => !_redMotion && !_sobrio,
});

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

portalStart();

/* ══ v49 · MEDIR A MÁQUINA E RECUAR ═════════════════════════════════════════════════════════════
   Mede quadros por segundo com a página em repouso e, se a máquina não sustenta animação, liga
   `body.fps-baixo` — que desliga as 15 animações infinitas que animam `filter`, spread de
   `box-shadow` ou `background-position` (as que forçam repintura por quadro). Ver o bloco
   "MODO SÓBRIO MEDIDO" no CSS.

   POR QUE MEDIDO E NÃO ADIVINHADO. Sniff de user-agent, contagem de núcleos e `deviceMemory` erram
   feio (esta VM tem 11 GB e 2 vCPU sem GPU; um celular tem 8 núcleos e compõe melhor). O que
   importa é uma coisa só: esta máquina, agora, entrega quadro? Então conta quadro.

   Roda DEPOIS da intro (a intro é o pico de carga e mediria o transiente, não o regime) e amostra
   1 s. Não fica em laço — só remede quando a aba volta do segundo plano (ver v52 abaixo).
   `_redMotion` continua um eixo separado: preferência declarada do usuário, não capacidade.

   v52 · MEDIR ABA OCULTA MEDE O NAVEGADOR, NÃO A MÁQUINA. Com `document.hidden` o Chrome congela
   o rAF: `passo` roda UMA vez, 60 s depois, e a conta dava 1·1000/60000 ≈ 0 fps. Quem abrisse o
   painel em aba de segundo plano (link em nova aba, restaurar sessão) caía em modo sóbrio PARA
   SEMPRE — medido no navegador do it-campo: hidden=true, _jfnFps=0, _sobrio=true, 7 `.nu-chip` no
   DOM e mesa em branco. Agora: não mede oculto, remede ao voltar, e o sóbrio é REVERSÍVEL. */

/* 2,6 s = fim da intro (1,96 s) + folga para o primeiro render de conteúdo assentar. */
setTimeout(_medirFps,2600);

/* ═══════════ v10 "AGÊNCIA" — avisos da casa, erro humano, orçamento de vida ═══════════ */// Orçamento de vida: aba do navegador oculta → toda animação CSS pausa (os canvas já pausam).
document.addEventListener('visibilitychange',()=>document.documentElement.classList.toggle('rest',document.hidden));
// Esferas roláveis sem scrollbar: fade lateral só quando há conteúdo escondido.
function _sphMask(){const s=document.querySelector('.spheres');if(!s)return;
  s.classList.toggle('scrollx',s.scrollWidth>s.clientWidth+4&&s.scrollLeft<s.scrollWidth-s.clientWidth-4);}
/* v59: a órbita é geometria medida em pixel — redimensionar a janela move os oito instrumentos e
   o núcleo, e os fios ficariam ligando posições que não existem mais. `energiaRever` só faz algo
   se o `#ck-orbita` estiver na tela, então nas outras 59 abas isto custa uma busca por id. */
addEventListener('resize',()=>{_sphMask();energiaRever();});
document.addEventListener('scroll',e=>{if(e.target&&e.target.classList&&e.target.classList.contains('spheres'))_sphMask();},true);
setTimeout(_sphMask,600);

/* ── v27 TATO: a onda nasce onde o dedo tocou ────────────────────────────
   Um listener so, delegado no documento, em vez de um por controle: o painel
   troca o innerHTML de #view a cada aba, entao listener por elemento morreria
   junto com a aba. Delegacao sobrevive a troca.
   `pointerdown` e nao `click`: a resposta tem que sair no TOQUE, nao na
   soltura — 100ms de atraso ja le como travado.                            */
(function _ligarTato(){
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
(function _ligarObservadorDeValor(){
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

/* ═══════════════════════════════════════════════════════════════════════════════════════════
   PONTE DE GLOBAIS — o que os ~161 handlers inline do painel precisam achar no `window`.

   POR QUE ISTO EXISTE, E POR QUE EXISTE AGORA. O painel monta atributos `on*="..."` dentro dos
   59 renders, e o navegador avalia esse código no escopo GLOBAL. Enquanto o painel é UM script
   clássico, isso sai de graça — e este bloco é literalmente um no-op, porque todo nome citado
   aqui já está no escopo. No instante em que o fonte virar módulos com build (`--format=iife`),
   tudo passa a viver dentro de uma função e cada nome precisa ser reinstalado de propósito.

   Esquecer um não derruba o boot: derruba UM botão, de UMA aba, na hora em que alguém clicar.
   Por isso a ponte nasce ANTES da migração, inerte e já sob teste — `tools/painel_ponte_check.py`
   extrai a lista de dentro dos próprios handlers e `tests/test_painel_ponte_completa.py` falha se
   faltar um nome ou se a superfície crescer.

   A ponte NÃO é o destino. O destino é delegação por `data-*` no `#view`, feita por domínio. O
   `TETO_GLOBAIS` do teste é o que torna esse progresso mensurável: cada domínio migrado baixa o
   teto. Ponte sem teto vira desculpa permanente.
   ═════════════════════════════════════════════════════════════════════════════════════════ */
/* SEGUNDA CATEGORIA DA PONTE: contrato de FERRAMENTA, não de handler.

   `TABS` não aparece em nenhum atributo `on*` — o extrator do `painel_ponte_check` (que lê os
   handlers) nunca o veria. Mas ele é lido de dentro da página por três ferramentas da casa:
   `painel_boot_check` (`typeof TABS === 'object'` é o sinal de boot vivo, e
   `Object.values(TABS).flat()` é como ele descobre as 60 abas), `painel_medir_boot` e o walker.
   Sem esta linha, o primeiro `--todas` depois do build morre com `ReferenceError: TABS is not
   defined` — e foi exatamente o que aconteceu na primeira tentativa desta migração.
   Documentado aqui porque a razão de existir não está no arquivo que o usa. */
window.TABS=TABS;
/* Mesma segunda categoria: contrato de FERRAMENTA. `revelacaoCenso()` devolve o que as gramáticas
   de revelação (v59) marcaram no último render — quantas linhas de tabela, quantos rankings,
   quantas seções. Nenhum handler o cita; quem lê é a sonda e `test_painel_revelacao`.
   Existe porque animação que NÃO acontece não quebra nada e não aparece em revisão de código: foi
   assim que o `--i` do v34 atravessou versões inteiras sem numerar uma única linha de tabela,
   enquanto o comentário afirmava que a coluna era lida de cima para baixo. O que não é medido
   apodrece calado. */
window.revelacaoCenso=revelacaoCenso;
/* Idem para a órbita do cockpit (v59): quantas linhas, quantos pacotes vivos, se o laço
   está de pé. Contrato de ferramenta — nenhum handler o cita. */
window.energiaCenso=energiaCenso;

Object.assign(window,{
  $,_acPagPick,_acPick,_jCache,_pagMais,abrirCapMestra,abrirCertame,abrirDossie,acKeydown,acao,
  autocompletar,detRodar,fazBusca,fecharCertame,fecharDossie,filtrar,filtrarPag,fxConsultar,
  gerarPdfIntel,glossario,hfToggle,instAcionar,instUgs,ir,missaoCriar,missaoListar,missaoVer,
  conscienciaToggle,montarSpheres,montarTabs,ordenar,pecaGerar,sinteseProcesso,seiArvore,seiBaixarZip,sweep,toggle,trocarEsfera,validar,
  verCruzamento,});

/* Os 19 estados que o HTML não lê — ESCREVE. `onchange="_respProc=this.value;ir('e_resp')"`,
   `onclick="_compView='dossie';ir(aba)"`, `onclick="...;esfera='geral';aba='g_acoes';..."`.
   Para estes, `Object.assign` NÃO serve: `window._respProc='X'` não atualiza um `let _respProc`
   de módulo, e a falha é MUDA — o filtro simplesmente para de responder, sem um erro no console.
   É o risco mais perigoso da migração inteira, e a única forma correta é acessor com get E set. */
(()=>{const cx={
  _cjEsf:     [()=>_cjEsf,     v=>{_set_cjEsf(v)}],      _comisView: [()=>_comisView, v=>{_set_comisView(v)}],
  _compCat:   [()=>_compCat,   v=>_set_compCat(v)],    _compDisp:  [()=>_compDisp,  v=>_set_compDisp(v)],
  _compEsf:   [()=>_compEsf,   v=>_set_compEsf(v)],    _compGrupo: [()=>_compGrupo, v=>_set_compGrupo(v)],
  _compOrd:   [()=>_compOrd,   v=>_set_compOrd(v)],    _compTermo: [()=>_compTermo, v=>_set_compTermo(v)],
  _compView:  [()=>_compView,  v=>{_set_compView(v)}],   _ctrView:   [()=>_ctrView,   v=>{_set_ctrView(v)}],
  _fantFaixa: [()=>_fantFaixa, v=>{_set_fantFaixa(v)}],  _gastosDet: [()=>_gastosDet, v=>{_set_gastosDet(v)}],
  _nuHover:   [()=>_nuHover,   v=>_setNuHover(v)],    _perGrau:   [()=>_perGrau,   v=>_set_perGrau(v)],
  _perOrdem:  [()=>_perOrdem,  v=>{_set_perOrdem(v)}],   _respProc:  [()=>_respProc,  v=>{_set_respProc(v)}],
  _riscoView: [()=>_riscoView, v=>{_set_riscoView(v)}],  aba:        [()=>aba,        v=>setAba(v)],
  esfera:     [()=>esfera,     v=>setEsfera(v)],
};
for(const n in cx)Object.defineProperty(window,n,{get:cx[n][0],set:cx[n][1],configurable:true});
})();
