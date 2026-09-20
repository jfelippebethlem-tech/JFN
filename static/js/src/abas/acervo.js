// ═══ ACERVO — uma busca, uma ficha, todo processo (Estado + Prefeitura) — 20/09/2026 ═══
// Busca por nº de processo, CNPJ, fornecedor, órgão ou termo → lista unificada → ficha com
// identidade, documentos (com leitura), OBs do SIAFE, contratos, agentes/assinantes, achados,
// perícias (ficha contábil/jurídica, avaliação 360, leitura estruturada), LAI e ações.
// Delegação por data-acervo (sem global novo no window).
import {$, esc, card, kpi, sec, cover, spin} from '../nucleo/dom.js';
import {J, erroHumano} from '../nucleo/http.js';
import {fmtN, fmtRc} from '../nucleo/formato.js';

let _q = '', _esf = 'todos', _ultimaFicha = null;

const GRAU = g => { const s = String(g || '').toUpperCase();
  if (/EXTREMO|ALTO|🔴|CRIT/.test(s)) return 'var(--rose)'; if (/MEDIO|MÉDIO|🟡|ATEN/.test(s)) return 'var(--amber)'; return null; };
const tag = (t, cor) => t ? `<span class="tag" ${cor ? `style="color:${cor};border-color:${cor}"` : ''}>${esc(t)}</span>` : '';
const _pre = (v) => `<pre style="white-space:pre-wrap;font-size:12px;max-height:340px;overflow:auto;margin:6px 0">${esc(typeof v === 'string' ? v : JSON.stringify(v, null, 1))}</pre>`;

export async function renderAcervo(){
  const st = await J('/api/acervo/estatisticas', {tetoMs: 30000});
  let h = cover('geral', 'Acervo — todo processo, uma ficha',
    'Digite um nº de processo (Estado ou Prefeitura), um CNPJ, um fornecedor, um órgão ou um termo. A ficha reúne documentos, OBs do SIAFE, contratos, agentes, achados, perícias e LAI de todas as bases da casa — e diz o que ainda não foi coletado.', '🗂️');
  if (st && st.ok) {
    h += `<div class="grid">
      ${kpi(fmtN(st.estado_arvores), 'Processos SEI do Estado (árvore)', null, null, {sobre: 'sei_arvore: processos estaduais com árvore lida e OBs ligadas.'})}
      ${kpi(fmtN(st.estado_avaliados_360), 'Avaliados 360', null, null, {sobre: 'processo_avaliacao: perícia 360 gravada (achados, lacunas, síntese).'})}
      ${kpi(fmtN(st.estado_obs_com_processo), 'Processos citados em OB (SIAFE)', null, null, {sobre: 'ob_orcamentaria_siafe.processo distinto com prefixo SEI-.'})}
      ${kpi(fmtN(st.pcrj_catalogo), 'Catálogo SEI municipal', null, null, {sobre: 'pcrj_processo: todos os processos públicos enumerados (2020→hoje).'})}
      ${kpi(fmtN(st.pcrj_com_integra), 'Municipais com íntegra', null, null, {sobre: 'pcrj_processo_doc: processos com pelo menos um documento com texto (CCON/conferência).'})}
      ${kpi(fmtN(st.pcrj_emergencias), 'Emergências à incumbente', 'var(--rose)', null, {sobre: 'pcrj_emergencia_sinal: dispensa por emergência a quem já era contratado do órgão.'})}
    </div>`;
  }
  h += card(`<form data-acervo-form="1" role="search" style="display:grid;grid-template-columns:3fr 1fr auto;gap:8px;align-items:end">
      <label>O que procurar<br><input id="ac-q" class="inp" style="width:100%" value="${esc(_q)}" placeholder="SEI-080001/000633/2024 · 000700.007924/2026-97 · SME-PRO-2025/38233 · CNPJ · fornecedor · órgão · termo"></label>
      <label>Esfera<br><select id="ac-esf" class="inp"><option value="todos">todas</option><option value="estado" ${_esf === 'estado' ? 'selected' : ''}>Estado</option><option value="prefeitura" ${_esf === 'prefeitura' ? 'selected' : ''}>Prefeitura</option></select></label>
      <button type="submit" class="btn accent">🔎 Buscar</button></form>
    <div id="ac-res" style="margin-top:10px">${_q ? spin() : '<div class="dim">Resultados ordenados por valor pago; clique no nº para abrir a ficha.</div>'}</div>`);
  h += `<div id="ac-ficha" style="margin-top:12px"></div>`;
  if (_q) setTimeout(() => acervoBuscar(_q, _esf), 0);
  return h;
}

