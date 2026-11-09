/* MÍDIA DO PAINEL — som de interface e as ilustrações dos estados vazios (2026-11-09).
 *
 * Módulo SEM efeito de topo (contrato de `test_painel_ordem_de_boot`): quem o liga é a sequência
 * de boot em `entrada.js`, com UMA chamada (`ligarMidia()`). Não instala nada no `window` — o
 * botão do cabeçalho é delegado por `data-som`, como `data-vinc`/`data-drill`, e não sobe o
 * `TETO_GLOBAIS` da ponte.
 *
 * SOM — DESLIGADO por padrão, e as três regras que não se negociam:
 *   1. Só toca depois que a pessoa LIGOU (botão "Som" no cabeçalho; fica no localStorage, com
 *      try/catch — aba anônima ou storage bloqueado = continua desligado, sem erro).
 *   2. Cada acontecimento tem a SUA voz (área ≠ alerta ≠ dossiê): o dono não gosta do mesmo som
 *      repetido. E nenhum se repete em rajada — há um intervalo mínimo por voz.
 *   3. `prefers-reduced-motion` é lido como pedido de QUIETUDE: o som de troca de área (o mais
 *      frequente) cala, e os outros dois tocam na metade do volume. Arquivo ausente ou bloqueio de
 *      autoplay = silêncio, nunca erro na tela.
 *
 * ILUSTRAÇÕES — arte GERADA (não composta por código), aplicada SÓ pelo CSS (`98-midia.css`) e só
 * depois que a peça carregou de fato: `html.ilus-doc` / `html.ilus-rede`. Peça que não existe =
 * classe que nunca acende = estado vazio de sempre, sem buraco reservado. O pedido é feito depois
 * do boot (não disputa banda com o cockpit) e serve de pré-carga para quando o vazio aparecer.
 *   doc  = MEDI e não achei (resultado vazio de uma base que respondeu)
 *   rede = NÃO DEU PARA SABER (fonte/servidor não respondeu) — INDISPONÍVEL ≠ 0, e as duas
 *          figuras são diferentes justamente para a tela nunca confundir uma com a outra.
 */

const SFX = {
  area:   {src: '/static/assets/sfx/area.mp3',   vol: 0.10, intervalo: 350},
  alerta: {src: '/static/assets/sfx/alerta.mp3', vol: 0.16, intervalo: 8000},
  dossie: {src: '/static/assets/sfx/dossie.mp3', vol: 0.12, intervalo: 600},
};
const CHAVE = 'jfn.som';
const ILUS = {doc: '/static/assets/gen/vazio-doc.webp', rede: '/static/assets/gen/vazio-rede.webp'};

let _ligado = false;
const _audio = {};        // tipo -> HTMLAudioElement (criado só depois de ligar)
const _ultimo = {};       // tipo -> timestamp do último toque
const _quebrado = {};     // tipo -> true se o arquivo falhou: não insiste

function _lerPref() { try { return localStorage.getItem(CHAVE) === '1'; } catch (_) { return false; } }
function _gravarPref(v) { try { localStorage.setItem(CHAVE, v ? '1' : '0'); } catch (_) { /* sem storage: vale só nesta aba */ } }
function _quieto() {
  try { return !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches); }
  catch (_) { return false; }
}

function _pegar(tipo) {
  if (_audio[tipo] || _quebrado[tipo]) return _audio[tipo] || null;
  const s = SFX[tipo]; if (!s || typeof Audio !== 'function') return null;
  const a = new Audio(); a.preload = 'auto';
  a.addEventListener('error', () => { _quebrado[tipo] = true; delete _audio[tipo]; });
  a.src = s.src; _audio[tipo] = a; return a;
}

/** Toca a voz `tipo` ('area' | 'alerta' | 'dossie') se o som estiver ligado. Nunca lança. */
export function somTocar(tipo) {
  if (!_ligado) return;
  const s = SFX[tipo]; if (!s) return;
  const quieto = _quieto();
  if (quieto && tipo === 'area') return;
  const agora = Date.now();
  if (agora - (_ultimo[tipo] || 0) < s.intervalo) return;
  const a = _pegar(tipo); if (!a) return;
  _ultimo[tipo] = agora;
  try {
    a.volume = quieto ? s.vol / 2 : s.vol;
    a.currentTime = 0;
    const p = a.play(); if (p && p.catch) p.catch(() => {});
  } catch (_) { /* autoplay bloqueado/arquivo ruim: silêncio */ }
}

function _pintarBotao() {
  document.querySelectorAll('[data-som]').forEach(b => {
    b.setAttribute('aria-pressed', _ligado ? 'true' : 'false');
    b.classList.toggle('on', _ligado);
    b.title = _ligado ? 'Som de interface LIGADO — clique para silenciar'
                      : 'Som de interface desligado — clique para ligar';
    const t = b.querySelector('.som-t'); if (t) t.textContent = _ligado ? 'Som' : 'Mudo';
  });
}

function _alternar() {
  _ligado = !_ligado; _gravarPref(_ligado); _pintarBotao();
  if (_ligado) { Object.keys(SFX).forEach(_pegar); somTocar('area'); }   // o próprio clique é o gesto que libera o áudio
}

function _sondarIlustracoes() {
  Object.keys(ILUS).forEach(k => {
    const im = new Image();
    im.decoding = 'async';
    im.onload = () => document.documentElement.classList.add('ilus-' + k);
    im.src = ILUS[k];
  });
}

/** Liga o botão de som do cabeçalho (delegado) e sonda as ilustrações dos estados vazios. */
export function ligarMidia() {
  _ligado = _lerPref();
  _pintarBotao();
  document.addEventListener('click', e => {
    const b = e.target && e.target.closest && e.target.closest('[data-som]');
    if (b) { e.preventDefault(); _alternar(); }
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const b = e.target && e.target.closest && e.target.closest('[data-som]');
    if (b) { e.preventDefault(); _alternar(); }
  });
  // depois do portal e do primeiro render: a pré-carga não disputa banda com o cockpit
  setTimeout(_sondarIlustracoes, 4000);
}
