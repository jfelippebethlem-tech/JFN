/* AS LINHAS DE ENERGIA DA ÓRBITA — o cockpit vira centro de gravidade (§6.3-b do PAINEL-v58).
 *
 * A mesa de vigília era um bloco empilhado entre o herói e os oito instrumentos. Empilhada, a
 * peça central da tela lê como mais uma faixa da página, e os cartões abaixo dela leem como uma
 * lista sem relação com o que a mesa mostra — quando são exatamente as leituras que chegam POR
 * ela. Em órbita, a relação vira geometria: o núcleo no meio, quatro instrumentos de cada lado, e
 * um fio ligando cada instrumento ao núcleo.
 *
 * ═══ O PACOTE É O EVENTO, E ISSO NÃO É DETALHE DE IMPLEMENTAÇÃO ═══
 *
 * O plano pedia "pacotes viajando na taxa real de eventos". Há duas formas de fazer isso, e só uma
 * é honesta nesta casa:
 *   · ler `eventosPorMinuto` e emitir pacotes NAQUELA cadência — um gerador que produz um
 *     movimento parecido com a média. É série sintética com outro nome, e o PRODUCT.md proíbe.
 *   · emitir UM pacote por evento REAL, na linha do domínio que o produziu. A taxa então não é
 *     imitada: ela É a taxa, porque cada traço na tela corresponde a uma linha que entrou no
 *     banco. Quem olha por dez segundos e conta três pacotes contou três eventos.
 * É a segunda. `energiaPacote()` é chamada do mesmo gancho do barramento que já alimenta a onda
 * do piso, e usa a MESMA tabela de domínio e de cor (`EV_DOMINIO`/`EV_COR`, importadas) — se as
 * duas divergissem, a tela contaria duas histórias sobre o mesmo evento.
 *
 * E a consequência que fecha a regra: **barramento calado = nada se move.** Sem evento não há
 * pacote, e o desenho fica sendo os fios parados. Silêncio que parece silêncio é a mesma lei do
 * deck da Consciência — um painel que inventa movimento quando não há acontecimento é protetor de
 * tela, não instrumento.
 *
 * ═══ CUSTO (2 vCPU, 19-29 FPS) ═══
 *
 * O laço de animação SÓ EXISTE ENQUANTO HÁ PACOTE VIVO. Sem pacote, desenha-se o quadro parado
 * uma vez e o `requestAnimationFrame` para — não fica um RAF ocioso girando atrás de uma tela
 * silenciosa, que é o custo que a VM não tem para dar. É a mesma conta do `setInterval` da
 * Consciência, que só corre com o deck aberto.
 *
 * Os dois pisos: `prefers-reduced-motion` deixa os fios parados (a estrutura continua sendo
 * informação — ela diz o que se liga a quê); modo sóbrio apaga o canvas inteiro, porque aí a
 * máquina já não estava dando conta do que existia antes desta camada.
 */
import {$} from '../nucleo/dom.js';
import {_redMotion, _sobrio} from '../capacidade/estado.js';
import {EV_COR, EV_DOMINIO} from './index.js';

let _raf = 0;
let _pacotes = [];        // {i: índice da linha, p: 0..1, c: 'r,g,b'}
let _linhas = [];         // {x0,y0,x1,y1, id}
let _cv = null, _cx = null, _W = 0, _H = 0, _dpr = 1;

/* Teto de pacotes vivos. Uma rajada do sweep despeja dezenas de eventos no mesmo segundo, e sem
   teto o fio vira um enxame em que não se conta mais nada — o excesso destrói justamente a
   propriedade que justifica a peça (poder contar). Os mais VELHOS saem: o que acabou de chegar é
   a informação nova. */
const TETO = 30;
const DUR = 1500;         // ms que um pacote leva do instrumento ao núcleo

/** Mede a geometria da órbita. Uma leitura só, em bloco, e nenhuma escrita no meio. */
function _medir() {
  const box = $('ck-orbita'), nuc = $('ck-nucleo'), g = $('ck-grid');
  _cv = $('ck-energia');
  if (!box || !nuc || !g || !_cv) return false;
  const rb = box.getBoundingClientRect();
  /* Abaixo de 1100px a órbita não existe: o CSS mantém a pilha de sempre e os cartões ficam
     EMBAIXO do núcleo. Fio ligando um cartão ao que está acima dele não desenha relação nenhuma,
     desenha um risco vertical. Nessa largura a camada simplesmente não entra. */
  if (rb.width < 1100) return false;
  const rn = nuc.getBoundingClientRect();
  const cx = rn.left - rb.left + rn.width / 2, cy = rn.top - rb.top + rn.height / 2;
  _linhas = [...g.children].map(el => {
    const r = el.getBoundingClientRect();
    const esq = r.left - rb.left + r.width / 2 < cx;
    return {
      id: (el.id || '').replace('cki-', ''),
      // sai pela borda VOLTADA para o núcleo, não pelo centro do cartão: fio nascendo de dentro
      // do texto atravessa o número que o cartão existe para mostrar.
      x0: (esq ? r.right : r.left) - rb.left,
      y0: r.top - rb.top + r.height / 2,
      x1: cx, y1: cy,
    };
  });
  _W = Math.round(rb.width); _H = Math.round(rb.height);
  _dpr = Math.min(2, window.devicePixelRatio || 1);
  _cv.width = _W * _dpr; _cv.height = _H * _dpr;
  _cv.style.width = _W + 'px'; _cv.style.height = _H + 'px';
  _cx = _cv.getContext('2d');
  _cx.setTransform(_dpr, 0, 0, _dpr, 0, 0);
  return _linhas.length > 0;
}

