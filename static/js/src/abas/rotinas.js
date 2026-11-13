// ═══ ROTINAS AUTOMÁTICAS — Estado › Perícia contábil · Estado › CGE × JFN (13/11/2026) ═══
// Pedido do dono: "tudo rodando, periciando, cruzando informação, automaticamente atualizado no painel".
// Dados: GET /api/pericia_contabil (rotina diária), /api/cge_confronto (semanal), /api/detectores_achados
// (rotas/pericias_rotinas.py). Rotina que ainda não rodou diz "sem execução" — não é zero. Sem delegação de
// eventos (só <details>): nada novo no `window` nem na ordem de boot.
import {esc, card, kpi, sec, cover} from '../nucleo/dom.js';
import {J, erroHumano} from '../nucleo/http.js';
import {fmtN, fmtR, fmtData} from '../nucleo/formato.js';

const _txt = '<style>.rt-txt th,.rt-txt td{text-align:left;vertical-align:top}.rt-txt th.right,.rt-txt td.right{text-align:right}</style>';
const _rodape = d => `<div class="dim" style="font-size:12px;margin-top:6px">Rotina <code>${esc(d.rotina || '')}</code> · ${esc(d.horario || '')} · arquivo gravado em ${esc(d.arquivo_mtime || '—')}</div>`;
const _semExec = d => card(`<div class="warn">${esc(d.mensagem || 'Rotina ainda sem execução.')}</div>
  <div class="dim" style="font-size:12px;margin-top:6px">Comando: <code>${esc(d.rotina || '')}</code> (${esc(d.horario || '')}).</div>`);
// Diretriz do dono (13/11/2026): estado VERIFICADO/PENDENTE visível ao lado de todo número.
const _estado = v => `<b style="color:${v === 'VERIFICADO' ? 'var(--green)' : 'var(--amber)'}">${esc(v)}</b>`;
const _pct = (a, b) => (b ? (100 * a / b).toLocaleString('pt-BR', {maximumFractionDigits: 1}) + '%' : '—');

const _CLASSES = [
  ['CONFORME', 'Conforme', 'var(--green)', '✅'],
  ['A_MAIOR', 'Pago a maior', 'var(--rose)', '🔺'],
  ['A_MENOR_ENCERRADO', 'A menor — encerrado', 'var(--amber)', '🔻'],
  ['A_MENOR_EM_CURSO', 'A menor — em curso', null, '⏳'],
  ['INDETERMINADO', 'Indeterminado', null, '❔'],
];

function _linhasContrato(itens, campoValor){
  return (itens || []).map(x => `<tr><td style="font-size:13px"><b>${esc(x.fornecedor || '')}</b> <span class="dim" style="font-size:11px">${esc(x.fornecedor_doc || '')}</span>
      <div>${esc(x.objeto || '')}</div><div class="dim" style="font-size:11px">${esc(x.orgao || '')}${x.ug ? ' · UG ' + esc(x.ug) : ''} · contrato ${esc(x.contrato || '')}${x.processo ? ' · ' + esc(x.processo) : ''}</div></td>
    <td class="right" style="white-space:nowrap">${x.valor_atualizado == null ? '—' : fmtR(x.valor_atualizado)}</td>
    <td class="right" style="white-space:nowrap">${x.devido == null ? '—' : fmtR(x.devido)}</td>
    <td class="right" style="white-space:nowrap">${x.pago == null ? '—' : fmtR(x.pago)}</td>
    <td class="right" style="white-space:nowrap"><b>${campoValor(x)}</b>${x.prova_primaria ? `<div class="dim" style="font-size:11px;white-space:normal;max-width:220px">${_estado(x.verificacao || 'PENDENTE')} ${esc(x.prova_primaria)}</div>` : ''}</td></tr>`).join('');
}

