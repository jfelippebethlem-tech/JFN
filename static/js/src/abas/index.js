/* AS TELAS — as 59 abas do painel, cada uma uma funcao que recebe dado e devolve HTML.
 *
 * Saem em UM modulo, e nao nos sete dominios que o plano previa, pelo mesmo motivo da cena: aqui
 * elas estao em DUAS faixas separadas pelo catalogo `TABS`, e o proprio arquivo explica por que —
 * `TABS` e `const` e referencia o render na AVALIACAO, entao um `const renderX` declarado depois
 * daria TDZ e mataria o boot em silencio, coisa que ja aconteceu. Separar por dominio exige
 * classificar 59 funcoes e resolver as que sao compartilhadas entre esferas (`renderSobrepreco`,
 * `renderConluio` e `renderPoder` aparecem em duas ou tres, com argumento diferente) — isso e
 * trabalho de classificacao, nao de mudanca de arquivo, e fica para um corte proprio.
 *
 * O que se ganha ja: o entrypoint deixa de ser onde as telas moram. Ele passa a ser o catalogo,
 * a sequencia de boot e a ponte.
 */
import {$, esc, svgIco, card, kpi, sec, cover, spin, leitura, semMedicao, btnPdf, acoesAba,
        toggle, corta, clk} from '../nucleo/dom.js';
import {drillSeCompleto, limparDrill, registrarDrill} from '../nucleo/drill.js';
import {fmtN, fmtD, fmtPct, fmtR, fmtRc, ROTULOS, rot} from '../nucleo/formato.js';
import {J, _jCache, erroHumano} from '../nucleo/http.js';
import {filtrar, filtrarPag, _pagMais, _acPagPick, buscaPag, listaPaginada, ordenar,
        _pagState} from '../nucleo/lista.js';
import {_redMotion, _sobrio} from '../capacidade/estado.js';
import {esfera, aba} from '../app/estado.js';
import {nuSet, nuSweepPoll, NU_NODES, nucleoStart} from '../cena/index.js';
import {energiaLigar} from '../cena/energia.js';
import {abrirDossie, abrirCertame, verCruzamento, jsq, seiArvore, seiBaixarZip,
        a11yfy, holografar, jfnToast, jfnConfirm} from '../ui/index.js';

// ═══ RESPONSÁVEIS pelo processo (ordenador · gestor · fiscal) ═══
// Declarado ANTES de TABS de propósito: TABS é `const` e referencia o render na avaliação —
// um `const renderX` declarado depois daria TDZ e mataria o boot em silêncio (já aconteceu).
// `async function` é hoisted, mas a ordem aqui é explícita para quem vier depois.
export let _respProc='';
// O payload traz `cargo`, e o extrator às vezes deposita ali o e-mail da assinatura do
// documento. E-mail pessoal de servidor não vai para a tela: mostra-se o cargo só quando é
// cargo. O dado continua no banco; o que não se faz é publicá-lo.
export const _ehEmail=s=>/@/.test(String(s||''));
export async function renderResponsaveis(){
  let h=cover('estado','Responsáveis pelo processo','Quem responde por um processo SEI: ordenador de despesa, gestor e fiscal do contrato, com ID funcional quando o documento o traz.','🧑‍⚖️');
  h+=`<div class="search"><span class="mag"></span><input id="resp-proc" placeholder="número SEI (ex.: SEI-070002/006145/2024)…" value="${esc(_respProc)}" onchange="_respProc=this.value;ir('e_resp')" onkeydown="if(event.key==='Enter'){_respProc=this.value;ir('e_resp')}"></div>`;
  if(!_respProc.trim())return h+card('<div class="muted">Informe o número do processo. A busca lê o que já foi capturado — ela responde uma pergunta, não varre o acervo.</div>');
  let d;
  try{ d=await J('/api/responsaveis?processo='+encodeURIComponent(_respProc.trim())); }
  catch(e){ return h+card(`<div class="muted">Não foi possível consultar: ${esc(String(e&&e.message||e))}</div>`); }
  if(!d||d.ok===false)return h+card(`<div class="muted">${esc((d&&d.erro)||'consulta sem resposta')}</div>`);
  const ag=d.agentes||[];
  h+=card(`<div style="font-weight:700">${esc(d.processo||_respProc)}</div><div class="dim">${ag.length} responsável(is) identificado(s) nos documentos capturados</div>`);
  if(!ag.length){
    // LACUNA declarada, nunca "não há responsável": em 97% dos processos o ato de designação
    // vive no processo de contratação, não no de pagamento. Confundir os dois produziria
    // acusação falsa de execução sem fiscal.
    return h+card('<div class="muted">Nenhum responsável identificado <b>nos documentos capturados</b>. Isso é lacuna de captura ou de instrução — <b>não</b> afirmação de que o processo corra sem responsável designado: o ato de designação costuma viver no processo de contratação, não no de pagamento.</div>');
  }
  h+=`<div class="grid">`+ag.map(a=>card(
    `<div><div style="font-weight:700">${esc(a.nome||'—')}</div>
     <div class="dim">${esc(String(a.papel||'').replace(/_/g,' '))}${a.id_funcional?` · ID ${esc(a.id_funcional)}`:''}${a.cargo&&!_ehEmail(a.cargo)?` — ${esc(a.cargo)}`:''}</div>
     <div class="dim" style="font-size:12px">origem: ${esc(a.origem||'—')}${a.documento?` · ${esc(a.documento)}`:''}</div></div>`)).join('')+`</div>`;
  const lac=d.lacunas||[];
  if(lac.length)h+=card(`<div style="font-weight:700">Lacunas apontadas</div><ul style="margin:6px 0 0 18px">${lac.slice(0,5).map(l=>`<li>${esc(l.descricao||l.tipo||'—')}</li>`).join('')}</ul>`);
  return h;
}

// ═══════════════════════════════════════════════════════════════════════════════════════════════
// ABAS NOVAS (2026-07-29) — o que estava implementado no backend e invisível para quem decide.
//
// A auditoria mediu: 57 de 158 rotas não tinham NENHUM ponto de entrada no painel, incluindo o
// dossiê completo, o dossiê mestre, a minuta .docx pronta para o gabinete assinar, e todo o eixo
// de vínculos. Rota órfã não é detalhe de UI: é trabalho feito que não vira decisão de fiscalização.
// A catraca que impede isso de voltar a crescer é tests/test_rotas_sem_orfa.py.
//
// ⚠️ Estes renders ficam ANTES de `const TABS` de propósito: TABS é const e referencia o render na
// avaliação — declarar depois daria TDZ e mataria o boot em silêncio (já custou 13 versões).
// ═══════════════════════════════════════════════════════════════════════════════════════════════

// ═══ PEÇAS — os produtos entregáveis que não tinham botão ═══
export async function renderPecas(){
  let h=cover('geral','Peças — o que sai daqui assinável',
    'Os produtos completos do motor: <b>dossiê completo</b> por CNPJ, <b>dossiê mestre</b> de licitações por órgão, <b>minuta em .docx</b> pronta para o gabinete assinar (requerimento ALERJ ou representação ao TCE), dossiê pericial de PPP, auditoria de acatamento de parecer e avaliação de conjunto dos certames. Geração assíncrona: o arquivo chega no Telegram e aparece em Relatórios.','📜');
  h+=card(`<div class="search"><span class="mag"></span>
      <input id="pc-alvo" placeholder="CNPJ, nome de fornecedor, órgão ou UG…"></div>
    <div class="dim" style="margin-top:8px">Para acatamento de parecer, informe o número do processo SEI.</div>`);
  const b=(rota,rot,desc,campo)=>card(
    `<div style="font-weight:700">${esc(rot)}</div><div class="dim" style="margin-top:4px">${desc}</div>
     <div class="btns" style="margin-top:10px"><button type="button" class="btn" onclick="pecaGerar('${rota}','${campo}')">Gerar</button></div>`);
  h+=`<div class="grid g2" style="margin-top:12px">`+[
    b('/api/dossie/completo','Dossiê completo (CNPJ)','360 + fachada + cláusulas na íntegra + suspeitas + árvore SEI + parecer + planilha.','cnpj'),
    b('/api/dossie/mestre','Dossiê mestre de licitações','Portfólio de certames do órgão, com ranking por dano e escalada sugerida.','orgao'),
    b('/api/mandato/minuta','Minuta .docx para assinar','Requerimento de informação (ALERJ) ou representação ao TCE-RJ, já fundamentado.','alvo'),
    b('/api/ppp','Dossiê pericial de PPP/concessão','Perícia de parceria público-privada: equilíbrio, aportes, matriz de risco.','alvo'),
    b('/api/sei/acatamento','Acatamento de parecer (art. 53)','O gestor seguiu o parecer jurídico? Divergência não motivada é achado.','processo'),
    // 2026-08-02: até aqui, processo ainda não avaliado devolvia a mensagem "POST /api/processo/avaliar"
    // e NÃO havia botão nenhum — o painel mandava o usuário fazer uma requisição HTTP à mão. A rota
    // só tinha "superfície" porque duplicava o /processo no menu; tirada a duplicata, o buraco apareceu.
    b('/api/processo/avaliar','Avaliar um processo SEI ainda não avaliado','Dispara a avaliação 360 em background (fases, marcos, A1-A5, acatamento, juízo por documento). Use quando a consulta disser que o processo ainda não foi avaliado.','numero'),
    b('/api/conjunto/orgao','Avaliação de conjunto dos certames','Lê o órgão como conjunto, não certame a certame — §5 da metodologia.','orgao'),
  ].join('')+`</div><div id="pc-out"></div>`;
  // SÍNTESE GLOBAL — a leitura de CONJUNTO do processo. A lista de achados responde "o que há de
  // errado"; isto responde "o que este processo mostra": a ordem dos atos, quem decidiu, onde os
  // documentos se contradizem. Num processo de 484 documentos e 3 milhões de caracteres, é a
  // única forma de ver o todo.
  // A FILA DO FISCAL — a ORDEM em que os autos devem ser abertos. Ela era calculada há semanas e
  // vivia só como markdown em disco: quem quisesse a prioridade da casa tinha de abrir um arquivo.
  // Painel sem a fila é a mesma família do "construído, testado, nunca rodado".
  h+=sec('Fila do fiscal — por onde começar');
  h+=card(`<div class="dim">Ordenada por <b>qualidade do achado</b>, não por score cru: o score de
      convergência satura no topo em processo grande, e ali tudo parece igual. Vício <b>lido nos
      autos</b> pesa mais que indício sobre a empresa.</div>
    <div class="btns" style="margin-top:10px">
      <button type="button" class="btn" data-fila="todos">Ver a fila</button>
      <button type="button" class="btn ghost" data-fila="osint">Só os com sinal OSINT</button>
    </div><div id="ff-out"></div>`);

  h+=sec('Leitura de conjunto de um processo SEI');
  h+=card(`<div class="dim">O esqueleto do processo fase a fase, as contradições entre documentos
      e a leitura do todo — sobre TODOS os documentos capturados, sem corte de páginas.</div>
    <div class="btns" style="margin-top:10px">
      <input id="sg-num" class="inp" placeholder="SEI-070002/001289/2022" style="min-width:260px">
      <button type="button" class="btn" onclick="sinteseProcesso()">Ler o conjunto</button>
    </div><div id="sg-out"></div>`);
  h+=`<div class="note">Toda peça passa pelo gate de neutralidade (nenhum nome interno) e pelo gate de citações (nenhum acórdão inexistente).</div>`;
  return h;
}

export async function filaFiscal(soOsint){
  const o=$('ff-out');
  o.innerHTML=card('<div class="dim">recalculando a fila sobre o acervo de hoje…</div>');
  const d=await J('/api/fiscal/fila?limite=60'+(soOsint?'&so_osint=1':''));
  if(!d||d.ok===false){o.innerHTML=card(`<div class="warn">${erroHumano(d&&d.erro)}</div>`);return;}
  const it=d.itens||[];
  if(!it.length){
    o.innerHTML=card(soOsint
      ? '<div class="dim">Nenhum processo da fila tem sinal OSINT hoje. <b>Não observado nesta rodada</b> não é ausência de vínculo — o grafo cresce a cada varredura.</div>'
      : '<div class="warn">Fila vazia — o ranking não devolveu processo algum.</div>');
    return;
  }
  const cor=g=>/EXTREMO/.test(g||'')?'var(--red)':(/ALTO/.test(g||'')?'var(--amber)':null);
  let h=`<div class="grid g2" style="margin-top:12px">
      ${kpi(fmtN(d.total),'Processos na fila','var(--amber)','📋',{drill:'ffTodos'})}
      ${kpi(fmtN(d.com_osint),'Com sinal OSINT',(d.com_osint||0)?'var(--red)':null,'🕸️',{drill:'ffOsint'})}</div>`;
  h+=leitura(esc(d.regua||''));
  const _lin=x=>card(`<div style="display:flex;justify-content:space-between;gap:10px">
      <div style="min-width:0">
        <div style="font-weight:700">${x.posicao}. ${esc(x.processo)}</div>
        <div class="dim">${esc(x.grau)}</div>
        <div style="font-size:12.5px;margin-top:4px">${esc(x.motivos||'')}</div>
      </div>
      <div class="right">
        <div class="num" style="font-weight:800;color:${cor(x.grau)||'inherit'}">${x.pontos}</div>
        <div class="dim">pontos</div>
        <button type="button" class="btn ghost" style="margin-top:6px"
                data-fila-abrir="${esc(x.processo)}">Abrir</button>
      </div></div>`, x.osint?'hl':'');
  registrarDrill('ffTodos',{titulo:'Fila do fiscal',itens:it,render:_lin});
  registrarDrill('ffOsint',{titulo:'Processos com sinal OSINT',itens:it.filter(x=>x.osint),render:_lin,
    nota:'Sinal OSINT NUNCA supera vício lido nos autos: conflito de órgão vale 3, achado de pagamento sem execução vale 5.'});
  h+=`<div class="grid">`+it.map(_lin).join('')+`</div>`;
  h+=`<div class="note">${esc(d.resumo||'')} · a fila é recalculada a cada consulta, sobre o acervo do momento.</div>`;
  o.innerHTML=h;
  // Os cinco painéis de PADRÃO que acompanham a fila: a fila mostra processo a processo, e o que
  // se leva ao TCE-RJ é a taxa, a janela, a concentração por grupo, a coparticipação de
  // relacionadas e a exposição a empresa em recuperação judicial.
  // EM SEQUÊNCIA, não em paralelo. A API é single-process: sete fetches simultâneos não são
  // atendidos ao mesmo tempo, viram fila — e na primeira visita (cache frio, 2 vCPU) o último da
  // fila demorava tanto que o card parecia não existir. Em sequência cada painel aparece assim que
  // fica pronto, na ordem em que o fiscal lê.
  (async () => {
    for (const f of [taxaPorUnidade, fimDeExercicio, concentracaoPorGrupo,
                     coparticipacaoRelacionados, recuperacaoJudicial, aditivoPrecoce,
                     nucleoCartel, consorcioVeiculo, emergenciaRecorrente, leituraDupla, zerosSemCausa,
                     detectoresFramework]) {
      try { await f(); } catch (e) { console.warn('painel de padrão falhou:', e); }
    }
  })();
}

// O PADRÃO NÃO CABE NA FILA. A fila mostra processo a processo; o achado que se leva ao TCE-RJ
// é a TAXA da unidade — 45,8% do Fundo Estadual da Saúde contra 0% dos 44 do Fundo dos
// Bombeiros, e o contraste SOBE quando se controla pela profundidade de leitura (66% × 0% na
// faixa de 10 a 19 documentos), o que afasta a hipótese de artefato do gate.
async function taxaPorUnidade() {
  const o = $("ff-out");
  if (!o) return;
  const d = await J("/api/fiscal/taxa_por_unidade");
  if (!d || d.ok === false) return;
  const alvo = document.createElement("div");
  if (!(d.itens || []).length) {
    alvo.innerHTML = sec("Taxa da lacuna por unidade")
      + vazioDeclarado(d, "unidade com processos avaliados suficientes para publicar taxa");
    o.appendChild(alvo); return;
  }
  const fx = (v, k) => { const f = (v.faixas || {})[k] || [0, 0]; return f[0] ? `${f[1]}/${f[0]}` : "—"; };
  alvo.innerHTML = sec("O padrão por unidade — pagamento sem prova de execução")
    + card(`<table class="tb"><thead><tr><th>Unidade</th><th class="right">avaliados</th>
      <th class="right">com a lacuna</th><th class="right">taxa</th><th class="right">1-9 docs</th>
      <th class="right">10-19</th><th class="right">20-49</th></tr></thead><tbody>`
      + d.itens.map((x) => `<tr><td>${esc(x.unidade)}</td><td class="right">${fmtN(x.n)}</td>
          <td class="right">${fmtN(x.com)}</td>
          <td class="right" style="font-weight:800;color:${x.taxa >= 25 ? "var(--red)" : x.taxa >= 10 ? "var(--amber)" : "inherit"}">${x.taxa}%</td>
          <td class="right dim">${fx(x, "1-9")}</td><td class="right dim">${fx(x, "10-19")}</td>
          <td class="right dim">${fx(x, "20-49")}</td></tr>`).join("")
      + `</tbody></table>`)
    + leitura(esc(d.ressalva || ""));
  o.appendChild(alvo);
}

// A JANELA EM QUE A LIQUIDAÇÃO AFROUXA. Dezembro é quando o empenho precisa ser consumido, e é
// onde a prova de entrega costuma faltar: a NRTT recebeu R$ 25,4 mi em SETE OBs num único 28/12,
// e a EVOLUÇÃO teve 30 OBs num 22/12. Concentrar pagamento em dezembro é legal — o que a tela diz
// é ONDE conferir medição, atesto e recebimento definitivo.
async function fimDeExercicio() {
  const o = $("ff-out");
  if (!o) return;
  const d = await J("/api/fiscal/fim_de_exercicio?limite=15");
  if (!d || d.ok === false) return;
  const alvo = document.createElement("div");
  if (!(d.itens || []).length) {
    alvo.innerHTML = sec("Ano inteiro pago em nov–dez")
      + vazioDeclarado(d, "credor privado com o ano concentrado no fim do exercício");
    o.appendChild(alvo); return;
  }
  alvo.innerHTML = sec(`Ano inteiro pago em nov–dez (${fmtN(d.total)} credores privados)`)
    + card(`<table class="tb"><thead><tr><th>Ano</th><th>Credor</th><th class="right">total no ano</th>
      <th class="right">% em nov–dez</th><th class="right">OBs</th></tr></thead><tbody>`
      + d.itens.map((x) => `<tr><td>${esc(String(x.exercicio))}</td>
          <td>${esc(x.nome.slice(0, 46))} <span class="dim">${esc(x.raiz)}</span></td>
          <td class="right">${fmtRc(x.total)}</td>
          <td class="right" style="font-weight:800;color:${x.pct >= 95 ? "var(--red)" : "var(--amber)"}">${x.pct}%</td>
          <td class="right dim">${fmtN(x.obs)}</td></tr>`).join("")
      + `</tbody></table>`)
    + leitura(esc(d.ressalva || ""));
  o.appendChild(alvo);
}

// O QUE O CNPJ ESCONDE. Um órgão pode contratar dez empresas e pagar quase tudo a um só dono: o
// HHI da UG 660100 em 2025 é 0,1022 por CNPJ ("desconcentrado") e 0,3671 por GRUPO, com 7 CNPJs
// somando 57,5%. Ordena pelo DELTA, não pelo HHI — UG dominada por fornecedor único já aparecia
// na medida por CNPJ e não é o que esta tela procura.
// O `cimento` é obrigatório na leitura: 2 de 5 pontes ADMINISTRANDO duas empresas (Cidades) não
// é a mesma coisa que 1 em 28 numa teia de sociedades médicas de cotistas (FSERJ, 10,3%).
async function concentracaoPorGrupo() {
  const o = $("ff-out");
  if (!o) return;
  const d = await J("/api/fiscal/concentracao_por_grupo?ano=2025&limite=10");
  if (!d || d.ok === false) return;
  if (!(d.itens || []).length) {
    const vazio = document.createElement("div");
    vazio.innerHTML = sec("Concentração por grupo econômico")
      + vazioDeclarado(d, "unidade gestora concentrada por grupo em 2025");
    o.appendChild(vazio); return;
  }
  const rot = { comando_comum: ["comando comum", "var(--red)"],
                coparticipacao_com_excecao: ["coparticipação (1 exceção)", "var(--amber)"],
                coparticipacao: ["coparticipação", "inherit"] };
  const alvo = document.createElement("div");
  alvo.innerHTML = sec("Concentração por GRUPO econômico — o que a medição por CNPJ não mostra")
    + card(`<table class="tb"><thead><tr><th>Unidade</th><th class="right">pago em 2025</th>
      <th class="right">HHI CNPJ</th><th class="right">HHI grupo</th>
      <th class="right">maior grupo</th><th>o que sustenta o grupo</th>
      <th>base</th></tr></thead><tbody>`
      + d.itens.map((x) => {
        const g = x.maior_grupo || {}, c = g.cimento || {};
        const [txt, cor2] = rot[c.tipo] || ["QSA indisponível", "inherit"];
        // A COBERTURA É POR LINHA. O ranking mistura UG com base completa e UG com 100% da amostra
        // ausente da fonte canônica — comparar as frações sem isso é comparar o que não se compara.
        const cb = x.cobertura || {};
        const base = cb.estado === "parcial"
          ? `<span style="color:var(--red)">parcial · ${cb.pct_ausente}% ausente</span>`
          : (cb.estado === "coberto" ? '<span class="dim">coberta</span>'
             : `<span class="dim">${esc(cb.estado || "—")}</span>`);
        return `<tr><td>${esc(x.nome_ug || ("UG " + x.ug))} <span class="dim">${esc(x.ug)}</span></td>
          <td class="right">${fmtRc(x.total_pago)}</td>
          <td class="right dim">${x.hhi_por_cnpj.toFixed(4)}</td>
          <td class="right" style="font-weight:800;color:${x.hhi_por_grupo >= 0.25 ? "var(--red)" : "inherit"}">${x.hhi_por_grupo.toFixed(4)}</td>
          <td class="right">${((g.fracao || 0) * 100).toFixed(1)}% <span class="dim">${fmtN(g.n_cnpj || 0)} CNPJs</span></td>
          <td style="color:${cor2}">${esc(txt)}${c.pontes ? ` <span class="dim">${c.pontes_que_administram}/${c.pontes} pontes</span>` : ""}</td>
          <td style="font-size:12px">${base}</td></tr>`;
      }).join("")
      + `</tbody></table>`)
    + leitura("<b>A coluna 'base' não é detalhe técnico.</b> Onde a fonte canônica está parcial, o "
      + "valor pago é PISO e a fração do maior grupo só se sustenta se o que falta for aleatório — "
      + "ela pode estar enviesada nos dois sentidos. " + esc(d.ressalva || ""));
  o.appendChild(alvo);
}

// AS DUAS DO MESMO COMANDO NA MESMA DISPUTA. Cruza os 82.941 licitantes municipais do TCE-RJ com
// o quadro societário — a travessia que o resolver_nome_cnpj foi escrito para permitir e que
// nenhum módulo fazia. O elo tem de estar VIGENTE na data: sem esse filtro os dois maiores pares
// eram anacronismos (o administrador comum entrou no ano seguinte ao certame).
/* VAZIO DECLARADO. Um card que não renderiza não produz erro nenhum — foi assim que dois dos seis
   painéis de padrão sumiram do ar sem uma linha no console (família 38 do catálogo). E lista vazia
   tem DUAS causas opostas: medi e não achei, ou não tenho a fonte. Calar as duas na mesma tela em
   branco é a afirmação mais perigosa que um painel de fiscalização pode fazer. */
function vazioDeclarado(d, oQue){
  const f=d.fonte||{}; const t=f.tabelas||{};
  if(f.ok===false){
    const falta=Object.entries(t).filter(([,v])=>v==='ausente'||v===0).map(([k])=>k).join(', ');
    return card(`<div class="dim"><b>Não medido</b> — ${esc(oQue)}: fonte indisponível${
      falta?' ('+esc(falta)+')':''}${f.erro?': '+esc(f.erro):''}. Lista vazia aqui significa
      <b>não medi</b>, nunca "nada a apurar".</div>`);
  }
  return card(`<div class="dim">Nenhum caso de ${esc(oQue)} <b>na fatia já medida</b> — a base foi
    varrida e respondeu. Ausência aqui é resultado, não silêncio; a fatia é que limita.</div>`);
}

async function coparticipacaoRelacionados() {
  const o = $("ff-out");
  if (!o) return;
  const d = await J("/api/fiscal/coparticipacao_relacionados?limite=12");
  if (!d || d.ok === false) return;
  const alvo = document.createElement("div");
  if (!(d.itens || []).length) {
    alvo.innerHTML = sec("Relacionadas no mesmo certame")
      + vazioDeclarado(d, "empresas relacionadas disputando o mesmo certame");
    o.appendChild(alvo); return;
  }
  alvo.innerHTML = sec(`Relacionadas no mesmo certame (${fmtN(d.total)} pares)`)
    + card(`<table class="tb"><thead><tr><th class="right">certames</th><th class="right">mun.</th>
      <th>empresa A</th><th>empresa B</th><th>elo vigente</th>
      <th class="right">homologado</th></tr></thead><tbody>`
      + d.itens.map((x) => `<tr>
          <td class="right" style="font-weight:800;color:${x.certames >= 4 ? "var(--red)" : x.certames >= 3 ? "var(--amber)" : "inherit"}">${x.certames}</td>
          <td class="right dim">${x.municipios}</td>
          <td>${esc(x.nome_a.slice(0, 30))} <span class="dim">${esc(x.cnpj_a)}</span></td>
          <td>${esc(x.nome_b.slice(0, 30))} <span class="dim">${esc(x.cnpj_b)}</span></td>
          <td class="dim">${esc((x.elos || []).join("; ").slice(0, 44))}</td>
          <td class="right">${fmtRc(x.valor)}</td></tr>`).join("")
      + `</tbody></table>`)
    + leitura(esc(d.ressalva || ""));
  o.appendChild(alvo);
}

// A EMPRESA EM CRISE ENTRA PELO CONSÓRCIO. Seis consórcios da UG 660100 carregam a MESMA empresa
// em recuperação judicial no quadro societário — R$ 415,5 mi pagos, invisíveis a qualquer busca
// pelo nome do credor. Participar NÃO é vedado (exige plano homologado e viabilidade
// demonstrada): a tela diz onde conferir a habilitação econômico-financeira.
async function recuperacaoJudicial() {
  const o = $("ff-out");
  if (!o) return;
  const d = await J("/api/fiscal/recuperacao_judicial?limite=12");
  if (!d || d.ok === false) return;
  const alvo = document.createElement("div");
  if (!(d.itens || []).length) {
    alvo.innerHTML = sec("Pagos em recuperação judicial")
      + vazioDeclarado(d, "credor pago com recuperação judicial no quadro");
    o.appendChild(alvo); return;
  }
  alvo.innerHTML = sec(`Pagos em recuperação judicial — ${fmtN(d.total)} credores, ${fmtRc(d.soma)}`)
    + card(`<table class="tb"><thead><tr><th>Credor</th><th class="right">UGs</th><th>anos</th>
      <th>como aparece</th><th class="right">pago (OB)</th><th class="right">OBs</th></tr></thead><tbody>`
      + d.itens.map((x) => `<tr>
          <td>${esc(x.nome.slice(0, 42))} <span class="dim">${esc(x.raiz)}</span></td>
          <td class="right dim">${x.n_ug}</td><td class="dim">${esc(x.anos)}</td>
          <td style="color:${x.via === "credor" ? "inherit" : "var(--amber)"}">${esc(x.via)}${
            (x.membros_em_recuperacao || []).length
              ? ` <span class="dim">${esc(x.membros_em_recuperacao[0].slice(0, 30))}</span>` : ""}</td>
          <td class="right" style="font-weight:700">${fmtRc(x.total)}</td>
          <td class="right dim">${fmtN(x.obs)}</td></tr>`).join("")
      + `</tbody></table>`)
    + leitura(esc(d.ressalva || ""));
  o.appendChild(alvo);
}

/* Delegação única para a fila — nenhum nome novo no `window`. A catraca de globais do painel
   chegou a 59 porque handler inline é sempre o caminho mais curto na hora, e a conta só aparece
   depois. Um ouvinte no `document` sobrevive à troca de `innerHTML` do `#view`, que é justamente
   onde os botões inline morriam. Ligado uma vez no boot, junto com os demais. */
export function ligarFila(){
  document.addEventListener('click',ev=>{
    if(!ev.target.closest)return;
    const b=ev.target.closest('[data-fila]');
    if(b){ev.preventDefault();filaFiscal(b.dataset.fila==='osint'?1:0);return;}
    const a=ev.target.closest('[data-fila-abrir]');
    if(!a)return;
    ev.preventDefault();
    const i=$('sg-num'); if(!i)return;
    i.value=a.getAttribute('data-fila-abrir');
    i.scrollIntoView({behavior:'smooth',block:'center'});
    sinteseProcesso();
  });
}

export async function sinteseProcesso(){
  const v=($('sg-num')?.value||'').trim(); const o=$('sg-out');
  if(!v){o.innerHTML=card('<div class="warn">Informe o número do processo.</div>');return;}
  o.innerHTML=card('<div class="dim">lendo o conjunto…</div>');
  try{
    const d=await J('/api/processo?numero='+encodeURIComponent(v));
    if(d&&d.rodando){o.innerHTML=card('<div class="dim">avaliação em curso — tente em instantes.</div>');return;}
    const a=(d&&(d.avaliacao||d))||{}; const s=a.sintese;
    if(!s||s.indisponivel){
      o.innerHTML=card(`<div class="warn">Síntese INDISPONÍVEL para este processo${s&&s.motivo?': '+esc(s.motivo):''} — indisponível não é ausência de irregularidade.</div>`);
      return;
    }
    const fases=Object.entries(s.fases||{}).map(([f,r])=>
      `<tr><td>${esc(f)}</td><td class="r">${r.n_docs}</td>
       <td>${r.de?esc(r.de)+' → '+esc(r.ate):'<span class="dim">sem data</span>'}</td>
       <td class="r">${r.viciados?'<b class="bad">'+r.viciados+'</b>':'—'}</td>
       <td class="dim">${(r.assinantes||[]).slice(0,3).map(esc).join(', ')||'—'}</td></tr>`).join('');
    const contr=(s.contradicoes||[]).map(c=>
      `<li><b>${esc(c.codigo)}</b> — ${esc(c.diz)}<br><span class="dim">${esc(c.evidencia||'')}</span></li>`).join('');
    o.innerHTML=card(
      `<div style="font-weight:700">${esc(v)}</div>
       <div style="margin:8px 0">${esc(s.leitura||'')}</div>
       <table class="tb"><thead><tr><th>Fase</th><th class="r">Docs</th><th>Período</th>
         <th class="r">Viciados</th><th>Assinantes</th></tr></thead><tbody>${fases}</tbody></table>
       ${contr?`<div style="margin-top:10px;font-weight:700">Contradições entre documentos (${s.contradicoes.length})</div><ul>${contr}</ul>`
              :'<div class="dim" style="margin-top:8px">Nenhuma contradição entre documentos pela leitura do conjunto.</div>'}
       ${s.prosa?`<div style="margin-top:10px">${esc(s.prosa)}</div>`:''}`);
  }catch(e){ o.innerHTML=card(`<div class="warn">${erroHumano(String(e))}</div>`); }
}

export async function pecaGerar(rota,campo){
  const v=($('pc-alvo')?.value||'').trim(); const o=$('pc-out');
  if(!v){o.innerHTML=card('<div class="warn">Informe o alvo acima.</div>');return;}
  o.innerHTML=card('<div class="dim">acionando… a geração é assíncrona; o arquivo chega no Telegram e em Relatórios.</div>');
  try{
    const d=await J(rota,{method:'POST',headers:{'Content-Type':'application/json'},
                          body:JSON.stringify({[campo]:v,alvo:v})});
    if(d&&d.ambiguo){
      o.innerHTML=card(`<div style="font-weight:700">${esc(d.pergunta||'Alvo ambíguo')}</div>`+
        `<div class="grid" style="margin-top:8px">`+(d.candidatos||[]).map(c=>
          `<button type="button" class="btn ghost" onclick="$('pc-alvo').value='${esc(c.cnpj||c.ug||c.nome)}';pecaGerar('${rota}','${campo}')">${esc(c.nome||c.razao||c.cnpj)}</button>`).join('')+`</div>`);
      return;
    }
    o.innerHTML=card(`<div class="ok">Acionado.</div><div class="dim" style="margin-top:6px">${esc(d.mensagem||d.status||'A peça chega no Telegram quando terminar.')}</div>`);
  }catch(e){ o.innerHTML=card(`<div class="warn">${erroHumano(String(e))}</div>`); }
}

// ═══ FONTES EXTERNAS — os seis providers que ninguém alcançava ═══
export async function renderFontesExternas(){
  let h=cover('geral','Fontes externas — o que se sabe fora da nossa base',
    'Consulta pontual às fontes abertas já integradas: cadastro da Receita, idoneidade (CEIS/CNEP), estrutura societária global (GLEIF), vazamentos indexados (ICIJ), rastro na web e diário oficial municipal. Todas gratuitas; nenhuma exige chave paga.','🛰️');
  h+=card(`<div class="search"><span class="mag"></span>
      <input id="fx-alvo" placeholder="CNPJ, CPF mascarado, nome ou domínio…"
             onkeydown="if(event.key==='Enter')fxConsultar('/api/empresa')"></div>
    <div class="btns" style="margin-top:10px;flex-wrap:wrap">
      <button type="button" class="btn" onclick="fxConsultar('/api/empresa')">Cadastro (Receita)</button>
      <button type="button" class="btn ghost" onclick="fxConsultar('/api/idoneidade')">Idoneidade</button>
      <button type="button" class="btn ghost" onclick="fxConsultar('/api/ownership')">Estrutura (GLEIF)</button>
      <button type="button" class="btn ghost" onclick="fxConsultar('/api/leaks')">Vazamentos (ICIJ)</button>
      <button type="button" class="btn ghost" onclick="fxConsultar('/api/links')">Rastro na web</button>
      <button type="button" class="btn ghost" onclick="fxConsultar('/api/diario')">Diário oficial</button>
    </div>`);
  h+=`<div id="fx-out"></div>`;
  h+=`<div class="note">Ausência de resultado numa fonte externa é <b>INDISPONÍVEL</b>, não prova de inexistência: a cobertura de cada base é parcial e declarada por ela mesma.</div>`;
  /* v49: o que cada fonte NÃO tem deixa de viver só em prosa de handoff. Fonte que falha calada
     devolve lista vazia, e lista vazia vira "nada encontrado" no parecer — afirmação falsa por
     omissão. Aqui o limite é DADO, e a tabela diz se é bloqueio (contornável) ou limite da fonte. */
  const lim=await J('/api/fontes/limites');
  if(lim&&lim.ok&&(lim.itens||[]).length){
    h+=sec(`Limites conhecidos das fontes — ${lim.bloqueios} bloqueio(s), ${lim.limites_de_dado} limite(s) de dado`);
    h+=card(`<table><thead><tr><th>Fonte</th><th>Tipo</th><th>O que acontece</th><th>Caminho alternativo</th><th>Medido</th></tr></thead><tbody>`
      +lim.itens.map(x=>`<tr>
          <td><b>${esc(x.fonte)}</b></td>
          <td><span class="pill ${x.tipo==='bloqueio'?'medio':'alto'}">${x.tipo==='bloqueio'?'bloqueio':'limite da fonte'}</span></td>
          <td>${esc(x.o_que_acontece)}</td>
          <td class="dim">${esc(x.caminho_alternativo)}</td>
          <td class="dim">${esc(x.medido_em)}</td></tr>`).join('')
      +`</tbody></table>
        <div class="note">Um <b>bloqueio</b> pode cair amanhã e vale retentar; um <b>limite da fonte</b> não —
        a base simplesmente não tem aquele campo, e insistir é queimar sessão. Este quadro existe para
        a peça escrever <b>LACUNA nomeada</b> em vez de "nada encontrado".</div>`);
  }
  return h;
}

export async function fxConsultar(rota){
  const v=($('fx-alvo')?.value||'').trim(); const o=$('fx-out');
  if(!v){o.innerHTML=card('<div class="warn">Informe o alvo.</div>');return;}
  o.innerHTML=card('<div class="dim">consultando…</div>');
  const d=await J(rota+'?alvo='+encodeURIComponent(v)+'&cnpj='+encodeURIComponent(v)+'&q='+encodeURIComponent(v));
  if(d&&d.ok===false){o.innerHTML=card(`<div class="warn">${erroHumano(d.erro)}</div>`);return;}
  /* v58: era JSON.stringify cru num <pre> — o operador tinha de LER JSON para saber se a fonte
     respondeu. Agora os campos escalares viram tabela (o que a fonte disse), e o JSON completo
     fica atrás de um <details> para quem precisa do bruto. Campo composto (lista/objeto) não é
     achatado: diz o tamanho e remete ao bruto — resumir estrutura seria inventar leitura. */
  const linhas=Object.entries(d||{}).filter(([k])=>k!=='ok'&&k!=='erro').map(([k,v])=>{
    const composto=v&&typeof v==='object';
    const val=composto?`<span class="dim">${Array.isArray(v)?fmtN(v.length)+' item(ns)':'objeto'} — ver bruto</span>`
                     :(v===null||v===''?'<span class="dim">INDISPONÍVEL</span>':esc(String(v)));
    return `<tr><td><b>${esc(k)}</b></td><td>${val}</td></tr>`;});
  o.innerHTML=sec(esc(rota.replace('/api/','')))+card(
    (linhas.length?`<table><thead><tr><th style="width:34%">Campo</th><th>Valor</th></tr></thead><tbody>${linhas.join('')}</tbody></table>`
                 :`<div class="dim">A fonte respondeu sem campos — <b>INDISPONÍVEL</b>, não "nada consta".</div>`)
    +`<details style="margin-top:10px"><summary class="dim" style="cursor:pointer">resposta bruta (JSON)</summary>
      <pre style="white-space:pre-wrap;font-size:12px;margin:8px 0 0">${esc(JSON.stringify(d,null,1))}</pre></details>`);
}

