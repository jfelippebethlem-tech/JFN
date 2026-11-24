/* CONCILIAÇÃO OB do SIAFE × espelho TFE — esfera Sistema (qualidade de dado).

   Pedido do dono (24/11/2026): "corrige o painel usando o SIAFE e as OBs. Quero o que tiver de divergência com o
   TFE também, mas OBs são o principal; TFE pode ter erro." O bloco diz, por exercício, quanto o SIAFE pagou, quanto
   o espelho lista, quantas OB casam e por que o resto não casa. Nada daqui é "pago": pago é a OB do SIAFE. */
import {esc, kpi, sec, card} from '../nucleo/dom.js';
import {fmtN, fmtR, fmtData} from '../nucleo/formato.js';
import {J} from '../nucleo/http.js';

const ROTA = '/api/conciliacao/ob_tfe';
const NOME = {
  casada_numero: 'casada pelo nº da OB', casada_credor_valor_data: 'casada por credor + valor + data',
  complementar: 'Pagamento Complementar (não vai ao banco)', devolvida: 'devolvida pelo banco',
  reemitida: 'reemitida e paga por outra', nao_contabilizada: 'não contabilizada no SIAFE',
  cobertura_parcial_siafe: 'lacuna da nossa coleta do SIAFE', ausente_no_siafe: 'ausente no SIAFE, sem explicação',
  fora_do_universo_tfe: 'fora do universo do espelho (folha, previdência, repasse)',
  tfe_defasado: 'espelho ainda não publicou', ausente_no_tfe: 'ausente no espelho, sem explicação',
};
const nome = c => NOME[c] || c;
const tb = (cab, linhas) => `<div style="overflow-x:auto"><table class="tb"><thead><tr>${cab}</tr></thead><tbody>${linhas}</tbody></table></div>`;

function _classes(cl) {
  const ks = Object.keys(cl || {}).filter(k => !k.startsWith('casada'));
  if (!ks.length) return '<span class="dim">—</span>';
  return ks.sort((a, b) => cl[b].valor - cl[a].valor)
    .map(k => `<div class="dim">${esc(nome(k))}: ${fmtN(cl[k].n)} · ${fmtR(cl[k].valor)}</div>`).join('');
}

