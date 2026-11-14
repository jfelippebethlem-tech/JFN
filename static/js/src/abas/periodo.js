// ═══ POR ANO E MÊS — seletor Ano/Mês + quebra ano → mês, um componente para todas as abas ═══
// Pedido do dono (13/11/2026): "coloca em tudo organização por ano e mês também. pagamentos e contratações etc."
// Diretriz: "não pode ter margem pra erro em nada". Por isso:
//  · o NÚMERO vem fechado do servidor (`compliance_agent/periodo.py`, somado em centavos, Σ meses = ano = total
//    conferido antes de responder) — aqui nada é somado, só desenhado;
//  · mês sem registro aparece como 0 só se a fonte COBRE aquele mês; senão INDISPONÍVEL;
//  · cada fonte diz que data usa (emissão da OB, assinatura do contrato, publicação no DOERJ…), a medida
//    (pago = só OB Contabilizada; empenho ≠ liquidação ≠ pagamento; contratado ≠ pago) e a cobertura;
//  · o filtro (ano, mês) é UM só no painel inteiro: escolhido numa aba, vale nas outras.
// A aba chama `blocoPeriodo(['ob_siafe', …])`, que devolve um marcador; o bloco se preenche sozinho quando o
// marcador entra na tela (a aba não espera a quebra para abrir).
import {esc, card, sec} from '../nucleo/dom.js';
import {J, erroHumano} from '../nucleo/http.js';
import {fmtN, fmtR} from '../nucleo/formato.js';

const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const MESES_L = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro',
  'outubro', 'novembro', 'dezembro'];
const ESFERA = {estado: 'Estado do RJ', prefeitura: 'Prefeitura do Rio', transversal: 'Transversal'};
const _CHAVE = 'jfn.periodo';

let _P = {ano: '', mes: ''};
function _ler(){   // chamada por ligarPeriodo() na sequência de boot — módulo sem efeito de topo
  try { const s = JSON.parse(sessionStorage.getItem(_CHAVE) || 'null'); if (s && typeof s === 'object') _P = {ano: String(s.ano || ''), mes: String(s.mes || '')}; } catch (e) { /* sem storage: filtro vale só nesta visita */ }
}
const _salvar = () => { try { sessionStorage.setItem(_CHAVE, JSON.stringify(_P)); } catch (e) { /* idem */ } };

let _seq = 0;
const _blocos = new Map();      // id → [fontes]

export function periodoAtual(){ return {ano: _P.ano, mes: _P.mes}; }

/* Marcador do bloco. `titulo` opcional; as fontes são ids de `compliance_agent/periodo_fontes.py`. */
export function blocoPeriodo(fontes, titulo){
  const id = 'per-' + (++_seq);
  _blocos.set(id, fontes);
  _quandoNaTela(id);
  return `<div style="height:16px"></div>${sec(titulo || 'Por ano e mês')}<section class="per" id="${id}" aria-live="polite">
    <div class="skel"><span class="sp"></span>Montando a quebra por ano e mês…</div></section>`;
}

function _quandoNaTela(id, n = 0){
  const el = document.getElementById(id);
  if (el) { _pintar(id); return; }
  if (n < 200) setTimeout(() => _quandoNaTela(id, n + 1), 50);   // a aba ainda não pôs o HTML na tela
  else _blocos.delete(id);                                       // a aba trocou antes: o bloco morreu junto
}

const _qs = () => (_P.ano ? `?ano=${encodeURIComponent(_P.ano)}${_P.mes ? '&mes=' + encodeURIComponent(_P.mes) : ''}` : '');

async function _pintar(id){
  const fontes = _blocos.get(id); if (!fontes) return;
  const el = document.getElementById(id); if (!el) return;
  const rs = await Promise.all(fontes.map(f => J('/api/periodo/' + f + _qs(), {tetoMs: 90000})));
  const el2 = document.getElementById(id); if (!el2) return;     // trocou de aba durante a espera
  const anos = new Set();
  rs.forEach(r => r && r.ok && (r.quebra.anos || []).forEach(a => anos.add(a.ano)));
  el2.innerHTML = _seletor([...anos].sort((a, b) => b - a)) + rs.map((r, i) => _fonte(r, fontes[i])).join('');
}

function _seletor(anos){
  if (_P.ano && !anos.includes(Number(_P.ano))) anos = [Number(_P.ano), ...anos];
  const oA = `<option value="">Todos os anos</option>` + anos.map(a => `<option value="${a}"${String(a) === _P.ano ? ' selected' : ''}>${a}</option>`).join('');
  const oM = `<option value="">Todos os meses</option>` + MESES_L.map((m, i) => `<option value="${i + 1}"${String(i + 1) === _P.mes ? ' selected' : ''}>${m}</option>`).join('');
  return `<div class="per-sel" role="group" aria-label="Filtrar por ano e mês">
    <label>Ano <select class="inp" data-per-ano>${oA}</select></label>
    <label>Mês <select class="inp" data-per-mes${_P.ano ? '' : ' disabled title="escolha o ano primeiro"'}>${oM}</select></label>
    ${_P.ano ? `<button type="button" class="btn ghost" data-per-limpar>Limpar filtro</button>` : ''}
    <span class="dim per-nota">O filtro vale para todas as abas. Toque num mês da tabela para filtrar por ele.</span></div>`;
}