// ═══ HUB FÍSICO — uma âncora, vários CNPJs (detector novo que nasceu sem aba) ═══
export async function renderHubFisico(){
  const d=await J('/api/intel/hub_compartilhado?limite=150');
  if(!d.ok)return sec('Hub compartilhado')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||d.hubs||[];
  let h=cover('geral','Hub físico — uma âncora, vários fornecedores',
    'Endereço, telefone ou e-mail <b>idêntico</b> em empresas distintas que vendem ao Estado. A lição já paga: <b>mesma sala</b> significa muito, <b>mesmo prédio</b> quase nada — o topo do acervo por prédio é um endereço com 318 CNPJs. Só a âncora com complemento (sala/andar) pesa.','🏢')+acoesAba('hub_compartilhado');
  /* `Hubs` e `Com complemento` contam o mesmo `a` desta tela. `CNPJs envolvidos` é uma SOMA de
     campos, não uma contagem de linhas — abrir uma gaveta com os hubs ali faria o clique mostrar
     menos linhas do que o número promete, que é o defeito que esta casa já cometeu duas vezes. */
  const _linHub=x=>card(`<div style="display:flex;justify-content:space-between;gap:10px"><div style="min-width:0"><div style="font-weight:700">${esc(x.ancora||x.endereco||x.valor||'—')}</div><div class="dim">${esc(x.tipo||'')}${x.complemento?' · '+esc(x.complemento):''}</div></div><div class="right"><div class="num" style="font-weight:800">${fmtN(x.n_cnpjs||x.n||0)}</div><div class="dim">CNPJs</div></div></div>`);
  registrarDrill('hubTodos',{titulo:'Hubs — âncora compartilhada por empresas distintas',itens:a,render:_linHub,
    nota:'Mesma SALA pesa; mesmo PRÉDIO quase nada — o topo do acervo por prédio tem 318 CNPJs.'});
  registrarDrill('hubComComplemento',{titulo:'Hubs com complemento (sala/andar) — os que pesam',
    itens:a.filter(x=>(x.tipo||'').includes('sala')||x.complemento),render:_linHub});
  h+=`<div class="grid g2">${kpi(fmtN(a.length),'Hubs','var(--amber)','🏢',{drill:'hubTodos'})}
      ${kpi(fmtN(a.reduce((s,x)=>s+(x.n_cnpjs||x.n||0),0)),'CNPJs envolvidos',null,null,
        {sobre:'Soma de CNPJs distintos nos agrupamentos exibidos. A mesma empresa pode aparecer em mais de um grupo — o número mede alcance do padrão, não quantidade de empresas suspeitas.'})}
      ${kpi(fmtN(a.filter(x=>(x.tipo||'').includes('sala')||x.complemento).length),'Com complemento (sala/andar)','var(--rose)','🚪',{drill:'hubComComplemento'})}</div>`;
  h+=`<div class="search" style="margin-top:12px"><span class="mag"></span><input placeholder="filtrar por âncora ou empresa…" oninput="filtrar(this,'#hub-list .card')"></div>`;
  h+=`<div id="hub-list" class="grid">`+a.map(x=>card(
    `<div style="font-weight:700">${esc(x.ancora||x.endereco||x.valor||'—')} <span class="tag">${esc(x.tipo||'endereço')}</span></div>
     <div class="muted" style="font-size:12.5px;margin-top:3px">${esc((x.empresas||x.cnpjs||[]).join(' · '))}</div>
     <div class="dim" style="margin-top:4px">${fmtN(x.n_cnpjs||x.n||(x.empresas||[]).length)} empresas</div>`,
    (x.n_cnpjs||x.n||0)>=4?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'Coworking, escritório virtual e prédio comercial hospedam empresas sem relação — a âncora é indício, não prova.')}</div>`;
  return h;
}

// ═══ ACURÁCIA — o motor medido, publicado junto do produto ═══
export async function renderAcuracia(){
  let h=cover('geral','Acurácia — o quanto o juízo do motor acerta',
    'Publica a métrica do próprio motor: acurácia do juízo jurídico contra o conjunto-ouro de casos do TCU (F1 macro contra baseline burro) e o <b>lift</b> de cada detector — quantas vezes ele acerta acima da taxa-base. Detector com lift abaixo de 1 é <b>anti-preditivo</b>: acende mais no regular que no irregular.','🎯');
  /* DUAS ETAPAS, medido em campo (2026-07-31): hermenêutica volta em 0,031 s e o lift em 18,95 s.
     Num Promise.all a aba inteira ficava 19 s em "Carregando…" sem dizer nada — não era aba muda,
     era espera sem retorno visual. Agora o bloco rápido sai na hora e o lift entra no lugar dele
     quando chegar, com esqueleto próprio e o aviso de que aquele cálculo demora. */
  const he=await J('/api/eval/hermeneutica');
  if(he&&he.estado&&he.estado!=='medido'){
    h+=sec('Juízo jurídico (conjunto-ouro TCU)');
    h+=semMedicao(he,'Ainda não medido neste ambiente');
    if(he.tem_baseline===false)h+=`<div class="dim">Também não há baseline aceito — a primeira medição vira o baseline.</div>`;
  }else if(he&&he.ok!==false){
    h+=sec('Juízo jurídico (conjunto-ouro TCU)');
    h+=`<div class="grid g2">${kpi(fmtD(he.f1_macro,3),'F1 macro',null,'⚖️',{sobre:'Média harmônica de precisão e recall, calculada por CLASSE e depois promediada (macro) — cada classe pesa igual, mesmo as raras. É a régua honesta quando as classes são desbalanceadas: acertar só a classe comum não infla o número. Fonte: casos ROTULADOS À MÃO em <code>eval_groundtruth</code>. Recalcula com <code>python -m tools.eval_hermeneutica</code>.'})}
        ${kpi(fmtD(he.baseline_f1,3),'F1 do baseline burro',null,null,{sobre:'O que um chute sem inteligência alcançaria (classe majoritária sempre). Existe para responder a única pergunta que importa sobre um F1: <b>ele é melhor que nada?</b> Modelo acima do baseline por pouco não sustenta decisão. Mesma fonte e mesmo comando do F1 macro.'})}
        ${kpi(he.acuracia==null?'—':fmtD(100*he.acuracia,1)+'%','Acurácia',null,null,{sobre:'Proporção de acertos sobre os casos ROTULADOS À MÃO. Sozinha ela engana quando as classes são desbalanceadas — acertar só a classe comum já dá acurácia alta. Por isso o F1 macro está ao lado, e o F1 do baseline burro ao lado dele.'})}
        ${kpi(he.n==null?'—':fmtN(he.n),'Casos rotulados',null,null,{sobre:'Quantos casos foram rotulados À MÃO para servir de gabarito. É o DENOMINADOR de todas as métricas desta aba: um F1 excelente sobre poucas dezenas de casos diz pouco. Sem rótulo não há medição — e é por isso que este número aparece ao lado dos outros, não escondido.'})}</div>`;
    if(he.alucinacao_citacao!=null)
      h+=leitura(`Alucinação de citação: <b>${fmtD(100*he.alucinacao_citacao,1)}%</b>. Abstenção: ${he.abstencao==null?'—':fmtD(100*he.abstencao,0)+'%'} — abster-se é resultado honesto, não falha.`);
  }else h+=card(`<div class="dim">Acurácia do juízo indisponível nesta execução${he&&he.erro?': '+esc(he.erro):''}.</div>`);

  h+=`<div id="acu-lift">${spin('Calculando o lift dos detectores…')}
      <div class="note">Este cálculo varre o acervo inteiro cruzando cada detector com sanção
      posterior — leva perto de 20 s na primeira carga do dia e responde na hora depois disso.
      O resto da aba já está acima; o lift entra aqui quando terminar.</div></div>`;
  /* O innerHTML da aba só é montado DEPOIS que esta função retorna. Numa segunda visita o lift
     vem do cache de navegação (90 s) e resolve ANTES do mount — escrever direto cairia no vazio
     e a aba ficaria presa no esqueleto justamente no caminho rápido. Daí a espera pelo nó. */
  J('/api/eval/lift',{tetoMs:60000}).then(lf=>{
    const html=_acuLiftHtml(lf); let t=0;
    const por=()=>{const el=$('acu-lift'); if(el)el.innerHTML=html; else if(t++<40)setTimeout(por,50);};
    por();
  });
  return h;
}

export function _acuLiftHtml(lf){
  let h='';
  // Mesmo caso da hermenêutica: painel_lift devolve estado='sem_medicao' + mensagem quando a
  // retro-auditoria não fecha nesta base — vale mostrar o motivo, não uma tabela vazia.
  if(lf&&lf.estado&&lf.estado!=='medido'&&!(lf.detectores||[]).length)
    return sec('Lift por detector')+semMedicao(lf,'Lift ainda não medido nesta base');
  if(lf&&lf.ok!==false){
    const ds=lf.detectores||lf.itens||[];
    h+=sec('Lift por detector',ds.length);
    if(lf.taxa_base!=null) h+=`<div class="dim">Taxa-base do acervo: <b>${fmtD(100*lf.taxa_base,2)}%</b>. Lift 1,0 = o detector não informa nada.</div>`;
    h+=`<table class="tb" style="margin-top:10px"><thead><tr><th>Detector</th><th class="r">Lift</th><th class="r">n</th><th>Leitura</th></tr></thead><tbody>`;
    for(const d of ds){
      const L=Number(d.lift||0);
      const cls=L<1?'bad':(L>=3?'ok':'');
      const lei=L<1?'ANTI-preditivo — acende mais no regular':(d.circular?'lift alto porém CIRCULAR (usa sanção como insumo)':(L>=3?'discrimina bem':'informa pouco'));
      h+=`<tr><td>${esc(d.detector||d.id)}</td><td class="r ${cls}"><b>${fmtD(L,2)}</b></td>
          <td class="r dim">${fmtN(d.n)}</td><td class="dim">${esc(lei)}</td></tr>`;
    }
    h+=`</tbody></table>`;
    h+=`<div class="note">Lift alto por circularidade não é mérito: se o detector usa sanção como insumo e a sanção é o alvo, ele está prevendo o passado.</div>`;
  }else h+=card(`<div class="dim">Lift indisponível nesta execução${lf&&lf.erro?': '+esc(lf.erro):''}.</div>`);
  return h;
}

// ═══ DETECTORES ÓRFÃOS — segunda onda do "ligar tudo" (2026-07-29) ═══
// Cada um destes existia no backend, com teste, e sem uma tela: anomalias por PyOD, rodízio
// temporal, conflito doador↔contrato, sobrepreço contra mediana de mercado, co-endereço,
// concentração geográfica e as duas leituras do D.O. do Rio.
export const _DETS_ORFAOS=[
  {id:'anomalias', rota:'/api/anomalias?top=40', tl:'Anomalias nos pagamentos',
   ic:'🌡️', desc:'Ordens bancárias que fogem do padrão do próprio órgão (ensemble de detecção de outlier + Benford). Outlier não é irregularidade: é onde vale olhar primeiro.', campo:'alertas'},
  {id:'rodizio', rota:'/api/rodizio?top=40', tl:'Rodízio de vencedores',
   ic:'🔄', desc:'Empresas que se revezam nas vitórias do mesmo órgão. Alternância pode ser mercado pequeno — ou combinação. O sinal está na regularidade do revezamento.', campo:'achados'},
  {id:'conflito', rota:'/api/conflito', tl:'Conflito doador ↔ contrato',
   ic:'🗳️', desc:'Doador de campanha (TSE) que é sócio de empresa paga pelo Estado. Doação é lícita e pública; a questão é o que veio depois dela.', campo:'achados'},
  {id:'doador_contrato', rota:'/api/doador_contrato', tl:'Doador × contrato (via QSA)',
   ic:'💸', desc:'Mesma pergunta pelo outro lado: partindo do contrato, chega-se a um doador no quadro societário?', campo:'achados'},
  {id:'sobrepreco', rota:'/api/sobrepreco?top=40', tl:'Sobrepreço vs mercado',
   ic:'📈', desc:'Preço unitário acima da mediana de mercado para item comparável. Só vale sobre item homogêneo — descrição genérica compara produtos diferentes.', campo:'itens'},
  {id:'coendereco', rota:'/api/coendereco/clusters?limite=80', tl:'Co-endereço (grupos por sede)',
   ic:'🏠', desc:'Empresas que dividem a mesma sede. Mesma SALA significa muito; mesmo PRÉDIO quase nada — o topo do acervo por prédio tem 318 CNPJs.', campo:'clusters'},
  {id:'cidades', rota:'/api/orgao/cidades', tl:'Concentração geográfica',
   ic:'🗺️', desc:'De onde vêm os fornecedores do órgão. Concentração num município distante do objeto é indício a explicar.', campo:'cidades'},
  {id:'doe_conc', rota:'/api/pcrj/doe_concentracao', tl:'D.O. Rio — concentração em atas',
   ic:'📰', desc:'Concentração de fornecedores nas atas de registro de preço publicadas no Diário Oficial do Rio.', campo:'achados'},
  {id:'doe_canal', rota:'/api/pcrj/doe_canal_informal', tl:'D.O. Rio — canal informal',
   ic:'📧', desc:'Contratação cujo canal de propostas é e-mail pessoal (gmail e afins) em vez de sistema oficial.', campo:'achados'},
  {id:'tse_ano', rota:'/api/compliance/tse/2022', tl:'Doações eleitorais (TSE) por ano',
   ic:'🗳️', desc:'Doações declaradas ao TSE no exercício. Base pública e lícita — serve para cruzar com quadro societário de fornecedor.', campo:'doacoes'},
  {id:'sei_direc', rota:'/api/sei/direcionamento', tl:'Direcionamento em editais (SEI)',
   ic:'🎯', desc:'Varre os autos do SEI procurando cláusula restritiva de competição, item a item, com a base legal de cada uma.', campo:'achados'},
  {id:'sancoes_det', rota:'/api/sancoes/detalhar', tl:'Sanção — veda de fato?',
   ic:'🚫', desc:'Detalha a sanção: qual cadastro, qual abrangência, qual vigência. Nem toda sanção impede contratar com o Estado.', campo:'sancoes'},
];

export async function renderDetectoresOrfaos(){
  let h=cover('geral','Detectores — leituras que não tinham tela',
    'Dez leituras já implementadas e testadas no motor que nunca tiveram um botão: anomalia em pagamento, rodízio de vencedores, doador que virou fornecedor, sobrepreço contra mercado, sede compartilhada, concentração geográfica e as duas varreduras do Diário Oficial do Rio. Toda leitura aqui é <b>indício</b> — a explicação inocente vem junto.','🧪');
  h+=`<div class="grid g2">`+_DETS_ORFAOS.map(d=>card(
    `<div style="font-weight:700">${svgIco(d.ic)} ${esc(d.tl)}</div>
     <div class="dim" style="margin-top:5px">${d.desc}</div>
     <div class="btns" style="margin-top:10px"><button type="button" class="btn ghost" onclick="detRodar('${d.id}')">Rodar</button></div>
     <div id="det-${d.id}"></div>`)).join('')+`</div>`;
  return h;
}

export async function detRodar(id){
  const d=_DETS_ORFAOS.find(x=>x.id===id); const o=$('det-'+id);
  o.innerHTML='<div class="dim" style="margin-top:8px">lendo…</div>';
  const r=await J(d.rota);
  if(r&&r.ok===false){o.innerHTML=`<div class="warn" style="margin-top:8px">${erroHumano(r.erro)}</div>`;return;}
  const itens=(r&&(r[d.campo]||r.achados||r.itens||r.clusters||r.alertas))||[];
  if(!itens.length){
    o.innerHTML=`<div class="note" style="margin-top:8px">Nada retornado nesta execução. <b>INDISPONÍVEL não é zero</b> — pode ser cobertura parcial da fonte, não ausência do fato.</div>`;
    return;
  }
  let h=`<div class="dim" style="margin-top:8px"><b>${fmtN(itens.length)}</b> linha(s)</div>`;
  h+=`<div style="max-height:320px;overflow:auto;margin-top:6px"><table class="tb"><tbody>`;
  for(const it of itens.slice(0,60)){
    const txt=typeof it==='object'
      ? Object.entries(it).filter(([k,v])=>v!=null&&typeof v!=='object').slice(0,5)
          .map(([k,v])=>`<b>${esc(k)}</b> ${esc(String(v)).slice(0,60)}`).join(' · ')
      : esc(String(it));
    h+=`<tr><td style="font-size:12px">${txt}</td></tr>`;
  }
  h+=`</tbody></table></div>`;
  if(itens.length>60) h+=`<div class="note">60 de ${fmtN(itens.length)} linhas acima — a lista completa sai no relatório do órgão.</div>`;
  if(r.ressalva) h+=`<div class="note">${esc(r.ressalva)}</div>`;
  o.innerHTML=h;
}

// ═══ INSTRUMENTAÇÃO — agenda, pipelines, memória, UGs, SIAFE, radar, núcleo ═══
export async function renderInstrumentacao(){
  let h=cover('geral','Instrumentação — o estado da máquina, sem abrir terminal',
    'Timers e crons agendados, frescor de cada pipeline, aprendizados na memória, catálogo de UGs, estado do SIAFE, radar de vigilância e o comando do núcleo de perícia. Tudo isto era alcançável só por curl.','🔧');
  const [ag,pp,mm,ug,sf,rd,cb,rt,cc,tr,tk,mo]=await Promise.all([
    J('/api/agenda'),J('/api/pipelines'),J('/api/memoria'),J('/api/ugs?limite=15'),
    J('/api/siafe/status'),J('/api/radar/status'),J('/api/pericia/cobertura'),
    J('/api/ob/retiradas'),J('/api/captura/cobertura'),J('/api/siafe/truncamento'),
    J('/api/tac/ranking'),J('/api/motor/fotografia')]);

  // COBERTURA DA PERÍCIA DOCUMENTAL — o número que só existia dentro do SQLite. Sem ele, o painel
  // mostra achados e fila do fiscal sem dizer que a maior parte do acervo nunca foi periciada
  // documento a documento; processo sem juízo NÃO é processo regular, é processo não periciado.
  // COBERTURA DE CAPTURA — o número que limita todos os outros e não existia no painel. Mostrar
  // 51 processos EXTREMO sem dizer que eles saem de 1.941 lidos, num universo de 40 mil pagos,
  // deixa a impressão contrária à verdade. Sobre o que não se leu a casa não afirma NADA — não é
  // ausência de irregularidade, é ausência de leitura.
  h+=sec('Cobertura de CAPTURA — sobre quanto do dinheiro a casa consegue falar');
  if(cc && cc.indisponivel===false){
    const a=cc.acervo||{};
    // ACESSO RESTRITO — "nunca tocado" e "tentado e BARRADO" são cegueiras diferentes, e só a
    // segunda é limite institucional: o processo existe, o login existe, e a árvore não abre. A
    // restrição é da UNIDADE (Previdência 93%, Saúde ~50%, outras 1-3%), e é o tipo de limite que
    // se resolve por pedido formal de acesso, não por código.
    const rx=cc.restricao||{};
    const rest = rx.disponivel
      ? `<div style="margin-top:8px">Dos <b>${fmtN(rx.processos_tentados)}</b> processos com veredito
           de leitura registrado${rx.desde?' (desde '+esc(rx.desde)+')':''},
           <b>${fmtN(rx.restritos)}</b> (${rx.pct}%) o registro de controle classifica como
           de <b>nível de acesso restrito</b> — a árvore não abriu em duas leituras de processo que
           existe no cadastro, nem pelo caminho <i>cracked</i>. Não é ausência de irregularidade e
           não é falta de permissão da nossa conta (ostensivos das mesmas unidades abrem normal):
           é sigilo do processo, a confirmar por amostra com o leitor canônico.
           <span class="dim">Ordenado pela relevância do ponto cego (rateio proporcional do valor
           pago da unidade), não pelo percentual: 93% de uma unidade que pagou R$ 0,9 mi não é o
           maior ponto cego.</span></div>
         <div style="margin-top:6px">`+(rx.por_unidade||[]).map(u=>
           `<div class="kv"><span class="k">${esc(u.ug)} — ${esc(u.nome||'')}</span>`+
           `<b>${u.pct.toFixed(0)}% restrito</b> <span class="dim">(${u.restritos} de ${u.lidos} · `+
           `unidade pagou ${fmtRc(u.valor_pago)})</span></div>`
         ).join('')+`</div>`
      : '';
    h+=card(`<div class="grid g3">
        <div><div class="dim">Processos legíveis</div><div style="font-size:1.5rem;font-weight:700">${a.integro} <span class="dim" style="font-size:.9rem">de ${cc.processos_com_ob_paga} com OB paga (${cc.pct_utilizavel}%)</span></div></div>
        <div><div class="dim">Nunca tocados</div><div style="font-size:1.5rem;font-weight:700">${cc.nunca_tocados}</div></div>
        <div><div class="dim">Universo pago</div><div style="font-size:1.5rem;font-weight:700">${fmtRc(cc.valor_pago_universo)}</div></div>
      </div>
      <div style="margin-top:8px">Arquivados: <b>${a.integro}</b> íntegros · <b>${a.parcial}</b> parciais ·
        <b>${a.sem_teor}</b> sem teor · <b>${a.sem_docs}</b> sem índice`+
        // TETO DE COLETA: o painel dizia 1.941 íntegros enquanto o motor recusava 176 deles —
        // arquivos vindos do CACHE do sweep parados em EXATAMENTE 40 documentos. O cache do
        // SEI-170002/000732/2022 registra árvore de 783 contra 40 lidos: é corte, não processo
        // completo. Some no balde de "íntegro" seria repetir no painel o erro que o gate cometia.
        (a.teto_de_coleta?` · <b>${a.teto_de_coleta}</b> no <b>teto de coleta</b> (parados em 40 documentos)`:'')+
        ` — todos estes voltam à fila do sweep</div>
      ${rest}
      <div class="dim" style="margin-top:6px">${esc(cc.nota||'')}</div>`);
  }else{
    h+=card(`<div class="warn">Cobertura de captura INDISPONÍVEL${cc&&cc.motivo?': '+esc(cc.motivo):''} — indisponível não é zero.</div>`);
  }

  // TRUNCAMENTO DA FONTE CANÔNICA — o limite da NOSSA coleta, não da fonte. A tela de OB
  // Orçamentária devolve no máximo 1.000 registros por consulta; uma varredura feita só com
  // --por-ug numa UG grande para exatamente nesse número, calada. Enquanto isso não é medido, o
  // universo pago do cartão acima e toda soma por UG mentem para baixo sem avisar.
  // TAC POR UNIDADE — pagamento FORA de contrato regular. Um percentual sozinho não diz nada; a
  // régua é COMPARATIVA. Com 56 unidades medidas, a mediana é 0,3% e a Fundação Saúde está em 27%.
  // ESTADO DO MOTOR — quantos achados de cada código o acervo tem AGORA. Sem isto, medir o efeito
  // de uma correção de detector exigia SQL na mão, e duas dessas medições saíram erradas num dia.
  // É a mesma função que a pipeline `tools/pos_correcao` usa no antes/depois: painel e diff não
  // divergem.
  h+=sec('Estado do motor — achados por código no acervo');
  if(mo && mo.codigos){
    const cod=Object.entries(mo.codigos).filter(([k])=>k!=='—').sort((a,b)=>b[1]-a[1]).slice(0,14);
    const org=Object.entries(mo.origens||{}).sort((a,b)=>b[1]-a[1]).slice(0,8);
    h+=card(`<div class="grid g3">
        <div><div class="dim">Códigos distintos</div><div style="font-size:1.5rem;font-weight:700">${fmtN(cod.length)}</div></div>
        <div><div class="dim">Achados no acervo</div><div style="font-size:1.5rem;font-weight:700">${fmtN(Object.values(mo.codigos).reduce((s,x)=>s+x,0))}</div></div>
        <div><div class="dim">Processos avaliados</div><div style="font-size:1.5rem;font-weight:700">${fmtN(Object.values(mo.faixas||{}).reduce((s,x)=>s+x,0))}</div></div>
      </div>
      <div style="margin-top:8px">`+cod.map(([k,v])=>{
        // SEVERIDADE ao lado do código. Sem ela o painel dizia "F_EXECUCAO_SEM_EVIDENCIA 319" e o
        // leitor não via que 68 desses trazem, nos autos, documento que DECLARA a entrega — a
        // diferença entre abrir diligência por pagamento sem prova e abrir a peça para conferir o
        // teor. Mesma cegueira que o diff da pós-correção tinha antes de contar por código E grau.
        const sev=Object.entries(mo.graus||{}).filter(([g])=>g.startsWith(k+' · '))
          .map(([g,n])=>[g.split(' · ')[1],n]).sort((a,b)=>b[1]-a[1]);
        // o dado guarda `critica`/`media` sem acento (é chave, não texto); o painel é entregável.
        const ACENTO={critica:'crítica',media:'média',alta:'alta',baixa:'baixa',medio:'médio',baixo:'baixo'};
        const det=sev.length>1?` <span class="dim">(${sev.map(([s,n])=>fmtN(n)+' '+esc(ACENTO[s]||s)).join(' · ')})</span>`:'';
        return `<div class="kv"><span class="k">${esc(k)}${det}</span><b>${fmtN(v)}</b></div>`;
      }).join('')+`</div>
      <div class="dim" style="margin-top:6px">Por origem: `+org.map(([k,v])=>`${esc(k)} ${fmtN(v)}`).join(' · ')+`</div>`+
      // COBERTURA DAS RÉGUAS — o número mais silencioso do sistema até 2026-08-04: `indisponiveis`
      // só registrava motor QUEBRADO, então o dossiê dizia "indisponíveis: nenhum" num processo em
      // que 30 das 43 réguas não tinham dado. A mediana real é 5 réguas aferidas por processo.
      (mo.reguas&&mo.reguas.processos_medidos?`<div style="margin-top:10px" class="kv">
        <span class="k">Réguas que conseguem AFERIR o processo (mediana)</span><b>${mo.reguas.aferidas_mediana}</b></div>
      <div class="kv"><span class="k">Réguas SEM DADO para avaliar (mediana · máximo)</span>
        <b>${mo.reguas.sem_dado_mediana} · ${mo.reguas.sem_dado_max}</b></div>
      <div class="dim" style="margin-top:4px">Não é ausência de irregularidade: é ausência de dado.
        Cada dossiê lista quais réguas ficaram de fora e por quê.</div>`:''));
  }else{
    h+=card(`<div class="warn">Estado do motor INDISPONÍVEL${mo&&mo.erro?': '+esc(mo.erro):''} — indisponível não é zero.</div>`);
  }

  h+=sec('Pagamento fora de contrato regular (TAC/indenização) — por unidade');
  if(tk && tk.indisponivel===false && (tk.unidades||[]).length){
    const us=tk.unidades.slice(0,8), topo=us[0];
    h+=card(`<div class="grid g3">
        <div><div class="dim">Mediana entre ${fmtN(tk.unidades.length)} unidades</div><div style="font-size:1.5rem;font-weight:700">${tk.mediana_pct}%</div></div>
        <div><div class="dim">Mais alta: ${esc(topo.ug)}</div><div style="font-size:1.5rem;font-weight:700">${topo.pct}%</div></div>
        <div><div class="dim">Valor via TAC nessa unidade</div><div style="font-size:1.5rem;font-weight:700">${fmtRc(topo.total_tac)}</div></div>
      </div>
      <div style="margin-top:8px">`+us.map(u=>
        `<div class="kv"><span class="k">${esc(u.ug)} — ${esc(u.nome||'')}</span>`+
        `<b>${u.pct}%</b> <span class="dim">${fmtRc(u.total_tac)} de ${fmtRc(u.total)}</span></div>`
      ).join('')+`</div>
      <div class="dim" style="margin-top:6px">${esc(tk.nota||'')}</div>`, topo.pct>=25?'hl':'');
  }else{
    h+=card(`<div class="warn">Ranking de TAC INDISPONÍVEL${tk&&tk.motivo?': '+esc(tk.motivo):''} — indisponível não é zero.</div>`);
  }

  h+=sec('Cobertura da fonte canônica — o que o SIAFE ainda não tem');
  /* DOIS detectores, e o segundo é o que pega mais. Contagem redonda é a assinatura do TETO de
     consulta; coleta que MORRE em timeout para em número qualquer e fica com cara de concluída.
     Medido em 2026-08-09: 7 pares redondos contra 557 parciais e 258 nunca coletados — e o SIAFE
     inteiro tem 21,1% das OBs do espelho. Dizer "não aparenta truncamento" olhando só o teto era
     afirmar completude que não existe. */
  if(tr && tr.indisponivel===false && (tr.pares_parciais||tr.pares_nunca_coletados)){
    const pp=(tr.parciais||[]).filter(x=>x.estado==='parcial').slice(0,8).map(t=>
      `<div class="kv"><span class="k">UG ${esc(t.ug)} · exercício ${esc(t.exercicio)}</span>`+
      `<b>${t.pct_ausente}% da amostra ausente</b> <span class="dim">${fmtN(t.obs_siafe)} linhas no SIAFE · espelho tem ${fmtN(t.obs_espelho_tfe)}</span></div>`).join('');
    const nunca=(tr.parciais||[]).filter(x=>x.estado==='nunca_coletado').length;
    /* TERCEIRO ESTADO: coletado e INUTILIZÁVEL. A coleta de junho do SIAFE 1 gravou por posição
       (19 colunas lá, 23 no SIAFE 2): o valor foi parar em `nome_credor` e `valor` ficou 0,00.
       12.073 linhas da UG 010100, 2016-2023, escondendo R$ 3,41 bi — e o par passava por COBERTO,
       porque `numero_ob` é a 1ª coluna e foi gravado certo. É o pior dos três: não parece lacuna. */
    const desl=(tr.parciais||[]).filter(x=>x.estado==='deslocado');
    h+=card(`<div class="grid g3">
        <div><div class="dim">A fonte canônica tem, do que o espelho conhece</div>
          <div style="font-size:1.5rem;font-weight:700;color:${(tr.pct_do_espelho||0)<80?'var(--red)':'inherit'}">${tr.pct_do_espelho==null?'—':tr.pct_do_espelho+'%'}
          <span class="dim" style="font-size:.9rem">${fmtN(tr.obs_siafe_total||0)} de ${fmtN(tr.obs_espelho_total||0)} OBs</span></div></div>
        <div><div class="dim">Pares com coleta INTERROMPIDA</div><div style="font-size:1.5rem;font-weight:700;color:var(--red)">${fmtN((tr.parciais||[]).filter(x=>x.estado==='parcial').length)}</div></div>
        <div><div class="dim">Pares NUNCA coletados</div><div style="font-size:1.5rem;font-weight:700">${fmtN(nunca)}</div></div>
        <div><div class="dim">Pares com colunas DESLOCADAS</div><div style="font-size:1.5rem;font-weight:700;color:${desl.length?'var(--red)':'inherit'}">${fmtN(desl.length)}
          <span class="dim" style="font-size:.9rem">${fmtN(desl.reduce((s0,x)=>s0+(x.obs_deslocadas||0),0))} linhas</span></div></div>
        <div><div class="dim">Parados no teto de ${tr.teto_consulta}</div><div style="font-size:1.5rem;font-weight:700">${fmtN(tr.pares_truncados)} <span class="dim" style="font-size:.9rem">de ${fmtN(tr.pares_avaliados)}</span></div></div>
      </div>
      <div style="margin-top:8px">${pp}</div>
      ${desl.length?`<div class="warn" style="margin-top:8px"><b>Coletado, porém INUTILIZÁVEL</b> —
        ${fmtN(desl.length)} par(es) com os campos deslocados: o valor está gravado no campo do nome
        do credor e <b>a coluna de valor lê R$ 0,00</b>. Soma por esses exercícios devolve zero, e
        cruzamento por credor devolve número onde deveria vir nome. Não é lacuna de coleta — é
        coleta que passou por completa. ${desl.map(x=>esc(x.ug+'/'+x.exercicio)).join(' · ')}.
        A cura é RECOLETAR (o parser já foi corrigido); esses pares estão no topo da fila do dreno.</div>`:''}
      <div class="dim" style="margin-top:6px">A contagem redonda é a assinatura do <b>teto de consulta</b>; passada que morre em
        timeout grava o que deu tempo e para num número qualquer, <b>com cara de concluída</b> — e é
        por isso que o segundo detector, que compara NÚMEROS de OB com o espelho, acha muito mais.
        <b>Todo total tirado do SIAFE é PISO enquanto estes pares existirem.</b></div>`,'hl');
  }else if(tr && tr.indisponivel===false && tr.pares_truncados){
    const linhas=(tr.truncados||[]).slice(0,8).map(t=>
      `<div class="kv"><span class="k">UG ${esc(t.ug)} · exercício ${esc(t.exercicio)}</span>`+
      `<b>${fmtN(t.obs_faltando_ao_menos)} OBs a menos</b></div>`).join('');
    h+=card(`<div class="grid g3">
        <div><div class="dim">Pares (UG, ano) travados no teto</div><div style="font-size:1.5rem;font-weight:700">${tr.pares_truncados} <span class="dim" style="font-size:.9rem">de ${tr.pares_avaliados}</span></div></div>
        <div><div class="dim">OBs faltando ao menos</div><div style="font-size:1.5rem;font-weight:700">${fmtN(tr.obs_faltando_ao_menos)}</div></div>
        <div><div class="dim">Nesses pares: SIAFE × espelho</div><div style="font-size:1.5rem;font-weight:700">${fmtRc(tr.valor_siafe_nos_truncados)} <span class="dim" style="font-size:.9rem">× ${fmtRc(tr.valor_espelho_nos_truncados)}</span></div></div>
      </div>
      <div style="margin-top:8px">${linhas}</div>
      <div class="dim" style="margin-top:6px">${esc(tr.nota||'')}</div>`,'hl');
  }else if(tr && tr.indisponivel===false){
    h+=card(`<div>Nenhum par (UG, ano) parado no teto de ${tr.teto_consulta} — a coleta do SIAFE não aparenta truncamento.</div>`);
  }else{
    h+=card(`<div class="warn">Truncamento do SIAFE INDISPONÍVEL${tr&&tr.motivo?': '+esc(tr.motivo):''} — indisponível não é zero.</div>`);
  }

  h+=sec('Perícia documental — cobertura do acervo (24/7)');
  if(cb && cb.indisponivel===false){
    const pct=cb.pct==null?'—':cb.pct+'%';
    const cadeias=Object.entries(cb.por_cadeia||{}).map(([k,v])=>`${esc(k)}: ${v}`).join(' · ')||'—';
    const esc3=(cb.por_escala||{})['3']||0, esc2=(cb.por_escala||{})['2']||0,
          esc1=(cb.por_escala||{})['1']||0, escN=(cb.por_escala||{})['null']||0;
    h+=card(`<div class="grid g3">
        <div><div class="dim">Processos com juízo</div><div style="font-size:1.5rem;font-weight:700">${cb.processos_com_juizo} <span class="dim" style="font-size:.9rem">de ${cb.processos_periciaveis==null?cb.processos_avaliados:cb.processos_periciaveis} periciáveis (${pct})</span></div></div>
        <div><div class="dim">Documentos julgados</div><div style="font-size:1.5rem;font-weight:700">${cb.documentos_julgados}</div></div>
        <div><div class="dim">Pendentes</div><div style="font-size:1.5rem;font-weight:700">${cb.processos_pendentes}</div></div>
      </div>
      <div style="margin-top:8px">Escala do juízo: <b>${esc3}</b> viciado · <b>${esc2}</b> frágil · <b>${esc1}</b> regular · <span class="dim">${escN} não classificável</span></div>
      <div class="dim" style="margin-top:4px">Julgado por: ${cadeias} · rubrica v${esc(cb.rubrica)} · último juízo ${esc(cb.ultimo_juizo||'—')}</div>
      ${cb.processos_sem_captura?`<div class="dim" style="margin-top:4px">+ ${cb.processos_sem_captura} processos fora desta conta: não têm captura utilizável, e essa é outra fila (ver o cartão acima).</div>`:''}
      <div class="dim" style="margin-top:6px">${esc(cb._nota||'')}</div>`);
  }else{
    h+=card(`<div class="warn">Cobertura da perícia INDISPONÍVEL${cb&&cb.motivo?': '+esc(cb.motivo):''} — indisponível não é zero.</div>`);
  }

  // OBs DESPUBLICADAS — a base é reconstruída por exercício a cada coleta do TFE, e até
  // 2026-08-04 isso era silencioso: 140 OBs somando R$ 30.001.367,60 sumiram sem aviso e só
  // apareceram dois dias depois, porque um golden de números quebrou. Ordem bancária é a prova de
  // pagamento; sair do portal é fato sobre a prova, e fato sobre a prova mora no painel.
  h+=sec('Ordens bancárias despublicadas pela fonte');
  if(rt && rt.indisponivel===false){
    const anos=(rt.por_exercicio||[]).map(e=>`${esc(e.exercicio)}: ${e.n}`).join(' · ')||'—';
    h+=card(`<div class="grid g3">
        <div><div class="dim">OBs retiradas</div><div style="font-size:1.5rem;font-weight:700">${rt.n}</div></div>
        <div><div class="dim">Valor que saiu do portal</div><div style="font-size:1.5rem;font-weight:700">${fmtRc(rt.valor)}</div></div>
        <div><div class="dim">Favorecidos distintos</div><div style="font-size:1.5rem;font-weight:700">${rt.favorecidos_distintos}</div></div>
      </div>
      <div style="margin-top:8px">Por exercício: ${anos}</div>
      <div class="dim" style="margin-top:4px">Última retirada detectada: ${esc(rt.ultima_retirada||'—')}</div>
      <div class="dim" style="margin-top:6px">${esc(rt.ressalva||'')}</div>`);
    const mm2=(rt.maiores||[]).slice(0,8);
    if(mm2.length){
      h+=`<table class="tb"><thead><tr><th>OB</th><th>Órgão</th><th>Favorecido</th><th class="r">Valor</th></tr></thead><tbody>`;
      for(const o of mm2)
        h+=`<tr><td class="dim">${esc(o.numero_ob)}</td><td>${esc(o.ug_nome||'—')}</td>
            <td>${esc(o.favorecido_nome||'—')}</td><td class="r">${fmtR(o.valor)}</td></tr>`;
      h+=`</tbody></table>`;
    }
  }else{
    /* Vazio ≠ indisponível: tabela ainda não criada é "não medido", não "nada foi retirado". */
    h+=card(`<div class="dim">Retiradas de OB ${rt&&rt.motivo?esc(rt.motivo):'indisponíveis nesta execução'} — indisponível não é zero.</div>`);
  }

  h+=sec('Frescor das fontes (SLO por pipeline)');
  const ps=(pp&&(pp.pipelines||pp.itens))||[];
  if(ps.length){
    h+=`<table class="tb"><thead><tr><th>Pipeline</th><th>Estado</th><th class="r">Idade</th></tr></thead><tbody>`;
    for(const p of ps){
      // /api/pipelines devolve `status` e `idade_h`; /api/sistema/atividade devolve `estado` e
      // `idade_dias`. Lendo só um dos contratos, a aba Instrumentação pintava TODA linha de ruim.
      const st=String(p.estado||p.status||'').toLowerCase();
      const ruim=st==='stale'||st==='ausente'||(st&&!/^(ok|pausado|sob_demanda)/.test(st));
      const idade=p.idade_dias!=null?p.idade_dias+' d':(p.idade_h!=null?p.idade_h+' h':'—');
      h+=`<tr><td>${esc(p.nome||p.id)}</td><td class="${ruim?'bad':'ok'}">${esc(p.estado||p.status||'—')}</td>
          <td class="r dim">${idade}</td></tr>`;
    }
    h+=`</tbody></table>`;
  /* Vazio ≠ indisponível (regra da casa, aplicada à própria tela): rota que respondeu com lista
     vazia é informação — dizer "indisponível" nos dois casos inventa uma falha que não houve. */
  }else h+=card(`<div class="dim">${pp&&pp.ok===false?'Pipelines indisponíveis nesta execução'+(pp.erro?': '+esc(pp.erro):'')+'.':'Nenhum pipeline registrado — a rota respondeu, a lista está vazia.'}</div>`);

  h+=sec('Agenda (timers e crons)');
  const js=(ag&&(ag.jobs||ag.itens||ag.agenda))||[];
  if(js.length){
    h+=`<table class="tb"><thead><tr><th>Job</th><th>Quando</th><th>Último</th></tr></thead><tbody>`;
    for(const j of js.slice(0,40))
      h+=`<tr><td>${esc(j.nome||j.id||'—')}</td><td class="dim">${esc(j.quando||j.cron||j.schedule||'—')}</td>
          <td class="dim">${esc(j.ultimo||j.last||'—')}</td></tr>`;
    h+=`</tbody></table>`;
  }else h+=card(`<div class="dim">${ag&&ag.ok===false?'Agenda indisponível nesta execução'+(ag.erro?': '+esc(ag.erro):'')+'.':'Nenhum job agendado — a rota respondeu, a agenda está vazia.'}</div>`);

  h+=sec('SIAFE e radar');
  h+=`<div class="grid g2">
    ${kpi(esc((sf&&(sf.estado||sf.status))||'—'),'SIAFE',null,'💵',
      {sobre:'Estado da coleta no SIAFE — a fonte canônica de pagamento. Coleta parada significa números <b>congelados na última data</b>, não ausência de pagamento novo: é a diferença entre o mundo e o que a casa viu do mundo.'})}
    ${kpi(fmtN(sf&&(sf.n_obs||sf.obs)),'OBs coletadas',null,null,
      {sobre:'Ordens bancárias ingeridas — pagamento EFETIVO. Empenho é reserva orçamentária e pode ser cancelado; liquidação é o reconhecimento da dívida. Só a OB significa que o dinheiro saiu, e é por isso que só ela conta como "pago" nesta casa.'})}
    ${kpi(esc((rd&&(rd.estado||rd.status))||'—'),'Radar',null,'🎯',
      {sobre:'Estado do varredor que reavalia os fornecedores. Parado, as faixas de risco continuam mostrando a última avaliação — número velho com cara de atual é a forma mais silenciosa de errar.'})}
    ${kpi(fmtN(mm&&(mm.n||mm.total||mm.aprendizados)),'Itens na memória','var(--accent)','🧠',
      {sobre:'Aprendizados registrados no acervo de metacognição — o que a casa já descobriu sobre os próprios erros. É o que impede um defeito corrigido de voltar por esquecimento; cada família de falha do catálogo nasceu de um caso concreto.'})}</div>`;
  h+=card(`<div class="btns" style="flex-wrap:wrap">
      <button type="button" class="btn ghost" onclick="instAcionar('/api/siafe/status','GET')">Status SIAFE</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/siafe/atualizar','POST')">Atualizar SIAFE</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/siafe/sweep','POST')">Sweep SIAFE</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/radar/status','GET')">Status radar</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/radar/ciclo','POST')">Ciclo do radar</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/radar/vigiar','POST')">Colocar sob vigilância</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/compliance/stats','GET')">Estatísticas</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/compliance/alerts','GET')">Alertas</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/compliance/relatorio_30d','GET')">Relatório 30 dias</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/nucleo/comando','POST')">Núcleo de perícia</button>
    </div><div id="inst-out"></div>`);

  h+=sec('Catálogo de UGs');
  const us=(ug&&(ug.ugs||ug.itens))||[];
  if(us.length){
    h+=card(`<div class="search"><span class="mag"></span>
        <input id="inst-ug" placeholder="filtrar UG por nome ou código…" onkeydown="if(event.key==='Enter')instUgs()"></div>
      <div id="inst-ugs" style="margin-top:10px">`+us.map(u=>
        `<div class="kv"><span class="k">${esc(u.codigo||u.ug)} — ${esc(u.nome||'')}</span><b>${fmtRc(u.total||u.total_pago)}</b></div>`).join('')+`</div>
      <div class="dim" style="margin-top:6px">${fmtN(ug.n_total||us.length)} UGs no catálogo.</div>`);
  }else h+=card(`<div class="dim">${ug&&ug.ok===false?'Catálogo de UGs indisponível'+(ug.erro?': '+esc(ug.erro):'')+'.':'Catálogo de UGs vazio nesta base — a rota respondeu.'}</div>`);

  h+=sec('Fila do fiscal (flags e restritos)');
  h+=card(`<div class="btns">
      <button type="button" class="btn ghost" onclick="instAcionar('/api/flags','GET')">Flags de triagem</button>
      <button type="button" class="btn ghost" onclick="instAcionar('/api/restritos','GET')">Processos restritos</button>
    </div><div class="dim" style="margin-top:6px">A página <code>/controle</code> mostra o mesmo em tela dedicada.</div>`);
  return h;
}

export async function instUgs(){
  const f=($('inst-ug')?.value||'').trim();
  const d=await J('/api/ugs?limite=40&filtro='+encodeURIComponent(f));
  const us=(d&&(d.ugs||d.itens))||[];
  $('inst-ugs').innerHTML=us.length
    ? us.map(u=>`<div class="kv"><span class="k">${esc(u.codigo||u.ug)} — ${esc(u.nome||'')}</span><b>${fmtRc(u.total||u.total_pago)}</b></div>`).join('')
    : '<div class="dim">Nenhuma UG com esse filtro.</div>';
}

export async function instAcionar(rota,metodo){
  const o=$('inst-out'); o.innerHTML='<div class="dim" style="margin-top:8px">acionando…</div>';
  try{
    const d=await J(rota, metodo==='POST'?{method:'POST'}:undefined);
    o.innerHTML=sec(esc(rota))+card(
      `<pre style="white-space:pre-wrap;font-size:12px;margin:0">${esc(JSON.stringify(d,null,1)).slice(0,4000)}</pre>`);
  }catch(e){ o.innerHTML=card(`<div class="warn">${erroHumano(String(e))}</div>`); }
}

// ═══ MISSÕES DO HERMES — a fila paralela que só existia no backend ═══
export async function renderMissoes(){
  let h=cover('geral','Missões — a fila do auditor autônomo',
    'O Hermes aceita <b>várias missões em paralelo</b> desde sempre no backend; a tela só sabia operar uma. Aqui a fila fica visível: o que está rodando, o que já terminou, e o resultado de cada uma.','🛰️');
  h+=card(`<div class="search"><span class="mag"></span>
      <input id="ms-txt" placeholder="descreva a missão (ex.: audite os pagamentos do ITERJ em 2025)…"
             onkeydown="if(event.key==='Enter')missaoCriar()"></div>
    <div class="btns" style="margin-top:10px">
      <button type="button" class="btn" onclick="missaoCriar()">Enfileirar missão</button>
      <button type="button" class="btn ghost" onclick="missaoListar()">↻ Atualizar fila</button>
    </div>`);
  h+=`<div id="ms-out"></div>`;
  setTimeout(missaoListar,50);
  return h;
}

export async function missaoListar(){
  const o=$('ms-out'); if(!o)return;
  const d=await J('/api/hermes/missoes');
  const ms=(d&&(d.missoes||d.itens))||[];
  if(!ms.length){o.innerHTML=card('<div class="dim">Nenhuma missão na fila.</div>');return;}
  o.innerHTML=sec('Fila',ms.length)+`<div class="grid">`+ms.map(m=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
       <div style="min-width:0"><div style="font-weight:700">${esc(m.titulo||m.objetivo||m.id)}</div>
         <div class="dim" style="margin-top:3px">${esc(m.estado||m.status||'—')}${m.criada_em?' · '+esc(m.criada_em):''}</div></div>
       <button type="button" class="btn ghost" onclick="missaoVer('${esc(m.id)}')">Ver</button></div>
     <div id="ms-${esc(m.id)}"></div>`)).join('')+`</div>`;
}

