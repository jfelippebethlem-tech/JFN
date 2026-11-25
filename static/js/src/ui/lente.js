/* O7.2 · SELETOR GLOBAL DE LENTE + FAIXA DA LENTE (plano mestre v2 §3.6 e §8 "Lentes no painel").
 *
 * Uma lente (config/lentes.yaml: bombeiros, couto, mgs_iterj, beneficios, fserj, pcrj_saude, emendas, obras) é um
 * FILTRO sobre a mesma esteira — não existe aba por órgão. O seletor fica no cabeçalho e vale para TODAS as abas:
 *   · toda consulta de dado do painel leva `lente=<nome>` (`nucleo/http.js`);
 *   · a rota que recortou devolve `X-JFN-Lente`; a faixa abaixo do cabeçalho CONTA, por aba, quantas consultas foram
 *     recortadas e quantas mostram o universo inteiro (rota ainda sem recorte por lente) e diz quais — o leitor nunca
 *     toma um número do universo inteiro por número da lente;
 *   · a faixa abre o RECORTE da lente (visão materializada `lente_<nome>` do E15, `/api/esteira/lente`): universo,
 *     pago (só OB), fora da soma, determinável × indeterminado lado a lado, achados por status (`nao_avaliavel`
 *     visível) e o topo da fila com os componentes da prioridade — ordem de exame, não probabilidade.
 * Escolha guardada só no navegador (conveniência; falha de storage não quebra nada).
 */
import {J, lenteAtual, lenteDefinir, lenteNovaAba, lenteUso, _jCache, erroHumano} from '../nucleo/http.js';
import {esc} from '../nucleo/dom.js';
import {fmtN, fmtR} from '../nucleo/formato.js';

const CHAVE = 'jfn_lente';
let _cat = null, _resumo = {}, _recarregar = null;   // _recarregar: o roteador (`ir(aba)`), injetado no boot
const _rs = v => v == null ? 'INDISPONÍVEL' : fmtR(v);
const _n = v => v == null ? 'INDISPONÍVEL' : fmtN(v);

function _guardar(nome) { try { if (nome) localStorage.setItem(CHAVE, nome); else localStorage.removeItem(CHAVE); } catch (e) { /* storage bloqueado: só não lembra */ } }
function _lembrada() { try { return localStorage.getItem(CHAVE); } catch (e) { return null; } }

/** Monta o seletor no cabeçalho. Lente lembrada que não existe mais é descartada (nunca filtro fantasma).
    `recarregar` = o roteador repintando a aba atual (injetado por quem chama: este módulo não importa o entrypoint). */
export async function lenteBoot(recarregar) {
  _recarregar = recarregar;
  const host = document.getElementById('lente-seletor'); if (!host) return;
  const d = await J('/api/esteira/lentes', {tetoMs: 15000});
  if (!d || !d.ok) {
    host.innerHTML = `<span class="lente-off" title="${esc(String((d && d.erro) || 'sem resposta'))}">lentes indisponíveis</span>`;
    lenteDefinir(null); _faixa(); return;
  }
  _cat = d.lentes || [];
  const lembrada = _lembrada(), valida = _cat.some(l => l.lente === lembrada) ? lembrada : null;
  host.innerHTML = `<label class="lente-rot" for="lente-sel">Lente</label><select id="lente-sel" class="lente-sel" title="Recorta todas as abas pela lente (config/lentes.yaml). Nenhuma aba por órgão.">
    <option value="">universo inteiro</option>${_cat.map(l => `<option value="${esc(l.lente)}" title="${esc(l.descricao)}">${esc(l.lente.replace(/_/g, ' '))}</option>`).join('')}</select>`;
  const sel = host.querySelector('select');
  sel.value = valida || '';
  lenteDefinir(valida); if (!valida) _guardar(null);
  sel.addEventListener('change', () => {
    lenteDefinir(sel.value || null); _guardar(sel.value || null); _jCache.clear();
    if (_recarregar) _recarregar(); else _faixa();
  });
  document.addEventListener('jfn-lente-uso', _contagem);
  /* o seletor monta DEPOIS da primeira aba (não atrasa o boot): lente lembrada ⇒ repinta a aba já recortada */
  if (valida && _recarregar) _recarregar(); else _faixa();
}

/** Chamado pelo roteador a cada troca de aba (antes do render): zera a contagem da aba. */
export function lenteTrocaDeAba() { lenteNovaAba(); _faixa(); }

function _contagem() {
  const c = document.getElementById('lente-uso'); if (!c) return;
  const a = lenteUso.aplicada.length, n = lenteUso.nao_aplicada.length, t = a + n;
  c.innerHTML = !t ? 'nesta aba: nenhuma consulta de dado ainda'
    : `nesta aba: <b>recorte aplicado em ${fmtN(a)} de ${fmtN(t)}</b> consulta(s)${n ? ` — <b class="lente-alerta">${fmtN(n)} mostra(m) o UNIVERSO INTEIRO</b> (rota ainda sem recorte por lente: ${lenteUso.nao_aplicada.map(r => `<code>${esc(r)}</code>`).join(', ')})` : ''}`;
}

