/* O MODO SÓBRIO — o painel mede se esta máquina entrega quadro, e recua se não entrega.
 *
 * POR QUE MEDIDO E NÃO ADIVINHADO. Sniff de user-agent, contagem de núcleos e `deviceMemory` erram
 * feio (a VM tem 11 GB e 2 vCPU sem GPU; um celular tem 8 núcleos e compõe melhor). O que importa
 * é uma coisa só: esta máquina, agora, entrega quadro? Então conta quadro.
 *
 * Roda DEPOIS da intro — a intro é o pico de carga e mediria o transiente, não o regime — e amostra
 * 1 s. Não fica em laço: só remede quando a aba volta do segundo plano.
 *
 * v52 · MEDIR ABA OCULTA MEDE O NAVEGADOR, NÃO A MÁQUINA. Com `document.hidden` o Chrome congela o
 * rAF: o passo roda UMA vez, 60 s depois, e a conta dava 1·1000/60000 ≈ 0 fps. Quem abrisse o
 * painel em aba de segundo plano (link em nova aba, restaurar sessão) caía em modo sóbrio PARA
 * SEMPRE — medido no navegador do it-campo: hidden=true, _jfnFps=0, _sobrio=true, mesa em branco.
 * Agora: não mede oculto, remede ao voltar, e o sóbrio é REVERSÍVEL.
 *
 * Este módulo recebe os três vídeos por PARÂMETRO em vez de importá-los. Sem isso ele importaria
 * `cena/video.js`, que importa a bandeira daqui — ciclo. A bandeira mora na folha
 * `capacidade/estado.js` justamente para os dois lados a lerem sem se enxergarem.
 */
import {$} from '../nucleo/dom.js';
import {_redMotion, _sobrio, _setSobrio} from './estado.js';

let _reagir = () => {};     // o que reavaliar quando a sobriedade muda (os vídeos da cena)
let _medirArmado = false;

/** Aviso VISÍVEL: degradação calada é como ninguém descobre que o painel não é o desenhado. */
function _sobrioAviso(fps) {
  const alvo = document.querySelector('.htop') || document.querySelector('header');
  if (!alvo) return;
  const s = $('modo-sobrio') || document.createElement('span'); s.id = 'modo-sobrio';
  s.textContent = 'modo sóbrio · ' + Math.round(fps) + ' fps';
  s.title = 'Esta máquina entregou ' + Math.round(fps) + ' quadros por segundo com a tela parada.\n'
          + 'As animações que exigem repintura por quadro foram desligadas para o painel ficar '
          + 'legível. O dado e as funções são os mesmos.';
  if (!s.isConnected) alvo.appendChild(s);
}

function _sobrioAplicar(lig, fps) {
  if (_sobrio === lig) return;
  _setSobrio(lig);
  document.body.classList.toggle('fps-baixo', lig);
  if (lig) _sobrioAviso(fps); else { const s = $('modo-sobrio'); if (s) s.remove(); }
  /* v51: a nebulosa viva pode já estar tocando quando a medição fecha (ela acende no boot, isto
     roda a 2,6 s). Reentrar nela com `_sobrio` ligado pausa o vídeo e devolve o JPG — sem isto o
     modo sóbrio desligava tudo MENOS o item mais caro da tela. Ao SAIR do sóbrio a mesma chamada
     devolve o vídeo. Idem para o núcleo (v53) e o holograma do Estado (v55). */
  _reagir();
  /* Os laços dos canvas param quando `_sobrio` liga, e cada um já tem seu ouvinte de
     `visibilitychange` que cancela e repinta — reemitir o evento é o gancho que JÁ EXISTE para
     "reavalie e volte a desenhar", em vez de espalhar uma segunda porta de retomada por canvas. */
  document.dispatchEvent(new Event('visibilitychange'));
}

/** Remede na volta da aba. Um ouvinte só — não empilha. */
function _medirQuandoVisivel() {
  if (_medirArmado) return;
  _medirArmado = true;
  const h = () => {
    if (document.hidden) return;
    document.removeEventListener('visibilitychange', h); _medirArmado = false;
    setTimeout(_medirFps, 600);            // folga: o 1º quadro depois da volta é o mais caro
  };
  document.addEventListener('visibilitychange', h);
}

export function _medirFps() {
  if (_redMotion) return;                  // quem já pediu menos movimento não precisa da medição
  if (document.hidden) { _medirQuandoVisivel(); return; }
  let n = 0; const t0 = performance.now();
  const passo = () => {
    if (document.hidden) { _medirQuandoVisivel(); return; }   // aba saiu de foco: amostra morta
    n++;
    const dt = performance.now() - t0;
    if (dt < 1000) { requestAnimationFrame(passo); return; }
    /* Janela de 1 s que levou mais de 3 s = o navegador estrangulou o rAF (aba oculta, janela
       minimizada, economia de energia). Isso não é a máquina; não condena ninguém. */
    if (dt > 3000) { _medirQuandoVisivel(); return; }
    const fps = n * 1000 / dt;
    window._jfnFps = Math.round(fps);
    if (fps < 24) _sobrioAplicar(true, fps);
    else { _sobrioAplicar(false, fps); _medirQuandoVisivel(); }  // segue vigiando: máquina piora também
  };
  requestAnimationFrame(passo);
}

/** Registra o que reavaliar quando a sobriedade vira — os três vídeos da cena. */
export function sobrioAoMudar(fn) { if (typeof fn === 'function') _reagir = fn; }
