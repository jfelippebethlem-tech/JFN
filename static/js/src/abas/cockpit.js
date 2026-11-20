/* O COCKPIT — a aba Início, e o único ecrã do painel que é um instrumento ao vivo em vez de uma
 * consulta. Saiu de `abas/index.js` na v59 (§6.2-B do PAINEL-v58).
 *
 * POR QUE O CORTE FOI POR DOMÍNIO, E NÃO POR ESFERA. O plano propunha separar as 59 telas por
 * esfera e apontava o obstáculo: seis renders aparecem em duas ou três esferas
 * (`renderSobrepreco`, `renderConluio`, `renderPoder`, `renderAditivos`, `renderEscalada`,
 * `renderComparador`), e classificá-los obrigaria a escolher um dono arbitrário ou duplicar.
 *
 * O obstáculo desaparece quando o eixo muda: um DOMÍNIO não é uma esfera. O comparador é um
 * domínio que duas esferas consomem — e um módulo importado por dois lugares é a coisa mais
 * banal que existe. Cortar por domínio dá módulos coesos, e as seis telas compartilhadas deixam
 * de ser um problema porque nunca foram um; eram um problema do eixo errado.
 *
 * O que mora aqui: a tela (`renderCockpit`), a montagem depois do paint (`ckBoot`), os oito
 * instrumentos (`ckCard`/`ckFill`), o ticker (`ckPush`) e o puxador de dados (`ckPull`), mais o
 * bloco de funções mestras gerado de `capabilities.yaml`.
 *
 * O `ckBoot` é chamado pelo `ir()` DEPOIS de pintar, e não por um timer daqui: o v44 reagendava
 * até achar o `#ck-grid`, mas o grid que ele achava era o do quadro ANTERIOR — o `innerHTML` final
 * entrava depois e jogava fora o que tinha sido montado. Timer não serializa com paint assíncrono;
 * chamada após o paint, sim.
 *
 * Sem efeito de topo.
 */
import {$, esc} from '../nucleo/dom.js';
import {fmtN, fmtD, fmtRc, rot} from '../nucleo/formato.js';
import {J, erroHumano} from '../nucleo/http.js';
import {v63InicioHtml, v63InicioMontar} from '../v63/inicio.js';
import {reatorMontar} from '../cena/reator.js';
import {aoVivoLigar} from '../aovivo/estado.js';
import {preocupacoesMontar} from './preocupacoes.js';
import {mapaMontar} from '../mapa/territorio.js';
import {flipAoVivo} from '../ui/movimento.js';
import {aba, esfera} from '../app/estado.js';
import {nuSet, NU_NODES} from '../cena/index.js';
import {a11yfy} from '../ui/index.js';
import {galaxiaPreviewHtml, galaxiaPreviewMontar} from './galaxia_inicio.js';   // 16/11: preview leve da galáxia (fim do Início)

// ═══ COCKPIT (aba Início) — command deck ao vivo ═══
let _ckTimer=null;
/* ── TERRITÓRIO GLOBAL — o Estado do RJ atrás de toda aba ──────────────────
   Desenha a malha REAL do IBGE num offscreen (1× por tamanho/cor), tingida pela
   cor da esfera ativa, e no RAF passa só uma varredura de radar + respiração
   (barato). Pausa em document.hidden e reduced-motion. O território re-tinge
   quando a esfera muda (rjbgTinge). O dado sempre lê primeiro: opacity baixa. */

/* v10: _ckSpark/_ckSynth removidos — gerador de série sintética (Math.random) sem caller,
   proibido pelo PRODUCT.md ("dado sintético = proibido"). Sparkline real, quando vier, nasce de série da API. */
function _ckCount(el,to,fmt,ms=1000){if(!el)return;const rm=matchMedia('(prefers-reduced-motion:reduce)').matches;if(rm||to==null){el.textContent=fmt(to);return;}
  const t0=performance.now();(function s(t){const p=Math.min(1,(t-t0)/ms),e=1-Math.pow(1-p,3);el.textContent=fmt(to*e);if(p<1)requestAnimationFrame(s);else el.textContent=fmt(to);})(performance.now());}