async function acervoBuscar(q, esf){
  _q = q; _esf = esf; const o = $('ac-res'); if (!o) return;
  o.innerHTML = spin('Buscando "' + esc(q) + '"…');
  const r = await J('/api/acervo/buscar?q=' + encodeURIComponent(q) + '&esfera=' + encodeURIComponent(esf) + '&limite=100', {tetoMs: 60000});
  if (!r || !r.ok) { o.innerHTML = card(`<div class="warn">${esc(erroHumano((r || {}).erro || 'a busca não respondeu'))}</div>`); return; }
  const it = r.hits || [];
  if (!it.length) { o.innerHTML = card('<div class="dim">Nada encontrado nas bases da casa. Nº de processo desconhecido pode ser capturado: Estado → sei_fila_captura; Prefeitura → busca livre no SEI municipal.</div>'); return; }
  o.innerHTML = `<div class="dim" style="margin-bottom:6px">${fmtN(it.length)} resultado(s) · ${esc(r.tipo)}${r.esferas ? ` · Estado ${fmtN(r.esferas.estado)} · Prefeitura ${fmtN(r.esferas.prefeitura)}` : ''}</div>
    <div style="overflow-x:auto"><table class="tb"><thead><tr><th>esfera</th><th>processo</th><th>objeto / tipo</th><th>órgão / fornecedor</th><th>grau</th><th>pago</th><th>docs</th><th>fontes</th></tr></thead><tbody>`
    + it.map(h => `<tr><td>${esc(h.esfera)}</td><td><a href="#" data-acervo="abrir" data-numero="${esc(h.numero)}"><b>${esc(h.numero)}</b></a></td>
      <td>${esc((h.objeto || '').slice(0, 110))}</td><td>${esc((h.fornecedor || h.orgao || '').slice(0, 50))}</td><td>${tag(h.grau, GRAU(h.grau))}${h.n_achados ? ' ' + tag(h.n_achados + ' achado(s)', 'var(--rose)') : ''}</td>
      <td class="num">${h.total_pago != null ? fmtRc(h.total_pago) : '—'}</td><td>${h.n_docs != null ? fmtN(h.n_docs) : '—'}</td><td class="dim">${esc(h.fonte || '')}</td></tr>`).join('')
    + `</tbody></table></div>`;
  if (r.tipo === 'numero' && it.length === 1) acervoAbrir(it[0].numero);
}

function _secDocs(f){
  const docs = f.documentos || [];
  if (!docs.length) return card('<div class="dim">Nenhum documento listado ainda.</div>');
  const comTexto = docs.filter(d => d.texto_path || d.com_texto).length;
  return `<div class="dim" style="margin-bottom:4px">${fmtN(docs.length)} documento(s) · ${fmtN(comTexto)} com texto legível · clique em "ler"</div>
    <div style="overflow-x:auto;max-height:420px;overflow-y:auto"><table class="tb"><thead><tr><th>#</th><th>documento</th><th>tipo / fase</th><th>unidade / data</th><th>chars</th><th></th></tr></thead><tbody>`
    + docs.map(d => `<tr><td>${esc(d.seq)}</td><td>${esc((d.titulo || '').slice(0, 100))}</td><td class="dim">${esc(d.tipo || '')}${d.fase ? ' · ' + esc(d.fase) : ''}</td>
      <td class="dim">${esc(d.unidade || '')}${d.data ? ' · ' + esc(d.data) : ''}</td><td class="num">${d.chars ? fmtN(d.chars) : '—'}${d.ocr ? ' <span class="tag">OCR</span>' : ''}</td>
      <td>${(d.texto_path || d.com_texto) ? `<button type="button" class="btn ghost" data-acervo="ler" data-numero="${esc(f.numero)}" data-seq="${esc(d.seq)}">ler</button>` : (d.url ? `<a class="dim" href="${esc(d.url)}" target="_blank" rel="noopener">fonte</a>` : '<span class="dim">só listado</span>')}</td></tr>`).join('')
    + `</tbody></table></div><div id="ac-doc" style="margin-top:8px"></div>`;
}