export async function missaoCriar(){
  const t=($('ms-txt')?.value||'').trim(); if(!t)return;
  await J('/api/hermes/missoes',{method:'POST',headers:{'Content-Type':'application/json'},
                                body:JSON.stringify({objetivo:t,titulo:t})});
  jfnToast('Missão enfileirada.','green'); $('ms-txt').value=''; setTimeout(missaoListar,400);
}

export async function missaoVer(id){
  const o=$('ms-'+id); if(!o)return;
  o.innerHTML='<div class="dim" style="margin-top:8px">lendo…</div>';
  const d=await J('/api/hermes/missoes/'+encodeURIComponent(id));
  o.innerHTML=`<pre style="white-space:pre-wrap;font-size:12px;margin-top:8px">${esc(JSON.stringify(d,null,1)).slice(0,3000)}</pre>`;
}

/* ─────────────────────────────────────────────────────────────────────── */

export async function frescorHtml(){
  const d=await J('/api/fontes/frescor');
  if(!d.ok)return '';
  const rows=(d.fontes||[]).map(f=>{
    const idade=f.idade_dias==null?'sem dado':f.idade_dias===0?'hoje':f.idade_dias+'d atrás';
    return `<div class="f"><span class="led ${f.estado}"></span><span class="nome">${esc(f.fonte)}</span><span class="idade">${idade}</span></div>`;}).join('');
  return sec('Fontes & frescor')+card(`<div class="fresh">${rows}</div><div class="dim" style="margin-top:8px">≤3 dias · 🟡 ≤10 · 🔴 parada — vermelho significa coletor quebrado: investigar, não ignorar.</div>`);
}

// ═══ ESTADO ═══
export async function renderPanoramaEstado(){
  /* Conta já feita em campo (2026-07-31) — NÃO refazer: /status 0,002 s · /api/compliance/painel
     1,706 s (o pior) · conluio 0,626 s · sancionadas 0,016 s. Pior caso 1,7 s: quebrar em etapas
     custaria mais cintilação (blocos aparecendo em tempos diferentes) do que ganha. Só reabrir
     esta decisão com número novo — o gatilho é o painel passar de ~3 s. */
  const [st,p,cj,sc]=await Promise.all([J('/status'),J('/api/compliance/painel'),J('/api/pncp/conluio?esfera=estado'),J('/api/intel/sancionadas?limite=1')]);
  const a=p.alertas||{},o=p.obs||{};const coletaErro=/erro/i.test(p.ultima_coleta||'');
  const nc=(cj.captura||[]).length+(cj.rodizio_vencedores||[]).length;
  let h=cover('estado','Estado do Rio de Janeiro','Ordens Bancárias do SIAFE, concentração de fornecedores, sancionadas, perícias e conluio — somente órgãos ESTADUAIS (esfera oficial do PNCP; federais e municípios ficam em Transversal).','🏛️');
  if(coletaErro)h+=`<div class="warn">Última coleta SIAFE falhou — <b>${esc(p.ultima_coleta)}</b>.</div>`;
  h+=`<div class="grid g2">
    ${kpi(fmtN(o.total),'Ordens Bancárias',null,'💳','e_siafe')}${kpi(fmtRc(o.valor_total),'Valor fiscalizado',null,'💰','e_siafe')}
    ${kpi(fmtN(a.total??0),'Alertas ativos',(a.alta?'var(--rose)':'#fff'),'🚨','e_alertas')}${kpi(nc,'Conluio (estado)','var(--purple)','🕸️','e_conluio')}
    ${kpi(fmtN(sc.n_a_epoca??'—'),'Sancionadas à época','var(--rose)','🚫','e_sanc')}${kpi(fmtN(a.alta??0),'🔴 Alta','var(--rose)',null,'e_alertas')}
    ${kpi(st.logged_in?'🟢 ok':'🔴 off','SIAFE · '+esc(st.exercicio||'—'),null,null,'e_siafe')}${kpi(fmtN(o.hoje??0),'OBs hoje',null,null,'e_siafe')}</div>`;
  h+=`<div style="height:16px"></div>`+sec('Ir para')+`<div class="grid two">
    ${card(`<div style="font-weight:700">Sancionadas contratadas</div><div class="muted" style="font-size:13px">CEIS/CNEP × pagamentos, com teste "à época"</div><div class="btns"><button class="btn accent" onclick="ir('e_sanc')">Abrir</button></div>`)}
    ${card(`<div style="font-weight:700">Perícias de fornecedor</div><div class="muted" style="font-size:13px">8.648 periciados, pesquisável</div><div class="btns"><button class="btn ghost" onclick="ir('e_pericias')">Abrir</button></div>`)}</div>`;
  h+=`<div style="height:16px"></div>`+await frescorHtml();
  h+=`<div style="height:14px"></div>`+card(`<div class="kv"><span class="k">Última atualização</span><b>${esc(p.atualizado||'—')}</b></div><div class="kv"><span class="k">Última coleta SIAFE</span><b style="${coletaErro?'color:#f0c078':''}">${esc(p.ultima_coleta||'—')}</b></div>`);
  return h;
}

