/* A CONSCIÊNCIA — o que o sistema está pensando e captando AGORA, numa tela só.
 *
 * O holofeed é uma janela de dez linhas num canto: bom para o canto do olho, incapaz de responder
 * "o que está acontecendo com a máquina neste momento". Este deck é o órgão. Desce sobre o painel,
 * é chamado por tecla ou pelo kyber, e sai quando se volta ao trabalho — sempre a um gesto, nunca
 * no caminho.
 *
 * CINCO LEITURAS, todas de rota que já existia. Nenhuma inventada:
 *   ritmo      a marcha corrente do relógio (`ritmo.js`), com os três regimes NOMEADOS na tela.
 *              Nas outras telas o BPM é sentido; aqui ele é mostrado — quem abre o deck entende
 *              em dois segundos por que o painel inteiro está naquele ritmo.
 *   fluxo      cada evento do SSE como um traço vivo: hora, rótulo, delta. É o que entrou no banco
 *              neste segundo.
 *   vitais     load1 e memória do batimento, com escala — instrumento, não número solto.
 *   sweeps     /api/sweeps/status: qual coleta roda, em que órgão, quantos lidos.
 *   frescor    /api/fontes/frescor: quais fontes estão vivas, quais pararam, e há quantos dias.
 *
 * A REGRA QUE GOVERNA ESTE DECK, e é a mesma do resto da casa: ele não inventa nada. Barramento
 * calado = deck em silêncio, DIZENDO que é silêncio. Rota que falhou = "não deu para saber", nunca
 * um zero. É a diferença entre um painel de consciência e um protetor de tela.
 */
import {$, esc, svgIco} from './nucleo/dom.js';
import {fmtN, fmtD} from './nucleo/formato.js';
import {_redMotion, _sobrio} from './capacidade/estado.js';

const MARCHA = {
  vigilia: {t: 'vigília', d: 'sem coleta em curso e menos de um evento por minuto. O painel está acordado e parado.'},
  coleta: {t: 'coleta', d: 'há sweep vivo ou evento chegando. O painel acelerou junto.'},
  enxurrada: {t: 'enxurrada', d: 'muitos eventos no minuto, ou a VM sob carga. Tensão máxima.'},
};

/* ── os estados do frescor, como a ROTA os nomeia ─────────────────────────────────────────────
   `/api/fontes/frescor` já classifica cada fonte em ok/atenção/crítico, com o critério de cada
   uma (a folha do Estado é mensal, o PNCP é semanal — 6 dias significa coisas diferentes nas
   duas). Até aqui a tela jogava essa classificação fora e reclassificava por idade crua, com um
   único corte em 14 dias: o PNCP com 6 dias e estado `atencao` aparecia neutro, igual a uma
   fonte coletada hoje. Quem decide o estado é quem conhece a cadência — a rota. Esta tabela só
   traduz o veredito em glifo, cor e palavra.

   `sem_medicao` é uma quarta linha de propósito, e não um sinônimo de crítico: fonte sem idade
   medida não é uma fonte parada, é uma fonte sobre a qual não se sabe. Pintar de vermelho seria
   afirmar o que não foi apurado — a mesma regra que separa INDISPONÍVEL de zero. */
const ESTADO_FONTE = {
  ok: {c: 'ok', t: 'viva', d: 'dentro da cadência esperada desta fonte.'},
  atencao: {c: 'velho', t: 'atrasada', d: 'passou da cadência esperada, mas ainda não é ausência.'},
  critico: {c: 'crit', t: 'parada', d: 'muito além da cadência — trate como fonte parada até provar o contrário.'},
  sem_medicao: {c: 'mudo', t: 'sem medição', d: 'não há idade apurada. Isto não é zero nem atraso: é desconhecimento.'},
};

let _lerRitmo = () => ({marcha: 'vigilia', eventosPorMinuto: 0, load1: 0, sweep: false});
let _fluxo = [];          // últimos eventos, os mais novos primeiro
let _vitais = null;       // último batimento recebido
let _aberto = false;
let _relogio = 0;

/* ── leitura das duas rotas, com a distinção que o painel inteiro faz ──────────────────────────
   `vazio` é uma resposta boa com zero itens. `falhou` é ausência de resposta. Elas NÃO podem
   produzir o mesmo texto — foi exatamente essa confusão que fez a tela de controle dizer "sem
   flags" quando a consulta tinha estourado. */
async function ler(rota) {
  try {
    const r = await fetch(rota);
    const d = await r.json();
    if (!r.ok || d.ok === false) return {estado: 'falhou', erro: d && d.erro, d: null};
    return {estado: 'ok', d};
  } catch (e) { return {estado: 'falhou', erro: String(e), d: null}; }
}