/* Situação de uma célula. O vocabulário é o do servidor: ok | parcial | zero | indisponivel. */
const _TAG = {parcial: '<span class="tag amber" title="cobertura parcial — o número é PISO">parcial</span>',
  zero: '<span class="tag" title="a fonte cobre o período e não há registro">sem registro</span>',
  indisponivel: '<span class="tag" title="a fonte não cobre este período — não é zero">INDISPONÍVEL</span>'};
const _val = (b, k) => (b.v == null ? '<span class="dim">—</span>' : fmtR(b.v[k]));

function _linha(f, b, cab, ir, on, cls){
  const ind = b.status === 'indisponivel';
  const cel = ind ? `<td colspan="${1 + f.medidas.length}" class="dim">INDISPONÍVEL</td>`
    : `<td class="right num">${b.n == null ? '—' : fmtN(b.n)}</td>${f.medidas.map(k => `<td class="right num">${_val(b, k)}</td>`).join('')}`;
  const c = [cls, ir ? 'per-ir' : '', on ? 'on' : ''].filter(Boolean).join(' ');
  return `<tr${c ? ` class="${c}"` : ''}${ir ? ` data-per-ir="${ir}" tabindex="0" title="filtrar por este período"` : ''}>
    <td>${cab} ${b.status === 'ok' || ind ? '' : (_TAG[b.status] || '')}</td>${cel}</tr>`;
}

function _fonte(r, fid){
  if (!r || !r.ok) return card(`<div class="warn">${erroHumano(r && r.erro)} — a quebra de <b>${esc(fid)}</b> está INDISPONÍVEL (não é zero).</div>`);
  const f = r.fonte, q = r.quebra, cob = r.cobertura || {}, sel = r.selecao || {}, fil = r.filtro || {};
  const cabMed = f.medidas.map(k => `<th class="right">${esc(f.rotulos_medidas[k] || k)}</th>`).join('');
  const thead = `<thead><tr><th>Período</th><th class="right">Registros</th>${cabMed}</tr></thead>`;
  let corpo = '';
  for (const a of [...q.anos].reverse()) {
    const aberto = fil.ano ? fil.ano === a.ano : a === q.anos[q.anos.length - 1];
    corpo += _linha(f, a, `<b>${a.ano}</b>`, `${a.ano}-0`, fil.ano === a.ano && !fil.mes, 'per-ano');
    if (a.meses && aberto) {
      for (const m of a.meses) corpo += _linha(f, m, `<span class="per-mes">${MESES[m.mes - 1]}/${a.ano}</span>`, `${a.ano}-${m.mes}`, fil.ano === a.ano && fil.mes === m.mes);
      if (a.sem_mes && a.sem_mes.n) corpo += _linha(f, {...a.sem_mes, status: 'ok'}, '<span class="per-mes dim">sem mês na fonte</span>');
    }
  }
  if (q.sem_data.n) corpo += _linha(f, {...q.sem_data, status: 'ok'}, '<span class="dim">Sem data na fonte</span>');
  const tfoot = `<tfoot><tr><td><b>Total geral</b></td><td class="right num"><b>${fmtN(q.total_geral.n)}</b></td>${f.medidas.map(k => `<td class="right num"><b>${fmtR(q.total_geral.v[k])}</b></td>`).join('')}</tr></tfoot>`;
  const anual = q.granularidade === 'ano' ? `<div class="per-aviso">Fonte <b>anual</b>: publica só o acumulado do exercício — não existe valor por mês, e o painel não inventa um.</div>` : '';
  const recorte = fil.ano ? _recorte(f, sel, r) : '';
  const extra = _extra(r.extra || {});
  return card(`<div class="per-cab"><div style="min-width:0"><div style="font-weight:700">${esc(f.rotulo)}</div>
      <div class="dim" style="font-size:12px">Data: <b>${esc(f.campo_data)}</b> · Fonte: ${esc(f.origem)}</div></div>
      <span class="tag ${f.esfera === 'prefeitura' ? 'teal' : f.esfera === 'estado' ? 'accent' : ''}">${esc(ESFERA[f.esfera] || f.esfera)}</span></div>
    ${recorte}${anual}
    <div class="per-tbw"><table class="per-tb">${thead}<tbody>${corpo}</tbody>${tfoot}</table></div>
    <div class="dim" style="font-size:12px;margin-top:6px"><b>Cobertura:</b> ${esc(cob.inicio || '?')} a ${esc(cob.fim || '?')}${(cob.anos_sem_coleta || []).length ? ` · exercícios NÃO coletados: ${cob.anos_sem_coleta.join(', ')}` : ''}. ${esc(cob.nota || '')}</div>${extra}`);
}

