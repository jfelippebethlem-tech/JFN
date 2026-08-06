/* VÍNCULOS — beneficiário final, parentesco no QSA, histórico societário, rede de poder.
 * Saiu de `abas/index.js` na v59 (§6.2-B do PAINEL-v58).
 *
 * ERA O CASO DIFÍCIL, e vale registrar por quê: diferente do cockpit e do comparador, este
 * domínio NÃO era contíguo no arquivo. Ele vivia em duas faixas separadas por quatro blocos que
 * não têm nada a ver com ele (Peças, Fontes externas, Hub físico, Acurácia) — exatamente o
 * "interleavamento" que o plano descreve como obstáculo para subdividir `cena/`.
 *
 * O interleavamento é obstáculo para um corte por RECORTE DE TEXTO, e não para um corte por
 * domínio: as duas faixas não se referenciam por posição, só por nome, e nome não tem endereço.
 * Juntá-las aqui é a mesma operação que juntar uma faixa só, e o resultado é mais legível do que
 * o original — as doze ações do domínio finalmente cabem numa tela.
 *
 * É também o domínio que estreou a delegação por `data-vinc` (§6.2-C): nenhuma destas doze funções
 * é citada por nome em `onclick`, e nenhuma está no `window`. O mapa `VINC_ACOES` é a superfície,
 * e o ouvinte de `ligarVinculos` mora no `document` porque o `#view` é trocado a cada navegação.
 *
 * Sem efeito de topo.
 */
import {$, esc, svgIco, card, kpi, sec, cover, leitura, corta, clk} from '../nucleo/dom.js';
import {fmtN, fmtD, fmtR, fmtRc, rot} from '../nucleo/formato.js';
import {J, erroHumano} from '../nucleo/http.js';
import {abrirDossie} from '../ui/index.js';

// ═══ VÍNCULOS — beneficiário final · parentesco · histórico societário ═══
export async function renderVinculos(){
  const s=await J('/api/osint/serie_societaria');
  let h=cover('geral','Vínculos — quem está atrás da empresa, e desde quando',
    'Sobe a cadeia societária de PJ em PJ até chegar à pessoa física (<b>beneficiário final</b>), infere <b>parentesco</b> por eixos calibrados na própria base, e responde <b>desde quando</b> cada vínculo existe — usando a série de snapshots mensais da Receita. Vínculo é indício; parentesco só se prova por certidão.','🕸️');

  // Estado da série: é o denominador. Sem ele, o leitor supõe que o vínculo é atual.
  if(s.ok){
    const n=s.n_snapshots||0, st=s.vinculos_por_status||{};
    h+=`<div class="grid g2">${kpi(fmtN(n),'Snapshots mensais na série',n>=2?'var(--emerald)':'var(--rose)','📅')}
        ${kpi(esc(s.cobertura||'—'),'Janela observada',null,'🗓️')}
        ${kpi(fmtN(st.saiu||0),'Saídas de sócio detectadas','var(--amber)','🚪')}
        ${kpi(fmtN(st.ativo||0),'Vínculos vistos no último mês',null,'✅')}</div>`;
    h+=leitura(n<2
      ? `<b>Série com ${n} snapshot(s).</b> Com menos de dois meses observados, <b>saída de sócio é inobservável</b> — a base da Receita traz data de entrada e nenhuma de saída. Toda pergunta do tipo "era sócio na data do certame?" sai como INDISPONÍVEL, nunca como afastada.`
      : `Série de <b>${n} meses</b> (${esc(s.cobertura)}). Saída de sócio é inferida por <b>diferença entre snapshots</b>: precisão máxima de um mês. Sócio ausente num mês <b>não ingerido</b> não saiu — o mês não foi observado.`);
    h+=`<div class="note" style="margin-top:8px">Fonte: ${esc(s.fonte||'')}</div>`;
  }else{
    h+=card(`<div class="warn">${erroHumano(s.erro)}</div>`);
  }

  h+=sec('Consultar uma empresa');
  h+=card(`<div class="search"><span class="mag"></span>
      <input id="vinc-cnpj" placeholder="CNPJ da empresa (com ou sem pontuação)…"
             data-vinc-enter="consultar"></div>
    <div class="btns" style="margin-top:10px">
      <button type="button" class="btn" data-vinc="consultar">Beneficiário final</button>
      <button type="button" class="btn ghost" data-vinc="parentesco">Parentesco no QSA</button>
      <button type="button" class="btn ghost" data-vinc="contato">Contato compartilhado</button>
      <button type="button" class="btn ghost" data-vinc="trocas">Trocas de quadro</button>
      <button type="button" class="btn ghost" data-vinc="grafo">Rede de poder</button>
      <button type="button" class="btn ghost" data-vinc="ftm">Exportar FollowTheMoney</button>
    </div>
    <div class="btns" style="margin-top:8px">
      <button type="button" class="btn ghost" data-vinc="agentePublico">Agente público no QSA (fila)</button>
      <button type="button" class="btn ghost" data-vinc="conluioMunicipal">Conluio municipal (vencedor × perdedora)</button>
      <button type="button" class="btn ghost" data-vinc="resolucao">Resolução nome → CNPJ</button>
      <button type="button" class="btn ghost" data-vinc="interposicao">Perfil de laranja</button>
      <button type="button" class="btn ghost" data-vinc="patrimonio">Capacidade × recebido</button>
    </div>
    <div class="dim" style="margin-top:8px">Histórico de uma <b>pessoa</b> (de quais empresas foi sócia):
      <input id="vinc-pessoa" placeholder="nome do sócio…" style="margin-left:6px">
      <button type="button" class="btn ghost" style="margin-left:6px" data-vinc="historicoPessoa">Ver histórico</button>
    </div>
    <div class="dim" style="margin-top:8px">Para <b>"era sócio nesta data?"</b> informe também a data:
      <input id="vinc-data" type="date" style="margin-left:6px">
      <button type="button" class="btn ghost" style="margin-left:6px" data-vinc="naData">Verificar na data</button>
    </div>`);
  h+=`<div id="vinc-out"></div>`;

  h+=sec('Calibração dos eixos de parentesco');
  h+=card(`<div class="dim">Nenhuma base aberta brasileira publica filiação. O que sai daqui é
      inferência, e a única forma honesta de inferir é medir a <b>prevalência de cada eixo na própria
      base</b> antes de deixá-lo pesar — um eixo que acende na maioria mede a base, não o alvo.</div>
    <div class="btns" style="margin-top:10px"><button type="button" class="btn ghost" data-vinc="prevalencia">Medir na base de hoje</button></div>
    <div id="vinc-prev"></div>`);
  return h;
}

