/* O10.7 · `h3-js` só serve às camadas hexagonais do three-globe (hexBin/hexPolygons), que o painel não usa: fora do
   bundle tardio (−208 KB). Se alguém ligar a camada, o erro diz o porquê. */
const nao = () => { throw new Error('h3-js fora do bundle do globo (O10.7): camadas hexagonais não são usadas'); };
export const latLngToCell = nao, cellToLatLng = nao, cellToBoundary = nao, polygonToCells = nao;