function _recorte(f, sel, r){
  if (sel.status === 'indisponivel') return `<div class="per-aviso"><b>${esc(sel.rotulo)}: INDISPONÍVEL</b> — ${esc(sel.motivo || 'a fonte não cobre este período')}. Não é zero.</div>`;
  const vals = f.medidas.map(k => `<div class="per-kv"><span>${esc(f.rotulos_medidas[k] || k)}</span><b class="num">${fmtR(sel.v[k])}</b></div>`).join('');
  let h = `<div class="per-sel-res"><div class="per-kv"><span>Recorte</span><b>${esc(sel.rotulo)}${sel.status === 'parcial' ? ' ' + _TAG.parcial : ''}${sel.status === 'zero' ? ' ' + _TAG.zero : ''}</b></div>
    <div class="per-kv"><span>Registros</span><b class="num">${fmtN(sel.n)}</b></div>${vals}</div>`;
  const it = r.itens || [];
  if (it.length) {
    const temV = it.some(x => x.valor != null);
    h += `<details class="per-top" open><summary><b>Maiores de ${esc(sel.rotulo)}</b> <span class="dim">(até ${fmtN(r.top)})</span></summary>
      <div class="per-tbw"><table class="per-tb"><tbody>${it.map(x => `<tr><td style="min-width:180px">${esc(x.nome)}${x.doc ? ` <span class="dim">${esc(x.doc)}</span>` : ''}
        ${x.orgao ? `<div class="dim" style="font-size:12px">${esc(x.orgao)}${x.data ? ' · ' + esc(String(x.data).slice(0, 10)) : ''}</div>` : ''}
        ${x.objeto ? `<div class="dim" style="font-size:12px">${esc(x.objeto)}</div>` : ''}</td>
        <td class="right num">${x.n != null ? fmtN(x.n) + ' reg.' : ''}</td>${temV ? `<td class="right num"><b>${x.valor == null ? '—' : fmtR(x.valor)}</b></td>` : ''}</tr>`).join('')}</tbody></table></div></details>`;
  } else if (r.itens) {
    h += `<div class="dim" style="font-size:12px;margin:4px 0 8px">${f.granularidade === 'ano' && _P.mes ? 'Fonte anual: sem registros por mês.' : 'Nenhum registro individual neste recorte.'}</div>`;
  }
  return h;
}

function _extra(x){
  const p = [];
  if (x.fora_do_pago && x.fora_do_pago.length) p.push('<b>Fora do "pago"</b> (não somado acima): ' + x.fora_do_pago.map(s => `${esc(s.status)} ${fmtN(s.n)} OB · ${fmtR(s.valor)}`).join(' · '));
  if (x.posicao_por_ano) p.push('<b>Posição do relatório</b>: ' + Object.entries(x.posicao_por_ano).map(([a, v]) => `${esc(a)} até ${esc(v)}`).join(' · '));
  if (x.canceladas_fora) p.push(`<b>Canceladas</b> fora da soma: ${fmtN(x.canceladas_fora)}`);
  if (x.sem_valor_legivel) p.push(`<b>Extratos sem valor legível</b> (contam em registros, não em R$): ${fmtN(x.sem_valor_legivel)}`);
  if (x.descartados_fora) p.push(`<b>Descartados pela triagem</b> fora da contagem: ${fmtN(x.descartados_fora)}`);
  if (x.datas_futuras) p.push(`<b>Assinatura com data futura</b> na fonte: ${fmtN(x.datas_futuras)} (erro de digitação do órgão provável)`);
  if (x.por_cadastro) p.push('<b>Por cadastro</b>: ' + Object.entries(x.por_cadastro).map(([k, v]) => `${esc(k)} ${fmtN(v)}`).join(' · '));
  return p.length ? `<div class="dim" style="font-size:12px;margin-top:4px">${p.join('<br>')}</div>` : '';
}

function _repintarTodos(){
  for (const id of [..._blocos.keys()]) {
    if (document.getElementById(id)) _pintar(id); else _blocos.delete(id);
  }
}

function _definir(ano, mes){
  _P = {ano: ano ? String(ano) : '', mes: ano && mes ? String(mes) : ''};
  _salvar();
  _repintarTodos();
}

let _ligado = false;
export function ligarPeriodo(){
  if (_ligado) return; _ligado = true;
  _ler();
  document.addEventListener('change', ev => {
    const t = ev.target;
    if (!t || !t.matches) return;
    if (t.matches('[data-per-ano]')) _definir(t.value, t.value === _P.ano ? _P.mes : '');
    else if (t.matches('[data-per-mes]')) _definir(_P.ano, t.value);
  });
  const ir = el => { const [a, m] = el.dataset.perIr.split('-').map(Number); _definir(a, m || ''); };
  document.addEventListener('click', ev => {
    const b = ev.target && ev.target.closest && ev.target.closest('[data-per-limpar],[data-per-ir]');
    if (!b) return;
    if (b.hasAttribute('data-per-limpar')) _definir('', '');
    else ir(b);
  });
  document.addEventListener('keydown', ev => {
    const b = (ev.key === 'Enter' || ev.key === ' ') && ev.target && ev.target.closest && ev.target.closest('[data-per-ir]');
    if (b) { ev.preventDefault(); ir(b); }
  });
}
