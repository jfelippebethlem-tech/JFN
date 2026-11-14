/* CRUZAMENTO DE MOTORES — o co-motor Claude ao lado da cascata, no Início (AO VIVO).

   Pedido do dono (13/11/2026): "o claude vai ser o CO-MOTOR de tudo. os outros continuam também e
   depois se cruzam". As duas rotas existiam (`/api/ao-vivo/claude` e `/api/ao-vivo/cruzamento`) e
   nenhuma tela as lia — gasto e concordância só eram vistos por quem abria o JSON.

   O que mostra: uso da ASSINATURA (chamadas e tempo de hoje contra o teto), uso da API paga (gasto,
   saldo e projeção por BALDE), concordância por tarefa × modelo, a matriz ⚪🟡🔴, o efeito dos
   exemplos (com × sem — o A/B que a memória `prompt-mais-especifico-piorou-recall` exige) e as
   revisões pendentes (divergência grave, que nunca se resolve sozinha).

   Regra de leitura que a tela repete: acordo com o Claude é REFERÊNCIA, não gabarito; amostra abaixo
   de 20 pares não sustenta taxa; rota que não respondeu é INDISPONÍVEL, nunca zero. */
import {esc, kpi, sec, card} from '../nucleo/dom.js';
import {fmtN} from '../nucleo/formato.js';
import {J} from '../nucleo/http.js';

const AMOSTRA_MINIMA = 20;
const NIV = ['⚪', '🟡', '🔴'];
const usd = v => (v == null ? '—' : 'US$ ' + Number(v).toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2}));
const usd4 = v => (v == null ? '—' : 'US$ ' + Number(v).toLocaleString('pt-BR', {minimumFractionDigits: 4, maximumFractionDigits: 6}));
const pct = v => (v == null ? '—' : Math.round(v * 100) + '%');
const taxaCom = (t, n) => (t == null || !n ? '—' : `${pct(t)} <span class="dim">(${fmtN(n)})</span>${n < AMOSTRA_MINIMA ? ' <span class="dim">· amostra curta</span>' : ''}`);
const indisp = rota => card(`<b>INDISPONÍVEL</b> — a rota <code>${esc(rota)}</code> não respondeu. Sem leitura, não há número: INDISPONÍVEL ≠ 0.`);

/** Monta o bloco no `host` e relê a cada 2 min enquanto o host estiver na página. */
export function cruzamentoMontar(host) {
  if (!host) return;
  host.innerHTML = `${sec('Cruzamento de motores')}<div class="dim">Lendo o uso do Claude e a concordância entre motores…</div>`;
  const ler = async () => {
    if (!host.isConnected) { clearInterval(relogio); return; }
    const [u, c] = await Promise.all([J('/api/ao-vivo/claude'), J('/api/ao-vivo/cruzamento')]);
    host.innerHTML = sec('Cruzamento de motores') + _uso(u) + _cruz(c);
  };
  const relogio = setInterval(ler, 120000);
  ler();
}

