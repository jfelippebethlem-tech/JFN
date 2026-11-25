/* O10.7 · GLOBO ↔ TABELA na aba Orçamento por órgão (plano mestre v2 §18.1; auditoria O10.1 §8.2).
 *
 * O que fica no bundle do painel é só isto (o seletor, a tabela equivalente, a conferência e a imagem parada em SVG).
 * O globo 3D (three + three-globe) mora em `static/js/globo.bundle.js` e só é baixado quando a pessoa liga "Globo" —
 * nunca no boot, nunca em outra aba, nunca sob reduced-motion, modo sóbrio ou celular (lá fica a imagem parada).
 *
 * Os arcos vêm da MESMA rota da tabela (`/api/orcamento_orgao?…&arcos=1`), no MESMO exercício, mês e filtro. A soma
 * (arcos + tracejado INDISPONÍVEL + fora do mapa) é conferida, em centavos, contra o "Pago (OB do SIAFE)" dos órgãos
 * visíveis; se não bater, nada é desenhado e a tela diz por quê. */
import {esc} from '../../nucleo/dom.js';
import {fmtN} from '../../nucleo/formato.js';
import {_redMotion, _sobrio} from '../../capacidade/estado.js';
import {quadroLigar} from '../../ritmo.js';
import {geoCentroid} from 'd3-geo';
import {modelo, reais} from './dados.js';
import {svgParado, centrosRJ} from './parado.js';

const _CSS = `<style>
  .gl-topo{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:10px}.gl-sub{font-size:12px;flex:1;min-width:220px}
  .gl-palco{position:relative;width:100%;aspect-ratio:720/440;max-height:560px;border-radius:14px;overflow:hidden;background:linear-gradient(180deg,var(--bg,#F3F8FE),var(--bg-2,#E8F1FC));border:1px solid var(--line,rgba(30,110,220,.16))}
  .gl-palco .gl-svg{position:absolute;inset:0;width:100%;height:100%;transition:opacity var(--dur-3,480ms) var(--ease,ease)}
  .gl-palco.gl-3d-on .gl-svg{opacity:0;pointer-events:none}.gl-3d{position:absolute;inset:0}.gl-canvas{display:block;width:100%!important;height:100%!important;cursor:grab}
  .gl-mun path{fill:rgba(255,255,255,.75);stroke:rgba(30,110,220,.28);stroke-width:.6}
  .gl-arcos path{fill:none;stroke:rgba(20,112,230,.55);stroke-linecap:round}.gl-discos circle{fill:rgba(20,112,230,.28);stroke:#1470E6;stroke-width:1}
  .gl-svg .gl-t1{stroke:var(--crit,#D93A40)}.gl-discos .gl-t1{fill:rgba(217,58,64,.25)}.gl-arcos .gl-tr{stroke:var(--muted,#51667F);stroke-dasharray:4 4}.gl-arcos .gl-oi{stroke-dasharray:7 3}
  .gl-svg .gl-sel{stroke:var(--cyan,#22B5F5);filter:drop-shadow(0 0 3px rgba(34,181,245,.6))}.gl-svg [data-gl-arco]{cursor:pointer}
  .gl-chip rect{fill:#fff;stroke:var(--line-strong,rgba(30,110,220,.32))}.gl-chip text{font:600 11px var(--mono,ui-monospace,monospace);fill:var(--ink,#0B1B33)}
  .gl-chip-ind rect{stroke-dasharray:3 3}.gl-chip-ind text{fill:var(--muted,#51667F)}
  .gl-conf{font-size:12.5px;margin:0 0 10px;padding:8px 10px;border-radius:10px;background:rgba(14,158,116,.08);color:var(--ink,#0B1B33)}
  .gl-vistas{margin-top:8px}.gl-dica{min-height:1.4em;font-size:12.5px;margin-top:6px}.gl-nota{font-size:12px;margin-top:6px}
  .gl-leg{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px;color:var(--ink-2,#34496A);margin-top:8px}
  .gl-k{display:inline-block;width:18px;height:0;border-top:3px solid #1470E6;vertical-align:middle;margin-right:4px}.gl-k-t1{border-color:var(--crit,#D93A40)}
  .gl-k-tr{border-top:2px dashed var(--muted,#51667F)}.gl-k-oi{border-top:3px dashed #1470E6}.gl-k-d{width:10px;height:10px;border:1px solid #1470E6;border-radius:50%;background:rgba(20,112,230,.28)}
  .gl-tab{max-height:340px;overflow:auto;margin-top:12px}.gl-tab tr.gl-on td{background:rgba(34,181,245,.10)}.gl-ver{text-align:left;white-space:normal;min-height:44px}
  @media (max-width:480px){.gl-palco{aspect-ratio:auto;height:auto}.gl-palco .gl-svg{position:static;height:auto}}
  @media (prefers-reduced-motion:reduce){.gl-palco .gl-svg{transition:none}}
</style>`;
const URL_GLOBO = '/static/js/globo.bundle.js?v=d9ab31c2';
const CHAVE = 'jfn_oo_globo';
const MAX_ARCOS = 300;      // o Estado inteiro cabe sem agregar (236 ligações em 2024); acima disso agrega

