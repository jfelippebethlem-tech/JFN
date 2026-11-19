/* GALÁXIA v64 — desenho 2D em canvas com LOD, usado pela página /galaxia e pelo preview do Início.
 *
 * Dados = `/api/galaxia` (forma leve): nós com x/y JÁ calculados no servidor (aglomerado = órgão no
 * centro, fornecedores em filotaxia, sócios em volta), arestas como [s, t, tipo]. Aqui só se desenha.
 *
 * NÍVEIS DE DETALHE (k = px por unidade do mundo):
 *   longe   k < .28  névoa dos aglomerados, órgãos, dossiês, fornecedores como poeira (1–2 px), pontes
 *   médio   k < .95  fornecedores em círculo pelo score, ligações órgão→fornecedor, endereço e sócio
 *   perto            sócios, processos SEI, nomes
 * Culling pelo retângulo visível; nós do mesmo balde de cor numa única path (um `fill` por cor).
 * Pulsos de luz correm em ligações visíveis (só quando há laço: página com movimento permitido).
 *
 * Módulo FOLHA (sem efeito de topo — lei do `test_painel_ordem_de_boot`).
 */

export const COR = {
  tinta: '#0B1B3A', cobalto: '#1D5BFF', ceu: '#6FA8FF', ciano: '#38D3FF', gelo: '#BFD3FF',
  alerta: '#FFC400', orgao: '#0B3D91', sei: '#8FA4C8',
};
export const CRITICO = 50;

/** Cor do fornecedor pela régua do Radar: escala de azul; amarelo SÓ para crítico (≥ 50). */
export function corScore(s) {
  if (s >= CRITICO) return COR.alerta;
  if (s >= 25) return COR.cobalto;
  if (s >= 10) return COR.ceu;
  return COR.gelo;
}
const ALFA_SCORE = [.42, .68, .9, 1];      // v70: score < 10 · 10–24 · 25–49 · crítico
const balde = s => s >= CRITICO ? 3 : s >= 25 ? 2 : s >= 10 ? 1 : 0;

/** Prepara índices: vizinhos, grade espacial, listas por tipo, raio de cada nó. */
export function preparar(d) {
  const nos = d.nos || [], ar = d.arestas || [], tipos = d.tipos_aresta || [];
  const T = Object.fromEntries(tipos.map((t, i) => [t, i]));
  for (const n of nos) {
    n.r = n.t === 'orgao' ? 7 + Math.min(14, Math.sqrt(n.nf || 0) * 1.2)
      : n.t === 'caso' ? 6.5 + (n.nv || 0) * .9
      : n.t === 'cnpj' ? 2.2 + Math.min(4.8, (n.s || 0) / 12) + (n.nk ? 1.2 : 0)
      : n.t === 'socio' ? 1.5 : 1.3;
    n.viz = [];
  }
  ar.forEach((a, i) => { nos[a[0]] && nos[a[0]].viz.push(i); nos[a[1]] && nos[a[1]].viz.push(i); });
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const n of nos) { x0 = Math.min(x0, n.x - (n.R || 0)); y0 = Math.min(y0, n.y - (n.R || 0)); x1 = Math.max(x1, n.x + (n.R || 0)); y1 = Math.max(y1, n.y + (n.R || 0)); }
  const C = 60, grade = new Map();
  nos.forEach((n, i) => { const k = Math.floor(n.x / C) + ':' + Math.floor(n.y / C); (grade.get(k) || grade.set(k, []).get(k)).push(i); });
  const por = t => nos.map((n, i) => n.t === t ? i : -1).filter(i => i >= 0);
  return {d, nos, ar, T, bbox: [x0, y0, x1, y1], grade, C,
    orgaos: por('orgao'), casos: por('caso'), forn: por('cnpj'), socios: por('socio'), seis: por('sei'),
    pulsos: [], filtro: null, sel: -1, foco: null};
}

