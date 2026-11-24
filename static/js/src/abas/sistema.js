/* SISTEMA — configurações e funcionamento do JFN, numa esfera própria.

   Pedido do dono (14/11/2026): "coloque uma outra aba (configurações e funcionamento do sistema) e
   mova o que for disso." O Início e o Transversal misturavam o que o JFN ACHA (riscos, casos,
   alertas) com como o JFN FUNCIONA (motores rodando, coletas, instrumentação, regras de qualidade,
   concordância entre modelos). Esta aba junta a segunda parte: a grade de motores, o cruzamento de
   motores, o frescor das fontes e as funções mestras saíram do Início para cá.

   Custo de API e uso da assinatura NÃO aparecem (dono, 14/11: "isso polui"). */
import {$, esc, svgIco, card, cover} from '../nucleo/dom.js';
import {J} from '../nucleo/http.js';
import {a11yfy} from '../ui/index.js';
import {aoVivoLigar} from '../aovivo/estado.js';
import {motoresMontar} from '../ui/aovivo.js';
import {cruzamentoMontar, conferenciaMontar} from './motores_cruzamento.js';
import {conciliacaoMontar} from './conciliacao_ob.js';

/* O `ir()` pinta o HTML depois que o render resolve (às vezes dentro de uma View Transition), e só
   o cockpit tem gancho pós-pintura. Aqui se espera o nó existir, quadro a quadro, por até ~3 s. */
function _quandoExistir(id, fn, tentativas = 180) {
  const el = document.getElementById(id);
  if (el) { fn(el); return; }
  if (tentativas > 0) requestAnimationFrame(() => _quandoExistir(id, fn, tentativas - 1));
}

/* ══ v49 · UM BOTÃO POR FUNÇÃO MESTRA (pedido do dono) ══════════════════════════════════════════
   A lista vem de `CAPS_MESTRAS` (static/js/caps.js), GERADA de capabilities.yaml pelo
   tools/gerar_superficie_caps.py. Escrever os botões aqui à mão criaria a quinta cópia da mesma
   lista — e a casa já tem cicatriz de lista duplicada divergindo em silêncio.

   As rotas aparecem como string literal no arquivo gerado de propósito: é assim que as duas
   catracas de rota (órfãs, teto 0; e sem-superfície) enxergam que a capacidade tem porta de
   entrada. Fosse `fetch('/api/lista')` em runtime, elas acusariam órfãs que não são órfãs. */
/* Frescor das fontes — saiu do Início para a esfera Sistema em 14/11/2026 (pedido do dono). */
function frescorMontar(box){
  J('/api/fontes/frescor').then(d=>{if(!box||!box.isConnected||!d||!d.fontes)return;
    const cor=f=>{const s=(f.estado||'').toLowerCase();if(s.includes('verde')||s.includes('ok')||s.includes('fresc'))return '#5fe0a1';
      if(s.includes('amar')||s.includes('aten')||s.includes('velh'))return '#f2b544';if(s.includes('verm')||s.includes('erro')||s.includes('crit'))return '#ff7a8a';
      return f.idade_dias==null?'#63718f':(f.idade_dias<=2?'#5fe0a1':(f.idade_dias<=10?'#f2b544':'#ff7a8a'));};
    box.innerHTML=`<div class="ck-flabel">Fontes de dados — frescor ao vivo</div><div class="ck-fgrid">`+
      d.fontes.map(f=>`<div class="ck-fchip" title="${esc(f.detalhe||'')}"><span class="fled" style="background:${cor(f)}"></span>
        <span class="fnm">${esc((f.fonte||'').replace(/·/g,'·'))}</span><span class="fage">${f.idade_dias==null?'—':f.idade_dias+'d'}</span></div>`).join('')+`</div>`;});
}
function blocoComandosMestres(){
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

export async function renderMotoresSistema() {
  aoVivoLigar();
  _quandoExistir('s-motores', motoresMontar);
  _quandoExistir('s-conf', conferenciaMontar);
  _quandoExistir('s-cruz', cruzamentoMontar);
  _quandoExistir('s-fontes', frescorMontar);
  _quandoExistir('s-conc', conciliacaoMontar);
  return cover('sistema', 'Motores — o que está rodando e se os modelos concordam',
    'Estado de cada motor do JFN (rodando, com falha, agendado, sem efeito) e o cruzamento entre o Claude e os outros modelos. Clique num motor para ver os eventos da última hora. Rota que não responde é INDISPONÍVEL, nunca zero.', '⚙️')
    + '<section class="c61-motores" id="s-motores" aria-labelledby="c61-motores-t"></section>'
    + '<div class="ck-fontes" id="s-fontes" style="margin-top:18px"></div>'
    + '<section class="c61-cruz" id="s-conf" aria-label="Conferência do Opus" style="margin-top:18px"></section>'
    + '<section class="c61-cruz" id="s-cruz" aria-label="Cruzamento de motores" style="margin-top:18px"></section>'
    + '<section id="s-conc" aria-label="Conciliação OB do SIAFE × espelho TFE" style="margin-top:18px"></section>';
}

/* "Funções mestras" — os comandos de capabilities.yaml, que ficavam no rodapé do Início. */
export async function renderComandosSistema() {
  return cover('sistema', 'Comandos — as funções mestras do JFN',
    'Cada botão é uma capacidade pronta (capabilities.yaml), a mesma que o Yoda atende no Telegram. Nada é disparado sem a sua decisão.', '🧭')
    + (blocoComandosMestres() || '<div class="dim">Lista de comandos INDISPONÍVEL nesta carga.</div>');
}
