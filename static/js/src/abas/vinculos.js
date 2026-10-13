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
import {registrarDrill, drillSeCompleto} from '../nucleo/drill.js';
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
    h+=`<div class="grid g2">${kpi(fmtN(n),'Snapshots mensais na série',n>=2?'var(--emerald)':'var(--rose)','📅',
          {sobre:'Quantos meses da base de sócios da Receita foram efetivamente ingeridos. É o DENOMINADOR de tudo nesta aba: a Receita publica data de entrada e <b>nenhuma data de saída</b>, então saída de sócio só existe como diferença entre dois snapshots. Com menos de dois, ela é inobservável — e a resposta correta é INDISPONÍVEL, nunca NÃO.'})}
        ${kpi(esc(s.cobertura||'—'),'Janela observada',null,'🗓️',
          {sobre:'O primeiro e o último mês ingeridos. Fora desta janela nada foi observado: um sócio ausente num mês que não entrou na série <b>não saiu</b> — o mês é que não existe aqui.'})}
        ${kpi(fmtN(st.saiu||0),'Saídas de sócio detectadas','var(--amber)','🚪',
          {sobre:'Vínculos presentes num snapshot e ausentes no seguinte. A precisão máxima é de <b>um mês</b>, porque é esse o passo da série — a data exata da alteração contratual só a JUCERJA tem.'})}
        ${kpi(fmtN(st.ativo||0),'Vínculos vistos no último mês',null,'✅',
          {sobre:'Vínculos presentes no snapshot mais recente. "Ativo" aqui significa <b>visto por último</b>, não juridicamente vigente hoje: entre a extração da Receita e agora pode ter havido alteração não publicada.'})}</div>`;
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
      <button type="button" class="btn ghost" data-vinc="osintProcessos">OSINT × processos lidos</button>
      <button type="button" class="btn ghost" data-vinc="elosOcultos">Elos ocultos (contato × dinheiro)</button>
      <button type="button" class="btn ghost" data-vinc="cocontato">Mesmo certame, mesmo contato</button>
      <button type="button" class="btn ghost" data-vinc="assinaturasPcrj">Quem assinou (Prefeitura)</button>
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
  /* Participação cruzada circular é ACHADO — o módulo a trata como estrutura que dificulta
     identificar quem está por trás. Um número desses sem caminho para as cadeias é inútil. */
  registrarDrill('bfCiclos',{titulo:'Participações cruzadas circulares',itens:(d.ciclos||[]),
    render:ci=>card(`<div>${(Array.isArray(ci)?ci:[ci]).map(x=>esc(String(x))).join(' → ')}</div>`),
    nota:'Ciclo é indício de estrutura que dificulta identificar o beneficiário — não prova.'});
  let h=sec('Beneficiário final — '+esc(d.pj||c));
  registrarDrill('bfPessoas',{titulo:'Pessoas físicas ao fim da cadeia',itens:ps,
    render:x=>card(`<div style="font-weight:700">${esc(x.nome||x)}</div>
      <div class="dim">${esc(x.qualificacao||x.doc||'')}</div>`),
    nota:'CPF de sócio sai mascarado por dever legal (LGPD) — a identificação plena é do órgão de controle, não do painel.'});
  h+=`<div class="grid g2">${kpi(fmtN(d.n_pessoas),'Pessoas físicas na cadeia',ps.length?'var(--emerald)':'var(--amber)','👤',{drill:'bfPessoas'})}
      ${kpi((cob.pct==null?'—':cob.pct+'%'),'Cobertura de QSA da cadeia',cob.pct>=80?null:'var(--amber)','🔍',
        {sobre:'Que fração das PJ da cadeia teve o quadro societário efetivamente lido. Cobertura baixa <b>não</b> significa cadeia curta: significa que degraus ficaram por abrir, e o beneficiário final pode estar atrás de um deles. Por isso o número aparece ao lado da resposta, e não escondido.'})}
      ${kpi(fmtN(d.saltos_max),'Degraus até a pessoa física',null,null,
        {sobre:'Quantas PJ foram atravessadas até chegar a uma pessoa natural. Cadeia longa é <b>lícita</b> e comum em grupo econômico; ela só pesa combinada com outros sinais — sozinha, mede estrutura societária, não irregularidade.'})}
      ${kpi(fmtN((d.ciclos||[]).length),'Participações cruzadas circulares',(d.ciclos||[]).length?'var(--rose)':null,'🔄',{drill:'bfCiclos'})}</div>`;
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
  registrarDrill('contatoArestas',{titulo:'Empresas ligadas por telefone ou e-mail',itens:ar,
    render:x=>card(`<div style="display:flex;justify-content:space-between;gap:10px"><div style="min-width:0"><div style="font-weight:700">${esc(x.para)}</div><div class="dim">${esc(x.detalhe||'')} · ${esc(x.tipo)}</div><div class="dim">${esc(x.explicacao_inocente||'')}</div></div><div class="right"><div class="num" style="font-weight:800">${Math.round((x.forca||0)*100)}%</div></div></div>`),
    nota:'Contato dividido é indício de mesma administração, não prova.'});
  /* O QUE FICOU DE FORA É TÃO AUDITÁVEL QUANTO O QUE ENTROU. Cada guarda que descarta contato é
     uma decisão minha sobre o que não vira sinal — telefone-lixo, fan-out acima do teto, e-mail de
     contabilidade. Sem esta gaveta, o leitor teria de confiar que o corte foi honesto. */
  registrarDrill('contatoDesc',{titulo:'Contatos descartados, por guarda',
    itens:Object.entries(desc).map(([g,n])=>({guarda:g,n})),
    render:x=>card(`<div style="display:flex;justify-content:space-between;gap:10px">
      <div style="font-weight:700">${esc(x.guarda)}</div><div class="num">${fmtN(x.n)}</div></div>`),
    nota:'Guarda que descarta contato existe porque contato repetido nem sempre é mesma mão: central de atendimento, escritório contábil e provedor de e-mail produzem o mesmo padrão.'});
  h+=`<div class="grid g2">${kpi(fmtN(ar.length),'Empresas ligadas por contato',ar.length?'var(--amber)':null,'📞',{drill:'contatoArestas'})}
      ${kpi(fmtN(cob.com_telefone),'Alvos com telefone publicado',null,null,
        {sobre:'Dos estabelecimentos consultados, quantos publicam telefone na base da Receita — <b>83,9%</b> dos 6.171.766 no acervo. Quem não publica não pode ser ligado por este eixo: ausência de aresta aqui é lacuna de cadastro, não prova de independência.'})}
      ${kpi(fmtN(cob.com_email),'Alvos com e-mail publicado',null,null,
        {sobre:'Idem para e-mail — <b>69,0%</b> da base. O eixo de e-mail é o mais forte da régua depois de mesma sala (0,80), justamente porque endereço eletrônico é escolhido, não herdado do imóvel.'})}
      ${kpi(fmtN(Object.values(desc).reduce((s,x)=>s+x,0)),'Contatos DESCARTADOS por guarda','var(--dim)','🚫',{drill:'contatoDesc'})}</div>`;
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

