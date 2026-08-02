/* A PARALAXE DO PONTEIRO — uma FOLHA, e ela existe para quebrar um ciclo.
 *
 * A posição normalizada do mouse é escrita por um ouvinte da sequência de boot (`cenaPonteiro`) e
 * lida por quem desenha por quadro: hoje a malha de rede do fundo, amanhã qualquer outra peça da
 * cena. Enquanto viveu em `cena/index.js`, o corte da v59 (§6.2-B) criou exatamente o ciclo que
 * esta casa já pagou uma vez: `index.js` reexportava de `fundo.js` e `fundo.js` importava as duas
 * variáveis de `index.js`.
 *
 * ESM resolve ciclo e o bundle não reclama — e é por isso que o ciclo é perigoso: ele não quebra
 * nada hoje, e amarra os dois arquivos para sempre. Com a folha, os dois lados leem daqui e
 * nenhum enxerga o outro. É o mesmo remédio de `capacidade/estado.js`, pela mesma razão escrita lá.
 *
 * Este arquivo NÃO importa nada. Se um dia importar, deixou de ser folha e o ciclo volta.
 *
 * Sem efeito de topo.
 */
export let _ckMX = .5, _ckMY = .5;
export function cenaPonteiro(x, y) { _ckMX = x; _ckMY = y; }