// ═══ SANCIONADAS (Estado e Transversal) ═══
export async function renderSancionadas(esf){
  const d=await J('/api/intel/sancionadas?limite=1000');   // teto da rota = 1000 > n(770): cobre a base
  if(!d.ok)return sec('Sancionadas')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  let emp=d.empresas||[];const carregadas=emp.length;   // ANTES do corte de esfera — é o que o filtro varre
  if(esf==='estado')emp=emp.filter(e=>e.estado.obs>0);
  const aepoca=emp.filter(e=>e.estado.obs_durante>0||e.pncp.vitorias_durante>0);
  let h=cover(esf==='estado'?'estado':'geral','Sancionadas que contratam com o poder público',
    'Empresas punidas no CEIS/CNEP (impedimento, suspensão, inidoneidade) que receberam pagamento (OB SIAFE) ou venceram licitação (PNCP). <b>À ÉPOCA</b> = o ato ocorreu DENTRO da vigência da punição — vedação legal direta (Lei 14.133, art. 156).','🚫')+acoesAba('sancionadas');
  /* As duas primeiras métricas contam `emp` e `aepoca`, que são os MESMOS arrays desta tela — o
     drill mostra exatamente o que o número conta. As duas últimas somam valor e vitórias: soma não
     é contagem de linhas, e por isso não ganham gaveta. */
  const _linSanc=e=>card(`<div style="display:flex;justify-content:space-between;gap:10px"><div style="min-width:0">${clk(e.cnpj,e.razao_social||e.cnpj)}<div class="dim">${esc(e.cnpj)}</div></div><div class="right"><div class="dim">OB ${fmtN(e.estado.obs)} · à época ${fmtN(e.estado.obs_durante)}</div><div class="dim">PNCP ${fmtN(e.pncp.vitorias)} · à época ${fmtN(e.pncp.vitorias_durante)}</div></div></div>`);
  registrarDrill('sancComContrato',{titulo:'Sancionadas com contrato ou pagamento',itens:emp,render:_linSanc,
    nota:'Sanção vigente não é o mesmo que ato à época — a coluna "à época" é a que sustenta a vedação do art. 156.'});
  registrarDrill('sancAEpoca',{titulo:'Ato praticado À ÉPOCA da sanção',itens:aepoca,render:_linSanc,
    nota:'O ato ocorreu DENTRO da vigência da punição (Lei 14.133, art. 156).'});
  h+=`<div class="grid g2">${kpi(fmtN(emp.length),'Empresas sancionadas c/ contrato',null,'🚫',{drill:'sancComContrato'})}${kpi(fmtN(aepoca.length),'Com ato À ÉPOCA','var(--rose)','⚠️',{drill:'sancAEpoca'})}
      ${kpi(fmtRc(aepoca.reduce((s,e)=>s+e.estado.valor_durante,0)),'Pago durante sanção (OB)','var(--rose)','💸',
        {sobre:'Ordens bancárias emitidas <b>enquanto</b> a sanção estava vigente — não o histórico da empresa. A fonte é a OB do SIAFE, que é pagamento efetivo: empenho é reserva e pode ser cancelado, liquidação é reconhecimento da dívida. Só a OB significa que o dinheiro saiu.'})}${kpi(fmtN(aepoca.reduce((s,e)=>s+e.pncp.vitorias_durante,0)),'Vitórias durante sanção','var(--amber)','🏆',
        {sobre:'Certames vencidos <b>enquanto</b> a sanção vigorava, segundo o PNCP. Vencer não é receber: o valor efetivamente pago está no KPI ao lado, e vem da OB do SIAFE.'})}</div>`;
  h+=buscaPag('san','filtrar por nome ou CNPJ…');
  h+=`<div class="dim" style="margin:6px 2px 0">mostrando ${fmtN(Math.min(80,emp.length))} de ${fmtN(emp.length)}${(d.n&&d.n>carregadas)?` carregadas — a base tem ${fmtN(d.n)}; a rota entrega no máximo 1000, então <b>o filtro NÃO cobre a base inteira</b>: se um CNPJ não aparecer aqui, use a busca por CNPJ do painel antes de concluir qualquer coisa`:' — o filtro busca em todas'}</div>`;
  h+=listaPaginada('san',emp,e=>{
    const grave=e.estado.obs_durante>0||e.pncp.vitorias_durante>0;
    const s0=(e.sancoes||[])[0]||{};
    const ex=(e.estado.exemplos_durante||[])[0]||(e.pncp.exemplos_durante||[])[0];
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0">${clk(e.cnpj,e.nome||e.cnpj)}<div class="dim">${esc(e.cnpj)}</div>
      <div class="muted" style="font-size:12.5px;margin-top:4px">${esc(s0.cadastro||'')} · ${esc((s0.categoria||'').slice(0,60))}<br>vigência ${esc(s0.data_inicio||'?')} → ${esc(s0.data_fim||'?')} · ${esc((s0.orgao||'').slice(0,50))}</div></div>
      <div class="right">${grave?'<span class="sev alta">à época</span>':'<span class="sev baixa">fora da vigência</span>'}
      <div style="margin-top:6px" class="num"><b>${fmtRc(e.estado.valor_durante+e.pncp.valor_durante||e.estado.valor+e.pncp.valor)}</b></div>
      <div class="dim">${grave?'durante a sanção':'total recebido'}</div></div></div>
      ${grave&&ex?leitura(`Exemplo: ${ex.ob?('OB <b>'+esc(ex.ob)+'</b> paga em '):'certame homologado em '}<b>${esc(ex.data)}</b> (${fmtRc(ex.valor)}) — a sanção ${esc(ex.sancao)} vigia de ${esc(ex.vigencia)}. Pagamento/contratação DENTRO do período vedado.`):''}`,grave?'hl':'');},80,e=>e.nome);
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}

// ═══ FRACIONAMENTO (Estado) ═══
export async function renderFracionamento(){
  const d=await J('/api/intel/fracionamento?limite=120');
  if(!d.ok)return sec('Fracionamento')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const g=d.grupos||[];
  let h=cover('estado','Fracionamento de despesa — fatiar para não licitar',
    'Mesmo favorecido, mesma unidade gestora e mesmo mês, com várias Ordens Bancárias <b>coladas no teto de dispensa</b> de licitação. É o padrão de dividir a compra para caber embaixo do limite e não licitar (Lei 14.133, art. 75 §1º). Quanto maior a <b>concentração</b> (% de OBs coladas no teto), mais deliberado o indício.','✂️')+acoesAba('fracionamento');
  const alta=g.filter(x=>x.concentracao>=0.5).length;
  registrarDrill('fracConc50',{titulo:'Grupos com concentração ≥ 50% num único favorecido',itens:g.filter(x=>x.concentracao>=0.5),nota:'Fracionamento é indício de divisão da compra para escapar da licitação — o objeto decide.'});
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Grupos sinalizados','var(--amber)','✂️',drillSeCompleto('fracGrupos',d.n,g,{titulo:'Grupos com indício de fracionamento',nota:'Mesmo favorecido, mesma UG e mesmo mês, com OBs coladas no teto de dispensa. O objeto decide se houve divisão indevida.'})
        ||{sobre:'Grupos com indício de fracionamento — mesmo favorecido, mesma UG, mesmo mês, com pagamentos colados no teto de dispensa. A tela recebe uma página e por isso a gaveta está desligada aqui. Este eixo já esteve <b>26× inflado</b> nesta casa (59.209 caindo para 2.225): o número só vale com a régua de agrupamento à vista.'})}${kpi(fmtN(alta),'Concentração ≥50%','var(--rose)','🎯',{drill:'fracConc50'})}
      ${kpi(fmtRc(g.reduce((s,x)=>s+x.soma,0)),'Soma dos grupos exibidos',null,'💰',
        {sobre:'Soma dos grupos EM TELA, não do acervo — o rótulo diz isso de propósito. Fracionamento já esteve 26× inflado nesta casa (59.209 caindo para 2.225) por contar o que não devia; somar só o exibido é o que impede o número de crescer sem lastro.'})}${kpi(g.length?Math.round(Math.max(...g.map(x=>x.concentracao))*100)+'%':'—','Pior concentração','var(--rose)',null,
        {sobre:'O grupo com maior parcela num único favorecido. Concentração alta pode ser mercado de um fornecedor só; o que ela indica é onde perguntar por pesquisa de preço, não onde concluir.'})}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por favorecido, UG ou mês…" oninput="filtrar(this,'#frac-list .card')"></div>`;
  h+=`<div id="frac-list" class="grid">`+g.map(x=>{
    const pct=Math.round(x.concentracao*100);
    const cor=pct>=60?'var(--rose)':pct>=40?'var(--amber)':'var(--tx2)';
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0">${clk(x.credor,x.nome||x.cnpj_fmt)}<div class="dim">${esc(x.cnpj_fmt)} · UG ${esc(String(x.ug_emitente))} · ${esc(x.mes)}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:19px;color:${cor}">${pct}%</div><div class="dim">colado no teto</div></div></div>
      <div class="kv" style="margin-top:8px"><span class="k">${x.n_colado} de ${x.n} OBs em 85–100% do teto (R$ ${Number(x.teto).toLocaleString('pt-BR',{maximumFractionDigits:0})})</span><b>${fmtRc(x.soma)}</b></div>
      ${leitura(`${x.n_colado} das ${x.n} OBs deste favorecido para a UG ${esc(String(x.ug_emitente))} em ${esc(x.mes)} ficaram logo abaixo do teto de dispensa. Somadas dão ${fmtRc(x.soma)} — acima do limite, o que exigiria licitação. Cruzar com os empenhos/processos do mês.`)}`,
      pct>=50?'hl':'');}).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}

// ═══ CERTAMES — conjunto por órgão (Estado) ═══
export async function renderCertames(){
  const d=await J('/api/conjunto/portfolio?min_certames=3');
  if(!d.ok)return sec('Certames')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const o=d.orgaos||[];
  let h=cover('estado','Certames — o padrão de cada órgão licitante',
    'Todos os certames indexados de cada órgão, avaliados <b>como conjunto</b>: mediana do Índice de Direcionamento (0-100, 7 famílias — inclui o que <b>ocorreu na sessão</b>: eliminações em massa ou por motivo trivial sem saneamento, art. 64 §1º), <b>reincidência</b> da mesma cláusula restritiva (≥3 certames = auditoria temática) e <b>desvio frente aos pares</b>. Um certame ruim pode ser acaso; um padrão de órgão nunca é.','🧮')+acoesAba('certames');
  const piores=o.filter(x=>(x.desvio_vs_pares||0)>10).length, aud=o.filter(x=>x.auditoria_tematica&&x.auditoria_tematica.length).length;
  registrarDrill('orgAcimaPares',{titulo:'Órgãos acima dos pares em mais de 10 pontos',itens:o.filter(x=>(x.desvio_vs_pares||0)>10),nota:'A régua é COMPARATIVA: o desvio mede este órgão contra os semelhantes, não contra zero.'});
  registrarDrill('orgAuditoriaTematica',{titulo:'Órgãos com gatilho de auditoria temática',itens:o.filter(x=>x.auditoria_tematica&&x.auditoria_tematica.length)});
  h+=`<div class="grid g2">${kpi(fmtN(d.n_orgaos),'Órgãos avaliados (≥3 certames)',null,'🏢',drillSeCompleto('orgaosAvaliados',d.n_orgaos,o,{titulo:'Órgãos avaliados (≥3 certames indexados)',nota:'Órgão com menos de 3 certames fica fora: régua comparativa exige base para comparar.'})
        ||{sobre:'Órgãos com pelo menos três certames — abaixo disso não há série para falar de padrão, e qualquer concentração seria ruído de amostra pequena. A gaveta está desligada porque a tela recebe uma página do total.'})}${kpi(d.mediana_pares!=null?d.mediana_pares.toFixed(0):'—','Mediana dos pares',null,'📏',{sobre:'Mediana do Índice de Direcionamento entre órgãos COMPARÁVEIS (≥3 certames indexados). A régua desta casa é comparativa de propósito: 40 pontos não significa nada sozinho — significa alguma coisa contra os 22 dos semelhantes. Órgão sem par suficiente fica sem desvio, e isso é dito, não preenchido com zero.'})}
      ${kpi(fmtN(piores),'Acima dos pares (+10)','var(--amber)','📈',{drill:'orgAcimaPares'})}${kpi(fmtN(aud),'Com gatilho de auditoria temática','var(--rose)','🎯',{drill:'orgAuditoriaTematica'})}</div>`;
  h+=`<div class="grid" style="margin-top:14px">`+o.map(x=>{
    const md=x.score_mediana!=null?x.score_mediana:0, dv=x.desvio_vs_pares;
    const cor=md>=50?'var(--rose)':md>=25?'var(--amber)':'var(--tx2)';
    const nome=x.orgao_nome||x.orgao_cnpj;
    const audit=(x.auditoria_tematica||[]).map(a=>`<span class="tag rose">${esc(a.subtipo)} × ${a.certames} certames</span>`).join(' ');
    const ancoras=(x.casos_ancora||[]).slice(0,3).map(c=>`<span class="tag ${c.faixa==='ALTO'||c.faixa==='EXTREMO'?'rose':'accent'}" style="cursor:pointer" title="${esc(c.certame)} — clique p/ ver as 7 famílias" onclick="abrirCertame('${jsq(c.certame)}')">${c.score.toFixed(0)}·${esc(c.faixa)}</span>`).join(' ');
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><b>${esc(nome)}</b><div class="dim">${esc(x.orgao_cnpj)} · ${fmtN(x.n_avaliados??x.n_certames_indexados)} avaliados de ${fmtN(x.n_certames_indexados)} indexados</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:${cor}">${md.toFixed(0)}</div><div class="dim">mediana · p90 ${x.score_p90!=null?x.score_p90.toFixed(0):'—'}</div></div></div>
      <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">${dv!=null?`<span class="tag ${dv>10?'rose':dv>0?'amber':'teal'}">${dv>0?'+':''}${dv.toFixed(0)} vs pares</span>`:''}
        ${x.violacoes_saneamento?`<span class="tag rose">${x.violacoes_saneamento} eliminação(ões) trivial(is) sem saneamento</span>`:''}
        ${x.hhi_concentrado?`<span class="tag amber">vitórias concentradas (HHI ${x.hhi_vitorias})</span>`:''}${audit}</div>
      ${ancoras?`<div style="margin-top:6px" class="dim">casos-âncora: ${ancoras}</div>`:''}
      ${leitura(`A mediana <b>${md.toFixed(0)}/100</b> sobre os <b>${fmtN(x.n_avaliados??x.n_certames_indexados)}</b> certames com análise real (dos ${fmtN(x.n_certames_indexados)} indexados — o resto ainda sem família analisável, INDISPONÍVEL ≠ 0) ${dv!=null&&dv>10?`está <b>${dv.toFixed(0)} pontos acima</b> dos pares — o padrão do órgão destoa`:dv!=null&&dv>0?'fica levemente acima dos pares':'acompanha os pares'}.${(x.auditoria_tematica||[]).length?` A <b>mesma cláusula restritiva reincide</b> em ${x.auditoria_tematica[0].certames} certames — caso de <b>auditoria temática</b>, não de representação avulsa.`:''} Quanto menos certames indexados, menor a confiança — toque nos casos-âncora para ver o índice de cada um.`)}`,
      (dv!=null&&dv>10)||(x.auditoria_tematica||[]).length?'hl':'');}).join('')+`</div>`;
  // ── granularidade por UNIDADE/secretaria (o CNPJ guarda-chuva esconde a secretaria real) ──
  const u=await J('/api/conjunto/unidades?min_certames=3');
  if(u.ok&&(u.unidades||[]).length){
    h+=`<h3 style="margin:22px 0 4px">Por unidade / secretaria</h3>`;
    h+=`<div class="dim" style="margin-bottom:10px">O CNPJ guarda-chuva do Estado/Município esconde a secretaria real. Aqui, ${fmtN(u.n_unidades)} unidades com ≥3 certames (mediana dos pares ${u.mediana_pares!=null?u.mediana_pares.toFixed(0):'—'}). Cobertura cresce com o PNCP/enxame.</div>`;
    h+=`<div class="grid">`+u.unidades.map(x=>{
      const md=x.score_mediana!=null?x.score_mediana:0, dv=x.desvio_vs_pares;
      const cor=md>=50?'var(--rose)':md>=25?'var(--amber)':'var(--tx2)';
      const anc=(x.casos_ancora||[]).slice(0,3).map(c=>`<span class="tag ${c.faixa==='ALTO'||c.faixa==='EXTREMO'?'rose':'accent'}" style="cursor:pointer" title="${esc(c.certame)} — clique p/ ver as 7 famílias" onclick="abrirCertame('${jsq(c.certame)}')">${c.score.toFixed(0)}·${esc(c.faixa)}</span>`).join(' ');
      return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
        <div style="min-width:0"><b>${esc(x.unidade)}</b><div class="dim">${fmtN(x.n_avaliados??x.n_certames)} avaliados de ${fmtN(x.n_certames)} · ${x.n_alto_extremo} ALTO/EXTREMO</div></div>
        <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:${cor}">${md.toFixed(0)}</div><div class="dim">mediana · p90 ${x.score_p90!=null?x.score_p90.toFixed(0):'—'}</div></div></div>
        ${dv!=null?`<div style="margin-top:8px"><span class="tag ${dv>10?'rose':dv>0?'amber':'teal'}">${dv>0?'+':''}${dv.toFixed(0)} vs pares</span>${x.n_alto_extremo>0?` <span class="tag rose">${x.n_alto_extremo} certame(s) de alto risco</span>`:''}</div>`:''}
        ${anc?`<div style="margin-top:6px" class="dim">casos-âncora: ${anc}</div>`:''}
        ${leitura(`<b>${esc(x.unidade)}</b>: mediana ${md.toFixed(0)}/100 em ${fmtN(x.n_certames)} certames${x.n_alto_extremo>0?`, com <b>${x.n_alto_extremo}</b> de alto risco`:''}. ${dv!=null&&dv>10?'Padrão acima dos pares — prioridade de auditoria.':'Acompanha os pares.'} Toque nos casos-âncora para o índice de cada certame.`)}`,
        (dv!=null&&dv>10)||x.n_alto_extremo>0?'hl':'');}).join('')+`</div>`;
  }
  h+=`<div class="note">Determinístico e auditável (indício ≠ acusação; órgão/unidade sem certame indexado não aparece — INDISPONÍVEL ≠ 0). Fontes: certame_indice + clausula_veredito + certame_julgamento + PNCP.</div>`;
  return h;
}

// ═══ ADITIVOS (Estado) ═══
// ═══ CONCENTRAÇÃO × PREFEITURA (HHI por ramo de objeto — análogo municipal do Cartel) ═══
export async function renderCartelMun(){
  const d=await J('/api/intel/concentracao_municipio?limite=60');
  if(!d.ok)return sec('Concentração — Prefeitura')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.orgaos||[];
  let h=cover('prefeitura','Concentração de fornecedor por mercado municipal',
    'Para cada <b>ramo de objeto</b> (limpeza, TI, veículos…), quem domina os contratos do Município do Rio: <b>top-share</b> (≥60% forte · ≥40% médio — régua R8) e <b>HHI</b> (>2.500 = mercado altamente concentrado, referência CADE). <b>Base = valor CONTRATADO</b> do PNCP — a PCRJ não publica pagamento por credor 2024+; concentração de contrato é screen de captura, não medida de execução.','🔗');
  // total do servidor: só ganha gaveta se a página trouxer o universo
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Mercados analisados',null,'🧺',drillSeCompleto('mercadosAnalisados',d.n,a,{titulo:'Mercados analisados',nota:''})
        ||{sobre:'Mercados (agrupamentos de item comparável) submetidos ao teste de concentração. É o DENOMINADOR: mercado fora desta conta não foi considerado competitivo — não foi examinado. A gaveta está desligada porque a tela recebe uma página do total.'})}${kpi(fmtN(d.n_criticos||0),'Concentrados (share ≥40%)','var(--rose)','🚨',{sobre:'Quantos fornecedores concentram 40% ou mais do que o órgão pagou. O corte de 40% é a régua desta casa, não da lei: serve para separar o que merece leitura do que é a distribuição normal de um mercado pequeno.'})}
      ${kpi(a.length?fmtN(a[0].hhi):'—','Maior HHI','var(--rose)',null,{sobre:'Índice Herfindahl-Hirschman do maior caso: soma dos quadrados das participações de mercado. Acima de 2.500 o mercado é considerado <b>altamente concentrado</b> pelo padrão do CADE. Concentração alta não é ilícito — é a condição em que combinação se torna fácil, e por isso pede exame do objeto e do número de participantes.'})}${kpi(a.length?a[0].top_share+'%':'—','Maior top-share','var(--rose)',null,{sobre:'Fatia do maior fornecedor no órgão. Complementa o HHI: um mercado pode ter HHI moderado e ainda assim um único fornecedor dominante. <b>Não prova captura</b> — objeto muito específico e mercado pequeno produzem o mesmo número.'})}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por ramo ou fornecedor…" oninput="filtrar(this,'#cmun-list .card')"></div>`;
  h+=`<div id="cmun-list" class="grid">`+a.map(o=>{
    const forte=o.grav>=3;
    const selo=o.ramo_canonico?'':' <span class="tag" title="agrupamento heurístico de 2 palavras — conferir o objeto real">heurístico</span>';
    const top3=(o.top3||[]).map(f=>`${esc((f.nome||f.cnpj).slice(0,34))} <b>${f.share}%</b>`).join(' <span class="dim">·</span> ');
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:700">${esc(o.orgao)}${selo} ${forte?`<span class="tag ${o.grav>=4?'rose':'amber'}">top ${o.top_share}%</span>`:''}</div>
      <div class="muted" style="font-size:12.5px;margin-top:3px">líder: ${clk(o.top_fornecedor.cnpj,o.top_fornecedor.nome||o.top_fornecedor.cnpj)} — ${fmtRc(o.top_fornecedor.valor)} em ${o.top_fornecedor.n} contrato(s)</div>
      <div class="dim" style="margin-top:2px">top 3: ${top3}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:${forte?'var(--rose)':'var(--tx2)'}">${fmtN(o.hhi)}</div><div class="dim">HHI</div></div></div>
      <div class="kv" style="margin-top:8px"><span class="k">${fmtN(o.n_contratos)} contratos · ${fmtN(o.n_fornecedores)} fornecedores · ${fmtRc(o.total)} contratados</span></div>
      ${forte?leitura(`No mercado municipal de <b>${esc(o.orgao)}</b>, <b>${esc(o.top_fornecedor.nome||'—')}</b> detém <b>${o.top_share}%</b> do valor contratado (HHI ${fmtN(o.hhi)}). Concentração nesse nível é screen de captura/R8 — verificar se decorre de ata de RP legítima, estatal prestadora ou de barreiras de entrada nos editais do ramo.`):''}`,
    forte?'hl':'');}).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}

// ═══ SANCIONADAS × PREFEITURA (contrato municipal DURANTE sanção impeditiva — TCM-RJ) ═══
export async function renderSancionadasMun(){
  const d=await J('/api/intel/sancionadas_municipio?limite=300');   // n=238 → cabe inteiro; filtro em memória, não no DOM
  if(!d.ok)return sec('Sancionadas — Prefeitura')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const emp=d.empresas||[];const aepoca=emp.filter(e=>(e.contratos_durante||0)>0);
  let h=cover('prefeitura','Sancionadas contratadas pela Prefeitura do Rio',
    'Empresas com sanção <b>impeditiva</b> (CEIS: impedimento, suspensão, inidoneidade) que assinaram contrato com o <b>Município do Rio</b>. <b>À ÉPOCA</b> = assinatura DENTRO da vigência da punição — vedação legal direta (Lei 14.133, art. 156 §§4º-5º). Competência: <b>TCM-RJ</b>. Órgãos federais/estaduais são excluídos do corte.','🚫')+acoesAba('sancionadas_municipio');
  /* v50 — KPI somado sobre a PÁGINA mentia: a rota entrega no máximo `limite` empresas de `d.n`,
     e os três primeiros KPIs (inclusive um VALOR EM REAIS) eram calculados sobre a fatia recebida.
     Agora contagem vem do total da casa (d.n / d.n_a_epoca) e o dinheiro vem do agregado do
     servidor sobre o conjunto inteiro; se a resposta for antiga (cache sem o campo), o rótulo
     declara explicitamente que é a soma das empresas em tela — nunca um valor mudo. */
  const vdTotal=d.valor_durante_total;const parcial=(vdTotal==null);
  h+=`<div class="grid g2">${kpi(fmtN(d.n??emp.length),'Sancionadas c/ contrato municipal',null,'🚫',
        {sobre:'Empresas com registro de sanção que aparecem em contrato do município. <b>Estar aqui não é achado</b>: a sanção pode ser posterior ao contrato, ou de outro ente, ou já cumprida. O recorte que decide é o de ao lado.'})}${kpi(fmtN(d.n_a_epoca??aepoca.length),'Com contrato À ÉPOCA','var(--rose)','⚠️',
        {sobre:'O ACHADO: contrato ou pagamento <b>dentro da vigência</b> da sanção. Situação vale na data do ato, não hoje — a medição desta casa mostrou que 78,7% das acusações de "empresa não-ativa" eram anacrônicas, e é esse erro que este recorte existe para não repetir.'})}
      ${kpi(fmtRc(parcial?aepoca.reduce((s,e)=>s+(e.valor_durante||0),0):vdTotal),parcial?`Contratado durante sanção (soma das ${fmtN(emp.length)} em tela)`:'Contratado durante sanção','var(--rose)','💸',
        {sobre:'Valor contratado enquanto a sanção vigorava. O rótulo muda quando a lista vem cortada — ali a soma é <b>das empresas em tela</b>, não do acervo, e dizer isso no próprio rótulo é o que impede o número de ser lido como total.'})}${kpi(fmtN(Object.values(d.descartados_outra_esfera||{}).reduce((s,v)=>s+v,0)),'Descartados (outra esfera)',null,'🧹',
        {sobre:'Casos recusados por serem de OUTRA esfera de governo — sanção estadual não alcança contrato municipal e vice-versa. Ficam contados porque esfera trocada já produziu acusação errada aqui, e o descarte precisa ser auditável.'})}</div>`;
  h+=buscaPag('sanm','filtrar por nome ou CNPJ…');
  h+=`<div class="dim" style="margin:6px 2px 0">mostrando ${fmtN(Math.min(100,emp.length))} de ${fmtN(d.n??emp.length)}${emp.length<(d.n??emp.length)?' — o filtro busca nas '+fmtN(emp.length)+' carregadas':' — o filtro busca em todas'}</div>`;
  h+=listaPaginada('sanm',emp,e=>{
    const s0=(e.sancoes||[])[0]||{};const forte=(e.contratos_durante||0)>0;
    const ex=(e.exemplos_durante||[])[0];
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:700">${clk(e.cnpj,e.nome||e.cnpj)} ${forte?`<span class="tag rose">à época</span>`:''}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">${esc(s0.cadastro||'')}: ${esc(s0.categoria||'—')} · ${esc(s0.data_inicio||'?')} → ${esc(s0.data_fim||'sem prazo')}</div>
      <div class="dim" style="margin-top:2px">sancionador: ${esc((s0.orgao||'—').slice(0,60))}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:${forte?'var(--rose)':'var(--tx2)'}">${fmtN(e.contratos_durante||0)}/${fmtN(e.contratos||0)}</div><div class="dim">durante/total</div></div></div>
      <div class="kv" style="margin-top:8px"><span class="k">Contratado total ${fmtRc(e.valor||0)}</span><b style="color:${forte?'var(--rose)':'inherit'}">${fmtRc(e.valor_durante||0)} durante</b></div>
      ${forte&&ex?leitura(`Contrato <b>${esc(ex.contrato||'')}</b> (${esc(ex.data||'?')}, ${fmtRc(ex.valor||0)}) assinado <b>dentro da vigência</b> da sanção ${esc(ex.sancao||'')} (${esc(ex.vigencia||'')}) — "${esc((ex.objeto||'').slice(0,90))}". Vedação objetiva: matéria para representação ao TCM-RJ com pedido de apuração da habilitação.`):''}`,
    forte?'hl':'');},100,e=>e.nome);
  h+=`<div class="note">${esc(d.explicacao||'')}</div>`;
  return h;
}

export async function renderAditivos(esf='estado'){
  const d=await J('/api/intel/aditivos?limite=120&esfera='+esf);
  if(!d.ok)return sec('Aditivos')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover(esf,'Aditivos que estouram o limite legal',
    'Contrato cujo valor cresceu <b>acima do limite de acréscimo</b> (25% em regra; 50% p/ reforma — Lei 14.133 art. 125), ou com <b>change orders em série</b> (≥3 aditivos, red-flag OCDE/Banco Mundial de fraude por aditivos).','📑')+acoesAba('aditivos');
  // total do servidor: só ganha gaveta se a página trouxer o universo
  h+=`<div class="grid g2">${kpi(fmtN(d.n_estoura_teto),'Estouram o teto legal','var(--rose)','🚨',drillSeCompleto('aditEstouraTeto',d.n_estoura_teto,a.filter(x=>x.estoura_teto),{titulo:'Aditivos que estouram o teto legal',nota:'Art. 125 da Lei 14.133: 25% para obras e serviços, 50% para reforma de edifício.'})
        ||{sobre:'Aditivos que ultrapassam o limite do art. 125 da Lei 14.133 (25%, ou 50% em reforma de edifício). Estourar o teto não é automaticamente ilícito: a lei admite hipóteses excepcionais que o próprio processo tem de justificar. A gaveta está desligada porque a lista vem paginada.'})}${kpi(fmtN(d.n_serie),'3+ aditivos em série','var(--amber)','📑',
        {sobre:'Contratos com três ou mais termos aditivos. Aditar é lícito e às vezes necessário; a sequência longa é que levanta a pergunta sobre o planejamento original do objeto.'})}
      ${kpi(fmtN(d.contratos_analisados),'Contratos analisados',null,'📄',{sobre:'Universo efetivamente examinado nesta tela. Serve para responder a pergunta que todo número de achado exige: <b>de quantos?</b> Contrato fora do universo não foi julgado limpo — não foi julgado.'})}${kpi(a.length?fmtPct(a[0].pct):'—','Pior acréscimo','var(--rose)',null,
        {sobre:'O maior percentual de acréscimo da lista. O teto do art. 125 da Lei 14.133 é de 25% (50% em reforma de edifício) — acima disso, o aditivo exige justificativa que o próprio processo tem de trazer.'})}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por fornecedor, órgão ou objeto…" oninput="filtrar(this,'#adt-list .card')"></div>`;
  h+=`<div id="adt-list" class="grid">`+a.map(x=>{
    const forte=x.estoura_teto;
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:700">${clk(x.cnpj,x.fornecedor||x.cnpj_fmt)} ${forte?`<span class="tag rose">${fmtPct(x.pct)}</span>`:`<span class="tag amber">${x.num_aditivos} aditivos</span>`}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">${esc((x.orgao||'—').slice(0,46))}</div>
      <div class="dim" style="margin-top:2px">${esc((x.objeto||'').slice(0,90))}</div></div>
      <div class="right"><div class="num" style="font-weight:800;color:${forte?'var(--rose)':'var(--tx2)'}">${forte?fmtPct(x.pct):x.num_aditivos+'×'}</div><div class="dim">${forte?'acréscimo':'aditivos'}</div></div></div>
      <div class="kv" style="margin-top:8px"><span class="k">R$ inicial ${fmtRc(x.valor_inicial)} → global ${fmtRc(x.valor_global)}${x.acrescimo_real!=null?` · acréscimo real ${fmtRc(x.acrescimo_real)}`:''}</span><b>teto ${x.teto_pct}%</b></div>
      ${forte?`<div class="dim" style="font-size:12px;margin-top:4px">${x.acrescimo_confirmado
        ?'✓ acréscimo <b>confirmado no termo</b> (natureza classificada como valor)'
        :'⚠ percentual por <b>valor global − inicial</b>, que inclui reajuste e prorrogação — indício, não conclusão'}
        · base do %: valor inicial <b>não atualizado</b> (o art. 125 mede sobre o atualizado; rente ao teto pode ser lícito)</div>`:''}
      ${leitura(forte?`Contrato de <b>${esc(x.fornecedor||'—')}</b> saiu de ${fmtRc(x.valor_inicial)} para ${fmtRc(x.valor_global)} — <b>${fmtPct(x.pct)}</b>, acima do teto de ${x.teto_pct}% de acréscimo (${x.num_aditivos} aditivo(s)). ${x.acrescimo_real!=null?'Acréscimo classificado no termo: '+fmtRc(x.acrescimo_real)+'.':'Separar reajuste do acréscimo no termo aditivo.'}`:`${x.num_aditivos} aditivos no mesmo contrato de ${esc(x.fornecedor||'—')} (${fmtRc(x.valor_global)}). Aditamento em série é red-flag de fraude — verificar se cada termo tem justificativa e se somados estouram o limite.`)}`,
    forte?'hl':'');}).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}

// ═══ SOBREPREÇO (Estado) ═══
export async function renderSobrepreco(esf='estado'){
  const d=await J('/api/intel/sobrepreco?limite=120&esfera='+esf);
  if(!d.ok)return sec('Sobrepreço')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover(esf,'Sobrepreço — pagou muito acima da mediana',
    'Mesmo item (descrição normalizada) comprado por vários órgãos: sinaliza quem pagou o preço <b>unitário</b> muito acima da mediana do grupo (≥ 2× a mediana e fora de mediana+3·MAD, medida robusta a outliers). Fonte: preço unitário homologado do PNCP.','📈')+acoesAba('sobrepreco');
  if(!a.length){
    h+=`<div class="warn" style="margin-top:12px">Base de preços unitários em formação: ${fmtN(d.itens_com_preco)} itens com preço, ${fmtN(d.grupos_comparaveis)} grupos comparáveis (≥5 compras do mesmo item). O backfill do PNCP popula o preço unitário item a item; a aba acende conforme a cobertura cresce.</div>`;
    return h+`<div class="note">${esc(d.ressalva||'')}</div>`;
  }
  // total do servidor: só ganha gaveta se a página trouxer o universo
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Itens com sobrepreço','var(--rose)','📈',drillSeCompleto('itensSobrepreco',d.n,a,{titulo:'Itens com indício de sobrepreço',nota:'Comparação com a mediana de mercado do MESMO item — produto diferente não compara.'})
        ||{sobre:'Itens com preço unitário acima da mediana do MESMO item entre compradores públicos. Comparação só vale entre produtos equivalentes — 60% da \'economia\' de uma medição anterior desta casa vinha de comparar coisas diferentes sob descrição parecida. A gaveta está desligada porque a tela recebe uma página.'})}${kpi(fmtN(d.grupos_comparaveis),'Grupos comparáveis',null,'🧺',
        {sobre:'Grupos de itens que puderam ser comparados entre si. É o DENOMINADOR: item sem par comparável não é caro nem barato — é INDISPONÍVEL, e sair dessa contagem não significa aprovação.'})}
      ${kpi(a.length?fmtN(a[0].razao)+'×':'—','Pior caso (× mediana)','var(--rose)',null,
        {sobre:'Quantas vezes o item mais caro supera a mediana do MESMO item. Comparação só vale entre produtos equivalentes: 60% de uma estimativa anterior desta casa comparava coisas diferentes sob descrição genérica.'})}${kpi(fmtRc(a.reduce((s,x)=>s+(x.sobrepreco_est*(x.amostra?1:1)),0)),'Δ acima da mediana (unit.)',null,'💸',
        {sobre:'Diferença unitária entre o preço praticado e a mediana. É estimativa de sobrepreço, não dano apurado — sobrepreço se confirma com pesquisa de mercado da época e especificação completa do item.'})}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por item, órgão ou fornecedor…" oninput="filtrar(this,'#sob-list .card')"></div>`;
  h+=`<div id="sob-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:700">${esc(x.item)}${x.unidade_medida?` <span class="dim">/ ${esc(x.unidade_medida)}</span>`:''}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">${esc((x.orgao||'—').slice(0,48))}${x.municipio?' · '+esc(x.municipio):''}</div>
      <div class="dim" style="margin-top:2px">venc.: ${clk(x.fornecedor_cnpj,x.fornecedor||'—')}${x.data?' · '+esc(x.data):''}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:var(--rose)">${fmtN(x.razao)}×</div><div class="dim">a mediana</div></div></div>
      <div class="kv" style="margin-top:8px"><span class="k">Pagou <b style="color:var(--rose)">${fmtR(x.preco)}</b> · mediana ${fmtR(x.mediana)} (n=${fmtN(x.amostra)})</span><b>z ${fmtN(x.z_robusto)}</b></div>
      ${leitura(`Este órgão pagou <b>${fmtR(x.preco)}</b> por unidade de "${esc(x.item)}", enquanto a mediana de ${fmtN(x.amostra)} compras do mesmo item foi <b>${fmtR(x.mediana)}</b> — <b>${fmtN(x.razao)}× mais caro</b> (z robusto ${fmtN(x.z_robusto)}). Sobrepreço unitário estimado: ${fmtR(x.sobrepreco_est)}. Confirmar marca/especificação no termo de referência.`)}`,
    'hl')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}

// ═══ ESCALADA DE PREÇO (mesmo fornecedor sobe o preço do mesmo item no tempo) ═══
export async function renderEscalada(esf='estado'){
  const d=await J('/api/intel/escalada?limite=120&esfera='+esf);
  if(!d.ok)return sec('Escalada')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover(esf,'Escalada de preço — o mesmo fornecedor sobe o preço no tempo','Diferente do sobrepreço (que compara entre órgãos), aqui é <b>longitudinal</b>: o <b>mesmo fornecedor</b> vende o <b>mesmo item</b> ao poder público por preços cada vez <b>maiores</b> (≥3 compras, ≥45 dias, alta ≥3×). É o padrão de <b>preço dirigido/captura</b> — o fornecedor aprende que o comprador aceita aumentos. Cruza com a mediana de mercado dos outros fornecedores.','🪜')+acoesAba('escalada');
  if(!a.length){
    h+=`<div class="warn" style="margin-top:12px">Sem escalada detectada na janela atual de preços do PNCP — a base de preço unitário ainda é estreita no tempo. Acende conforme o histórico cresce.</div>`;
    return h+`<div class="note">${esc(d.ressalva||'')}</div>`;
  }
  registrarDrill('aditAcimaMercado',{titulo:'Aditivos cujo preço final também supera o mercado',itens:a.filter(x=>x.final_vs_mercado&&x.final_vs_mercado>=2),nota:'Acréscimo dentro do limite legal ainda pode chegar a preço fora do mercado.'});
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Escaladas detectadas','var(--rose)','📈',drillSeCompleto('escaladasTodas',d.n,a,{titulo:'Escaladas de preço detectadas',nota:'Escalada compara o mesmo item ao longo do tempo no mesmo comprador — variação legítima existe e o objeto decide.'})
        ||{sobre:'Contratos cujo valor cresce em degraus sucessivos. Escalada tem explicações inocentes fortes — reequilíbrio econômico-financeiro e reajuste contratual respondem por boa parte. A gaveta está desligada porque a lista vem paginada.'})}${kpi(a.filter(x=>x.final_vs_mercado&&x.final_vs_mercado>=2).length,'Também acima do mercado','var(--rose)','🎯',{drill:'aditAcimaMercado'})}
      ${kpi(a.length?fmtN(a[0].razao)+'×':'—','Maior escalada','var(--rose)',null,{sobre:'O EXTREMO da cauda, não o típico: quantas vezes o preço do mesmo item cresceu no mesmo comprador, no pior caso observado. Serve para dizer até onde a cauda vai. Reajuste contratual, mudança de especificação e variação cambial produzem escalada legítima — o objeto decide.'})}${kpi(a.length?fmtN(a[0].span_dias)+'d':'—','Janela do pior caso',null,'📅',{sobre:'Em quantos dias a maior escalada aconteceu. Uma alta de 3× em 30 dias e a mesma alta em 3 anos são fatos diferentes: a janela é o que separa reajuste de salto.'})}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por item ou fornecedor…" oninput="filtrar(this,'#escal-list .card')"></div>`;
  h+=`<div id="escal-list" class="grid">`+a.map(x=>{
    const serie=(x.serie||[]).map(s=>`<span title="${esc(s.orgao||'')} ${esc(s.data)}">${fmtR(s.preco)}</span>`).join(' <span class="dim">→</span> ');
    const mkt=x.final_vs_mercado?`<span class="tag rose">${fmtN(x.final_vs_mercado)}× o mercado</span>`:'';
    return card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:700">${esc(x.item)}${x.unidade_medida?` <span class="dim">/ ${esc(x.unidade_medida)}</span>`:''}</div>
      <div class="dim" style="margin-top:2px">${clk(x.fornecedor_cnpj,x.fornecedor||'—')} · ${fmtN(x.n_compras)} compras em ${fmtN(x.span_dias)} dias ${mkt}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:var(--rose)">${fmtN(x.razao)}×</div><div class="dim">${fmtR(x.preco_inicial)} → ${fmtR(x.preco_final)}</div></div></div>
      <div class="kv" style="margin-top:8px"><span class="k">série: ${serie}</span></div>
      ${leitura(`<b>${esc(x.fornecedor)}</b> vendeu "${esc(x.item)}" começando em <b>${fmtR(x.preco_inicial)}</b> e chegando a <b>${fmtR(x.preco_final)}</b> (<b>${fmtN(x.razao)}× mais caro</b>) em ${fmtN(x.span_dias)} dias${x.final_vs_mercado?`, hoje <b>${fmtN(x.final_vs_mercado)}× a mediana de mercado</b> do item`:''}. Nenhum reajuste legítimo triplica preço nessa janela — indício de preço dirigido. Confirmar especificação no termo de referência.`)}`,
    'hl');}).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}

// ═══ RISCOS (Transversal): fantasmas · sancionadas · nunca ganham ═══
export let _riscoView='fantasmas';
export async function renderRiscos(){
  const chips=`<div class="chips">
    <button type="button" class="chip ${_riscoView==='fantasmas'?'on':''}" onclick="_riscoView='fantasmas';ir('g_riscos')">Fantasmas</button>
    <button type="button" class="chip ${_riscoView==='sanc'?'on':''}" onclick="_riscoView='sanc';ir('g_riscos')">Sancionadas</button>
    <button type="button" class="chip ${_riscoView==='cover'?'on':''}" onclick="_riscoView='cover';ir('g_riscos')">Nunca ganham</button></div>`;
  if(_riscoView==='sanc')return chips+acoesAba('sancionadas')+(await renderSancionadas(''));
  if(_riscoView==='cover'){
    const d=await J('/api/intel/perdedoras');
    let h=cover('geral','Perdedoras contumazes — participam e NUNCA vencem',
      'Empresa que compete "sempre" e nunca vence é o perfil clássico de <b>proposta de cobertura</b> (OCDE bid rigging): existe para dar aparência de disputa e legitimar o vencedor combinado. Quanto mais vezes perde junto do MESMO vencedor, mais forte o indício.','🎭')+chips+acoesAba('perdedoras');
    if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
    const cov=d.cobertura_extracao||{};
    registrarDrill('perdedorasContumazes',{titulo:'Perdedoras contumazes — participam e nunca vencem',
      itens:(d.perdedoras||[]),
      render:p=>card(`<div style="display:flex;justify-content:space-between;gap:10px"><div style="min-width:0">${clk(p.cnpj,p.nome!=='—'?p.nome:p.cnpj_fmt)}<div class="dim">${esc(p.cnpj_fmt||'')}</div></div><div class="right"><div class="num" style="font-weight:800">${p.participou}×</div><div class="dim">participou · 0 vitórias</div></div></div>`),
      nota:'Perder sempre é indício de proposta de cobertura, não prova.'});
    h+=`<div class="grid g2">${kpi(fmtN(d.n),'Perdedoras contumazes','var(--amber)','🎭',{drill:'perdedorasContumazes'})}${kpi(fmtN(cov.atas_entrada),'Atas no corpus',null,'📄',{sobre:'Quantas atas de sessão entraram no corpus. É o DENOMINADOR: sem ele, \'12 perdedoras contumazes\' pode ser 12 em 12 ou 12 em 12 mil. O PNCP publica só o vencedor — os perdedores vêm do TEXTO das atas, e a extração é conservadora de propósito.'})}${kpi(fmtN(cov.atas_avaliaveis),'Atas avaliáveis',null,'✅',{sobre:'Das atas no corpus, quantas têm participantes E resultado extraíveis. A diferença para o total não é falha do órgão: é ata que não traz a lista de quem disputou. <b>Cobertura pequena não é ausência de conluio</b> — é ausência de observação.'})}${kpi(fmtN(cov.certames_no_grafo),'Certames no grafo',null,'🕸️',
        {sobre:'Certames que entraram na rede de participantes. Fora dela não há como testar rodízio nem captura — o certame não foi absolvido, ficou sem exame.'})}</div>`;
    if((cov.atas_avaliaveis||0)<50)h+=`<div class="warn" style="margin-top:12px">Cobertura ainda pequena: só ${fmtN(cov.atas_avaliaveis)} de ${fmtN(cov.atas_entrada)} atas têm participantes+resultado extraíveis. O PNCP publica apenas o vencedor; os perdedores vêm do texto das atas — a extração é conservadora de propósito (zero falso-positivo) e cresce com o corpus.</div>`;
    h+=`<div class="grid" style="margin-top:12px">`+(d.perdedoras||[]).map(p=>card(
      `<div style="display:flex;justify-content:space-between;gap:10px"><div style="min-width:0">${clk(p.cnpj,p.nome!=='—'?p.nome:p.cnpj_fmt)}<div class="dim">${esc(p.cnpj_fmt)}</div></div>
       <div class="right"><div class="num" style="font-weight:800;font-size:19px;color:var(--amber)">${p.participou}×</div><div class="dim">participou · 0 vitórias</div></div></div>
       ${(p.perde_junto_com||[]).length?leitura('Perde junto com: '+(p.perde_junto_com||[]).map(x=>`<b>${esc(x.nome!=='—'?x.nome:x.cnpj)}</b> (${x.vezes}×)`).join(' · ')+' — o co-participante mais frequente é o beneficiário provável da cobertura.'):''}`)).join('')+`</div>`;
    h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
    return h;
  }
  // fantasmas
  const d=await J('/api/intel/fantasmas?limite=60');
  let h=cover('geral','Radar de empresas-fantasma',
    'Score 0-100 por <b>8 sinais objetivos</b> (situação irregular na Receita, capital incompatível com o que recebe, endereço-ninho, endereço residencial, aberta às vésperas do 1º contrato, sócio único + capital baixo, CNAE incompatível, sanção). Aplicado ao conjunto-alvo: vencedoras de captura/rodízio, perdedoras contumazes, sancionadas e top favorecidos.','👻')+chips+acoesAba('fantasmas');
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const emp=(d.empresas||[]).filter(e=>e.classificacao!=='sem_cadastro');
  /* CADA MÉTRICA REGISTRA O CONJUNTO QUE ELA CONTA — mesmo universo, sempre: `alto` e `medio` saem
     do mesmo `emp` que alimenta os números, e "sem cadastro" sai da lista bruta. "Empresas no alvo"
     é um total do SERVIDOR e por isso NÃO ganha drill: registrar `emp` ali faria o clique mostrar
     menos linhas do que o número promete — foi exatamente esse o defeito da primeira versão. */
  const _lin=e=>card(`<div style="display:flex;justify-content:space-between;gap:10px"><div style="min-width:0">${clk(e.cnpj,e.razao_social||e.cnpj)}<div class="dim">${esc(e.cnpj)} · ${rot(e.origem||'—')}</div></div><div class="right"><div class="num" style="font-weight:800">${e.score??'—'}</div><div class="dim">/100 ${esc(e.classificacao||'')}</div></div></div>`);
  registrarDrill('fantasmaAlto',{titulo:'Empresas com risco ALTO de fachada',itens:emp.filter(e=>e.classificacao==='alto'),render:_lin,nota:'Score 0-100 por 8 sinais objetivos; indício de fachada, não prova.'});
  registrarDrill('fantasmaMedio',{titulo:'Empresas com risco médio',itens:emp.filter(e=>e.classificacao==='medio'),render:_lin});
  /* `sem_cadastro` NÃO GANHA DRILL, e a razão é a regra da casa: o número (647) é um total do
     SERVIDOR e a página traz 60 empresas — a gaveta mostrava ZERO linhas para um KPI de 647.
     Verificado ao vivo. Enquanto a rota não servir essas linhas, a métrica fica sem caminho: KPI
     sem clique é honesto, gaveta que mostra 0 para 647 é mentira. */
  h+=`<div class="grid g2">${kpi(fmtN(d.total_alvo),'Empresas no alvo',null,'🎯',{sobre:'Conjunto submetido ao radar de fachada: vencedoras de captura ou rodízio, perdedoras contumazes, sancionadas e maiores favorecidos. <b>Não é o universo de fornecedores</b> — é onde faz sentido gastar verificação. Empresa fora do alvo não foi considerada regular.'})}${kpi(fmtN(emp.filter(e=>e.classificacao==='alto').length),'Risco ALTO','var(--rose)','🔴',{drill:'fantasmaAlto'})}
      ${kpi(fmtN(emp.filter(e=>e.classificacao==='medio').length),'Risco médio','var(--amber)','🟡',{drill:'fantasmaMedio'})}${kpi(fmtN(d.sem_cadastro),'Sem cadastro ainda','var(--dim)','⏳',
        {sobre:'Empresas do alvo cujo cadastro ainda não foi coletado. É fila de trabalho, não achado: enquanto está aqui, nenhuma conclusão sobre fachada pode ser tirada.'})}</div>`;
  if(d.sem_cadastro>0)h+=`<div class="warn" style="margin-top:12px"><b>${fmtN(d.sem_cadastro)}</b> empresas do alvo ainda sem cadastro da Receita na base (fila de enriquecimento). "Sem cadastro" NÃO significa regular — significa não-avaliada.</div>`;
  h+=`<div class="grid" style="margin-top:12px">`+emp.slice(0,50).map(e=>{
    const cor=e.classificacao==='alto'?'var(--rose)':e.classificacao==='medio'?'var(--amber)':'var(--green)';
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0">${clk(e.cnpj,e.razao_social||e.cnpj)}<div class="dim">${esc(e.cnpj)} · no alvo por: ${rot(e.origem||'—')}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:${cor}">${e.score??'—'}</div><div class="dim">/100 ${esc(e.classificacao)}</div></div></div>
      ${(e.sinais||[]).length?`<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">${e.sinais.map(s=>`<span class="tag ${e.classificacao==='alto'?'rose':'amber'}" title="${esc(s.detalhe||'')}">${rot(s.id)} +${s.peso}</span>`).join('')}</div>`:''}
      ${(e.sinais||[]).length?leitura(esc((e.sinais[0]||{}).detalhe||'')+((e.sinais||[]).length>1?' — e mais '+(e.sinais.length-1)+' sinal(is); toque no nome para o dossiê completo.':'')):''}`,e.classificacao==='alto'?'hl':'');}).join('')+`</div>`;
  h+=`<div class="note">${esc(d.explicacao||'')} ${esc(d.ressalva||'')}</div>`;
  return h;
}

// ═══ PREFEITURA DO RIO ═══
export async function renderPanoramaPref(){
  /* Medido em campo (2026-07-31): conluio 0,462 s · comissionados 0,183 s · benefícios 0,114 s.
     Paralelo fecha em ~0,5 s — não há o que quebrar aqui. */
  const [cj,cc,bv]=await Promise.all([J('/api/pncp/conluio?esfera=prefeitura'),J('/api/pcrj/comissionados_candidatos?limite=1'),J('/api/pcrj/beneficios_vinculo')]);
  const cov=cj.cobertura||{},cap=cj.captura||[],rod=cj.rodizio_vencedores||[];
  let h=cover('prefeitura','Prefeitura do Rio de Janeiro','Licitações do MUNICÍPIO do Rio pelo PNCP (esfera oficial), folha de comissionados, candidaturas e benefícios sociais. Os demais municípios do RJ ficam em Transversal → Conluio → chip "Municípios".','🏙️');
  h+=`<div class="grid g2">
    ${kpi(fmtN(cov.certames_com_resultado),'Certames do município',null,'📄','p_contr')}${kpi(fmtN(cov.orgaos),'Órgãos compradores',null,'🏢','p_gastos')}
    ${kpi(cap.length+rod.length,'Conluio (capturas+rodízios)','var(--purple)','🕸️','p_conluio')}${kpi(fmtN(cc.n_pessoas??cc.n??'—'),'Comissionados ex-candidatos','var(--amber)','🎖️','p_comis')}
    ${kpi(fmtN((bv.resumo||{}).n_alta??'—'),'Benefício DURANTE vínculo (certeza alta)','var(--rose)','🚨','p_benef')}${kpi(fmtN((bv.resumo||{}).n_ainda??'—'),'Ainda recebendo','var(--rose)','⏰','p_benef')}</div>`;
  h+=`<div style="height:16px"></div>`+sec('Ir para')+`<div class="grid two">
    ${card(`<div style="font-weight:700">Perícia de gastos D7–D10</div><div class="muted" style="font-size:13px">fracionamento, credor recém-aberto, sócio na folha, rede entre concorrentes</div><div class="btns"><button class="btn accent" onclick="ir('p_gastos')">Abrir</button></div>`)}
    ${card(`<div style="font-weight:700">Comissionados</div><div class="muted" style="font-size:13px">ex-candidatos + benefício social durante o vínculo</div><div class="btns"><button class="btn accent" onclick="ir('p_comis')">Abrir</button></div>`)}
    ${card(`<div style="font-weight:700">Servidor-fantasma</div><div class="muted" style="font-size:13px">8 sinais determinísticos, faixas forte/verificar/fraco</div><div class="btns"><button class="btn ghost" onclick="ir('p_fant')">Abrir</button></div>`)}
    ${card(`<div style="font-weight:700">PPPs e concessões</div><div class="muted" style="font-size:13px">triagem de red flags CCPAR + dossiê Souza Aguiar</div><div class="btns"><button class="btn ghost" onclick="ir('p_ppp')">Abrir</button></div>`)}
    ${card(`<div style="font-weight:700">Conluio municipal</div><div class="muted" style="font-size:13px">${cap.length+rod.length} indícios · nomes e objetos</div><div class="btns"><button class="btn ghost" onclick="ir('p_conluio')">Abrir</button></div>`)}</div>`;
  h+=`<div class="note">${esc(cj.aviso||'')}</div>`;
  return h;
}
export let _comisView='cand';
export async function renderComissionadosPref(){
  const chips=`<div class="chips">
    <button type="button" class="chip ${_comisView==='cand'?'on':''}" onclick="_comisView='cand';ir('p_comis')">Foram candidatos</button>
    <button type="button" class="chip ${_comisView==='benef'?'on':''}" onclick="_comisView='benef';ir('p_comis')">Benefício × vínculo</button></div>`;
  if(_comisView==='benef')return renderBeneficiosPref(chips);
  const d=await J('/api/pcrj/comissionados_candidatos?limite=1000');
  let h=cover('prefeitura','Comissionados da Prefeitura que foram candidatos',
    'Cruzamento da folha de cargos de confiança da Prefeitura do Rio com as candidaturas registradas no TSE. Cargo de confiança ocupado por quem disputa eleição é o retrato do aparelhamento político da máquina. Cada card é <b>uma pessoa</b>, com o histórico completo de nomeações — não mais uma linha por vínculo.','🗳️')+chips+acoesAba('comissionados');
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const it=d.comissionados||[];  // agora 1 item por PESSOA, com postos[] e candidaturas[]
  const nCidades=new Set(it.flatMap(x=>(x.candidaturas||[]).map(c=>c.cidade)).filter(Boolean)).size;
  /* Conferido na rota viva antes de ligar: `n_pessoas` do servidor e o tamanho da lista são os
     mesmos 341 — o teto de 1000 não corta nada hoje. Se um dia cortar, o `painel_drill_check`
     acusa na rodada seguinte, que é o ponto de ele existir. `Cidades de candidatura` conta um
     Set de strings, não linhas de uma lista, e por isso fica sem gaveta. */
  registrarDrill('comissCandidatos',{titulo:'Comissionados da Prefeitura que foram candidatos',itens:it,
    render:x=>card(`<div style="display:flex;justify-content:space-between;gap:10px"><div style="min-width:0"><div style="font-weight:700">${esc(x.nome||'—')}</div><div class="dim">${fmtN((x.postos||[]).length)} posto(s) · ${fmtN((x.candidaturas||[]).length)} candidatura(s)</div><div class="dim">${(x.candidaturas||[]).slice(0,3).map(c=>esc(`${c.cargo||''} ${c.ano||''} ${c.cidade||''}`)).join(' · ')}</div></div></div>`),
    nota:'Cruzamento por NOME com o TSE — indício; cargo de confiança não é, por si, irregularidade.'});
  h+=`<div class="grid g2">${kpi(fmtN(d.n_pessoas||it.length),'Pessoas ex-candidatas','var(--amber)','🎖️',{drill:'comissCandidatos'})}${kpi(fmtN(nCidades),'Cidades de candidatura',null,'🗺️',
        {sobre:'Municípios em que os nomes da folha aparecem como candidatos. Candidatar-se é direito político e não é irregularidade alguma — o cruzamento serve para ver coincidência entre nomeação e vínculo partidário, que é outra pergunta.'})}</div>`;
  h+=buscaPag('cc-list','filtrar por nome, cargo, órgão, cidade — busca em TODAS as pessoas…');
  if(d.truncado)h+=`<div class="note" style="margin-top:8px">Base tem mais pessoas do que o teto do servidor (1000) — caso raro; avise se precisar de mais.</div>`;
  const _montarCC=x=>{
    const postos=(x.postos||[]).map(p=>`<div class="dim" style="margin-top:2px">${esc(p.cargo||'—')} @ ${esc((p.orgao||'—').slice(0,50))} — ${esc(p.admissao||'?')}${p.exoneracao?' → '+esc(p.exoneracao):' · ativo'}</div>`).join('');
    const cands=(x.candidaturas||[]).map(c=>`<span class="tag amber">${esc(c.cargo||'?')} ${esc(String(c.ano||''))}${c.cidade?' · '+esc(c.cidade):''}</span>`).join(' ');
    const homon=x.homonimo_provavel?` <span class="tag" title="candidatou em 3+ cidades — provável homônimo, não a mesma pessoa">homônimo provável</span>`:'';
    return card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">
      <div style="font-weight:700">${esc(x.nome_pcrj)}${x.n_postos>1?` <span class="tag" style="font-weight:400">${x.n_postos} nomeações</span>`:''}${homon}</div>
      ${postos}</div>
      <div class="right" style="text-align:right">${cands}</div></div>`);
  };
  h+=listaPaginada('cc-list',it,_montarCC,60,x=>x.nome_pcrj);
  h+=`<div class="note">${esc(d.explicacao||'')} ${esc(d.ressalva||'')}</div>`;
  return h;
}
export async function renderBeneficiosPref(chips){
  const d=await J('/api/pcrj/beneficios_vinculo');
  chips=(chips||'')+acoesAba('beneficios');
  let h=cover('prefeitura','Servidores × benefício social — DURANTE o vínculo',
    'Pessoas que recebiam <b>Bolsa Família, BPC, Auxílio Brasil ou Auxílio Emergencial</b> (programas para quem tem baixa renda) <b>no mesmo mês</b> em que tinham salário como servidor/comissionado da Prefeitura ou Câmara do Rio. Meses fora do vínculo NÃO entram (justiça na contagem). É <b>indício de renda incompatível a apurar</b> — nunca acusação: pode haver dependente no mesmo CPF, homônimo ou erro de base. Cada linha traz o <b>nome</b>, o órgão, o cargo e o período.','🍞')+(chips||'');
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const r=d.resumo||{};
  // legenda dos dois eixos que confundiam: IDENTIDADE (quem é a pessoa) × BENEFÍCIO (o que recebeu)
  h+=`<div class="note" style="margin:10px 0 4px"><b>Como ler:</b> <span class="sev alta" style="padding:1px 7px">identidade confirmada</span> = há UM só servidor com esse nome na folha e o fragmento de CPF bate (é mesmo esta pessoa). <span class="sev media" style="padding:1px 7px">conferir homônimo</span> = nome comum, confirmar o CPF antes de usar. Isso é sobre <b>QUEM é a pessoa</b> — separado de <span class="tag rose">ainda recebe</span>, que diz que o benefício <b>continua ativo</b> hoje.</div>`;
  // total do servidor: só ganha gaveta se a página trouxer o universo
  h+=`<div class="grid g2">${kpi(fmtN(d.n_casos),'Pessoas identificadas','var(--amber)','👥',drillSeCompleto('pessoasIdentificadas',d.n_casos,(d.casos||d.itens||[]),{titulo:'Pessoas identificadas',nota:'Identificação por nome — confirmar homônimo antes de qualquer juízo.'})
        ||{sobre:'Pessoas cujo nome na folha municipal casou com o cadastro de benefício. Identificação por nome carrega homônimo — o recorte com CPF conferido está no KPI ao lado, e é ele que sustenta qualquer afirmação individual. A gaveta está desligada porque a lista vem paginada.'})}${kpi(fmtN(r.n_alta),'Identidade confirmada (nome único + CPF)','var(--rose)','🪪',
        {sobre:'Casos em que o nome é único na base E o fragmento de CPF confere. Sem os dois, o cruzamento é indício de identidade, não identidade — e nenhum caso sobe a produto sem essa distinção declarada.'})}
      ${kpi(fmtN(r.n_nomeados),'Comissionados/nomeados','var(--amber)','🎖️',
        {sobre:'Do universo identificado, quantos ocupam cargo de <b>livre nomeação</b>. É o recorte que importa: cargo comissionado tem remuneração conhecida e nomeação discricionária, o que torna a acumulação com benefício assistencial verificável — e a nomeação, atribuível.'})}${kpi(fmtN(r.n_ainda),'Benefício ainda ativo','var(--rose)','⏰',
        {sobre:'Casos em que o benefício aparece na competência MAIS RECENTE da base, não apenas em algum mês passado. A distinção é o que separa situação corrente de sobreposição já encerrada — e só a primeira comporta providência.'})}
      ${kpi(fmtN(r.n_bf),'Bolsa Família',null,'🍞',
        {sobre:'Benefício com critério de <b>renda familiar</b>. A sobreposição com remuneração pública é indício de renda não declarada ao cadastro — não de fraude provada: composição familiar muda, e a atualização cadastral tem prazo próprio.'})}${kpi(fmtN(r.n_bpc),'BPC',null,'♿',
        {sobre:'Benefício de Prestação Continuada — critério de <b>deficiência ou idade</b> somado à renda per capita. Ser servidor não veda o BPC por si; o que pesa é a renda do grupo familiar. Por isso este número fica separado do Bolsa Família em vez de somado.'})}
      ${kpi(esc(r.cobertura_benef||'—'),'Cobertura benefícios',null,'📅',
        {sobre:'A janela de competências efetivamente ingerida. Fora dela nada foi observado — e benefício ausente num mês que não entrou na base <b>não cessou</b>: o mês é que não existe aqui.'})}${kpi(esc(r.ultima||'—'),'Última competência',null,'🗓️',
        {sobre:'O mês mais recente disponível. É contra ele que "ainda ativo" é medido; se a base estiver defasada, o número de ativos descreve o passado dessa data, não o presente.'})}</div>`;
  h+=buscaPag('bv-list','filtrar por nome, órgão, cargo, partido — busca em TODOS os casos…');
  const _montarBV=x=>{
    const idOk=x.certeza==='ALTA';
    const selo=idOk?'<span class="sev alta" title="um só servidor com este nome + CPF bate — é esta pessoa">identidade confere</span>'
                  :'<span class="sev media" title="nome comum — confirmar CPF antes de usar">conferir homônimo</span>';
    return card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">
      <div style="font-weight:800;font-size:15px">${esc(x.nome)}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">${[x.poder,(x.orgao||'').slice(0,44),(x.cargo||'').slice(0,30),x.partido].filter(Boolean).map(esc).join(' · ')}</div>
      <div class="dim" style="margin-top:3px">${[x.natureza,x.situacao,x.cargo?'':'cargo não informado pela fonte'].filter(Boolean).map(esc).join(' · ')}</div></div>
      <div class="right">${selo}
      ${x.ainda_recebe?'<div style="margin-top:5px"><span class="tag rose" title="o benefício continua ativo na última competência">ainda recebe</span></div>':''}</div></div>
    <div class="kv" style="margin-top:8px"><span class="k">${esc(x.beneficios_str||'benefício')}</span><b>${esc(x.desde||'')} → ${esc(x.ate||'')} · ${fmtN(x.n_meses)} meses no vínculo</b></div>`,
    idOk?'hl':'');};
  h+=listaPaginada('bv-list',d.casos||[],_montarBV,60,x=>x.nome);
  h+=`<div class="note">${esc(d.explicacao||'')} ${esc(d.ressalva||'')}</div>`;
  return h;
}
export const _DET_ROTULO={d7_fracionamento:['✂️','Fracionamento de despesa','sucessão de contratações do mesmo objeto/credor somando acima do teto de dispensa (Lei 14.133 art. 75)'],
  d8_credor_recem_aberto:['🐣','Credor recém-aberto','empresa criada há <180 dias já recebendo da Prefeitura'],
  d9_socio_na_folha:['👔','Sócio de credor na folha','sócio de empresa contratada com vínculo na folha municipal (Lei 14.133 art. 9º)'],
  d10_rede_concorrentes:['🕸️','Rede entre concorrentes','sócios em comum entre empresas que disputam os mesmos certames'],
  d11_aditivo_estourado:['📈','Aditivo acima do limite','acréscimo contratual além dos 25%/50% do art. 125'],
  d12_coendereco_concorrentes:['📍','Co-endereço (OCDE)','fornecedores concorrentes do mesmo órgão no mesmo CEP']};
export let _gastosDet='';
export async function renderGastosPref(){
  const d=await J('/api/pcrj/gastos_achados');
  let h=cover('prefeitura','Perícia de gastos — detectores D7–D12',
    'Detectores determinísticos sobre a despesa por credor (ContasRio 2019-2023) e contratos/licitações municipais (PNCP 2024+): fracionamento, credor recém-aberto, sócio na folha, rede societária, aditivo acima do limite e co-endereço entre concorrentes (red flag OCDE 2025). Cada achado carrega a evidência e a base normativa; a perícia completa em PDF sai pelo runner com o colegiado de 5 lentes.','✂️')+acoesAba('gastos_pcrj');
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)} — rode tools/pcrj_pericia_gastos.py</div>`);
  const dets=Object.keys(d.detectores||{});
  /* A PROCEDÊNCIA JÁ EXISTIA E NÃO CHEGAVA À TELA: `_DET_ROTULO` guarda, no terceiro campo, o que
     cada detector mede e a base normativa — e o KPI só usava o ícone e o rótulo. Escrever texto
     novo aqui seria duplicar (e um dia divergir) o que a tabela já diz; o certo é ligar o que há. */
  h+=`<div class="grid g2">`+dets.map(k=>{const m=_DET_ROTULO[k]||['📌',k,''];
    return kpi(fmtN(d.detectores[k]),m[1],k==='d9_socio_na_folha'?'var(--rose)':null,m[0],
      m[2]?{sobre:esc(m[2])+' — a contagem é de INDÍCIOS a examinar, nunca de irregularidades apuradas.'}:null);}).join('')+`</div>`;
  h+=`<div class="chips" style="margin-top:12px"><button type="button" class="chip ${_gastosDet===''?'on':''}" onclick="_gastosDet='';ir('p_gastos')">Todos</button>`+
    dets.map(k=>`<button type="button" class="chip ${_gastosDet===k?'on':''}" onclick="_gastosDet='${k}';ir('p_gastos')">${svgIco((_DET_ROTULO[k]||['📌',k])[0])} ${(_DET_ROTULO[k]||['',k])[1]}</button>`).join('')+`</div>`;
  h+=`<div class="search"><span class="mag"></span><input placeholder="filtrar por credor, órgão, objeto…" oninput="filtrar(this,'#pg-list .card')"></div>`;
  const mostrar=_gastosDet?{[_gastosDet]:(d.achados||{})[_gastosDet]||[]}:(d.achados||{});
  let cards='';
  for(const [det,lista] of Object.entries(mostrar)){
    const m=_DET_ROTULO[det]||['📌',det,''];
    cards+=(lista||[]).slice(0,_gastosDet?200:12).map(a=>card(
      `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">
        <div style="font-weight:700">${svgIco(m[0])} ${esc(corta(a.titulo,90))}</div>
        <div class="muted" style="font-size:12.5px;margin-top:4px">${esc(corta(a.descricao,260))}</div></div>
        <span class="sev ${a.severidade==='alta'?'alta':'media'}">${esc(a.severidade||'')}</span></div>`,
      a.severidade==='alta'?'hl':'')).join('');
  }
  h+=`<div id="pg-list" class="grid">`+cards+`</div>`;
  if(!cards)h+=card('<div class="muted">Nenhum achado deste detector na última corrida — a base é revarrida a cada sweep; um resultado limpo aqui é um resultado, não um vazio.</div>');
  h+=`<div class="note">${esc(d.explicacao||'')} ${esc(d.ressalva||'')}</div>`;
  return h;
}
export let _fantFaixa='';
export async function renderFantasmasPref(){
  const qsF=new URLSearchParams({limite:800});  // 800 = teto real do servidor (rotas/investigacao.py)
  if(_fantFaixa)qsF.set('faixa',_fantFaixa);
  const d=await J('/api/pcrj/fantasmas?'+qsF.toString());
  let h=cover('prefeitura','Sinais de servidor-fantasma — Câmara/Prefeitura',
    'Oito sinais determinísticos (múltiplos gabinetes, cargo incompatível, vínculos concomitantes, geografia impossível…) somados em escore. É funil de priorização OSINT: a prova definitiva é o ponto/frequência interno, que só a apuração formal alcança.','👻')+acoesAba('fantasmas_pcrj');
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const fx=d.faixas||{};
  h+=`<div class="grid g2">${kpi(fmtN(fx.forte),'Faixa FORTE','var(--rose)','🔴',
        {sobre:'Servidores da folha municipal com o conjunto MAIS FORTE de sinais de vínculo apenas formal. Faixa é ordem de diligência, não conclusão: nenhum caso aqui afirma que a pessoa não trabalha — afirma que o cruzamento não achou o que deveria achar se ela trabalhasse.'})}${kpi(fmtN(fx.verificar),'Verificar','var(--amber)','🟡',
        {sobre:'Sinais presentes mas insuficientes para separar de explicação inocente — licença, cessão, lotação em unidade que não publica frequência. Existe para não empurrar dúvida para dentro da faixa forte.'})}${kpi(fmtN(fx.fraco),'Fraco',null,'🟢',
        {sobre:'Um único sinal, ou sinal com alta prevalência na própria base. Fica visível de propósito: esconder a cauda faria as faixas de cima parecerem mais decisivas do que são.'})}${kpi(esc((d.gerado_em||'').slice(0,10)),'Gerado em',null,'🗓️',
        {sobre:'Data da última execução do detector. Número velho com cara de atual é a forma mais silenciosa de errar; por isso a data fica ao lado das faixas, não escondida no rodapé.'})}</div>`;
  h+=`<div class="chips" style="margin-top:12px">`+['','forte','verificar','fraco'].map(f=>
    `<button type="button" class="chip ${_fantFaixa===f?'on':''}" onclick="_fantFaixa='${f}';ir('p_fant')">${f||'Todas as faixas'}</button>`).join('')+`</div>`;
  h+=buscaPag('pf-list','filtrar por nome ou gabinete — busca em TODOS os servidores…');
  const _itF=d.itens||[];
  const _montarF=x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">
      <div style="font-weight:700">${esc(x.nome)}${x.homonimo?' <span class="tag amber" title="nome existe em ≥3 municípios — confirmar por CPF/matrícula">homônimo?</span>':''}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">${esc(corta(x.gabinetes||'—',60))} · ${esc(corta(x.cargos_camara||'—',40))}</div>
      <div class="dim" style="margin-top:4px">${esc(corta(x.sinais,200))}</div></div>
      <div class="right"><span class="sev ${x.faixa==='forte'?'alta':'media'}">${esc(x.faixa)}</span><div class="dim" style="margin-top:4px">score ${x.score}</div></div></div>`,
    x.faixa==='forte'?'hl':'');
  h+=listaPaginada('pf-list',_itF,_montarF,60,x=>x.nome);
  h+=`<div class="note">${esc(d.explicacao||'')} ${esc(d.ressalva||'')}</div>`;
  return h;
}
export async function renderPPPPref(){
  const d=await J('/api/ppp/triagem');
  let h=cover('prefeitura','PPPs e concessões — triagem de red flags',
    'Lente determinística sobre editais/anexos de PPP da CCPAR: garantia com receita de saúde, aporte público, PMI-captura, prazo, valor vs RCL. O dossiê pericial completo (perícia mestre, íntegras normativas) sai por /ppp no Yoda.','🏗️');
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const r=d.resumo||{};
  h+=`<div class="grid g2">${kpi(fmtN(r.projetos),'Projetos triados',null,'🏗️',
        {sobre:'Parcerias público-privadas e concessões municipais submetidas à triagem. É o denominador: PPP fora desta contagem não foi avaliada, e não avaliar não é aprovar.'})}${kpi(fmtN(r.alto),'Grau ALTO','var(--rose)','🔴',
        {sobre:'Projetos com o conjunto mais forte de sinais — desequilíbrio na matriz de risco, aporte público desproporcional, prazo ou reajuste fora do padrão. Grau é ordem de exame; a perícia de PPP é que conclui.'})}${kpi(fmtN(r.medio),'Grau médio','var(--amber)','🟡',
        {sobre:'Sinais presentes e insuficientes para separar de arranjo contratual legítimo. Fica visível para não empurrar dúvida para dentro do grau alto — faixa que absorve incerteza deixa de significar alguma coisa.'})}${kpi(fmtN(r.cobertura_doe_ppp),'Matérias D.O. PPP',null,'📰',
        {sobre:'Publicações do Diário Oficial sobre PPP que alimentaram a triagem. Cobertura baixa significa triagem parcial — projeto que não teve matéria capturada não foi avaliado.'})}</div>`;
  h+=`<div class="grid" style="margin-top:14px">`+(d.itens||[]).map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">
      <div style="font-weight:700">${esc(x.nome)}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">fase: ${esc(x.fase||'—')} · fonte: ${esc(x.fonte||'—')}</div>
      <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">${(x.flags||[]).map(f=>`<span class="tag ${['garantia_receita_saude','aporte_publico','pmi_privado_ressarcimento'].includes(f)?'rose':'accent'}">${esc(f.replace(/_/g,' '))}</span>`).join('')}</div></div>
      <div class="right"><span class="sev ${(x.grau||'').includes('alto')?'alta':'media'}">${esc(x.grau||'')}</span><div class="dim" style="margin-top:4px">${x.n_altas} flag(s) alta(s)</div></div></div>`,
    (x.grau||'').includes('alto')?'hl':'')).join('')+`</div>`;
  h+=leitura('PPP transfere risco de décadas para o ente público. As três flags vermelhas — garantia com receita da saúde (CF art. 167 IV), aporte público e PMI ressarcida pelo vencedor — são as que a jurisprudência trata como as mais graves.');
  return h;
}
export const _TEMA_ROTULO={transparencia:'transparência',competicao:'competição',conluio:'conluio',fraude_cadastral:'fraude cadastral',preco:'preço',execucao:'execução',certame_ata:'sessão/ata'};
export let _ctrView='analise';
export async function renderContratosPref(){
  const chips=`<div class="chips">
    <button type="button" class="chip ${_ctrView==='analise'?'on':''}" onclick="_ctrView='analise';ir('p_contr')">Com análise (base local)</button>
    <button type="button" class="chip ${_ctrView==='vivo'?'on':''}" onclick="_ctrView='vivo';ir('p_contr')">Publicadas agora (PNCP ao vivo)</button></div>`;
  if(_ctrView==='vivo'){
    const r=await J('/api/pncp?uf=RJ&dias=45&esfera=prefeitura');const its=(r.contratacoes||r.dados||r.itens||[]);
    let h=cover('prefeitura','Contratações recentes (PNCP ao vivo)','Últimas licitações da PREFEITURA DO RIO publicadas no PNCP (esfera oficial do ente). Fonte pública, sem login — pode demorar: é a API nacional ao vivo.','📄')+chips;
    h+=sec('Publicadas (45 dias)',its.length);
    if(!its.length)return h+card('<div class="muted">Sem contratações no período (ou API do PNCP indisponível agora — a visão "Com análise" usa a base local e sempre responde).</div>');
    h+=buscaPag('ctr-list','filtrar por objeto ou órgão…');
    h+=listaPaginada('ctr-list',its,c=>card(`<div style="font-weight:650;font-size:13.5px">${esc(corta(c.objeto||c.objetoCompra||'—',140))}</div><div class="muted" style="font-size:12.5px;margin-top:3px">${esc(corta(c.orgao||c.orgaoNome||c.unidade||'',60))} ${c.valor||c.valorTotal?'· '+fmtRc(c.valor||c.valorTotal):''}</div>`),60);
    return h;
  }
  const d=await J('/api/certames/lista?esfera=prefeitura&limite=600');
  let h=cover('prefeitura','Contratações do município — cada uma com a sua análise','Certames da PREFEITURA DO RIO na base local, cada um com o <b>Índice de Direcionamento</b> (0-100) e os <b>temas</b> (7 famílias: transparência, competição, conluio, fraude cadastral, preço, execução, sessão/ata) onde acendeu sinal. Toque num card para a análise completa das 7 famílias. Certame sem análise = INDISPONÍVEL (≠ 0) — a cobertura cresce com o enxame.','📄')+chips+acoesAba('contratos_analise');
  if(!d.ok)return h+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const its=d.itens||[],rs=d.resumo||{};
  h+=`<div class="grid g2">${kpi(fmtN(rs.total),'Certames na base',null,'📄',
        {sobre:'Certames municipais capturados. É o denominador de tudo nesta aba: certame fora da base não foi considerado regular — não foi visto.'})}${kpi(fmtN(rs.analisados),'Com análise (índice calculado)','var(--amber)','🧮',
        {sobre:'Quantos já passaram pelo motor de índice. A diferença para o total é <b>fila de trabalho</b>, não achado nem ausência dele — e ela encolhe a cada rodada do sweep.'})}</div>`;
  h+=buscaPag('ctr-list','filtrar por objeto ou nº de controle — busca em TODOS os certames…');
  const _montarCtr=c=>{
    const cor=c.faixa==='EXTREMO'||c.faixa==='ALTO'?'var(--rose)':c.faixa==='MEDIO'?'var(--amber)':'var(--tx2)';
    const temas=(c.temas||[]).slice(0,4).map(t=>`<span class="tag ${t.valor>=0.6?'rose':t.valor>=0.3?'amber':'accent'}">${esc(_TEMA_ROTULO[t.familia]||t.familia)} ${(t.valor*100).toFixed(0)}%</span>`).join(' ');
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:650;font-size:13.5px">${esc(corta(c.objeto||'—',140))}</div>
      <div class="muted" style="font-size:12.5px;margin-top:3px">${esc(c.nc)} · ${c.ano||''}${c.valor_estimado?' · estimado '+fmtRc(c.valor_estimado):''}</div>
      ${temas?`<div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">${temas}</div>`:''}</div>
      <div class="right" style="text-align:right">${c.analisado
        ?`<div class="num" style="font-weight:800;font-size:19px;color:${cor}">${c.score.toFixed(0)}</div><div class="dim">${esc(c.faixa||'')} · conf. ${((c.confianca||0)*100).toFixed(0)}%</div>`
        :`<span class="tag" title="nenhuma das 7 famílias era analisável ainda — INDISPONÍVEL, não zero">sem análise</span>`}</div></div>`,
      c.faixa==='EXTREMO'||c.faixa==='ALTO'?'hl':'');
  };
  h+=`<div onclick="const c=event.target.closest('.card');if(!c)return;const nc=c.dataset.nc;if(nc)abrirCertame(nc);">`;
  // listaPaginada não injeta data-attrs — embrulha cada card com o nc pro clique
  const _wrap=c=>_montarCtr(c).replace('<div class="card','<div data-nc="'+esc(c.nc)+'" style="cursor:pointer" class="card');
  h+=listaPaginada('ctr-list',its,_wrap,60,c=>(c.objeto||'').slice(0,70))+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}

// ═══ CONLUIO (esfera-aware; no Transversal tem chips de esfera) ═══
export let _cjEsf='';
export async function renderConluio(esf){
  const d=await J('/api/pncp/conluio'+(esf?'?esfera='+esf:''));
  const rotulos={estado:'órgãos estaduais',prefeitura:'Prefeitura do Rio',municipios:'demais municípios do RJ',federal:'órgãos federais no RJ','':'todas as esferas'};
  const rot=rotulos[esf]??esf;
  if(!d.ok)return sec('Conluio')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const cov=d.cobertura||{},cap=d.captura||[],rod=d.rodizio_vencedores||[],esfs=d.esferas||{};
  let h=cover(esf==='prefeitura'?'prefeitura':esf==='estado'?'estado':'geral','Conluio em licitações · '+rot,
    'Vencedor homologado de cada item (fonte: PNCP, esfera OFICIAL do ente). <b>Captura</b>: uma empresa vence quase tudo num órgão. <b>Rodízio</b>: 2-3 empresas se revezam em compras parecidas. Toque num card para ver o que foi comprado — cada achado explica por que importa.','🕸️')+acoesAba('conluio');
  // chips de esfera (só na visão Transversal, onde a comparação faz sentido)
  if(esfera==='geral'){
    const chip=(id,tl)=>`<button type="button" class="chip ${(_cjEsf===id)?'on':''}" onclick="_cjEsf='${id}';ir('g_conluio')">${tl}${esfs[id]!=null?` <span class="dim">${fmtN(esfs[id])}</span>`:''}</button>`;
    h+=`<div class="chips">${chip('','🌐 Todas')}${chip('estado','🏛️ Estado')}${chip('prefeitura','🏙️ Pref. Rio')}${chip('municipios','🏘️ Municípios')}${chip('federal','🏦 Federais')}</div>`;
  }
  /* `cap` e `rod` são os mesmos arrays que a tela desenha abaixo. `certames_com_resultado` e
     `orgaos` vêm da cobertura do servidor e não têm linhas aqui — ficam sem gaveta. */
  registrarDrill('conluioCapturas',{titulo:'Captura de órgão — 1 empresa vence ≥80%',itens:cap,
    render:c=>card(`<div style="display:flex;justify-content:space-between;gap:10px"><div style="min-width:0"><div style="font-weight:700">${esc(c.orgao_nome||'—')}</div><div class="dim">${esc(c.vencedor_nome||c.vencedor_cnpj||'')}</div></div><div class="right"><div class="num" style="font-weight:800">${Math.round((c.share||0)*100)}%</div><div class="dim">${fmtN(c.itens||c.n||0)} itens</div></div></div>`),
    nota:'Vencedor homologado por item (PNCP). Concentração alta pede explicação, não a substitui.'});
  registrarDrill('conluioRodizios',{titulo:'Rodízio — 2-3 empresas se revezam',itens:rod,
    render:r=>card(`<div><div style="font-weight:700">${esc(r.orgao_nome||'—')}</div><div class="dim">${(r.empresas||[]).map(e=>esc(e.nome||e.cnpj||'')).join(' · ')}</div></div>`)});
  h+=`<div class="grid g2">${kpi(fmtN(cov.certames_com_resultado),'Certames analisados',null,'📄',
        {sobre:'O DENOMINADOR desta tela: certames com resultado publicado, que são os únicos em que se pode saber quem ganhou e quem perdeu. Certame fora daqui não foi afastado — não pôde ser examinado, e confundir as duas coisas transforma lacuna em conclusão.'})}${kpi(fmtN(cov.orgaos),'Órgãos compradores',null,'🏢',
        {sobre:'Quantos órgãos aparecem como compradores no conjunto examinado. Serve para ler a concentração do achado: espalhado por muitos órgãos sugere padrão de mercado; concentrado em um, sugere padrão daquele comprador.'})}${kpi(cap.length,'Capturas','var(--rose)','🎯',{drill:'conluioCapturas'})}${kpi(rod.length,'Rodízios','var(--amber)','🔁',{drill:'conluioRodizios'})}</div>`;
  if(cov.certames_sem_unidade>0)h+=`<div class="warn" style="margin-top:12px"><span>Identificação do órgão comprador em andamento: <b>${fmtN(cov.certames_sem_unidade)}</b> de ${fmtN(cov.certames_com_resultado)} certames ainda aparecem no nome do ente (ex.: "Estado do Rio de Janeiro"). O backfill do PNCP completa isso automaticamente.</span></div>`;
  const orgHead=x=>`<div style="font-weight:700">${esc(x.orgao_nome)}</div>${x.ente_nome&&x.ente_nome!==x.orgao_nome?`<div class="dim" style="margin-top:1px">${esc(x.ente_nome)} · ${esc(x.orgao_cnpj_fmt||'')}</div>`:''}`;
  if(cap.length){h+=`<div style="height:16px"></div>`+sec('Captura de órgão · 1 empresa vence ≥80%',cap.length)+`<div class="grid">`+cap.map(c=>card(
    `<div class="exp" onclick="toggle(this)"><div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0">${orgHead(c)}<div class="muted" style="font-size:13px;margin-top:4px">quem venceu: ${clk(c.fornecedor_cnpj_fmt,c.nome)}</div><div class="dim" style="margin-top:2px">${esc(c.fornecedor_cnpj_fmt)}</div></div>
      <div class="right"><div class="num" style="font-weight:800;color:var(--rose);font-size:20px">${Math.round(c.share*100)}%</div><div class="dim">das vitórias</div></div></div>
      ${leitura(`<b>${esc(c.nome)}</b> venceu ${Math.round(c.share*100)}% dos <b>${c.certames}</b> certames deste órgão (${c.distintos||'—'} concorrentes distintos apareceram no período). Concentração ≥80% é o gatilho OCDE de <b>mercado capturado</b>: pode ser mérito ou mercado raso — o próximo passo é comparar as propostas perdedoras e o QSA dos concorrentes.`)}
      <div class="objs">${(c.objetos||[]).map(o=>`<div class="obj">${esc(o)}</div>`).join('')||'<div class="dim">sem objeto</div>'}</div>
      <div class="dim" style="margin-top:8px"><span class="chev">▸</span> o que foi comprado</div></div>`,'hl')).join('')+`</div>`;}
  if(rod.length){h+=`<div style="height:16px"></div>`+sec('Rodízio de vencedores · revezamento em objeto parecido',rod.length)+`<div class="grid">`+rod.map(r=>{
    const nomes=(r.membros_nome||[]).map(m=>`<b>${esc(m.nome)}</b> (${m.vitorias}×)`).join(' · ');
    return card(
    `<div class="exp" onclick="toggle(this)"><div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0">${orgHead(r)}<div class="muted" style="font-size:13px;margin-top:4px">${r.certames} certames · o grupo levou ${Math.round(r.cobertura_grupo*100)}% deles</div></div>
      <span class="tag amber">${(r.membros_nome||[]).length} empresas</span></div>
      ${r.coesao_objeto!=null?`<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;align-items:center"><span class="tag ${r.coesao_objeto>=0.6?'rose':'teal'}" title="quão parecidos são os objetos dos certames deste grupo">compras ${Math.round(r.coesao_objeto*100)}% parecidas</span>${(r.termos_comuns||[]).slice(0,4).map(t=>`<span class="tag accent">${esc(t)}</span>`).join('')}</div>`:'<div class="dim" style="margin-top:6px">sem objeto comparável (rodízio no nível do órgão)</div>'}
      ${leitura(`${nomes} se revezam nas vitórias de compras ${r.coesao_objeto!=null?`<b>${Math.round(r.coesao_objeto*100)}% parecidas</b>`:'deste órgão'}${(r.termos_comuns||[]).length?` (em comum: ${r.termos_comuns.slice(0,3).map(esc).join(', ')})`:''}. Revezamento equilibrado no MESMO tipo de objeto é o padrão nº 1 de <b>combinação de propostas</b> (OCDE) — verificar QSA, endereços e quem mais participou de cada certame.`)}
      <table style="margin-top:10px"><tbody>${(r.membros_nome||[]).map(m=>`<tr><td>${clk(m.cnpj,m.nome)}<div class="dim">${esc(m.cnpj)}</div></td><td class="num"><b>${m.vitorias}</b> <span class="dim">vitórias</span></td></tr>`).join('')}</tbody></table>
      <div class="objs">${(r.objetos||[]).map(o=>`<div class="obj">${esc(o)}</div>`).join('')||'<div class="dim">sem objeto</div>'}</div>
      <div class="dim" style="margin-top:8px"><span class="chev">▸</span> o que foi comprado</div></div>`);}).join('')+`</div>`;}
  if(!cap.length&&!rod.length)h+=card('<div class="muted">Nenhum padrão de captura ou rodízio com o volume atual desta esfera. A base cresce a cada coleta do PNCP.</div>');
  if(esfera==='geral')h+=`<div style="height:14px"></div>`+card(`<div style="font-weight:700">E quem participa e NUNCA vence?</div><div class="muted" style="font-size:13px;margin-top:3px">As perdedoras contumazes (candidatas a proposta de cobertura) estão em Riscos.</div><div class="btns"><button class="btn ghost" onclick="_riscoView='cover';ir('g_riscos')">Abrir perdedoras</button></div>`);
  h+=`<div class="note">${esc(d.aviso||'')}</div>`;
  return h;
}

// ═══ PERÍCIAS ═══
export let _perOrdem='score',_perGrau='';
export async function renderPericias(){
  const d=await J('/api/pericias?limite=80&ordem='+_perOrdem+(_perGrau?'&grau='+encodeURIComponent(_perGrau):''));
  const it=d.itens||[];
  let h=cover('estado','Perícias de fornecedor','8.648 fornecedores periciados (grau 🟢🟡🔴 + achados). Clique num nome para o dossiê 360.','⚖️');
  h+=`<div class="chips">
    <button type="button" class="chip ${_perGrau===''?'on':''}" onclick="_perGrau='';ir('e_pericias')">Todos</button>
    <button type="button" class="chip ${_perGrau==='🟡'?'on':''}" onclick="_perGrau='🟡';ir('e_pericias')">Atenção</button>
    <button type="button" class="chip ${_perGrau==='🔴'?'on':''}" onclick="_perGrau='🔴';ir('e_pericias')">Grave</button>
    <button type="button" class="chip ${_perOrdem==='total'?'on':''}" onclick="_perOrdem=_perOrdem==='total'?'score':'total';ir('e_pericias')">↕ ${_perOrdem==='total'?'ordenar: R$':'ordenar: score'}</button></div>`;
  h+=`<div class="search"><span class="mag"></span><input placeholder="filtrar por nome ou CNPJ…" oninput="filtrar(this,'#per-list .card')"></div>`;
  h+=`<div id="per-list" class="grid">`+it.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:center"><div style="min-width:0"><div>${clk(x.cnpj,x.favorecido||x.cnpj)}</div>
      <div class="dim">${(x.indicios||0)} indício(s) · ${x.ugs} órgão(s) · ${fmtN(x.n_obs)} OBs</div></div>
      <div class="right"><div style="font-size:18px">${x.grau||'⚪'}</div><div class="dim">${fmtRc(x.total)}</div></div></div>`)).join('')+`</div>`;
  if(!it.length)h+=card('<div class="muted">Nenhum fornecedor casa esse filtro — a busca varre nome, CNPJ e objeto; tente um pedaço do nome ou só os dígitos do CNPJ.</div>');
  return h;
}