/* A curva. Um fio reto ligaria os pontos e leria como tabela; a curva com o controle deslocado
   para o lado do núcleo lê como cabo, que é o que ela representa. O deslocamento é proporcional à
   distância horizontal, então cartões mais afastados curvam mais — o feixe abre em leque em vez
   de virar oito paralelas. */
const _ctrl = L => ({x: L.x0 + (L.x1 - L.x0) * 0.62, y: L.y0});

function _ponto(L, t) {
  const c = _ctrl(L), u = 1 - t;
  return {x: u * u * L.x0 + 2 * u * t * c.x + t * t * L.x1,
          y: u * u * L.y0 + 2 * u * t * c.y + t * t * L.y1};
}

function _desenhar(agora) {
  if (!_cx) return;
  _cx.clearRect(0, 0, _W, _H);
  for (const L of _linhas) {
    const c = _ctrl(L);
    _cx.strokeStyle = 'rgba(150,190,225,.13)';
    _cx.lineWidth = 1;
    _cx.beginPath();
    _cx.moveTo(L.x0, L.y0);
    _cx.quadraticCurveTo(c.x, c.y, L.x1, L.y1);
    _cx.stroke();
  }
  if (_redMotion) { _raf = 0; return; }          // fios parados: a estrutura, sem o tráfego

  _pacotes = _pacotes.filter(p => agora - p.t0 < DUR);
  for (const p of _pacotes) {
    const L = _linhas[p.i]; if (!L) continue;
    const t = (agora - p.t0) / DUR;
    const q = _ponto(L, t);
    /* O pacote APAGA ao chegar, não some no meio: ele está entrando no núcleo, e a onda do piso
       (que o `nucleoPulse` dispara no mesmo evento) continua a história lá dentro. */
    const a = t < .12 ? t / .12 : (t > .82 ? (1 - t) / .18 : 1);
    const gr = _cx.createRadialGradient(q.x, q.y, 0, q.x, q.y, 9);
    gr.addColorStop(0, `rgba(${p.c},${(a * .95).toFixed(3)})`);
    gr.addColorStop(1, `rgba(${p.c},0)`);
    _cx.fillStyle = gr;
    _cx.beginPath(); _cx.arc(q.x, q.y, 9, 0, 6.283); _cx.fill();
  }
  /* AQUI está a economia: sem pacote vivo, o laço PARA. O quadro parado já está desenhado. */
  _raf = _pacotes.length ? requestAnimationFrame(_desenhar) : 0;
}

/** Liga a órbita. Chamada do `ckBoot`, depois de o `#ck-grid` estar preenchido. */
export function energiaLigar() {
  energiaParar();
  if (_sobrio) { const c = $('ck-energia'); if (c) c.hidden = true; return; }
  if (!_medir()) { const c = $('ck-energia'); if (c) c.hidden = true; return; }
  _cv.hidden = false;
  _desenhar(performance.now());
}

/** Solta o laço e ESQUECE A GEOMETRIA. Chamada ao sair do cockpit e antes de remedir.
 *
 *  Esquecer é a parte que importa, e o censo é quem a exigiu: numa primeira versão esta função só
 *  cancelava o quadro, e `_linhas`/`_cx` continuavam apontando para o canvas da tela ANTERIOR — que
 *  o `innerHTML` do `ir()` já tinha jogado fora. Um evento do barramento chegando depois disso
 *  passava na guarda (`_linhas.length` continuava 8), empilhava pacote e levantava um
 *  `requestAnimationFrame` para desenhar num canvas fora do documento: laço vivo, zero pixel na
 *  tela, custo real numa VM de 2 vCPU. Zerar aqui faz a guarda do `energiaPacote` voltar a
 *  significar "a órbita está na tela". */
export function energiaParar() {
  if (_raf) cancelAnimationFrame(_raf);
  _raf = 0; _pacotes = []; _linhas = []; _cx = null; _cv = null;
}

/** UM pacote por evento REAL do barramento, na linha do domínio que o produziu. */
export function energiaPacote(tipo) {
  if (_redMotion || _sobrio || !_linhas.length || !_cx) return;
  const alvo = EV_DOMINIO[tipo];
  const i = _linhas.findIndex(L => L.id === alvo);
  /* Evento de domínio que não tem instrumento na órbita NÃO vira pacote em linha qualquer. Pintar
     um fio que não é o dele diria ao auditor que a leitura veio de onde não veio — e é o tipo de
     mentira barata que este painel não comete nem na decoração. */
  if (i < 0) return;
  _pacotes.push({i, t0: performance.now(), c: EV_COR[tipo] || '95,217,255'});
  if (_pacotes.length > TETO) _pacotes.splice(0, _pacotes.length - TETO);
  if (!_raf) _raf = requestAnimationFrame(_desenhar);
}

/** Remede quando a janela muda de tamanho ou o modo sóbrio vira. */
export function energiaRever() {
  if (!$('ck-orbita')) return;
  energiaLigar();
}

/** O censo da órbita, para a sonda e o teste. Mesma razão do `revelacaoCenso()`: um laço de
 *  animação que NÃO roda não lança erro, não aparece no console e não muda contagem de teste —
 *  e este é o segundo lugar do painel onde isso poderia apodrecer calado. Só leitura. */
export const energiaCenso = () => ({
  linhas: _linhas.length,
  pacotes: _pacotes.length,
  laco: !!_raf,
  ligada: !!(_cv && !_cv.hidden),
});
