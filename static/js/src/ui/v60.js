/* v60 CLAREZA — os ajustes de DOM que só existem com `html.v60`.
 *
 * O CSS do v60 mora num estrato só (`static/css/src/99z-v60-clareza.css`); este módulo é o par dele
 * no JS: tudo o que o CSS sozinho não alcança (texto em caixa alta na origem, gatilho novo no
 * cabeçalho, estado recolhido do holofeed). Uma função de entrada, `v60Boot`, chamada UMA vez no
 * início da sequência de boot de `entrada.js` — e que não faz nada sem a classe. Sem a classe o
 * painel é o anterior, byte a byte no comportamento.
 *
 * Não tem efeito de topo (o boot é ordenado pelo entrypoint, não pelo import).
 */
import {$} from '../nucleo/dom.js';
import {_v60} from '../capacidade/estado.js';

export function v60Boot() {
  if (!_v60) return;
  /* rótulo do cabeçalho: sentence case na ORIGEM (o CSS não baixa "RJ"/"SIAFE" sem estragar a sigla) */
  const hs = $('hsub'); if (hs) hs.textContent = 'Central de inteligência · RJ';
}