function _esfera(nome, e, defs){
  const p = e.placar || {};
  const kp = _CLASSES.map(([k, rot, cor, gl]) => kpi(fmtN(p[k] || 0), `${rot} (${_pct(p[k] || 0, e.n)})`, cor, gl, {sobre: 'Contratos desta esfera nesta classe da perícia contábil: devido (valor + aditivos, pró-rata quando contínuo) × pago (só OB Contabilizada do SIAFE). Indeterminado = sem vínculo seguro OB↔contrato; nunca vira zero.'})).join('');
  const mot = (e.motivos_indeterminado || []).map(m => `<tr><td style="font-size:13px">${esc(m.texto)}</td><td class="right">${fmtN(m.n)}</td><td class="right">${_pct(m.n, p.INDETERMINADO)}</td></tr>`).join('');
  const dup = e.duplicidades || {};
  const cab = '<thead><tr><th>Fornecedor, objeto e órgão</th><th class="right">Valor atualizado</th><th class="right">Devido até o corte</th><th class="right">Pago</th><th class="right">%s</th></tr></thead>';
  return `${sec(esc(nome), e.n)}<div class="grid g2" style="margin-top:8px">${kp}</div>
  ${card(`<div style="font-size:12px;margin-bottom:6px">${_estado('VERIFICADO')} placar e somas: ${esc(((e.verificacao || {}).placar || '').replace(/^VERIFICADO — /, ''))}<br>${_estado('PENDENTE')} listas abaixo: ${esc(((e.verificacao || {}).listas || '').replace(/^PENDENTE — /, ''))}</div>
    <div style="font-size:13px"><b>${fmtN(e.n)}</b> contratos · corte ${e.corte ? fmtData(e.corte) : `por contrato, de ${fmtData(e.corte_min)} a ${fmtData(e.corte_max)}`} · pago determinado ${fmtR(e.pago_determinado)} × devido ${fmtR(e.devido_determinado)}
      · excesso "a maior" ${fmtR(e.excesso_a_maior)} (acima do valor global: ${fmtR(e.excesso_global)}) · déficit em encerrados ${fmtR(e.deficit_encerrado)}</div>
    <div class="dim" style="font-size:12px;margin-top:4px"><b>Pago:</b> ${esc(e.fonte_pago || '')}. ${esc(nome === 'Estado do RJ' ? defs.pago_estado || '' : defs.pago_prefeitura || '')}.
      <b>Contratos:</b> ${esc((e.proveniencia || {}).fonte_contratos || '')}. <b>Cobertura:</b> ${esc((e.proveniencia || {}).cobertura || '')}.
      Acréscimo acima do teto legal aferível em ${fmtN((e.art125 || {}).aferivel)} contratos; estouro em ${fmtN((e.art125 || {}).estouro)}.</div>
    <details style="margin-top:10px" open><summary style="cursor:pointer"><b>Maiores "pago a maior"</b> (${fmtN((e.a_maior || []).length)} de ${fmtN(p.A_MAIOR)}, maior diferença primeiro)</summary>
      <div style="max-height:560px;overflow:auto"><table class="tb rt-txt">${cab.replace('%s', 'Pago − devido')}<tbody>${_linhasContrato(e.a_maior, x => fmtR(x.diferenca))}</tbody></table></div></details>
    ${dup.aferivel === false ? `<div class="dim" style="font-size:12px;margin-top:8px"><b>Duplicidades:</b> ${esc(dup.motivo || 'não aferível nesta esfera')}</div>` : `<details style="margin-top:8px"><summary style="cursor:pointer"><b>Duplicidades — mesma NL, mesmo valor em mais de uma OB</b> (${fmtN(dup.n_contratos)} contratos · ${fmtN(dup.n_obs_repetidas)} OB repetidas · ${fmtR(dup.valor_repetido)})</summary>
      <div class="dim" style="font-size:12px;margin:4px 0">${esc(defs.duplicidade || '')}</div>
      <div style="max-height:480px;overflow:auto"><table class="tb rt-txt">${cab.replace('%s', 'Valor repetido (mesma NL)')}<tbody>${_linhasContrato(dup.itens, x => `${fmtR(x.valor_mesma_nl)} <span class="dim" style="font-size:11px">(${fmtN(x.obs_mesma_nl)} OB)</span>`)}</tbody></table></div></details>`}
    <details style="margin-top:8px"><summary style="cursor:pointer"><b>Por que ${fmtN(p.INDETERMINADO)} ficaram indeterminados</b></summary>
      <table class="tb rt-txt"><thead><tr><th>Motivo</th><th class="right">Contratos</th><th class="right">% dos indeterminados</th></tr></thead><tbody>${mot}</tbody></table></details>`)}`;
}

