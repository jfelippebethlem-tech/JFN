/* A ABERTURA DO PAINEL — ponto de entrada mantido com o nome antigo (`portalStart`) para que nenhum
 * chamador mude (`entrada.js` → reexport em `cena/index.js`).
 *
 * v63 (17/11/2026, "remover de vez o tema dark"): saiu o PORTAL DE IGNIÇÃO em WebGL — campo de estrelas
 * sobre fundo escuro, reator de núcleo laranja, malha do RJ revelada pela varredura. Ele estava morto
 * desde a v61 (o tema claro é sempre-ligado e desviava para a abertura clara de `cena/abertura.js`),
 * mas o shader, o `<video>` escuro e o `#portal` do HTML continuavam no código. Fica só a abertura clara.
 */
import {aberturaStart} from './abertura.js';

export function portalStart() {
  aberturaStart(null);
}
