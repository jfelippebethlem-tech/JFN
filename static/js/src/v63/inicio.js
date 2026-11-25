/* v63 · INÍCIO NO ESTILO RELAY — herói + faixa de fontes + quatro seções, ANTES do cockpit da v61.
 *
 *   herói      "Cada contrato, rastreado." + card de vidro com o GRAFO DO FLUXO (Ingestão SEI → SIAFE →
 *              Detectores → Verificador → Dossiê): arestas que se desenham, pulsos de luz percorrendo-as,
 *              selo `running` quando há motor rodando
 *   fontes     as fontes que o JFN lê, acendendo em sequência com contador + o frescor MEDIDO agora
 *   seção 1    "Gasto público é dado." — o registro da rodada (motores, item a item, ✓ / ● / !)
 *   seção 2    "Todo real conta." — números que contam (count-up) e barras que enchem
 *   seção 3    "Quem soma mais sinais." — barras isométricas do radar de risco, a maior em azul cheio
 *   seção 4    "Alerta que chama você." — o cartão de aprovação do Relay virou cartão de alerta (só PJ: LGPD)
 *
 * HONESTIDADE (REGRAS ABSOLUTAS #2 e #6): todo número sai de rota já inventariada
 * (`config/qualidade_inventario.yaml`, manchetes `v63-*`), traz a fonte e o ESTADO ao lado, e falha
 * vira "indisponível" com o motivo — nunca zero. Valor em R$ que é PAGO só vem de OB do SIAFE.
 * Score do radar = indício interno, dito na própria seção.
 */
import {J, erroHumano} from '../nucleo/http.js';
import {esc, corta} from '../nucleo/dom.js';
import {fmtN, fmtR} from '../nucleo/formato.js';
import {_redMotion, _sobrio} from '../capacidade/estado.js';
import {fundoSeguirSecoes} from './fundo.js';
import {revelarEm, contarEm} from './revelar.js';
import {mancheteEstado, mancheteLiberada, mancheteMotivo, mancheteAvisoHtml} from '../ui/manchete.js';   // O7.3

const FONTES = [
  {s: 'SEI', n: 'SEI-RJ', ir: 'p_integras'}, {s: 'SF', n: 'SIAFE-Rio', ir: 'e_siafe'},
  {s: 'TCE', n: 'TCE-RJ', ir: 'g_fontes'}, {s: 'QD', n: 'Querido Diário', ir: 'g_fontes'},
  {s: 'TSE', n: 'TSE', ir: 'g_fontes'}, {s: 'API', n: 'BrasilAPI', ir: 'g_fontes'},
  {s: 'OS', n: 'OpenSanctions', ir: 'e_sanc'},
];

/* ── o grafo do fluxo ─────────────────────────────────────────────────────────────────────────── */
/* Dois desenhos do MESMO grafo: deitado (≥ 601px) e em pé (celular). Escalar o deitado para 330px
   deixava o texto do nó com ~6px; em pé, o SVG roda quase 1:1 e o texto fica com 12–13px. */
const NOS_T = [
  {id: 'sei', t: 'Ingestão SEI', ir: 'p_integras'}, {id: 'siafe', t: 'SIAFE · OB', ir: 'e_siafe'},
  {id: 'det', t: 'Detectores', ir: 'g_dets'}, {id: 'ver', t: 'Verificador', ir: 'g_conform'},
  {id: 'dos', t: 'Dossiê', ir: 'g_buscar'},
];
const LAYOUT = {
  deitado: {vb: '0 0 560 300', pos: {sei: [16, 30], siafe: [16, 232], det: [204, 131], ver: [392, 30], dos: [392, 232]},
    arestas: ['M168 60 C190 60 182 161 204 161', 'M168 262 C190 262 182 161 204 161', 'M356 161 C378 161 370 60 392 60',
              'M468 90 C468 140 468 182 468 232', 'M356 161 C378 161 370 262 392 262']},
  empe: {vb: '0 0 340 372', pos: {sei: [8, 10], siafe: [180, 10], det: [94, 152], ver: [8, 300], dos: [180, 300]},
    arestas: ['M84 70 C84 112 170 110 170 152', 'M256 70 C256 112 170 110 170 152', 'M170 212 C170 256 84 256 84 300',
              'M160 330 C167 330 173 330 180 330', 'M170 212 C170 256 256 256 256 300']},
};