// ═══ AUTOCOMPLETE genérico (empresas + nomeados, /api/sugestoes) ═══
export let _acTimer=null,_acItens=[],_acCb=null,_acSelIdx=-1;
export function _acRenderSel(box){[...box.querySelectorAll('.ac-item')].forEach((el,i)=>el.classList.toggle('sel',i===_acSelIdx));}
export function _acPick(i){const it=_acItens[i];if(!it)return;document.querySelectorAll('.ac-box.on').forEach(b=>b.classList.remove('on'));if(_acCb)_acCb(it);}
export function autocompletar(input,boxSel,onPick){
  clearTimeout(_acTimer);
  const box=document.querySelector(boxSel);if(!box)return;
  const q=input.value.trim();_acSelIdx=-1;
  if(q.length<2){box.classList.remove('on');return;}
  _acTimer=setTimeout(async()=>{
    const d=await J('/api/sugestoes?q='+encodeURIComponent(q));
    if(input.value.trim()!==q)return;  // resposta atrasada de digitação antiga — descarta
    const emp=(d.empresas||[]).map(e=>({tipo:'empresa',nome:e.nome,cnpj:e.cnpj,sub:e.cnpj||'',...e}));
    const nom=(d.nomeados||[]).map(n=>({tipo:'nomeado',nome:n.nome,sub:`${n.cargo||''} · ${(n.orgao||'').slice(0,30)} (${n.esfera})`,...n}));
    _acItens=[...emp,...nom];_acCb=onPick;
    if(!_acItens.length){box.classList.remove('on');return;}
    box.innerHTML=_acItens.map((it,i)=>`<div class="ac-item" data-i="${i}" onmousedown="event.preventDefault();_acPick(${i})">${it.tipo==='empresa'?'🏢':'👤'} <b>${esc(it.nome||'')}</b><span class="dim">${esc(it.sub||'')}</span></div>`).join('');
    box.classList.add('on');
  },250);
}
export function acKeydown(ev,input,boxSel,onEnterSemSelecao){
  const box=document.querySelector(boxSel);
  const aberta=!!(box&&box.classList.contains('on'));
  if(ev.key==='Escape'&&aberta){box.classList.remove('on');return;}
  if(aberta&&(ev.key==='ArrowDown'||ev.key==='ArrowUp')){
    ev.preventDefault();
    _acSelIdx=ev.key==='ArrowDown'?Math.min(_acSelIdx+1,_acItens.length-1):Math.max(_acSelIdx-1,0);
    _acRenderSel(box);return;}
  if(ev.key!=='Enter')return;
  /* v55 — CAUSA RAIZ do "Enter não busca" (medida pelo it-campo no navegador: com a lista de
     sugestões aberta, o keydown voltava CANCELADO e o submit do form nunca disparava).
     O v54 consumia TODO Enter aqui para evitar busca dobrada. Consumir sem ter o que escolher
     é engolir: com a lista aberta e NENHUMA sugestão destacada, ninguém sobrava para buscar.
     Regra nova, uma só: só consumo o Enter quando ele tem destino — a sugestão em foco.
     Em qualquer outro caso a lista fecha e o evento SEGUE, e quem busca é a submissão
     implícita do <form> (caminho do próprio navegador, que nenhum handler precisa reproduzir).
     Fora de form não há submit para herdar; aí sim chamo a busca na mão. */
  if(aberta&&_acSelIdx>=0){ev.preventDefault();_acPick(_acSelIdx);return;}
  if(aberta)box.classList.remove('on');
  if(!input.closest('form')){ev.preventDefault();onEnterSemSelecao();}
}
// ═══ BUSCA universal ═══
export let _bq='';
export async function renderBuscar(){
  return cover('geral','Busca universal','Procure por empresa, CNPJ, órgão, contrato ou termo. Clique num resultado para o dossiê 360.','🔎')+
    /* v54: o campo passa a viver dentro de um <form>. Medido pelo it-campo: com "limpeza"
       digitado, o Enter só chamava /api/sugestoes — /api/compliance/buscar NUNCA era
       chamado, e só o clique no botão buscava. Campo de busca solto depende de o
       handler de tecla sobreviver; dentro de um form, o Enter é submissão implícita
       do navegador — funciona mesmo que algum handler acima engula o keydown.
       O acKeydown continua responsável pela lista de sugestões (setas + Enter escolhe
       a que está em foco) e consome o Enter, então o submit não dispara duas vezes. */
    `<form class="busca-uni" role="search" onsubmit="event.preventDefault();fazBusca()">
     <div class="search"><span class="mag"></span><input id="bq" name="q" autocomplete="off" placeholder="nome, CNPJ ou objeto — ex.: engenharia, limpeza, 42498733000148…" value="${esc(_bq)}"
       oninput="autocompletar(this,'#bq-ac',(it)=>{$('bq').value=it.nome;if(it.tipo==='empresa'&&it.cnpj)abrirDossie(it.cnpj,it.nome);else fazBusca();})"
       onkeydown="acKeydown(event,this,'#bq-ac',fazBusca)">
     <div id="bq-ac" class="ac-box"></div></div>
     <div class="btns" style="margin-top:-2px"><button type="submit" class="btn accent">Buscar</button></div>
     </form>
     <div id="bres" style="margin-top:14px">${_bq?spin():'<div class="dim" style="text-align:center;padding:20px">Digite acima e tecle Enter (ou toque em Buscar, ou escolha uma sugestão).</div>'}</div>`;
}
export async function fazBusca(){
  const q=($('bq')||{}).value?.trim()||'';if(!q)return;_bq=q;const box=$('bres');box.innerHTML=spin('Buscando "'+esc(q)+'"…');
  const r=await J('/api/compliance/buscar?q='+encodeURIComponent(q));
  if(r.error){box.innerHTML=card(`<div class="warn">${esc(r.error)}</div>`);return;}
  const forn=r.fornecedores||[],ctr=r.contratos||[],doe=r.doerj||[],alt=r.alertas||[];let h='';
  if(forn.length){h+=sec('Fornecedores',forn.length)+`<div class="grid">`+forn.slice(0,30).map(f=>{const cnpj=(f.cnpj||'').replace(/\D/g,'');
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:center"><div style="min-width:0">${clk(cnpj,f.nome||f.razao_social||cnpj)}<div class="dim">${esc(f.cnpj_fmt||f.cnpj||'')}</div></div>${f.total_pago!=null?`<div class="right"><b>${fmtRc(f.total_pago)}</b><div class="dim">${fmtN(f.n_obs||0)} OBs</div></div>`:''}</div>`);}).join('')+`</div>`;}
  if(ctr.length)h+=`<div style="height:14px"></div>`+sec('Contratos',ctr.length)+`<div class="grid">`+ctr.slice(0,20).map(c=>card(`<div style="font-weight:650;font-size:13.5px">${esc((c.objeto||c.descricao||'contrato')).slice(0,140)}</div><div class="muted" style="font-size:12.5px;margin-top:3px">${esc(c.fornecedor||c.contratado||'')} ${c.valor?'· '+fmtRc(c.valor):''}</div>`)).join('')+`</div>`;
  if(doe.length)h+=`<div style="height:14px"></div>`+sec('Diário Oficial',doe.length)+`<div class="grid">`+doe.slice(0,12).map(x=>card(`<div style="font-size:13px">${esc((x.texto||x.trecho||JSON.stringify(x)).slice(0,220))}</div>`)).join('')+`</div>`;
  if(alt.length)h+=`<div style="height:14px"></div>`+sec('Alertas',alt.length)+`<div class="grid">`+alt.slice(0,12).map(x=>card(`<div style="font-size:13px">${esc(x.titulo||x.tipo||JSON.stringify(x).slice(0,180))}</div>`)).join('')+`</div>`;
  box.innerHTML=h||card('<div class="muted">Nada encontrado. Tente nome parcial, CNPJ ou objeto.</div>');
}

// ═══ PODER / LARANJAS / CARTEL / ALERTAS / SIAFE / SWEEPS / VALIDAR / AÇÕES ═══
export async function renderPoder(){
  const d=await J('/api/poder/nomeados_candidatos?limite=1000');
  if(!d.ok)return sec('Poder')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const it=d.itens||[];
  let h=cover('estado','Nomeados × candidatos (Estado)','Servidor público estadual (folhas: Defensoria/RJ + Câmara Municipal do Rio + TJRJ) que também foi candidato a cargo eletivo, sobretudo cargo em comissão. Cruzamento por nome (verificar homônimo). Os comissionados da PREFEITURA estão na esfera Prefeitura → Comissionados.','🏛️')+acoesAba('nomeados');
  const _linPoder=x=>card(`<div style="display:flex;justify-content:space-between;gap:10px"><div style="min-width:0"><div style="font-weight:700">${esc(x.nome)}</div><div class="dim">${esc(x.orgao||'—')} · ${esc(x.cargo_folha||'—')}</div><div class="dim">disputou ${esc(x.cargo_disputado||'—')} · ${esc(x.partido||'—')} · ${esc(x.ano||'—')}</div></div>${x.comissionado?'<span class="tag rose">comissão</span>':'<span class="tag accent">efetivo</span>'}</div>`);
  registrarDrill('poderCruzamentos',{titulo:'Servidor que também foi candidato',itens:it,render:_linPoder,
    nota:'Cruzamento por NOME — verificar homônimo antes de qualquer juízo.'});
  registrarDrill('poderComissionados',{titulo:'Cruzamentos em cargo COMISSIONADO',itens:it.filter(x=>x.comissionado),render:_linPoder});
  h+=`<div class="grid g2">${kpi(it.length,'Cruzamentos',null,'🏛️',{drill:'poderCruzamentos'})}${kpi(fmtN(it.filter(x=>x.comissionado).length),'Comissionados','var(--rose)','🎖️',{drill:'poderComissionados'})}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por nome, cargo, partido…" oninput="filtrar(this,'#pod-list .card')"></div>`;
  h+=`<div id="pod-list" class="grid">`+it.map(x=>card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0"><div style="font-weight:700">${esc(x.nome)}</div><div class="muted" style="font-size:13px;margin-top:2px">${esc(x.orgao||'—')} · ${esc(x.cargo_folha||'—')}</div></div>${x.comissionado?'<span class="tag rose">comissão</span>':'<span class="tag accent">efetivo</span>'}</div><div class="kv" style="margin-top:8px"><span class="k">Disputou</span><b>${esc(x.cargo_disputado||'—')} · ${esc(x.partido||'—')} · ${esc(x.ano||'—')}</b></div>`)).join('')+`</div>`;
  h+=`<div class="note">${esc(d.aviso||'')}</div>`;return h;
}
export async function renderSocioServidor(){
  const d=await J('/api/intel/socio_servidor?limite=150');
  if(!d.ok)return sec('Servidor-sócio')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Servidor público sócio de fornecedor do Estado',
    'Servidor que aparece nas folhas coletadas e também é sócio de empresa que recebeu do Estado. Servidor <b>administrador/diretor</b> de empresa privada viola a vedação estatutária de gerência; se a empresa contrata com o órgão dele, há impedimento (Lei 14.133 art. 9). <b>Confiança ALTA</b> = nome e fragmento de CPF batem; <b>MÉDIA</b> = só o nome.','🕴️')+acoesAba('socio_servidor');
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Servidores sócios','var(--rose)','🕴️',
        {sobre:'Pessoas que aparecem ao mesmo tempo na folha do Estado e no quadro societário de empresa paga pelo Estado. <b>Estar aqui não é irregularidade</b>: servidor pode ser sócio, e a medição na própria base dá 28%. O que pesa são os recortes ao lado.'})}${kpi(fmtN(d.n_gerencia),'Com gerência (vedada)','var(--rose)','⚖️',
        {sobre:'Sócio com qualificação de <b>administrador, diretor ou gerente</b> — o estatuto do servidor veda o exercício de gerência em empresa privada (art. 117, X da Lei 8.112/1990 e correspondentes estaduais). Aqui a qualificação vem do QSA da Receita, declarada pela própria empresa.'})}
      ${kpi(fmtN(d.n_art9||0),'Art. 9 (mesmo órgão)','var(--rose)','🎯',
        {sobre:'O recorte MAIS GRAVE desta tela: a empresa é paga pela <b>própria repartição</b> onde o sócio serve. É o impedimento direto do art. 9º, III da Lei 8.429/1992 — auferir vantagem de contrato de órgão em que atua. Os demais casos exigem investigar; este já nasce com o vínculo entre o dinheiro e a decisão.'})}${kpi(fmtN(d.n_alta),'Confiança ALTA (CPF)','var(--amber)','🔎',
        {sobre:'Casamento em que <b>nome e fragmento de CPF</b> coincidem, não só o nome. O resto é casamento por nome, que carrega homônimo — por isso a confiança viaja junto do achado, e nenhum caso sobe a relatório sem confirmação do CPF completo pelo órgão de controle.'})}</div>`;
  h+=`<div class="dim" style="margin-top:8px">Folhas cruzadas: ${esc((d.folhas||[]).join(', '))||'—'}. Homônimos descartados por CPF: ${fmtN(d.homonimos_descartados)}. Art. 9 = empresa paga pela própria repartição do servidor (impedimento direto).</div>`;
  h+=`<div class="search" style="margin-top:12px"><span class="mag"></span><input placeholder="filtrar por servidor, empresa, órgão ou cargo…" oninput="filtrar(this,'#ss-list .card')"></div>`;
  h+=`<div id="ss-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:700">${esc(x.socio)} ${x.mesmo_orgao?'<span class="tag rose">art. 9 · mesmo órgão</span>':x.gerencia?'<span class="tag rose">gerência</span>':'<span class="tag amber">sócio</span>'}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">${esc(x.qualificacao)} de ${clk(x.cnpj,x.empresa)}</div>
      <div class="dim" style="margin-top:2px">servidor: ${esc(x.servidor_cargo||'—')} · ${esc((x.servidor_orgao||'').slice(0,40))} · ${esc(x.vinculo||'')}</div>
      ${(x.ugs_pagadoras||[]).length&&x.ugs_pagadoras[0].nome?`<div class="dim" style="margin-top:2px">paga por: ${(x.ugs_pagadoras||[]).filter(u=>u.nome).map(u=>esc(u.nome)+' ('+fmtRc(u.valor)+')').join(' · ')}</div>`:''}</div>
      <div class="right"><span class="tag ${x.confianca==='ALTA'?'rose':'accent'}">${esc(x.confianca)}</span>
      <div class="num" style="margin-top:6px;font-weight:800">${fmtRc(x.total_pago)}</div><div class="dim">recebido · ${fmtN(x.n_obs)} OBs</div></div></div>
      ${leitura(`<b>${esc(x.socio)}</b> é <b>${esc(x.qualificacao)}</b> da empresa <b>${esc(x.empresa)}</b> (recebeu ${fmtRc(x.total_pago)} do Estado) e consta na folha como <b>${esc(x.servidor_cargo||'servidor')}</b> ${esc(x.servidor_orgao?('do '+x.servidor_orgao):'')}.${x.mesmo_orgao?' <b>A empresa é paga pela PRÓPRIA repartição do servidor — impedimento direto do art. 9.</b>':x.gerencia?' Cargo de gerência em empresa privada é vedado ao servidor (estatuto).':''} ${x.confianca==='ALTA'?'Nome e fragmento de CPF coincidem.':'Casamento por nome — confirmar CPF.'}`)}`,
    x.mesmo_orgao||x.confianca==='ALTA'||x.gerencia?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}
// ═══ FORNECEDOR DEPENDENTE / CATIVO ═══
export async function renderCapital(){
  const d=await J('/api/intel/capital_incompativel?limite=150');
  if(!d.ok)return sec('Capital irrisório')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Capital irrisório — sem lastro para o que faturou','Empresa com <b>capital social ínfimo</b> (&lt; R$50 mil) que recebeu do Estado <b>≥100× o próprio capital</b> (e mais de R$1 mi). Subcapitalização crônica frente ao volume faturado é indício de <b>fachada/interposição</b> — falta capacidade econômico-financeira para executar contratos vultosos (Lei 14.133 art. 5º, 62-63). Capital: dump da Receita.','🫧')+acoesAba('capital_incompativel');
  registrarDrill('capitalIrrisorio',{titulo:'Empresas com capital social de até R$ 1.000',itens:a.filter(x=>x.capital<=1000),nota:'Capital irrisório frente ao recebido é indício de fachada, não prova.'});
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Empresas','var(--rose)','🫧',
        {sobre:'Empresas cujo <b>capital social declarado</b> é pequeno diante do que receberam do Estado. Capital baixo é lícito e comum — mede o que a empresa declarou à Junta, não a capacidade real, que também vem de faturamento e crédito. O sinal serve para perguntar se havia estrutura para executar, não para afirmar que não havia.'})}${kpi(a.length?fmtN(a[0].razao)+'×':'—','Pior razão (recebido/capital)','var(--rose)',null,
        {sobre:'O extremo da lista: quantas vezes o recebido supera o capital declarado. Razão altíssima com capital de R$ 1.000 é o perfil clássico de empresa aberta para o contrato — mas também aparece em prestadora de serviço que não precisa de imobilizado. Por isso é ordem de diligência, não conclusão.'})}
      ${kpi(fmtRc(a.reduce((s,x)=>s+(x.total_recebido||0),0)),'Volume recebido',null,'💰',
        {sobre:'Soma paga às empresas desta página. Volume dimensiona o que está sob exame; não afirma nada sobre a regularidade do pagamento.'})}${kpi(a.filter(x=>x.capital<=1000).length,'Capital ≤ R$1k','var(--amber)','⚠️',{drill:'capitalIrrisorio'})}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por empresa…" oninput="filtrar(this,'#cap-list .card')"></div>`;
  h+=`<div id="cap-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">${clk(x.cnpj,x.nome||x.cnpj_fmt)}<div class="dim">${esc(x.cnpj_fmt)} · ${fmtN(x.n_obs)} OBs</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:var(--rose)">${fmtN(x.razao)}×</div><div class="dim">o capital</div></div></div>
      <div class="kv" style="margin-top:8px"><span class="k">capital <b>${fmtR(x.capital)}</b></span><b>recebeu ${fmtRc(x.total_recebido)}</b></div>
      ${leitura(`<b>${esc(x.nome)}</b> tem capital social de apenas <b>${fmtR(x.capital)}</b> mas recebeu <b>${fmtRc(x.total_recebido)}</b> do Estado — <b>${fmtN(x.razao)}× o próprio capital</b>. Capital irrisório frente ao volume faturado é indício de subcapitalização/fachada. Confirmar o capital ATUAL (o dump é de um mês) e a capacidade econômico-financeira.`)}`,
    x.razao>=1000?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;
  return h;
}
export async function renderPrioridade(){
  const d=await J('/api/intel/prioridade_valor?limite=80');
  if(!d.ok)return sec('Prioridade por valor em risco')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Prioridade — onde a auditoria rende mais','Fila que cruza <b>risco × dinheiro</b>: fornecedores que o <b>radar</b> já marca (sinal aceso) <b>E</b> que têm <b>economia recuperável</b> (pagaram acima da mediana de mercado do item). Risco alto sem dinheiro pode esperar; dinheiro alto sem sinal pode ser variação legítima — o cruzamento dos dois no mesmo CNPJ é a fila que rende mais por hora de apuração.','⚡')+acoesAba('prioridade_valor');
  registrarDrill('sinalMedioMais',{titulo:'Com sinal médio ou alto (score ≥ 25)',itens:a.filter(x=>x.score>=25),nota:''});
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Na interseção','var(--teal)','⚡',drillSeCompleto('prioridadeTodos',d.n,a,{titulo:'Risco × dinheiro — a interseção',nota:'Risco alto sem dinheiro pode esperar; dinheiro sem sinal pode ser variação legítima. A fila é o cruzamento dos dois.'})
        ||{sobre:'A interseção entre risco e dinheiro: risco alto sem valor pode esperar, valor alto sem sinal pode ser só volume. A gaveta está desligada porque a tela recebe uma página do total do servidor.'})}${kpi(fmtRc(d.economia_em_risco),'Economia em risco',null,'💰',
        {sobre:'Soma da economia potencial estimada na interseção risco × dinheiro. É estimativa de comparação de preço, não dano apurado — e depende de os itens comparados serem realmente equivalentes.'})}
      ${kpi(a.filter(x=>x.score>=25).length,'Sinal médio+ (🟡🔴)','var(--amber)',null,{drill:'sinalMedioMais'})}${kpi(a.length?fmtRc(a[0].economia):'—','Maior isolado','var(--rose)',null,
        {sobre:'O maior valor único da interseção risco × dinheiro. É <b>economia potencial estimada</b>, não dano apurado: nasce de comparação de preço, e comparação só vale entre produtos equivalentes — 60% de uma estimativa anterior desta casa comparava itens diferentes sob descrição genérica.'})}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por empresa ou sinal…" oninput="filtrar(this,'#pri-list .card')"></div>`;
  h+=`<div id="pri-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">${clk(x.cnpj,x.nome||x.cnpj_fmt)}<div class="dim">${esc(x.cnpj_fmt)} · ${fmtN(x.n_compras)} compra(s) acima da mediana</div>
      <div style="margin-top:6px;display:flex;gap:5px;flex-wrap:wrap">${(x.sinais||[]).slice(0,4).map(s=>`<span class="tag teal">${rot(s)}</span>`).join('')}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:var(--teal)">${fmtRc(x.economia)}</div><div class="dim">${x.rating} score ${fmtN(x.score)}</div></div></div>
      ${leitura(`<b>${esc(x.nome)}</b> junta <b>sinal de risco</b> (${(x.sinais||[]).map(rot).join(', ')||'—'}, score ${fmtN(x.score)}/100) com <b>${fmtRc(x.economia)}</b> de sobrepreço recuperável sobre ${fmtN(x.n_compras)} compra(s) acima da mediana de mercado. Priorizar: risco + dinheiro no mesmo fornecedor. Economia é teto teórico (mediana atingível), não valor a ressarcir.`)}`,
    x.score>=50?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.escala||'')} — ${esc(d.ressalva||'')}</div>`;
  return h;
}
export async function renderFornecedorDependente(){
  const d=await J('/api/intel/fornecedor_dependente?limite=150');
  if(!d.ok)return sec('Cativos')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Fornecedor cativo — "empresa do órgão"','Empresa comercial que recebe <b>quase tudo (≥90%)</b> de UMA única unidade gestora do Estado. Dependência total de um comprador é o perfil de fornecedor cativo — mercado fechado, risco de direcionamento.','🔗')+acoesAba('fornecedor_dependente');
  registrarDrill('dep100Orgao',{titulo:'Fornecedores que faturam ~100% com um único órgão',itens:a.filter(x=>x.share>=0.99),nota:'Dependência total de um comprador é indício de captura — cabe verificar o objeto.'});
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Fornecedores cativos','var(--amber)','🔗',
        {sobre:'Empresas cuja receita pública vem quase toda de <b>um único órgão</b>. Dependência não é irregularidade — pode ser especialização legítima. O que ela mede é a assimetria: fornecedor que só vive daquele comprador tem pouco incentivo para contestar, e o comprador ganha poder que não está em contrato nenhum.'})}${kpi(fmtRc(a.reduce((s,x)=>s+x.total,0)),'Volume dependente',null,'💰',
        {sobre:'Soma recebida pelos fornecedores <b>desta página</b>, não do acervo. Volume não é dano: dimensiona o que está sob concentração, e nada aqui afirma pagamento indevido.'})}
      ${kpi(a.filter(x=>x.share>=0.99).length,'100% de 1 órgão','var(--rose)','🎯',{drill:'dep100Orgao'})}${kpi(a.length?Math.round(a[0].share*100)+'%':'—','Maior dependência',null,null,
        {sobre:'A maior fração da receita pública de um fornecedor vinda de um só órgão. Dependência não é irregularidade: mede assimetria de poder na relação, que é o que pode explicar preço sem contestação.'})}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por empresa ou UG…" oninput="filtrar(this,'#dep-list .card')"></div>`;
  h+=`<div id="dep-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">${clk(x.cnpj,x.nome||x.cnpj_fmt)}<div class="dim">${esc(x.cnpj_fmt)}</div>
      <div class="muted" style="font-size:12.5px;margin-top:3px">UG ${esc(String(x.ug))} ${esc(x.ug_nome||'')} · aparece em ${x.n_ugs} órgão(s)</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:${x.share>=0.99?'var(--rose)':'var(--amber)'}">${Math.round(x.share*100)}%</div><div class="dim">de ${fmtRc(x.total)}</div></div></div>
      ${leitura(`<b>${esc(x.nome)}</b> recebeu <b>${Math.round(x.share*100)}%</b> de tudo (${fmtRc(x.total)}) da UG ${esc(String(x.ug))} ${esc(x.ug_nome||'')}. Empresa comercial dependente de um só comprador é o perfil de fornecedor cativo — checar o histórico de licitações desse órgão.`)}`,
    x.share>=0.99?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

