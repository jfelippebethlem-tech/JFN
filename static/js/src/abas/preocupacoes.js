/* SINAIS CRÍTICOS — bloco do Início, logo abaixo do mapa (nome e lugar pedidos pelo dono em 14/11:
   "grandes preocupações" ficou tosco; "fica abaixo do mapa e dos dados dele").

   Pedido do dono (14/11/2026): "a aba início tem que ser inteligente pra aparecer o arc que já tá,
   o mapa do estado, e coisas que impressionem enquanto dados, números, grandes preocupações". O
   funcionamento (motores, comandos, frescor das fontes) foi para a esfera Sistema.

   Regra de governo (sem margem para erro): só entra aqui número que a rotina marca como VERIFICADO
   na fonte primária, sempre com a fonte e a ressalva ao lado. Indício não é acusação. Rota que não
   respondeu some do bloco com a palavra INDISPONÍVEL — nunca vira zero. */
import {esc} from '../nucleo/dom.js';
import {fmtN} from '../nucleo/formato.js';
import {J} from '../nucleo/http.js';

const brl = v => 'R$ ' + Number(v).toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});

function _item({grau, valor, titulo, texto, fonte, estado, destino}) {
  return `<button type="button" class="pq-item" onclick="ir('${destino}')">
    <div class="pq-topo"><span class="pq-grau" aria-hidden="true">${grau}</span><span class="pq-valor num">${valor}</span></div>
    <div class="pq-tit">${titulo}</div>
    <div class="pq-txt">${texto}</div>
    <div class="pq-fonte"><b>${esc(estado)}</b> · ${esc(fonte)}</div>
  </button>`;
}

function _couto(d) {
  if (!d || d.ok === false || !d.pontos_atencao) return '<div class="pq-indisp"><b>Governo Couto: INDISPONÍVEL</b> — a rota não respondeu.</div>';
  const it = (d.pontos_atencao.itens || []).filter(x => x.verificacao === 'VERIFICADO' || (x.verificacao && x.verificacao.estado === 'VERIFICADO'));
  const verm = it.filter(x => x.grau === '🔴'), amar = it.filter(x => x.grau === '🟡');
  if (!verm.length && !amar.length) return '';
  const top = verm[0] || amar[0];
  const nome = String(top.regra_ou_hipotese || '').replace(/^[A-Z]\d+\s*·\s*/, '');
  return _item({
    grau: verm.length ? '🔴' : '🟡',
    valor: `${fmtN(verm.length)} grave${verm.length === 1 ? '' : 's'} · ${fmtN(amar.length)} em atenção`,
    titulo: 'Pontos de atenção na gestão Couto (desde 23/03/2026)',
    texto: `Mais grave: ${esc(nome.length > 170 ? nome.slice(0, 168) + '…' : nome)}${top.valor_ob ? ` — ${brl(top.valor_ob)} em OB contabilizada` : ''}. Explicação inocente possível: ${esc(top.explicacao_inocente || 'ver a aba')}.`,
    fonte: 'SIAFE (OB Contabilizado), CEIS/CNEP, DOERJ, TCE-RJ — só os pontos com prova primária conferida',
    estado: 'VERIFICADO', destino: 'e_couto'});
}

function _pericia(d) {
  if (!d || d.ok === false || !d.esferas) return '<div class="pq-indisp"><b>Perícia contábil: INDISPONÍVEL</b> — a rota não respondeu.</div>';
  const e = d.esferas['Estado do RJ'];
  if (!e || !e.placar || !e.placar.A_MAIOR) return '';
  const verif = String((e.verificacao || {}).placar || '');
  if (!/^VERIFICADO/.test(verif)) return '';
  return _item({
    grau: '🟡',
    valor: brl(e.excesso_a_maior),
    titulo: `Pago acima do valor contratado — ${fmtN(e.placar.A_MAIOR)} contratos do Estado`,
    texto: `Soma das OB contabilizadas no SIAFE que passam do valor registrado do contrato. O TCE-RJ não publica os termos aditivos: é indício a conferir nos aditivos, não dano apurado. Em contratos já encerrados, ficaram ${brl(e.deficit_encerrado)} abaixo do devido.`,
    fonte: 'SIAFE (OB Contabilizado) × contratos do TCE-RJ, régua determinística reproduzível',
    estado: 'VERIFICADO', destino: 'e_pcont'});
}

/** Monta o bloco no `host` (lê uma vez; as rotinas que o alimentam são diárias/semanais). */
export async function preocupacoesMontar(host) {
  if (!host) return;
  const CAB = '<div class="pq-cab"><span class="pq-pulso" aria-hidden="true"></span><h2 class="sec">Sinais críticos</h2><span class="pq-sub">varredura cruzada · prova primária conferida</span></div>';
  host.innerHTML = CAB + '<div class="dim">Varrendo…</div>';
  const [c, p] = await Promise.all([J('/api/governo_couto', {tetoMs: 60000}), J('/api/pericia_contabil', {tetoMs: 60000})]);
  if (!host.isConnected) return;
  const corpo = _couto(c) + _pericia(p);
  host.innerHTML = CAB
    + (corpo ? `<div class="pq-grade">${corpo}</div>` : '<div class="dim">Nenhum sinal verificado para mostrar agora.</div>')
    + '<div class="pq-nota">Indício não é acusação. Cada item abre a aba com a prova primária e a explicação inocente.</div>';
}