function indisponivel(oQue, erro) {
  const det = erro ? ` title="${esc(String(erro)).slice(0, 220)}"` : '';
  return `<div class="cs-vazio"${det}>${svgIco('§indisp')}
    <div><b>Não deu para saber.</b><div class="dim">A consulta de ${esc(oQue)} não respondeu.
    INDISPONÍVEL não é zero — isto não está dizendo que não há nada.</div></div></div>`;
}

// ── as cinco leituras ────────────────────────────────────────────────────────────────────────

function pintarRitmo() {
  const e = _lerRitmo(), m = MARCHA[e.marcha] || MARCHA.vigilia;
  const alvo = $('cs-ritmo'); if (!alvo) return;
  alvo.innerHTML = `
    <div class="cs-marchas" role="group" aria-label="regime do painel">
      ${Object.keys(MARCHA).map(k => `<span class="cs-marcha${k === e.marcha ? ' on' : ''}">${MARCHA[k].t}</span>`).join('')}
    </div>
    <div class="cs-batida" aria-hidden="true"><span></span></div>
    <div class="dim" style="margin-top:8px">${esc(m.d)}</div>
    <div class="dim" style="margin-top:4px">${fmtN(e.eventosPorMinuto)} evento(s) no último minuto${e.sweep ? ' · sweep vivo' : ''}</div>`;
}

function pintarFluxo() {
  const alvo = $('cs-fluxo'); if (!alvo) return;
  if (!_fluxo.length) {
    alvo.innerHTML = `<div class="cs-vazio">${svgIco('§sweep')}
      <div><b>Silêncio.</b><div class="dim">Nenhum evento desde que esta tela abriu. O barramento
      está ligado — o que não há é acontecimento. Isso também é informação.</div></div></div>`;
    return;
  }
  alvo.innerHTML = _fluxo.map(ev => `<div class="cs-ev${ev._crit ? ' crit' : ''}">
      <span class="h">${esc(ev.t || '')}</span>
      <span class="r">${esc(ev.rotulo || ev.tipo || '')}</span>
      <span class="d">${ev.delta > 1 ? '×' + fmtN(ev.delta) : '◈'}</span></div>`).join('');
}

function pintarVitais() {
  const alvo = $('cs-vitais'); if (!alvo) return;
  if (!_vitais) {
    alvo.innerHTML = `<div class="cs-vazio">${svgIco('§indisp')}
      <div><b>Ainda sem batimento.</b><div class="dim">O painel recebe carga e memória pelo mesmo
      canal dos eventos. Enquanto o primeiro batimento não chega, não há o que mostrar — e mostrar
      zero aqui seria inventar.</div></div></div>`;
    return;
  }
  const {load1, load5, mem} = _vitais;
  // Teto 5 = o mesmo do arco do kyber: 2 vCPU, load 5 é o crítico.
  const barra = (rot, v, teto, unid) => {
    const f = Math.max(0, Math.min(1, (Number(v) || 0) / teto));
    return `<div class="cs-medidor"><div class="l">${rot}</div>
      <div class="t"><span style="width:${(f * 100).toFixed(1)}%"></span></div>
      <div class="v">${v == null ? '—' : (unid === '%' ? fmtN(v) + '%' : fmtD(v, 2))}</div></div>`;
  };
  alvo.innerHTML = barra('carga 1 min', load1, 5) + barra('carga 5 min', load5, 5)
                 + (mem != null ? barra('memória', mem, 100, '%') : '');
}

async function pintarSweeps() {
  const alvo = $('cs-sweeps'); if (!alvo) return;
  const r = await ler('/api/sweeps/status');
  if (r.estado !== 'ok') { alvo.innerHTML = indisponivel('sweeps', r.erro); return; }
  const linhas = [];
  for (const [nome, s] of Object.entries(r.d)) {
    if (!s || typeof s !== 'object') continue;
    const rodando = !!(s.rodando || s.supervisor);
    linhas.push(`<div class="cs-sweep${rodando ? ' on' : ''}">
      <span class="n">${esc(nome.toUpperCase())}</span>
      <span class="e">${rodando ? 'coletando' : 'parado'}</span>
      <span class="q">${s.feitos != null ? fmtN(s.feitos) + ' lidos' : ''}</span></div>`);
  }
  alvo.innerHTML = linhas.length ? linhas.join('')
    : `<div class="cs-vazio">${svgIco('§sweep')}<div><b>Nenhum sweep declarado.</b>
       <div class="dim">A rota respondeu e não trouxe coleta nenhuma.</div></div></div>`;
}