let _cfg = null;            // {buscar(): Promise<payload com globo>, visiveis(d): órgãos visíveis}
let _G = null, _GK = '';    // payload com `globo` e a chave (exercício|mês) a que ele pertence
let _topo = null, _centros = null, _cena = null, _io = null, _m = null, _sel = null, _seq = 0;

const _ler = () => { try { return localStorage.getItem(CHAVE) === 'globo' ? 'globo' : 'tabela'; } catch (_) { return 'tabela'; } };
const _gravar = v => { try { localStorage.setItem(CHAVE, v); } catch (_) { /* sem storage: vale só nesta visita */ } };
let _modo = null;           // lido do localStorage na 1ª pintura da aba (nada roda no import do módulo)
const _modoAgora = () => (_modo == null ? (_modo = _ler()) : _modo);

/** Imagem parada em vez do 3D: reduced-motion, modo sóbrio ou tela estreita (390 px do celular). */
export const soParado = () => _redMotion || _sobrio || matchMedia('(max-width: 480px)').matches;

/** HTML da seção (o seletor e o palco vazio). Nada é buscado aqui. */
export function globoSecao() {
  _modoAgora();
  const on = m => (_modo === m ? ' on' : '');
  return _CSS + `<div class="gl-sec" data-gl-raiz>
    <div class="gl-topo"><div class="chips" role="group" aria-label="Ver como">
      <button type="button" class="chip${on('tabela')}" data-gl-modo="tabela" aria-pressed="${_modo === 'tabela'}">Tabela</button>
      <button type="button" class="chip${on('globo')}" data-gl-modo="globo" aria-pressed="${_modo === 'globo'}">Globo</button></div>
      <span class="dim gl-sub">De onde a OB saiu (sede da UG) até onde mora quem recebeu (município do RJ ou UF, pelo cadastro do CNPJ na Receita). Só o que foi pago por OB do SIAFE.</span></div>
    <div data-gl-corpo>${_modo === 'globo' ? '<div class="dim" aria-busy="true">Carregando os arcos…</div>' : '<div class="dim">A tabela órgão a órgão está abaixo. "Globo" mostra o mesmo pago, por destino, e confere a soma com ela.</div>'}</div>
  </div>`;
}

function _sair3d() {
  if (_io) { _io.disconnect(); _io = null; }
  if (_cena) { try { _cena.sair(); } catch (_) { /* contexto já perdido */ } _cena = null; }
}