async function _faixa() {
  const f = document.getElementById('lente-faixa'); if (!f) return;
  const nome = lenteAtual();
  if (!nome) { f.hidden = true; f.innerHTML = ''; return; }
  const l = (_cat || []).find(x => x.lente === nome) || {lente: nome, descricao: ''};
  f.hidden = false;
  f.innerHTML = `<div class="lente-linha"><span class="lente-nome">Lente <b>${esc(nome.replace(/_/g, ' '))}</b></span>
    <span class="lente-desc">${esc(l.descricao)}</span>
    <button type="button" class="chip lente-tirar" id="lente-tirar">tirar a lente</button></div>
    <div class="lente-uso" id="lente-uso" aria-live="polite"></div>
    <details class="lente-rec" id="lente-rec"><summary>o recorte da lente — universo, pago, indeterminados, achados, fila</summary><div id="lente-corpo">lendo a visão da lente…</div></details>`;
  f.querySelector('#lente-tirar').addEventListener('click', () => {
    const s = document.getElementById('lente-sel'); if (s) s.value = '';
    lenteDefinir(null); _guardar(null); _jCache.clear();
    if (_recarregar) _recarregar(); else _faixa();
  });
  _contagem();
  const d = _resumo[nome] || await J('/api/esteira/lente?lente=' + encodeURIComponent(nome), {tetoMs: 20000});
  if (d && d.ok) _resumo[nome] = d;
  const corpo = document.getElementById('lente-corpo'); if (!corpo || lenteAtual() !== nome) return;
  corpo.innerHTML = d && d.ok ? _resumoHtml(d) : `<div class="warn">Recorte da lente <b>INDISPONÍVEL</b> — ${erroHumano(d && d.erro)}</div>`;
}

function _tab(cab, linhas) {
  return `<table class="lente-tab"><thead><tr>${cab.map(c => `<th>${c}</th>`).join('')}</tr></thead><tbody>${linhas.join('') || `<tr><td colspan="${cab.length}" class="dim">nenhum item</td></tr>`}</tbody></table>`;
}