export async function renderCockpit(){
  /* v61: o mapa do território (centro-esquerda) e a coluna do reator (direita) entram ANTES do
     resto; a mesa de vigília antiga segue no DOM, oculta pelo CSS, e o laço dela não é iniciado. */
  const v61=`<section class="c61-mapa" id="c61-mapa" aria-label="Mapa do território"></section>
    <aside class="c61-lado" id="c61-lado"><div class="c61-reator" id="c61-reator"></div>
      <button type="button" class="chip c61-ir-motores" onclick="ir('s_motores')">Motores · ver todos</button></aside>
    <section class="c61-preoc" id="c61-preoc" aria-label="Sinais críticos"></section>`;
  /* v63: o herói e as quatro seções no estilo Relay entram ANTES do cockpit (`v63/inicio.js`) */
  const html=`${v63InicioHtml()}<div class="ck ck61">${v61}
    <div class="ck-ticker"><div class="lane" id="ck-lane"><span>◉ sincronizando o barramento — os primeiros sinais chegam em segundos…</span></div></div>
    <div class="ck-hero">
      <div class="ck-lead" role="link" tabindex="0" style="cursor:pointer" title="Abrir as compras com sobrepreço (Comparador › Economia possível)"
        onclick="if(!event.target.closest('[data-v60-desc]')){_compView='economia';_compEsf='todas';ir('e_comp')}"
        onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();_compView='economia';_compEsf='todas';ir('e_comp')}"><div class="ck-eye">Economia potencial identificada</div>
      <div class="ck-big" id="ck-econ">R$ ——</div>
      <div class="ck-sub" id="ck-sub">Quanto os cofres públicos deixariam de gastar se cada compra acima da mediana tivesse pago a <b>mediana de mercado</b> do item.</div>
      <span class="chip" style="margin-top:8px;display:inline-block">Ver as compras →</span></div>
      <!-- caixa 'vedada' retirada em 19/11/2026: universo vazio e três defeitos de alcance/vigência medidos (COR-04) -->
    </div>
    <!-- v59 · A ÓRBITA. A mesa de vigília era um bloco EMPILHADO entre o herói e os cartões: a
         peça central da tela lida como mais uma faixa da página, e os oito instrumentos abaixo
         dela pareciam uma lista sem relação com o que a mesa mostra — quando são exatamente as
         leituras que chegam por ela.

         Aqui a mesa vira o CENTRO e os instrumentos orbitam, quatro de cada lado, ligados ao
         núcleo por linhas de energia com pacotes viajando na taxa REAL de eventos do barramento.

         O "#ck-grid" continua sendo UM container com os mesmos oito filhos e o mesmo id — quem
         distribui em volta é o CSS, com "display:contents" promovendo os cartões a itens da
         grade da órbita. Reescrever o "ckBoot" para dois containers seria mexer no caminho que
         monta a tela viva para resolver um problema que é de layout. Em tela estreita nada disso
         liga: a órbita não existe abaixo de 1100px e a pilha continua a de sempre. -->
    <div class="ck-orbita" id="ck-orbita">
    <div class="ck-nucleo" id="ck-nucleo"><canvas id="nucleo-cv" aria-hidden="true"></canvas>
      <div class="nu-legend">Mesa de vigília · cada feixe = um domínio · onda no piso = evento real</div>
      <div class="nu-hud" id="nu-hud" aria-live="polite">vigília armada — aguardando o primeiro evento do barramento</div>
      <div class="nu-sweep" id="nu-sweep" aria-live="polite"></div>
      <div id="nu-chips"></div></div>
    <!-- RECOMENDAÇÃO EDITORIAL PENDENTE DE DECISÃO DO DONO (rodada 5, 2026-07-31):
         os 6 números deste ck-grid são os MESMOS já rotulados na mesa de vigília logo acima
         (nu-chips de NU_NODES: radar, alertas, mesma sala, empresa morta, comunidades,
         compras). O leitor lê o mesmo dado duas vezes em uma tela — e o cartão, por ser
         maior, rouba a leitura da mesa, que é a peça que o Início existe para mostrar.
         Sugestão do auditor: remover os KPIs e deixar a mesa (o chip já traz rótulo+número).
         NÃO EXECUTADA — cortar conteúdo do Início é decisão do dono, não do auditor. -->
    <div class="ck-grid" id="ck-grid"></div>
    <canvas class="ck-energia" id="ck-energia" aria-hidden="true"></canvas>
    </div>
    <!-- 14/11/2026: a grade de motores e o cruzamento de motores foram para a esfera Sistema
         (aba s_motores) — pedido do dono: configurações e funcionamento numa aba própria. -->
    <!-- 14/11/2026: "Funções mestras" e "Fontes de dados — frescor" foram para a esfera Sistema
         (abas s_comandos e s_motores): o Início fica com o que impressiona — reator, mapa, números
         e grandes preocupações (pedido do dono). -->
    ${galaxiaPreviewHtml()}
    </div>`;
  /* v48: quem monta o cockpit e o ir(), DEPOIS de pintar — nao um timer daqui.
     O v44 reagendava ate achar o ck-grid, mas o grid que ele achava era o do
     quadro ANTERIOR: o innerHTML final entrava depois e jogava fora o que
     havia sido montado (canvas voltava a 300x150, os 7 nos do mapa sumiam).
     Timer nao serializa com paint assincrono; chamada apos o paint, sim. */
  return html;
}

