/* CAPACIDADE — as duas verdades sobre o que esta maquina aguenta, num lugar só.
 *
 * Elas são DIFERENTES e a distinção não é acadêmica:
 *
 *   `_redMotion`  é PREFERÊNCIA DECLARADA. O usuário marcou "reduzir movimento" no sistema
 *                 operacional. Não se discute, não se mede, não se reverte por FPS bom.
 *   `_sobrio`     é CAPACIDADE MEDIDA. O painel contou os quadros, não coube, e recuou. Nasceu
 *                 depois de a VM cair para 1-2 FPS com 57 animações infinitas simultâneas.
 *
 * POR QUE ESTE MÓDULO É UMA FOLHA — não importa NADA. É o que quebra o ciclo: `cena/*` precisa
 * ler `_sobrio` para parar de agendar quadro, e `capacidade/sobrio.js`, que ESCREVE `_sobrio`,
 * precisa de `cena/video.js` para pausar os vídeos. Se a bandeira morasse junto com quem a
 * escreve, cena e capacidade se importariam em círculo. Morando aqui, os dois importam a folha.
 *
 * A ESCRITA PASSA POR FUNÇÃO de propósito. `export let` dá binding VIVO para quem lê — os ~40
 * pontos do painel que consultam `_sobrio` continuam vendo o valor novo sem nenhuma mudança. Mas
 * um módulo não pode atribuir à variável importada de outro; quem escreve chama `_setSobrio`.
 * Isso é uma garantia, não uma cerimônia: o compilador passa a apontar qualquer tentativa de
 * escrever a bandeira de fora do único lugar que tem o direito de decidir.
 */

/* v45: vive no TOPO. Estava declarado 2.800 linhas abaixo e o boot (nucleoStart, canvas do
   núcleo) o lia antes — ReferenceError de TDZ que matava a montagem do núcleo em toda carga. */
export let _redMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

/* v50: capacidade MEDIDA (≠ _redMotion, que é preferência declarada). `_medirFps` liga isto
   quando a máquina não entrega quadro. O CSS do modo sóbrio usa `animation:none`, que mata
   @keyframes e NÃO toca requestAnimationFrame — sem este flag os canvas de tela cheia (#rjbg,
   #netbg, este último O(n²) sobre até 76 pontos) seguiam desenhando a custo cheio depois do
   recuo: o painel media o orçamento, dizia "não cabe", e gastava igual. */
export let _sobrio = false;

/* v60 CLAREZA (2026-11-10): a flag que o script inline do <head> grava em `<html class="v60">`
   ANTES deste bundle. É constante por carga de página: ligar/desligar é `?v60=1` / `?v60=0`, que
   recarrega. Mora nesta folha pelo mesmo motivo das outras duas — `cena/*` e `ui/*` a leem para
   NÃO iniciar os laços das camadas ambientes que o v60 aposentou. */
export const _v60 = document.documentElement.classList.contains('v60');
/* AS TRÊS BANDEIRAS (`_v60`, `_v61`, `_v63`) SÃO CONSTANTES VERDADEIRAS: o <head> as liga em toda carga
   (decisão do dono, 11/11 e 17/11/2026). Os ramos "desligado" saíram do painel (untangle 20/11); os
   leitores que sobraram são blocos mortos que um teste fixa pelo texto — `nebulaViva`, `rjbgStart`/
   `netbgStart`, a órbita de `cena/energia.js` — e a mesa do núcleo (`cena/index.js::trilhos`). Ver
   `docs/untangle/painel.md` §9.6. Bandeira nova não entra aqui: versão que vira padrão perde o `if`. */

/* v61 TRON CLARO (2026-11-11): o tema claro, sempre ligado (o script do <head> põe `v61` em toda
   carga; a volta ao escuro saiu em 11/11 e o resto do tema escuro foi apagado na v63, 17/11). */
export const _v61 = document.documentElement.classList.contains('v61');

/** Único caminho de escrita da bandeira de sobriedade. Chamado só por `capacidade/sobrio.js`. */
export function _setSobrio(v) { _sobrio = !!v; }

/* v63 FLUXO CLARO (2026-11-17): a linguagem da landing "Relay" traduzida para branco + azul — fundo de
   fitas de luz, título com palavra em serifa itálica, grafo de fluxo, transição de clique que enche a
   tela. A classe `v63` nasce SEMPRE no script do <head> (padrão desde 17/11/2026), constante por carga. */
export const _v63 = document.documentElement.classList.contains('v63');