async function pintarFrescor() {
  const alvo = $('cs-frescor'); if (!alvo) return;
  const r = await ler('/api/fontes/frescor');
  if (r.estado !== 'ok') { alvo.innerHTML = indisponivel('frescor das fontes', r.erro); return; }
  const fontes = r.d.fontes || [];
  if (!fontes.length) { alvo.innerHTML = indisponivel('frescor das fontes', 'lista vazia'); return; }
  /* Ordem por IDADE, não alfabética: a pergunta desta leitura é "o que parou", e o que parou tem
     de estar em cima. Fonte sem idade medida vai para o fim — ela não é "nova", é desconhecida. */
  const ord = [...fontes].sort((a, b) => (b.idade_dias ?? -1) - (a.idade_dias ?? -1));
  alvo.innerHTML = ord.map(f => {
    const d = f.idade_dias;
    /* Se a rota mudar de vocabulário, o fallback NÃO promove a crítico: sem veredito da rota, o
       máximo que a idade crua sustenta é "atrasada". Alarme só com quem sabe a cadência. */
    const est = ESTADO_FONTE[f.estado] || (d == null ? ESTADO_FONTE.sem_medicao
                                                     : (d > 14 ? ESTADO_FONTE.atencao : ESTADO_FONTE.ok));
    const idade = d == null ? 'sem medição' : (d === 0 ? 'hoje' : fmtN(d) + ' d');
    /* O `title` junta as duas coisas que o operador precisa junto: o que o estado SIGNIFICA e a
       nota da própria rota (cadência do timer, qual campo foi medido). Fonte sem detalhe fica só
       com o significado — nunca com um tooltip vazio. */
    const dica = est.d + (f.detalhe ? ' · ' + f.detalhe : '');
    return `<div class="cs-fonte ${est.c}" title="${esc(dica)}">
      <span class="g" aria-hidden="true">${svgIco('§fonte')}</span>
      <span class="n">${esc(f.fonte || '')}</span>
      <span class="e">${est.t}</span>
      <span class="i">${idade}</span></div>`;
  }).join('');
}

// ── ciclo de vida ────────────────────────────────────────────────────────────────────────────

/** Um evento REAL chegou pelo barramento. Guardado mesmo com o deck fechado — quem abre quer ver
 *  o que aconteceu enquanto não estava olhando. Teto de 60: é uma janela, não um histórico. */
export function conscienciaEvento(ev, crit) {
  _fluxo.unshift(Object.assign({_crit: !!crit}, ev));
  if (_fluxo.length > 60) _fluxo.length = 60;
  if (_aberto) { pintarFluxo(); pintarRitmo(); }
}

/** Batimento: carga medida e memória. */
export function conscienciaBatimento(p) {
  _vitais = {load1: p.load1, load5: p.load5, mem: p.mem};
  if (_aberto) { pintarVitais(); pintarRitmo(); }
}

/* ── o fundo do deck ──────────────────────────────────────────────────────────────────────────
   A cena própria da Consciência, gerada no Gemini: filamentos de íon subindo devagar pelas duas
   BORDAS, com o centro do quadro vazio de propósito — é lá que mora a grade de leitura, e uma
   arte com sujeito central disputaria com o dado. As faíscas âmbar são a segunda temperatura da
   casa.

   TRÊS COISAS QUE ESTE VÍDEO FAZ DIFERENTE DA MESA, e as três vêm de ele ser sobreposição de
   viewport inteira e não peça dentro de um cartão:
     1. SEM degradê de borda. A mesa dissolvia no cartão; este sangra até a beirada da tela.
     2. Só toca com o deck ABERTO. Vídeo rodando atrás de um deck fechado é custo puro numa VM de
        2 vCPU — a mesma conta que já faz o `setInterval` só existir enquanto está aberto.
     3. O HEAD só acontece na PRIMEIRA abertura. Quem nunca abre a Consciência nunca baixa os
        725 KB.
   Os dois pisos desligam, como em toda peça viva daqui: sem vídeo, fica o fundo chapado do deck,
   que já era legível sozinho. */
let _fundoOk;                                        // undefined = ainda não perguntei

async function fundoVivo(d) {
  let v = d.querySelector('video.cs-fundo');
  if (_redMotion || _sobrio) { if (v) { v.classList.remove('on'); v.pause(); } return; }
  const url = '/static/assets/consciencia-fundo.mp4';
  if (_fundoOk === undefined) {
    try { _fundoOk = (await fetch(url, {method: 'HEAD'})).ok; } catch (e) { _fundoOk = false; }
  }
  if (!_fundoOk) { if (v) v.classList.remove('on'); return; }
  if (!v) {
    v = document.createElement('video');
    v.className = 'cs-fundo';
    v.muted = true; v.loop = true; v.playsInline = true;
    v.setAttribute('aria-hidden', 'true');
    v.poster = '/static/assets/consciencia-fundo.jpg';
    v.addEventListener('playing', () => v.classList.add('on'));
    v.innerHTML = '<source src="/static/assets/consciencia-fundo.webm" type="video/webm">'
                + '<source src="' + url + '" type="video/mp4">';
    d.insertBefore(v, d.firstChild);
    v.load();
  }
  v.play().catch(() => {});
}

