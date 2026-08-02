/* ONDE O PAINEL ESTÁ — a esfera e a aba correntes, e nada mais.
 *
 * Duas variáveis, e elas são lidas por quase tudo: o roteador decide o que montar, a barra de abas
 * decide o que acender, a CENA decide qual nebulosa tocar e de que cor tingir a malha, e ~15
 * handlers inline as ESCREVEM direto de dentro do HTML
 * (`onclick="fecharDossie();esfera='geral';aba='g_acoes';…"`).
 *
 * POR QUE ELAS PRECISAM DE MÓDULO PRÓPRIO, e é a mesma lição que `capacidade/estado.js` ensinou:
 * enquanto moravam no entrypoint, a cena as lia como global e o IIFE do bundle as fechou —
 * `esfera is not defined` no primeiro quadro, pego pelo `boot_check`. Uma FOLHA que ninguém
 * importa e que todos importam é o que quebra o círculo entre "quem navega" e "quem desenha".
 *
 * `export let` dá binding VIVO: os ~40 pontos que leem continuam iguais. A escrita passa por
 * função porque um módulo não pode atribuir à variável importada — e isso é garantia, não
 * cerimônia: o compilador aponta qualquer tentativa de mexer em "onde estamos" de um lugar que
 * não é o roteador.
 */

export let esfera = 'inicio';
export let aba = 'i_cockpit';

/** Único caminho de escrita. Chamado pelo roteador e pela ponte (que serve os handlers inline). */
export function setEsfera(v) { esfera = v; }
export function setAba(v) { aba = v; }