function _grafo() {
  const L = LAYOUT[matchMedia('(max-width:600px)').matches ? 'empe' : 'deitado'];
  const ARESTAS = L.arestas.map((d, i) => ({id: 'a' + (i + 1), d, ramo: i === 4}));
  const pulsos = _redMotion ? '' : ARESTAS.map((a, i) =>
    `<circle r="3.4" class="v63-pulso"><animateMotion dur="${2.2 + i * .25}s" begin="${.9 + i * .35}s" repeatCount="indefinite" calcMode="spline" keyTimes="0;1" keySplines=".45 0 .25 1"><mpath href="#v63-${a.id}"/></animateMotion></circle>`).join('');
  return `<svg class="v63-grafo" viewBox="${L.vb}" role="img" aria-label="Fluxo do JFN: ingestão SEI e SIAFE alimentam os detectores; o verificador confere; o dossiê sai por CNPJ">
    <defs><linearGradient id="v63-gA" x1="0" x2="1"><stop offset="0" stop-color="#6FA8FF"/><stop offset="1" stop-color="#1D5BFF"/></linearGradient></defs>
    ${ARESTAS.map((a, i) => `<path id="v63-${a.id}" class="v63-aresta${a.ramo ? ' ramo' : ''}" d="${a.d}" pathLength="1" style="--i:${i}"/>`).join('')}
    ${pulsos}
    ${NOS_T.map((n, i) => `<g class="v63-no" data-no="${n.id}" data-v63-ir="${n.ir}" data-v63-gesto="zoom" role="link" tabindex="0" aria-label="${esc(n.t)}" style="--i:${i}" transform="translate(${L.pos[n.id][0]} ${L.pos[n.id][1]})">
      <rect width="152" height="60" rx="14"/><circle class="v63-no-pt" cx="18" cy="21" r="4"/>
      <text class="v63-no-t" x="30" y="25">${esc(n.t)}</text>
      <text class="v63-no-s" x="16" y="45" id="v63-no-${n.id}">lendo…</text></g>`).join('')}
  </svg>`;
}

/* O herói nasce JÁ revelado (`v63-in` no HTML): a animação de entrada começa na inserção, sem esperar o
   IntersectionObserver — com a thread ocupada no boot ele atrasava segundos e o título (o LCP da página)
   ficava invisível esse tempo todo (Lighthouse na VM: LCP 27,7 s → ver relatório). */
