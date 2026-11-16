/* GALÁXIA — layout determinístico e desenho 2D (sem three.js).
 *
 * Usado em dois lugares que NÃO podem carregar WebGL:
 *   · o preview do fim da aba Início (painel), que é um canvas minúsculo pintado UMA vez;
 *   · o modo estático da página /galaxia (movimento reduzido, máquina lenta ou `?modo=2d`).
 *
 * O layout é uma espiral de três braços: os casos vão do núcleo para fora em ordem de gravidade
 * (o nível 4 fica no centro, onde a luz é maior), e cada CNPJ / processo SEI orbita o primeiro caso
 * que o cita; os sócios orbitam o CNPJ. É O(n) e estável entre cargas — o mesmo dado dá o mesmo
 * desenho, sem simulação de forças.
 *
 * Módulo FOLHA, sem efeito de topo (lei do `test_painel_ordem_de_boot`).
 */

export const COR = {
  ciano: '#22B5F5', ion: '#1E7BF0', gelo: '#7FDBFF', marinho: '#0B3D91', fundo: '#030B1F', branco: '#FFFFFF',
};

/** Hash estável de string → [0,1). */
export function h01(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return ((h >>> 0) % 100000) / 100000;
}

/** Posições {id: {x,y,z}} numa espiral de 3 braços, escala ~[-R,R]. */
export function layoutEspiral(dados, R = 300) {
  const nos = dados.nos || [], ar = dados.arestas || [];
  const viz = new Map();
  for (const a of ar) {
    if (!viz.has(a.source)) viz.set(a.source, []);
    if (!viz.has(a.target)) viz.set(a.target, []);
    viz.get(a.source).push(a.target); viz.get(a.target).push(a.source);
  }
  const casos = nos.filter(n => n.tipo === 'caso')
    .sort((a, b) => (b.nivel || 0) - (a.nivel || 0) || (b.grau || 0) - (a.grau || 0) || (a.id < b.id ? -1 : 1));
  const pos = {};
  const N = Math.max(1, casos.length);
  casos.forEach((c, i) => {
    const t = Math.sqrt((i + 1) / N);                    // densidade maior no núcleo
    const r = R * (0.08 + 0.82 * t);
    const braco = i % 3;
    const ang = braco * (2 * Math.PI / 3) + t * 4.2 + (h01(c.id) - 0.5) * 0.5;
    pos[c.id] = {x: r * Math.cos(ang), y: r * Math.sin(ang), z: (h01(c.id + 'z') - 0.5) * R * 0.08};
  });
  const orbita = (id, pai, raio) => {
    const p = pos[pai]; const a = h01(id) * Math.PI * 2, rr = raio * (0.6 + 0.8 * h01(id + 'r'));
    pos[id] = {x: p.x + rr * Math.cos(a), y: p.y + rr * Math.sin(a), z: p.z + (h01(id + 'z') - 0.5) * raio};
  };
  const solto = id => {
    const a = h01(id) * Math.PI * 2, r = R * (0.3 + 0.7 * h01(id + 'r'));
    pos[id] = {x: r * Math.cos(a), y: r * Math.sin(a), z: (h01(id + 'z') - 0.5) * R * 0.1};
  };
  for (const n of nos) {
    if (n.tipo !== 'cnpj' && n.tipo !== 'sei') continue;
    const pai = (viz.get(n.id) || []).find(v => v.startsWith('caso:') && pos[v]);
    if (pai) orbita(n.id, pai, n.tipo === 'cnpj' ? R * 0.07 : R * 0.1); else solto(n.id);
  }
  for (const n of nos) {
    if (n.tipo !== 'socio') continue;
    const pai = (viz.get(n.id) || []).find(v => pos[v]);
    if (pai) orbita(n.id, pai, R * 0.03); else solto(n.id);
  }
  return pos;
}

/** Tamanho visual de um nó (px no 2D; unidades no 3D multiplicam fora). */
export function raioNo(n) {
  if (n.tipo === 'caso') return 2.4 + (n.nivel || 0) * 0.9;
  if (n.tipo === 'cnpj') return 1.8;
  if (n.tipo === 'socio') return 1.0;
  return 1.1;
}
export function corNo(n) {
  if (n.tipo === 'caso') return (n.nivel || 0) >= 4 ? COR.ciano : (n.nivel || 0) >= 2 ? COR.ion : '#3B6FD8';
  if (n.tipo === 'cnpj') return COR.ion;
  if (n.tipo === 'socio') return COR.gelo;
  return COR.ciano;
}