function _legenda(g, m) {
  const t1 = (g.tier1_detectores || []).length;
  return `<div class="gl-leg" aria-label="Legenda">
    <span><i class="gl-k gl-k-n"></i> pago (cor neutra)</span>
    <span><i class="gl-k gl-k-t1"></i> parte paga a CNPJ com achado Tier 1 — hoje ${fmtN(t1)} detector(es) no Tier 1${t1 ? `, ${fmtN(g.tier1_cnpjs)} CNPJ` : ': nenhum arco realçado'}</span>
    <span><i class="gl-k gl-k-tr"></i> tracejado até INDISPONÍVEL = sede de quem recebeu não comprovada (CNPJ fora do cadastro local)</span>
    <span><i class="gl-k gl-k-oi"></i> traço curto = sede da UG não comprovada: o arco sai do ponto da UF (RJ), não de um município</span>
    <span><i class="gl-k gl-k-d"></i> disco/coluna = pago a quem tem sede no mesmo município da UG</span>
    <span>Espessura ∝ raiz do valor (escala raiz). Sede fora do RJ = ponto da UF, nunca uma cidade.${m.agregado !== 'nenhum' ? ` Acima de ${fmtN(m.max)} ligações, ${m.agregado === 'origem' ? 'as UGs viram uma origem só' : 'as UGs viram uma origem só e os municípios menores do RJ viram "demais municípios"'} — a soma não muda.` : ''}</span></div>`;
}

function _conferencia(m, n) {
  const linha = `Arcos ${reais(m.soma_arcos)} · tracejado (sede INDISPONÍVEL) ${reais(m.soma_tracejado)} · fora do mapa ${reais(m.soma_fora)} = <b>${reais(m.soma)}</b>`;
  return m.confere
    ? `<div class="gl-conf ok" data-gl-confere="1">${linha} — <b>confere</b> com o "Pago (OB do SIAFE)" dos ${fmtN(n)} órgão(s) da tabela neste filtro (${reais(m.total_tabela)}).</div>`
    : `<div class="warn" data-gl-confere="0">${linha}, mas a tabela diz ${reais(m.total_tabela)} para os mesmos órgãos. O globo NÃO é desenhado enquanto os dois não baterem.</div>`;
}

function _tabelaArcos(m) {
  const lin = m.arcos.map(a => `<tr${a.id === _sel ? ' class="gl-on"' : ''}><td><button type="button" class="btn ghost gl-ver" data-gl-arco="${a.id}" aria-pressed="${a.id === _sel}">${esc(a.rotulo.split(': ')[0])}</button>
      <div class="dim" style="font-size:11px">${fmtN(a.n_ugs)} UG${a.origem_comprovada ? '' : ' · sede da UG não comprovada: origem na UF'}${a.t1_centavos ? ` · Tier 1: ${reais(a.t1_centavos)}` : ''}</div></td>
    <td class="right">${reais(a.centavos)}</td></tr>`).join('');
  const fora = m.fora.map(f => `<tr><td>${esc(f.rotulo)}</td><td class="right">${reais(f.centavos)}</td></tr>`).join('');
  return `<div class="gl-tab"><table class="tb oo-txt"><caption class="dim" style="text-align:left">Tabela equivalente ao globo (${fmtN(m.arcos.length)} ligações)</caption>
    <thead><tr><th>Origem → destino</th><th class="right">Pago (OB do SIAFE)</th></tr></thead><tbody>${lin}</tbody>
    ${fora ? `<tbody><tr><th colspan="2">Fora do mapa — sem ponto</th></tr>${fora}</tbody>` : ''}</table></div>`;
}

async function _dadosGeo() {
  if (!_topo) _topo = fetch('/static/assets/geo/rj-municipios.topo.json', {credentials: 'same-origin'}).then(r => { if (!r.ok) throw new Error('malha do RJ'); return r.json(); });
  const t = await _topo;
  if (!_centros) _centros = centrosRJ(t, geoCentroid);
  return t;
}

