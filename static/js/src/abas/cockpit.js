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
import {$, esc, svgIco, card, kpi, sec, cover, corta, clk} from '../nucleo/dom.js';
import {fmtN, fmtD, fmtR, fmtRc, rot} from '../nucleo/formato.js';
import {J, erroHumano} from '../nucleo/http.js';
import {_redMotion} from '../capacidade/estado.js';
import {aba, esfera} from '../app/estado.js';
import {nuSet, nuSweepPoll, NU_NODES, nucleoStart} from '../cena/index.js';
import {energiaLigar} from '../cena/energia.js';
import {a11yfy, abrirDossie} from '../ui/index.js';

// ═══ COCKPIT (aba Início) — command deck ao vivo ═══
export let _ckTimer=null;
/* ── TERRITÓRIO GLOBAL — o Estado do RJ atrás de toda aba ──────────────────
   Desenha a malha REAL do IBGE num offscreen (1× por tamanho/cor), tingida pela
   cor da esfera ativa, e no RAF passa só uma varredura de radar + respiração
   (barato). Pausa em document.hidden e reduced-motion. O território re-tinge
   quando a esfera muda (rjbgTinge). O dado sempre lê primeiro: opacity baixa. */

/* v10: _ckSpark/_ckSynth removidos — gerador de série sintética (Math.random) sem caller,
   proibido pelo PRODUCT.md ("dado sintético = proibido"). Sparkline real, quando vier, nasce de série da API. */
export function _ckCount(el,to,fmt,ms=1000){if(!el)return;const rm=matchMedia('(prefers-reduced-motion:reduce)').matches;if(rm||to==null){el.textContent=fmt(to);return;}
  const t0=performance.now();(function s(t){const p=Math.min(1,(t-t0)/ms),e=1-Math.pow(1-p,3);el.textContent=fmt(to*e);if(p<1)requestAnimationFrame(s);else el.textContent=fmt(to);})(performance.now());}
export const _CK={teal:'#5fd9ff',gold:'#eec276',good:'#5fe0a1',amber:'#f2b544',rose:'#ff7a8a'};

/* ══ v49 · UM BOTÃO POR FUNÇÃO MESTRA (pedido do dono) ══════════════════════════════════════════
   A lista vem de `CAPS_MESTRAS` (static/js/caps.js), GERADA de capabilities.yaml pelo
   tools/gerar_superficie_caps.py. Escrever os botões aqui à mão criaria a quinta cópia da mesma
   lista — e a casa já tem cicatriz de lista duplicada divergindo em silêncio.

   As rotas aparecem como string literal no arquivo gerado de propósito: é assim que as duas
   catracas de rota (órfãs, teto 0; e sem-superfície) enxergam que a capacidade tem porta de
   entrada. Fosse `fetch('/api/lista')` em runtime, elas acusariam órfãs que não são órfãs. */
export function blocoComandosMestres(){
  if(typeof CAPS_MESTRAS==='undefined'||!CAPS_MESTRAS.length)return '';
  const grupos={};
  for(const c of CAPS_MESTRAS)(grupos[c.grupo]=grupos[c.grupo]||[]).push(c);
  let h=`<div class="ck-caps"><div class="ck-eye">Funções mestras — ${CAPS_MESTRAS.length} comandos, um clique cada</div>`;
  for(const g of Object.keys(grupos)){
    const gi=grupos[g][0]||{};
    h+=`<div class="caps-g"><div class="caps-gt">${gi.grupo_ic?`<span class="caps-gi" aria-hidden="true">${svgIco(gi.grupo_ic)}</span> `:''}${esc(gi.grupo_rot||g)}</div><div class="btns" style="flex-wrap:wrap">`;
    for(const c of grupos[g]){
      const dica=esc(`${c.descricao||c.nome}${c.exemplo?'\n\nex.: '+c.exemplo:''}${c.rota?'\n\n'+c.metodo+' '+c.rota:''}`);
      h+=`<button type="button" class="btn ghost" title="${dica}" onclick="abrirCapMestra('${esc(c.id)}')">`
        +`${esc(c.nome)}${c.cmd?`<span class="caps-cmd">${esc(c.cmd)}</span>`:''}</button>`;
    }
    h+=`</div></div>`;
  }
  h+=`<div class="note">Cada botão é uma capacidade com <b>status PRONTO</b> em <code>capabilities.yaml</code>.
      O mesmo <code>cmd</code> serve o Telegram e o painel — uma fonte, várias superfícies.</div></div>`;
  return h;
}