// ═══ CORRIDA DE DEZEMBRO ═══
export async function renderCorridaDezembro(){
  const d=await J('/api/intel/corrida_dezembro?limite=150');
  if(!d.ok)return sec('Dezembro')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Corrida do empenho de dezembro','Fornecedor comercial que recebeu <b>a maior parte do ano em dezembro</b> (≥75%). Concentração no fim do exercício é red-flag de "corrida do empenho" — verba usada às pressas antes de perder o orçamento, terreno fértil para dispensa e direcionamento.','📅')+acoesAba('corrida_dezembro');
  registrarDrill('dez100',{titulo:'Fornecedores com ~100% do faturamento em dezembro',itens:a.filter(x=>x.share>=0.99),nota:'Concentração no fim do exercício pede exame do empenho e da entrega.'});
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Fornecedores concentrados','var(--amber)','📅',
        {sobre:'Fornecedores com parcela desproporcional do ano recebida em <b>dezembro</b>. O padrão tem explicação inocente forte — encerramento do exercício financeiro empurra liquidação e pagamento para o fim do ano. O que o sinal pede é olhar se houve entrega correspondente, não presumir que não houve.'})}${kpi(fmtRc(a.reduce((s,x)=>s+x.dezembro,0)),'Pago em dezembro',null,'💰',
        {sobre:'Ordens bancárias emitidas em dezembro para os fornecedores desta página. Fonte: OB do SIAFE — pagamento efetivo. Empenho concentrado em dezembro é rotina orçamentária; <b>pagamento</b> concentrado é que levanta a pergunta sobre a data da entrega.'})}
      ${kpi(a.filter(x=>x.share>=0.99).length,'100% em dezembro','var(--rose)','🎯',{drill:'dez100'})}${kpi(a.length?Math.round(a[0].share*100)+'%':'—','Maior concentração',null,null,
        {sobre:'A maior parcela do ano paga em dezembro a um único fornecedor. Encerramento de exercício explica boa parte do padrão; o que resta a perguntar é a data da entrega.'})}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por empresa…" oninput="filtrar(this,'#dez-list .card')"></div>`;
  h+=`<div id="dez-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">${clk(x.cnpj,x.nome||x.cnpj_fmt)}<div class="dim">${esc(x.cnpj_fmt)} · ${fmtN(x.n_obs)} OBs</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:${x.share>=0.99?'var(--rose)':'var(--amber)'}">${Math.round(x.share*100)}%</div><div class="dim">em dezembro</div></div></div>
      <div class="kv" style="margin-top:8px"><span class="k">${fmtRc(x.dezembro)} em dezembro</span><b>de ${fmtRc(x.total)} no ano</b></div>
      ${leitura(`<b>${esc(x.nome)}</b> recebeu <b>${Math.round(x.share*100)}%</b> do valor do ano (${fmtRc(x.total)}) só em dezembro. Concentração no fim do exercício sugere corrida do empenho — verificar se houve planejamento ou uso apressado da verba.`)}`,
    x.share>=0.99?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

// ═══ RADAR DE RISCO (score composto) ═══
export async function renderRadar(){
  const d=await J('/api/intel/radar?limite=150');
  if(!d.ok)return sec('Radar')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Radar de risco — todos os detectores somados','Score <b>0-100</b> por fornecedor somando sinais independentes de todos os detectores (conluio societário, sanção à época, fantasma, servidor-sócio, perdedora contumaz, fênix). Um detector isolado é indício fraco; <b>vários acesos no mesmo CNPJ raramente são coincidência</b> — esta é a fila de apuração priorizada.','🎯')+acoesAba('radar_risco');
  // a cor era 'var(--rose)' FIXA: com zero críticos o painel mostrava "0" em vermelho
  // com triângulo de alerta — boa notícia vestida de alarme, e o oposto de "coisas
  // graves brilham graves" (se tudo grita, nada grita). A cor segue o número contra
  // o limiar que a própria escala declara; abaixo dele, neutro e sem ícone.
  const _nVerm=Number(d.n_vermelho||0), _maior=a.length?Number(a[0].score):null;
  registrarDrill('tresSinais',{titulo:'Com três ou mais sinais acumulados',itens:a.filter(x=>x.n_sinais>=3),nota:''});
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Fornecedores com sinal',null,null,
        {sobre:'Fornecedores com ao menos um indício acionado no conjunto de detectores. Ter sinal é comum e não classifica ninguém: o que ordena a fila é o <b>score</b>, e mesmo ele é indício interno da casa, jamais juízo sobre a empresa.'})}${kpi(fmtN(_nVerm),'Score ≥50 (crítico)',_nVerm>0?'var(--rose)':null,null,
        {sobre:'Corte de 50 na escala interna. O número que ele produz depende dos detectores ligados no dia — quando sete famílias foram corrigidas por leitura defeituosa, esta faixa caiu sozinha. Score é da CASA, não da empresa: mede quanto material há para examinar.'})}
      ${kpi(_maior!=null?_maior:'—','Maior score',_maior!=null&&_maior>=50?'var(--rose)':null,null,
        {sobre:'O maior valor da escala interna de risco. Score é da CASA, não da empresa: mede quanto material há para examinar, e muda quando os detectores mudam.'})}${kpi(a.filter(x=>x.n_sinais>=3).length,'Com ≥3 sinais',null,null,{drill:'tresSinais'})}</div>`;
  h+=`<div class="dim" style="margin-top:8px">${esc(d.escala||'').replace(/\b([a-z]+_[a-z_]+)\b/g,m=>rot(m))}</div>`;
  h+=`<div class="search" style="margin-top:12px"><input placeholder="filtrar por empresa ou sinal…" oninput="filtrar(this,'#radar-tbl tbody tr')"></div>`;
  h+=`<div class="card" style="padding:4px 15px;overflow-x:auto"><table id="radar-tbl"><thead><tr><th>Fornecedor</th><th style="text-align:left">Sinais que dispararam</th><th class="right">Nº</th><th class="right">Score</th></tr></thead><tbody>`+
    a.map(x=>`<tr><td style="min-width:180px">${clk(x.cnpj,x.nome||x.cnpj_fmt)}<div class="dim mono" style="font-size:11px">${esc(x.cnpj_fmt)}</div></td>
      <td style="text-align:left;max-width:520px" title="${esc((x.sinais||[]).map(s=>rot(s.sinal)+(s.detalhe?' — '+s.detalhe:'')).join(' · '))}">${(x.sinais||[]).map(s=>`<span class="tag ${s.peso>=25?'rose':'amber'}">${rot(s.sinal)} +${s.peso}</span>`).join('')}</td>
      <td class="num">${x.n_sinais}</td>
      <td style="white-space:nowrap"><span class="meter ${x.score>=50?'crit':''}"><i style="width:${Math.min(100,x.score)}%"></i></span><b class="num" style="color:${x.score>=50?'var(--rose)':'var(--amber)'}">${x.score}</b></td></tr>`).join('')+
    `</tbody></table></div>`;
  h+=`<div class="note">${esc(d.ressalva||'')} Score sempre acompanhado das regras que o dispararam — clique no nome para a trilha completa no dossiê.</div>`;return h;
}

// ═══ CONLUIO DIRETO (vencedor × perdedora × QSA) ═══
export async function renderConluioQSA(){
  const d=await J('/api/intel/conluio_qsa');
  if(!d.ok)return sec('Conluio QSA')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.pares||[];const cob=d.cobertura||{};
  let h=cover('geral','Conluio direto — vencedor × perdedora do mesmo dono','Vencedor e perdedora do <b>MESMO certame</b> com <b>sócio em comum</b> no QSA da Receita (ou matriz×filial "concorrendo" entre si). A perdedora do mesmo dono existe para dar aparência de disputa — <b>proposta de cobertura</b> (OCDE bid rigging; art. 337-F do CP). Fontes: resultados PNCP + atas de julgamento do corpus.','🤝')+acoesAba('conluio_qsa');
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Pares vencedor×perdedora','var(--rose)','🤝',
        {sobre:'Pares em que quem venceu e quem perdeu o mesmo certame têm sócio em comum — ou são a mesma empresa em filiais diferentes. É o teste clássico de <b>concorrência fingida</b> (art. 337-F do Código Penal). Grupo econômico é lícito; disputar contra si mesmo não é.'})}${kpi(fmtN(d.n_forte||0),'Fortes (QSA/matriz-filial)','var(--rose)','🚨',
        {sobre:'O recorte em que o vínculo é <b>documental</b>, não inferido: mesma raiz de CNPJ (matriz e filial) ou sócio comum no QSA da Receita. Os demais pares dependem de casamento por nome e pedem confirmação de CPF antes de qualquer citação.'})}
      ${kpi(fmtN(cob.certames_com_perdedora||0),'Certames com perdedora conhecida',null,'⚖️',
        {sobre:'O DENOMINADOR: só entra certame cuja ata registra quem perdeu. A maioria das atas publica apenas o vencedor — e sem a perdedora não há par a testar. Este número diz o tamanho real do que pôde ser examinado.'})}${kpi(fmtN(cob.pares_sem_qsa||0),'Pares sem QSA local (INDISPONÍVEL ≠ 0)','var(--amber)','❓',
        {sobre:'Pares que existiam e <b>não puderam ser testados</b> por falta de quadro societário na base local. Não foram afastados — ficam contados aqui exatamente para não serem lidos como ausência de conluio. Cada QSA que a coleta traz reduz este número e pode aumentar o de achados.'})}</div>`;
  h+=`<div class="search" style="margin-top:12px"><span class="mag"></span><input placeholder="filtrar por empresa ou sócio…" oninput="filtrar(this,'#cq-list .card')"></div>`;
  h+=`<div id="cq-list" class="grid">`+a.map(x=>{
    const socios=(x.socios_comuns||[]).map(s=>esc(s.nome)).slice(0,3).join(', ')||'matriz × filial (mesmo CNPJ-raiz)';
    const tcls=x.tier==='MEDIA'?'amber':'rose';
    return card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">
      <div style="font-weight:700">${clk(x.vencedor.cnpj,x.vencedor.nome)} <span class="dim">venceu</span></div>
      <div style="font-weight:700">${clk(x.perdedora.cnpj,x.perdedora.nome)} <span class="dim">perdeu</span></div>
      <div class="muted" style="font-size:12.5px;margin-top:4px"><span class="tag ${tcls}">${esc(x.tier)}</span> sócio(s) em comum: ${socios}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:var(--rose)">${x.n_certames}</div><div class="dim">certame(s) · ${fmtRc(x.valor_vencido)}</div></div></div>
      ${leitura(`<b>${esc(x.vencedor.nome)}</b> venceu ${x.n_certames} certame(s) (${fmtRc(x.valor_vencido)}) em que <b>${esc(x.perdedora.nome)}</b> — ${x.tier==='MESMA_EMPRESA'?'a PRÓPRIA empresa (outra filial)':'empresa com sócio em comum'} — aparecia como concorrente. Disputa de fachada: o dono ganha dos dois lados. Confirmar CPF completo do sócio antes de citar.`)}`,
    x.tier!=='MEDIA'?'hl':'');}).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

// ═══ COMUNIDADES (Louvain) ═══
export async function renderComunidades(){
  const d=await J('/api/intel/comunidades');
  if(!d.ok)return sec('Comunidades')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.comunidades||[];const g=d.grafo||{};
  let h=cover('geral','Comunidades — clusters família-empresa-órgão (Louvain)','Algoritmo de comunidades (Louvain) sobre o grafo de <b>sócios (QSA), disputas em comum e dinheiro dos mesmos órgãos</b>. O cluster denso pessoa+empresa+órgão é o desenho clássico do grupo econômico oculto atrás de licitações. Score 0-100 por sinais objetivos dentro do cluster.','🧩')+acoesAba('comunidades',`<a class="btn ghost" style="flex:0 0 auto;min-width:150px" href="/graph?fonte=comunidades" target="_blank">Grafo das comunidades</a>`);
  // mesmo conserto do radar: zero cluster crítico não é alarme (cor e 🚨 eram fixos)
  const _nCrit=a.filter(x=>x.score>=50).length;
  registrarDrill('comunidadesCriticas',{titulo:'Comunidades com score ≥ 50',itens:a.filter(x=>x.score>=50),nota:'Zero comunidade crítica NÃO é alarme — a cor e o glifo já foram fixos aqui uma vez.'});
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Comunidades relevantes','var(--amber)','🧩',drillSeCompleto('comunidadesTodas',d.n,a,{titulo:'Comunidades detectadas no grafo',nota:'Comunidade é agrupamento por densidade de vínculo — indício de grupo, não prova de grupo econômico.'})
        ||{sobre:'Agrupamentos por densidade de vínculo no grafo. Comunidade é indício de <b>grupo</b>, não de conluio — família, holding e sócios recorrentes produzem o mesmo desenho. A gaveta está desligada porque a lista vem paginada.'})}${kpi(fmtN(_nCrit),'Score ≥50 (🔴)',_nCrit>0?'var(--rose)':null,_nCrit>0?'🚨':'',{drill:'comunidadesCriticas'})}
      ${kpi(fmtN(g.nos||0),'Nós no grafo',null,'🕸️',
        {sobre:'Pessoas e empresas persistidas no grafo de vínculos. O grafo cresce a cada varredura — comunidade que não aparece hoje pode aparecer amanhã, e por isso ausência aqui nunca é afastamento.'})}${kpi(fmtN(g.arestas||0),'Arestas',null,'🔗',
        {sobre:'Ligações gravadas entre esses nós, cada uma com tipo, força e fonte. Tipos simétricos (mesmo telefone, mesmo e-mail) são gravados em <b>direção canônica</b> para não contar a mesma ligação duas vezes.'})}</div>`;
  h+=`<div class="dim" style="margin-top:8px">${esc(d.escala||'').replace(/\b([a-z]+_[a-z_]+)\b/g,m=>rot(m))}</div>`;
  h+=`<div class="search" style="margin-top:12px"><span class="mag"></span><input placeholder="filtrar por empresa, pessoa ou órgão…" oninput="filtrar(this,'#com-list .card')"></div>`;
  h+=`<div id="com-list" class="grid">`+a.map(x=>{
    const emp=(x.membros||[]).filter(m=>m.tipo==='empresa').slice(0,4).map(m=>esc(m.label));
    const pes=(x.membros||[]).filter(m=>m.tipo==='pessoa').slice(0,3).map(m=>esc(m.label));
    const org=(x.membros||[]).filter(m=>m.tipo==='orgao').slice(0,2).map(m=>esc(m.label));
    return card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">
      <div style="font-weight:700">${x.rating} Comunidade #${x.id} · ${x.n_empresas} empresa(s), ${x.n_pessoas} pessoa(s), ${x.n_orgaos} órgão(s)</div>
      <div class="muted" style="font-size:12.5px;margin-top:3px">${emp.join(' · ')||'—'}</div>
      <div class="muted" style="font-size:12.5px">${pes.join(' · ')||'—'} &nbsp; 🏛️ ${org.join(' · ')||'—'}</div>
      <div class="muted" style="font-size:12.5px;margin-top:4px">${(x.sinais||[]).map(s=>`<span class="tag ${s.peso>=20?'rose':'amber'}">${esc(s.sinal)} +${s.peso}</span>`).join(' ')}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:22px;color:${x.score>=50?'var(--rose)':'var(--amber)'}">${x.score}</div><div class="dim">${fmtRc(x.valor_total)}</div></div></div>
      ${leitura(`Cluster com <b>${x.n_empresas}</b> empresa(s) e <b>${x.n_pessoas}</b> pessoa(s) movimentando <b>${fmtRc(x.valor_total)}</b>${(x.sinais||[]).length?', com sinais: '+esc(x.sinais.map(s=>s.sinal+(s.detalhe?' ('+s.detalhe+')':'')).join('; ')):''}. Densidade ${x.densidade}. Mapa de onde olhar — não prova de conluio.`)}`,
    x.score>=50?'hl':'');}).join('')+`</div>`;
  if(d.articuladores&&d.articuladores.length){
    h+=sec('Articuladores (pontes entre grupos)')+`<div class="grid">`+d.articuladores.slice(0,10).map(x=>card(
      `<div style="display:flex;justify-content:space-between;gap:10px"><div><b>${esc(x.label)}</b> <span class="dim">${esc(x.tipo)}</span></div>
       <div class="right"><span class="num">${x.grau}</span> <span class="dim">conexões</span></div></div>`)).join('')+`</div>`;}
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

// ═══ RETRO-AUDITORIA (hindsight) ═══
export async function renderRetro(){
  const d=await J('/api/intel/retro');
  if(!d.ok)return sec('Retro')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const ps=d.por_sinal||{};const ex=d.exemplos||[];const j=d.janela||{};
  const nsin=Object.values(ps).reduce((s,x)=>s+x.n_sinais,0);
  const ncor=Object.values(ps).reduce((s,x)=>s+x.n_sancao_depois,0);
  const pago=Object.values(ps).reduce((s,x)=>s+x.pago_depois,0);
  let h=cover('geral','Retro-auditoria — o que aconteceu DEPOIS do alerta','Para cada detector, o <b>ledger de sinais</b> guarda a data do 1º alerta por empresa (nunca regravada). Aqui medimos o que veio depois: <b>sanção federal posterior</b> (corroboração independente do detector) e <b>R$ que o Estado continuou pagando após o alerta</b> — o custo da inação. A janela cresce todo dia com o timer.','🔮')+acoesAba('retro');
  h+=`<div class="grid g2">${kpi(fmtN(nsin),'Sinais no ledger','var(--amber)','📒',
        {sobre:'Sinais que o motor registrou com <b>data</b>, para poder ser cobrado depois. Sem esse registro não há retroteste possível: detector que só olha o presente nunca descobre se acertou.'})}${kpi(fmtN(ncor),'Sanção DEPOIS do sinal','var(--rose)','⚖️',
        {sobre:'Casos em que o motor apontou a empresa ANTES de ela ser sancionada por outro órgão. É a única medida honesta de <b>poder preditivo</b> desta casa — e foi medindo assim que dois detectores se revelaram anti-preditivos e saíram da régua.'})}
      ${kpi(fmtRc(pago),'Pago APÓS o alerta','var(--rose)','💸',
        {sobre:'Dinheiro que continuou saindo depois de o sinal existir. Não afirma que o pagamento era indevido — afirma que houve <b>tempo e informação</b> para olhar antes, que é exatamente o que o controle externo cobra.'})}${kpi((j.sinal_mais_antigo_dias??'—')+'d','Idade do sinal mais antigo',null,'📅',
        {sobre:'Há quantos dias o registro mais antigo espera confirmação. Ledger novo não pode ser lido como "detector sem acerto": sem tempo decorrido, a ausência de confirmação mede a idade do ledger, não a qualidade do sinal.'})}</div>`;
  h+=`<div class="dim" style="margin-top:8px">Janela retro de ${j.sinal_mais_antigo_dias??'—'} dia(s) — zeros são esperados no começo (sanção demora); a leitura fica forte com semanas de ledger.</div>`;
  h+=sec('Por detector')+`<div class="grid">`+Object.entries(ps).map(([s,v])=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px"><div><b>${esc(s)}</b>
      <div class="muted" style="font-size:12.5px;margin-top:3px">${fmtN(v.n_sinais)} empresa(s) sinalizadas · ${fmtN(v.vitorias_depois)} vitória(s) PNCP depois</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:${v.n_sancao_depois?'var(--rose)':'var(--amber)'}">${v.n_sancao_depois}</div><div class="dim">sanção depois · ${fmtRc(v.pago_depois)} pago depois</div></div></div>`)).join('')+`</div>`;
  if(ex.length){h+=sec('Casos (sanção posterior ou pagamento pós-alerta)')+`<div class="grid">`+ex.slice(0,20).map(e=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px"><div style="min-width:0">${clk(e.cnpj,e.cnpj)}
      <div class="muted" style="font-size:12.5px">[${esc(e.sinal)}] desde ${esc(e.desde)} · ${esc(e.detalhe||'')}</div>
      ${e.sancao_depois?`<div class="muted" style="font-size:12.5px;margin-top:2px"><span class="tag rose">sancionada em ${esc(e.sancao_depois.data_inicio)}</span> ${esc(e.sancao_depois.cadastro||'')}</div>`:''}</div>
      <div class="right"><div class="num" style="font-weight:800;color:var(--rose)">${fmtRc(e.pago_depois)}</div><div class="dim">pago após o alerta</div></div></div>`,
    e.sancao_depois?'hl':'')).join('')+`</div>`;}
  h+=await _liftBloco();
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

// bloco de LIFT: valida cada detector contra o gabarito objetivo (sanções)
export async function _liftBloco(){
  const d=await J('/api/intel/lift');
  if(!d.ok)return '';
  const det=d.detectores||[];
  const barra=(l,circ)=>{const w=Math.min(100,(l||0)/15*100);const col=circ?'var(--muted)':(l>=2?'var(--rose)':(l>=1?'var(--amber)':'var(--green,var(--green))'));
    return `<div style="background:rgba(255,255,255,.06);border-radius:4px;height:8px;overflow:hidden"><div style="width:${w}%;height:100%;background:${col}"></div></div>`;};
  let h=sec('Validação contra o gabarito objetivo (sanções) — lift por detector');
  h+=`<div class="dim" style="margin-bottom:8px">Taxa-base do universo: <b>${fmtD(d.taxa_base*100,1)}%</b> dos ${fmtN(d.universo)} fornecedores são sancionados. <b>Lift</b> = quantas vezes o detector concentra sancionados acima disso. <b>lift ≥ 2</b> = sinal forte · <b>~1</b> = ruído · <b>&lt; 1</b> = anti-sinal · <span class="dim">circular</span> = usa sanção como input (não é corroboração independente).</div>`;
  h+=`<div class="grid">`+det.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:12px;align-items:center">
      <div style="min-width:0;flex:1"><div style="font-weight:700">${rot(x.detector)} ${x.circular?'<span class="tag" style="opacity:.6">circular</span>':''}${x.n_pequeno?'<span class="tag amber">n<10</span>':''}</div>
      <div class="muted" style="font-size:12.5px;margin:3px 0">${x.sancionados}/${x.n} marcados são sancionados (${fmtD(x.taxa*100,1)}%)</div>
      ${barra(x.lift,x.circular)}</div>
      <div class="right"><div class="num" style="font-weight:800;font-size:22px;color:${x.circular?'var(--muted)':(x.lift>=2?'var(--rose)':(x.lift>=1?'var(--amber)':'var(--green)'))}">${fmtN(x.lift)}×</div><div class="dim">lift</div></div></div>`)).join('')+`</div>`;
  return h;
}

// ═══ SÓCIO OCULTO ═══
export async function renderSocioOculto(){
  const d=await J('/api/intel/socio_oculto?limite=150');
  if(!d.ok)return sec('Sócio oculto')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Sócio oculto — um dono, vários fornecedores','Mesma pessoa (ou holding) sócia de <b>várias empresas</b> que vendem ao Estado. Um dono por trás de vários fornecedores permite simular concorrência entre empresas do mesmo grupo (fracionamento, propostas de cobertura) e concentrar contratos disfarçadamente.','🫥')+acoesAba('socio_oculto');
  registrarDrill('holdings',{titulo:'Casos em que o sócio é PJ (holding)',itens:a.filter(x=>x.holding),nota:'Sócio PJ é o degrau que permite subir a cadeia até a pessoa física.'});
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Sócios com ≥3 empresas','var(--amber)','🕸️',
        {sobre:'Pessoas no quadro societário de <b>três ou mais</b> empresas que receberam do Estado. Ter várias empresas é lícito e comum; o que este número faz é apontar onde vale cruzar se elas <b>disputam os mesmos certames</b> — porque aí o mesmo dono estaria dos dois lados da mesa.'})}${kpi(fmtRc(a.reduce((s,x)=>s+x.total,0)),'Volume das empresas',null,'💰',
        {sobre:'Soma do que TODAS as empresas destes sócios receberam — <b>exibidas nesta página</b>, não o acervo. É volume sob um mesmo dono, não dano: nada aqui afirma que o pagamento foi indevido.'})}
      ${kpi(a.length?a[0].n_empresas:'—','Mais empresas (1 sócio)','var(--rose)',null,
        {sobre:'O caso extremo da lista: quantas empresas pagas pelo Estado o sócio mais ramificado detém. Número alto pode ser grupo econômico declarado — a pergunta que ele levanta é se essas empresas se encontram no mesmo certame.'})}${kpi(a.filter(x=>x.holding).length,'Holdings/PJ',null,'🏢',{drill:'holdings'})}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por sócio ou empresa…" oninput="filtrar(this,'#ocult-list .card')"></div>`;
  h+=`<div id="ocult-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0"><div style="font-weight:700">${esc(x.socio)} ${x.holding?'<span class="tag purple">holding/PJ</span>':''}</div>
      <div class="muted" style="font-size:12.5px;margin-top:3px">${esc((x.empresas||[]).slice(0,4).join(' · '))}${(x.empresas||[]).length>4?' …':''}</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:var(--amber)">${x.n_empresas}</div><div class="dim">empresas · ${fmtRc(x.total)}</div></div></div>
      ${leitura(`<b>${esc(x.socio)}</b> é sócio de <b>${x.n_empresas}</b> empresas que receberam do Estado (${fmtRc(x.total)} somados). Um mesmo dono em vários fornecedores permite simular concorrência entre empresas do próprio grupo — cruzar se disputam os mesmos certames/órgãos.`)}`,
    x.n_empresas>=5?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