export async function vincAssinaturasPcrj(){
  // QUEM DECIDIU, no município. O SEI da Prefeitura publica a MATRÍCULA de quem assina cada
  // despacho; a folha municipal tem matrícula e nome. Identificação por CADASTRO — mais forte que
  // casamento por nome, que carrega 4,7% de homônimo comprovado no índice do QSA.
  const o=$('vinc-out');
  o.innerHTML=card('<div class="dim">casando matrículas do SEI com a folha da Prefeitura…</div>');
  const d=await J('/api/pcrj/assinaturas?limite=150');
  if(d.erro||d.ok===false){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const it=d.itens||[];
  /* UNIDADE: o KPI conta MATRÍCULAS, a gaveta contava ASSINATURAS — 51 contra 110, e 18 contra 38.
     Nenhum dos dois números estava errado; eles medem coisas diferentes, e a mesma pessoa assina
     vários despachos. Um KPI que abre uma lista com o dobro de linhas faz o leitor desconfiar do
     número certo. A gaveta passa a agrupar por matrícula, que é o que o rótulo promete, e cada
     linha diz quantas assinaturas aquela matrícula responde. */
  const _porMatricula=lista=>{
    const m=new Map();
    for(const x of lista){
      const k=x.matricula_num||x.matricula||'—';
      if(!m.has(k)) m.set(k,{...x,n_assinaturas:0,processos:new Set()});
      const v=m.get(k); v.n_assinaturas++; if(x.numero) v.processos.add(x.numero);
    }
    return [...m.values()];
  };
  const _linMat=x=>card(`<div style="display:flex;justify-content:space-between;gap:10px">
      <div style="min-width:0">
        <div style="font-weight:700">${x.identificada?esc(x.nome):'matrícula '+esc(x.matricula_num||x.matricula)}</div>
        ${x.identificada?`<div class="dim">${esc(x.orgao||'')}${x.unidade_folha?' · '+esc(x.unidade_folha):''}</div>`:'<div class="dim">sem par na folha — requisitado de outro ente, empresa pública ou vínculo anterior a 12/2020</div>'}
        <div class="dim" style="font-size:12.5px;margin-top:4px">matrícula ${esc(x.matricula_num||x.matricula||'—')} · ${fmtN(x.processos.size)} processo(s)</div>
      </div>
      <div class="right"><div class="num" style="font-weight:800">${fmtN(x.n_assinaturas)}</div>
        <div class="dim">assinatura(s)</div></div></div>`);
  /* E MESMO AGRUPADO POR MATRÍCULA A CONTA NÃO FECHA SOZINHA: o KPI conta o ACERVO (51), a página
     servida tem 150 das 165 assinaturas e revela 46 matrículas. Nenhum dos dois mente — mas juntos
     mentiriam. `drillSeCompleto` só liga a gaveta quando o que está em mão É o universo; do
     contrário o KPI cai para a procedência, e ninguém precisa escolher entre mentir e não ter
     caminho. Quando o sweep completar a captura e a página couber, a gaveta liga sozinha. */
  const _mIdent=_porMatricula(it.filter(x=>x.identificada&&!x.ambigua));
  const _mSemPar=_porMatricula(it.filter(x=>!x.identificada));
  const _dIdent=drillSeCompleto('apIdent',d.identificadas,_mIdent,{
    titulo:'Matrículas identificadas na folha',render:_linMat,
    nota:'Uma linha por MATRÍCULA, não por assinatura — a mesma pessoa assina vários despachos, e é a matrícula que o KPI conta.'});
  const _dSemPar=drillSeCompleto('apSemPar',d.nao_identificadas,_mSemPar,{
    titulo:'Sem par na folha municipal',render:_linMat,
    nota:'NÃO significa inexistente: requisitado de outro ente, empresa pública com registro próprio, ou vínculo encerrado antes de 12/2020.'});
  let h=sec('Quem assinou — despachos da Prefeitura');
  const _lin=x=>card(`<div style="display:flex;justify-content:space-between;gap:10px">
      <div style="min-width:0">
        <div style="font-weight:700">${x.identificada?esc(x.nome):'matrícula '+esc(x.matricula_num||x.matricula)}</div>
        ${x.identificada?`<div class="dim">${esc(x.orgao||'')}${x.unidade_folha?' · '+esc(x.unidade_folha):''}</div>`:'<div class="dim">sem par na folha — requisitado de outro ente, empresa pública ou vínculo anterior a 12/2020</div>'}
        <div style="font-size:12.5px;margin-top:4px">${esc(x.tipo||'')} ${esc(x.documento||'')} · processo ${esc(x.numero||'')}</div>
        <div class="dim" style="font-size:12px">${esc(x.quando||'')} · ${esc(x.unidade||'')}</div>
        ${x.ambigua?'<div class="dim" style="font-size:12px;color:var(--amber)">matrícula com MAIS DE UM nome na folha — ambígua, não identificada</div>':''}
      </div></div>`, x.identificada&&!x.ambigua?'':'');
  /* MEDIDO EM 07/08/2026: KPI 165, gaveta 150 — a rota serve no máximo `limite` itens e o total
     conta o acervo inteiro. `drillSeCompleto` só liga a gaveta quando a lista É o universo; do
     contrário o KPI cai para a procedência, que diz o número e por que a lista não cabe. */
  h+=`<div class="grid g2">${kpi(fmtN(d.total),'Assinaturas capturadas','var(--amber)','✍️',
        drillSeCompleto('apAll',d.total,it,{titulo:'Assinaturas capturadas',render:_lin})
        ||{sobre:'Assinaturas de despacho capturadas na Lista de Andamentos do SEI da Prefeitura. A tela recebe uma PÁGINA da lista (parâmetro <b>limite</b>), não o acervo — por isso a gaveta fica desligada aqui: um número que abre uma lista menor é pior que um número sem caminho. Os recortes por identificação, ao lado, cabem inteiros e continuam clicáveis.'})}
      ${kpi(fmtN(d.identificadas),'Matrículas identificadas','var(--emerald)','🪪',
        _dIdent||{sobre:`Matrículas que casaram com nome na folha municipal, contadas sobre o ACERVO. A tela recebe uma página das assinaturas, e nela aparecem ${fmtN(_mIdent.length)} das ${fmtN(d.identificadas)} — por isso a gaveta fica desligada: abrir uma lista menor que o número faria desconfiar do número certo. <b>Formato não é identidade</b>: a folha guarda a matrícula com 7 dígitos e zero à esquerda, o SEI com 8; comparadas como texto davam 0 de 69, como número dão 51.`})}
      ${kpi(fmtN(d.nao_identificadas),'Sem par na folha','var(--dim)','❔',
        _dSemPar||{sobre:`Matrículas sem par na folha municipal — ${fmtN(_mSemPar.length)} visíveis na página servida, ${fmtN(d.nao_identificadas)} no acervo. <b>Não são erro nem ausência</b>: podem ser servidor requisitado de outro ente, empresa pública com registro próprio, ou vínculo encerrado antes de 12/2020, que é a primeira competência da folha.`})}
      ${kpi(fmtN(d.com_empresa_paga_pela_prefeitura??'—'),'Sócio de quem a Prefeitura paga',(d.com_empresa_paga_pela_prefeitura||0)?'var(--red)':null,'🚨',{drill:'apQsa'})}</div>`;
  h+=leitura(esc(d.ressalva||''));
  if(d.ressalva_qsa) h+=leitura(esc(d.ressalva_qsa));

  /* ZERO AQUI É "NÃO OBSERVADO NESTA AMOSTRA", nunca "não existe" — e a gaveta precisa dizer isso,
     porque um zero clicável que abre vazio é lido como afastamento da hipótese. */
  registrarDrill('apQsa',{titulo:'Signatário sócio de empresa paga pela Prefeitura',
    itens:(d.qsa_itens||[]),
    render:x=>card(`<div style="display:flex;justify-content:space-between;gap:10px">
      <div style="min-width:0"><div style="font-weight:700">${esc(x.signatario||'')}</div>
        <div class="dim">${esc(x.orgao||'')} · processo ${esc(x.processo||'—')}</div>
        <div style="margin-top:4px">${esc(x.empresa||'')} <span class="dim">(${esc(x.qualificacao||'')})</span></div>
      </div><div class="right"><div class="num" style="font-weight:800">${fmtRc(x.pago_pela_prefeitura)}</div>
        <div class="dim">pago pela Prefeitura</div></div></div>`,'hl'),
    nota:'Estar no QSA de alguma empresa NÃO é sinal: 33% dos signatários identificados aparecem no cadastro nacional. O sinal é a empresa receber do MESMO poder público cujo ato ele assina. Lista vazia = não observado nesta amostra.'});
  if((d.top_signatarios||[]).length){
    h+=sec('Quem mais assina')+`<div class="grid g2">`+(d.top_signatarios||[]).slice(0,8).map(
      ([nome,n])=>card(`<div style="display:flex;justify-content:space-between;gap:8px"><div style="min-width:0;font-weight:700">${esc(nome)}</div><div class="right"><b>${fmtN(n)}</b></div></div>`)).join('')+`</div>`;
  }
  h+=`<div class="grid" style="margin-top:12px">`+it.slice(0,60).map(_lin).join('')+`</div>`;
  h+=`<div class="note">${fmtN(Math.min(60,it.length))} de ${fmtN(d.total)} exibidas · gerado em ${esc(d.gerado_em||'—')}.</div>`;
  o.innerHTML=h;
}

export async function vincCocontato(){
  // O TESTE CLÁSSICO DE BID RIGGING, e aqui não há hipótese sobre "empresas ligadas": é o MESMO
  // certame, com os dois nomes na mesma ata. Quem disputa não deveria atender pelo mesmo contato.
  const o=$('vinc-out');
  o.innerHTML=card('<div class="dim">cruzando participantes de 4.517 certames com 6,17 milhões de estabelecimentos…</div>');
  const d=await J('/api/osint/cocontato_certame?limite=120');
  if(d.erro||d.ok===false){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const it=d.itens||[];
  let h=sec('Mesmo certame, mesmo contato');
  h+=`<div class="grid g2">${kpi(fmtN(d.total),'Pares no mesmo certame','var(--amber)','⚖️',{drill:'ccTodos'})}
      ${kpi(fmtN(d.sem_explicacao),'SEM explicação',(d.sem_explicacao||0)?'var(--red)':null,'🚨',{drill:'ccSemExpl'})}
      ${kpi(fmtN(d.contato_de_servico),'Contato de serviço','var(--dim)','📗',{drill:'ccServico'})}
      ${kpi(fmtN(d.certames_com_disputa),'Certames com 2+ fornecedores',null,null,
        {sobre:'O DENOMINADOR do teste. Certame com um único participante não pode ter disputa fingida — não há com quem fingir. Só estes entram na conta, e é contra este número que a taxa de achado deve ser lida.'})}</div>`;
  h+=leitura(esc(d.ressalva||''));
  const _lin=x=>card(`<div style="min-width:0">
      <div style="font-weight:700">${esc(x.nome_a)}</div>
      <div style="font-weight:700">${esc(x.nome_b)}</div>
      <div style="margin-top:5px;font-size:12.5px">${esc(x.via)} · <b>${esc(x.tipo)}</b></div>
      <div class="dim" style="font-size:12px;margin-top:3px">certame ${esc(x.certame)} · ${esc(x.orgao||'')}</div>
      <div class="dim" style="font-size:12px">foro: <b>${esc(x.corte||'—')}</b>${x.esfera?` (${esc(x.esfera)})`:''}</div>
      <div class="dim" style="font-size:12px">${esc((x.objeto||'').slice(0,140))}</div>
      ${x.contato_de_servico?'<div class="dim" style="font-size:12px;margin-top:3px">contato de serviço (contabilidade/central) — não liga as empresas entre si</div>':''}
      ${x.mesmo_grupo_aparente?`<div class="dim" style="font-size:12px;margin-top:3px">mesmo grupo aparente (<b>${esc(x.marca)}</b>) — grupo é lícito; disputar o mesmo certame fingindo concorrência não é</div>`:''}
    </div>`, (!x.contato_de_servico&&!x.mesmo_grupo_aparente)?'hl':'');
  registrarDrill('ccTodos',{titulo:'Pares do mesmo certame que dividem contato',itens:it,render:_lin});
  registrarDrill('ccSemExpl',{titulo:'Sem explicação — disputa com contato compartilhado',
    itens:it.filter(x=>!x.contato_de_servico&&!x.mesmo_grupo_aparente),render:_lin,
    nota:'Art. 337-F do Código Penal e Lei 12.529/2011 — cabe verificar as propostas e os sócios.'});
  registrarDrill('ccServico',{titulo:'Explicados por contato de serviço',
    itens:it.filter(x=>x.contato_de_servico),render:_lin,
    nota:'Escritório de contabilidade ou central de atendimento não liga as empresas entre si.'});
  h+=`<div class="grid">`+it.map(_lin).join('')+`</div>`;
  h+=`<div class="note">${fmtN(it.length)} de ${fmtN(d.total)} exibidos · ${fmtN(d.cnpjs_participantes)} CNPJs cruzados · gerado em ${esc(d.gerado_em||'—')}.</div>`;
  o.innerHTML=h;
}

export async function vincElosOcultos(soSemExplicacao){
  // A PERGUNTA QUE O GRAFO EXISTE PARA RESPONDER: duas empresas que disputam o mesmo dinheiro
  // público atendem pelo mesmo telefone ou e-mail? Ou são o mesmo grupo — e a disputa entre elas é
  // aparente — ou há uma mão comum que ninguém declarou.
  const o=$('vinc-out');
  o.innerHTML=card('<div class="dim">cruzando contato compartilhado com quem recebeu do Estado…</div>');
  const d=await J('/api/osint/elos_ocultos?limite=120'+(soSemExplicacao?'&so_sem_explicacao=1':''));
  if(d.erro||d.ok===false){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const it=d.itens||[];
  let h=sec('Elos ocultos — contato compartilhado × dinheiro público');
  h+=`<div class="grid g2">${kpi(fmtN(d.total),'Pares com os DOIS lados pagos','var(--amber)','🔗',{drill:'eoTodos'})}
      ${kpi(fmtN(d.sem_explicacao),'SEM explicação aparente',(d.sem_explicacao||0)?'var(--red)':null,'🚨',{drill:'eoSemExpl'})}
      ${kpi(fmtN(d.mesmo_grupo_aparente),'Mesmo grupo aparente','var(--dim)','🏢',{drill:'eoGrupo'})}
      ${kpi(fmtN(d.estruturais),'Estruturais (fora da fila)','var(--dim)','📗',
        {sobre:'Pares cujo contato compartilhado é explicado pela própria forma jurídica — filial e matriz, empresa e seu sindicato patronal, entidades do mesmo grupo declarado. Saem da fila do fiscal de propósito: acusar o que a lei organiza assim é ruído que faz o leitor desconfiar do resto.'})}</div>`;
  /* O DENOMINADOR DO GRAFO É PARTE DO ACHADO. Sem ele, "39 elos" lê-se como o resultado de varrer
     o universo — e o grafo percorreu 9,4% dos credores quando esta linha nasceu. O que está fora
     não foi afastado: não foi visto, e a diferença é a mesma que separa lacuna de achado. */
  /* O PESO É PISO — e o leitor precisa saber ANTES de julgar o número. Medido em 2026-08-09: a
     coleta do SIAFE tinha 22 pares (UG, ano) parados em contagem redonda, e o par que encabeçava
     a fila com R$ 423,2 mi aparecia com R$ 40,7 mi enquanto a fonte canônica só tinha 1 das 13
     OBs de um dos lados. */
  if(d.peso_e_piso&&d.peso_e_piso.ug_ano_no_teto_de_coleta){
    h+=leitura(`<b>Os valores abaixo são PISO.</b> A coleta do SIAFE tem teto por unidade e ano, e <b>${fmtN(d.peso_e_piso.ug_ano_no_teto_de_coleta)}</b> pares (UG, ano) ainda estão parados em contagem redonda — sintoma de coleta interrompida, não de órgão sem despesa. Onde o espelho conhece 50× mais que a fonte canônica, o valor dele vem declarado no item.`);
  }
  if(d.cobertura_grafo&&d.cobertura_grafo.universo){
    const cg=d.cobertura_grafo;
    h+=leitura(`O grafo societário percorreu <b>${fmtN(cg.percorridos)}</b> de <b>${fmtN(cg.universo)}</b> credores com Ordem Bancária (<b>${cg.pct}%</b>). Os elos abaixo existem SÓ dentro desse recorte — credor ainda não percorrido não foi afastado, não foi visto. A cobertura cresce a cada varredura, nas duas máquinas.`);
  }
  h+=leitura(esc(d.ressalva||''));
  const _lin=x=>card(`<div style="display:flex;justify-content:space-between;gap:10px">
      <div style="min-width:0">
        <div style="font-weight:700">${esc(x.a)}</div>
        <div class="dim">${esc(x.cnpj_a)} · ${fmtRc(x.pago_a)}</div>
        <div style="font-weight:700;margin-top:5px">${esc(x.b)}</div>
        <div class="dim">${esc(x.cnpj_b)} · ${fmtRc(x.pago_b)}</div>
        <div style="margin-top:5px;font-size:12.5px">${esc(x.detalhe||x.tipo)}</div>
        ${x.mesmo_grupo_aparente?`<div class="dim" style="font-size:12px;margin-top:3px">mesmo grupo aparente (<b>${esc(x.marca)}</b>) — grupo econômico é lícito; disputar o mesmo certame fingindo concorrência não é</div>`:''}
      </div>
      <div class="right"><div class="num" style="font-weight:800">${fmtRc(x.peso)}</div><div class="dim">somados</div></div></div>`,
    x.mesmo_grupo_aparente?'':'hl');
  registrarDrill('eoTodos',{titulo:'Pares com os dois lados pagos pelo Estado',itens:it,render:_lin});
  registrarDrill('eoSemExpl',{titulo:'Sem explicação aparente',itens:it.filter(x=>!x.mesmo_grupo_aparente),render:_lin,
    nota:'Nomes distintos, sem forma jurídica que os una, mesmo contato, ambos pagos pelo poder público.'});
  registrarDrill('eoGrupo',{titulo:'Mesmo grupo aparente',itens:it.filter(x=>x.mesmo_grupo_aparente),render:_lin,
    nota:'Grupo econômico é LÍCITO — art. 337-F do CP alcança a disputa fingida, não a existência do grupo.'});
  h+=`<div class="grid">`+it.map(_lin).join('')+`</div>`;
  h+=`<div class="note">${fmtN(it.length)} de ${fmtN(d.total)} exibidos · ${fmtN(d.arestas_de_contato)} arestas de contato no grafo, ${fmtN(d.estruturais)} explicadas pela forma jurídica · gerado em ${esc(d.gerado_em||'—')}.</div>`;
  o.innerHTML=h;
}

export async function vincOsintProcessos(soConflito){
  // A CORRELAÇÃO QUE FALTAVA. Inteligência sobre empresa não fiscaliza nada sozinha: quem fiscaliza
  // abre AUTOS. Aqui a fila de agente público encontra as fichas de processo que citam o CNPJ —
  // e o conflito PELO PROCESSO é mais forte que o conflito pelo pagamento, porque o caminho do
  // dinheiro passa pelo fundo e o caminho da DECISÃO passa pelo órgão.
  const o=$('vinc-out');
  o.innerHTML=card('<div class="dim">cruzando a fila de agente público com as fichas de processo…</div>');
  const d=await J('/api/osint/processos?limite=120'+(soConflito?'&so_conflito=1':''));
  if(d.erro||d.ok===false){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  const it=d.itens||[];
  const nConf=(d.itens||[]).filter(x=>(x.agentes||[]).some(a=>a.conflito_pelo_processo||a.conflito_de_orgao)).length;
  let h=sec('OSINT × processos lidos');
  const _lin=x=>{
    const g=(x.agentes||[])[0]||{};
    const conf=g.conflito_pelo_processo||g.conflito_de_orgao;
    return card(`<div style="display:flex;justify-content:space-between;gap:10px">
       <div style="min-width:0"><div style="font-weight:700">${esc(x.processo)}</div>
         <div class="dim">${esc(x.orgao_do_processo||'órgão não resolvido')}</div>
         <div style="font-size:13px;margin-top:4px">${esc(g.nome||'—')} · ${esc(g.cargo||'')} <span class="dim">(${esc(g.orgao||'')})</span></div>
         <div class="dim" style="font-size:12.5px">${esc(g.entidade||'')}</div>
         ${conf?`<div style="margin-top:5px;font-size:12.5px;color:var(--red);font-weight:700">⚠ os AUTOS correm no próprio órgão do agente: ${esc(conf)}</div>`:''}
         ${(x.sem_qsa_capturado||[]).length?`<div class="dim" style="font-size:12px;margin-top:3px">${fmtN(x.sem_qsa_capturado.length)} CNPJ(s) sem QSA capturado — LACUNA, não limpeza</div>`:''}
       </div><div class="right"><div class="num" style="font-weight:800">${fmtN(x.peso)}</div><div class="dim">peso</div></div></div>`,
      conf?'hl':'');
  };
  h+=`<div class="grid g2">${kpi(fmtN(d.total),'Processos com sinal','var(--amber)','⚖️',
        drillSeCompleto('opTodos',d.total,it,{titulo:'Processos com sinal OSINT',render:_lin})
        ||{sobre:'Processos cuja ficha cita CNPJ que aparece na fila de agente público. Medido em 07/08/2026: <b>294</b> no acervo, e a tela recebe os primeiros <b>120</b> — por isso a gaveta fica desligada neste KPI. O recorte grave ao lado (autos no próprio órgão do agente) cabe inteiro e abre.'})}
      ${kpi(fmtN(d.processos_com_cnpj),'Fichas com CNPJ',null,null,
        {sobre:'Quantas fichas de processo têm ao menos um CNPJ extraído — é o universo que pode ser cruzado com a fila de agente público. Processo sem CNPJ na ficha não foi afastado: ele simplesmente <b>não pôde ser testado</b>, e essa diferença é o que separa lacuna de achado.'})}
      ${kpi(fmtN(nConf),'Autos no PRÓPRIO órgão do agente',nConf?'var(--red)':null,'⚠️',{drill:'opConflito'})}</div>`;
  h+=leitura(esc(d.ressalva||''));

  registrarDrill('opConflito',{titulo:'Autos que correm no próprio órgão do agente',
    itens:it.filter(x=>(x.agentes||[]).some(a=>a.conflito_pelo_processo||a.conflito_de_orgao)),render:_lin,
    nota:'Art. 9º, III da Lei 8.429/1992 e dever de impedimento do art. 20 da Lei 9.784/1999.'});
  h+=`<div class="grid">`+it.map(_lin).join('')+`</div>`;
  h+=`<div class="note">${fmtN(it.length)} de ${fmtN(d.total)} exibidos · gerado em ${esc(d.gerado_em||'—')}.</div>`;
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
    // O NOME DA FONTE DIZ DE QUEM É O DINHEIRO. Os rótulos crus ("pcrj_despesa") escondem que
    // R$ 2,6 bi de um item podem ser MUNICIPAIS enquanto o agente serve a um órgão ESTADUAL — e o
    // leitor apressado soma tudo como se fosse do Estado (medido 2026-08-09, caso VIVA RIO:
    // R$ 8,2 mi no SIAFE estadual contra R$ 2,60 bi pagos pela Prefeitura).
    const _FONTE={siafe_ob:'OB do Estado (SIAFE)', pcrj_despesa:'pago pela Prefeitura do Rio',
      pcrj_contratos:'contratos da Prefeitura (valor global, não pagamento)',
      emenda_favorecidos:'emendas parlamentares'};
    const v=Object.entries(x.valor_por_fonte||{})
      .map(([k,n])=>`${esc(_FONTE[k]||k)} ${fmtRc(n)}`).join(' · ');
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
  h+=`<div class="grid g2">${kpi(esc(d.grau||'nenhum eixo'),'Grau',cor,'👪',
        {sobre:'A força do que os eixos sustentam: <b>hipótese fraca</b>, <b>hipótese</b> ou <b>indício</b>. Nenhum grau aqui é prova — no Brasil não há base aberta de filiação, e parentesco só se prova por certidão de registro civil. O que existe é inferência calibrada.'})}
      ${kpi(fmtN(d.n_hipoteses),'Hipóteses',null,null,
        {sobre:'Quantos pares de sócios acionaram ao menos um eixo. Número alto em empresa grande é esperado: quanto mais sócios, mais pares — por isso o grau depende do eixo acionado, não da quantidade.'})}
      ${kpi(d.falso_positivo_esperado_pct+'%','Falso positivo esperado',d.falso_positivo_esperado_pct>=10?'var(--amber)':null,'📉',
        {sobre:'Medido na PRÓPRIA BASE antes de deixar o eixo pesar: um eixo que acende na maioria das empresas mede a base, não o alvo. Foi assim que sobrenome compartilhado deixou de acender sozinho — no Brasil ele casa com meio país.'})}
      ${kpi(fmtN(d.n_socios_pf),'Sócios PF no QSA',null,null,
        {sobre:'Pessoas naturais no quadro societário declarado. É o universo dos pares testados: com um sócio só, nenhum eixo de parentesco pode acionar, e a resposta correta é ausência de teste, não ausência de parentesco.'})}</div>`;
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
  h+=`<div class="grid g2">${kpi(esc(d.resposta),'Resposta',cor,'⚖️',
        {sobre:'SIM, NÃO ou INDISPONÍVEL. <b>INDISPONÍVEL não é NÃO</b>: significa que o mês da data pedida não foi observado na série, e responder NÃO ali seria afirmar uma ausência que o dado não sustenta.'})}
      ${kpi(esc(d.mes_observado||'—'),'Mês efetivamente observado',null,null,
        {sobre:'O snapshot realmente usado para responder — quase nunca é o mês exato da pergunta, porque a série tem passo mensal. É este mês, não a data pedida, que a resposta descreve.'})}
      ${kpi(d.defasagem_meses==null?'—':d.defasagem_meses,'Defasagem (meses)',null,null,
        {sobre:'Distância entre a data perguntada e o snapshot usado. Defasagem grande enfraquece a resposta: quanto mais longe, mais espaço houve para alteração contratual não observada entre os dois pontos.'})}
      ${kpi(fmtN((d.serie||{}).n_meses),'Meses na série',null,null,
        {sobre:'Tamanho da série disponível para esta consulta. Com um único mês, toda pergunta sobre data anterior sai INDISPONÍVEL por construção.'})}</div>`;
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
  const _troca=x=>card(`<div style="display:flex;justify-content:space-between;gap:10px">
      <div style="min-width:0"><div style="font-weight:700">${esc(x.nome||'')}</div>
      <div class="dim">${esc(x.qualificacao||'')}</div></div>
      <div class="right"><div class="dim">${esc(x.mes||x.data||'')}</div></div></div>`);
  registrarDrill('trEntradas',{titulo:'Entradas de sócio na janela',itens:(d.entradas||[]),render:_troca,
    nota:'A data é do SNAPSHOT em que o sócio apareceu, com precisão de um mês — não da alteração contratual.'});
  registrarDrill('trSaidas',{titulo:'Saídas de sócio na janela',itens:(d.saidas||[]),render:_troca,
    nota:'Saída é inferida por AUSÊNCIA entre dois snapshots. Mês não ingerido não produz saída — produz lacuna.'});
  h+=`<div class="grid g2">${kpi(fmtN(d.n_entradas),'Entradas na janela',d.n_entradas?'var(--amber)':null,'➡️',{drill:'trEntradas'})}
      ${kpi(fmtN(d.n_saidas),'Saídas na janela',d.n_saidas?'var(--amber)':null,'🚪',{drill:'trSaidas'})}
      ${kpi(fmtN(d.janela_meses),'Janela (meses)',null,null,
        {sobre:'Quantos meses ao redor da data de referência foram varridos. Janela larga acha mais trocas e diz menos sobre proximidade com o ato; janela estreita diz mais e acha menos. O número está aqui para o leitor calibrar a leitura.'})}</div>`;
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
  /* Os três números SÃO os três arrays desta resposta — mesmo universo, sem página no meio. */
  registrarDrill('grafoNos',{titulo:'Nós da rede (2 saltos)',itens:nos,
    render:n=>card(`<div style="display:flex;justify-content:space-between;gap:10px"><div style="min-width:0"><div style="font-weight:700">${esc(n.rotulo||n.id||'—')}</div><div class="dim">${esc(n.tipo||'')}</div></div></div>`)});
  registrarDrill('grafoArestas',{titulo:'Arestas da rede',itens:ar,
    render:x=>card(`<div><b>${esc(x.de||x.origem||'—')}</b> → <b>${esc(x.para||x.destino||'—')}</b><div class="dim">${esc(x.tipo||'')}${x.fonte?' · '+esc(x.fonte):''}</div></div>`),
    nota:'Aresta por NOME sem documento vale pouco (homonímia).'});
  registrarDrill('grafoComunidades',{titulo:'Comunidades detectadas',itens:(d.comunidades||[]),
    render:cm=>card(`<div><b>${esc(cm.rotulo||cm.id||'comunidade')}</b><div class="dim">${fmtN((cm.membros||[]).length||cm.n||0)} membro(s)</div></div>`)});
  o.innerHTML=sec('Rede de poder — 2 saltos')+
    `<div class="grid g2">${kpi(fmtN(nos.length),'Nós',null,null,{drill:'grafoNos'})}${kpi(fmtN(ar.length),'Arestas',null,null,{drill:'grafoArestas'})}
      ${kpi(fmtN((d.comunidades||[]).length),'Comunidades',null,null,{drill:'grafoComunidades'})}</div>`+
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
  /* CADA LINHA DE `achados` É UM PAR, NÃO UM CERTAME — 42 pares para 31 certames na medição de
     07/08/2026, porque um certame com dois classificados problemáticos gera dois pares. A gaveta
     estava pendurada no KPI de CERTAMES: 31 no número, 42 na lista. Defeito meu, da mesma família
     que a casa já corrigiu três vezes (68→55, 201→22, 647→0). Vai para o KPI que ela conta. */
  const _cmLin=a=>card(`<div style="font-weight:700">${esc(a.certame)}</div>
      <div class="dim" style="margin-top:3px">vencedor <b>${esc(a.vencedor_raiz)}</b> × perdedora <b>${esc(a.perdedora_raiz)}</b></div>
      <div style="margin-top:4px">Sócio(s) em comum: <b>${esc((a.socios_em_comum||[]).join(' · '))}</b></div>
      <div class="dim" style="margin-top:3px">${esc(a.veredito||'')}</div>`,'hl');
  h+=`<div class="grid g2">${kpi(fmtN(d.n_certames_com_achado),'Certames com achado',d.n_certames_com_achado?'var(--rose)':null,'🤝',
        {sobre:'Certames DISTINTOS em que ao menos um par vencedor × perdedora divide sócio — 31 certames para 42 pares em 07/08/2026. Não é o mesmo número que o de pares: um certame com dois classificados problemáticos conta UMA vez aqui e DUAS ali. As linhas estão na gaveta do KPI ao lado, que é o que elas contam.'})}
      ${kpi(fmtN(d.n_pares),'Pares vencedor × perdedora',null,null,
        drillSeCompleto('cmAchados',d.n_pares,(d.achados||[]),{
          titulo:'Pares vencedor × perdedora com sócio em comum', render:_cmLin,
          nota:'Sócio em comum entre quem venceu e quem perdeu o MESMO certame é o teste clássico de concorrência fingida (art. 337-F do CP). Grupo econômico declarado é lícito; disputar contra si mesmo não é.'})
        ||{sobre:'Quantos pares foram efetivamente testados. Um certame com quatro classificados gera três pares contra o vencedor — por isso este número é maior que o de certames, e não deve ser lido como quantidade de irregularidades. A gaveta só liga quando a lista em mão é o universo inteiro; cortada, o KPI prefere não ter caminho a ter um caminho que mente.'})}
      ${kpi(fmtN(c.cruzaveis_com_qsa_dos_dois_lados),'Certames efetivamente cruzados',null,null,
        {sobre:'O DENOMINADOR honesto: só entram os certames em que o QSA dos DOIS lados foi resolvido. O eixo devolvia zero por falta de dado, não de motor — havia 114 certames com classificado além do 1º lugar em todo o acervo. O que está fora daqui é INDISPONÍVEL, não afastado.'})}
      ${kpi((c.taxa_de_achado_pct==null?'—':c.taxa_de_achado_pct+'%'),'Taxa de achado',null,null,
        {sobre:'Achados sobre certames efetivamente cruzados — nunca sobre o acervo inteiro, que daria um percentual falsamente tranquilizador. Taxa alta neste eixo pede desconfiança do próprio motor antes de acusar: 7 famílias de detector já caíram por leitura defeituosa, nenhuma por limiar.'})}</div>`;
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
    `<div class="grid g2">${kpi(fmtN(d.nomes),'Nomes no universo',null,null,
        {sobre:'Razões sociais que aparecem em atas e editais sem CNPJ ao lado — o problema que esta rotina existe para resolver. Nome sem documento não cruza com nada: não vira QSA, não vira sanção, não vira pagamento.'})}
      ${kpi(fmtN(d.resolvidos),'Resolvidos','var(--emerald)','✅',
        {sobre:'Nomes que casaram com um ÚNICO CNPJ no catálogo nacional da Receita. Casamento múltiplo não conta como resolvido — eleger um entre vários seria inventar identidade.'})}
      ${kpi(fmtN(d.ambiguos),'Ambíguos (CNPJ nulo)','var(--amber)','⚖️',
        {sobre:'Nomes que casaram com mais de um CNPJ, ou com nenhum. Ficam declarados em vez de sumir: são exatamente os alvos que uma diligência humana (JUCERJA, ata original) ainda pode fechar.'})}
      ${kpi(d.pct_resolvido+'%','Taxa de resolução',null,null,
        {sobre:'Contra o catálogo LOCAL a taxa era de <b>13,9%</b>. A técnica de comparação nunca foi o problema — era o tamanho do catálogo: a maioria dos licitantes municipais nunca vendeu ao Estado e não estava nas nossas raízes.'})}</div>`+
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
  agentePublico:vincAgentePublico, osintProcessos:vincOsintProcessos,
  elosOcultos:vincElosOcultos, cocontato:vincCocontato,
  assinaturasPcrj:vincAssinaturasPcrj,
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