/* O clique abre a ficha da capacidade com a rota, o método e um exemplo. NÃO dispara sozinho:
   várias destas geram peça pesada (PDF, planilha) ou escrevem no banco, e disparo acidental num
   painel de auditoria é caro — o botão leva ao comando, quem decide é a pessoa. */
export function abrirCapMestra(id){
  const c=(typeof CAPS_MESTRAS!=='undefined'?CAPS_MESTRAS:[]).find(x=>x.id===id);
  if(!c)return;
  const linha=(r,v)=>`<div style="display:flex;gap:10px;margin:6px 0"><b style="min-width:104px">${r}</b><span>${v}</span></div>`;
  const ov=$('ov'),sh=$('sheet');ov.classList.add('on');
  sh.innerHTML=`<span class="x" onclick="fecharDossie()">✕ fechar</span><div class="grab"></div>
    <div style="font-weight:800;font-size:17px;margin-bottom:4px">${esc(c.nome)}</div>
    <div class="muted" style="font-size:13px;margin-bottom:14px">${esc(c.grupo)}</div>`
    +card((c.descricao?`<p style="margin:0 0 10px">${esc(c.descricao)}</p>`:'')
      +(c.rota?linha('Rota',`<code>${esc(c.metodo)} ${esc(c.rota)}</code>`):'')
      +(c.cmd?linha('No Telegram',`<code>${esc(c.cmd)}</code>`):'')
      +(c.exemplo?linha('Exemplo',`<code>${esc(c.exemplo)}</code>`):''))
    +`<div class="note">Nada foi disparado. Vários destes comandos geram peça pesada (PDF, planilha)
      ou escrevem no banco — o painel mostra o caminho, o disparo é decisão sua.</div>`;
  a11yfy(sh);
}