// ═══ NEPOTISMO ═══
export async function renderNepotismo(){
  const d=await J('/api/intel/nepotismo?limite=150');
  if(!d.ok)return sec('Nepotismo')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Nepotismo — parentes em cargo de confiança','Duas ou mais pessoas de nomes distintos com o <b>mesmo sobrenome de família raro</b>, ambas em cargo de confiança no mesmo órgão. É o perfil de nepotismo — a <b>Súmula Vinculante 13 do STF</b> proíbe nomear parente para cargo em comissão. O fragmento de CPF confirma que são pessoas distintas.','👪')+acoesAba('nepotismo',`<a class="btn ghost" style="flex:0 0 auto;min-width:150px" href="/graph?fonte=familias" target="_blank">Grafo de famílias</a>`);
  registrarDrill('sobrenome100',{titulo:'Grupos em que o sobrenome cobre 100% do quadro',itens:a.filter(x=>x.concentracao>=1),nota:'Sobrenome compartilhado NÃO é sinal sozinho: 16,9% das empresas com 2+ sócios PF o têm.'});
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Clusters familiares','var(--rose)','👪',
        {sobre:'Grupos de pessoas com o <b>mesmo sobrenome</b> em cargo de confiança no mesmo órgão. Sobrenome não prova parentesco e no Brasil não há base aberta de filiação — o que sustenta o sinal é a <b>prevalência</b>: o eixo só acende quando o sobrenome é raro na folha e está concentrado ali.'})}${kpi(fmtN(d.n_com_autoridade),'Com autoridade nomeante','var(--rose)','⚖️',
        {sobre:'Clusters em que um dos membros ocupa cargo com <b>poder de nomear</b>. É o que separa coincidência de cadeia: a Súmula Vinculante 13 alcança a nomeação feita por quem tem a competência, não a simples presença de parentes na mesma repartição.'})}
      ${kpi(a.filter(x=>x.concentracao>=1).length,'100% do sobrenome','var(--amber)','🎯',{drill:'sobrenome100'})}${kpi(a.length?a[0].n_membros:'—','Maior cluster',null,null,
        {sobre:'Quantas pessoas tem o maior grupo da lista. Número alto com sobrenome comum é ruído de base; com sobrenome raro, é o caso a abrir primeiro — por isso a concentração aparece em cada linha, e não só o tamanho.'})}</div>`;
  h+=`<div class="dim" style="margin-top:8px">Folhas cruzadas: ${esc((d.folhas||[]).join(', '))||'—'}. Cobertura cresce com novas folhas.</div>`;
  h+=`<div class="search" style="margin-top:12px"><span class="mag"></span><input placeholder="filtrar por sobrenome, órgão ou nome…" oninput="filtrar(this,'#nep-list .card')"></div>`;
  h+=`<div id="nep-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0"><div style="font-weight:700">${esc(x.sobrenome)} ${x.tem_autoridade?'<span class="tag rose">autoridade no cluster</span>':''}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">${esc((x.orgao||'').slice(0,44))}</div>
      <div class="dim" style="margin-top:2px">${Math.round(x.concentracao*100)}% das ${x.total_folha} pessoas desse sobrenome na folha</div></div>
      <div class="right"><div class="num" style="font-weight:800;font-size:20px;color:var(--rose)">${x.n_membros}</div><div class="dim">parentes?</div></div></div>
      <table style="margin-top:10px"><tbody>${(x.membros||[]).map(m=>`<tr><td>${esc(m.nome)}</td><td class="dim">${esc(m.cargo||'')}${m.cpf_frag?' · CPF …'+esc(m.cpf_frag):''}</td></tr>`).join('')}</tbody></table>
      ${leitura(`<b>${x.n_membros}</b> pessoas com o sobrenome <b>${esc(x.sobrenome)}</b> (${Math.round(x.concentracao*100)}% de todos com esse sobrenome na folha) ocupam cargo de confiança no mesmo órgão. Sobrenome raro concentrado em cargos comissionados é o perfil de nepotismo (SV13). ${x.membros.some(m=>m.cpf_frag)?'Fragmentos de CPF distintos confirmam pessoas diferentes.':''} Confirmar o parentesco e a cadeia de nomeação.`)}`,
    'hl')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}
// ═══ EMPRESA FÊNIX ═══
export async function renderFenix(){
  const d=await J('/api/intel/fenix?limite=150');
  if(!d.ok)return sec('Fênix')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  // O texto de cada item pedia ao leitor "verificar se os pagamentos são posteriores à
  // baixa" — pergunta que o dado JÁ responde desde que a data da baixa entrou no detector.
  // E citava o total recebido de TODOS os tempos como se fosse o valor pago à empresa
  // morta: a IDESI aparecia com "R$ 508,1 mi", quando o que veio depois da baixa foi
  // R$ 1,33 mi. Agora afirma o que sabe e diz INDISPONÍVEL quando não sabe.
  const _fenixLeitura=x=>{
    const quem=`<b>${esc(x.nome)}</b> está <b>${esc(x.situacao)}</b> na Receita`;
    if(x.pagou_apos_baixa===true)
      return `${quem} desde <b>${esc(x.data_baixa)}</b> e ainda assim recebeu `
        +`<b>${fmtRc(x.valor_apos_baixa)}</b> em <b>${fmtN(x.n_ob_apos_baixa)} OB posteriores à baixa</b> `
        +`(de ${fmtRc(x.total_recebido)} no total). Pagamento a empresa baixada/inapta é irregular — indício forte.`;
    if(x.pagou_apos_baixa===false)
      return `${quem} desde <b>${esc(x.data_baixa)}</b>, mas <b>todos</b> os ${fmtRc(x.total_recebido)} `
        +`foram pagos <b>antes</b> da baixa — situação comum, <b>não é</b> pagamento a empresa morta. `
        +`Fica na lista como contexto do fornecedor, não como indício.`;
    return `${quem} e recebeu ${fmtRc(x.total_recebido)} do Estado. A <b>data da baixa</b> não está `
      +`na base da Receita local, então não dá para dizer se os pagamentos são posteriores — `
      +`<b>INDISPONÍVEL</b>, que não é o mesmo que regular.`;
  };
  let h=cover('geral','Empresa fênix — morta que recebe, ou nascida para faturar','Empresa <b>BAIXADA/INAPTA</b> na Receita que mesmo assim recebeu do Estado (pagamento a empresa morta), ou <b>aberta poucos meses antes</b> do primeiro pagamento (nasceu já para faturar — perfil de laranja).','🦅')+acoesAba('fenix');
  // o KPI vermelho é o CONFIRMADO (recebeu depois da baixa); "baixada hoje" fica neutro,
  // porque estar baixada hoje e ter recebido antes disso não é indício de nada.
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Empresas fênix','var(--rose)','🦅',
        {sobre:'Empresas com baixa no cadastro da Receita que aparecem no fluxo de pagamento do Estado. O rótulo sozinho não acusa nada — o que separa achado de ruído é a <b>ordem das datas</b>, e ela está nos dois KPIs seguintes.'})}${kpi(fmtN(d.n_defunta_confirmada||0),'Recebeu DEPOIS da baixa',(d.n_defunta_confirmada?'var(--rose)':null),'💀',
        {sobre:'O ACHADO de verdade: ordem bancária emitida em data POSTERIOR à baixa. Uma versão anterior desta tela somava tudo que empresa hoje baixada já recebeu — e anunciava bilhões que eram pagamentos regulares feitos quando a empresa estava viva; o erro foi de ~218×. Situação cadastral vale <b>na data do ato</b>, nunca hoje.'})}
      ${kpi(fmtRc(d.total_apos_baixa||0),'Pago após a baixa',(d.total_apos_baixa?'var(--rose)':null),'💰',
        {sobre:'Soma das OB emitidas depois da baixa — só destas, não do histórico da empresa. Fonte: <b>SIAFE</b>, ordem bancária, que é o único registro de pagamento efetivo; empenho e liquidação não entram porque empenho pode ser cancelado.'})}${kpi(fmtN(d.n_defunta||0),'Baixada hoje (recebeu antes)',null,'🗓️',
        {sobre:'Empresas hoje baixadas cujos pagamentos são TODOS anteriores à baixa. Ficam listadas e fora do achado de propósito: encerrar atividade depois de cumprir contrato é o curso normal das coisas, e contá-las como irregularidade é o erro que esta tela já cometeu.'})}</div>`;
  h+=`<div class="note" style="margin-top:8px">Só o pagamento <b>posterior à baixa</b> caracteriza "pagamento a empresa morta". Estar baixada hoje e ter recebido antes disso é situação comum e não é indício — por isso os dois números aparecem separados.</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por empresa…" oninput="filtrar(this,'#fenix-list .card')"></div>`;
  h+=`<div id="fenix-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0">${clk(x.cnpj,x.nome||x.cnpj)}<div class="dim">${esc(x.cnpj)}</div>
      <div class="muted" style="font-size:12.5px;margin-top:3px">${x.tipo==='defunta'?`<span class="tag rose">${esc(x.situacao)}</span>`:'<span class="tag amber">recém-aberta</span>'} · aberta ${esc(x.data_abertura)} · 1ª OB ${esc(x.primeira_ob)}</div></div>
      <div class="right"><div class="num" style="font-weight:800">${fmtRc(x.total_recebido)}</div><div class="dim">recebido</div></div></div>
      ${leitura(x.tipo==='defunta'?_fenixLeitura(x):`<b>${esc(x.nome)}</b> foi aberta em ${esc(x.data_abertura)} e recebeu o 1º pagamento ${x.meses_ate_ob} meses depois. Empresa que nasce e já fatura com o Estado é perfil de laranja/fachada.`)}`,
    x.tipo==='defunta'?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

// ═══ PORTA GIRATÓRIA ═══
export async function renderPortaGiratoria(){
  const d=await J('/api/intel/porta_giratoria?limite=150');
  if(!d.ok)return sec('Porta giratória')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Porta giratória — ex-servidor virou fornecedor','Ex-servidor público (vínculo inativo/exonerado/sem lotação nas folhas) que hoje é <b>sócio de empresa fornecedora do Estado</b>. Sair do serviço público e virar fornecedor pode violar a quarentena e indica captura do ex-órgão.','🚪')+acoesAba('porta_giratoria');
  registrarDrill('confiancaAlta',{titulo:'Cruzamentos com confiança ALTA (casados por CPF)',itens:a.filter(x=>x.confianca==='ALTA'),nota:'Confiança ALTA = documento, não nome. É a única faixa que dispensa checar homônimo.'});
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Ex-servidores fornecedores','var(--rose)','🚪',
        {sobre:'Pessoas que constam na folha como <b>ex-servidores</b> e hoje figuram no quadro societário de empresa paga pelo Estado. Não é irregularidade por si: o que a lei restringe é a <b>quarentena</b> — contratar com o órgão de onde se saiu, dentro do prazo de impedimento. Por isso cada caso pede as duas datas.'})}${kpi(fmtRc(a.reduce((s,x)=>s+(x.total_pago||0),0)),'Volume recebido',null,'💰',
        {sobre:'Soma paga às empresas <b>desta página</b>. Volume não é dano: mede o tamanho do que precisa ser olhado, não o prejuízo — este só existe se o contrato tiver vício próprio.'})}
      ${kpi(fmtN(a.filter(x=>x.confianca==='ALTA').length),'Confiança ALTA (CPF)','var(--amber)','🔎',{drill:'confiancaAlta'})}${kpi(fmtN(d.homonimos_descartados),'Homônimos descartados',null,'🚮',
        {sobre:'Casos que o motor RECUSOU por não distinguir a pessoa — nome igual sem fragmento de CPF que confirme. Ficam contados de propósito: o que se joga fora é tão auditável quanto o que fica, e um detector que não mostra o próprio descarte pede fé em vez de conferência.'})}</div>`;
  h+=`<div class="search" style="margin-top:14px"><span class="mag"></span><input placeholder="filtrar por nome, empresa ou órgão…" oninput="filtrar(this,'#porta-list .card')"></div>`;
  h+=`<div id="porta-list" class="grid">`+a.map(x=>card(
    `<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div style="min-width:0"><div style="font-weight:700">${esc(x.socio)}</div>
      <div class="muted" style="font-size:12.5px;margin-top:2px">${esc(x.qualificacao)} de ${clk(x.cnpj,x.empresa)}</div>
      <div class="dim" style="margin-top:2px">ex: ${esc(x.ex_cargo||'—')} · ${esc((x.ex_orgao||'').slice(0,34))} <span class="tag amber">${esc(x.vinculo)}</span></div></div>
      <div class="right"><span class="tag ${x.confianca==='ALTA'?'rose':'accent'}">${esc(x.confianca)}</span><div class="num" style="margin-top:6px;font-weight:800">${fmtRc(x.total_pago)}</div></div></div>
      ${leitura(`<b>${esc(x.socio)}</b> consta na folha como ex-servidor (${esc(x.vinculo)}, ${esc(x.ex_orgao||'')}) e hoje é ${esc(x.qualificacao)} de <b>${esc(x.empresa)}</b>, que recebeu ${fmtRc(x.total_pago)} do Estado. Porta giratória — confirmar as datas de saída e do contrato (quarentena).`)}`,
    x.confianca==='ALTA'?'hl':'')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

// ═══ NEPOTISMO CRUZADO ═══
export async function renderNepotismoCruzado(){
  const d=await J('/api/intel/nepotismo_cruzado?limite=80');
  if(!d.ok)return sec('Nepotismo cruzado')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const a=d.achados||[];
  let h=cover('geral','Nepotismo cruzado — troca de favores entre órgãos','A família X manda no órgão A e coloca um parente no órgão B, enquanto a família Y manda no órgão B e coloca um parente no A. A <b>reciprocidade</b> dribla a Súmula Vinculante 13, que só proíbe nomear parente no PRÓPRIO órgão.','🔀')+acoesAba('nepotismo_cruzado');
  h+=`<div class="grid g2">${kpi(fmtN(d.n),'Pares recíprocos','var(--rose)','🔀',
        {sobre:'Pares de órgãos em que o padrão se INVERTE: num deles manda um sobrenome e está colocado o outro; no segundo, o contrário. É o desenho do <b>nepotismo cruzado</b> — a troca que a Súmula Vinculante 13 alcança justamente por burlar a vedação direta. Continua valendo que sobrenome não é parentesco: o par indica onde perguntar, não o que concluir.'})}</div>`;
  if(!a.length)return h+card('<div class="muted">Nenhum par recíproco com o padrão rigoroso nas folhas atuais. Cresce com mais folhas. 🟢</div>')+`<div class="note">${esc(d.ressalva||'')}</div>`;
  h+=`<div class="grid" style="margin-top:14px">`+a.map(x=>card(
    `<div style="font-weight:700">${esc(x.sobrenome_a)} ⇄ ${esc(x.sobrenome_b)}</div>
     <div class="kv" style="margin-top:8px"><span class="k">${esc((x.orgao_a||'').slice(0,30))}</span><b>autoridade: ${esc(x.autoridade_a)}</b></div>
     <div class="kv"><span class="k">${esc((x.orgao_b||'').slice(0,30))}</span><b>autoridade: ${esc(x.autoridade_b)}</b></div>
     ${leitura(`No órgão <b>${esc((x.orgao_a||'').slice(0,26))}</b> manda um <b>${esc(x.sobrenome_a)}</b> e há um <b>${esc(x.sobrenome_b)}</b> colocado; no <b>${esc((x.orgao_b||'').slice(0,26))}</b> é o inverso. Padrão de troca recíproca de parentes entre órgãos — confirmar parentesco e nomeações.`)}`,
    'hl')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.ressalva||'')}</div>`;return h;
}

export async function renderLaranjas(){
  const d=await J('/api/laranjas');if(!d.ok)return sec('Laranjas')+card(`<div class="warn">${erroHumano(d.erro)}</div>`);
  const it=d.itens||[];
  let h=cover('geral','Laranjas — sócio que recebe benefício','Sócio de empresa que recebe do Estado e ao mesmo tempo recebe benefício social de subsistência — indício de interposição (art. 337-F CP).','🎭');
  if(!it.length)return h+card('<div class="muted">Nenhum sócio-beneficiário confirmado. A resolução CPF×benefício é conservadora (evita homônimo). 🟢</div>')+`<div class="note">${esc(d.aviso||'')}</div>`;
  h+=`<div class="grid">`+it.map(x=>card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div><div style="font-weight:700">${esc(x.socio||'—')}</div><div class="dim">${esc(x.cpf||'')}</div></div><span class="tag rose">laranja?</span></div><div class="kv" style="margin-top:6px"><span class="k">Benefícios</span><b>${(x.beneficios||[]).map(esc).join(', ')||'—'}</b></div>${x.motivo?`<div class="muted" style="font-size:12.5px;margin-top:4px">${esc(x.motivo)}</div>`:''}`,'hl')).join('')+`</div>`;
  h+=`<div class="note">${esc(d.aviso||'')}</div>`;return h;
}
export async function renderCartel(){
  const c=await J('/api/cartel');const d=(c.dados||[]).slice(0,20);
  let h=cover('estado','Concentração & cartel · SIAFE','Órgãos onde um fornecedor concentra a maior fatia do valor pago (top share por UG). Complementa o conluio do PNCP com o lado do pagamento.','🔗');
  if(!d.length)return h+card('<div class="muted">Sem dados de concentração.</div>');
  const maxS=Math.max(1,...d.map(u=>u.top_share||0));
  h+=card(`<div class="barw">`+d.slice(0,10).map(u=>{const cor=u.top_share>=90?'var(--rose-d)':u.top_share>=70?'var(--amber-d)':null;
    return `<div><div class="row"><span class="lab">${esc((u.ug_nome||u.ug||'').slice(0,58))}</span><span class="num" style="font-weight:700;color:${cor?(u.top_share>=90?'var(--rose)':'var(--amber)'):'#fff'}">${u.top_share}%</span></div><div class="track"><span class="fill" style="width:${Math.max(4,(u.top_share/maxS)*100)}%${cor?`;background:${cor}`:''}"></span></div></div>`;}).join('')+`</div>`);
  h+=`<div style="height:14px"></div><div class="grid">`+d.map(u=>card(`<div style="display:flex;justify-content:space-between;gap:12px;align-items:center"><div style="min-width:0"><div style="font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(u.ug_nome||'')} <span class="dim">(${esc(u.ug||'')})</span></div><div class="muted" style="font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${u.n_fornecedores} fornec. · top: ${esc(u.top_fornecedor||'—')}</div></div><div class="right"><div style="font-weight:800;color:${u.top_share>=90?'var(--rose)':u.top_share>=70?'var(--amber)':'#fff'}">${u.top_share}%</div><div class="dim">${fmtRc(u.total)}</div></div></div>`)).join('')+`</div>`;
  return h;
}
// glossário: traduz os CÓDIGOS crípticos dos alertas p/ linguagem simples
export const TIPO_ALERTA={
  pcrj_d7_fracionamento:['✂️','Fracionamento de despesa','Compras fatiadas em várias notas para caber abaixo do limite e não fazer licitação.'],
  pcrj_d10_rede_concorrentes:['🕸️','Rede de concorrentes','Empresas ligadas entre si (mesmo sócio/endereço) que disputam as mesmas licitações — concorrência de fachada.'],
  pcrj_d9_socio_na_folha:['🕴️','Sócio na folha','Sócio de empresa fornecedora que também é servidor público — conflito de interesse.'],
  fracionamento:['✂️','Fracionamento de despesa','Compras fatiadas para não licitar.'],
  sobrepreco:['📈','Sobrepreço','Preço muito acima da mediana de mercado.'],
};
export const SEV_LEGENDA={
  alta:['🔴','Alta','Indício forte — priorize a verificação.'],
  media:['🟡','Média','Merece checagem, mas o sinal é mais fraco ou depende de confirmação documental.'],
  baixa:['⚪','Baixa','Sinal fraco / informativo.'],
};
export async function renderAlertas(){
  const p=await J('/api/compliance/painel');const lst=p.lista_alertas||[];
  if(!lst.length)return sec('Auditoria')+card('<div class="muted">Sem alertas no momento. 🟢</div>');
  // legenda da escala (o que 🔴/🟡 significam) — resolve "não entendo o amarelo"
  let h=cover('estado','Alertas de auditoria','Sinais automáticos de irregularidade nas contas. A <b>cor</b> indica a força do indício, não uma acusação.','🚨');
  h+=card(`<div style="font-weight:700;margin-bottom:8px">Como ler as cores</div>`+
    Object.values(SEV_LEGENDA).map(([ic,nome,desc])=>`<div class="kv"><span class="k" style="min-width:110px"><span class="sev ${nome.toLowerCase()==='alta'?'alta':nome.toLowerCase()==='média'?'media':'baixa'}">${ic} ${nome}</span></span><b style="font-weight:500;color:var(--tx2);text-align:right">${desc}</b></div>`).join(''));
  // agrupa por TIPO, com contagem e explicação em português
  const porTipo={};lst.forEach(a=>{(porTipo[a.tipo]=porTipo[a.tipo]||[]).push(a);});
  h+=`<div style="height:14px"></div>`+sec('Alertas por tipo',lst.length);
  h+=`<div class="grid">`+Object.entries(porTipo).map(([tipo,alertas])=>{
    const[ic,nome,desc]=TIPO_ALERTA[tipo]||['🚩',tipo,''];
    const nAlta=alertas.filter(a=>a.severidade==='alta').length,nMed=alertas.length-nAlta;
    return card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0"><div style="font-weight:700">${ic} ${esc(nome)}</div><div class="muted" style="font-size:12.5px;margin-top:3px">${esc(desc)}</div></div>
      <div class="right">${nAlta?`<span class="sev alta">${nAlta} 🔴</span> `:''}${nMed?`<span class="sev media">${nMed} 🟡</span>`:''}</div></div>
      <div class="exp" onclick="toggle(this)" style="margin-top:8px"><div class="dim"><span class="chev">▸</span> ver os ${alertas.length} casos</div>
      <div class="objs">${alertas.slice(0,40).map(a=>`<div class="obj">${a.severidade==='alta'?'🔴':'🟡'} <b>${esc((a.titulo||'').replace(/^[^—]*—\\s*/,''))}</b>${a.descricao?` — <span class="muted">${esc(a.descricao)}</span>`:''}</div>`).join('')}</div></div>`);
  }).join('')+`</div>`;
  h+=`<div class="note">Indício para apuração interna — não é acusação. 🔴 = sinal forte; 🟡 = merece checagem.</div>`;
  return h;
}
export async function renderSiafe(){
  const s=await J('/api/siafe/stats');if(!s.ok)return sec('SIAFE')+card('<div class="muted">SIAFE indisponível.</div>');
  const linhas=(s.por_ano||[]).filter(x=>x.valor>0).map(x=>`<tr><td>${x.exercicio}</td><td>${fmtN(x.n)}</td><td>${fmtR(x.valor)}</td></tr>`).join('');
  let h=sec('SIAFE · ordens bancárias')+`<div class="grid g2">${kpi(fmtN(s.total),'OBs ingeridas',null,null,
        {sobre:'Ordens bancárias no acervo — pagamento EFETIVO. Empenho é reserva e pode ser cancelado; liquidação reconhece a dívida. Só a OB significa que o dinheiro saiu.'})}${kpi(fmtRc(s.valor_total),'Valor total',null,null,
        {sobre:'Soma das OB ingeridas. É o total do que a casa VIU, não o do orçamento executado: exercício não coletado não entra, e a diferença é lacuna de coleta, não economia.'})}</div><div style="height:12px"></div>`;
  /* QUANTIFICAR A LACUNA, não só avisar dela. O tooltip dizia "exercício não coletado não entra";
     o leitor precisa do TAMANHO: medido em 2026-08-09, a fonte canônica tinha 23,6% das OBs que o
     espelho conhece, e o número sobe a cada drenagem. Sem isto, R$ 86 bi lê-se como o gasto do
     Estado. */
  const cb0=s.cobertura||{};
  if(cb0.pct_do_espelho!=null){
    h+=leitura(`Este total é <b>o que a casa já coletou</b>, não o gasto do Estado: a fonte canônica
      tem <b>${cb0.pct_do_espelho}%</b> das OBs que o espelho conhece
      (${fmtN(s.total)} de ${fmtN(cb0.obs_espelho_total||0)}), <b>Todo valor daqui é PISO</b> — a drenagem roda
      a cada 2 h e o estado por par sai em <code>cobertura_siafe.medir()</code>.`);
  }
  h+=card(`<table><thead><tr><th>Exercício</th><th>OBs</th><th>Valor</th></tr></thead><tbody>${linhas||'<tr><td colspan=3 class="muted">sem dados</td></tr>'}</tbody></table>`);
  h+=`<div style="height:16px"></div>`+await frescorHtml();
  return h;
}
export async function renderSweeps(){
  // Cockpit do SISTEMA (pedido do dono 2026-07-26): sweeps, fila SEI com barra,
  // arquivo compacto, pipelines e aprendizados — vivo, atualizando em 30s.
  /* Medido em campo (2026-07-31): sweeps/status 0,278 s · sistema/atividade 0,114 s. Nada a dividir. */
  const [d,a]=await Promise.all([J('/api/sweeps/status'),J('/api/sistema/atividade')]);
  const sei=a.sei||{},apr=a.aprendizados||{};
  const gb=v=>v==null?'—':fmtD(v/1e9,2)+' GB';
  const idade=st=>st==null?'—':(st<90?'agora':(st<5400?Math.round(st/60)+' min atrás':Math.round(st/3600)+' h atrás'));
  const aprTotal=(apr.memoria_db||0)+(apr.fichas_sei||0)+(apr.direcionamentos||0)+(apr.vault_notas||0);
  let h=cover('geral','Sistema — a atividade de toda a máquina',
    'O que está coletando agora, quanto da fila SEI já virou <b>arquivo compacto</b>, o estado de cada pipeline e quantos <b>aprendizados</b> a leitura já produziu. Atualiza sozinho a cada 30s.','🛰️');
  h+=`<div class="grid g2" id="sis-live">
    ${kpi(sei.pct_lido==null?'—':fmtD(sei.pct_lido,1)+'%','Fila SEI já lida',null,'📄',
      {sobre:'Fração da fila de processos já capturada e arquivada. É a medida de <b>cobertura</b> de tudo que depende de leitura de autos: com fila incompleta, a ausência de achado num processo não lido não significa processo regular — significa processo não visto.'})}
    ${kpi(fmtN(sei.arquivados),'Processos no arquivo compacto',null,null,
      {sobre:'Processos com texto, fases e fotos gravados em disco. O arquivo é o caminho principal de leitura — browser e IA só entram quando ele não tem a peça, porque reler o SEI a cada pergunta é lento e derruba a sessão única por IP.'})}
    ${kpi(gb(sei.arquivo_bytes),'Espaço do arquivo (texto+fases+fotos)',null,null,
        {sobre:'Disco ocupado pelo arquivo compacto de processos. Importa porque o arquivo é o caminho principal de leitura — quando ele cresce sem controle, a poda passa a ser o que decide o que a casa consegue reler.'})}
    ${kpi(fmtN(aprTotal),'Aprendizados acumulados','var(--accent)','🧠',
        {sobre:'Lições registradas pelo motor de metacognição. É o que impede um defeito corrigido de voltar por esquecimento — cada família do catálogo de falhas nasceu de um caso concreto.'})}</div>`;
  const falta=(sei.fila_total!=null&&sei.arquivados!=null)?sei.fila_total-sei.arquivados:null;
  h+=card(`<div class="kv"><span class="k">Fila SEI por dinheiro — lidos × restantes</span><b><span class="num" id="sis-lidos">${fmtN(sei.arquivados)}</span> de ${fmtN(sei.fila_total)}${falta!=null?` · faltam <span class="num" id="sis-falta">${fmtN(falta)}</span>`:''}</b></div>
    <div class="sisbar bar" title="${sei.pct_lido==null?'fila total indisponível':fmtD(sei.pct_lido,1)+'% lido'}"><i id="sis-barra" style="width:${sei.pct_lido==null?0:Math.max(1.2,sei.pct_lido)}%"></i></div>
    ${sei.pct_lido==null?leitura('Total da fila <b>INDISPONÍVEL</b> agora (não é zero) — a barra volta quando o compliance.db responder.'):''}`);
  h+=`<div style="height:14px"></div>`+sec('Sweeps de coleta',(a.sweeps||[]).length);
  h+=card((a.sweeps||[]).map(s0=>{
    const on=s0.vivo,sup=s0.supervisor;
    const est=a.pausado?'pausado':(on?'rodando':(sup?'supervisionado (aguardando janela)':'parado'));
    const cor=a.pausado?'var(--amber)':(on?'var(--green)':(sup?'var(--accent)':'var(--rose)'));
    return `<div class="kv"><span class="k"><span class="sinal" style="background:${cor};box-shadow:0 0 8px ${cor}"></span> ${esc(s0.nome)}</span><b>${est} · <span class="num">${idade(s0.atividade_s)}</span></b></div>`;}).join('')
    +`<div class="btns" style="margin-top:10px"><button class="btn red" onclick="sweep('pausar')">⏸ Pausar</button><button class="btn green" onclick="sweep('retomar')">▶ Retomar</button><button class="btn ghost" onclick="ir(aba)">↻ Atualizar</button></div>`);
  if((a.pipelines||[]).length){
    h+=`<div style="height:14px"></div>`+sec('Pipelines (SLO)',a.pipelines.length);
    h+=card(`<div style="display:flex;flex-wrap:wrap;gap:8px">`+a.pipelines.map(p0=>{
      // A rota /api/pipelines devolve `status` (+ idade_h); /api/sistema/atividade devolve
      // `estado`. A tela lia só `estado`, então TODA linha aparecia como "—" e pintada de ruim —
      // inclusive com o SLO 100% verde. Aceita os dois, e `pausado`/`sob_demanda` não são falha:
      // são estado declarado da fonte.
      const st=String(p0.estado||p0.status||'').toLowerCase();
      const ok=/^(ok|pausado|sob_demanda)/.test(st);
      return `<span class="tag ${ok?'green':'amber'}" title="${esc(p0.estado||p0.status||'')}"><span class="sinal" style="background:${ok?'var(--green)':'var(--amber)'}"></span>${esc(p0.nome)}</span>`;}).join('')+`</div>`);}
  h+=`<div style="height:14px"></div>`+sec('Aprendizados — o que a leitura já produziu');
  h+=card(`<div class="kv"><span class="k">Fichas SEI montadas</span><b class="num">${fmtN(apr.fichas_sei)}</b></div>
    <div class="kv"><span class="k">Análises de direcionamento</span><b class="num">${fmtN(apr.direcionamentos)}</b></div>
    <div class="kv"><span class="k">Árvores de processo capturadas</span><b class="num">${fmtN(apr.arvores_sei)}</b></div>
    <div class="kv"><span class="k">Memória de aprendizado (DB)</span><b class="num">${fmtN(apr.memoria_db)}</b></div>
    <div class="kv"><span class="k">Notas de aprendizado no vault</span><b class="num">${fmtN(apr.vault_notas)}</b></div>`);
  h+=(d.sei?.ultima?`<div style="height:12px"></div><pre>${esc((d.sei.ultima||'').replace(/\*\*/g,''))}</pre>`:'');
  h+=`<div style="height:16px"></div>`+await frescorHtml();
  clearInterval(window._sisTick);
  window._sisTick=setInterval(async()=>{
    if(aba!=='g_sweeps'||!document.getElementById('sis-live')){clearInterval(window._sisTick);return;}
    try{const n=await J('/api/sistema/atividade');const ns=n.sei||{};
      const up=(id,v)=>{const e=document.getElementById(id);if(e&&v!=null&&e.textContent!==String(v))e.textContent=v;};
      up('sis-lidos',fmtN(ns.arquivados));
      if(ns.fila_total!=null&&ns.arquivados!=null)up('sis-falta',fmtN(ns.fila_total-ns.arquivados));
      const b=document.getElementById('sis-barra');
      if(b&&ns.pct_lido!=null)b.style.width=Math.max(1.2,ns.pct_lido)+'%';
    }catch(e){}
  },30000);
  return h;
}
export async function sweep(a){if(a==='pausar'&&!await jfnConfirm('Pausar <b>todos</b> os sweeps de coleta? O painel continua no ar — só a alimentação de dados novos para até você retomar.','⏸ Pausar tudo'))return;await J('/api/sweeps/'+a,{method:'POST'});jfnToast(a==='pausar'?'Sweeps pausados.':'Sweeps retomados.','green');setTimeout(()=>ir(aba),500);}
export let _valLista=[],_valIdx=0;
export async function renderValidar(){
  const d=await J('/api/fachada/revisar?limite=200');_valLista=(d&&d.fachadas)||[];_valIdx=0;
  return cover('geral','Validador de fachada','Fachadas flagradas p/ revisão humana. Veja o Street View, decida, e a base atualiza.','🏢')+`<div id="val-card">${_valCard()}</div>`;
}
export function _valCard(){
  if(_valIdx>=_valLista.length)return card('<div class="muted">Tudo revisado nesta sessão. Recarregue p/ mais.</div>');
  const f=_valLista[_valIdx];
  const maps=(f.geo_lat&&f.geo_lon)?`https://www.google.com/maps/@${f.geo_lat},${f.geo_lon},19z`:`https://www.google.com/maps/search/${encodeURIComponent((f.endereco||'')+', '+(f.municipio||''))}`;
  const sv=(f.geo_lat&&f.geo_lon)?`https://www.google.com/maps?layer=c&cbll=${f.geo_lat},${f.geo_lon}`:maps;
  const motivo=f.nivel==='SEM_GOOGLE'?'Sem marcação no Google':f.nivel==='FECHADO_GOOGLE'?'Fechado no Google':'Revisar fachada';
  return card(`<div class="dim">${_valIdx+1} de ${_valLista.length}</div><div style="font-weight:700;font-size:16px;margin:4px 0">${esc(f.razao||f.cnpj)}</div>
     <div class="kv"><span class="k">Motivo</span><b style="color:var(--rose)">${esc(motivo)}</b></div><div class="kv"><span class="k">Recebido do Estado</span><b>${fmtR(f.total_recebido)}</b></div>
     <div class="kv"><span class="k">Endereço</span><b class="right" style="max-width:60%">${esc(f.endereco||'—')}, ${esc(f.municipio||'')}/${esc(f.uf||'')}</b></div><div class="kv"><span class="k">CNPJ</span><b>${esc(f.cnpj)}</b></div>
     <div class="btns"><a class="btn ghost" href="${sv}" target="_blank">Street View</a><a class="btn ghost" href="${maps}" target="_blank">Maps</a></div>
     <input id="val-nota" placeholder="nota p/ o Claude (opcional)" style="margin-top:10px">
     <div class="btns" style="margin-top:8px"><button class="btn red" onclick="validar('suspeito')">Suspeito</button><button class="btn green" onclick="validar('ok')">Legítima</button><button class="btn ghost" onclick="validar('mais_info')">Mais info</button></div>`);
}
export async function validar(v){const f=_valLista[_valIdx];if(!f)return;const nota=($('val-nota')||{}).value||'';
  await J('/api/fachada/veredito',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cnpj:f.cnpj,veredito:v,nota})});
  _valIdx++;const el=$('val-card');if(el)el.innerHTML=_valCard();}