export function v63InicioHtml() {
  return `<div class="v63-inicio" id="v63-inicio">
  <section class="v63-hero" data-v63-quadro="1">
    <div class="v63-poeira" aria-hidden="true">${_redMotion ? '' : Array.from({length: 14}, (_, i) => `<i style="--i:${i}"></i>`).join('')}</div>
    <div class="v63-hero-tx">
      <span class="v63-eti v63-mono v63-rv v63-in" style="--i:0"><i></i>controle externo · rio de janeiro · ${FONTES.length} fontes</span>
      <h2 class="v63-h1 v63-rv v63-in" style="--i:1">Cada contrato,<br><em class="v63-it">rastreado.</em></h2>
      <p class="v63-lead v63-rv v63-in" style="--i:2">O JFN lê o SEI, o SIAFE, o PNCP e as listas de sanção, cruza tudo sozinho e só chama você quando um indício pede olhar humano.</p>
      <div class="v63-cta v63-rv v63-in" style="--i:3">
        <a class="v63-btn sol" role="button" tabindex="0" data-v63-ir="e_alertas">Ver alertas</a>
        <a class="v63-btn fan" role="button" tabindex="0" data-v63-ir="s_motores" data-v63-gesto="cortina"><span class="play" aria-hidden="true">▶</span>ver ao vivo</a>
      </div>
      <p class="v63-nota v63-mono v63-rv v63-in" style="--i:4">dado real · relido a cada 30 s · indício ≠ acusação</p>
    </div>
    <div class="v63-fluxo v63-vidro v63-rv v63-in v63-tilt" style="--i:2">
      <div class="v63-fluxo-top v63-mono"><span>pipeline · 5 etapas / 1 ramo</span><b class="v63-selo" id="v63-selo">lendo</b></div>
      ${_grafo()}
      <div class="v63-fluxo-pe v63-mono" id="v63-fluxo-pe">—</div>
    </div>
  </section>

  <section class="v63-integra v63-rv" aria-label="Fontes que o JFN lê">
    <p class="v63-mono v63-integra-t">conectado a <b class="v63-conta" data-alvo="${FONTES.length}">0</b> fontes públicas — e ao que cada uma publica</p>
    <div class="v63-integra-l">${FONTES.map((f, i) => `<a class="v63-fonte" data-v63-ir="${f.ir}" role="link" tabindex="0" style="--i:${i}"><span class="v63-fonte-ic">${f.s}</span><span class="v63-fonte-n">${esc(f.n)}</span></a>`).join('')}</div>
    <p class="v63-mono v63-integra-fr" id="v63-frescor" data-manchete="v63-frescor">frescor medido: lendo…</p>
  </section>

  <section class="v63-sec v63-sec-run" data-v63-quadro="2">
    <div class="v63-sec-tx">
      <span class="v63-mono v63-eti v63-rv"><i></i>01 · rodada contínua</span>
      <h3 class="v63-h2 v63-rv" style="--i:1">Gasto público é <em class="v63-it">dado.</em></h3>
      <p class="v63-rv" style="--i:2">Cada motor faz uma parte: o SEI de madrugada, o SIAFE todo dia, as perícias quando há o que periciar. O registro abaixo é o desta hora — o mesmo da aba Sistema › Motores.</p>
    </div>
    <div class="v63-run v63-vidro v63-rv v63-tilt" style="--i:2" data-manchete="v63-run">
      <div class="v63-run-top v63-mono"><span id="v63-run-id">run · lendo</span><span id="v63-run-ev">—</span></div>
      <ol class="v63-run-l" id="v63-run-l"></ol>
      <div class="v63-run-pe v63-mono" id="v63-run-pe"></div>
    </div>
  </section>

  <section class="v63-sec v63-sec-num" data-v63-quadro="3">
    <div class="v63-sec-tx">
      <span class="v63-mono v63-eti v63-rv"><i></i>02 · o que já está na base</span>
      <h3 class="v63-h2 v63-rv" style="--i:1">Todo real <em class="v63-it">conta.</em></h3>
      <p class="v63-rv" style="--i:2">Pagamento só é pagamento quando há Ordem Bancária. Alerta é indício a conferir. Cada número diz de onde veio e em que estado está.</p>
    </div>
    <div class="mch-slot" id="mch-slot">${mancheteAvisoHtml()}</div>
    <div class="v63-nums" id="v63-nums">
      ${_tile('ob', 0, 'data-manchete="v63-ob"')}${_tile('alertas', 1, 'data-manchete="v63-alertas"')}
      ${_tile('acervo', 2, 'data-manchete="v63-acervo"')}${_tile('econ', 3, 'data-manchete="v63-econ"')}
    </div>
  </section>

  <section class="v63-sec v63-sec-iso" data-v63-quadro="4">
    <div class="v63-sec-tx">
      <span class="v63-mono v63-eti v63-rv"><i></i>03 · radar composto</span>
      <h3 class="v63-h2 v63-rv" style="--i:1">Radar <em class="v63-it">em recalibração.</em></h3>
      <p class="v63-rv" style="--i:2" id="v63-iso-tx">Conferido na fonte primária em 19/11/2026: em 24 de 26 fornecedores o score estava inflado — a mesma prova contada duas vezes. O ranking volta à capa depois de corrigido e medido de novo; a aba Radar segue aberta como fila interna.</p>
    </div>
  </section>

  <section class="v63-sec v63-sec-alerta" data-v63-quadro="5">
    <div class="v63-sec-tx">
      <span class="v63-mono v63-eti v63-rv"><i></i>04 · onde você entra</span>
      <h3 class="v63-h2 v63-rv" style="--i:1">Alerta que <em class="v63-it">chama você.</em></h3>
      <p class="v63-rv" style="--i:2">O JFN não decide sozinho: ele aponta, mostra a prova e espera. O cartão do último alerta saiu da capa em 19/11/2026 (o exibido era um fracionamento de inexigibilidade — a regra não se aplica). Alerta só volta à capa quando o detector que o produz estiver calibrado (Tier 1); a fila completa segue na aba Alertas.</p>
    </div>
  </section>

  <div class="v63-ponte v63-mono v63-rv"><span>território · reator · grandes preocupações</span></div>
</div>`;
}

