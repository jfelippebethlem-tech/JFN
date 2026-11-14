/* CRUZAMENTO DE MOTORES — o co-motor Claude ao lado da cascata, no Início (AO VIVO).

   Pedido do dono (13/11/2026): "o claude vai ser o CO-MOTOR de tudo. os outros continuam também e
   depois se cruzam". As duas rotas existiam (`/api/ao-vivo/claude` e `/api/ao-vivo/cruzamento`) e
   nenhuma tela as lia — gasto e concordância só eram vistos por quem abria o JSON.

   O que mostra: concordância por tarefa × modelo, a matriz ⚪🟡🔴, o efeito dos
   exemplos (com × sem — o A/B que a memória `prompt-mais-especifico-piorou-recall` exige) e as
   revisões pendentes (divergência grave, que nunca se resolve sozinha).

   Custo de API e uso da assinatura NÃO aparecem no painel (dono, 14/11/2026: "não quero saber o
   custo das chamadas da api nem chamadas da assinatura no painel. isso polui"). Ficam só nos
   arquivos de registro (data/claude_api_gasto.json, data/claude_motor_uso.json).

   Regra de leitura que a tela repete: acordo com o Claude é REFERÊNCIA, não gabarito; amostra abaixo
   de 20 pares não sustenta taxa; rota que não respondeu é INDISPONÍVEL, nunca zero. */
import {esc, kpi, sec, card} from '../nucleo/dom.js';
import {fmtN} from '../nucleo/formato.js';
import {J} from '../nucleo/http.js';

const AMOSTRA_MINIMA = 20;
const NIV = ['⚪', '🟡', '🔴'];
const pct = v => (v == null ? '—' : Math.round(v * 100) + '%');
const taxaCom = (t, n) => (t == null || !n ? '—' : `${pct(t)} <span class="dim">(${fmtN(n)})</span>${n < AMOSTRA_MINIMA ? ' <span class="dim">· amostra curta</span>' : ''}`);
const indisp = rota => card(`<b>INDISPONÍVEL</b> — a rota <code>${esc(rota)}</code> não respondeu. Sem leitura, não há número: INDISPONÍVEL ≠ 0.`);

/** Monta o bloco no `host` e relê a cada 2 min enquanto o host estiver na página. */
export function cruzamentoMontar(host) {
  if (!host) return;
  host.innerHTML = `${sec('Cruzamento de motores')}<div class="dim">Lendo a concordância entre motores…</div>`;
  const ler = async () => {
    if (!host.isConnected) { clearInterval(relogio); return; }
    const c = await J('/api/ao-vivo/cruzamento');
    host.innerHTML = sec('Cruzamento de motores') + _cruz(c);
  };
  const relogio = setInterval(ler, 120000);
  ler();
}