function _secAchados(f){
  const a = f.achados || [];
  let h = '';
  if (a.length) h += `<div style="overflow-x:auto"><table class="tb"><thead><tr><th>fonte</th><th>código</th><th>grau</th><th>o que diz</th><th>apoio</th></tr></thead><tbody>`
    + a.map(x => `<tr><td class="dim">${esc(x.fonte)}</td><td><b>${esc(x.codigo || '')}</b></td><td>${tag(x.grau, GRAU(x.grau))}${x.score != null ? ' ' + esc(x.score) : ''}</td><td>${esc((x.diz || '').slice(0, 220))}</td><td class="dim">${esc((x.apoio || '').slice(0, 160))}</td></tr>`).join('') + `</tbody></table></div>`;
  else h += '<div class="dim">Nenhum achado gravado para este processo (não é ausência de problema: ver cobertura).</div>';
  return h;
}

function _secPericias(f){
  const p = f.pericias || {}; let h = '';
  if (p.contabil || p.juridica || p.red_flags) {
    h += `<div class="grid g2">${p.contabil ? card(`<div style="font-weight:700">Perícia contábil (ficha)</div>${_pre(p.contabil)}`) : ''}${p.juridica ? card(`<div style="font-weight:700">Perícia jurídica (ficha)</div>${_pre(p.juridica)}`) : ''}</div>`;
    if (p.red_flags) h += card(`<div style="font-weight:700">Red flags da ficha ${tag(p.nivel_risco, GRAU(p.nivel_risco))}</div>${_pre(p.red_flags)}<div class="dim">modelo: ${esc(p.fonte_modelo || '—')} · ${esc(p.atualizado_em || '')}</div>`);
  }
  const a = f.avaliacao_360;
  if (a) {
    h += card(`<div style="font-weight:700">Avaliação 360 ${tag(a.grau, GRAU(a.grau))} · score ${esc(a.score100)} · ${esc(a.faixa || '')} · vencedor ${esc(a.cnpj_vencedor || '—')} · ${esc(a.avaliado_em || '')}</div>
      ${(a.lacunas || []).length ? `<div style="margin-top:6px"><b>Lacunas</b>: ${esc((a.lacunas || []).map(l => typeof l === 'string' ? l : (l.diz || l.codigo || JSON.stringify(l))).join(' · ').slice(0, 600))}</div>` : ''}
      ${a.sintese ? `<details><summary>síntese do conjunto</summary>${_pre(a.sintese)}</details>` : ''}`);
  }
  if (p.leitura_estruturada && Object.keys(p.leitura_estruturada).length) {
    h += card(`<div style="font-weight:700">Leitura estruturada dos documentos obtidos</div><div style="overflow-x:auto"><table class="tb"><thead><tr><th>campo</th><th>valores</th></tr></thead><tbody>`
      + Object.entries(p.leitura_estruturada).map(([k, v]) => `<tr><td><b>${esc(k)}</b></td><td>${esc([...new Set(v.map(x => x.valor))].slice(0, 12).join(' · ').slice(0, 300))}</td></tr>`).join('') + `</tbody></table></div>`);
  }
  return h || '<div class="dim">Sem perícia gravada — use "Avaliar 360" (Estado) ou aguarde a leitura estruturada (Prefeitura).</div>';
}