/** Câmera que enquadra a caixa toda (ou um aglomerado) no canvas de w×h. */
export function enquadrar(G, w, h, caixa = G.bbox, folga = .9) {
  const [x0, y0, x1, y1] = caixa;
  const k = Math.min(w / (x1 - x0 || 1), h / (y1 - y0 || 1)) * folga;
  return {cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, k, rot: 0};
}

/** Nó sob o ponto de tela (px, py), com tolerância em px; -1 se nenhum. */
export function acertar(G, cam, w, h, px, py, tol = 12) {
  const [wx, wy] = paraMundo(cam, w, h, px, py);
  const raio = tol / cam.k, C = G.C;
  let melhor = -1, dm = Infinity;
  for (let gx = Math.floor((wx - raio - 30) / C); gx <= Math.floor((wx + raio + 30) / C); gx++)
    for (let gy = Math.floor((wy - raio - 30) / C); gy <= Math.floor((wy + raio + 30) / C); gy++)
      for (const i of G.grade.get(gx + ':' + gy) || []) {
        const n = G.nos[i];
        if (!visivelNoNivel(G, n, cam.k) || (G.filtro && !G.filtro(n))) continue;
        const d = Math.hypot(n.x - wx, n.y - wy) - n.r * kr(cam.k) / cam.k;
        if (d < raio && d < dm) { dm = d; melhor = i; }
      }
  return melhor;
}

export function paraMundo(cam, w, h, px, py) {
  const c = Math.cos(-cam.rot), s = Math.sin(-cam.rot);
  const dx = (px - w / 2) / cam.k, dy = (py - h / 2) / cam.k;
  return [cam.cx + dx * c - dy * s, cam.cy + dx * s + dy * c];
}
export function paraTela(cam, w, h, x, y) {
  const c = Math.cos(cam.rot), s = Math.sin(cam.rot), dx = x - cam.cx, dy = y - cam.cy;
  return [w / 2 + (dx * c - dy * s) * cam.k, h / 2 + (dx * s + dy * c) * cam.k];
}

/** Escala do raio na tela: linear até k = 1,2; depois cresce devagar (o zoom revela, não incha). */
export const kr = k => k <= 1.2 ? k : 1.2 + (k - 1.2) * .3;

function visivelNoNivel(G, n, k) {
  if (n.t === 'socio' || n.t === 'sei') return k >= .95;
  return true;
}

/** Sorteia novos pulsos em ligações visíveis (chamado pelo laço da página, ~4 por segundo). */
export function semearPulsos(G, cam, w, h, n = 3) {
  if (G.pulsos.length > 60) return;
  const vis = G._visAr;
  if (!vis || !vis.length) return;
  for (let j = 0; j < n; j++) {
    const i = vis[(Math.random() * vis.length) | 0];
    G.pulsos.push({a: i, t: 0, v: .35 + Math.random() * .5, inv: Math.random() < .5});
  }
}

/** Desenha um quadro. `dt` em s avança os pulsos. Opções: {fundo, rotulos, pulsos, nevoa}.
 *  Devolve quantos nós caem DENTRO da tela (sem margem) — 0 = tela vazia (v66: a página recentra). */
