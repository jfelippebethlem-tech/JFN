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

/** Único caminho de escrita da bandeira de sobriedade. Chamado só por `capacidade/sobrio.js`. */
export function _setSobrio(v) { _sobrio = !!v; }