async function _abrir(raiz) {
  const corpo = raiz.querySelector('[data-gl-corpo]');
  const meu = ++_seq;
  _sair3d();
  corpo.innerHTML = '<div class="dim" aria-busy="true">Carregando os arcos…</div>';
  const k = _cfg.chave();
  if (!_G || _GK !== k) {
    const d = await _cfg.buscar();
    if (meu !== _seq || !raiz.isConnected) return;
    if (!d || d.ok === false || !d.globo) { corpo.innerHTML = `<div class="warn">Arcos INDISPONÍVEIS agora (${esc((d && d.erro) || 'sem resposta')}) — não é zero.</div>`; return; }
    _G = d; _GK = k;
  }
  const g = _G.globo;
  if (!g.ok) { corpo.innerHTML = `<div class="warn">${esc(g.motivo || 'arcos INDISPONÍVEIS')}</div>`; return; }
  if ((g.divergentes || []).length) { corpo.innerHTML = `<div class="warn">A leitura das OB para os arcos divergiu da tabela em ${fmtN(g.divergentes.length)} UG — globo suspenso (não desenha número que não bate).</div>`; return; }
  const codigos = new Set(_cfg.visiveis().map(o => o.orgao));
  const orgaos = (_G.orgaos || []).filter(o => codigos.has(o.orgao));
  if (!orgaos.some(o => o.pago_siafe != null)) {
    corpo.innerHTML = '<div class="warn">Nenhum órgão deste filtro tem "Pago (OB do SIAFE)" neste período (a coleta do exercício não separa OB orçamentária, ou não há OB): arcos INDISPONÍVEIS — não é zero.</div>';
    return;
  }
  const m = modelo(g, orgaos, {max: MAX_ARCOS});
  _m = m;
  let topo;
  try { topo = await _dadosGeo(); } catch (e) { corpo.innerHTML = `<div class="warn">Malha do RJ INDISPONÍVEL (${esc(e.message)}).</div>`; return; }
  if (meu !== _seq || !raiz.isConnected) return;
  const parado = soParado();
  corpo.innerHTML = `${_conferencia(m, orgaos.length)}
    ${m.confere ? `<div class="gl-palco" data-gl-palco>${svgParado(m, topo, _centros, {sel: _sel})}</div>
    ${parado ? `<div class="dim gl-nota">Imagem parada (${_redMotion ? 'movimento reduzido' : _sobrio ? 'modo sóbrio' : 'tela estreita'}). Mesmos arcos e valores do globo.</div>` : '<div class="gl-vistas chips" role="group" aria-label="Aproximar"><button type="button" class="chip" data-gl-vista="globo">Globo</button><button type="button" class="chip" data-gl-vista="brasil">Brasil</button><button type="button" class="chip" data-gl-vista="rj">RJ</button></div>'}
    <div class="gl-dica dim" role="status" aria-live="polite" data-gl-dica>${_sel != null && m.arcos[_sel] ? esc(m.arcos[_sel].rotulo) : 'Passe o mouse num arco ou escolha uma linha da tabela.'}</div>
    ${_legenda(g, m)}` : ''}
    ${_tabelaArcos(m)}`;
  if (!m.confere || parado) return;
  const palco = corpo.querySelector('[data-gl-palco]');
  let mod;
  try { mod = await import(URL_GLOBO); } catch (e) {
    const dica = corpo.querySelector('[data-gl-dica]'); if (dica) dica.textContent = 'Globo 3D INDISPONÍVEL (o módulo não carregou); a imagem parada acima tem os mesmos arcos.';
    return;
  }
  if (meu !== _seq || !palco.isConnected) return;
  const dica = corpo.querySelector('[data-gl-dica]');
  const host = document.createElement('div'); host.className = 'gl-3d';
  palco.prepend(host);
  try {
    _cena = mod.criar(host, m, _centros, {
      laco: fn => quadroLigar((t, dt) => {
        if (!host.isConnected) { _sair3d(); return false; }
        try { return fn(t, dt); } catch (e) {          // o laço do painel engole a exceção: aqui ela aparece e o 3D sai
          console.error('[globo] quadro falhou — volta a imagem parada:', e);
          _sair3d(); host.remove(); palco.classList.remove('gl-3d-on');
          if (dica) dica.textContent = 'Globo 3D INDISPONÍVEL (falha ao desenhar); a imagem parada acima tem os mesmos arcos.';
          return false;
        }
      }),
      aoApontar: a => { if (dica) dica.textContent = a ? a.rotulo : (_sel != null && _m.arcos[_sel] ? _m.arcos[_sel].rotulo : 'Passe o mouse num arco ou escolha uma linha da tabela.'); },
    });
  } catch (e) {                                    // sem WebGL: fica a imagem parada
    host.remove();
    if (dica) dica.textContent = `Globo 3D INDISPONÍVEL neste navegador (${e.message}); a imagem parada acima tem os mesmos arcos.`;
    return;
  }
  palco.classList.add('gl-3d-on');
  _io = new IntersectionObserver(es => { for (const e of es) _cena && _cena.pausar(!e.isIntersecting); });
  _io.observe(palco);
}