/* o atributo `data-manchete` vai LITERAL na chamada: é o que o inventário de qualidade lê (regra 9) */
function _tile(k, i, manchete) {
  return `<div class="v63-num v63-vidro v63-rv v63-tilt" style="--i:${i}" id="v63-n-${k}" ${manchete}><span class="v63-mono v63-num-l">—</span><b class="v63-num-v">—</b><span class="v63-num-s"></span><div class="v63-num-b"></div><span class="v63-mono v63-num-f"></span></div>`;
}

/* ── montagem: busca tudo em paralelo; cada bloco se pinta quando a SUA rota responde ──────────── */
export function v63InicioMontar() {
  const raiz = document.getElementById('v63-inicio'); if (!raiz || raiz.dataset.montado) return;
  raiz.dataset.montado = '1';
  revelarEm(raiz);
  fundoSeguirSecoes(raiz);
  _pausarGrafoForaDaTela(raiz);
  const [pEst, pPai, pMch] = [J('/api/ao-vivo/estado'), J('/api/compliance/painel'), mancheteEstado()];
  pEst.then(d => { _selo(d); _run(d); });
  /* O7.3: o que é número de detector espera o estado de calibração (falha fechada) */
  pMch.then(() => { const sl = document.getElementById('mch-slot'); if (sl) sl.innerHTML = mancheteAvisoHtml(); });
  Promise.all([pEst, pPai, pMch]).then(([e, p]) => _nos(e, p));
  pPai.then(d => { _numOB(d); _numAcervo(d); });
  Promise.all([pPai, pMch]).then(([d]) => _numAlertas(d));
  Promise.all([J('/api/comparador/economia'), pMch]).then(([d]) => _numEcon(d));
  J('/api/fontes/frescor').then(_frescor);
}

const _ok = d => d && !d.erro;
/* `erroHumano` (da casa) devolve HTML — motivo + botão "tentar de novo" —, então vai por innerHTML, sem esc */
function _indisp(d) { return 'indisponível — ' + erroHumano(d && d.erro); }

function _selo(d) {
  const s = document.getElementById('v63-selo'); if (!s) return;
  if (!_ok(d) || !Array.isArray(d.motores)) { s.textContent = 'indisponível'; s.className = 'v63-selo off'; return; }
  const n = d.motores.filter(m => m.estado === 'rodando' && m.classe !== 'infra').length;
  s.textContent = n ? 'running' : 'em espera'; s.className = 'v63-selo' + (n ? ' on' : '');
  const pe = document.getElementById('v63-fluxo-pe');
  if (pe) pe.textContent = `${fmtN(n)} ${n === 1 ? 'motor rodando' : 'motores rodando'} · ${String(d.eventos_min ?? '—').replace('.', ',')} eventos/min · ${_hora(d.atualizado_em)}`;
}

