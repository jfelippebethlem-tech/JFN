/* O10.7 · a IMAGEM PARADA do globo — SVG em d3-geo, sem WebGL e sem laço de quadro.
 * É o que aparece com `prefers-reduced-motion`, no modo sóbrio e no celular (≤ 480 px), e é o pôster enquanto o globo
 * 3D carrega. Mesmo modelo (`dados.js`), mesmos arcos, mesmos valores no <title> de cada traço.
 * O RJ é desenhado com os 92 municípios (IBGE); a sede fora do RJ sai pela borda na direção da UF, com a sigla —
 * nunca um ponto numa cidade. Pago dentro do próprio município da UG = disco no ponto (arco de comprimento zero). */
import {geoMercator, geoPath} from 'd3-geo';
import {feature} from 'topojson-client';
import {esc} from '../../nucleo/dom.js';
import {coord, espessura} from './dados.js';

const W = 720, H = 440, M = 18;

/** Centros [lat, lng] dos 92 municípios a partir do TopoJSON do IBGE (o mesmo do mapa do Território). */
export function centrosRJ(topo, geoCentroid) {
  const fc = feature(topo, topo.objects.municipios);
  const m = new Map();
  for (const f of fc.features) { const [lng, lat] = geoCentroid(f); m.set(String(f.properties.cod_ibge), [lat, lng]); }
  return m;
}

function _naBorda(x0, y0, x, y) {           // corta o segmento (x0,y0)→(x,y) na moldura
  if (x >= M && x <= W - M && y >= M && y <= H - M) return [x, y, false];
  const dx = x - x0, dy = y - y0;
  let t = 1;
  if (dx) t = Math.min(t, dx > 0 ? (W - M - x0) / dx : (M - x0) / dx);
  if (dy) t = Math.min(t, dy > 0 ? (H - M - y0) / dy : (M - y0) / dy);
  return [x0 + dx * t, y0 + dy * t, true];
}

export function svgParado(m, topo, centros, {sel = null} = {}) {
  const fc = feature(topo, topo.objects.municipios);
  const proj = geoMercator().fitExtent([[M + 30, M + 20], [W - M - 120, H - M - 30]], fc);
  const path = geoPath(proj);
  const p = k => { const c = coord(k, centros); return c ? proj([c[1], c[0]]) : null; };
  const [cx, cy] = proj([-42.66, -22.25]);
  let arcos = '', discos = '', bordas = '';
  const vistos = new Set();
  for (const a of m.arcos) {
    const w = espessura(a.centavos, m.max_centavos, 0.8, 9);
    const cls = `gl-a${a.t1_centavos > 0 ? ' gl-t1' : ''}${a.tracejado ? ' gl-tr' : ''}${a.origem_comprovada ? '' : ' gl-oi'}${sel === a.id ? ' gl-sel' : ''}`;
    const po = p(a.o), pd0 = p(a.d);
    if (!po || !pd0) continue;
    if (a.mesmo_lugar) {
      discos += `<circle class="${cls}" data-gl-arco="${a.id}" cx="${po[0].toFixed(1)}" cy="${po[1].toFixed(1)}" r="${(w * 1.4 + 2).toFixed(1)}"><title>${esc(a.rotulo)}</title></circle>`;
      continue;
    }
    const [x, y, cortado] = _naBorda(cx, cy, pd0[0], pd0[1]);
    const mx = (po[0] + x) / 2, my = (po[1] + y) / 2 - Math.min(90, Math.hypot(x - po[0], y - po[1]) * 0.35);
    arcos += `<path class="${cls}" data-gl-arco="${a.id}" d="M${po[0].toFixed(1)},${po[1].toFixed(1)} Q${mx.toFixed(1)},${my.toFixed(1)} ${x.toFixed(1)},${y.toFixed(1)}" stroke-width="${w.toFixed(2)}"><title>${esc(a.rotulo)}</title></path>`;
    if ((cortado || a.tracejado) && !vistos.has(a.d)) {
      vistos.add(a.d);
      const sigla = a.tracejado ? 'INDISPONÍVEL' : a.d.slice(2);
      bordas += `<g class="gl-chip${a.tracejado ? ' gl-chip-ind' : ''}"><rect x="${(x - 4).toFixed(1)}" y="${(y - 9).toFixed(1)}" width="${sigla.length * 7.4 + 10}" height="18" rx="9"/><text x="${(x + 1).toFixed(1)}" y="${(y + 4).toFixed(1)}">${esc(sigla)}</text></g>`;
    }
  }
  const mun = fc.features.map(f => `<path d="${path(f)}"/>`).join('');
  return `<svg class="gl-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Imagem parada: para onde foi o pago por OB — ${m.arcos.length} ligações; a tabela equivalente está logo abaixo">
    <g class="gl-mun">${mun}</g><g class="gl-arcos">${arcos}</g><g class="gl-discos">${discos}</g><g class="gl-bordas">${bordas}</g></svg>`;
}