function _uso(u) {
  if (!u || u.erro || u.disponivel === false) return indisp('/api/ao-vivo/claude');
  const a = u.api;
  let h = `<div class="grid g4">
    ${kpi(`${fmtN(u.hoje)} / ${fmtN(u.teto)}`, 'Assinatura · chamadas hoje', u.ligado ? 'var(--teal)' : 'var(--rose)', null,
      {sobre: `Chamadas ao Claude pela ASSINATURA hoje contra o teto diário (claude_motor: reserva antes de rodar; processo que morre no meio conta). ${fmtN(u.ok)} ok, ${fmtN(u.erros)} com erro, ${fmtN(u.bloqueadas)} barradas pelo teto. ${u.ligado ? 'Motor ligado.' : 'Motor DESLIGADO: ' + (u.motivo_desligado || 'sem motivo registrado') + '.'} Fonte: data/claude_motor_uso.json.`})}
    ${kpi(`${fmtN(Math.round(u.segundos || 0))} s`, 'Assinatura · tempo hoje', 'var(--teal)', null,
      {sobre: `Segundos de Claude pela assinatura hoje, contra o teto de ${fmtN(u.teto_segundos)} s. É o que a cota da assinatura mede — não há dólar aqui. Fonte: data/claude_motor_uso.json.`})}
    ${a ? kpi(usd(a.gasto_usd), 'API paga · gasto acumulado', 'var(--amber)', null,
      {sobre: `Dólares gastos na API da Anthropic desde ${esc(a.desde || '—')}, por preço de tabela × tokens que a própria resposta informa (lote = 50%). Só Haiku; Opus nunca vai pela API (decisão do dono). ${fmtN(a.chamadas)} chamadas; ${fmtN(a.recusadas_teto)} recusadas pelo teto. Fonte: data/claude_api_gasto.json.`})
      : kpi('—', 'API paga · gasto acumulado', 'var(--dim)', null, {sobre: 'O registro de gasto da API não pôde ser lido — INDISPONÍVEL, não zero.'})}
    ${a ? kpi(usd(a.resta_usd), 'API paga · saldo até o teto', 'var(--amber)', null,
      {sobre: `Quanto ainda cabe: teto de ${usd(a.teto_usd)} menos a margem de segurança (limite efetivo ${usd(a.limite_efetivo_usd)}), menos o gasto e o reservado por lotes em curso (${usd(a.reservado_usd)}). Cada balde tem teto próprio abaixo.`})
      : kpi('—', 'API paga · saldo até o teto', 'var(--dim)', null, {sobre: 'O registro de gasto da API não pôde ser lido — INDISPONÍVEL, não zero.'})}
  </div>`;
  if (a && a.baldes) {
    const linhas = Object.entries(a.baldes).map(([nome, b]) => `<tr>
      <td style="text-align:left">${esc(nome.replace(/_/g, ' '))}${b.pausada ? ` <span class="tag rose" title="${esc(b.pausada.motivo || '')}">pausada</span>` : ''}</td>
      <td class="num">${usd(b.teto_usd)}</td><td class="num">${usd4(b.gasto_usd)}</td><td class="num">${fmtN(b.itens)}</td>
      <td class="num">${usd4(b.usd_por_item)}</td><td class="num">${b.restantes == null ? '—' : fmtN(b.restantes)}</td>
      <td class="num">${b.projecao_total_usd == null ? '—' : usd(b.projecao_total_usd)}</td>
      <td>${b.projecao_cabe == null ? '<span class="dim">sem medida</span>' : b.projecao_cabe ? 'cabe' : '<b style="color:var(--rose)">NÃO cabe</b>'}</td></tr>`).join('');
    h += card(`<div style="font-weight:700;margin-bottom:6px">Projeção por balde</div>
      <div class="dim" style="margin-bottom:6px">Projeção = custo REAL por item já colhido × itens que faltam. Sem item colhido, não há projeção (sem medida ≠ zero).</div>
      <div style="overflow-x:auto"><table class="tb"><thead><tr><th>Balde</th><th>Teto</th><th>Gasto</th><th>Itens</th><th>US$/item</th><th>Faltam</th><th>Projeção</th><th>Cabe?</th></tr></thead><tbody>${linhas}</tbody></table></div>`);
  }
  return h;
}