export function _vincCnpj(){const v=($('vinc-cnpj')?.value||'').replace(/\D/g,'');return v.length>=8?v:'';}

export async function vincConsultar(){
  const c=_vincCnpj(); const o=$('vinc-out'); if(!c){o.innerHTML=card('<div class="warn">Informe um CNPJ.</div>');return;}
  o.innerHTML=card('<div class="dim">subindo a cadeia societária…</div>');
  const d=await J('/api/osint/beneficiario_final?cnpj='+encodeURIComponent(c));
  if(d.ok===false){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const cob=d.cobertura||{}, ps=d.pessoas||[];
  let h=sec('Beneficiário final — '+esc(d.pj||c));
  h+=`<div class="grid g2">${kpi(fmtN(d.n_pessoas),'Pessoas físicas na cadeia',ps.length?'var(--emerald)':'var(--amber)','👤')}
      ${kpi((cob.pct==null?'—':cob.pct+'%'),'Cobertura de QSA da cadeia',cob.pct>=80?null:'var(--amber)','🔍')}
      ${kpi(fmtN(d.saltos_max),'Degraus até a pessoa física')}
      ${kpi(fmtN((d.ciclos||[]).length),'Participações cruzadas circulares',(d.ciclos||[]).length?'var(--rose)':null,'🔄')}</div>`;
  h+=leitura(esc(d.motivo||''));
  if(ps.length){
    h+=`<div class="grid">`+ps.map(p=>card(
      `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
         <div style="min-width:0"><div style="font-weight:700">${esc(p.rotulo)}
           ${p.documentado?'<span class="tag">documento confirmado</span>':'<span class="tag amber">CPF mascarado na fonte</span>'}</div>
           <div class="muted" style="font-size:12.5px;margin-top:3px">${esc((p.caminho||[]).join(' → '))}</div></div>
         <div class="right"><div class="num" style="font-weight:800;font-size:20px">${(p.confianca*100).toFixed(0)}%</div>
           <div class="dim">confiança · ${p.saltos} degrau(s)</div></div></div>`,
      p.confianca>=0.85?'hl':'')).join('')+`</div>`;
  }
  if((d.ciclos||[]).length){
    h+=card(`<div style="font-weight:700">Participação cruzada circular</div>`+
      (d.ciclos||[]).map(c=>`<div class="muted" style="font-size:12.5px">${esc((c||[]).join(' → '))}</div>`).join('')+
      leitura('Empresa A sócia da B, que é sócia da A. É lícito, e é também a estrutura que mais dificulta identificar quem manda — cabe olhar o contrato social.'));
  }
  h+=`<div class="note">${esc((d.documentacao||{}).nota||'')}</div>`;
  h+=`<div class="note">${esc((d.temporalidade||{}).nota||'')}</div>`;
  h+=`<div class="note">${esc(cob.nota||'')}</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  o.innerHTML=h;
}

export async function vincContato(){
  // TELEFONE E E-MAIL COMPARTILHADOS — as arestas mais fortes da régua depois de `mesma_sala`
  // (0,70 e 0,80), sobre 6.171.766 estabelecimentos da Receita que estavam indexados e SEM UM
  // ÚNICO CONSUMIDOR. Duas empresas de raízes diferentes que dividem central telefônica é o sinal
  // clássico de mesma mão por trás: na primeira amostra real, APPA SERVIÇOS TEMPORÁRIOS e
  // OBJETIVA SERVIÇOS TERCEIRIZADOS, ambas de terceirização, no 1147593220.
  const c=_vincCnpj(); const o=$('vinc-out'); if(!c){o.innerHTML=card('<div class="warn">Informe um CNPJ.</div>');return;}
  o.innerHTML=card('<div class="dim">cruzando telefone e e-mail em 6,17 milhões de estabelecimentos…</div>');
  const d=await J('/api/osint/contato_compartilhado?cnpj='+encodeURIComponent(c));
  if(d.erro){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const ar=d.arestas||[], cob=d.cobertura||{}, desc=d.descartados||{};
  let h=sec('Contato compartilhado — '+esc(c));
  h+=`<div class="grid g2">${kpi(fmtN(ar.length),'Empresas ligadas por contato',ar.length?'var(--amber)':null,'📞')}
      ${kpi(fmtN(cob.com_telefone),'Alvos com telefone publicado')}
      ${kpi(fmtN(cob.com_email),'Alvos com e-mail publicado')}
      ${kpi(fmtN(Object.values(desc).reduce((s,x)=>s+x,0)),'Contatos DESCARTADOS por guarda','var(--dim)','🚫')}</div>`;
  h+=leitura('Contato dividido é indício de mesma administração, não prova: escritório contábil, central de atendimento e grupo econômico legítimo produzem o mesmo sinal. Por isso o e-mail de contabilidade cai para <b>mesmo_contador</b> (0,30) e o que passa do teto de fan-out sai fora — o corte é medido, e o que fica de fora está contado abaixo.');
  if(ar.length){
    h+=`<div class="grid">`+ar.slice(0,40).map(a=>card(
      `<div style="display:flex;justify-content:space-between;gap:10px">
         <div style="min-width:0"><div style="font-weight:700">${esc(a.para)}</div>
           <div class="muted" style="font-size:12.5px">${esc(a.detalhe||'')} · ${esc(a.tipo)}</div>
           <div class="dim" style="font-size:12px;margin-top:3px">${esc(a.explicacao_inocente||'')}</div></div>
         <div class="right"><div class="num" style="font-weight:800;font-size:20px">${(a.forca*100).toFixed(0)}%</div>
           <div class="dim">força · ${fmtN(a.n_no_grupo)} no grupo</div></div></div>`,
      a.forca>=0.7?'hl':'')).join('')+`</div>`;
    if(ar.length>40) h+=`<div class="note">40 de ${fmtN(ar.length)} exibidas.</div>`;
  } else {
    h+=card('<div class="dim">Nenhuma empresa dividindo contato dentro dos tetos medidos. Ausência de aresta não é ausência de vínculo — é ausência <b>por esta via</b>.</div>');
  }
  h+=`<div class="note">Descartados: `+Object.entries(desc).map(([k,v])=>`${esc(k)} ${fmtN(v)}`).join(' · ')+`</div>`;
  h+=`<div class="note">${esc(cob.nota||'')}</div>`;
  o.innerHTML=h;
}

export async function vincAgentePublico(filtro){
  // AGENTE PÚBLICO NO QUADRO SOCIETÁRIO. Não pede CNPJ: a pergunta é sobre a FILA inteira — 251 mil
  // nomes das folhas do Estado e da ALERJ cruzados com o QSA nacional (27,6 mi de linhas). O que
  // chega aqui já passou por três cortes: entidade que recebeu dinheiro público, nome com um único
  // CPF mascarado no índice, e explicação institucional DECLARADA (não escondida) ao lado do par.
  const o=$('vinc-out');
  o.innerHTML=card('<div class="dim">cruzando as folhas com o quadro societário do país…</div>');
  const d=await J('/api/osint/agente_publico?limite=250&filtro='+encodeURIComponent(filtro||'apTodos'));
  if(d.erro||d.ok===false){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  // CADA KPI TEM UM CAMINHO PARA O DADO. `filtro` é o nome da fatia que o número representa —
  // clicar em "68 comissionados" mostra os 68, não outra tela com outro número.
  const FILTROS={
    apTodos:'todos os pares', apComissionados:'agentes comissionados',
    apTerceiroSetor:'entidades de terceiro setor',
    apExplicados:'pares com explicação do programa',
    apNovos:'novos desde a última rodada', apConflito:'pagos pelo próprio órgão',
  };
  const sel={t:FILTROS[filtro]||FILTROS.apTodos};
  // A FATIA VEM DO SERVIDOR, já aplicada à fila inteira — filtrar aqui só a página carregada fazia
  // o clique contradizer o KPI (68 viravam 55, 201 viravam 22, 1 novo virava 0).
  const it=d.itens||[];
  let h=sec('Agente público no quadro societário'+(filtro&&filtro!=='apTodos'?' · '+sel.t:''));
  h+=`<div class="grid g2">${kpi(fmtN(d.total),'Pares agente × entidade','var(--amber)','🏛️',{drill:'apTodos'})}
      ${kpi(fmtN(d.comissionados),'Agentes COMISSIONADOS',d.comissionados?'var(--red)':null,'★',{drill:'apComissionados'})}
      ${kpi(fmtN(d.terceiro_setor),'Em ONG / associação / fundação',null,null,{drill:'apTerceiroSetor'})}
      ${kpi(fmtN(d.com_explicacao_institucional),'Com explicação do PROGRAMA','var(--dim)','📗',{drill:'apExplicados'})}
      ${kpi(fmtN(d.novos||0),'NOVOS desde a última rodada',(d.novos||0)?'var(--red)':null,'🆕',{drill:'apNovos'})}</div>`;
  h+=leitura(esc(d.ressalva||''));
  h+=`<div class="grid">`+it.map(x=>{
    const v=Object.entries(x.valor_por_fonte||{}).map(([k,n])=>`${esc(k)} ${fmtRc(n)}`).join(' · ');
    const ex=x.explicacao_institucional
      ? `<div class="dim" style="font-size:12px;margin-top:3px">desenho do programa: <b>${esc(x.explicacao_institucional)}</b></div>` : '';
    // CONFLITO DE ÓRGÃO: a unidade que pagou é a unidade onde o agente serve. É o único eixo
    // quase-objetivo da fila (art. 9º, III da Lei 8.429/1992) e por isso encabeça o cartão.
    const cf=x.orgao_pagador_e_o_proprio
      ? `<div style="margin-top:5px;font-size:12.5px;color:var(--red);font-weight:700">⚠ pago pelo PRÓPRIO ÓRGÃO do agente: ${esc(x.orgao_pagador_e_o_proprio)}</div>` : '';
    return card(
      `<div style="display:flex;justify-content:space-between;gap:10px">
         <div style="min-width:0">
           <div style="font-weight:700">${x.novo?'🆕 ':''}${x.comissionado?'★ ':''}${esc(x.agente)}</div>
           <div class="muted" style="font-size:12.5px">${esc(x.cargo||'')} · ${esc(x.orgao||'')}</div>
           <div style="font-size:13px;margin-top:4px">${esc(x.entidade)}${x.terceiro_setor?' <span class="dim">[3º setor]</span>':''}</div>
           <div class="dim" style="font-size:12px;margin-top:3px">${v||'sem desembolso — só contrato'}</div>
           ${cf}${ex}
         </div>
         <div class="right"><div class="dim" style="font-size:12px">${(x.fontes||[]).map(esc).join('<br>')}</div>
           <div class="dim" style="font-size:12px;margin-top:4px">${fmtN(x.servidores_no_qsa)} de ${fmtN(x.socios_no_qsa)} sócios</div></div>
       </div>`,
      (!x.explicacao_institucional && (x.orgao_pagador_e_o_proprio || x.comissionado)) ? 'hl' : '');
  }).join('')+`</div>`;
  if(!it.length) h+=card(`<div class="dim">Nenhum par nesta fatia.</div>`);
  h+=`<div class="note">${fmtN(it.length)} exibidos de ${fmtN(d.total_fatia)} nesta fatia`
     +`${filtro&&filtro!=='apTodos'?' ('+esc(sel.t)+')':''} · ${fmtN(d.total)} na fila inteira.`
     +` Clique em qualquer métrica acima para trocar a fatia.</div>`;
  h+=`<div class="note">Fontes: ${esc(d.fontes||'')}</div>`;
  o.innerHTML=h;
}

export async function vincParentesco(){
  const c=_vincCnpj(); const o=$('vinc-out'); if(!c){o.innerHTML=card('<div class="warn">Informe um CNPJ.</div>');return;}
  o.innerHTML=card('<div class="dim">medindo eixos…</div>');
  const d=await J('/api/osint/parentesco?cnpj='+encodeURIComponent(c));
  if(!d.ok){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const cor={indicio:'var(--rose)',hipotese:'var(--amber)',hipotese_fraca:null}[d.grau]||null;
  let h=sec('Parentesco inferido — CNPJ raiz '+esc(d.cnpj_basico));
  h+=`<div class="grid g2">${kpi(esc(d.grau||'nenhum eixo'),'Grau',cor,'👪')}
      ${kpi(fmtN(d.n_hipoteses),'Hipóteses')}
      ${kpi(d.falso_positivo_esperado_pct+'%','Falso positivo esperado',d.falso_positivo_esperado_pct>=10?'var(--amber)':null,'📉')}
      ${kpi(fmtN(d.n_socios_pf),'Sócios PF no QSA')}</div>`;
  h+=leitura(esc(d.leitura||''));
  if((d.eixos_acionados||[]).length){
    h+=`<div class="grid">`+(d.eixos_acionados||[]).map(e=>card(
      `<div style="font-weight:700">${esc(e.descricao)}
         ${e.pode_acender_sozinho?'<span class="tag">eixo forte</span>':'<span class="tag amber">não acende sozinho</span>'}</div>
       <div class="dim" style="margin-top:4px">Prevalência na base: <b>${e.prevalencia_na_base_pct}%</b></div>
       ${leitura('Explicação inocente: '+esc(e.explicacao_inocente))}`)).join('')+`</div>`;
  }
  if((d.hipoteses||[]).length){
    h+=sec('Pessoas',d.hipoteses.length);
    h+=`<div class="grid">`+d.hipoteses.map(x=>card(
      `<div style="font-weight:700">${esc((x.pessoas||[]).join('  ·  '))}</div>
       <div class="dim" style="margin-top:3px">${esc(x.onde||'')}${x.familia?' · família '+esc(x.familia):''}
         · hipótese: <b>${esc(x.tipo_provavel)}</b></div>
       <div class="dim">eixos: ${esc((x.eixos||[]).join(', '))}</div>`)).join('')+`</div>`;
  }
  if(d.diligencia){
    h+=card(`<div style="font-weight:700">Diligência que fecha a questão</div>
      <div class="dim" style="margin-top:4px">${esc(d.diligencia.por_que)}</div>
      <ul class="dim">`+(d.diligencia.fontes||[]).map(f=>`<li>${esc(f)}</li>`).join('')+`</ul>
      <div class="note">${esc(d.diligencia.metodologia_citavel)}</div>`);
  }
  o.innerHTML=h;
}

export async function vincNaData(){
  const c=_vincCnpj(), dt=($('vinc-data')?.value||''); const o=$('vinc-out');
  if(!c||!dt){o.innerHTML=card('<div class="warn">Informe CNPJ e data.</div>');return;}
  o.innerHTML=card('<div class="dim">consultando a série…</div>');
  const d=await J(`/api/osint/vinculo_na_data?cnpj=${encodeURIComponent(c)}&data=${encodeURIComponent(dt)}`);
  if(!d.ok){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const cor={SIM:'var(--rose)',NAO:null,INDISPONIVEL:'var(--amber)'}[d.resposta]||null;
  let h=sec('Havia vínculo societário em '+esc(dt)+'?');
  h+=`<div class="grid g2">${kpi(esc(d.resposta),'Resposta',cor,'⚖️')}
      ${kpi(esc(d.mes_observado||'—'),'Mês efetivamente observado')}
      ${kpi(d.defasagem_meses==null?'—':d.defasagem_meses,'Defasagem (meses)')}
      ${kpi(fmtN((d.serie||{}).n_meses),'Meses na série')}</div>`;
  if(d.resposta==='INDISPONIVEL') h+=leitura('<b>INDISPONÍVEL não é NÃO.</b> '+esc(d.motivo||''));
  else h+=leitura(esc(d.ressalva||''));
  if((d.socios||[]).length){
    h+=`<div class="grid">`+d.socios.map(s=>card(
      `<div style="font-weight:700">${esc(s.nome)}</div>
       <div class="dim">${esc(s.qualificacao||'—')} · entrada declarada ${esc(s.data_entrada||'—')}</div>`)).join('')+`</div>`;
  }
  if(d.diligencia){
    h+=card(`<div style="font-weight:700">${esc(d.diligencia.orgao)}</div>
      <div class="dim" style="margin-top:4px">${esc(d.diligencia.documento)}</div>
      <div class="note">${esc(d.diligencia.por_que)}</div>
      <div class="note">${esc(d.diligencia.como)}</div>`);
  }
  o.innerHTML=h;
}

export async function vincTrocas(){
  const c=_vincCnpj(), dt=($('vinc-data')?.value||''); const o=$('vinc-out');
  if(!c){o.innerHTML=card('<div class="warn">Informe um CNPJ.</div>');return;}
  if(!dt){o.innerHTML=card('<div class="warn">Informe a data de referência (homologação, assinatura ou pagamento).</div>');return;}
  o.innerHTML=card('<div class="dim">procurando trocas de quadro…</div>');
  const d=await J(`/api/osint/trocas_societarias?cnpj=${encodeURIComponent(c)}&data=${encodeURIComponent(dt)}`);
  if(!d.ok){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro||d.motivo)}</div>`);return;}
  let h=sec('Trocas de quadro societário perto de '+esc(dt));
  h+=`<div class="grid g2">${kpi(fmtN(d.n_entradas),'Entradas na janela',d.n_entradas?'var(--amber)':null,'➡️')}
      ${kpi(fmtN(d.n_saidas),'Saídas na janela',d.n_saidas?'var(--amber)':null,'🚪')}
      ${kpi(fmtN(d.janela_meses),'Janela (meses)')}</div>`;
  h+=leitura(esc(d.leitura||''));
  const linhas=[...(d.entradas||[]).map(x=>['entrada',x]),...(d.saidas||[]).map(x=>['saída',x])];
  if(linhas.length){
    h+=`<div class="grid">`+linhas.map(([tipo,x])=>card(
      `<div style="font-weight:700">${esc(x.nome_norm)} <span class="tag ${tipo==='saída'?'amber':''}">${tipo}</span></div>
       <div class="dim">${esc(x.qualificacao||'—')} · visto de ${esc(x.visto_de)} a ${esc(x.visto_ate)}
         ${x.saiu_entre?' · saiu entre '+esc(x.saiu_entre):''}
         ${x.janela_confiavel===0?' · <b>janela com mês não observado</b>':''}</div>`)).join('')+`</div>`;
  }
  o.innerHTML=h;
}

