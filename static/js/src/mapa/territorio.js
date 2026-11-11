/* v61 — MAPA DO TERRITÓRIO (o coração do Início).
 *
 * Dois escopos, e nenhum deles é "contrato de prefeitura por município":
 *   estado  contratos do ESTADO (Executivo estadual) por MUNICÍPIO de execução  → /api/territorio/estado
 *   pcrj    contratos da PREFEITURA DO RIO por ÁREA DE PLANEJAMENTO (AP1…AP5)   → /api/territorio/pcrj
 *
 * Geometria: TopoJSON em `static/assets/geo/` (IBGE e Data.Rio; `tools/v61_geo.sh`). Projeção
 * `geoMercator().fitSize` — nada desenhado à mão. Render em SVG; o que é dado é código.
 *
 * REGRAS DE HONESTIDADE DESTA TELA
 *   · Sem resposta da API → todo o mapa em hachura e a faixa "dados do território: INDISPONÍVEL".
 *   · Território sem contrato ATRIBUÍDO → hachura + "sem dado" na legenda. Nunca pintado como zero:
 *     há contratos sem município identificado, e o balde deles fica sempre visível no rodapé.
 *   · Contrato de vários municípios não tem o valor repartido (seria número inventado): vai para o
 *     balde "vários municípios"; cada município só diz de quantos desses participa.
 *   · `pago` nulo (sem OB vinculada) aparece como INDISPONÍVEL, não como R$ 0,00.
 */
import {geoMercator, geoPath} from 'd3-geo';
import {feature, mesh} from 'topojson-client';
import {$, esc} from '../nucleo/dom.js';
import {fmtN, fmtR} from '../nucleo/formato.js';
import {_redMotion} from '../capacidade/estado.js';
import {aoVivoOuvir} from '../aovivo/estado.js';
import {abrirDossie} from '../ui/index.js';

const GEO = '/static/assets/geo/';
const W = 800, H = 520;
const RAMPA = ['#EAF4FF', '#B9D9FB', '#6FAEF6', '#1E7BF0', '#0A3E8C'];
const RIO = '3304557';
const METRICAS = [
  ['valor_contratado', 'Valor contratado', 'rs'],
  ['valor_em_execucao', 'Em execução', 'rs'],
  ['pago', 'Pago', 'rs'],
  ['n_contratos', 'Nº de contratos', 'n'],
  ['n_alertas', 'Alertas', 'n'],
];
const PERIODOS = [['vigentes', 'Vigentes hoje'], ['2023', '2023–hoje'], ['tudo', 'Tudo']];
const METODO = {campo: 'campo', orcamento: 'orçamento', unidade: 'unidade', endereco: 'endereço', texto: 'texto',
                orgao: 'órgão regional'};
const STATUS = {em_execucao: 'Em execução', executado: 'Executado', rescindido: 'Rescindido'};

const rs = v => (v == null ? 'INDISPONÍVEL' : fmtR(v));
const pct = v => (v == null ? 'INDISPONÍVEL' : (Math.round(v * 1000) / 10).toLocaleString('pt-BR') + '%');
const dma = s => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || ''); return m ? `${m[3]}/${m[2]}/${m[1]}` : '—'; };
const dmhm = s => { const d = s ? new Date(s) : null; if (!d || isNaN(d)) return '—';
  const p = n => String(n).padStart(2, '0'); return `${p(d.getDate())}/${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`; };
/* valor curto para legenda/tooltip de eixo: R$ 1,2 bi · R$ 340 mi · R$ 12 mil (o valor inteiro fica na ficha) */
const curto = (v, tipo) => {
  if (v == null) return '—'; if (tipo === 'n') return fmtN(Math.round(v));
  const a = Math.abs(v), f = (x, s) => 'R$ ' + x.toLocaleString('pt-BR', {maximumFractionDigits: x < 10 ? 1 : 0}) + s;
  return a >= 1e9 ? f(v / 1e9, ' bi') : a >= 1e6 ? f(v / 1e6, ' mi') : a >= 1e3 ? f(v / 1e3, ' mil') : f(v, '');
};