function _nos(e, p) {
  const set = (id, t) => { const el = document.getElementById('v63-no-' + id); if (el) el.textContent = corta(t, 22); };
  const mot = id => _ok(e) && Array.isArray(e.motores) ? e.motores.find(m => m.id === id) : null;
  const est = m => !m ? 'indisponível' : m.estado === 'rodando' ? 'rodando agora' : m.estado === 'agendado' && m.proxima ? `agendado · ${_hora(m.proxima)}` : m.estado;
  set('sei', est(mot('sei-noturno')));
  if (_ok(p) && p.obs && p.obs.ultimo_dia) set('siafe', `${_dataCurta(p.obs.ultimo_dia)} · ${fmtN(p.obs.n_ultimo_dia)} OB`); else set('siafe', 'indisponível');
  if (!mancheteLiberada('v63-alertas')) set('det', 'fila de triagem');   // O7.3: contagem de detector não é manchete
  else if (_ok(p) && p.alertas && p.alertas.total != null) set('det', `${fmtN(p.alertas.total)} alertas abertos`); else set('det', 'indisponível');
  set('ver', 'regras · ' + est(mot('qualidade')));
  set('dos', 'md · pdf · xlsx');
  const ativo = {sei: mot('sei-noturno'), siafe: mot('siafe-ob'), det: mot('ronda'), ver: mot('qualidade'), dos: null};
  for (const [k, m] of Object.entries(ativo)) {
    const g = document.querySelector(`.v63-no[data-no="${k}"]`);
    if (g) g.classList.toggle('vivo', !!(m && m.estado === 'rodando'));
  }
}

function _run(d) {
  const l = document.getElementById('v63-run-l'); if (!l) return;
  if (!_ok(d) || !Array.isArray(d.motores)) { l.innerHTML = `<li class="v63-run-x">${_indisp(d)}</li>`; return; }
  document.getElementById('v63-run-id').textContent = `run · ${_hora(d.atualizado_em)}`;
  document.getElementById('v63-run-ev').textContent = `${String(d.eventos_min ?? '—').replace('.', ',')} ev/min`;
  const ord = {rodando: 0, falhou: 1, indisponivel: 2, ocioso: 3, agendado: 4};
  const ms = d.motores.filter(m => m.classe !== 'infra')
    .sort((a, b) => (ord[a.estado] ?? 5) - (ord[b.estado] ?? 5) || _t(b.ultimo_evento) - _t(a.ultimo_evento)).slice(0, 7);
  const maxAt = Math.max(1, ...ms.map(m => (m.atividade || []).reduce((s, x) => s + x, 0)));
  l.innerHTML = ms.map((m, i) => {
    const at = (m.atividade || []).reduce((s, x) => s + x, 0);
    const ic = m.estado === 'rodando' ? '●' : m.estado === 'falhou' || m.estado === 'indisponivel' ? '!' : m.estado === 'agendado' ? '○' : '✓';
    const qd = m.ultimo_evento ? _rel(m.ultimo_evento.t) : m.proxima ? 'às ' + _hora(m.proxima) : '';
    const tit = m.ultimo_evento ? m.ultimo_evento.texto : (m.descricao || '');
    return `<li class="v63-run-i e-${esc(m.estado)}" style="--i:${i}" title="${esc(tit)}">
      <span class="v63-run-ic" aria-hidden="true">${ic}</span><span class="v63-run-n">${esc(m.nome)}</span>
      <span class="v63-run-b"><i style="--w:${m.estado === 'rodando' ? 1 : Math.max(.04, at / maxAt).toFixed(3)}"></i></span>
      <span class="v63-run-q v63-mono">${esc(m.estado === 'indisponivel' ? 'indisponível' : m.estado)}${qd ? ' · ' + esc(qd) : ''}</span></li>`;
  }).join('');
  const r = d.resumo || {};
  document.getElementById('v63-run-pe').textContent =
    `${fmtN(r.rodando)} rodando · ${fmtN(r.agendado)} agendados · ${fmtN(r.ocioso)} ociosos · ${fmtN(r.falhou)} com falha — fonte: /api/ao-vivo/estado (systemd)`;
  revelarEm(l);
}