export async function renderPericiaContabil(){
  const d = await J('/api/pericia_contabil', {tetoMs: 60000});
  let h = cover('estado', 'Perícia contábil de todos os contratos',
    'Valor DEVIDO até a data de corte × valor PAGO, contrato a contrato, recalculado toda madrugada. Estado: pago = só OB Contabilizada do SIAFE. Prefeitura: total pago no SIAFIC-Rio. Esferas nunca se misturam. Indício não é acusação.', '⚖️');
  if (!d || d.ok === false) return h + card(`<div class="warn">${erroHumano(d)}</div>`);
  if (d.estado === 'sem_execucao') return h + _semExec(d);
  const defs = d.definicoes || {};
  h += card(`<div style="font-size:13px"><b>Régua:</b> ${esc(d.regua || '')} · <b>Tolerância:</b> ${esc(d.tolerancia || '')}</div>
    <div class="dim" style="font-size:12px;margin-top:4px">${esc(defs.indeterminado || '')}. ${esc(d.ressalva || '')}</div>${_rodape(d)}`);
  for (const [nome, e] of Object.entries(d.esferas || {})) h += _esfera(nome, e, defs);
  return `<div id="rt-pericia">${h}${_txt}</div>`;
}

const _sim = v => (v == null ? '<span class="dim">indisp.</span>' : (v ? '✔' : '<span class="dim">—</span>'));