const _topo = {};
async function topo(nome) {
  if (!_topo[nome]) _topo[nome] = fetch(GEO + nome + '.topo.json', {credentials: 'same-origin'}).then(r => { if (!r.ok) throw new Error(nome); return r.json(); });
  return _topo[nome];
}
async function api(caminho) {
  try { const r = await fetch('/api/territorio/' + caminho, {credentials: 'same-origin'}); if (!r.ok) return null; return await r.json(); }
  catch (_) { return null; }
}

let _vivo = null;     // instância montada (uma por cockpit)

export function mapaMontar(host) {
  if (!host) return;
  if (_vivo) _vivo.sair();
  const S = {escopo: 'estado', metrica: 'valor_contratado', periodo: 'vigentes', dados: {}, sel: null};
  host.classList.add('tm');
  host.innerHTML = `
    <div class="tm-topo">
      <h2 class="tm-tit v61-disp" id="tm-tit">Território</h2>
      <div class="tm-ctl">
        <div class="chips" role="group" aria-label="Escopo">
          <button type="button" class="chip on" data-tm-escopo="estado">Estado · por município</button>
          <button type="button" class="chip" data-tm-escopo="pcrj">Prefeitura do Rio · por AP</button>
        </div>
        <div class="chips" role="group" aria-label="Métrica">${METRICAS.map(([k, r], i) =>
          `<button type="button" class="chip${i ? '' : ' on'}" data-tm-metrica="${k}">${r}</button>`).join('')}</div>
        <div class="chips" role="group" aria-label="Período">${PERIODOS.map(([k, r], i) =>
          `<button type="button" class="chip${i ? '' : ' on'}" data-tm-periodo="${k}">${r}</button>`).join('')}
          <select class="tm-ir" id="tm-ir" aria-label="Abrir a ficha de um território"><option value="">Ir para…</option></select>
        </div>
      </div>
    </div>
    <div class="tm-palco" id="tm-palco">
      <div class="tm-placa" id="tm-placa">
        <svg class="tm-svg" viewBox="0 0 ${W} ${H}" role="group" aria-label="Mapa">
          <defs><pattern id="tm-hach" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="#EEF4FB"/><line x1="0" y1="0" x2="0" y2="6" stroke="#9FB9D9" stroke-width="1.4"/></pattern></defs>
          <g class="tm-cam" id="tm-cam"><g class="tm-g tm-est" id="tm-est"></g></g>
          <g class="tm-g tm-rio" id="tm-rio"></g>
          <g class="tm-pulsos" id="tm-pulsos"></g>
        </svg>
        <div class="tm-radar" aria-hidden="true"></div>
      </div>
      <div class="tm-dica" id="tm-dica" role="status" hidden></div>
      <div class="tm-aviso" id="tm-aviso" hidden></div>
      <div class="tm-leg" id="tm-leg"></div>
      <aside class="tm-ficha" id="tm-ficha" aria-live="polite" hidden></aside>
    </div>
    <div class="tm-pe" id="tm-pe">Fonte: lendo…</div>`;

  const q = s => host.querySelector(s);
  const gEst = q('#tm-est'), gRio = q('#tm-rio'), cam = q('#tm-cam'), dica = q('#tm-dica'), ficha = q('#tm-ficha');
  const geo = {est: null, rio: null};      // {feats, path, centro: Map}

  /* ── geometria ── */
  async function carregarEstado() {
    const t = await topo('rj-municipios');
    const fc = feature(t, t.objects.municipios);
    const path = geoPath(geoMercator().fitExtent([[14, 14], [W - 14, H - 14]], fc));
    const centro = new Map();
    gEst.innerHTML = fc.features.map(f => { const k = f.properties.cod_ibge; centro.set(k, path.centroid(f));
      return `<path class="tm-a" data-k="${k}" d="${path(f)}" tabindex="-1"><title>${esc(f.properties.nome)}</title></path>`; }).join('')
      + `<path class="tm-div" d="${path(mesh(t, t.objects.municipios, (a, b) => a !== b))}"/>`;
    geo.est = {feats: fc.features, path, centro, nomes: new Map(fc.features.map(f => [f.properties.cod_ibge, f.properties.nome]))};
    const rio = fc.features.find(f => f.properties.cod_ibge === RIO);
    geo.est.caixaRio = rio ? path.bounds(rio) : null;
  }
  async function carregarRio() {
    if (geo.rio) return;
    const t = await topo('rio-aps');
    const aps = feature(t, t.objects.aps);
    const path = geoPath(geoMercator().fitExtent([[24, 24], [W - 24, H - 24]], aps));
    const centro = new Map();
    gRio.innerHTML = aps.features.map(f => { const k = String(f.properties.ap); centro.set(k, path.centroid(f));
      return `<path class="tm-a" data-k="${k}" d="${path(f)}" tabindex="-1"><title>AP ${k}</title></path>`; }).join('')
      + `<path class="tm-div fina" d="${path(mesh(t, t.objects.ras, (a, b) => a !== b))}"/>`
      + `<path class="tm-div" d="${path(mesh(t, t.objects.aps, (a, b) => a !== b))}"/>`
      + aps.features.map(f => { const c = path.centroid(f); return `<text class="tm-rot" x="${c[0].toFixed(1)}" y="${c[1].toFixed(1)}">AP ${f.properties.ap}</text>`; }).join('');
    const ras = feature(t, t.objects.ras).features.map(f => f.properties);
    geo.rio = {path, centro, ras, nomes: new Map(aps.features.map(f => [String(f.properties.ap), 'AP ' + f.properties.ap]))};
  }

  /* ── dados ── */
  const chave = () => S.escopo + '|' + S.periodo;
  async function lerDados() {
    const k = chave();
    if (S.dados[k] === undefined) S.dados[k] = await api(`${S.escopo}?periodo=${S.periodo}`);
    return S.dados[k];
  }
  const linhas = d => !d ? [] : (S.escopo === 'estado' ? d.municipios : d.aps) || [];
  const idDe = l => S.escopo === 'estado' ? String(l.cod_ibge) : String(l.ap);
  const valorDe = l => { const v = l[S.metrica]; return (v == null || !(l.n_contratos > 0)) ? null : Number(v); };

  /* ── pintura (coroplético por quantis) ── */
  function pintar(d) {
    const g = S.escopo === 'estado' ? gEst : gRio, G = S.escopo === 'estado' ? geo.est : geo.rio;
    if (!G) return;
    const por = new Map(linhas(d).map(l => [idDe(l), l]));
    const vals = [...por.values()].map(valorDe).filter(v => v != null && v > 0).sort((a, b) => a - b);
    const cortes = [];
    if (vals.length) for (let i = 1; i < RAMPA.length; i++) cortes.push(vals[Math.min(vals.length - 1, Math.floor(i * vals.length / RAMPA.length))]);
    const classe = v => { let c = 0; while (c < cortes.length && v >= cortes[c]) c++; return c; };
    const tipo = METRICAS.find(m => m[0] === S.metrica)[2];
    let semDado = 0;
    g.querySelectorAll('path.tm-a').forEach(p => {
      const l = por.get(p.dataset.k), v = l ? valorDe(l) : null;
      const tem = v != null && v > 0;
      p.style.fill = tem ? RAMPA[classe(v)] : 'url(#tm-hach)';
      p.classList.toggle('tm-sd', !tem); if (!tem) semDado++;
      const nome = G.nomes.get(p.dataset.k) || p.dataset.k;
      p.setAttribute('aria-label', tem ? `${nome}: ${curto(v, tipo)}` : `${nome}: sem dado`);
    });
    /* legenda */
    const faixas = !vals.length ? '' : RAMPA.map((c, i) => {
      const de = i ? cortes[i - 1] : vals[0], ate = i < cortes.length ? cortes[i] : vals[vals.length - 1];
      return `<span class="tm-lg"><i style="background:${c}"></i>${i === RAMPA.length - 1 ? '≥ ' + curto(de, tipo) : curto(de, tipo) + (ate > de ? ' – ' + curto(ate, tipo) : '')}</span>`; }).join('');
    q('#tm-leg').innerHTML = faixas + `<span class="tm-lg"><i class="hach"></i>sem dado${semDado ? ` (${fmtN(semDado)})` : ''}</span>`;
    /* aviso + rodapé */
    const av = q('#tm-aviso');
    av.hidden = !!d; if (!d) av.innerHTML = '<b>dados do território: INDISPONÍVEL</b> — a API <code>/api/territorio</code> não respondeu (a rota entra no próximo reinício do serviço). O mapa mostra só as divisas.';
    q('#tm-pe').innerHTML = rodape(d);
    /* seletor "Ir para…" */
    const sel = q('#tm-ir'), ids = [...G.nomes.entries()].sort((a, b) => a[1].localeCompare(b[1], 'pt-BR', {numeric: true}));
    sel.innerHTML = `<option value="">${S.escopo === 'estado' ? 'Ir para município…' : 'Ir para AP…'}</option>` + ids.map(([k, n]) => `<option value="${k}">${esc(n)}</option>`).join('');
    q('#tm-tit').textContent = S.escopo === 'estado' ? 'Contratos do Estado · por município' : 'Prefeitura do Rio · por área de planejamento';
  }
  function rodape(d) {
    if (!d) return 'Fonte: INDISPONÍVEL';
    const b = d.baldes || {}, p = [];
    p.push(`Fonte: ${esc(d.fonte || '—')}`, `atualizado em <span class="num">${dmhm(d.atualizado_em)}</span>`);
    const um = (x, rot) => x && x.n ? `<b class="num">${fmtN(x.n)}</b> ${rot} (<span class="num">${rs(x.valor)}</span>)` : '';
    if (S.escopo === 'estado') {
      p.push(um(b.sem_municipio, 'contratos sem município identificado') || '<b class="num">0</b> contratos sem município identificado');
      p.push(um(b.multimunicipio, 'em vários municípios'), um(b.estado_inteiro, 'do Estado inteiro / sede'), um(b.regiao, 'só com região'));
    } else {
      p.push(um(b.sem_ap, 'contratos sem AP identificada') || '<b class="num">0</b> contratos sem AP identificada');
      p.push(um(b.multi_ap, 'em várias APs'), um(b.cidade_inteira, 'da cidade inteira / sede'));
    }
    const at = b.atribuido, tt = b.total;
    if (at && tt && tt.valor > 0) p.push(`cobertura: <b class="num">${(100 * at.valor / tt.valor).toLocaleString('pt-BR', {maximumFractionDigits: 1})}%</b> do valor em ${S.escopo === 'estado' ? 'um município' : 'uma AP'}`);
    if (d.confianca_texto === 'baixa') p.push('atribuição por <b>texto</b> com confiança <b>baixa</b> (auditoria &lt; 85%)');
    return p.filter(Boolean).join(' · ');
  }

  /* ── tooltip de vidro ── */
  function mostrarDica(p, ev) {
    const d = S.dados[chave()], G = S.escopo === 'estado' ? geo.est : geo.rio;
    const l = linhas(d).find(x => idDe(x) === p.dataset.k), nome = G.nomes.get(p.dataset.k) || '';
    const tem = l && l.n_contratos > 0;
    dica.innerHTML = `<b>${esc(nome)}</b>` + (!d ? '<span>dados: INDISPONÍVEL</span>' : !tem ? '<span>nenhum contrato atribuído</span>'
      : `<span class="num">${rs(l.valor_contratado)}</span><span><b class="num">${fmtN(l.n_contratos)}</b> contratos · <b class="num">${fmtN(l.n_em_execucao)}</b> em execução</span>`
        + `<span>executado: <b class="num">${pct(l.pct_executado)}</b></span>`
        + (l.n_multi ? `<span>participa de <b class="num">${fmtN(l.n_multi)}</b> multimunicipais</span>` : ''));
    dica.hidden = false;
    const r = q('#tm-palco').getBoundingClientRect(), b = p.getBoundingClientRect();
    const x = (ev && ev.clientX != null && ev.pointerType === 'mouse' ? ev.clientX : b.left + b.width / 2) - r.left;
    const y = (ev && ev.clientY != null && ev.pointerType === 'mouse' ? ev.clientY : b.top) - r.top;
    dica.style.left = Math.max(8, Math.min(r.width - dica.offsetWidth - 8, x - dica.offsetWidth / 2)) + 'px';
    dica.style.top = Math.max(8, y - dica.offsetHeight - 14) + 'px';
  }
  const sumirDica = () => { dica.hidden = true; };

  /* ── ficha ── */
  async function abrirFicha(k) {
    S.sel = k;
    host.querySelectorAll('path.tm-a.on').forEach(p => p.classList.remove('on'));
    const g = S.escopo === 'estado' ? gEst : gRio, p = g.querySelector(`path.tm-a[data-k="${k}"]`);
    if (p) { p.classList.add('on'); g.insertBefore(p, g.querySelector('.tm-div')); }
    const G = S.escopo === 'estado' ? geo.est : geo.rio, nome = G.nomes.get(k) || k;
    ficha.hidden = false; ficha.classList.add('on'); host.classList.add('tm-com-ficha');
    ficha.innerHTML = `<div class="tf-alca" data-tf-alca></div><button type="button" class="tf-x" data-tf-x aria-label="Fechar a ficha">✕</button>
      <h3 class="v61-disp">${esc(nome)}</h3><div class="dim">lendo…</div>`;
    const f = await api(`${S.escopo}/${encodeURIComponent(k)}?periodo=${S.periodo}`);
    if (S.sel !== k) return;
    ficha.innerHTML = `<div class="tf-alca" data-tf-alca></div><button type="button" class="tf-x" data-tf-x aria-label="Fechar a ficha">✕</button>` + fichaHTML(nome, f);
    ficha.scrollTop = 0;
  }
  function fecharFicha() { S.sel = null; ficha.classList.remove('on'); ficha.hidden = true; ficha.style.transform = ''; host.classList.remove('tm-com-ficha');
    host.querySelectorAll('path.tm-a.on').forEach(p => p.classList.remove('on')); }
  function fichaHTML(nome, f) {
    const sub = S.escopo === 'estado' ? 'Contratos do Estado executados neste município' : 'Contratos da Prefeitura do Rio nesta área de planejamento';
    if (!f) return `<h3 class="v61-disp">${esc(nome)}</h3><p class="tf-sub">${sub}</p><div class="tf-indisp"><b>INDISPONÍVEL</b> — a API do território não respondeu.</div>`;
    const k = f.kpis || {}, kp = (r, v) => `<div class="tf-k"><span>${r}</span><b class="num">${v}</b></div>`;
    const maxO = Math.max(1, ...(f.orgaos || []).map(o => o.valor || 0));
    const selo = c => `<span class="tf-selo m-${esc(c.metodo || '')} c-${esc(c.confianca || '')}" title="${esc(c.evidencia || '')}">${esc(METODO[c.metodo] || c.metodo || '—')} · ${esc(c.confianca || '—')}</span>`;
    return `<h3 class="v61-disp">${esc(nome)}</h3><p class="tf-sub">${sub} · ${esc((PERIODOS.find(p => p[0] === S.periodo) || [])[1] || '')}</p>
      <div class="tf-kpis">${kp('Em execução', fmtN(k.n_em_execucao))}${kp('Executados', fmtN(k.n_executados))}
        ${kp('Valor contratado', rs(k.valor_contratado))}${kp('Pago', rs(k.pago))}${kp('% executado', pct(k.pct_executado))}</div>
      <p class="tf-nota">${k.n_com_pago ? `Pago e % executado consideram só os <b class="num">${fmtN(k.n_com_pago)}</b> de <b class="num">${fmtN(k.n_contratos)}</b> contratos com pagamento vinculado.` : 'Nenhum contrato desta seleção tem pagamento vinculado: pago <b>INDISPONÍVEL</b> (≠ zero).'}${f.nota_pago ? ' ' + esc(f.nota_pago) + '.' : ''}</p>
      ${k.n_multi ? `<p class="tf-nota">Participa de <b class="num">${fmtN(k.n_multi)}</b> contratos multimunicipais (valor não repartido — fica no balde "vários municípios").</p>` : ''}
      ${f.ras && f.ras.length ? `<h4>Regiões administrativas</h4><div class="tf-ras">${f.ras.map(r => `<span class="tag">${esc(r)}</span>`).join('')}</div>` : ''}
      <h4>Órgãos ${S.escopo === 'estado' ? 'estaduais' : 'municipais'}</h4>
      ${(f.orgaos || []).length ? `<ul class="tf-bar">${f.orgaos.map(o => `<li><span class="tf-n">${esc(o.orgao)}</span><span class="num">${rs(o.valor)}</span><i style="width:${Math.max(2, (o.valor || 0) / maxO * 100).toFixed(1)}%"></i></li>`).join('')}</ul>` : '<div class="dim">Nenhum órgão nesta seleção.</div>'}
      <h4>Fornecedores</h4>
      ${(f.fornecedores || []).length ? `<ul class="tf-forn">${f.fornecedores.map(x => `<li><button type="button" class="tf-lk" data-tf-cnpj="${esc(x.cnpj || '')}" data-tf-nome="${esc(x.nome || '')}">${esc(x.nome || x.cnpj || '—')}</button><span class="num">${rs(x.valor)}</span></li>`).join('')}</ul>` : '<div class="dim">Nenhum fornecedor nesta seleção.</div>'}
      <h4>Contratos <span class="tf-cnt num">${fmtN((f.contratos || []).length)}${f.n_contratos_total > (f.contratos || []).length ? ' de ' + fmtN(f.n_contratos_total) : ''}</span></h4>
      ${(f.contratos || []).length ? `<ul class="tf-ctr">${f.contratos.map(c => `<li${c.fornecedor_cnpj ? ` data-tf-cnpj="${esc(c.fornecedor_cnpj)}" data-tf-nome="${esc(c.fornecedor_nome || '')}" tabindex="0" role="button"` : ''}>
          <div class="tf-obj">${esc(c.objeto || '(sem objeto na fonte)')}</div>
          <div class="tf-meta">${esc(c.orgao || '—')} · ${esc(c.fornecedor_nome || c.fornecedor_cnpj || '—')}</div>
          <div class="tf-lin"><span class="num tf-val">${rs(c.valor)}</span><span class="num">${dma(c.vig_ini)} – ${dma(c.vig_fim)}</span></div>
          <div class="tf-lin"><span class="tf-st s-${esc(c.status || '')}">${esc(STATUS[c.status] || c.status || '—')}</span><span>pago: <b class="num">${pct(c.pct_pago)}</b></span>${selo(c)}${c.multi ? '<span class="tf-selo">multimunicipal</span>' : ''}</div></li>`).join('')}</ul>`
        : '<div class="dim">Nenhum contrato atribuído nesta seleção.</div>'}
      <h4>Alertas e achados</h4>
      ${(f.alertas || []).length ? `<ul class="tf-al">${f.alertas.map(a => `<li>${esc(a.texto || '')}</li>`).join('')}</ul>` : `<div class="dim">${f.alertas === null ? 'INDISPONÍVEL — os alertas ainda não têm vínculo territorial.' : 'Nenhum alerta ligado a este território.'}</div>`}
      <p class="tf-fonte">Fonte: ${esc(f.fonte || '—')} · atualizado em <span class="num">${dmhm(f.atualizado_em)}</span></p>`;
  }

  /* ── escopo: zoom animado (900 ms) até a cidade do Rio e troca para as APs ── */
  async function trocarEscopo(e) {
    if (e === S.escopo) return;
    fecharFicha(); sumirDica(); S.escopo = e;
    host.querySelectorAll('[data-tm-escopo]').forEach(b => b.classList.toggle('on', b.dataset.tmEscopo === e));
    if (e === 'pcrj') { try { await carregarRio(); } catch (_) {} }
    const cx = geo.est && geo.est.caixaRio;
    if (e === 'pcrj' && cx) {
      const [[x0, y0], [x1, y1]] = cx, k = Math.min(W / (x1 - x0), H / (y1 - y0)) * 0.9;
      cam.style.transform = `translate(${(W / 2 - k * (x0 + x1) / 2).toFixed(1)}px,${(H / 2 - k * (y0 + y1) / 2).toFixed(1)}px) scale(${k.toFixed(3)})`;
    } else cam.style.transform = '';
    host.classList.toggle('tm-pcrj', e === 'pcrj');
    pintar(await lerDados());
  }

  /* ── pulsos ao vivo: onda de 1,2 s no centróide do território citado pelo evento ── */
  const pararVivo = aoVivoOuvir((tipo, ev) => {
    if (tipo !== 'evento' || !ev || _redMotion) return;
    const G = S.escopo === 'estado' ? geo.est : geo.rio, k = S.escopo === 'estado' ? ev.cod_ibge : (ev.ap != null ? String(ev.ap) : null);
    const c = G && k && G.centro.get(String(k)); if (!c) return;
    const o = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    o.setAttribute('cx', c[0].toFixed(1)); o.setAttribute('cy', c[1].toFixed(1)); o.setAttribute('r', '4'); o.setAttribute('class', 'tm-onda');
    q('#tm-pulsos').appendChild(o); setTimeout(() => o.remove(), 1300);
  });

  /* ── celular/tablet: a ficha é um bottom sheet e vai morar no <body> ──
     Dentro do miolo ela herdava o contexto de empilhamento do `#view` (ficava ATRÁS da barra de esferas) e
     qualquer ancestral com transform/perspective virava o seu bloco de contenção. No <body> ela é fixa na
     janela de verdade. Como sai de dentro do hospedeiro, os ouvintes delegados são postos nela também; e
     quando o hospedeiro some (troca de aba) ela é removida junto. */
  const portal = matchMedia('(max-width:999px)').matches;
  if (portal) {
    document.querySelectorAll('body > .tm-ficha').forEach(x => x.remove());
    document.body.appendChild(ficha);
    const v = $('view');
    if (v) { const mo = new MutationObserver(() => { if (!host.isConnected) { ficha.remove(); mo.disconnect(); } });
             mo.observe(v, {childList: true}); }
  }
  /* ── eventos (delegados no hospedeiro e, com portal, na ficha) ── */
  const ouvir = (t, fn, o) => { host.addEventListener(t, fn, o); if (portal) ficha.addEventListener(t, fn, o); };
  ouvir('click', async e => {
    const b = e.target.closest('[data-tm-escopo],[data-tm-metrica],[data-tm-periodo],[data-tf-x],[data-tf-cnpj],path.tm-a');
    if (!b) return;
    if (b.dataset.tmEscopo) return trocarEscopo(b.dataset.tmEscopo);
    if (b.dataset.tmMetrica) { S.metrica = b.dataset.tmMetrica;
      host.querySelectorAll('[data-tm-metrica]').forEach(x => x.classList.toggle('on', x === b)); return pintar(await lerDados()); }
    if (b.dataset.tmPeriodo) { S.periodo = b.dataset.tmPeriodo;
      host.querySelectorAll('[data-tm-periodo]').forEach(x => x.classList.toggle('on', x === b));
      pintar(await lerDados()); if (S.sel) abrirFicha(S.sel); return; }
    if ('tfX' in b.dataset) return fecharFicha();
    if (b.dataset.tfCnpj) return abrirDossie(b.dataset.tfCnpj, b.dataset.tfNome || '');
    if (b.matches('path.tm-a')) abrirFicha(b.dataset.k);
  });
  ouvir('keydown', e => { const li = e.target.closest && e.target.closest('li[data-tf-cnpj]');
    if (li && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); abrirDossie(li.dataset.tfCnpj, li.dataset.tfNome || ''); }
    if (e.key === 'Escape' && S.sel) fecharFicha(); });
  ouvir('change', e => { if (e.target.id === 'tm-ir' && e.target.value) { abrirFicha(e.target.value); e.target.value = ''; } });
  ouvir('pointerover', e => { const p = e.target.closest && e.target.closest('path.tm-a'); if (p) mostrarDica(p, e); });
  ouvir('pointermove', e => { const p = e.target.closest && e.target.closest('path.tm-a'); if (p && e.pointerType === 'mouse') mostrarDica(p, e); });
  ouvir('pointerout', e => { if (e.target.closest && e.target.closest('path.tm-a')) sumirDica(); });
  /* bottom sheet arrastável (celular): puxar a alça para baixo fecha */
  let arr = null;
  ouvir('pointerdown', e => { if (!e.target.closest('[data-tf-alca]')) return; arr = {y: e.clientY}; ficha.setPointerCapture(e.pointerId); ficha.classList.add('arrastando'); });
  ouvir('pointermove', e => { if (!arr) return; ficha.style.transform = `translateY(${Math.max(0, e.clientY - arr.y)}px)`; });
  const solta = e => { if (!arr) return; const dy = e.clientY - arr.y; arr = null; ficha.classList.remove('arrastando');
    if (dy > 90) fecharFicha(); else ficha.style.transform = ''; };
  ouvir('pointerup', solta); ouvir('pointercancel', solta);

  /* ── partida ── */
  (async () => {
    try { await carregarEstado(); } catch (_) { q('#tm-aviso').hidden = false; q('#tm-aviso').innerHTML = '<b>mapa: INDISPONÍVEL</b> — a malha municipal não carregou.'; return; }
    pintar(await lerDados());
  })();

  _vivo = {sair() { pararVivo(); if (portal) ficha.remove(); if (_vivo && _vivo.host === host) _vivo = null; }, host};
}
