/* v68 · CINE 3D — vídeos renderizados no Blender (it-campo, EEVEE) com os DADOS REAIS do sistema, sem texto
 * queimado: todo rótulo e número fica em código por cima (`tools/v68_blender_cenas.py`).
 *
 *   mapa3d     municípios do RJ extrudados por √(valor contratado vigente atribuído), topo da aba Mapa;
 *   galaxia3d  voo pela galáxia de casos até o fornecedor crítico, enquanto a página /galaxia carrega.
 *
 * Variante por tela: retrato (≤ 4:5) leva `_m` (vertical), o resto a paisagem. Fontes AV1 → VP9 → H.264.
 * Reduzir movimento / economia de dados → só o pôster. O vídeo nunca baixa antes de ser preciso
 * (`preload="none"` até tocar).
 */
const BASE = '/static/assets/v68/';

export const cineRetrato = () => matchMedia('(max-aspect-ratio: 4/5)').matches;
export const cineSoPoster = () => matchMedia('(prefers-reduced-motion: reduce)').matches
  || !!(navigator.connection && navigator.connection.saveData);

/** `<video>` mudo/inline com as 3 fontes e o pôster (AVIF/WebP pelo `<picture>` fica com quem chama). */
export function cineVideo(nome, {loop = false} = {}) {
  const b = BASE + nome + (cineRetrato() ? '_m' : '');
  const v = document.createElement('video');
  v.muted = true; v.loop = loop; v.playsInline = true; v.preload = 'none';
  v.setAttribute('muted', ''); v.setAttribute('playsinline', ''); v.setAttribute('aria-hidden', 'true');
  v.poster = b + '.webp';
  v.innerHTML = `<source src="${b}.av1.mp4" type='video/mp4; codecs="av01.0.09M.08"'>`
    + `<source src="${b}.webm" type='video/webm; codecs="vp9"'><source src="${b}.mp4" type="video/mp4">`;
  return v;
}

/** Toca só enquanto ≥ 35 % do elemento está visível e a aba está à vista; pausa no resto. Devolve o desligar. */
export function cineSoVisivel(v, el = v) {
  if (cineSoPoster() || typeof IntersectionObserver !== 'function') return () => {};
  let vis = false;
  const aplica = () => {
    if (vis && !document.hidden) { v.preload = 'auto'; const p = v.play(); if (p && p.catch) p.catch(() => {}); }
    else v.pause();
  };
  const io = new IntersectionObserver(es => { for (const e of es) vis = e.isIntersecting; aplica(); }, {threshold: .35});
  io.observe(el); document.addEventListener('visibilitychange', aplica);
  return () => { io.disconnect(); document.removeEventListener('visibilitychange', aplica); v.pause(); };
}
