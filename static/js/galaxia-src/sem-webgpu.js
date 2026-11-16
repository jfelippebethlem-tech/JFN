/* `three-render-objects` importa `WebGPURenderer` de 'three/webgpu' (~600 KB com o TSL) só para o caso
   `useWebGPU: true`, que a galáxia não usa. O build:galaxia aponta 'three/webgpu' para este arquivo
   (`--alias`), e o bundle cai de ~1,5 MB para ~0,9 MB. Se alguém ligar o WebGPU, falha alto, não calado. */
export class WebGPURenderer {
  constructor() { throw new Error('WebGPU desligado no bundle da galáxia (ver static/js/galaxia-src/sem-webgpu.js)'); }
}