export async function renderCockpit(){
  const html=`<div class="ck">
    <div class="ck-ticker"><div class="lane" id="ck-lane"><span>◉ sincronizando o barramento — os primeiros sinais chegam em segundos…</span></div></div>
    <div class="ck-hero">
      <div class="ck-lead"><div class="ck-eye">Economia potencial identificada</div>
      <div class="ck-big" id="ck-econ">R$ ——</div>
      <div class="ck-sub" id="ck-sub">Quanto os cofres públicos deixariam de gastar se cada compra acima da mediana tivesse pago a <b>mediana de mercado</b> do item.</div></div>
      <div class="ck-ved" id="ck-vedbox" hidden><span class="n" id="ck-ved">R$ —</span>
        <span class="l">pago <b style="color:var(--rose)">acima do mercado a fornecedor juridicamente vedado</b> (inidôneo), à época — o alvo mais forte.</span></div>
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
    ${blocoComandosMestres()}
    <div class="ck-fontes" id="ck-fontes"></div></div>`;
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
export function ckFill(id,{num,txt,meta}={}){const el=$('cki-'+id);if(!el)return;const v=el.querySelector('.val'),m=el.querySelector('.meta');
  if(num!=null&&isFinite(num))_ckCount(v,num,x=>fmtN(Math.round(x)));else if(txt!=null)v.textContent=txt;
  if(meta!=null){m.innerHTML=meta;m.classList.remove("esperando");}
  nuSet(id,num!=null&&isFinite(num)?Math.round(num):txt);   // espelha no Núcleo orbital
}
export let _ckTick=[];
export function ckPush(items){items.forEach(x=>_ckTick.push(x));const L=$('ck-lane');if(L&&_ckTick.length)L.innerHTML=_ckTick.concat(_ckTick).map(x=>`<span class="${x.c||''}">${x.h}</span>`).join('');}
export function ckBoot(){
  const g=$('ck-grid');if(!g)return;
  g.innerHTML=[ckCard('radar','Radar de risco','','bgteal','g_radar'),
    ckCard('com','Comunidades','','bgteal','g_comun'),
    ckCard('dossie','Caro + suspeito','ckrose','bgrose','e_comp'),
    ckCard('lift','Melhor detector (lift)','','bgteal','g_retro'),
    ckCard('fenix','Pago a empresa morta','ckrose','bgrose','g_fenix'),
    ckCard('compras','Compras auditáveis','','bgteal','e_comp'),
    ckCard('orgao','Órgão que mais economiza','ckgood','bgteal','e_comp'),
    ckCard('ninho','Ninhos de fachada','ckamber','bgamber','g_riscos')].join('');
  a11yfy(g);   // ck-grid é preenchido após o a11yfy do ir() → operar os cards por teclado aqui
  nucleoStart();
  /* v59 · a órbita. DEPOIS do `nucleoStart` e do grid preenchido: ela mede a geometria dos oito
     instrumentos e do núcleo, e medir antes de os cartões existirem daria oito retângulos de
     largura zero. Um `requestAnimationFrame` porque o `innerHTML` acima ainda não passou pelo
     layout — `getBoundingClientRect` no mesmo quadro leria a posição anterior. */
  requestAnimationFrame(()=>energiaLigar());
  ckPull(true);
  clearInterval(_ckTimer);_ckTimer=setInterval(()=>{if(!document.hidden&&aba==='i_cockpit')ckPull(false);},30000);
}
export function ckPull(first){
  _ckTick=[];
  /* O chip anunciava `lista_alertas.length` — o TAMANHO DA PÁGINA (40), não a contagem
     (7.058). Trocar uma grandeza pela outra no chip mais visível da mesa é o mesmo pecado
     de "empenho como total pago": quem tirasse print levava 40 onde há 7.058. A manchete
     passa a ser `alertas.total`; a página vive no title, explícita, nunca sozinha.
     E `if(n)` engolia o zero: sem total, zero e falha eram o mesmo "—". Agora zero é zero
     (o número) e falha é falha (o motivo no title). */
  J('/api/compliance/painel').then(d=>{
    const a=(d&&d.alertas)||null,el=$('nu-alertas');
    if(!a||a.total==null){nuSet('alertas',null);if(el)el.title=erroHumano(d&&d.erro);return;}
    nuSet('alertas',a.total);
    if(el)el.title=`${fmtN(a.alta||0)} de gravidade alta · ${fmtN(a.media||0)} média`
      +` — a lista da tela mostra as ${fmtN((d.lista_alertas||[]).length)} primeiras`;});
  if(first)J('/api/intel/ninho_sala?limite=60').then(d=>{
    /* Falhar em SILÊNCIO deixava o card em "—" — indistinguível de "não há ninho".
       Silêncio ≠ INDISPONÍVEL: se a rota não respondeu, o card diz isso. */
    if(!d||!d.ok){ckFill('ninho',{txt:'—',meta:erroHumano(d&&d.erro)});return;}
    /* Passou a ser MESMA SALA (endereço + complemento), não mesmo prédio: 'Rua da
       Assembleia 10' tem 318 CNPJs e é edifício comercial. E o grau vem do ACÚMULO de
       fatores — 2+ recebendo, maioria baixada, abertura em lote, telefone comum —,
       nunca de um sinal só. Por isso o número é menor: ele agora sustenta o que diz. */
    /* mesmo cuidado do chip de alertas: `grupos` vem cortado em ?limite=60 — quem conta
       o total é a rota (`n_alto`, `n`), não o tamanho da página que chegou. */
    const gs=(d.grupos||[]),altos=gs.filter(g=>g.grau==='alto'),
          nAlto=(d.n_alto!=null?d.n_alto:altos.length),nTot=(d.n!=null?d.n:gs.length);
    ckFill('ninho',{num:nAlto,
      meta:`grupos na <b>MESMA SALA</b> com 2+ CNPJs recebendo e <b>3+ fatores</b> de fachada`
           +(nTot>nAlto?` · outros ${fmtN(nTot-nAlto)} com menos fatores`:'')
           +` — <b>${fmtRc(d.total_recebido_ob||0)}</b> em OB no conjunto`});
    ckPush(altos.slice(0,3).map(g=>({c:'a',h:`◉ mesma sala — <b>${fmtN(g.n_recebem_ob)} de ${fmtN(g.n_cnpjs)} CNPJs recebem</b> · ${esc((g.fatores||[])[1]||'')} · ${fmtRc(g.total_recebido_ob)}`})));});
  J('/api/comparador/economia').then(d=>{if(!d||!d.ok){
      // herói nunca fica preso no placeholder: erro vira mensagem humana + retry
      const big=$('ck-econ');if(big&&/—/.test(big.textContent)){big.textContent='—';
        if($('ck-sub'))$('ck-sub').innerHTML=erroHumano(d&&d.erro);}
      return;}
    // A manchete passa a ser a economia HOMOGÊNEA — a que se apoia em comparação de
    // produto igual. Medido em 25/07/2026: dos R$ 15,6 mi, R$ 9,4 mi (60,4%) vinham de
    // grupos cuja descrição do PNCP mistura produtos diferentes ('Locação de Veículos -
    // Leves / Pesados', dispersão 300,9×; 'peça de veículo', onde parafuso e motor têm a
    // mesma descrição, 1292,5×). O total não some: vira o teto da faixa, ao lado.
    const _eco=(d.economia_homogenea!=null?d.economia_homogenea:d.economia_total);
    const _nc =(d.n_compras_homogeneas!=null?d.n_compras_homogeneas:d.n_compras_acima_mediana);
    _ckCount($('ck-econ'),_eco,fmtRc,first?1300:900);
    if($('ck-sub'))$('ck-sub').innerHTML=
      `Se cada uma das <b>${fmtN(_nc)}</b> compras acima da mediana tivesse pago a <b>mediana de mercado</b> do item`
      +(d.economia_descricao_generica>0
        ? ` — contando só itens de <b>descrição consistente</b>. Há mais <b>${fmtRc(d.economia_descricao_generica)}</b>`
          +` em itens de descrição genérica (ex.: "peça de veículo"), onde a mediana pode comparar produtos diferentes.`
        : `.`);
    ckFill('compras',{num:_nc,meta:'acima da mediana, em itens de descrição consistente'});
    const o=d.por_orgao&&d.por_orgao[0],onm=o?(o.orgao||''):'';
    // o valor grande é a caixa do NÚMERO: um nome de órgão cortado duas vezes (25 chars
    // no JS + reticências do CSS a 26px) virava "PREFEITURA …", que não informa nada.
    // O número é a economia; o nome do órgão vive inteiro na linha de baixo.
    ckFill('orgao',{txt:o?fmtRc(o.economia):'—',meta:o?`<b>${esc(onm)}</b> — potencial a recuperar`:'—'});
    // economia_total (15,6 mi/337) compara produtos DIFERENTES sob rótulo genérico — o herói
    // desta mesma tela já publica a homogênea (6,2 mi/106). O ticker ficou com o número velho:
    // duas manchetes contraditórias a 30px uma da outra. Uma fonte só, a defensável.
    ckPush([{c:'g',h:`✦ economia potencial <b>${fmtRc(d.economia_homogenea)}</b> em ${fmtN(d.n_compras_homogeneas)} compras`}]);});
  J('/api/comparador/vedada').then(d=>{if(d&&d.ok&&d.economia_vedada_total){const b=$('ck-vedbox');if(b)b.hidden=false;_ckCount($('ck-ved'),d.economia_vedada_total,fmtRc);}});
  J('/api/intel/radar?limite=6').then(d=>{if(!d||!d.ok)return;ckFill('radar',{num:d.n,meta:`fornecedores com sinal · <b class="ckrose">${fmtN(d.n_vermelho)}</b> em nível crítico`});
    ckPush((d.achados||[]).slice(0,5).map(a=>({c:'',h:`▸ RADAR ${a.score} — <b>${(a.nome||'').slice(0,30)}</b> · ${(a.sinais||[]).map(s=>rot(s.sinal)).slice(0,2).join(', ')}`})));});
  J('/api/intel/comunidades').then(d=>{if(!d||!d.ok)return;ckFill('com',{num:d.n,meta:'clusters família-empresa-órgão (Louvain)'});});
  J('/api/intel/lift').then(d=>{if(!d||!d.ok)return;const b=(d.detectores||[]).filter(x=>!x.circular).sort((a,c)=>(c.lift||0)-(a.lift||0))[0];
    ckFill('lift',{txt:b?b.lift+'×':'—',meta:b?`<b>${rot(b.detector)}</b> concentra fraude ${b.lift}× acima da base`:'—'});});
  J('/api/comparador/dossie').then(d=>{if(!d||!d.ok)return;ckFill('dossie',{num:d.n,meta:'itens pagos caro a fornecedor sancionado/fantasma'});
    ckPush((d.achados||[]).slice(0,6).map(a=>({c:'a',h:`◉ ${(a.orgao||'').slice(0,24)} pagou <b>${a.vs_mediana}× a mediana</b> — ${(a.fornecedor||'').slice(0,24)} (sancionada)`})));});
  J('/api/intel/fenix').then(d=>{if(!d||!d.ok)return;
    // "Pago a empresa MORTA" só vale para quem recebeu DEPOIS da baixa. O card mostrava
    // `total_defunta` — o conjunto AMPLO de "hoje está baixada e um dia recebeu" — e dizia
    // R$ 4 bi. Medido: só R$ 18,3 mi (54 empresas) foram pagos APÓS a baixa; os outros
    // R$ 2,56 bi são pagamentos anteriores à morte, que não têm nada de irregular (a Cruz
    // Vermelha, baixada em 2005, sozinha respondia por R$ 305 mi). O número da manchete
    // passa a ser o confirmado; o amplo vira contexto na linha de baixo, sem sumir.
    ckFill('fenix',{txt:fmtRc(d.total_apos_baixa||0),
      meta:`<b>${fmtN(d.n_defunta_confirmada||0)}</b> empresas receberam <b>depois</b> da baixa na Receita`
           +` · outras ${fmtN((d.n_defunta||0)-(d.n_defunta_confirmada||0))} estão baixadas hoje mas só receberam antes`});
    if(d.n_defunta_confirmada)ckPush([{c:'a',h:`◉ <b>${fmtRc(d.total_apos_baixa)}</b> pagos a ${fmtN(d.n_defunta_confirmada)} empresas DEPOIS da baixa na Receita`}]);});
  J('/api/fontes/frescor').then(d=>{const box=$('ck-fontes');if(!box||!d||!d.fontes)return;
    const cor=f=>{const s=(f.estado||'').toLowerCase();if(s.includes('verde')||s.includes('ok')||s.includes('fresc'))return '#5fe0a1';
      if(s.includes('amar')||s.includes('aten')||s.includes('velh'))return '#f2b544';if(s.includes('verm')||s.includes('erro')||s.includes('crit'))return '#ff7a8a';
      return f.idade_dias==null?'#63718f':(f.idade_dias<=2?'#5fe0a1':(f.idade_dias<=10?'#f2b544':'#ff7a8a'));};
    box.innerHTML=`<div class="ck-flabel">Fontes de dados — frescor ao vivo</div><div class="ck-fgrid">`+
      d.fontes.map(f=>`<div class="ck-fchip" title="${esc(f.detalhe||'')}"><span class="fled" style="background:${cor(f)}"></span>
        <span class="fnm">${esc((f.fonte||'').replace(/·/g,'·'))}</span><span class="fage">${f.idade_dias==null?'—':f.idade_dias+'d'}</span></div>`).join('')+`</div>`;});
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