function _selecionar(raiz, id) {
  _sel = _sel === id ? null : id;
  if (!_m) return;
  raiz.querySelectorAll('[data-gl-arco]').forEach(el => {
    const on = Number(el.dataset.glArco) === _sel;
    if (el.tagName === 'BUTTON') { el.setAttribute('aria-pressed', String(on)); el.closest('tr').classList.toggle('gl-on', on); }
    else el.classList.toggle('gl-sel', on);
  });
  const dica = raiz.querySelector('[data-gl-dica]');
  if (dica) dica.textContent = _sel != null && _m.arcos[_sel] ? _m.arcos[_sel].rotulo : 'Passe o mouse num arco ou escolha uma linha da tabela.';
  if (_cena) _cena.selecionar(_sel);
}

/** Depois que a aba (re)pintou: se o modo salvo é "globo", abre. */
export function globoDepoisDePintar() {
  const raiz = document.querySelector('[data-gl-raiz]');
  _sair3d(); _sel = null;
  if (raiz && _modoAgora() === 'globo') _abrir(raiz);
}

/** O filtro da tabela mudou: o globo segue o mesmo filtro (sem nova busca). */
export function globoFiltro() {
  const raiz = document.querySelector('[data-gl-raiz]');
  if (raiz && _modo === 'globo' && _G) { _sel = null; _abrir(raiz); }
}

/** Liga a delegação (uma vez). `cfg` = {buscar, visiveis, chave}. */
let _ligado = false;
export function globoLigar(cfg) {
  _cfg = cfg;
  if (_ligado) return; _ligado = true;
  /* O modo sóbrio pode ligar DEPOIS que o globo abriu (a medição de quadros roda segundos após o boot); quem o liga
     reemite `visibilitychange` (capacidade/sobrio.js). Aqui o 3D sai e fica a imagem parada que já está no palco. */
  document.addEventListener('visibilitychange', () => {
    if (!_cena || document.hidden || !soParado()) return;
    const palco = document.querySelector('[data-gl-raiz] [data-gl-palco]');
    _sair3d();
    if (palco) { palco.classList.remove('gl-3d-on'); palco.querySelectorAll('.gl-3d').forEach(x => x.remove()); }
    const dica = document.querySelector('[data-gl-raiz] [data-gl-dica]');
    if (dica) dica.textContent = 'Modo sóbrio ligado: o globo 3D parou e ficou a imagem parada, com os mesmos arcos e valores.';
  });
  document.addEventListener('click', ev => {
    const b = ev.target && ev.target.closest && ev.target.closest('[data-gl-modo],[data-gl-vista],[data-gl-arco]');
    if (!b) return;
    const raiz = b.closest('[data-gl-raiz]'); if (!raiz) return;
    if (b.dataset.glModo) {
      _modo = b.dataset.glModo; _gravar(_modo);
      raiz.querySelectorAll('[data-gl-modo]').forEach(x => { const on = x.dataset.glModo === _modo; x.classList.toggle('on', on); x.setAttribute('aria-pressed', String(on)); });
      if (_modo === 'globo') _abrir(raiz);
      else { ++_seq; _sair3d(); raiz.querySelector('[data-gl-corpo]').innerHTML = '<div class="dim">A tabela órgão a órgão está abaixo. "Globo" mostra o mesmo pago, por destino, e confere a soma com ela.</div>'; }
    } else if (b.dataset.glVista) { if (_cena) _cena.voar(b.dataset.glVista); }
    else if (b.dataset.glArco != null) _selecionar(raiz, Number(b.dataset.glArco));
  });
}