function _resumoHtml(d) {
  const u = d.universo || {};
  let h = `<p class="dim">${esc(d.fonte || '')} · filtro: ${esc((d.filtro || []).join(' · '))}${d.paridade ? ` · <span title="${esc(d.paridade)}">paridade com o script antigo (passe o mouse)</span>` : ''}</p>`;
  if (d.esfera === 'estado') {
    const ind = d.indeterminado || {}, sp = ind.sem_processo || {}, ns = ind.processo_nao_sei || {}, fs = u.fora_da_soma || {};
    h += `<div class="lente-kv">
      <div><b>${_rs(u.valor_pago)}</b><span>pago (OB SIAFE, ${_n(u.obs_pagas)} OB) · <i class="v63-estado verificado">${esc(d.estado || '')}</i></span></div>
      <div><b>${_rs((d.determinavel || {}).valor)}</b><span>determinável: OB paga com nº de processo SEI-RJ (${_n((d.determinavel || {}).obs)} OB)</span></div>
      <div><b>${_rs((sp.valor || 0) + (ns.valor || 0))}</b><span>INDETERMINADO ao lado do valor: ${_n(sp.obs)} OB sem nº de processo · ${_n(ns.obs)} com nº que não é SEI-RJ — pagamento real, vínculo com o SEI INDISPONÍVEL</span></div>
      <div><b>${_rs(fs.valor)}</b><span>fora da soma (${_n(fs.obs)} OB: anulada, excluída, devolvida, complementar, reemitida)</span></div>
      <div><b>${(d.cobertura || {}).fracao_do_pago_ligavel_ao_sei == null ? 'INDISPONÍVEL' : fmtN(Math.round(1000 * d.cobertura.fracao_do_pago_ligavel_ao_sei) / 10) + '%'}</b><span>do pago liga ao SEI (cobertura)</span></div>
      <div><b>${_n(u.credores)}</b><span>credores · ${_n(u.processos_legiveis)} processos · última OB paga ${esc(u.ultima_ob_paga || '—')}</span></div></div>`;
    h += _tab(['UG', 'OB pagas', 'pago'], (d.ugs || []).map(x => `<tr><td>${esc(x.ug)} ${esc(x.sigla || '')}</td><td>${fmtN(x.n_obs)}</td><td>${fmtR(x.pago)}</td></tr>`));
    h += _tab(['credor', 'doc', 'OB', 'pago'], (d.credores_topo || []).map(x => `<tr><td>${esc(x.nome)}</td><td>${esc(x.tipo)} ${esc(x.doc)}</td><td>${fmtN(x.n_obs)}</td><td>${fmtR(x.pago)}</td></tr>`));
    const a = d.achados || {};
    if (a.estado === 'VERIFICADO') {
      const t = a.totais || {};
      h += `<p><b>Achados no recorte</b> (${esc(a.fonte || '')}): ${fmtN(t.confirmado)} a regra disparou · ${fmtN(t.descartado)} descartados · <b>${fmtN(t.nao_avaliavel)} não avaliáveis</b> — ${esc(a.leitura || '')}</p>`;
      h += _tab(['detector', 'registro', 'tier', 'disparou', 'descartado', 'não avaliável'], (a.detectores || []).map(x => `<tr><td>${esc(x.detector)}</td><td>${esc(x.registro)}</td><td title="${esc(x.tier_motivo || '')}">${x.tier == null ? '—' : 'Tier ' + x.tier}</td><td>${fmtN(x.confirmado)}</td><td>${fmtN(x.descartado)}</td><td><b>${fmtN(x.nao_avaliavel)}</b></td></tr>`));
      const b = a.base_ug_em_texto_nao_conferivel || {};
      if (b.achados) h += `<p class="dim">${fmtN(b.achados)} ${esc(b.o_que_e || '')}</p>`;
    } else h += `<p><b>Achados no recorte: ${esc(a.estado || 'INDISPONÍVEL')}</b> — ${esc(a.motivo || '')}</p>`;
    const fl = d.fila || {};
    if (fl.itens) {
      h += `<p><b>Topo da fila única nesta lente</b> — ${esc(fl.rotulo || '')}</p>`;
      h += _tab(['processo', 'OB paga', 'escalar de valor', 'bônus da lente', 'Couto', 'outros sinais', 'por que está na lente'], fl.itens.map(x => {
        const c = x.componentes || {}, s = ['manual', 'legivel', 'contratacao_direta', 'direta_grande', 'lacuna_provada', 'osint', 'folha'].filter(k => c[k]);
        return `<tr><td>${esc(x.processo)}</td><td>${fmtR(x.ob_paga)}</td><td>${esc(String(c.escalar_valor))}</td><td>${esc(String(c.bonus_lente))}</td><td>${c.couto ? 'sim' : 'não'}</td><td>${esc(s.join(', ') || '—')}</td><td>${esc(x.lente_motivo || '')}</td></tr>`;
      }));
    } else if (fl.estado) h += `<p><b>Fila:</b> ${esc(fl.motivo || fl.estado)}</p>`;
  } else if (d.esfera === 'prefeitura') {
    h += `<div class="lente-kv"><div><b>${_rs(u.pago)}</b><span>pago (ContasRio) em ${_n(u.contratos)} contratos</span></div>
      <div><b>${_rs(u.liquidado)}</b><span>liquidado — reconhece a dívida, não é pagamento</span></div>
      <div><b>${_rs(u.empenhado)}</b><span>empenhado — reserva, pode ser cancelado; não é pagamento</span></div>
      <div><b>${_n((d.indeterminado || {}).contratos_sem_pago_informado)}</b><span>contratos sem pago informado (INDISPONÍVEL, não R$ 0,00)</span></div></div>`;
    h += _tab(['órgão', 'contratos', 'pago'], (d.orgaos || []).map(x => `<tr><td>${esc(x.orgao)}</td><td>${fmtN(x.contratos)}</td><td>${fmtR(x.pago)}</td></tr>`));
    h += _tab(['favorecido', 'doc', 'contratos', 'pago'], (d.favorecidos_topo || []).map(x => `<tr><td>${esc(x.nome)}</td><td>${esc(x.tipo)} ${esc(x.doc)}</td><td>${fmtN(x.contratos)}</td><td>${fmtR(x.pago)}</td></tr>`));
  } else {
    h += `<div class="lente-kv"><div><b>${_rs(u.pago)}</b><span>pago — OB FEDERAL (SIAFI), não SIAFE · ${_n(u.emendas)} emendas</span></div>
      <div><b>${_rs(u.liquidado)}</b><span>liquidado</span></div><div><b>${_rs(u.empenhado)}</b><span>empenhado — não é pagamento</span></div>
      <div><b>${_n((d.fora_da_lente || {}).emendas)}</b><span>${esc((d.fora_da_lente || {}).o_que_e || '')}</span></div></div>`;
    h += _tab(['ano', 'emendas', 'empenhado', 'liquidado', 'pago'], (d.por_ano || []).map(x => `<tr><td>${esc(String(x.ano))}</td><td>${fmtN(x.n)}</td><td>${fmtR(x.empenhado)}</td><td>${fmtR(x.liquidado)}</td><td>${fmtR(x.pago)}</td></tr>`));
  }
  return h;
}