/* ── números ─────────────────────────────────────────────────────────────────────────────────── */
function _num(k, {l, v, fmt, s, f, estado, barras, alvo}) {
  const c = document.getElementById('v63-n-' + k); if (!c) return;
  c.querySelector('.v63-num-l').textContent = l;
  const ve = c.querySelector('.v63-num-v');
  if (v == null) { ve.textContent = '—'; c.classList.add('indisp'); }
  else { ve.dataset.alvo = String(v); ve.dataset.fmt = fmt; ve.textContent = fmt === 'R$' ? fmtR(0) : '0'; contarEm(c); }
  c.querySelector('.v63-num-s').innerHTML = s || '';
  c.querySelector('.v63-num-b').innerHTML = (barras || []).map(b =>
    `<div class="v63-barra"><span>${esc(b.l)}</span><i><b style="--w:${b.w.toFixed(4)}"${b.c ? ` class="${b.c}"` : ''}></b></i><em class="v63-mono">${esc(b.v)}</em></div>`).join('');
  c.querySelector('.v63-num-f').innerHTML = `<i class="v63-estado ${estado.toLowerCase().replace(/\s+/g, '-')}">${estado}</i> ${f}`;   // f: rótulo fixo daqui ou o HTML do erroHumano
}

function _numOB(d) {
  if (!_ok(d) || !d.obs || !d.obs.ultimo_dia) return _num('ob', {l: 'pago em OB · último dia no SIAFE', v: null, f: _indisp(d), estado: 'INDISPONÍVEL'});
  _num('ob', {l: `pago em OB · ${_dataCurta(d.obs.ultimo_dia)}`, v: d.obs.valor_ultimo_dia, fmt: 'R$',
    s: `<b>${fmtN(d.obs.n_ultimo_dia)}</b> ordens bancárias contabilizadas no último dia com OB no SIAFE`,
    f: 'SIAFE · ob_orcamentaria_siafe', estado: 'VERIFICADO'});
}
/* O7.3: número de detector bloqueado — sem o valor, com o porquê; o dado segue na aba */
function _bloq(k, l, onde) {
  _num(k, {l, v: null, s: `<b>não é manchete</b> — ${esc(mancheteMotivo('v63-' + k))}`, f: esc(onde), estado: 'NÃO CALIBRADO'});
  const c = document.getElementById('v63-n-' + k); if (c) c.classList.add('mch-off');
}
function _numAlertas(d) {
  if (!mancheteLiberada('v63-alertas')) return _bloq('alertas', 'alertas abertos', 'a fila segue na aba Alertas');
  const a = _ok(d) && d.alertas;
  if (!a || a.total == null) return _num('alertas', {l: 'alertas abertos', v: null, f: _indisp(d), estado: 'INDISPONÍVEL'});
  const t = Math.max(1, a.total), baixa = a.baixa != null ? a.baixa : Math.max(0, a.total - (a.alta || 0) - (a.media || 0));
  _num('alertas', {l: 'alertas abertos', v: a.total, fmt: 'n', s: 'fila de triagem (motor de regras e perícias), descartados fora',
    barras: [{l: 'alta', w: (a.alta || 0) / t, v: fmtN(a.alta || 0), c: 'alta'}, {l: 'média', w: (a.media || 0) / t, v: fmtN(a.media || 0)},
             {l: 'baixa', w: baixa / t, v: fmtN(baixa), c: 'baixa'}],
    f: 'motor de regras · alertas', estado: 'PENDENTE'});
}
function _numAcervo(d) {
  if (!_ok(d) || !d.obs || d.obs.total == null) return _num('acervo', {l: 'ordens bancárias no acervo', v: null, f: _indisp(d), estado: 'INDISPONÍVEL'});
  /* 21/11/2026: `obs.total` é OB PAGA no SIAFE desde 18/11 (`_siafe_pago_total`), mas o rótulo seguia dizendo "espelho
     TFE · ordens_bancarias" — o número certo com a fonte errada. O espelho TFE (parcial) vai como contexto, rotulado. */
  _num('acervo', {l: 'ordens bancárias pagas no acervo', v: d.obs.total, fmt: 'n',
    s: `OB pagas no SIAFE de 2021 em diante (Contabilizadas, sem devolvidas pelo banco)`
      + (d.obs.valor_total != null ? ` — <b>${fmtR(d.obs.valor_total)}</b>` : '')
      + (d.obs.tfe_total != null ? ` · espelho TFE (parcial, até ${_dataCurta(d.obs.tfe_ultimo_dia)}): ${fmtN(d.obs.tfe_total)} OB` : ''),
    f: 'SIAFE · ob_orcamentaria_siafe', estado: 'VERIFICADO'});
}
function _numEcon(d) {
  if (!mancheteLiberada('v63-econ')) return _bloq('econ', 'economia potencial', 'as compras seguem em Comparador › Economia possível');
  if (!_ok(d) || d.economia_total == null) return _num('econ', {l: 'economia potencial', v: null, f: _indisp(d), estado: 'INDISPONÍVEL'});
  /* 21/11/2026: o total era 100% da Prefeitura do Rio sem dizer a esfera (esferas estanques); agora diz de onde vem. */
  const pe = d.por_esfera || {}, esf = k => pe[k] && pe[k].n ? `${fmtR(pe[k].economia)} em ${fmtN(pe[k].n)}` : 'nenhuma conferida';
  _num('econ', {l: 'economia potencial', v: d.economia_total, fmt: 'R$',
    s: `<b>${fmtN(d.n_compras_acima_mediana)}</b> compras ≥ 2× a mediana do mesmo item, conferidas no PNCP — Estado: ${esf('estado')} · Prefeitura do Rio: ${esf('prefeitura')} — estimativa, não OB paga`, f: 'PNCP · comparador de preços', estado: 'PENDENTE'});
}