export function desenhar(ctx, G, cam, w, h, dt = 0, op = {}) {
  const {nos, ar} = G, k = cam.k, dpr = op.dpr || 1;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const T = (x, y) => paraTela(cam, w, h, x, y);
  const m = 40 / k, [vx0, vy0] = paraMundo(cam, w, h, 0, 0), [vx1, vy1] = paraMundo(cam, w, h, w, h);
  const [vx2, vy2] = paraMundo(cam, w, h, w, 0), [vx3, vy3] = paraMundo(cam, w, h, 0, h);
  const X0 = Math.min(vx0, vx1, vx2, vx3) - m, X1 = Math.max(vx0, vx1, vx2, vx3) + m;
  const Y0 = Math.min(vy0, vy1, vy2, vy3) - m, Y1 = Math.max(vy0, vy1, vy2, vy3) + m;
  const dentro = n => n.x + (n.R || n.r) >= X0 && n.x - (n.R || n.r) <= X1 && n.y + (n.R || n.r) >= Y0 && n.y - (n.R || n.r) <= Y1;
  const filtro = G.filtro, apaga = n => filtro && !filtro(n);
  const longe = k < .28, perto = k >= .95;

  /* 1. névoa dos aglomerados (gradiente radial azul muito leve, um por órgão visível) */
  if (op.nevoa !== false) for (const i of G.orgaos) {
    const n = nos[i]; if (!dentro(n) || !n.R) continue;
    const [x, y] = T(n.x, n.y), R = n.R * k;
    if (R < 3) continue;
    const g = ctx.createRadialGradient(x, y, 0, x, y, R * 1.08);
    const a = apaga(n) ? .02 : (n.s >= CRITICO ? .10 : .07);
    g.addColorStop(0, `rgba(111,168,255,${a * 1.5})`); g.addColorStop(.55, `rgba(56,211,255,${a * .55})`); g.addColorStop(1, 'rgba(56,211,255,0)');
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, R * 1.08, 0, 6.2832); ctx.fill();
  }

  /* 2. ligações — por nível; agrupadas por tipo num único stroke */
  const vis = [];
  const TA = G.T;
  const tiposVis = longe ? new Set([TA.caso_caso, TA.cita_cnpj]) : perto ? null : new Set([TA.caso_caso, TA.cita_cnpj, TA.caso_orgao, TA.orgao, TA.endereco]);
  const estilos = [
    [TA.orgao, 'rgba(29,91,255,.10)', .6], [TA.socio, 'rgba(56,211,255,.38)', .7], [TA.endereco, 'rgba(255,196,0,.55)', .9],
    [TA.cita_cnpj, 'rgba(29,91,255,.32)', .8], [TA.cita_sei, 'rgba(143,164,200,.4)', .6], [TA.caso_orgao, 'rgba(11,61,145,.22)', .7],
    [TA.caso_caso, 'rgba(29,91,255,.55)', 1.2],
  ];
  const longa = Math.hypot(w, h) * .42, longas = [];
  for (const [tipo, cor, lw] of estilos) {
    if (tipo === undefined || (tiposVis && !tiposVis.has(tipo))) continue;
    ctx.beginPath(); let algum = false;
    for (let i = 0; i < ar.length; i++) {
      const a = ar[i]; if (a[2] !== tipo) continue;
      const p = nos[a[0]], q = nos[a[1]];
      if (!visivelNoNivel(G, p, k) || !visivelNoNivel(G, q, k)) continue;
      if ((p.x < X0 && q.x < X0) || (p.x > X1 && q.x > X1) || (p.y < Y0 && q.y < Y0) || (p.y > Y1 && q.y > Y1)) continue;
      if (filtro && !(filtro(p) && filtro(q))) continue;
      const [x1, y1] = T(p.x, p.y), [x2, y2] = T(q.x, q.y);
      if (!longe && tipo !== TA.caso_caso && Math.hypot(x2 - x1, y2 - y1) > longa) { longas.push(x1, y1, x2, y2); continue; }
      if (tipo === TA.caso_caso) { const mx = (x1 + x2) / 2 - (y2 - y1) * .18, my = (y1 + y2) / 2 + (x2 - x1) * .18; ctx.moveTo(x1, y1); ctx.quadraticCurveTo(mx, my, x2, y2); }
      else { ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); }
      algum = true; vis.push(i);
    }
    if (algum) { ctx.strokeStyle = cor; ctx.lineWidth = lw; ctx.stroke(); }
  }
  if (longas.length) {                                   // ligações entre aglomerados distantes: só um véu
    ctx.beginPath();
    for (let i = 0; i < longas.length; i += 4) { ctx.moveTo(longas[i], longas[i + 1]); ctx.lineTo(longas[i + 2], longas[i + 3]); }
    ctx.strokeStyle = 'rgba(29,91,255,.045)'; ctx.lineWidth = .7; ctx.stroke();
  }
  G._visAr = vis;

  /* 3. pulsos de luz correndo nas ligações visíveis */
  if (op.pulsos && G.pulsos.length) {
    const vivos = [];
    ctx.fillStyle = 'rgba(56,211,255,.95)';
    for (const pu of G.pulsos) {
      pu.t += dt * pu.v; if (pu.t >= 1) continue;
      const a = ar[pu.a]; const p = nos[a[pu.inv ? 1 : 0]], q = nos[a[pu.inv ? 0 : 1]];
      const [x1, y1] = T(p.x, p.y), [x2, y2] = T(q.x, q.y);
      const x = x1 + (x2 - x1) * pu.t, y = y1 + (y2 - y1) * pu.t, al = Math.sin(pu.t * Math.PI);
      ctx.globalAlpha = .25 * al; ctx.beginPath(); ctx.arc(x, y, 5, 0, 6.2832); ctx.fill();
      ctx.globalAlpha = al; ctx.beginPath(); ctx.arc(x, y, 1.6, 0, 6.2832); ctx.fill();
      vivos.push(pu);
    }
    ctx.globalAlpha = 1; G.pulsos = vivos;
  }

  /* 4. nós: SEI e sócios (perto), fornecedores por balde, órgãos, dossiês por cima */
  if (perto) {
    ctx.fillStyle = COR.sei; ctx.beginPath();
    for (const i of G.seis) { const n = nos[i]; if (!dentro(n) || apaga(n)) continue; const [x, y] = T(n.x, n.y); ctx.rect(x - 1.6, y - 1.6, 3.2, 3.2); }
    ctx.fill();
    ctx.fillStyle = COR.ciano; ctx.beginPath();
    for (const i of G.socios) { const n = nos[i]; if (!dentro(n) || apaga(n)) continue; const [x, y] = T(n.x, n.y); const r = Math.max(1.4, n.r * kr(k)); ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, 6.2832); }
    ctx.fill();
  }
  /* v70: fornecedor pintado com a COR DO ÓRGÃO do aglomerado (`n.cor`, paleta única config/cores_orgaos.yaml,
     a mesma do grafo do vault). O score continua no tamanho e na opacidade (baixo = mais transparente) e o
     crítico ganha o anel âmbar. Um `fill` por (cor, faixa de score). */
  const caminhos = [[], [], [], []], porCor = new Map();
  for (const i of G.forn) { const n = nos[i]; if (!dentro(n)) continue; const b = balde(n.s || 0); caminhos[b].push(i);
    if (apaga(n)) continue; const ch = (n.cor || COR.gelo) + '|' + b; (porCor.get(ch) || porCor.set(ch, []).get(ch)).push(i); }
  for (const [ch, lista] of porCor) {
    const [cor, b] = ch.split('|');
    ctx.beginPath();
    for (const i of lista) {
      const n = nos[i], [x, y] = T(n.x, n.y);
      if (longe) { const r = +b >= 2 ? 1.6 : 1; ctx.rect(x - r, y - r, r * 2, r * 2); }
      else { const r = Math.max(1.6, n.r * kr(k)); ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, 6.2832); }
    }
    ctx.globalAlpha = ALFA_SCORE[b]; ctx.fillStyle = cor; ctx.fill();
  }
  ctx.globalAlpha = 1;
  {
    const fora = []; for (const lista of caminhos) for (const i of lista) if (apaga(nos[i])) fora.push(i);
    if (fora.length) {
      ctx.globalAlpha = .18; ctx.fillStyle = COR.gelo; ctx.beginPath();
      for (const i of fora) { const n = nos[i]; const [x, y] = T(n.x, n.y); ctx.rect(x - 1, y - 1, 2, 2); }
      ctx.fill(); ctx.globalAlpha = 1;
    }
  }
  /* crítico: anel amarelo fino em volta (lê mesmo no "longe") */
  if (!longe) {
    ctx.beginPath();
    for (const i of caminhos[3]) { const n = nos[i]; if (apaga(n)) continue; const [x, y] = T(n.x, n.y); const r = Math.max(1.6, n.r * kr(k)) + 2.5; ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, 6.2832); }
    ctx.strokeStyle = 'rgba(255,176,0,.9)'; ctx.lineWidth = 1.6; ctx.stroke();
  }
  /* órgãos: disco branco com aro azul-marinho */
  if (op.mini) {                                         // miniatura: órgão é só um ponto marinho (o aro pesava)
    ctx.beginPath();
    for (const i of G.orgaos) { const n = nos[i]; if (!dentro(n) || !n.nf) continue; const [x, y] = T(n.x, n.y); const r = 1.2 + Math.min(2.4, Math.sqrt(n.nf) * .25); ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, 6.2832); }
    ctx.fillStyle = 'rgba(11,61,145,.75)'; ctx.fill();
  }
  for (const i of (op.mini ? [] : G.orgaos)) {
    const n = nos[i]; if (!dentro(n)) continue;
    const [x, y] = T(n.x, n.y), r = Math.max(longe ? 2.4 : 3.5, n.r * kr(k) * (longe ? 1.6 : 1));
    ctx.globalAlpha = apaga(n) ? .25 : 1;
    ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); ctx.fillStyle = '#fff'; ctx.fill();
    ctx.lineWidth = Math.max(1, r * .22); ctx.strokeStyle = n.cor || COR.orgao; ctx.stroke();
    ctx.beginPath(); ctx.arc(x, y, r * .38, 0, 6.2832); ctx.fillStyle = n.cor || COR.cobalto; ctx.fill();
  }
  ctx.globalAlpha = 1;
  /* dossiês do vault: estrela com halo — os pontos mais vistosos do céu */
  for (const i of G.casos) {
    const n = nos[i]; if (!dentro(n)) continue;
    const [x, y] = T(n.x, n.y), r = Math.max(longe ? 3.2 : 4, n.r * kr(k) * (longe ? 1.4 : 1));
    ctx.globalAlpha = apaga(n) ? .25 : 1;
    const g = ctx.createRadialGradient(x, y, 0, x, y, r * 3.2);
    g.addColorStop(0, 'rgba(56,211,255,.55)'); g.addColorStop(.4, 'rgba(29,91,255,.16)'); g.addColorStop(1, 'rgba(29,91,255,0)');
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r * 3.2, 0, 6.2832); ctx.fill();
    estrela(ctx, x, y, r, n.cor || ((n.nv || 0) >= 4 ? COR.cobalto : COR.ceu));
  }
  ctx.globalAlpha = 1;

  /* 5. seleção e vizinhos */
  if (G.sel >= 0) {
    const n = nos[G.sel], [x, y] = T(n.x, n.y), r = Math.max(5, n.r * kr(k)) + 6;
    ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); ctx.strokeStyle = COR.cobalto; ctx.lineWidth = 2; ctx.stroke();
    ctx.beginPath(); ctx.arc(x, y, r + 5, 0, 6.2832); ctx.strokeStyle = 'rgba(56,211,255,.45)'; ctx.lineWidth = 1; ctx.stroke();
    ctx.beginPath();
    for (const ai of n.viz) { const a = ar[ai], o = nos[a[0] === G.sel ? a[1] : a[0]]; const [x2, y2] = T(o.x, o.y); ctx.moveTo(x, y); ctx.lineTo(x2, y2); }
    ctx.strokeStyle = 'rgba(29,91,255,.6)'; ctx.lineWidth = 1.2; ctx.stroke();
  }

  /* 6. rótulos — órgãos grandes no longe; casos e fornecedores com sinal no perto */
  if (op.rotulos !== false) rotulos(ctx, G, cam, w, h, T, dentro, apaga, longe, perto);
  return contarNaTela(G, cam, w, h);
}