export async function acervoAbrir(numero){
  const o = $('ac-ficha'); if (!o) return;
  o.innerHTML = spin('Reunindo tudo sobre ' + esc(numero) + '…');
  const f = await J('/api/acervo/processo?numero=' + encodeURIComponent(numero), {tetoMs: 90000});
  if (!f || !f.ok) { o.innerHTML = card(`<div class="warn">${esc(erroHumano((f || {}).erro || 'ficha indisponível'))}</div>`); return; }
  _ultimaFicha = f;
  const id = f.identidade || {}, cob = f.cobertura || {};
  let h = sec(`${f.esfera === 'estado' ? 'Estado' : 'Prefeitura'} · ${esc(f.numero)}`);
  h += card(`<div style="font-weight:700;font-size:15px">${esc(id.objeto || id.tipo || '(sem objeto na base)')}</div>
    <div class="dim" style="margin-top:4px">${[id.modalidade, id.fundamento_legal, id.unidade || id.orgao, id.situacao, id.lifecycle, id.sistema].filter(Boolean).map(esc).join(' · ')}</div>
    <div style="margin-top:6px">${tag(id.nivel_risco, GRAU(id.nivel_risco))} ${f.avaliacao_360 ? tag('360: ' + f.avaliacao_360.grau, GRAU(f.avaliacao_360.grau)) : ''} ${f.n_achados ? tag(f.n_achados + ' achado(s)', 'var(--rose)') : ''} ${id.disponivel_na_pesquisa_publica === 0 ? tag('indisponível na pesquisa pública', 'var(--amber)') : ''}</div>
    ${id.resumo ? `<div style="margin-top:8px">${esc(String(id.resumo).slice(0, 900))}</div>` : ''}
    <div style="margin-top:8px"><b>Cobertura:</b> ${Object.entries(cob).map(([k, v]) => `<span class="tag">${esc(k)}: ${esc(v)}</span>`).join(' ')}</div>
    <div class="btns" style="margin-top:8px">${(f.acoes || []).map(a => a.metodo === 'dossie'
      ? `<button type="button" class="btn ghost" data-acervo="dossie" data-cnpj="${esc(a.cnpj)}" data-nome="${esc(a.nome || '')}">${esc(a.rotulo)}</button>`
      : `<button type="button" class="btn ghost" data-acervo="acao" data-rota="${esc(a.rota)}" data-body='${esc(JSON.stringify(a.body))}'>${esc(a.rotulo)}</button>`).join(' ')}
      <span id="ac-acao-out" class="dim"></span></div>`);
  const obs = f.obs || {};
  if (obs.n) {
    h += sec('Pagamentos ligados ao processo', obs.n) + card(`<div class="dim">${esc(obs.fonte)}</div><div class="num" style="font-size:20px;font-weight:800">${fmtRc(obs.total)}</div>`
      + ((obs.por_credor || []).length ? `<div style="overflow-x:auto"><table class="tb"><thead><tr><th>credor</th><th>OBs</th><th>total</th><th>período</th><th>UGs</th></tr></thead><tbody>`
        + obs.por_credor.map(c => `<tr><td>${esc(c.nome_credor || c.credor)}</td><td>${fmtN(c.n)}</td><td class="num">${fmtRc(c.total)}</td><td class="dim">${esc(c.primeira || '')} → ${esc(c.ultima || '')}</td><td class="dim">${esc(c.ugs || '')}</td></tr>`).join('') + `</tbody></table></div>` : ''));
  }
  if ((f.contratos || []).length) {
    h += sec('Contratos e fornecedores', f.contratos.length) + `<div style="overflow-x:auto"><table class="tb"><thead><tr><th>fonte</th><th>fornecedor</th><th>órgão</th><th>forma / objeto</th><th>valor</th><th>pago</th><th>vigência</th><th></th></tr></thead><tbody>`
      + f.contratos.map(c => `<tr><td class="dim">${esc(c.fonte || '')}</td><td>${esc(c.nome || '')}<div class="dim">${esc(c.cnpj || '')}</div></td><td class="dim">${esc((c.orgao || '').slice(0, 40))}</td><td>${esc(((c.forma_contratacao ? c.forma_contratacao + ': ' : '') + (c.objeto || '')).slice(0, 120))}</td>
        <td class="num">${c.valor != null ? fmtRc(c.valor) : '—'}</td><td class="num">${c.total_pago != null ? fmtRc(c.total_pago) : '—'}</td><td class="dim">${esc(c.vigencia_ini || '')}${c.vigencia_fim ? ' → ' + esc(c.vigencia_fim) : ''}</td>
        <td>${c.url_ccon ? `<a href="${esc(c.url_ccon)}" target="_blank" rel="noopener">anexos</a>` : ''}</td></tr>`).join('') + `</tbody></table></div>`;
  }
  h += sec('Achados', (f.achados || []).length) + _secAchados(f);
  h += sec('Perícias') + _secPericias(f);
  if ((f.agentes || []).length) {
    h += sec('Agentes públicos no processo', f.agentes.length) + `<div style="overflow-x:auto"><table class="tb"><thead><tr><th>nome</th><th>papel</th><th>cargo / lotação</th><th>detalhe</th></tr></thead><tbody>`
      + f.agentes.map(a => `<tr><td><b>${esc(a.nome || '')}</b></td><td>${esc(a.papel || '')}</td><td class="dim">${esc(a.cargo || '')}</td><td class="dim">${esc(a.n_assinaturas ? a.n_assinaturas + ' assinatura(s) · ' + (a.primeira || '') + ' → ' + (a.ultima || '') : (a.contexto || a.contrato || a.origem || ''))}</td></tr>`).join('') + `</tbody></table></div>`;
  }
  h += sec('Documentos', (f.documentos || []).length) + _secDocs(f);
  if ((id.andamentos || []).length) {
    h += sec('Andamentos (últimos)', id.andamentos.length) + `<div style="max-height:260px;overflow:auto"><table class="tb"><tbody>` + id.andamentos.map(a => `<tr><td class="dim">${esc(a.quando)}</td><td class="dim">${esc(a.unidade)}</td><td>${esc((a.descricao || '').slice(0, 160))}</td></tr>`).join('') + `</tbody></table></div>`;
  }
  if ((f.lai || []).length) {
    h += sec('Pedidos LAI', f.lai.length) + `<table class="tb"><tbody>` + f.lai.map(l => `<tr><td>#${l.id}</td><td>${esc(l.status)}</td><td>${esc(l.protocolo || '—')}</td><td class="dim">${esc(l.prazo_resposta || '')}</td><td class="dim">${esc(l.criado_em || '')}</td></tr>`).join('') + `</tbody></table>`;
  }
  o.innerHTML = h;
  o.scrollIntoView({behavior: 'smooth', block: 'start'});
}