function _cruz(c) {
  if (!c || c.erro) return indisp('/api/ao-vivo/cruzamento');
  const ls = c.por_tarefa_modelo || [];
  const suf = ls.filter(x => x.amostra_suficiente);
  const nPares = ls.reduce((s, x) => s + (x.n || 0), 0);
  const acordos = ls.reduce((s, x) => s + (x.acordos || 0), 0);
  const graves = ls.reduce((s, x) => s + (x.graves || 0), 0);
  let h = `<div class="grid g4">
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

/* CONFERÊNCIA DO OPUS — o que os outros modelos produziram enquanto o Claude da assinatura estava no limite.

   Pedido do dono (14/11/2026): "quando chegar perto de 100% do uso do limite claude, coloque tudo pros outros
   modelos de ai continuarem… o que for feito por eles depois tem conferência sempre pelo claude opus".
   Mostra o ESTADO (em contingência até que horas, e por quê) e a FILA (pendentes por tarefa × modelo, o que o
   Opus já conferiu, quantas vezes divergiu). Nada de custo nem de contagem de chamadas da assinatura. */
export function conferenciaMontar(host) {
  if (!host) return;
  host.innerHTML = `${sec('Conferência do Opus')}<div class="dim">Lendo a fila de conferência…</div>`;
  const ler = async () => {
    if (!host.isConnected) { clearInterval(relogio); return; }
    const c = await J('/api/ao-vivo/conferencia-opus');
    host.innerHTML = sec('Conferência do Opus') + _conf(c);
  };
  const relogio = setInterval(ler, 120000);
  ler();
}

const _ORIGEM = {limite_assinatura: 'a conta do Claude chegou ao limite de uso', teto_proprio: 'o orçamento diário do motor passou de 90%', forcada: 'contingência ligada à mão'};
const _hora = iso => (iso ? String(iso).slice(11, 16) + ' de ' + String(iso).slice(8, 10) + '/' + String(iso).slice(5, 7) : '—');
const _n = v => (v == null ? 'INDISPONÍVEL' : fmtN(v));

function _conf(c) {
  if (!c || c.erro) return indisp('/api/ao-vivo/conferencia-opus');
  const k = c.contingencia || {};
  const estado = k.ativa
    ? card(`<b>🟡 Em contingência</b> — ${esc(_ORIGEM[k.origem] || k.origem || 'motivo não informado')}${k.ate_iso ? `; o Claude da assinatura volta às <b>${esc(_hora(k.ate_iso))}</b>` : ''}. O JFN segue produzindo com os outros modelos; o que eles fizerem entra na fila abaixo e não vira VERIFICADO antes de o Opus conferir.`)
    : card(`<b>🟢 Claude da assinatura respondendo</b> — sem contingência agora.${c.ultima_contingencia ? ` Última: ${esc(String(c.ultima_contingencia.desde || '').replace('T', ' ').slice(0, 16))} até ${esc(_hora(c.ultima_contingencia.ate))}.` : ''}${(k.tarefas_perto_do_teto || []).length ? ` Tarefas a mais de 90% do teto do dia: ${esc(k.tarefas_perto_do_teto.join(', ').replace(/_/g, ' '))}.` : ''}`);
  let h = estado + `<div class="grid g4">
    ${kpi(c.disponivel ? _n(c.pendentes) : 'INDISPONÍVEL', 'Aguardando o Opus', c.pendentes ? 'var(--amber, var(--accent))' : 'var(--green)', null,
      {sobre: 'Resultados entregues por outro modelo (cascata gratuita ou Claude barato) enquanto o Claude da assinatura não podia responder. Cada um fica PENDENTE até o Opus reler a mesma entrada. Fonte: data/conferencia_opus.db.'})}
    ${kpi(_n(c.triagem_pendente), 'Alertas da triagem aguardando o Opus', 'var(--accent)', null,
      {sobre: 'Fila irmã, mais antiga: alertas da triagem com leitura 🔴/🟡, descartada ou feita sem o Claude da assinatura (alertas_triagem.opus_pendente). O Opus relê em lotes a cada hora.'})}
    ${kpi(c.disponivel ? _n(c.conferidos) : 'INDISPONÍVEL', 'Já conferidos pelo Opus', 'var(--accent)', null,
      {sobre: 'Itens da fila que o Opus releu. Cada par Opus × outro modelo entra no cruzamento de motores abaixo.'})}
    ${kpi(c.disponivel ? _n(c.divergencias) : 'INDISPONÍVEL', 'Opus divergiu', c.divergencias ? 'var(--rose)' : 'var(--green)', null,
      {sobre: 'Conferências em que o Opus NÃO deu o mesmo nível que o modelo de contingência (ou a tarefa é texto, sem régua). Nesses casos vale o resultado do Opus; a leitura anterior fica registrada. Divergência de dois níveis (🔴×⚪) vira também revisão humana.'})}
  </div>`;
  if (!c.disponivel) return h + card('<b>INDISPONÍVEL</b> — a fila de conferência não pôde ser lida. Sem leitura não há número: INDISPONÍVEL ≠ 0.');
  const tab = (c.por_tarefa || []).map(x => `<tr><td style="text-align:left">${esc(String(x.tarefa).replace(/_/g, ' '))}</td><td style="text-align:left">${esc(x.motor)}</td>
    <td class="num">${fmtN(x.pendentes)}</td><td class="num">${fmtN(x.graves)}</td><td class="num">${fmtN(x.conferidos)}</td><td class="num">${fmtN(x.concordou)}</td><td class="num">${fmtN(x.divergiu)}</td><td class="num">${fmtN(x.erro)}</td></tr>`).join('');
  h += card(`<div style="font-weight:700;margin-bottom:6px">Fila por tarefa × modelo que produziu</div>
    <div class="dim" style="margin-bottom:6px">${esc(c.legenda || '')} Ordem de conferência: 🔴 primeiro, depois 🟡, indeterminado e ⚪; dentro do nível, maior valor.</div>
    <div style="overflow-x:auto"><table class="tb"><thead><tr><th>Tarefa</th><th>Modelo que produziu</th><th>Pendentes</th><th>🔴 pendentes</th><th>Conferidos</th><th>Opus concordou</th><th>Opus divergiu</th><th>Sem conferência válida</th></tr></thead><tbody>${tab || '<tr><td colspan="8" class="dim">fila vazia — nada foi produzido sem o Claude da assinatura</td></tr>'}</tbody></table></div>`);
  const its = (c.itens || []).map(r => `<tr><td class="num">${esc(String(r.desde || '').slice(0, 16).replace('T', ' '))}</td><td style="text-align:left">${esc(String(r.tarefa).replace(/_/g, ' '))}</td>
    <td style="text-align:left">${esc(r.item || '—')}</td><td>${NIV[r.nivel] || '?'} ${esc(r.veredito || '')}</td><td style="text-align:left">${esc(r.motor || '')}</td><td style="text-align:left" class="dim">${esc(r.motivo || '')}</td></tr>`).join('');
  if (its) h += card(`<div style="font-weight:700;margin-bottom:6px">Próximos ${fmtN((c.itens || []).length)} da fila</div>
    <div style="overflow-x:auto"><table class="tb"><thead><tr><th>Desde</th><th>Tarefa</th><th>Item</th><th>Leitura do outro modelo (pendente)</th><th>Modelo</th><th>Por que o Claude não respondeu</th></tr></thead><tbody>${its}</tbody></table></div>`);
  return h;
}