/** Nós visíveis no nível atual cujo centro cai na tela — ou na `area` [x0,y0,x1,y1] (filtro respeitado). Barato: ~10 mil nós. */
export function contarNaTela(G, cam, w, h, area = null) {
  const k = cam.k; let n = 0;
  const [ax0, ay0, ax1, ay1] = area || [0, 0, w, h];          // área útil (sem os painéis por cima)
  for (const no of G.nos) {
    if (!visivelNoNivel(G, no, k) || (G.filtro && !G.filtro(no))) continue;
    const [x, y] = paraTela(cam, w, h, no.x, no.y), r = (no.R && no.t === 'orgao' ? 0 : no.r * kr(k));
    if (x >= ax0 - r && x <= ax1 + r && y >= ay0 - r && y <= ay1 + r) n++;
  }
  return n;
}

function estrela(ctx, x, y, r, cor) {
  ctx.beginPath();
  for (let i = 0; i < 8; i++) { const a = i * Math.PI / 4 - Math.PI / 2, rr = i % 2 ? r * .42 : r; const px = x + rr * Math.cos(a), py = y + rr * Math.sin(a); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); }
  ctx.closePath(); ctx.fillStyle = cor; ctx.fill();
  ctx.beginPath(); ctx.arc(x, y, r * .3, 0, 6.2832); ctx.fillStyle = '#fff'; ctx.fill();
}

