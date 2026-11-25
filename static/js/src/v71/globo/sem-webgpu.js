/* O10.7 · o three-globe importa `three/webgpu` e `three/tsl` só para a camada de mapa de calor (heatmapsData), que o
   painel não usa. Sem este calço o bundle tardio levaria o renderizador WebGPU inteiro. Se alguém ligar a camada,
   o erro diz o porquê em vez de falhar calado. */
const nao = () => { throw new Error('three/webgpu fora do bundle do globo (O10.7): heatmapsData não é usado no painel'); };
export class WebGPURenderer { constructor() { nao(); } }
export class StorageInstancedBufferAttribute { constructor() { nao(); } }
