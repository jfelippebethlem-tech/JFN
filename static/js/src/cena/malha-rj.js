/* A MALHA DO ESTADO — o carregador do território do RJ (IBGE, estado 33).
 *
 * Saiu de `cena/index.js` na v59 (§6.2-B do PAINEL-v58). É a folha da cena: não importa nenhum
 * outro módulo de cena. O consumidor (`rjbgStart`, em `cena/fundo.js`) importa daqui em vez de
 * dividir um escopo. (O traçador `_rjBuild` saiu com o portal de ignição; a mesa de vigília, outra
 * consumidora, saiu no untangle de 20/11/2026.)
 *
 * UM SÓ FETCH SERVE TODOS. `_rjCarregar` guarda os pedidos numa fila enquanto o script de 21 KB
 * está a caminho e chama todo mundo quando ele chega — se cada consumidor buscasse por conta,
 * seriam vários downloads da mesma malha no primeiro segundo do painel.
 *
 * `_rjCbs`/`_rjLoading` moram no topo porque o `rjbgStart` chama `_rjCarregar` ANTES da definição
 * dela na ordem do arquivo original; com o módulo isso deixa de importar (declaração de função
 * sobe), mas a fila continua sendo estado de módulo e é aqui que ela pertence.
 *
 * Sem efeito de topo.
 */

var _rjCbs=[],_rjLoading=false;

export function _rjCarregar(cb){
  if(window.RJ_MALHA){try{cb();}catch(_){}return;}
  _rjCbs.push(cb);
  if(_rjLoading)return;
  _rjLoading=true;
  const s=document.createElement('script');
  s.src='/static/assets/rj-malha.js?v=c6127f36';s.async=true;
  s.onload=()=>{const l=_rjCbs.slice();_rjCbs.length=0;
    /* era `catch(_){}` — um catch vazio. Se o desenho da malha falhasse, a
       falha sumia sem rastro e o mapa ficava vazio sem nada no console.  */
    l.forEach(fn=>{try{fn();}catch(e){console.warn('[rj] callback da malha falhou:',e);}});};
  s.onerror=()=>{_rjLoading=false;};             // sem malha o painel segue igual
  document.head.appendChild(s);
}