function rotulos(ctx, G, cam, w, h, T, dentro, apaga, longe, perto) {
  const {nos} = G, k = cam.k, ocupado = [];
  const cabe = (x, y, lw, lh) => {
    for (const [a, b, c, d] of ocupado) if (x < c && x + lw > a && y < d && y + lh > b) return false;
    ocupado.push([x, y, x + lw, y + lh]); return true;
  };
  ctx.textBaseline = 'middle';
  const escreve = (n, txt, fonte, cor, dy) => {
    const [x, y] = T(n.x, n.y);
    if (x < -40 || x > w + 40 || y < -20 || y > h + 20) return;
    ctx.font = fonte; const lw = Math.min(ctx.measureText(txt).width, 220);
    const tx = x - lw / 2, ty = y + dy;
    if (!cabe(tx - 4, ty - 8, lw + 8, 16)) return;
    ctx.lineWidth = 3.5; ctx.strokeStyle = 'rgba(247,250,255,.92)'; ctx.strokeText(txt, tx, ty, 220);
    ctx.fillStyle = cor; ctx.fillText(txt, tx, ty, 220);
  };
  const curto = (s, n) => s.length > n ? s.slice(0, n - 1) + '…' : s;
  if (G.sel >= 0) { const n = nos[G.sel]; escreve(n, curto(n.l, 46), '600 12.5px Geist,system-ui,sans-serif', COR.tinta, -Math.max(5, n.r * kr(k)) - 16); }
  const orgs = G.orgaos.filter(i => dentro(nos[i]) && !apaga(nos[i])).sort((a, b) => (nos[b].nf || 0) - (nos[a].nf || 0));
  const nOrg = longe ? Math.max(6, Math.round(w / 110)) : 40;
  for (const i of orgs.slice(0, nOrg)) { const n = nos[i]; escreve(n, curto(n.l, longe ? 28 : 40), `600 ${longe ? 11 : 12}px Geist,system-ui,sans-serif`, COR.orgao, Math.max(8, n.r * kr(k) * (longe ? 1.6 : 1)) + 9); }
  if (longe) return;
  const casos = G.casos.filter(i => dentro(nos[i]) && !apaga(nos[i])).sort((a, b) => (nos[b].nv || 0) - (nos[a].nv || 0));
  for (const i of casos.slice(0, perto ? 60 : 14)) { const n = nos[i]; escreve(n, curto(n.l.replace(/^Caso\s*[—-]\s*/i, ''), 34), 'italic 13px "Instrument Serif",Georgia,serif', COR.cobalto, -Math.max(6, n.r * kr(k)) - 10); }
  if (!perto) return;
  const fs = G.forn.filter(i => dentro(nos[i]) && !apaga(nos[i])).sort((a, b) => (nos[b].s || 0) - (nos[a].s || 0));
  for (const i of fs.slice(0, 80)) { if (i === G.sel) continue; const n = nos[i]; escreve(n, curto(n.l, 30), '500 10.5px Geist,system-ui,sans-serif', '#2A3B5E', Math.max(3, n.r * kr(k)) + 8); }
}