async function acervoLer(numero, seq){
  const o = $('ac-doc'); if (!o) return;
  o.innerHTML = spin('lendo documento ' + esc(seq) + '…');
  const d = await J('/api/acervo/documento?numero=' + encodeURIComponent(numero) + '&seq=' + encodeURIComponent(seq), {tetoMs: 30000});
  if (!d || !d.ok) { o.innerHTML = card(`<div class="warn">${esc(erroHumano((d || {}).erro || 'sem texto'))}</div>`); return; }
  o.innerHTML = card(`<div style="font-weight:700">${esc(d.titulo || seq)}</div><pre style="white-space:pre-wrap;font-size:12px;max-height:520px;overflow:auto">${esc(d.texto || '')}</pre>`);
}

async function acervoAcao(rota, body){
  const o = $('ac-acao-out'); if (o) o.textContent = 'acionando…';
  try {
    const d = await J(rota, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body), tetoMs: 120000});
    if (o) o.textContent = (d && (d.resumo || d.msg || d.status || (d.ok ? 'ok' : erroHumano(d.erro || 'falhou')))) || 'sem resposta';
  } catch (e) { if (o) o.textContent = erroHumano(String(e)); }
}

/* Delegação por data-acervo — sem nome novo no window (teto de globais do painel). */
export function ligarAcervo(){
  document.addEventListener('submit', ev => {
    const f = ev.target.closest && ev.target.closest('[data-acervo-form]');
    if (!f) return;
    ev.preventDefault();
    acervoBuscar(($('ac-q')?.value || '').trim(), $('ac-esf')?.value || 'todos');
  });
  document.addEventListener('click', ev => {
    const b = ev.target.closest && ev.target.closest('[data-acervo]');
    if (!b) return;
    ev.preventDefault();
    const a = b.dataset.acervo;
    if (a === 'abrir') acervoAbrir(b.dataset.numero);
    else if (a === 'ler') acervoLer(b.dataset.numero, b.dataset.seq);
    else if (a === 'acao') acervoAcao(b.dataset.rota, JSON.parse(b.dataset.body || '{}'));
    else if (a === 'dossie' && typeof window.abrirDossie === 'function') window.abrirDossie(b.dataset.cnpj, b.dataset.nome);
  });
}