function _render(d) {
  if (!d || d.ok === false) {
    const m = d && d.calculando ? 'em cálculo — a varredura das duas tabelas leva alguns minutos; reabra a aba em seguida'
      : 'a rota não respondeu';
    return card(`<b>INDISPONÍVEL</b> — ${esc(m)} (<code>${ROTA}</code>). INDISPONÍVEL ≠ 0.`);
  }
  const anos = d.por_ano || [];
  const tot = anos.reduce((s, a) => ({si: s.si + a.siafe_pago_valor, tf: s.tf + a.tfe_valor,
    st: s.st + a.so_tfe_n, ss: s.ss + a.so_siafe_n, c: s.c + a.casadas_numero}), {si: 0, tf: 0, st: 0, ss: 0, c: 0});
  let h = `<div class="note"><b>${esc(d.rotulo)}.</b> ${esc(d.recorte)}. Espelho publicado até ${esc(fmtData(d.tfe_ultimo_dia))}; calculado em ${esc(fmtData(d.gerado_em))}.</div>`;
  h += `<div class="grid g4">
    ${kpi(fmtR(tot.si), 'Pago — OB do SIAFE', 'var(--accent)', null, {sobre: 'Soma das OB pagas no SIAFE (régua _ob_paga: Contabilizada, sem devolvida, sem complementar, sem reemitida, com número) no recorte. É o número que vale.'})}
    ${kpi(fmtR(tot.tf), 'Listado no espelho TFE', null, null, {sobre: 'Soma das linhas de ordens_bancarias (espelho TFE) no recorte — só confronto, nunca pagamento.'})}
    ${kpi(fmtN(tot.c), 'OB casadas pelo número', null, null, {sobre: 'Mesmo número de OB e mesma UG nos dois lados, paga no SIAFE.'})}
    ${kpi(`${fmtN(tot.ss)} · ${fmtN(tot.st)}`, 'Só no SIAFE · só no TFE', 'var(--amber)', null, {sobre: 'OB que só um dos lados tem. Cada uma sai classificada na tabela abaixo; a maior parte do "só no SIAFE" é folha, previdência e repasse, que o espelho não publica.'})}
  </div>`;
  h += card(tb('<th>Exercício</th><th class="right">SIAFE pago</th><th class="right">TFE</th><th class="right">diferença</th><th class="right">SIAFE ÷ TFE</th><th class="right">casadas</th><th>só no SIAFE — por quê</th><th>só no TFE — por quê</th><th class="right">pares UG parciais / indisp.</th>',
    anos.map(a => `<tr><td><b>${esc(a.ano)}</b></td><td class="right">${fmtR(a.siafe_pago_valor)}</td><td class="right">${fmtR(a.tfe_valor)}</td>
      <td class="right">${fmtR(a.diferenca)}</td><td class="right">${a.razao_siafe_tfe == null ? '—' : String(a.razao_siafe_tfe).replace('.', ',') + '×'}</td>
      <td class="right">${fmtN(a.casadas_numero)}</td><td>${_classes(a.classes_siafe)}</td><td>${_classes(a.classes_tfe)}</td>
      <td class="right">${fmtN(a.pares_parciais)} / ${fmtN(a.pares_indisponiveis)}</td></tr>`).join('')));
  const ugs = (d.por_ug || []).slice(0, 15);
  if (ugs.length) {
    h += `<div class="dim" style="margin:10px 2px 4px">${fmtN(ugs.length)} pares (UG, exercício) de maior divergência, de ${fmtN(d.por_ug_total)} — critério: ${esc(d.por_ug_criterio || '')}</div>`;
    h += card(tb('<th>Exercício</th><th>UG</th><th class="right">SIAFE pago</th><th class="right">TFE</th><th class="right">diferença</th><th>cobertura SIAFE</th><th>explicação (só no TFE)</th>',
      ugs.map(u => `<tr><td>${esc(u.ano)}</td><td>${esc(u.ug)} <span class="dim">${esc(u.ug_nome || '')}</span></td>
        <td class="right">${fmtR(u.siafe_pago_valor)}</td><td class="right">${fmtR(u.tfe_valor)}</td><td class="right">${fmtR(u.diferenca)}</td>
        <td>${esc(u.cobertura_siafe)}${u.pct_ausente_siafe != null ? ` <span class="dim">(${String(u.pct_ausente_siafe).replace('.', ',')}% do espelho ausente)</span>` : ''}</td>
        <td>${_classes(u.classes_tfe)}</td></tr>`).join('')));
  }
  const am = (titulo, lst) => !(lst || []).length ? '' : `<div class="dim" style="margin:10px 2px 4px">${esc(titulo)}</div>` + card(tb(
    '<th>OB</th><th>UG</th><th>data</th><th>favorecido</th><th class="right">valor</th><th>explicação</th>',
    lst.slice(0, 10).map(x => `<tr><td>${esc(x.numero_ob)}</td><td>${esc(x.ug)}</td><td>${esc(fmtData(x.data))}</td>
      <td>${esc(x.favorecido || '—')}</td><td class="right">${fmtR(x.valor)}</td><td>${esc(x.explicacao || nome(x.classe))}</td></tr>`).join('')));
  h += am('Maiores OB que o espelho lista e o SIAFE não paga', d.maiores_so_tfe);
  h += am('Maiores OB pagas no SIAFE que o espelho não lista (fornecedor, sem explicação)', d.maiores_so_siafe);
  const la = d.linhas_alheias_tfe || {};
  if (la.n) h += `<div class="note">${fmtN(la.n)} linha(s) alheia(s) dentro de <code>ordens_bancarias</code> (sem número AAAAOB* ou sem data) — fora de toda soma.</div>`;
  return h;
}

export function conciliacaoMontar(host) {
  if (!host) return;
  host.innerHTML = `${sec('Conciliação OB do SIAFE × espelho TFE')}<div class="dim">Lendo a conciliação…</div>`;
  J(ROTA).then(d => { if (host.isConnected) host.innerHTML = sec('Conciliação OB do SIAFE × espelho TFE') + _render(d); });
}