// ═══ NÚCLEO ORGÂNICO — a mesma informação do cockpit em forma viva (dados/eventos REAIS) ═══

export function ckCard(id,lab,valc,dotc,href,spark){return `<div class="ck-inst" id="cki-${id}" onclick="ir('${href}')">
  <div class="k"><span class="lab">${lab}</span><span class="dot ${dotc}"></span></div>
  <div class="val ${valc}">—</div><div class="meta esperando">lendo o barramento — o número aparece aqui</div>
  </div>`;}
function ckFill(id,{num,txt,meta}={}){const el=$('cki-'+id);if(!el)return;const v=el.querySelector('.val'),m=el.querySelector('.meta');
  /* v61: a 1ª leitura conta de 0 ao valor; quando o número MUDA numa leitura seguinte (a cada 30 s),
     ele troca com flip + lâmina de luz em vez de recontar do zero. */
  const _novo=num!=null&&isFinite(num)?fmtN(Math.round(num)):(txt!=null?String(txt):null);
  const _mudou=_novo!=null&&el.dataset.v61Val!==undefined&&el.dataset.v61Val!==_novo;
  if(_novo!=null&&el.dataset.v61Val===_novo){/* mesmo valor: nada a animar */}
  else if(_mudou){v.textContent=_novo;flipAoVivo(el);}
  else if(num!=null&&isFinite(num))_ckCount(v,num,x=>fmtN(Math.round(x)));else if(txt!=null)v.textContent=txt;
  if(_novo!=null)el.dataset.v61Val=_novo;
  if(meta!=null){m.innerHTML=meta;m.classList.remove("esperando");}
  nuSet(id,num!=null&&isFinite(num)?Math.round(num):txt);   // espelha no Núcleo orbital
}
let _ckTick=[];
function ckPush(items){items.forEach(x=>_ckTick.push(x));const L=$('ck-lane');if(L&&_ckTick.length)L.innerHTML=_ckTick.concat(_ckTick).map(x=>`<span class="${x.c||''}">${x.h}</span>`).join('');}
export function ckBoot(){
  const g=$('ck-grid');if(!g)return;
  /* v60: grade de 9 na ordem do brief, com ALERTAS (o total já vinha de `/api/compliance/painel`
     para o chip da mesa — é o mesmo número, agora também em cartão). */
  /* 19/11/2026 (COR-04, FP medida em fonte primária — ~/vault/aprendizados/fp-medida-*-2026-11-19.md): saíram
     Radar (24 de 26 scores inflados), Mesma sala (0 de 6 grupos altos se sustentam) e Caro + suspeito (universo
     vazio; REFUTADO em 13/11). As abas continuam; o número só volta à capa depois de corrigido e medido de novo.
     20/11/2026: saiu também 'Ente com maior indício de sobrepreço' (juiz reprovou 2×: o topo era a Prefeitura do Rio com
     R$ 6.990,40 em 2 compras — desproporcional para manchete e fora do escopo estadual). O dado segue na aba Compras. */
  g.innerHTML=[ckCard('alertas','Alertas','ckrose','bgrose','e_alertas'),
    ckCard('fenix','Pago a CNPJ baixado ou inapto','ckrose','bgrose','g_fenix'),
    ckCard('compras','Compras auditáveis','','bgteal','e_comp'),
    ckCard('com','Comunidades','','bgteal','g_comun'),
    ckCard('lift','Melhor detector (lift)','','bgteal','g_retro')].join('');
  a11yfy(g);   // ck-grid é preenchido após o a11yfy do ir() → operar os cards por teclado aqui
  aoVivoLigar();reatorMontar($('c61-reator'));mapaMontar($('c61-mapa'));preocupacoesMontar($('c61-preoc'));   // v61: o reator vivo no lugar da mesa
  v63InicioMontar();          // v63: depois do paint, como o resto do cockpit
  galaxiaPreviewMontar($('gx-prev'));   // 16/11: canvas 2D pintado uma vez; a galáxia 3D abre em /galaxia
  ckPull(true);
  clearInterval(_ckTimer);_ckTimer=setInterval(()=>{if(!document.hidden&&aba==='i_cockpit')ckPull(false);},30000);
}
function ckPull(first){
  _ckTick=[];
  /* O chip anunciava `lista_alertas.length` — o TAMANHO DA PÁGINA (40), não a contagem
     (7.058). Trocar uma grandeza pela outra no chip mais visível da mesa é o mesmo pecado
     de "empenho como total pago": quem tirasse print levava 40 onde há 7.058. A manchete
     passa a ser `alertas.total`; a página vive no title, explícita, nunca sozinha.
     E `if(n)` engolia o zero: sem total, zero e falha eram o mesmo "—". Agora zero é zero
     (o número) e falha é falha (o motivo no title). */
  J('/api/compliance/painel').then(d=>{
    const a=(d&&d.alertas)||null,el=$('nu-alertas');
    if(!a||a.total==null){nuSet('alertas',null);if(el)el.title=erroHumano(d&&d.erro);
      /* v60: INDISPONÍVEL ≠ 0 — o cartão fica no traço e diz o motivo */
      const m=$('cki-alertas')&&$('cki-alertas').querySelector('.meta');
      if(m){m.textContent='indisponível — '+erroHumano(d&&d.erro);m.classList.remove('esperando');}
      return;}
    nuSet('alertas',a.total);
    // só alerta NÃO descartado (o servidor filtra desde 13/11/2026); as três gravidades somam o total
    ckFill('alertas',{num:a.total,meta:`<b class="ckrose">${fmtN(a.alta||0)}</b> de gravidade alta · ${fmtN(a.media||0)} média`+(a.baixa!=null?` · ${fmtN(a.baixa)} baixa`:'')+` — descartados fora da conta · <b>fila de triagem, não irregularidade</b>: conferidos 34 na fonte primária em 19/11/2026, 13 não se sustentaram`});   // sem `#cki-alertas` (v60 desligado) o ckFill sai sem fazer nada
    if(el)el.title=`${fmtN(a.alta||0)} de gravidade alta · ${fmtN(a.media||0)} média${a.baixa!=null?' · '+fmtN(a.baixa)+' baixa':''} (descartados fora)`
      +` — a lista da tela mostra as ${fmtN((d.lista_alertas||[]).length)} primeiras`;});
  // card 'mesma sala' retirado em 19/11/2026 (FP medida 100% nos 6 grupos altos — COR-04); a aba Riscos segue
  J('/api/comparador/economia').then(d=>{if(!d||!d.ok){
      // herói nunca fica preso no placeholder: erro vira mensagem humana + retry
      const big=$('ck-econ');if(big&&/—/.test(big.textContent)){big.textContent='—';
        if($('ck-sub'))$('ck-sub').innerHTML=erroHumano(d&&d.erro);}
      return;}
    // Refeito em 2026-11-13 ("não pode ter margem pra erro em nada"; revisão D4/D5):
    // o herói era R$ 5,98 mi — 89% Prefeitura do Rio sem dizer a esfera, os 4 maiores certames
    // eram ATA de registro de preços (quantidade estimada, não compra), e somava QUALQUER compra
    // acima da mediana, inclusive orgânico de agricultura familiar e óleo de marca exigida.
    // Agora o herói só soma indício de sobrepreço (≥2× a mediana do MESMO item na MESMA unidade)
    // CONFERIDO no PNCP e fora de ata; Estado e Prefeitura aparecem separados; o resto é dito.
    const pe=d.por_esfera||{},est=pe.estado||{},pre=pe.prefeitura||{};
    _ckCount($('ck-econ'),d.economia_total||0,fmtRc,first?1300:900);
    if($('ck-sub'))$('ck-sub').innerHTML=
      `Indícios de sobrepreço <b>conferidos no PNCP</b> (≥ 2× a mediana do mesmo item, na mesma unidade), fora de ata de registro de preços: `
      +`<b>Estado ${fmtRc(est.economia||0)}</b> · <b>Prefeitura do Rio ${fmtRc(pre.economia||0)}</b>.`
      +(d.economia_pendente>0?` Mais <b>${fmtRc(d.economia_pendente)}</b> em ${fmtN(d.n_compras_pendentes)} compras <b>pendentes de conferência</b> (não somadas).`:'')
      +(d.economia_ata_teto>0?` Ata de registro de preços: até ${fmtRc(d.economia_ata_teto)} (teto — quantidade estimada).`:'')
      +` Quantidade homologada, não OB paga.`;
    ckFill('compras',{num:d.n_compras_acima_mediana,meta:'compras com indício conferido no PNCP'});
    const o=d.por_orgao&&d.por_orgao[0],onm=o?(o.orgao||''):'';
    // mesma base do herói (conferido, homogêneo) — antes vinha do conjunto genérico e punha
    // aluguel de imóvel comparado pela mediana de outros imóveis (R$ 25,9 mi "a recuperar").
    ckFill('orgao',{txt:o?fmtRc(o.economia):'—',meta:o?`<b>${esc(onm)}</b> (ente comprador) — diferença hipotética sobre a mediana nos indícios conferidos (quantidade homologada no PNCP, não OB paga)`:'nenhum indício conferido ainda'});
    ckPush([{c:'g',h:`✦ sobrepreço conferido <b>${fmtRc(d.economia_total||0)}</b> em ${fmtN(d.n_compras_acima_mediana)} compras · ${fmtN(d.n_compras_pendentes||0)} pendentes`}]);});

  J('/api/intel/comunidades').then(d=>{if(!d||!d.ok)return;ckFill('com',{num:d.n,meta:'clusters família-empresa-órgão (Louvain)'});});
  // Revisão D8 (13/11/2026): circulares (usam sanção como insumo) saem do CÁLCULO no servidor; o filtro aqui
  // fica como segunda trava. O rótulo diz o que o número mede: sancionados de qualquer época ou ente, com n.
  J('/api/intel/lift').then(d=>{if(!d||!d.ok)return;const b=(d.detectores||[]).filter(x=>!x.circular).sort((a,c)=>(c.lift||0)-(a.lift||0))[0];
    ckFill('lift',{txt:b?fmtD(b.lift,2)+'×':'—',meta:b?`<b>${rot(b.detector)}</b> marca ${fmtD(b.lift,2)}× mais fornecedores sancionados que a base (${fmtN(b.sancionados)} de ${fmtN(b.n)}; sanção de qualquer época ou ente — não mede irregularidade)`
      +((d.circulares||[]).length?` · ${fmtN(d.circulares.length)} detectores circulares fora do cálculo`:''):'—'});});
  // Revisão D6 (2026-11-13): o ticker dizia "(sancionada)" para os 5 casos e NENHUM estava
  // sancionado na data da compra. O sinal agora vem do servidor já com vigência e alcance;
  // o rótulo diz qual sinal é, e "sancionada depois" não se passa por vedação.
  J('/api/intel/fenix').then(d=>{if(!d||!d.ok)return;
    // "Pago a empresa MORTA" só vale para quem recebeu DEPOIS da baixa. O card mostrava
    // `total_defunta` — o conjunto AMPLO de "hoje está baixada e um dia recebeu" — e dizia
    // R$ 4 bi. Medido: só R$ 18,3 mi (54 empresas) foram pagos APÓS a baixa; os outros
    // R$ 2,56 bi são pagamentos anteriores à morte, que não têm nada de irregular (a Cruz
    // Vermelha, baixada em 2005, sozinha respondia por R$ 305 mi). O número da manchete
    // passa a ser o confirmado; o amplo vira contexto na linha de baixo, sem sumir.
    // Verificação de 13/11/2026: a soma ainda trazia cartório extinto, órgão público, filial baixada de matriz
    // ATIVA e pagamento judicial. O servidor os tira da soma e os conta à parte (`fora_da_manchete`); o card diz
    // isso e diz que é INDÍCIO A CONFERIR — inapta não é extinta, e cadastro irregular não prova inexecução.
    const _fm=d.fora_da_manchete||{},_fmN=k=>fmtN((_fm[k]||{}).n||0);
    ckFill('fenix',{txt:fmtRc(d.total_apos_baixa||0),
      meta:`<b>${fmtN(d.n_defunta_confirmada||0)}</b> CNPJs receberam <b>depois</b> da baixa ou inaptidão na Receita — <b>indício a conferir</b> no processo`
           +(d.n_fora_da_manchete?` · fora da conta: ${_fmN('natureza_publica')} órgãos públicos, ${_fmN('cartorio')} cartórios, ${_fmN('filial_de_matriz_ativa')} filiais de matriz ativa, ${_fmN('pagamento_judicial')} pagamentos judiciais`:'')});
    if(d.n_defunta_confirmada)ckPush([{c:'a',h:`◉ <b>${fmtRc(d.total_apos_baixa)}</b> pagos a ${fmtN(d.n_defunta_confirmada)} CNPJs DEPOIS da baixa/inaptidão na Receita — indício a conferir`}]);});
}


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