function _cge(d){
  if (d.estado === 'sem_execucao') return _semExec(d);
  if (d.estado !== 'ok') return card(`<div class="warn">Confronto INDISPONÍVEL — ${esc(d.erro || '')}. Não é zero.</div>`);
  const m = d.metricas || {}, t = m.todas || {}, g12 = m['G1+G2'] || {};
  const rg = d.rotulo_grau || {};
  const porGrau = ['G1', 'G2', 'G3', 'G0'].map(g => { const x = m[g] || {}; return `<tr><td><b>${g}</b> <span class="dim" style="font-size:12px">${esc(rg[g] || '')}</span></td>
      <td class="right">${fmtN(x.n)}</td><td class="right">${fmtR(x.valor_contratado)}</td><td class="right">${fmtN(x.autos_lidos)}</td>
      <td class="right">${fmtN(x.com_artefato)}</td><td class="right">${fmtN(x.com_sinal)}</td><td class="right">${fmtN(x.com_ob)}</td></tr>`; }).join('');
  const lin = (d.linhas || []).map(x => `<tr><td style="white-space:nowrap"><b>${esc(x.grau)}</b></td>
      <td style="font-size:13px"><b>${esc(x.orgao || '')}</b> · ${esc(x.processo || '')}<div>${esc(x.fornecedor || '')} — ${esc(x.objeto || '')}</div>
        ${x.irregularidade ? `<div class="dim" style="font-size:12px">CGE: ${esc(x.irregularidade)}</div>` : ''}</td>
      <td class="right" style="white-space:nowrap">${x.valor_contratado == null ? '—' : fmtR(x.valor_contratado)}</td>
      <td class="right">${x.autos_lidos ? fmtN(x.n_textos) + ' docs' : _sim(false)}</td>
      <td class="right">${_sim(x.jfn_artefato)}</td><td class="right">${_sim(x.jfn_sinal)}</td>
      <td class="right" style="white-space:nowrap">${x.ob_n == null ? '<span class="dim">indisp.</span>' : x.ob_n ? `${fmtR(x.ob_pago)} <span class="dim" style="font-size:11px">(${fmtN(x.ob_n)} OB)</span>` : '—'}</td></tr>`).join('');
  const hist = (d.historico || []).slice(-12).map(x => `<tr><td>${fmtData((x.data || '').slice(0, 10))}</td><td class="right">${fmtN(x.n)}</td>
      <td class="right">${fmtN(x.com_artefato)}</td><td class="right">${fmtN(x.com_sinal_g12)}</td><td class="right">${fmtN(x.autos_lidos)}</td><td class="right">${fmtN(x.relatorios_no_acervo)}</td></tr>`).join('');
  const novos = (d.relatorios_novos || []).length
    ? `<div class="warn" style="margin-top:8px">Relatório(s) da CGE no acervo ainda fora da lista confrontada: ${(d.relatorios_novos || []).map(esc).join(', ')} — ler e acrescentar à lista.</div>` : '';
  const ind = (d.fontes_indisponiveis || []).length ? `<div class="warn" style="margin-top:6px">Fontes INDISPONÍVEIS nesta rodada: ${(d.fontes_indisponiveis || []).map(esc).join(', ')} (não é zero).</div>` : '';
  return `<div class="grid g2" style="margin-top:8px">
      ${kpi(fmtN(t.n), 'Contratações auditadas pela CGE', null, '🔎', {sobre: 'Contratações examinadas nos relatórios de auditoria AGE/CGE que o JFN tem no acervo (lista transcrita dos relatórios). Não é o universo auditado pela CGE.'})}
      ${kpi(`${fmtN(t.com_artefato)} / ${fmtN(t.n)}`, `JFN com qualquer artefato (${_pct(t.com_artefato, t.n)})`, 'var(--amber)', '📂', {sobre: 'Dessas contratações, quantas têm no JFN algum alerta, ficha, achado ou caso no MESMO processo. Mede cobertura do sistema, não acerto.'})}
      ${kpi(`${fmtN(g12.com_sinal)} / ${fmtN(g12.n)}`, `JFN com sinal nas irregulares G1+G2 (${_pct(g12.com_sinal, g12.n)})`, 'var(--rose)', '🎯', {sobre: 'Entre as que a CGE classificou com dano ou irregularidade material, quantas o JFN já sinalizava. É o recall do sistema frente à CGE.'})}
      ${kpi(`${fmtN(t.autos_lidos)} / ${fmtN(t.n)}`, 'Autos lidos pelo JFN', null, '📄', {sobre: 'Processos dessas contratações com autos capturados do SEI no acervo do JFN.'})}
    </div>
    ${card(`<div style="font-size:12px;margin-bottom:6px">${_estado('VERIFICADO')} métricas medidas nas bases do JFN nesta rodada (${esc((d.gerado_em || '').slice(0, 16))}) · ${_estado('PENDENTE')} a lista de contratações e o grau G0–G3 são transcrição MANUAL dos relatórios da CGE (curadoria de ${esc(d.curado_em || '—')}) — conferir no relatório citado.</div>
      <div class="dim" style="font-size:12px"><b>Fonte:</b> ${esc(d.fonte || '')}<br><b>Cobertura:</b> ${esc(d.cobertura || '')}</div>${novos}${ind}
      <table class="tb rt-txt" style="margin-top:8px"><thead><tr><th>Grau (CGE)</th><th class="right">Contratações</th><th class="right">Contratado</th><th class="right">Autos lidos</th><th class="right">Com artefato</th><th class="right">Com sinal</th><th class="right">Com OB</th></tr></thead><tbody>${porGrau}</tbody></table>
      <details style="margin-top:10px"><summary style="cursor:pointer"><b>Processo a processo</b> (${fmtN((d.linhas || []).length)})</summary>
        <div style="max-height:620px;overflow:auto"><table class="tb rt-txt"><thead><tr><th>Grau</th><th>Contratação e o que a CGE apontou</th><th class="right">Contratado</th><th class="right">Autos</th><th class="right">Artefato</th><th class="right">Sinal</th><th class="right">OB pelo processo</th></tr></thead><tbody>${lin}</tbody></table></div></details>
      <details style="margin-top:8px"><summary style="cursor:pointer"><b>Histórico semanal</b> (${fmtN((d.historico || []).length)} medições)</summary>
        <table class="tb rt-txt"><thead><tr><th>Data</th><th class="right">Contratações</th><th class="right">Com artefato</th><th class="right">Sinal G1+G2</th><th class="right">Autos lidos</th><th class="right">Relatórios no acervo</th></tr></thead><tbody>${hist}</tbody></table></details>
      <div class="dim" style="font-size:12px;margin-top:6px">${esc(d.ressalva || '')}</div>${_rodape(d)}`)}`;
}

