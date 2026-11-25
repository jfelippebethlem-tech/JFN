/* O10.7 · GLOBO COM ARCOS — o modelo (puro: sem DOM, sem three). Roda no Node nos testes.
 *
 * Entrada: `d.globo` da MESMA rota da tabela (`/api/orcamento_orgao?…&arcos=1`), montado no servidor sobre o mesmo
 * payload (compliance_agent/orcamento_globo.py). Cada linha = {orgao, ug, o, oc, d, v, t1}: o pago por OB do SIAFE
 * de uma UG para um destino. Aqui só se FILTRA (os órgãos visíveis na tabela) e se AGREGA (limite de arcos): nenhum
 * valor é criado, estimado ou arredondado de novo. A soma é feita em centavos inteiros e conferida contra a coluna
 * "Pago (OB do SIAFE)" dos mesmos órgãos — se não bater, o globo NÃO desenha (`confere: false`).
 *
 * Três destinos:
 *   desenhado   'M:<ibge>' (município do RJ) ou 'U:<UF>' (sede fora do RJ: ponto da UF, nunca uma cidade inventada);
 *   tracejado   'X:sem_cadastro' — CNPJ sem sede comprovada: arco tracejado até o rótulo INDISPONÍVEL;
 *   fora        'X:pf', 'X:generico', 'X:ug', 'X:exterior' — sem ponto (pessoa física nunca vira ponto nem nome).
 */
import {fmtR} from '../../nucleo/formato.js';

/* Centro aproximado de cada UF (graus decimais). Só posiciona o PONTO DA UF quando a sede é de fora do RJ — o rótulo
   diz a UF, nunca uma cidade. */
export const UF_CENTRO = {
  AC: [-9.02, -70.81], AL: [-9.57, -36.78], AP: [1.41, -51.77], AM: [-3.47, -65.10], BA: [-12.58, -41.70],
  CE: [-5.20, -39.53], DF: [-15.83, -47.86], ES: [-19.19, -40.34], GO: [-15.98, -49.86], MA: [-5.42, -45.44],
  MT: [-12.64, -55.42], MS: [-20.51, -54.54], MG: [-18.10, -44.38], PA: [-3.79, -52.48], PB: [-7.28, -36.72],
  PR: [-24.89, -51.55], PE: [-8.38, -37.86], PI: [-6.60, -42.28], RJ: [-22.25, -42.66], RN: [-5.81, -36.59],
  RS: [-30.17, -53.50], RO: [-10.83, -63.34], RR: [1.99, -61.33], SC: [-27.45, -50.95], SP: [-22.19, -48.79],
  SE: [-10.57, -37.45], TO: [-9.46, -48.26],
};
/* O rótulo INDISPONÍVEL fica no mar, a leste do RJ: é um RÓTULO, não um lugar (o texto diz isso). */
export const PONTO_INDISPONIVEL = [-24.2, -38.6];

const FORA = new Set(['X:pf', 'X:generico', 'X:ug', 'X:exterior']);
const cent = v => Math.round(Number(v) * 100);
export const reais = c => fmtR(c / 100);

/** Nome legível de um lugar do payload. */
export function nomeLugar(g, k) {
  if (k === 'X:sem_cadastro') return 'INDISPONÍVEL — sede não comprovada';
  if (k === 'U:RJ*') return 'UGs do Estado (agregadas)';
  if (k === 'M:*') return 'demais municípios do RJ (agregados)';
  const l = (g.lugares || {})[k];
  if (!l) return k;
  return l.tipo === 'uf' ? (k === 'U:RJ' ? 'Estado do RJ (município não comprovado)' : `${l.nome} — sede fora do RJ`) : l.nome;
}

/** Os órgãos visíveis na tabela → total do "Pago (OB do SIAFE)" deles, em centavos (o número a bater). */
export function totalTabela(orgaos) {
  let c = 0, n = 0;
  for (const o of orgaos || []) if (o.pago_siafe != null) { c += cent(o.pago_siafe); n++; }
  return {centavos: c, orgaos_com_pago: n};
}

/**
 * Modelo do globo para os órgãos `orgaos` (os visíveis na tabela, no mesmo filtro).
 * `max` = teto de arcos desenhados; acima dele, agrega (1º: todas as UGs numa origem só; 2º: municípios do RJ fora do
 * topo viram "demais municípios"). Devolve também a conferência contra a tabela.
 */