export async function renderAcoes(){
  const reps=await J('/api/compliance/reports');const pdfs=((reps&&reps.length?reps:[])||[]).filter(x=>x.type==='pdf').slice(0,12);
  const repsHtml=pdfs.length?`<div class="lnks">`+pdfs.map(f=>`<a class="lnk" href="${f.url}" target="_blank"><span class="ic"></span><div><div class="t">${esc(f.name)}</div></div><span class="ar">→</span></a>`).join('')+`</div>`:card('<div class="muted">Nenhum relatório gerado ainda — peça um pelo botão "Gerar PDF" de qualquer aba, ou pelo /relatorio no Telegram; ele aparece aqui na hora.</div>');
  return cover('geral','Gerar relatórios & atalhos','Relatório de fornecedor/órgão com Lex forense, dossiê 360, cruzamento e painéis.','☑️')+
    card(`<label class="fld">Relatório de fornecedor (+ Lex forense)</label><div style="display:flex;gap:8px"><input id="ac-emp" placeholder="nome ou CNPJ"><button class="btn accent" style="flex:0 0 auto;min-width:82px" onclick="acao('relatorio')">Gerar</button></div>
      <div style="height:11px"></div><label class="fld">Relatório de órgão (+ Lex)</label><div style="display:flex;gap:8px"><input id="ac-org" placeholder="órgão ou UG (ex: 133100)"><button class="btn accent" style="flex:0 0 auto;min-width:82px" onclick="acao('orgao')">Gerar</button></div>
      <div style="height:11px"></div><label class="fld">Dossiê 360</label><div style="display:flex;gap:8px"><input id="ac-dos" placeholder="nome ou CNPJ do alvo"><button class="btn accent" style="flex:0 0 auto;min-width:82px" onclick="acao('dossie')">Gerar</button></div>
      <pre id="ac-out" style="margin-top:13px;display:none"></pre>`)+
    `<div style="height:18px"></div>`+sec('Relatórios gerados')+repsHtml+
    `<div style="height:18px"></div>`+sec('Painéis')+`<div class="lnks">
      <a class="lnk" href="/auditoria"><span class="ic"></span><div><div class="t">Painel de Auditoria</div><div class="d">KPIs clássicos</div></div><span class="ar">→</span></a>
      <a class="lnk" href="/graph"><span class="ic"></span><div><div class="t">Grafo de fraude</div><div class="d">relações entre entes</div></div><span class="ar">→</span></a>
      <a class="lnk" href="/graph?fonte=familias" target="_blank"><span class="ic"></span><div><div class="t">Grafo de famílias</div><div class="d">clãs em cargos + suas empresas</div></div><span class="ar">→</span></a>
      <a class="lnk" href="/hermes"><span class="ic"></span><div><div class="t">Yoda / Hermes</div><div class="d">chat e relatórios</div></div><span class="ar">→</span></a></div>`;
}
export async function acao(tipo){
  const out=$('ac-out');out.style.display='block';let url,body,val;
  if(tipo==='relatorio'){val=$('ac-emp').value.trim();if(!val)return;url='/api/relatorio/inteligencia';body={empresa:val};}
  if(tipo==='orgao'){val=$('ac-org').value.trim();if(!val)return;url='/api/relatorio/orgao';body={orgao:val};}
  if(tipo==='dossie'){val=$('ac-dos').value.trim();if(!val)return;url='/api/dossie';body={alvo:val};}
  out.textContent=`processando "${val}"… (até ~1 min)`;const t0=Date.now()/1000;
  const antes=new Set(((await J('/api/compliance/reports'))||[]).filter(x=>x.type==='pdf').map(x=>x.name));
  const d=await J(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(d.erro){out.textContent='⚠ erro: '+d.erro;return;}
  if(d.ambiguo){out.textContent=`❓ ambíguo: ${d.pergunta}\ncandidatos: ${(d.candidatos||[]).map(c=>c.nome||c).join(' · ')}`;return;}
  if(d.status==='gerando'||(d.msg&&d.path_pdf==null&&d.resumo==null)){out.textContent=(d.msg||'⏳ Gerando…').replace(/\*/g,'');return pollarPdf(out,val,t0,antes);}
  const pdf=d.path_pdf||d.path_lex||d.path_xlsx;
  const linha=[d.empresa||d.orgao||val,d.risco?('risco '+d.risco):'',d.grau_lex?('Lex '+d.grau_lex):'',d.score!=null?('score '+d.score):''].filter(Boolean).join(' · ');
  out.innerHTML=`✅ ${esc(linha)}\n${esc((d.resumo||'').slice(0,500))}`+(pdf?`\n\n📄 <a href="/${pdf.replace(/^\//,'')}" target="_blank" style="color:var(--accent)">abrir PDF</a>`:'');
}
export async function pollarPdf(out,termo,t0,antes){
  const slug=(termo||'').toLowerCase().replace(/[^a-z0-9]+/g,'_').slice(0,12);
  for(let i=0;i<36;i++){await new Promise(r=>setTimeout(r,5000));
    const pdfs=((await J('/api/compliance/reports'))||[]).filter(x=>x.type==='pdf');
    let novos=pdfs.filter(x=>x.mtime&&x.mtime>t0);if(!novos.length)novos=pdfs.filter(x=>!antes.has(x.name));
    const alvo=novos.find(x=>slug&&x.name.toLowerCase().includes(slug))||novos[0];
    if(alvo){sessaoReports.add(alvo.name);out.innerHTML='✅ pronto: '+esc(alvo.name)+`\n\n📄 <a href="${alvo.url}" target="_blank" style="color:var(--accent)">abrir PDF</a> (apaga ao sair)`;return;}}
  out.textContent='⏳ Ainda gerando — confira no Telegram ou em Relatórios.';
}
/* O REGISTRO DAS PEÇAS DA SESSÃO. Morava no entrypoint e era usado SÓ aqui — um símbolo livre
   entre módulos, do tipo que o `esbuild` empacota calado. Pior: como nada no entrypoint o
   referenciava, a poda de código morto levava a declaração e deixava os três usos, e o bundle
   publicado tinha `sessaoReports` usado três vezes e declarado zero. Agora mora com quem usa. */
const sessaoReports=new Set();
export function limparEfemeros(){if(!sessaoReports.size)return;const body=JSON.stringify({nomes:[...sessaoReports]});
  try{navigator.sendBeacon('/api/compliance/reports/limpar',new Blob([body],{type:'application/json'}));}
  catch(e){fetch('/api/compliance/reports/limpar',{method:'POST',headers:{'Content-Type':'application/json'},body,keepalive:true});}}



/* SETTERS DA PONTE. Estes estados sao ESCRITOS de dentro de atributos `on*` do HTML
   (`onchange="_respProc=this.value;ir('e_resp')"`). Depois que as telas viraram modulo, o
   entrypoint nao pode mais atribuir a eles: import e imutavel em JavaScript, e o esbuild
   recusa a build dizendo isso na cara. Nao e obstaculo — e a garantia funcionando. Antes,
   uma escrita que nao chegasse ao destino seria MUDA: o filtro pararia de responder sem um
   erro sequer. Agora ela nem compila. */
export function _set_cjEsf(v){_cjEsf=v;}
export function _set_comisView(v){_comisView=v;}
export function _set_ctrView(v){_ctrView=v;}
export function _set_fantFaixa(v){_fantFaixa=v;}
export function _set_gastosDet(v){_gastosDet=v;}
export function _set_perOrdem(v){_perOrdem=v;}
export function _set_respProc(v){_respProc=v;}
export function _set_riscoView(v){_riscoView=v;}

/* Estes vieram de declaracao MULTIPLA (`let _compView='catalogo', _compTermo='', ...`),
   que o meu gerador de setters nao reconheceu na primeira passada — mesma cegueira que o
   extrator da ponte ja tinha tido. O sintoma foi recursao infinita no getter do window. */
export function _set_perGrau(v){_perGrau=v;}

/* ── O COCKPIT SAIU (v59, §6.2-B) ────────────────────────────────────────────────────────────
   `abas/cockpit.js` leva a aba Início inteira: a tela, a montagem depois do paint, os oito
   instrumentos, o ticker e o puxador. O reexport mantém a porta: `entrada.js` continua importando
   `renderCockpit`, `ckBoot` e companhia daqui, e a linha de import dele não muda uma vírgula.
   Ver o cabeçalho de lá para por que o eixo do corte é DOMÍNIO e não esfera. */
export {renderCockpit, ckBoot, ckCard, ckFill, ckPush, ckPull, _ckCount, _ckTimer, _ckTick, _CK,
        blocoComandosMestres, abrirCapMestra} from './cockpit.js';

/* ── O COMPARADOR SAIU (v59, §6.2-B) ─────────────────────────────────────────────────────────
   `abas/comparador.js` leva a tela, as seis visões e os sete estados com seus setters. Ele é o
   caso que prova o eixo: duas esferas o consomem, e como DOMÍNIO isso é um módulo importado duas
   vezes em vez de um "compartilhado" a ser arbitrado. */
export {renderComparador, _compEsfChips, _compItemView, _montarGrupoCard, _compCatalogo,
        _compBuscar, _unOf, _compOrgaos, _compEconomia, _blocoVedada, _compDossie, _compForn,
        _compView, _compTermo, _compGrupo, _compCat, _compEsf, _compDisp, _compOrd,
        _set_compView, _set_compCat, _set_compDisp, _set_compEsf, _set_compGrupo, _set_compOrd,
        _set_compTermo} from './comparador.js';

/* ── VÍNCULOS SAIU (v59, §6.2-B) ─────────────────────────────────────────────────────────────
   Era o corte difícil: o domínio vivia em DUAS faixas separadas por quatro blocos alheios. O
   interleavamento é obstáculo para recortar texto, não para cortar por domínio — as duas faixas
   só se referenciavam por nome, e nome não tem endereço. Ver o cabeçalho de lá. */
export {renderVinculos, DRILL_ACOES, _vincCnpj, vincConsultar, vincParentesco, vincContato, vincAgentePublico, vincOsintProcessos, vincElosOcultos, vincCocontato, vincAssinaturasPcrj, vincNaData, vincTrocas,
        vincPrevalencia, vincGrafo, vincFtm, vincHistoricoPessoa, vincConluioMunicipal,
        vincResolucao, vincInterposicao, vincPatrimonio, VINC_ACOES,
        ligarVinculos} from './vinculos.js';

// O ACRÉSCIMO LOGO DEPOIS DA ASSINATURA. A CGE apontou 45,4% dezessete dias após assinar um
// contrato de pavimentação da SECID: desequilíbrio superveniente não se forma em duas semanas, e
// acréscimo grande no início sugere valor de certame subestimado. Só termo de natureza VALOR entra.
// A COBERTURA vem junto porque a data do termo só passou a ser guardada em 09/08/2026 — "0
// achados" sem ela leria-se como "nada a apurar".
async function aditivoPrecoce(){
  const o=$('ff-out'); if(!o) return;
  const d=await J('/api/fiscal/aditivo_precoce?dias=90&limite=12');
  if(!d||d.ok===false) return;
  const c=d.cobertura||{};
  const alvo=document.createElement('div');
  let h=sec(`Aditivo de valor nos primeiros ${d.dias} dias (${fmtN(d.total)})`);
  if((d.itens||[]).length){
    h+=card(`<table class="tb"><thead><tr><th class="right">dias</th><th>órgão</th><th>fornecedor</th>
      <th class="right">inicial</th><th class="right">acréscimo</th><th class="right">%</th>
      <th>art. 125</th></tr></thead><tbody>`
      +d.itens.map(x=>`<tr>
        <td class="right" style="font-weight:800;color:${x.dias<=30?'var(--red)':'var(--amber)'}">${x.dias}</td>
        <td>${esc((x.orgao||'').slice(0,26))}</td><td>${esc((x.fornecedor||'').slice(0,28))}</td>
        <td class="right dim">${fmtRc(x.valor_inicial)}</td>
        <td class="right" style="font-weight:700">${fmtRc(x.acrescimo)}</td>
        <td class="right">${x.pct==null?'—':x.pct+'%'}</td>
        <td style="color:${x.acima_do_teto?'var(--red)':'inherit'}">${x.acima_do_teto?'acima do teto de '+x.teto_pct+'%':'dentro'}</td></tr>`).join('')
      +`</tbody></table>`);
  } else if((d.fonte||{}).ok===false){
    h+=vazioDeclarado(d,`acréscimo de valor nos primeiros ${d.dias} dias`);
  } else {
    h+=card(`<div class="dim">Nenhum acréscimo de valor nos primeiros ${d.dias} dias <b>na fatia já
      medida</b> — e a fatia é o que importa ler junto: ausência aqui não é ausência no acervo.</div>`);
  }
  if(c.estado==='medido'){
    h+=leitura(`Cobertura: <b>${fmtN(c.avaliaveis)}</b> de <b>${fmtN(c.termos)}</b> termos aditivos
      são avaliáveis (<b>${c.pct}%</b>) — só entram os que têm a data do TERMO e a do CONTRATO. A data
      do termo passou a ser guardada em 09/08/2026; os coletados antes disso estão sendo recoletados.`);
  }
  h+=leitura(esc(d.ressalva||''));
  alvo.innerHTML=h; o.appendChild(alvo);
}

// O NÚCLEO, NÃO CADA SCREEN. Perder muito é o normal de quem disputa muito, e vencer em ramos
// díspares é o normal de distribuidora regional — isolados, os dois screens têm falso positivo
// estrutural. A interseção (vencedor generalista CERCADO de perdedores contumazes) é o que merece
// a fila. Esta lógica vivia dentro de um main() e por isso nenhuma tela a mostrava.
// ZERO DOCUMENTO NÃO É PROCESSO VAZIO. O sweep encerrava cada ciclo chamando os zerados de "fora de
// escopo/vazio" — causa afirmada que ninguém mediu. Enquanto ela é desconhecida, o processo segue
// ABERTO: nenhuma conclusão de ausência pode se apoiar nele, e R$ 3,77 bi em OB estão atrás disso.
// O FRAMEWORK DE DETECTORES ESTAVA MUDO. `data/achados.db` guarda o que as três varreduras
// produzem (órgão/fornecedor, certame, execução) — 10.630 avaliações e 543 confirmados por 13
// detectores — e até 2026-08-11 NENHUMA tela lia esse banco. Achado que não chega ao fiscal não é
// achado; era a maior lacuna de fiação da casa.
async function detectoresFramework(){
  const o=$('ff-out'); if(!o) return;
  const d=await J('/api/fiscal/detectores?limite=12');
  if(!d||d.ok===false) return;
  const alvo=document.createElement('div');
  let h=sec(`Framework de detectores — ${fmtN(d.confirmados)} confirmados de ${fmtN(d.avaliacoes)} avaliações`);
  if(!(d.detectores||[]).length){
    h+=card('<div class="dim">Nenhuma varredura gravou achado ainda — as três rodam por linha de comando e gravam em data/achados.db.</div>');
    alvo.innerHTML=h; o.appendChild(alvo); return;
  }
  h+=`<div class="grid g2">${kpi(fmtN(d.confirmados),'Indícios confirmados','var(--rose)','🎯',
      {sobre:'Achados que passaram a régua do detector. <b>Indício apurado, não acusação</b>: cada registro carrega explicação inocente e motivo de refutação.'})}${
      kpi(fmtN(d.nao_avaliaveis),'Não avaliáveis',null,'⬜',
      {sobre:'A fatia que a base não alimenta. Contá-la junto com os descartados esconderia a cobertura real — por isso ela aparece separada.'})}</div>`;
  h+=card(`<table class="tb"><thead><tr><th>detector</th><th>escopo</th><th class="right">confirmados</th>
    <th class="right">descartados</th><th class="right">não avaliáveis</th></tr></thead><tbody>`
    +d.detectores.filter(x=>x.confirmado>0).map(x=>`<tr>
      <td><b>${esc(x.detector)}</b></td><td class="dim">${esc(x.escopo)}</td>
      <td class="right" style="font-weight:800;color:${x.confirmado>=30?'var(--rose)':'inherit'}">${fmtN(x.confirmado)}</td>
      <td class="right dim">${fmtN(x.descartado||0)}</td>
      <td class="right dim">${fmtN(x.nao_avaliavel||0)}</td></tr>`).join('')
    +`</tbody></table>`);
  if((d.itens||[]).length){
    h+=card(`<table class="tb"><thead><tr><th>detector</th><th>alvo</th><th>motivo</th></tr></thead><tbody>`
      +d.itens.map(x=>`<tr><td><b>${esc(x.detector)}</b></td>
        <td class="dim" style="font-size:12px">${esc(String(x.alvo).slice(0,34))}</td>
        <td style="font-size:12px">${esc(String(x.motivo).slice(0,110))}</td></tr>`).join('')
      +`</tbody></table>`);
  }
  /* FRESCOR POR ESCOPO. Desde 11/08 16:30 as varreduras de órgão e certame estão DELEGADAS À VM-2,
     e este banco congela para elas até a colheita voltar. Contagem sem data faz dado parado passar
     por atual — mesma regra dos carimbos de alerta. */
  const f=(d.fonte||{}).medido_em||{};
  if(Object.keys(f).length){
    h+=`<div class="dim" style="margin-top:6px">Medido em: `
      +Object.entries(f).map(([k,v])=>`<b>${esc(k)}</b> ${esc(String(v).replace('T',' ').slice(0,16))}`).join(' · ')
      +((d.fonte||{}).delegado_vm2?' — <b>órgão e certame estão delegados à VM-2</b>; enquanto a colheita não voltar, esses dois números não avançam.':'')
      +`</div>`;
  }
  h+=leitura(esc(d.ressalva||''));
  alvo.innerHTML=h; o.appendChild(alvo);
}

// A EMERGÊNCIA QUE SE REPETE. O art. 75, VIII pressupõe imprevisibilidade; o screen mede a
// RECORRÊNCIA, que o inciso não prevê. Estava mudo desde que foi escrito: nenhuma rota, card ou
// cron consumia o `sweep_emergencia_recorrente` — a mesma família do `achados.db` sem leitor.
async function emergenciaRecorrente(){
  const o=$('ff-out'); if(!o) return;
  const d=await J('/api/fiscal/emergencia_recorrente?limite=14');
  if(!d||d.ok===false) return;
  const alvo=document.createElement('div');
  let h=sec(`Emergência recorrente — unidade × exercício com ${d.minimo}+ dispensas (${fmtN(d.total)})`);
  if(!(d.itens||[]).length){
    h+=card('<div class="dim">Nenhum grupo na fatia medida — o que não significa que não haja emergência recorrente fora dela.</div>');
    alvo.innerHTML=h; o.appendChild(alvo); return;
  }
  h+=`<div class="grid g2">${kpi(fmtRc(d.valor_total),'Somado nos grupos','var(--amber)','🚨',
      {sobre:'Dispensa emergencial é legal e às vezes indispensável. O indício é a <b>recorrência</b>: imprevisibilidade não se repete todo exercício. Uma linha por PROCESSO — a tabela do TCE-RJ tem uma linha por item e repete o total do processo em cada uma, o que inflava a soma em 2,3×.'})}${
      kpi(fmtN(d.total),'Grupos',null,'🏛️',
      {sobre:'Unidade × exercício. A régua reconhece a emergência pelo <b>enquadramento legal</b> (art. 75, VIII da Lei 14.133/2021 e art. 24, IV da Lei 8.666/93), não só pela palavra no objeto — 891 dispensas emergenciais diziam “PEITO DE FRANGO” e ficavam invisíveis.'})}</div>`;
  h+=card(`<table class="tb"><thead><tr><th>unidade</th><th class="right">exerc.</th>
    <th class="right">dispensas</th><th class="right">valor</th><th>dominante</th>
    <th class="right">concentr.</th></tr></thead><tbody>`
    +d.itens.map(x=>`<tr>
      <td>${esc(String(x.unidade||'').slice(0,40))}</td>
      <td class="right dim">${esc(String(x.exercicio||''))}</td>
      <td class="right">${fmtN(x.n)}</td>
      <td class="right">${fmtRc(x.total)}</td>
      <td style="font-size:12px">${esc(String(x.fornecedor_dominante||'').slice(0,30))}
        <span class="dim">(${fmtN(x.n_fornecedores)} forn.)</span></td>
      <td class="right">${(x.concentracao_dominante>=0.8?'<b>':'')}${(100*(x.concentracao_dominante||0)).toFixed(0)}%${(x.concentracao_dominante>=0.8?'</b>':'')}</td>
    </tr>`).join('')
    +`</tbody></table>`)+leitura(esc(d.ressalva||''));
  alvo.innerHTML=h; o.appendChild(alvo);
}

// LEITURA DUPLA — regra × IA no MESMO processo. O card mostra a DISCORDÂNCIA, que é a fila: onde as
// duas concordam ninguém precisa ler; onde discordam, ou a régua é estreita ou o modelo inventou.
async function leituraDupla(){
  const o=$('ff-out'); if(!o) return;
  const d=await J('/api/fiscal/leitura_dupla?limite=14');
  if(!d||d.ok===false) return;
  const alvo=document.createElement('div');
  let h=sec(`Leitura dupla — onde a regra e a IA discordam (${fmtN(d.total)} processos)`);
  if(!(d.itens||[]).length){
    h+=card('<div class="dim">Nenhum processo lido pelos dois caminhos ainda — rode <code>tools.sei_leitura_dupla</code>.</div>');
    alvo.innerHTML=h; o.appendChild(alvo); return;
  }
  h+=`<div class="grid g4">${kpi(fmtN(d.acordos),'Fatos em ACORDO','var(--green)','🤝',
      {sobre:'Regra e IA leram o mesmo valor: fato duplamente confirmado, ninguém precisa reler.'})}${
      kpi(fmtN(d.ausencias_concordes||0),'FORA da fila humana',null,'✔️',
      {sobre:'Fatos que não estão na fila, por motivos DIFERENTES — e a quebra abaixo importa porque nem todos são "resolvido". Resolvidos: os dois leitores dizem que o campo não existe; o documento DECLARA que não há; o ranque de valor é decidido por aritmética; a Ordem Bancária já resolveu quem recebeu. NÃO resolvido: `nao_perguntado` — a leitura é anterior ao campo (arp, tac, valor e favorecido entraram depois), então a IA nunca foi perguntada. Isso é falta de MEDIDA, não concordância, e some quando o processo for relido.'})}${
      kpi(fmtN(d.discordancias),'DISCORDÂNCIAS — a fila','var(--amber)','⚖️',
      {sobre:'Onde os dois leitores divergem. Não é veredito: é o único lugar em que o tempo de um humano rende, porque ali ou a nossa régua é estreita ou o modelo inventou.'})}${
      kpi(fmtN(d.total),'Processos lidos 2×',null,'📖',
      {sobre:'Cada um lido por regex e por IA gratuita. Processo marcado como truncado foi lido em parte — omissão ali não é ausência.'})}</div>`;
  const est=d.por_estado||{};
  h+=card(`<div class="dim">por tipo de divergência: `
    +Object.entries(est).map(([k,v])=>`<b>${esc(k)}</b> ${fmtN(v)}`).join(' · ')+`</div>`);
  /* O QUE SAIU DA FILA, E POR QUÊ. Chamar tudo de "ausência" deixou de ser verdade quando o
     comparador passou a resolver por aritmética e por fonte canônica — número certo com rótulo
     errado é o mesmo vício de somar o que não se soma. */
  const _fora=d.fora_da_fila_por_motivo||{};
  /* CADA ESTADO PRECISA DE NOME, e a rota já devolve SETE. Chave crua na tela é o mesmo vício de
     rótulo que agrega o que não se agrega — só que pior, porque não diz nada. Três destes medem o
     DESENHO, não o acervo, e o texto diz isso: campo criado depois, pergunta sem resposta única, e
     texto que a IA nem chegou a ler. */
  const _nome={nenhum_dos_dois:'nenhum dos dois achou',ausencia_declarada:'o documento declara que NÃO HÁ',
               ia_errou_o_maior:'ranque de valor — aritmética decide',so_fonte_canonica:'a Ordem Bancária já resolveu',
               ia_corroborada_pela_ob:'a Ordem Bancária confirma a IA',
               varios_instrumentos:'o processo cita VÁRIOS — a pergunta não tem resposta única',
               fora_da_janela_da_ia:'⚠️ o valor está além do texto que a IA leu',
               nao_perguntado:'⚠️ campo criado DEPOIS da leitura — a IA não foi perguntada'};
  if(Object.keys(_fora).length) h+=card(`<div class="dim">fora da fila, por motivo: `
    +Object.entries(_fora).sort((a,b)=>b[1]-a[1])
      .map(([k,v])=>`<b>${fmtN(v)}</b> ${esc(_nome[k]||k)}`).join(' · ')+`</div>`);
  /* A RÉGUA MUDOU NO MEIO DA MEDIÇÃO, e somar as duas em silêncio seria mentir por omissão:
     as leituras anteriores a 2026-08-13 contavam "os dois dizem que não existe" como
     DIVERGÊNCIA, então a fila delas está inflada e não é comparável com as novas. */
  if(d.medidos_com_regua_antiga>0) h+=card(`<div class="dim">⚠️ <b>${fmtN(d.medidos_com_regua_antiga)}</b> de ${fmtN(d.total)} processos foram medidos com a RÉGUA ANTIGA, que contava ausência concorde como divergência — a fila deles está inflada e não é comparável com as leituras novas.</div>`);
  /* O QUE FALTA NOS AUTOS. 354 dos 397 processos lidos trazem essa lista e NENHUMA rota a
     consumia — o dado existia, custou chamada de IA e morria no banco. Boa parte vem do CHECKLIST
     DO PRÓPRIO ÓRGÃO, declarando que Cópia do Contrato, Folha de Medição e Relatório dos Fiscais
     não estão lá: documento que prova execução faltando num processo de PAGAMENTO. */
  const _fal=d.documentos_que_mais_faltam||[];
  if(_fal.length) h+=card(`<div><b>${fmtN(d.processos_com_lacuna||0)}</b> processos declaram documento AUSENTE nos autos`
    +`<div class="dim" style="margin-top:6px">`
    +_fal.slice(0,6).map(([doc,n])=>`<b>${fmtN(n)}×</b> ${esc(String(doc).slice(0,70))}`).join('<br>')
    +`</div></div>`);
  h+=card(`<table class="tb"><thead><tr><th>processo</th><th class="right">acordo</th>
    <th class="right">divergência</th><th>o que a IA entendeu</th></tr></thead><tbody>`
    +d.itens.map(x=>`<tr>
      <td>${esc(x.processo)}${x.truncado?' <span class="dim">(truncado)</span>':''}</td>
      <td class="right">${fmtN(x.acordo)}</td>
      <td class="right">${x.discordancia>2?'<b>':''}${fmtN(x.discordancia)}${x.discordancia>2?'</b>':''}</td>
      <td style="font-size:12px">${esc(String(x.o_que_e||'—').slice(0,120))}${
        (x.o_que_falta||[]).length
          ? `<div style="color:var(--amber);margin-top:3px">falta nos autos: ${
              esc((x.o_que_falta||[]).slice(0,3).join(' · ').slice(0,150))}</div>`
          : ''}</td>
    </tr>`).join('')
    +`</tbody></table>`)+leitura(esc(d.ressalva||''));
  alvo.innerHTML=h; o.appendChild(alvo);
}

async function zerosSemCausa(){
  const o=$('ff-out'); if(!o) return;
  const d=await J('/api/fiscal/zeros_sem_causa?limite=12');
  if(!d||d.ok===false) return;
  const alvo=document.createElement('div');
  let h=sec(`Processos lidos que voltaram VAZIOS — fila de diligência (${fmtN(d.fila_total||d.total)})`);
  if(!(d.itens||[]).length){
    h+=card('<div class="dim">Nenhum processo zerado sem causa — todo zero do acervo tem motivo registrado.</div>');
    alvo.innerHTML=h; o.appendChild(alvo); return;
  }
  h+=`<div class="grid g3">${kpi(fmtRc(d.valor_ob_fornecedor!=null?d.valor_ob_fornecedor:d.valor_ob_sem_causa),'OB a FORNECEDOR atrás da fila','var(--rose)','💸',
      {sobre:'Soma das ordens bancárias <b>contabilizadas</b> a CNPJ/CPF nos processos que a casa leu e não trouxe nada. Não é irregularidade: é a medida do que ainda não foi possível examinar.'
        +(d.valor_ob_folha?' Fora desta conta ficam <b>'+fmtRc(d.valor_ob_folha)+'</b> de folha de pagamento e previdência (credor genérico: FOLHA DE PAGAMENTOS, RIOPREV)':'')
        +(d.valor_ob_publico?' e <b>'+fmtRc(d.valor_ob_publico)+'</b> de repasse a ente público (fundo municipal de saúde, Ministério da Fazenda), que tem CNPJ mas não é contratação':'')
        +((d.valor_ob_folha||d.valor_ob_publico)?' — publicá-los junto superestimaria a exposição fiscalizável.':'')})}${
      kpi(fmtN(d.total),'Sem causa nenhuma',null,'❓',
      {sobre:'Zero documento e nenhum motivo — nem no registro de restritos, nem no progresso do sweep. É o balde de ignorância propriamente dito.'})}${
      kpi(fmtN(d.caixa_leitura_falhou||0),'CAIXA: a leitura FALHOU','var(--amber)','🚫',
      {sobre:'O SEI devolveu a <b>caixa de entrada</b> (mais de 15 relacionados) em vez do processo — pela própria regra do sweep, isso é leitura falha, não processo vazio. A causa estava gravada no progresso o tempo todo; até 2026-08-11 esses casos eram contados como “sem causa”.'})}</div>`;
  h+=card(`<div class="dim">De ${fmtN(d.zeros)} zerados em ${fmtN(d.processos_com_registro)} processos com registro de leitura.</div>`);
  h+=card(`<table class="tb"><thead><tr><th>causa</th><th class="right">processos</th></tr></thead><tbody>`
    +Object.entries(d.por_causa||{}).map(([k,v])=>`<tr><td>${esc(k)}</td><td class="right">${fmtN(v)}</td></tr>`).join('')
    +`</tbody></table>`);
  if((d.contradicao||[]).length){
    h+=card(`<div><b>${fmtN(d.contradicao.length)} em contradição</b> — o registro diz que a leitura foi OK
      e mesmo assim não veio documento nem há arquivo. Se dá para ler, o zero é falha nossa:
      <span class="dim">${d.contradicao.map(p=>esc(p)).join(' · ')}</span></div>`);
  }
  h+=card(`<table class="tb"><thead><tr><th>processo</th><th class="right">OB a fornecedor</th><th>causa</th>
    <th class="right">tentativas</th></tr></thead><tbody>`
    +d.itens.map(x=>`<tr><td>${esc(x.processo)}${x.eh_folha?' <span class="dim">(folha/previdência)</span>':''}</td>
      <td class="right">${fmtRc(x.valor_ob_fornecedor!=null?x.valor_ob_fornecedor:x.valor_ob)}</td>
      <td class="dim">${esc(x.causa||'—')}</td>
      <td class="right">${x.esgotou_tentativas
        ? `<b title="o sweep desistiu: repetir a mesma leitura não muda o resultado — precisa de outro caminho (CRACKED, VM-2, pedido formal)">${fmtN(x.tentativas||0)} ⛔</b>`
        : `<span class="dim">${fmtN(x.tentativas||0)}</span>`}</td></tr>`).join('')
    +`</tbody></table>`)+leitura(esc(d.ressalva||''));
  alvo.innerHTML=h; o.appendChild(alvo);
}

async function nucleoCartel(){
  const o=$('ff-out'); if(!o) return;
  const d=await J('/api/fiscal/nucleo_cartel?limite=10');
  if(!d||d.ok===false) return;
  const alvo=document.createElement('div');
  let h=sec(`Núcleo de arranjo — generalista orbitado (${fmtN(d.total)} de ${fmtN(d.n_contumazes)} contumazes)`);
  if((d.itens||[]).length){
    h+=card(`<table class="tb"><thead><tr><th>Vencedor generalista</th><th class="right">ramos</th>
      <th class="right">vitórias</th><th class="right">municípios</th>
      <th>perdedores contumazes na órbita</th></tr></thead><tbody>`
      +d.itens.map(x=>`<tr>
        <td>${esc((x.vencedor||'').slice(0,38))}${x.so_estrutural?' <span class="dim">(FP estrutural provável)</span>':''}</td>
        <td class="right">${x.n_ramos}</td><td class="right">${fmtN(x.vitorias)}</td>
        <td class="right dim">${x.n_entes}</td>
        <td style="font-size:12px">${(x.orbitantes||[]).map(o0=>
          `${esc((o0.perdedor||'').slice(0,26))} <span class="dim">${o0.n}p/${o0.vitorias}v · órbita ${o0.conc}%</span>`).join('<br>')}</td></tr>`).join('')
      +`</tbody></table>`);
  } else if((d.fonte||{}).ok===false){
    h+=vazioDeclarado(d,'núcleo de arranjo');
  } else {
    h+=card('<div class="dim">Nenhum núcleo com os pisos atuais — o que não é ausência de arranjo, é ausência de INTERSEÇÃO entre os dois screens.</div>');
  }
  if((d.viajantes||[]).length){
    h+=card(`<div class="dim" style="margin-bottom:6px"><b>Licitante-viajante</b> — contumaz em três ou mais
      municípios: o custo de participar sem expectativa de ganhar é o sinal.</div>`
      +(d.viajantes||[]).slice(0,6).map(v=>
        `<div class="kv"><span class="k">${esc((v.perdedor||'').slice(0,42))}</span><b>${v.n_entes} municípios</b>
         <span class="dim">${v.n} part / ${v.vitorias} vit</span></div>`).join(''));
  }
  h+=leitura(esc(d.ressalva||''));
  alvo.innerHTML=h; o.appendChild(alvo);
}

// UM VEÍCULO POR CERTAME. A concentração por grupo diz QUANTO um grupo leva numa unidade; o quadro
// societário diz COMO a diversidade de CNPJs se forma — consórcios constituídos um a um, com as
// mesmas empresas dentro e o mesmo administrador. E o alcance atravessa unidades, que o recorte
// por UG não mostra. Consórcio é lícito (art. 15); o que se lê aqui é a REPETIÇÃO.
async function consorcioVeiculo(){
  const o=$('ff-out'); if(!o) return;
  const d=await J('/api/fiscal/consorcio_veiculo?limite=10');
  if(!d||d.ok===false) return;
  const alvo=document.createElement('div');
  if(!(d.itens||[]).length){
    alvo.innerHTML=sec('Um consórcio por certame')
      +vazioDeclarado(d,'administrador com mais de um consórcio pago');
    o.appendChild(alvo); return;
  }
  alvo.innerHTML=sec(`Um consórcio por certame — administrador com vários veículos (${fmtN(d.total)})`)
    +card(`<table class="tb"><thead><tr><th>Administrador</th><th class="right">consórcios</th>
      <th class="right">nos veículos</th><th class="right">+ diretas</th>
      <th class="right">UGs</th><th>núcleo presente em TODOS</th></tr></thead><tbody>`
      +d.itens.map(x=>`<tr>
        <td>${esc((x.administrador||'').slice(0,34))}</td>
        <td class="right" style="font-weight:800;color:${x.n_consorcios>=4?'var(--red)':(x.n_consorcios>=3?'var(--amber)':'inherit')}">${x.n_consorcios}</td>
        <td class="right">${fmtRc(x.total)}</td>
        <td class="right dim">${(x.total_com_diretas||x.total)>x.total?fmtRc(x.total_com_diretas-x.total):'—'}
          ${(x.empresas_diretas||[]).length?`<span class="dim" style="font-size:11px">${(x.empresas_diretas||[]).length} empresa(s)</span>`:''}</td>
        <td class="right dim">${x.n_ugs}</td>
        <td style="font-size:12px">${(x.nucleo_comum||[]).map(n=>esc(n.slice(0,30))).join('<br>')||'<span class="dim">—</span>'}</td></tr>`).join('')
      +`</tbody></table>`)
    +leitura(esc(d.ressalva||''));
  o.appendChild(alvo);
}

// ═══ LENTES CRUZADAS — quando o mesmo CNPJ acende em mais de um detector ═══
// Aba nova (2026-08-22). Existe porque as quatro lentes construídas em 08/2026 eram CLI-only —
// nenhuma tinha caller, o 7º caso de "construído, testado, nunca rodado" da casa. A rota
// `/api/lentes` lê JSON materializado (as lentes somam ~31 s; calcular na rota travaria o painel).
// O que ela mostra e as outras não: a CONVERGÊNCIA. Cada lente sozinha devolve centenas de
// empresas; o cruzamento é que ordena a fila.
export const _DIM_ROTULO={TAMANHO:'porte × pago',SANCAO:'sanção vigente',DEPENDENCIA:'dependência mútua'};
export async function renderLentes(){
  let h=cover('estado','Lentes cruzadas',
    'Quatro detectores independentes sobre a mesma base de pagamento (OB SIAFE). O que ordena a fila não é acender numa lente — é acender em <b>mais de uma</b>.','🔬');
  let d;
  try{ d=await J('/api/lentes?top=40'); }
  catch(e){ return h+card(`<div class="warn">${esc(String(e&&e.message||e))}</div>`); }
  if(!d||d.ok===false)return h+card(`<div class="warn">${esc((d&&d.erro)||'lentes não materializadas')} — rode <code>tools/lentes_materializar.py</code>.</div>`);
  const L=d.lentes||{};
  const conv=(L.convergencia&&L.convergencia.topo)||[];
  const mult=conv.filter(x=>x.n_dim>=2);
  // DIMENSÃO ≠ DETECTOR: `porte` e `estrutura magra` medem a mesma coisa (empresa pequena demais
  // para o que recebe) e contam UMA vez. Contá-las separado inflou "15 empresas em 3 lentes" para
  // um número que virou 0 quando a duplicidade saiu — o erro está registrado no vault.
  h+=`<div class="grid g2">
    ${kpi(fmtN(mult.length),'Empresas em 2+ dimensões','var(--rose)','🎯',{sobre:'Convergência de detectores independentes. <b>Dimensão não é detector</b>: porte e estrutura magra medem a mesma coisa e contam uma vez só.'})}
    ${kpi(fmtRc(mult.reduce((s,x)=>s+(x.pago||0),0)),'Pago a essas empresas','var(--amber)','💸',{sobre:'Soma das OB <b>Contabilizado</b> do SIAFE — pagamento efetivo, não empenho.'})}
    ${kpi(fmtN((L.convergencia&&L.convergencia.n)!=null?L.convergencia.n:'—'),'Marcadas por ao menos 1','var(--dim)','🔎',{sobre:'Total de empresas que acenderam em <b>alguma</b> das lentes — a base de onde sai a convergência. Acender numa lente sozinha <b>não é achado</b>: 93,9% estão nesse caso, e é por isso que a fila se ordena pelo cruzamento, não pelo total. Vem do JSON materializado, não da tela: por isso não tem gaveta.'})}
    ${kpi(esc((d.gerado_em||'').replace('T',' ').slice(0,16)),'Materializado em',null,'🕒',{sobre:'A rota LÊ um JSON; ela não calcula. As quatro lentes somam ~31 s de varredura sobre a OB inteira.'})}
  </div>`;
  h+=leitura('Convergência <b>ordena</b>, não acusa. Cada dimensão carrega as ressalvas da própria lente: porte da Receita pode estar desatualizado, dependência alta é esperada em serviço essencial com operador único, e sanção de outro ente pode não alcançar o contrato estadual.');
  h+=sec('Em mais de uma dimensão');
  h+=mult.length?mult.map(x=>card(`<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
      <div style="min-width:0">${clk(x.cnpj_basico,x.razao_social||x.cnpj_basico)}
        <div class="dim">${(x.dimensoes||[]).map(k=>`<span class="sev ${x.n_dim>=3?'alta':'media'}">${esc(_DIM_ROTULO[k]||k)}</span>`).join(' ')}</div>
        <div class="muted" style="font-size:12.5px;margin-top:4px">${esc((x.porques||[]).join(' · '))}</div></div>
      <div class="right"><div class="num"><b>${fmtRc(x.pago)}</b></div><div class="dim">${fmtN(x.n_dim)} dimensões</div></div></div>`,x.n_dim>=3?'hl':'')).join('')
    :card('<div class="muted">Nenhuma empresa em duas dimensões nesta materialização.</div>');
  // As três lentes por baixo, para conferência: o número da convergência só é auditável se o
  // usuário puder ver de onde cada dimensão veio.
  const _blocos=[
    ['dependencia_mutua','Dependência mútua','Fornecedor com 95%+ do que recebe vindo de UMA unidade, E que pesa 5%+ no orçamento dela. Repasse fundo-a-fundo, folha e OSS ficam de fora — contrato de gestão não é captura.',
      x=>`${clk(x.cnpj,x.nome)}<div class="dim">UG ${esc(x.ug)} · ${(100*x.concentracao).toFixed(0)}% dele · ${(100*x.fatia_ug).toFixed(1)}% dela</div>`,x=>x.pago_ug],
    ['porte_incompativel','Porte × pago','Empresa declarada ME/EPP que recebeu acima do teto legal de faturamento do próprio porte (LC 123/2006, art. 3º) num único ano.',
      x=>`${clk(x.cnpj_basico,x.razao_social)}<div class="dim">${esc(x.porte)} · ${esc(x.ano)} · ${x.razao_teto>=1?x.razao_teto.toFixed(0)+'× o teto':'—'}</div>`,x=>x.pago],
    ['pericia_tripla','Perícia tripla: jurídica · forense · financeira',
      'Ordena <b>processos</b> por <b>lacuna probatória</b> — o que deveria estar nos autos e não está —, lendo o campo <i>o_que_falta</i> da leitura dupla, que <b>nomeia o documento ausente</b>. Só entram processos de <b>captura completa</b> (docs ≥ árvore, sem lacuna declarada): sem esse corte, falta da NOSSA coleta viraria acusação contra a Administração. Ordenado por <b>gravidade</b>, não por contagem: falta de pesquisa de preços (3,9%) pesa 5; falta de instrumento (54,8%, e lícita no art. 95) pesa 1. Sinal raro ordena, sinal comum descreve.',
      x=>`${clk('',x.numero_sei)}<div class="dim">peso ${fmtN(x.peso)} · ${esc((x.lentes||[]).join('+'))} · ${esc((x.credor||'').slice(0,26))}</div><div class="muted" style="font-size:12px">${esc((x.falta||'').slice(0,130))}</div>`,x=>x.pago],
    ['pago_sem_contrato','Pago sem contrato (leitura dos autos)',
      'Única lente que vem do <b>texto</b>: lê a interpretação que a IA grava no confronto duplo e isola os processos em que ela aponta <b>ausência de contrato ou instrumento</b> — a citação típica é da própria nota de empenho, <i>&quot;Contrato 00000000 - SEM CONTRATO&quot;</i>. <b>Pagar sem contrato é lícito</b> em compra de entrega imediata (Lei 14.133, art. 95), e folha, tarifa, tributo, repasse e precatório ficam FORA por natureza. Sobra o núcleo em que o instrumento era esperado. Só vê o que foi lido: 3.256 de 221.130 processos com OB paga.',
      x=>`${clk('',x.numero_sei)}<div class="dim">${esc((x.credor||'').slice(0,30))} · ${fmtN(x.n_obs)} OB</div><div class="muted" style="font-size:12px">${esc((x.o_que_e||'').slice(0,120))}</div>`,x=>x.pago],
    ['contrato_acima_do_porte','Contrato acima do teto do porte',
      'Contrato <b>celebrado</b> com ME/EPP cujo valor supera o teto de receita do próprio porte (LC 123/2006, art. 3º). É o critério <b>legal na forma literal</b>: a Lei 14.133 fala em contratos celebrados no ano-calendário, não em dinheiro recebido. Fonte: espelho de contratos do <b>próprio TCE-RJ</b>, que cobre <b>51% dos fornecedores</b> pagos acima de R$ 1 mi — o resultado é <b>PISO</b>, e a ausência aqui não diz nada sobre a empresa. Prevalência 1,87% do cadastro ME/EPP. <b>Valor contratado não é valor executado</b> — esta lente mede incompatibilidade no dia da assinatura, não dano.',
      x=>`${clk(x.cnpj_basico,x.nome)}<div class="dim">${esc(x.porte)} · ${x.razao_teto>=1?fmtN(Math.round(x.razao_teto))+'× o teto':''} · ${fmtN(x.n_contratos)} contrato(s)${(x.contratos||[]).length?' · '+esc(x.contratos[0].data)+' '+esc((x.contratos[0].unidade||'').slice(0,30)):''}</div>`,x=>x.maior],
    ['troca_de_controle','Trocou de dono durante a execução',
      'Empresa cujo quadro de sócios mudou <b>por inteiro</b> durante a janela de pagamentos: nenhum sócio de hoje estava lá quando saiu o primeiro pagamento. <b>Trocar de dono é lícito</b> — o achado é a pergunta (a habilitação do novo controlador foi examinada?), não a resposta. Corte forte: 7,1% do universo; qualquer saída marcaria 21,6% e não ordenaria fila. Histórico começa em 03/2023 — troca anterior é invisível, e ausência aqui é limite de fonte.',
      x=>`${clk(x.cnpj_basico,x.nome)}<div class="dim">${esc(x.primeiro_pagamento)} → ${esc(x.ultimo_pagamento)} · ${fmtN((x.saidas||[]).length)} saída(s)${(x.saidas||[]).length?' · saiu '+esc(x.saidas[0].quando)+' '+esc((x.saidas[0].nome||'').slice(0,28)):''}</div>`,x=>x.pago],
    ['porte_declarado_certame','Declarou-se pequena depois de estourar o teto',
      'Empresa que se declarou ME/EPP/MEI em certame publicado <b>depois</b> de já ter recebido do Estado, naquele mesmo ano-calendário, acima do teto de EPP (R$ 4,8 mi — LC 123/2006, art. 3º). O TCU firmou que a declaração falsa de porte já é fraude à licitação, ainda que não haja vantagem concreta. Número é PISO: só o pago pelo Estado entra, e o PNCP capturado cobre 2024-2026/RJ.',
      x=>`${clk(x.cnpj_basico,x.nome)}<div class="dim">${esc((x.portes||[]).join('/'))} · ${fmtN(x.n_certames)} certame(s) · já recebera ${fmtRc(x.recebido_pico)} no ano</div>`,x=>x.homologado],
    ['pago_a_sancionado','Pago sob sanção','Pagamento (OB) emitido dentro da vigência de sanção que restringe contratar. Ver a aba <b>Sancionadas</b> para o detalhe por empresa.',
      x=>`${clk(x.cnpj,x.nome)}<div class="dim">${esc((x.categoria||'').slice(0,64))}</div>`,x=>x.pago_durante||x.pago||0],
  ];
  for(const [chave,titulo,nota,linha,valor] of _blocos){
    const b=L[chave]||{};
    h+=sec(titulo);
    if(b.ok===false){ h+=card(`<div class="warn">INDISPONÍVEL — a lente falhou ao materializar: ${esc(b.erro||'')}</div>`); continue; }
    // `n` nulo é INDISPONÍVEL, e a tela DIZ isso; nunca imprimir 0, que é uma afirmação.
    h+=`<div class="dim" style="margin:0 2px 6px">${esc(nota)} — ${b.n==null?'<b>INDISPONÍVEL</b>':fmtN(b.n)+' no total, mostrando '+fmtN((b.topo||[]).length)}</div>`;
    h+=(b.topo||[]).slice(0,12).map(x=>card(`<div style="display:flex;justify-content:space-between;gap:10px"><div style="min-width:0">${linha(x)}</div><div class="right"><b>${fmtRc(valor(x))}</b></div></div>`)).join('');
  }
  h+=`<div class="note">${esc(d.aviso||'')}</div>`;
  return h;
}