function _detectores(d){
  if (!d || d.ok === false) return card(`<div class="warn">Achados dos detectores INDISPONÍVEIS — ${esc((d && d.erro) || erroHumano(d))}. Não é zero.</div>`);
  const blocos = (d.detectores || []).map(x => {
    const st = Object.entries(x.por_status || {}).map(([k, v]) => `${esc(k)}: ${fmtN(v)}`).join(' · ');
    const cab = x.sem_execucao
      ? `<b>${esc(x.detector)}</b> — <span class="dim">ainda sem execução gravada (${esc(x.agenda || '')}); não é zero</span>`
      : `<b>${esc(x.detector)}</b> — ${fmtN(x.n_confirmado)} confirmado(s) em ${fmtN(x.n_ugs)} UG(s) · ${st} · última gravação ${esc((x.ultimo || '—').slice(0, 16))}${x.agenda ? ` <span class="dim" style="font-size:11px">· ${esc(x.agenda)}</span>` : ''}`;
    const it = (x.itens || []).map(i => `<tr><td style="white-space:nowrap">UG ${esc(i.ug || '')}<div class="dim" style="font-size:11px">${esc(i.processo || '')}</div></td>
        <td class="right">${i.score == null ? '—' : fmtN(i.score)}</td>
        <td style="font-size:13px">${esc(i.motivo)}${i.explicacao_inocente ? `<div class="dim" style="font-size:12px">Explicação inocente: ${esc(i.explicacao_inocente)}</div>` : ''}</td></tr>`).join('');
    return `<details style="margin-top:6px"${x.detector in {P7: 1, 'EST-VALOR-EXCEDIDO': 1, 'EST-ADITIVO-TETO': 1} ? ' open' : ''}><summary style="cursor:pointer">${cab}</summary>
      ${it ? `<div class="dim" style="font-size:12px">${_estado('PENDENTE')} indício do detector — exige leitura humana do processo. Listados ${fmtN((x.itens || []).length)} de ${fmtN(x.n_confirmado)} confirmados (maior score primeiro).</div><div style="max-height:420px;overflow:auto"><table class="tb rt-txt"><thead><tr><th>UG / processo</th><th class="right">Score</th><th>Motivo</th></tr></thead><tbody>${it}</tbody></table></div>` : '<div class="dim" style="font-size:12px">Sem achado confirmado.</div>'}</details>`;
  }).join('');
  return card(`<div style="font-size:13px"><b>${fmtN(d.n_confirmados)}</b> achados confirmados em ${fmtN((d.detectores || []).length)} detectores.</div>
    <div class="dim" style="font-size:12px;margin-top:4px"><b>Fonte:</b> ${esc(d.fonte || '')}. ${esc(d.ressalva || '')}</div>${blocos}`);
}

export async function renderCgeJfn(){
  const [c, dt] = await Promise.all([J('/api/cge_confronto', {tetoMs: 60000}), J('/api/detectores_achados', {tetoMs: 60000})]);
  let h = cover('estado', 'CGE × JFN e achados dos detectores',
    'O que a Controladoria auditou (Decreto 50.254/2026) × o que o JFN tem sobre o MESMO processo — recalculado toda semana. Abaixo, tudo o que os detectores gravaram, inclusive os semanais (P7 e valor contratual). Avaliação interna de desempenho; indício não é acusação.', '🔎');
  h += sec('1. Confronto CGE × JFN (recall por processo)');
  h += (!c || c.ok === false) ? card(`<div class="warn">${erroHumano(c)}</div>`) : _cge(c);
  h += sec('2. Achados dos detectores (achados.db)') + _detectores(dt);
  return `<div id="rt-cge">${h}${_txt}</div>`;
}
