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
import {mancheteEstado, detectorLiberado, detectorMotivo} from '../ui/manchete.js';

/* O7.3 (manchete só Tier 1): cada sinal crítico é número de DETECTOR — `couto.Dnn` (regras D01–D20; hipótese H* não
   está no registro) e `pericia_contabil`. Só vai à capa com `manchete_efetiva`; o que não está calibrado aparece
   como bloco "não é manchete", dizendo quantos pontos verificados existem e onde estão — nunca some calado. */
function _detCouto(x) { const m = String(x.regra_ou_hipotese || '').match(/^(D\d{2})\b/); return m ? 'couto.' + m[1] : null; }
function _bloqueado(titulo, n, dets, destino) {
  const motivos = [...new Set(dets.map(d => d ? detectorMotivo(d) : 'hipótese fora do registro de detectores — não é manchete'))];
  return `<button type="button" class="pq-item mch-off" onclick="ir('${destino}')">
    <div class="pq-topo"><span class="pq-grau" aria-hidden="true">⚪</span><span class="pq-valor num">não é manchete</span></div>
    <div class="pq-tit">${titulo}</div>
    <div class="pq-txt">${fmtN(n)} ponto(s) com prova primária conferida ficam fora da capa até o detector ser calibrado (Tier 1): ${esc(motivos.slice(0, 3).join(' · '))}${motivos.length > 3 ? ' …' : ''}. O conteúdo segue na aba.</div>
    <div class="pq-fonte"><b>NÃO CALIBRADO</b> · registro de detectores (tier calculado hoje)</div>
  </button>`;
}

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
  const graves = it.filter(x => x.grau === '🔴' || x.grau === '🟡');
  const libera = graves.filter(x => detectorLiberado(_detCouto(x)));
  if (graves.length && !libera.length)
    return _bloqueado('Pontos de atenção na gestão Couto (desde 23/03/2026)', graves.length, graves.map(_detCouto), 'e_couto');
  const verm = libera.filter(x => x.grau === '🔴'), amar = libera.filter(x => x.grau === '🟡');
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

/* Concentração (14/11/2026): o total saltou de R$ 4,26 mi para R$ 17,96 mi com 6 contratos a mais — 60% vinha de UM
   contrato de vigência longa sem termo publicado. Manchete concentrada tem de dizer que é concentrada. */
function _concentracao(e) {
  // mesma grandeza da manchete: `excesso_a_maior` é a soma de `diferenca` (pago − devido) dos contratos A_MAIOR
  const l = (e.a_maior || []).filter(x => x.diferenca > 0).sort((a, b) => b.diferenca - a.diferenca);
  const tot = e.excesso_a_maior;
  if (!l.length || !tot) return '';
  const top = l[0], p = Math.round(100 * top.diferenca / tot);
  if (p < 25) return '';
  const res = String(top.ressalvas || '').split(' · ')[0];
  return ` O maior caso (${esc(top.fornecedor || '—')}, ${esc(top.orgao ? top.orgao.split(' - ')[0] : '')}) responde por ${p}% da soma${res ? ` — ${esc(res)}` : ''}.`;
}

/* Decisão do dono (14/11/2026): consumo contínuo (concessionária, cota condominial, assinatura) e grupos de ata têm
   classe própria — ficam FORA desta soma; a frase diz quanto ficou de fora, para a manchete não esconder nada. */
function _foraDaManchete(e) {
  const cc = e.consumo_continuo, g = e.grupos_ata;
  const p = [];
  if (cc && cc.n) p.push(`${fmtN(cc.n)} de consumo contínuo (${brl(cc.excesso)}, valor registrado é estimativa)`);
  if (g && g.placar_grupos && g.placar_grupos.GRUPO_ATA_A_MAIOR) p.push(`${fmtN(g.placar_grupos.GRUPO_ATA_A_MAIOR)} grupo(s) de ata acima da soma dos desdobramentos (${brl(g.excesso_a_maior)})`);
  return p.length ? ` Fora desta soma, em classe própria: ${p.join('; ')}.` : '';
}

function _pericia(d) {
  if (!d || d.ok === false || !d.esferas) return '<div class="pq-indisp"><b>Perícia contábil: INDISPONÍVEL</b> — a rota não respondeu.</div>';
  const e = d.esferas['Estado do RJ'];
  if (!e || !e.placar || !e.placar.A_MAIOR) return '';
  const verif = String((e.verificacao || {}).placar || '');
  if (!/^VERIFICADO/.test(verif)) return '';
  if (!detectorLiberado('pericia_contabil'))
    return _bloqueado(`Pago acima do valor contratado — ${fmtN(e.placar.A_MAIOR)} contratos do Estado`, e.placar.A_MAIOR, ['pericia_contabil'], 'e_pcont');
  return _item({
    grau: '🟡',
    valor: brl(e.excesso_a_maior),
    titulo: `Pago acima do valor contratado — ${fmtN(e.placar.A_MAIOR)} contratos do Estado`,
    texto: `Soma das OB contabilizadas no SIAFE que passam do valor registrado do contrato. O TCE-RJ não publica os termos aditivos: é indício a conferir nos aditivos, não dano apurado.${_concentracao(e)} Em contratos já encerrados, ficaram ${brl(e.deficit_encerrado)} abaixo do devido.${_foraDaManchete(e)}`,
    fonte: 'SIAFE (OB Contabilizado) × contratos do TCE-RJ, régua determinística reproduzível',
    estado: 'VERIFICADO', destino: 'e_pcont'});
}

/** Monta o bloco no `host` (lê uma vez; as rotinas que o alimentam são diárias/semanais). */
export async function preocupacoesMontar(host) {
  if (!host) return;
  const CAB = '<div class="pq-cab"><span class="pq-pulso" aria-hidden="true"></span><h2 class="sec">Sinais críticos</h2><span class="pq-sub">varredura cruzada · prova primária conferida</span></div>';
  host.innerHTML = CAB + '<div class="dim">Varrendo…</div>';
  const [c, p] = await Promise.all([J('/api/governo_couto', {tetoMs: 60000}), J('/api/pericia_contabil', {tetoMs: 60000}), mancheteEstado()]);
  if (!host.isConnected) return;
  const corpo = _couto(c) + _pericia(p);
  host.innerHTML = CAB
    + (corpo ? `<div class="pq-grade">${corpo}</div>` : '<div class="dim">Nenhum sinal verificado para mostrar agora.</div>')
    + '<div class="pq-nota">Indício não é acusação. Cada item abre a aba com a prova primária e a explicação inocente.</div>';
}