/* _iso (barras do radar) e _slack (cartão do último alerta) saíram em 19/11/2026 com as duas seções (COR-04);
   estão no histórico do git (commit anterior) para quando voltarem medidas. */

function _frescor(d) {
  const el = document.getElementById('v63-frescor'); if (!el) return;
  if (!_ok(d) || !Array.isArray(d.fontes)) { el.innerHTML = 'frescor medido: ' + _indisp(d); return; }
  const n = k => d.fontes.filter(f => f.estado === k).length;
  el.innerHTML = `frescor medido agora em ${fmtN(d.fontes.length)} coletas: <b class="ok">${fmtN(n('ok'))} em dia</b> · <b class="at">${fmtN(n('atencao'))} em atenção</b> · <b class="cr">${fmtN(n('critico'))} atrasadas</b> <a data-v63-ir="s_motores" role="link" tabindex="0">ver →</a>`;
}

/* ── o grafo só anima na tela (SVG SMIL pausa de verdade com `pauseAnimations`) ─────────────── */
function _pausarGrafoForaDaTela(raiz) {
  const svg = raiz.querySelector('.v63-grafo'); if (!svg || !('IntersectionObserver' in window) || !svg.pauseAnimations) return;
  new IntersectionObserver(es => { for (const e of es) e.isIntersecting && !document.hidden ? svg.unpauseAnimations() : svg.pauseAnimations(); }).observe(svg);
  if (_sobrio) svg.pauseAnimations();
}

/* ── datas ───────────────────────────────────────────────────────────────────────────────────── */
function _t(ev) { return ev && ev.t ? Date.parse(ev.t) || 0 : 0; }
function _hora(iso) { const t = Date.parse(iso); if (!t) return '—'; const d = new Date(t); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); }
function _dataCurta(s) { const m = String(s || '').match(/^(\d{4})-(\d{2})-(\d{2})/); return m ? `${m[3]}/${m[2]}/${m[1]}` : (s || '—'); }
function _rel(iso) {
  const t = Date.parse(iso); if (!t) return '';
  const min = Math.round((Date.now() - t) / 60000);
  if (min < 1) return 'agora'; if (min < 60) return `há ${min} min`;
  const h = Math.round(min / 60); if (h < 48) return `há ${h} h`;
  return `há ${Math.round(h / 24)} dias`;
}