export function modelo(g, orgaos, {max = 80} = {}) {
  const vis = new Set((orgaos || []).map(o => o.orgao));
  const linhas = ((g && g.linhas) || []).filter(l => vis.has(l.orgao));
  const tab = totalTabela(orgaos);
  const pares = new Map(), fora = new Map();
  let somaArcos = 0, somaTrac = 0, somaFora = 0;
  for (const l of linhas) {
    const c = cent(l.v);
    if (FORA.has(l.d)) { fora.set(l.d, (fora.get(l.d) || 0) + c); somaFora += c; continue; }
    const tr = l.d === 'X:sem_cadastro';
    if (tr) somaTrac += c; else somaArcos += c;
    const k = l.o + '>' + l.d;
    const p = pares.get(k) || {o: l.o, d: l.d, c: 0, t1: 0, ugs: new Set(), oc: true, tracejado: tr};
    p.c += c; p.t1 += cent(l.t1 || 0); p.ugs.add(l.ug); p.oc = p.oc && !!l.oc;
    pares.set(k, p);
  }
  let arcos = [...pares.values()], agregado = 'nenhum';
  const juntar = (lista, chave) => {
    const m = new Map();
    for (const a of lista) {
      const [o, d] = chave(a), k = o + '>' + d;
      const p = m.get(k) || {o, d, c: 0, t1: 0, ugs: new Set(), oc: true, tracejado: a.tracejado};
      p.c += a.c; p.t1 += a.t1; a.ugs.forEach(u => p.ugs.add(u)); p.oc = p.oc && a.oc;
      m.set(k, p);
    }
    return [...m.values()];
  };
  if (arcos.length > max) { arcos = juntar(arcos, a => ['U:RJ*', a.d]); agregado = 'origem'; }
  if (arcos.length > max) {
    arcos.sort((a, b) => b.c - a.c);
    const topo = new Set(arcos.slice(0, max - 1).map(a => a.d));
    arcos = juntar(arcos, a => [a.o, topo.has(a.d) || !a.d.startsWith('M:') ? a.d : 'M:*']);
    agregado = 'municipio';
  }
  arcos.sort((a, b) => b.c - a.c);
  const soma = somaArcos + somaTrac + somaFora;
  return {
    arcos: arcos.map((a, i) => ({id: i, o: a.o, d: a.d, centavos: a.c, t1_centavos: a.t1, n_ugs: a.ugs.size,
                                 origem_comprovada: a.oc, tracejado: a.tracejado, mesmo_lugar: a.o === a.d,
                                 rotulo: `${nomeLugar(g, a.o)} → ${nomeLugar(g, a.d)}: ${reais(a.c)}`})),
    fora: [...fora.entries()].sort((a, b) => b[1] - a[1]).map(([k, c]) => ({k, rotulo: (g.baldes || {})[k] || k, centavos: c})),
    soma_arcos: somaArcos, soma_tracejado: somaTrac, soma_fora: somaFora, soma, n_linhas: linhas.length,
    total_tabela: tab.centavos, confere: soma === tab.centavos, agregado, max,
    max_centavos: Math.max(0, ...arcos.map(a => a.c)),
  };
}

/** Espessura do arco: ∝ raiz do valor (escala RAIZ declarada na legenda), entre `min` e `maxL`. */
export function espessura(c, maxC, min = 0.12, maxL = 1.1) {
  if (!(maxC > 0) || !(c > 0)) return min;
  return min + (maxL - min) * Math.sqrt(c / maxC);
}

/** Coordenadas [lat, lng] de um lugar; `centros` = Map ibge→[lat,lng] dos 92 municípios (do TopoJSON). */
export function coord(k, centros) {
  if (k === 'X:sem_cadastro') return PONTO_INDISPONIVEL;
  if (k === 'U:RJ*' || k === 'M:*') return UF_CENTRO.RJ;
  if (k.startsWith('M:')) return (centros && centros.get(k.slice(2))) || null;
  if (k.startsWith('U:')) return UF_CENTRO[k.slice(2)] || null;
  return null;
}