export async function vincPrevalencia(){
  const o=$('vinc-prev'); o.innerHTML='<div class="dim">medindo na base…</div>';
  const d=await J('/api/osint/parentesco/prevalencia');
  if(!d.ok){o.innerHTML=`<div class="warn">${erroHumano(d.erro)}</div>`;return;}
  const dec=d.declarado||{};
  let h=`<table class="tb" style="margin-top:10px"><thead><tr><th>Eixo</th><th class="r">Prevalência hoje</th><th class="r">Calibração declarada</th><th>Acende sozinho?</th></tr></thead><tbody>`;
  for(const [k,v] of Object.entries(d.eixos||{})){
    const dd=dec[k]||{}, alerta=v>(dd.prevalencia_medida||0)*1.5;
    h+=`<tr><td>${esc(dd.descricao||k)}</td><td class="r ${alerta?'bad':''}"><b>${v}%</b></td>
        <td class="r dim">${dd.prevalencia_medida==null?'—':dd.prevalencia_medida+'%'}</td>
        <td>${dd.pode_acender_sozinho?'sim':'<span class="dim">não — mede a base</span>'}</td></tr>`;
  }
  h+=`</tbody></table><div class="note">${esc(d.regra||'')}</div>`;
  o.innerHTML=h;
}



export async function vincGrafo(){
  const c=_vincCnpj(); const o=$('vinc-out'); if(!c){o.innerHTML=card('<div class="warn">Informe um CNPJ.</div>');return;}
  o.innerHTML=card('<div class="dim">montando a rede…</div>');
  const d=await J('/api/grafo?alvo='+encodeURIComponent(c)+'&saltos=2');
  if(d&&d.ok===false){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const nos=d.nos||[], ar=d.arestas||[];
  o.innerHTML=sec('Rede de poder — 2 saltos')+
    `<div class="grid g2">${kpi(fmtN(nos.length),'Nós')}${kpi(fmtN(ar.length),'Arestas')}
      ${kpi(fmtN((d.comunidades||[]).length),'Comunidades')}</div>`+
    card(`<div class="dim">A rede completa, navegável, abre em tela própria.</div>
      <div class="btns" style="margin-top:8px"><a class="btn ghost" target="_blank" href="/graph?alvo=${encodeURIComponent(c)}">Abrir grafo</a></div>`)+
    leitura('A aresta por <b>nome sem documento</b> vale pouco (homonímia). Para vínculo que pesa numa peça, use o beneficiário final — ele sobe a cadeia por documento.');
}
export async function vincFtm(){
  const c=_vincCnpj(); const o=$('vinc-out'); if(!c){o.innerHTML=card('<div class="warn">Informe um CNPJ.</div>');return;}
  o.innerHTML=card('<div class="dim">exportando…</div>');
  const d=await J('/api/grafo/ftm?alvo='+encodeURIComponent(c)+'&saltos=2');
  if(d&&d.ok===false){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const ents=d.entidades||d.entities||[];
  o.innerHTML=sec('FollowTheMoney')+card(
    `<div class="dim">${fmtN(ents.length)} entidade(s) no vocabulário FtM — interopera com Aleph e Gephi sem migrar nada.</div>
     <pre style="white-space:pre-wrap;font-size:11.5px;margin-top:8px;max-height:300px;overflow:auto">${esc(JSON.stringify(ents.slice(0,20),null,1))}</pre>`);
}
export async function vincHistoricoPessoa(){
  const n=($('vinc-pessoa')?.value||'').trim(); const o=$('vinc-out');
  if(!n){o.innerHTML=card('<div class="warn">Informe o nome do sócio.</div>');return;}
  o.innerHTML=card('<div class="dim">consultando a série…</div>');
  const d=await J('/api/osint/historico_socio?nome='+encodeURIComponent(n));
  if(!d.ok){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const vs=d.vinculos||[];
  if(!vs.length){o.innerHTML=card(`<div class="note">Nenhum vínculo desta pessoa na série. <b>INDISPONÍVEL não é ausência</b>: a série cobre só as raízes-alvo do acervo, não o Brasil inteiro.</div>`);return;}
  let h=sec('Sociedades de '+esc(n),vs.length)+`<table class="tb"><thead><tr><th>CNPJ raiz</th><th>Qualificação</th><th>Visto de</th><th>até</th><th>Situação</th></tr></thead><tbody>`;
  for(const v of vs)
    h+=`<tr><td>${esc(v.cnpj_basico)}</td><td class="dim">${esc(v.qualificacao||'—')}</td>
        <td>${esc(v.visto_de)}</td><td>${esc(v.visto_ate)}</td>
        <td class="${v.status==='saiu'?'bad':''}">${esc(v.status)}${v.saiu_entre?' ('+esc(v.saiu_entre)+')':''}${v.janela_confiavel===0?' ⚠ janela com mês não observado':''}</td></tr>`;
  h+=`</tbody></table>`;
  o.innerHTML=h;
}

export async function vincConluioMunicipal(){
  const o=$('vinc-out'); o.innerHTML=card('<div class="dim">cruzando QSA de vencedores e perdedoras…</div>');
  const d=await J('/api/osint/conluio_municipal?limite=400');
  if(!d.ok){o.innerHTML=card(`<div class="warn">${erroHumano(d.motivo||d.erro)}</div>`);return;}
  const c=d.cobertura||{};
  let h=sec('Conluio municipal — sócio em comum entre vencedor e perdedora');
  h+=`<div class="grid g2">${kpi(fmtN(d.n_certames_com_achado),'Certames com achado',d.n_certames_com_achado?'var(--rose)':null,'🤝')}
      ${kpi(fmtN(d.n_pares),'Pares vencedor × perdedora')}
      ${kpi(fmtN(c.cruzaveis_com_qsa_dos_dois_lados),'Certames efetivamente cruzados')}
      ${kpi((c.taxa_de_achado_pct==null?'—':c.taxa_de_achado_pct+'%'),'Taxa de achado')}</div>`;
  h+=leitura(`O eixo devolvia zero por falta de <b>dado</b>, não de motor: eram <b>114</b> certames com
     classificado além do 1º lugar em todo o acervo. Hoje são <b>${fmtN(c.com_vencedor_e_perdedora_resolvidos)}</b>
     com vencedor e perdedora resolvidos, e <b>${fmtN(c.cruzaveis_com_qsa_dos_dois_lados)}</b> com QSA dos dois lados.
     ${esc(c.nota||'')}`);
  if((d.achados||[]).length){
    h+=`<div class="search" style="margin-top:12px"><span class="mag"></span><input placeholder="filtrar por município, CNPJ ou sócio…" oninput="filtrar(this,'#cm-list .card')"></div>`;
    h+=`<div id="cm-list" class="grid">`+d.achados.map(a=>card(
      `<div style="font-weight:700">${esc(a.certame)}</div>
       <div class="dim" style="margin-top:3px">vencedor <b>${esc(a.vencedor_raiz)}</b> × perdedora <b>${esc(a.perdedora_raiz)}</b>
         · aresta ${esc(a.tipo_aresta)} (força ${a.forca_aresta})</div>
       <div style="margin-top:4px">Sócio(s) em comum: <b>${esc((a.socios_em_comum||[]).join(' · '))}</b></div>
       ${leitura('Veredito: <b>'+esc(a.veredito)+'</b>. '+esc(a.explicacao_inocente))}`,'hl')).join('')+`</div>`;
  }else{
    h+=card('<div class="note">Nenhum par com sócio em comum nos certames cruzados. Isso vale só para os cruzados — o resto é INDISPONÍVEL.</div>');
  }
  h+=(d.ressalvas||[]).map(r=>`<div class="note">${esc(r)}</div>`).join('');
  o.innerHTML=h;
}

export async function vincResolucao(){
  const o=$('vinc-out'); o.innerHTML=card('<div class="dim">consultando…</div>');
  const d=await J('/api/osint/resolucao_nome_cnpj');
  if(!d.ok){o.innerHTML=card(`<div class="warn">${erroHumano(d.motivo||d.erro)}</div>`);return;}
  o.innerHTML=sec('Resolução razão social → CNPJ (catálogo nacional da Receita)')+
    `<div class="grid g2">${kpi(fmtN(d.nomes),'Nomes no universo')}
      ${kpi(fmtN(d.resolvidos),'Resolvidos','var(--emerald)','✅')}
      ${kpi(fmtN(d.ambiguos),'Ambíguos (CNPJ nulo)','var(--amber)','⚖️')}
      ${kpi(d.pct_resolvido+'%','Taxa de resolução')}</div>`+
    leitura('Contra o catálogo LOCAL a taxa era de <b>13,9%</b>. O problema nunca foi a técnica de comparação — era o tamanho do catálogo: a maioria dos licitantes municipais nunca vendeu ao Estado e não estava nas nossas raízes.')+
    `<div class="note">${esc(d.nota||'')}</div>`;
}

export async function vincInterposicao(){
  const c=_vincCnpj(); const o=$('vinc-out'); if(!c){o.innerHTML=card('<div class="warn">Informe um CNPJ.</div>');return;}
  o.innerHTML=card('<div class="dim">medindo os eixos de interposição…</div>');
  const d=await J('/api/osint/interposicao?cnpj='+encodeURIComponent(c));
  if(!d.ok){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const socios=d.socios||d.perfis||[];
  let h=sec('Perfil de laranja (interposição) — CNPJ raiz '+esc(c.slice(0,8)));
  h+=leitura('Este módulo marcava <b>55%</b> da base até a prevalência de cada eixo ser medida: empresa com um só sócio é <b>54,9%</b> do normal, e sócio com mais de 80 anos é <b>1,87%</b>. Depois da calibragem, 1,4%. Eixo que acende na maioria mede a base, não o alvo.');
  h+=card(`<pre style="white-space:pre-wrap;font-size:12px;margin:0">${esc(JSON.stringify(d,null,1)).slice(0,4000)}</pre>`);
  o.innerHTML=h;
}
export async function vincPatrimonio(){
  const c=_vincCnpj(); const o=$('vinc-out'); if(!c){o.innerHTML=card('<div class="warn">Informe um CNPJ.</div>');return;}
  o.innerHTML=card('<div class="dim">comparando capacidade declarada e recebimento…</div>');
  const d=await J('/api/osint/patrimonio?cnpj='+encodeURIComponent(c));
  if(!d.ok){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  let h=sec('Capacidade declarada × recebimento público');
  h+=leitura('Sem renda conhecida o veredito é <b>não aferível</b>, nunca "renda incompatível" — a distinção entre fachada e enriquecimento depende de saber o que se declara, e quase sempre não se sabe.');
  h+=card(`<pre style="white-space:pre-wrap;font-size:12px;margin:0">${esc(JSON.stringify(d,null,1)).slice(0,3000)}</pre>`);
  o.innerHTML=h;
}

/* ═══ v59 · O PRIMEIRO DOMÍNIO SAI DA PONTE ═══════════════════════════════════════════════════
   A ponte (`Object.assign(window,{…})` no entrypoint) é um degrau, não o destino: ela existe
   porque os ~168 handlers `onclick=` do painel só resolvem nomes no escopo GLOBAL, e o destino
   declarado no §6.2-C é delegação por `data-*` no `#view`, feita POR DOMÍNIO.

   Vínculos é o domínio certo para começar, e por três razões que se pode conferir:
     · são 12 nomes — 17% do teto de 70, o maior bloco coeso da lista;
     · os 12 são handlers de ZERO argumento, então o `data-*` carrega tudo o que o `onclick`
       carregava, sem perder informação nenhuma na tradução (o que NÃO vale, por exemplo, para
       `ir('e_resp')` ou `abrirDossie(cnpj,nome)`, que levam argumento);
     · vivem todos numa aba só (`g_vinculos`), então o raio da mudança é uma tela.

   A migração GANHA acessibilidade em vez de custar: os doze já eram `<button type=button>`, e um
   botão de verdade é operável por teclado nativamente — deixa de depender do `a11yfy`, que existia
   justamente para consertar `[onclick]` em elemento não-focável.

   O mapa é a superfície: `data-vinc="grafo"` acha `grafo` aqui. Chave desconhecida não faz nada e
   não lança — botão morto é ruim, mas `TypeError` no console de um painel ao vivo é pior, e a
   completude de quem existe já é provada pelo `test_painel_ponte_completa`.  */
/* Uma ação por KPI: o nome no `data-drill` É o nome do filtro. Sem tabela paralela para
   dessincronizar — se o KPI cita uma fatia que não existe, o render cai no conjunto inteiro em vez
   de lançar, porque botão que não faz nada é ruim e `TypeError` em painel ao vivo é pior. */
export const DRILL_ACOES=Object.fromEntries(
  ['apTodos','apComissionados','apTerceiroSetor','apExplicados','apNovos']
    .map(k=>[k,()=>vincAgentePublico(k)]));

export const VINC_ACOES={
  consultar:vincConsultar, parentesco:vincParentesco, contato:vincContato,
  agentePublico:vincAgentePublico,
  trocas:vincTrocas, grafo:vincGrafo,
  ftm:vincFtm, conluioMunicipal:vincConluioMunicipal, resolucao:vincResolucao,
  interposicao:vincInterposicao, patrimonio:vincPatrimonio,
  historicoPessoa:vincHistoricoPessoa, naData:vincNaData, prevalencia:vincPrevalencia,
};

/** Liga a delegação de Vínculos. Chamada UMA vez, da sequência de boot.
 *
 *  Escuta no `document` e não no `#view` de propósito: `#view` tem o innerHTML trocado a cada
 *  navegação, e um ouvinte preso a ele morreria junto com o primeiro render — ou, pior, seria
 *  religado a cada troca de aba e acumularia um ouvinte por navegação. O documento é o único nó
 *  que sobrevive a tudo. Um ouvinte, para sempre.  */
export function ligarVinculos(){
  document.addEventListener('click',ev=>{
    const b=ev.target.closest&&ev.target.closest('[data-vinc]');
    const f=b&&VINC_ACOES[b.dataset.vinc];
    if(f){ev.preventDefault();f();return;}
    const k=ev.target.closest&&ev.target.closest('[data-drill]');
    const g=k&&DRILL_ACOES[k.dataset.drill];
    if(g){ev.preventDefault();g();}
  });
  /* O campo de CNPJ respondia ao Enter por `onkeydown` inline. Vira o mesmo mecanismo, com o
     nome da ação no atributo — um controle a menos citando função global. */
  document.addEventListener('keydown',ev=>{
    if(ev.key!=='Enter')return;
    const i=ev.target.closest&&ev.target.closest('[data-vinc-enter]');
    const f=i&&VINC_ACOES[i.dataset.vincEnter];
    if(f){ev.preventDefault();f();}
  });
}