/** Reavalia o fundo quando a capacidade da maquina muda. Sem isto, um FPS que cai DEPOIS do deck
 *  aberto deixaria o video tocando — e `display:none` nao pausa video em todo navegador. */
export function conscienciaRever() {
  const d = $('consciencia'); if (d && _aberto) fundoVivo(d);
}

export function conscienciaAbrir() {
  const d = $('consciencia'); if (!d || _aberto) return;
  _aberto = true;
  d.hidden = false;
  requestAnimationFrame(() => d.classList.add('on'));
  fundoVivo(d);
  pintarRitmo(); pintarFluxo(); pintarVitais(); pintarSweeps(); pintarFrescor();
  /* 15 s é o mesmo passo do polling que a mesa já usa para os sweeps — não se inventa uma
     cadência nova para a mesma pergunta. Só roda com o deck ABERTO: um deck fechado que continua
     consultando é custo puro numa VM de 2 vCPU. */
  _relogio = setInterval(() => { pintarSweeps(); pintarFrescor(); pintarRitmo(); }, 15000);
  const f = d.querySelector('.cs-fechar'); if (f) f.focus();
}

export function conscienciaFechar() {
  const d = $('consciencia'); if (!d || !_aberto) return;
  _aberto = false;
  clearInterval(_relogio); _relogio = 0;
  d.classList.remove('on');
  const v = d.querySelector('video.cs-fundo'); if (v) v.pause();
  setTimeout(() => { if (!_aberto) d.hidden = true; }, 260);
}

export function conscienciaToggle() { _aberto ? conscienciaFechar() : conscienciaAbrir(); }

/**
 * Monta o deck e liga a tecla. Chamado UMA vez, da sequência de boot do entrypoint.
 * @param {()=>object} lerRitmo  leitura do relógio (`ritmoEstado`), injetada para este módulo
 *                               não depender do de ritmo — o deck MOSTRA o ritmo, não o define.
 */
export function conscienciaLigar(lerRitmo) {
  if (typeof lerRitmo === 'function') _lerRitmo = lerRitmo;
  if ($('consciencia')) return;
  const d = document.createElement('div');
  d.id = 'consciencia'; d.hidden = true;
  d.setAttribute('role', 'dialog');
  d.setAttribute('aria-modal', 'true');
  d.setAttribute('aria-label', 'Consciência do sistema — o que está sendo captado agora');
  d.innerHTML = `
    <div class="cs-topo">
      <span class="cs-selo" aria-hidden="true">${svgIco('◎')}</span>
      <div><h2>Consciência</h2>
        <div class="dim">O que o sistema está captando agora. Nada aqui é simulado — sem
          barramento, esta tela fica em silêncio e diz que está.</div></div>
      <button type="button" class="btn ghost cs-fechar" aria-label="Fechar a consciência">Fechar ✕</button>
    </div>
    <div class="cs-grade">
      <section class="cs-bloco cs-largo"><h3>Ritmo</h3><div id="cs-ritmo"></div></section>
      <section class="cs-bloco"><h3>Sinais vitais</h3><div id="cs-vitais"></div></section>
      <section class="cs-bloco"><h3>Sweeps em curso</h3><div id="cs-sweeps"></div></section>
      <section class="cs-bloco cs-alto"><h3>Fluxo de captação</h3><div id="cs-fluxo"></div></section>
      <section class="cs-bloco cs-alto"><h3>Frescor das fontes</h3><div id="cs-frescor"></div></section>
    </div>`;
  document.body.appendChild(d);
  d.querySelector('.cs-fechar').addEventListener('click', conscienciaFechar);
  d.addEventListener('click', ev => { if (ev.target === d) conscienciaFechar(); });
  /* `c` abre, Esc fecha. O guarda de campo de texto não é detalhe: sem ele, digitar "cnpj" numa
     busca abriria o deck no meio da palavra. */
  document.addEventListener('keydown', ev => {
    const alvo = ev.target;
    const digitando = alvo && (alvo.tagName === 'INPUT' || alvo.tagName === 'TEXTAREA'
                               || alvo.isContentEditable);
    if (ev.key === 'Escape' && _aberto) { conscienciaFechar(); return; }
    if (digitando || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (ev.key === 'c' || ev.key === 'C') { ev.preventDefault(); conscienciaToggle(); }
  });
}