function _cruz(c) {
  if (!c || c.erro) return indisp('/api/ao-vivo/cruzamento');
  const ls = c.por_tarefa_modelo || [];
  const suf = ls.filter(x => x.amostra_suficiente);
  const nPares = ls.reduce((s, x) => s + (x.n || 0), 0);
  const acordos = ls.reduce((s, x) => s + (x.acordos || 0), 0);
  const graves = ls.reduce((s, x) => s + (x.graves || 0), 0);
  let h = `<div class="grid g4" style="margin-top:14px">
    ${kpi(fmtN(nPares), 'Pares cruzados (30 dias)', 'var(--accent)', null,
      {sobre: `Vereditos em que o Claude e outro motor julgaram o MESMO item, na mesma tarefa, nos últimos ${fmtN(c.dias || 30)} dias. Par com um lado indeterminado fica fora da taxa (INDISPONÍVEL ≠ discordância). Fonte: data/cruzamento_motores.db.`})}
    ${kpi(nPares ? pct(acordos / nPares) : '—', 'Concordância geral com o Claude', 'var(--accent)', null,
      {sobre: `Pares em que o outro motor deu o MESMO nível (⚪🟡🔴) que o Claude, sobre todos os pares medidos. Concordar com o Claude é REFERÊNCIA, não acerto: o Claude não é gabarito. Só ${fmtN(suf.length)} de ${fmtN(ls.length)} combinações tarefa × modelo têm a amostra mínima de ${AMOSTRA_MINIMA} pares.`})}
    ${kpi(fmtN(graves), 'Divergências graves', graves ? 'var(--rose)' : 'var(--green)', null,
      {sobre: 'Pares em que um motor disse 🔴 e o outro ⚪ (distância de dois níveis). Cada uma vira revisão humana; nenhuma é resolvida a favor de um lado sem gente olhar.'})}
    ${kpi(fmtN(c.revisao_pendente), 'Revisões pendentes', c.revisao_pendente ? 'var(--rose)' : 'var(--green)', null,
      {sobre: `Divergências graves ainda sem decisão humana (tabela revisao, status pendente). A lista abaixo mostra as ${fmtN((c.revisoes || []).length)} mais recentes. Exemplos guardados para o few-shot da cascata: ${fmtN(c.exemplos_few_shot)}.`})}
  </div>`;
  if (!c.medido) return h + card(`<div class="dim">${esc(c.motivo || 'Sem cruzamentos ainda')} — nada a medir.</div>`);

  const tab = ls.map(x => `<tr><td style="text-align:left">${esc(String(x.tarefa).replace(/_/g, ' '))}</td><td style="text-align:left">${esc(x.modelo)}</td>
    <td class="num">${fmtN(x.n)}</td><td class="num">${taxaCom(x.taxa_acordo, x.n)}</td><td class="num">${fmtN(x.graves)}</td><td class="num">${fmtN(x.indeterminados)}</td></tr>`).join('');
  h += card(`<div style="font-weight:700;margin-bottom:6px">Concordância por tarefa × modelo</div>
    <div class="dim" style="margin-bottom:6px">${esc(c.legenda || '')}. Abaixo de ${AMOSTRA_MINIMA} pares a taxa é indicação, não medida.</div>
    <div style="overflow-x:auto"><table class="tb"><thead><tr><th>Tarefa</th><th>Modelo comparado</th><th>Pares</th><th>Acordo</th><th>Graves</th><th>Indeterm.</th></tr></thead><tbody>${tab}</tbody></table></div>`);

  const matrizes = Object.entries(c.matriz || {}).map(([t, m]) => {
    const cel = (a, b) => m[`${NIV[a]}×${NIV[b]}`] || 0;
    const corpo = [0, 1, 2].map(a => `<tr><th>${NIV[a]}</th>${[0, 1, 2].map(b => `<td class="num"${a === b ? ' style="font-weight:700"' : (Math.abs(a - b) === 2 && cel(a, b) ? ' style="color:var(--rose);font-weight:700"' : '')}>${fmtN(cel(a, b))}</td>`).join('')}</tr>`).join('');
    return `<div style="min-width:180px"><div style="font-weight:600;margin-bottom:4px">${esc(t.replace(/_/g, ' '))}</div>
      <table class="tb"><thead><tr><th>Claude ↓ · outro →</th>${NIV.map(n => `<th>${n}</th>`).join('')}</tr></thead><tbody>${corpo}</tbody></table></div>`;
  }).join('');
  h += card(`<div style="font-weight:700;margin-bottom:6px">Matriz ⚪🟡🔴 por tarefa</div>
    <div class="dim" style="margin-bottom:6px">Linha = nível do Claude; coluna = nível do outro motor. Diagonal = acordo; canto 🔴×⚪ = divergência grave.</div>
    <div style="display:flex;flex-wrap:wrap;gap:16px">${matrizes || '<span class="dim">sem pares com os dois lados determinados</span>'}</div>`);

  const ab = ls.filter(x => x.n_com_exemplos || x.n_sem_exemplos).map(x => `<tr><td style="text-align:left">${esc(String(x.tarefa).replace(/_/g, ' '))}</td><td style="text-align:left">${esc(x.modelo)}</td>
    <td class="num">${taxaCom(x.taxa_com_exemplos, x.n_com_exemplos)}</td><td class="num">${taxaCom(x.taxa_sem_exemplos, x.n_sem_exemplos)}</td></tr>`).join('');
  h += card(`<div style="font-weight:700;margin-bottom:6px">Efeito dos exemplos (com × sem)</div>
    <div class="dim" style="margin-bottom:6px">Os exemplos são divergências passadas usadas como few-shot na cascata. Só se acredita que ajudaram quando os DOIS lados têm amostra mínima — mexer em prompt sem A/B medido já derrubou recall de 3/6 para 0/6.</div>
    <div style="overflow-x:auto"><table class="tb"><thead><tr><th>Tarefa</th><th>Modelo</th><th>Acordo com exemplos</th><th>Acordo sem exemplos</th></tr></thead><tbody>${ab || '<tr><td colspan="4" class="dim">sem medição</td></tr>'}</tbody></table></div>`);

  const rv = (c.revisoes || []).map(r => `<tr><td class="num">${esc((r.em || '').slice(0, 16).replace('T', ' '))}</td><td style="text-align:left">${esc(String(r.tarefa).replace(/_/g, ' '))}</td>
    <td style="text-align:left">${esc(r.item || '—')}</td><td>${NIV[r.nivel_claude] || '?'} ${esc(r.veredito_claude || '')} <span class="dim">${esc(r.modelo_claude || '')}</span></td>
    <td>${NIV[r.nivel_outro] || '?'} ${esc(r.veredito_outro || '')} <span class="dim">${esc(r.modelo_outro || '')}</span></td></tr>`).join('');
  h += card(`<div style="font-weight:700;margin-bottom:6px">Revisões pendentes</div>
    <div style="overflow-x:auto"><table class="tb"><thead><tr><th>Quando</th><th>Tarefa</th><th>Item</th><th>Claude</th><th>Outro motor</th></tr></thead><tbody>${rv || '<tr><td colspan="5" class="dim">nenhuma divergência grave pendente</td></tr>'}</tbody></table></div>`);
  return h;
}
