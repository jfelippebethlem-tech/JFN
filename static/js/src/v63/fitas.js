/* v63 · FITAS DE LUZ — a assinatura visual (o "Relay" tem fitas verde-limão sobre preto; aqui são
 * feixes de fios azuis sobre branco, como seda).
 *
 * Uma função pura de (contexto, largura, altura, tempo). Duas vidas:
 *   1. fallback ao vivo (`v63/fundo.js`) quando o vídeo não toca;
 *   2. MATRIZ do próprio vídeo `static/v63/fluxo_*.mp4` — `tools/v63_render_fitas.js` chama esta
 *      mesma função quadro a quadro e o ffmpeg codifica. Por isso ela é PERIÓDICA: todo termo de
 *      tempo é `fase × inteiro`, com fase = 2π·t/PERIODO — o quadro PERIODO é idêntico ao quadro 0 e
 *      o `<video loop>` emenda sem costura.
 *
 * Custo: ~60 fios × 48 segmentos = ~2,9 mil `lineTo` por quadro, nenhum `shadowBlur` (o brilho é um
 * traço largo de alfa baixo, não um filtro). Medido no Chromium da VM (2 vCPU ARM, sob carga): ~3,4 ms/quadro a 1280×720 — o ao vivo roda
 * a meia resolução e 30 fps (≈ 1 ms), e só quando o vídeo não toca.
 */
export const PERIODO = 12;          // segundos
const SEG = 48;
/* cada feixe: altura-base (fração), amplitude da onda, largura da fita aberta, nº de fios, inclinação,
   cores da ponta à ponta, frequência temporal (inteira!), fase própria */
const FEIXES = [
  {y0: .74, amp: .24, larg: .44, n: 46, incl: -.62, c: ['#1D5BFF', '#38D3FF'], k: 1, f: 0.0, ond: .85},
  {y0: .40, amp: .16, larg: .24, n: 26, incl: -.30, c: ['#6FA8FF', '#1D5BFF'], k: 1, f: 2.1, ond: 1.05},
  {y0: .96, amp: .10, larg: .16, n: 16, incl: -.70, c: ['#38D3FF', '#6FA8FF'], k: 2, f: 4.0, ond: 1.30},
];

export function desenharFitas(ctx, w, h, t, dens = 1) {
  const fase = 2 * Math.PI * ((t % PERIODO) / PERIODO);
  ctx.clearRect(0, 0, w, h);
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  const retrato = h > w * 1.1;
  /* no retrato a fita atravessa na diagonal (de baixo-esquerda a cima-direita), como no Relay mobile */
  const H = retrato ? h * .62 : h, oy = retrato ? h * .22 : 0;
  /* luz ambiente: um halo largo que deriva devagar (um `fillRect` com gradiente radial por quadro) */
  const hx = w * (.66 + .08 * Math.sin(fase)), hy = h * (.58 + .06 * Math.cos(fase)), hr = Math.max(w, h) * .55;
  const halo = ctx.createRadialGradient(hx, hy, 0, hx, hy, hr);
  halo.addColorStop(0, 'rgba(111,168,255,.16)'); halo.addColorStop(.5, 'rgba(56,211,255,.05)'); halo.addColorStop(1, 'rgba(56,211,255,0)');
  ctx.fillStyle = halo; ctx.fillRect(0, 0, w, h);
  for (const fx of FEIXES) {
    const n = Math.max(6, Math.round(fx.n * dens));
    const g = ctx.createLinearGradient(0, 0, w, 0);
    g.addColorStop(0, fx.c[0]); g.addColorStop(.55, fx.c[1]); g.addColorStop(1, fx.c[0]);
    ctx.strokeStyle = g;
    for (let i = 0; i < n; i++) {
      const u = i / (n - 1) - .5;                         // -0,5 … 0,5 através da fita
      _curva(ctx, w, H, oy, fx, fase, u, i, retrato);
      const borda = 1 - Math.abs(u) * 2;                  // fios do miolo mais acesos
      ctx.globalAlpha = .07 + .5 * borda * borda * borda;
      ctx.lineWidth = i % 7 === 3 ? 1.5 : .8;
      ctx.stroke();
    }
    /* o filamento: o fio do eixo, com halo ciano (traço largo de alfa baixo — sem shadowBlur) */
    _curva(ctx, w, H, oy, fx, fase, 0, 0, retrato);
    ctx.globalAlpha = .10; ctx.strokeStyle = '#38D3FF'; ctx.lineWidth = 9; ctx.stroke();
    ctx.globalAlpha = .9; ctx.strokeStyle = g; ctx.lineWidth = 1.6; ctx.stroke();
    ctx.globalAlpha = 1;
  }
}

function _curva(ctx, w, H, oy, fx, fase, u, i, retrato) {
  ctx.beginPath();
  for (let s = 0; s <= SEG; s++) {
    const xn = s / SEG;
    const x = -.08 * w + xn * 1.16 * w;
    /* a "dobra" da seda: a largura da fita oscila ao longo do x — onde passa por zero os fios se
       cruzam e o feixe acende sozinho (sobreposição), sem custo de brilho */
    const dobra = Math.sin(xn * Math.PI * 1.6 + fase * fx.k + fx.f);
    const eixo = fx.y0 + fx.amp * Math.sin(xn * Math.PI * fx.ond + fase * fx.k + fx.f * .7)
               + fx.incl * (xn - .5) * (retrato ? 1.5 : 1);
    const fio = Math.sin(xn * 9 + fase * 2 + i * .7) * .004;
    const y = oy + H * (eixo + u * fx.larg * dobra + fio);
    s ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }
}