/** Pinta a galáxia num canvas 2D, UMA vez (sem laço). `escala` multiplica o tamanho dos nós. */
export function desenhar2D(cv, dados, pos, {escala = 1, estrelas = 380, filtro = null, vista = null, fundo = true} = {}) {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const w = cv.clientWidth || cv.width, h = cv.clientHeight || cv.height;
  if (!w || !h) return;
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  /* fundo:false = só nós e ligações sobre transparente (o preview do Início põe o vídeo da galáxia por baixo) */
  if (fundo) {
  const bg = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.max(w, h) * 0.7);
  bg.addColorStop(0, '#0A2150'); bg.addColorStop(0.45, '#05112E'); bg.addColorStop(1, COR.fundo);
  g.fillStyle = bg; g.fillRect(0, 0, w, h);
  for (let i = 0; i < estrelas; i++) {                    // campo de estrelas (determinístico)
    const x = h01('sx' + i) * w, y = h01('sy' + i) * h, a = 0.15 + 0.6 * h01('sa' + i) ** 2;
    g.fillStyle = `rgba(190,225,255,${a.toFixed(2)})`; g.fillRect(x, y, h01('ss' + i) > 0.92 ? 1.6 : 0.9, h01('ss' + i) > 0.92 ? 1.6 : 0.9);
  }
  }
  let mx = 1;
  for (const k in pos) mx = Math.max(mx, Math.abs(pos[k].x), Math.abs(pos[k].y));
  /* vista = zoom/arrasto do modo plano (pinça, roda, botões): k multiplica a escala, x/y deslocam o centro */
  const vk = vista ? vista.k : 1, cx = w / 2 + (vista ? vista.x : 0), cy = h / 2 + (vista ? vista.y : 0);
  const s = (Math.min(w, h) / 2 - 10) / mx * vk;
  const P = id => pos[id] && [cx + pos[id].x * s, cy + pos[id].y * s];
  escala *= Math.min(2.2, Math.sqrt(vk));
  const nucleo = g.createRadialGradient(cx, cy, 0, cx, cy, Math.min(w, h) * 0.32 * vk);
  nucleo.addColorStop(0, 'rgba(127,219,255,.30)'); nucleo.addColorStop(0.4, 'rgba(30,123,240,.10)'); nucleo.addColorStop(1, 'rgba(30,123,240,0)');
  if (fundo) { g.fillStyle = nucleo; g.fillRect(0, 0, w, h); }
  const ok = filtro || (() => true);
  const nosV = (dados.nos || []).filter(ok), vis = new Set(nosV.map(n => n.id));
  g.globalCompositeOperation = 'lighter';
  for (const a of dados.arestas || []) {
    if (!vis.has(a.source) || !vis.has(a.target)) continue;
    const p = P(a.source), q = P(a.target); if (!p || !q) continue;
    const ponte = a.tipo === 'caso_caso';
    g.strokeStyle = ponte ? 'rgba(127,219,255,.34)' : 'rgba(30,123,240,.16)';
    g.lineWidth = ponte ? Math.min(1.8, 0.6 + (a.peso || 1) * 0.18) * escala : 0.6 * escala;
    g.beginPath(); g.moveTo(p[0], p[1]); g.lineTo(q[0], q[1]); g.stroke();
  }
  for (const n of nosV) {
    const p = P(n.id); if (!p) continue;
    const r = raioNo(n) * escala, cor = corNo(n);
    const halo = g.createRadialGradient(p[0], p[1], 0, p[0], p[1], r * (n.tipo === 'caso' ? 4.2 : 2.6));
    halo.addColorStop(0, cor + 'CC'); halo.addColorStop(0.35, cor + '44'); halo.addColorStop(1, cor + '00');
    g.fillStyle = halo; g.beginPath(); g.arc(p[0], p[1], r * (n.tipo === 'caso' ? 4.2 : 2.6), 0, Math.PI * 2); g.fill();
    g.fillStyle = n.tipo === 'caso' ? '#EAF8FF' : cor;
    g.beginPath(); g.arc(p[0], p[1], Math.max(0.6, r * (n.tipo === 'caso' ? 0.55 : 0.7)), 0, Math.PI * 2); g.fill();
  }
  g.globalCompositeOperation = 'source-over';
  return {P, s};
}
