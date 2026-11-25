# Licenças das dependências JavaScript empacotadas (SBOM do front)

> Escrito à mão na O10.7 (25/11/2026) a partir do `package-lock.json` e do *metafile* do esbuild do bundle do globo.
> O SBOM Python (`LICENCAS.md`, `sbom-python.cdx.json`) não cobre o JS. Toda biblioteca nova do painel entra aqui
> com a licença conferida no arquivo `LICENSE` do pacote instalado (`node_modules/<pacote>/LICENSE`), não só no
> campo `license` do `package.json`.

## 1. Bundle tardio do globo — `static/js/globo.bundle.js` (O10.7)

- **Entrada:** `static/js/src/v71/globo/cena.js` · **build:** `npm run build:globo` (esbuild, ESM, minificado,
  `--legal-comments=eof`: os avisos de licença das bibliotecas ficam no fim do arquivo).
- **Carregamento:** só por `import()` quando a pessoa liga "Globo" na aba Orçamento por órgão; nunca no boot.
- **Fora do bundle por calço** (camadas do three-globe que o painel não usa): `three/webgpu` e `three/tsl`
  (`sem-webgpu.js`, camada de mapa de calor) e `h3-js` (`sem-h3.js`, camadas hexagonais). Ligar essas camadas
  lança erro explícito.
- **Dados:** `world-atlas/countries-110m.json` (contornos dos países). Os polígonos vêm do Natural Earth (domínio
  público); o pacote é ISC (Mike Bostock).
- **Conferência de 25/11/2026:** nenhum pacote AGPL/GPL/LGPL/SSPL; todos MIT, ISC ou Unlicense. Nenhuma linha do
  Git City (AGPL-3.0) — regra do §18 do plano mestre v2.

| Pacote | Versão | Licença | Arquivo conferido | Origem | KB no bundle |
|---|---|---|---|---|---:|
| @turf/boolean-point-in-polygon | 7.4.0 | MIT | LICENSE | https://github.com/Turfjs/turf | 0,4 |
| @turf/invariant | 7.4.0 | MIT | LICENSE | https://github.com/Turfjs/turf | 0,4 |
| @tweenjs/tween.js | 25.0.0 | MIT | LICENSE | https://github.com/tweenjs/tween.js | 12,3 |
| accessor-fn | 1.5.3 | MIT | LICENSE | https://github.com/vasturiano/accessor-fn | 0,1 |
| d3-array | 3.2.5 | ISC | LICENSE | https://github.com/d3/d3-array | 4,5 |
| d3-color | 3.1.1 | ISC | LICENSE | https://github.com/d3/d3-color | 10,0 |
| d3-delaunay | 6.0.6 | ISC | LICENSE | https://github.com/d3/d3-delaunay | 18,9 |
| d3-format | 3.1.3 | ISC | LICENSE | https://github.com/d3/d3-format | 4,8 |
| d3-geo | 3.1.2 | ISC | LICENSE | https://github.com/d3/d3-geo | 24,9 |
| d3-geo-voronoi | 2.1.0 | ISC | LICENSE | https://github.com/Fil/d3-geo-voronoi | 6,9 |
| d3-interpolate | 3.0.2 | ISC | LICENSE | https://github.com/d3/d3-interpolate | 6,2 |
| d3-octree | 1.1.0 | MIT | LICENSE | https://github.com/vasturiano/d3-octree | 6,9 |
| d3-scale | 4.0.3 | ISC | LICENSE | https://github.com/d3/d3-scale | 3,3 |
| d3-scale-chromatic | 3.1.1 | ISC | LICENSE | https://github.com/d3/d3-scale-chromatic | 17,0 |
| data-bind-mapper | 1.0.3 | MIT | LICENSE | https://github.com/vasturiano/data-bind-mapper | 3,7 |
| delaunator | 5.1.0 | ISC | LICENSE | https://github.com/mapbox/delaunator | 5,1 |
| earcut | 3.2.4 | ISC | LICENSE | https://github.com/mapbox/earcut | 7,4 |
| frame-ticker | 1.0.3 | MIT | LICENSE.md | https://github.com/zeh/frame-ticker | 4,7 |
| index-array-by | 1.4.2 | MIT | LICENSE | https://github.com/vasturiano/index-array-by | 3,2 |
| kapsule | 1.16.3 | MIT | LICENSE | https://github.com/vasturiano/kapsule | 2,8 |
| lodash-es | 4.18.1 | MIT | LICENSE | https://github.com/lodash/lodash | 2,4 |
| point-in-polygon-hao | 1.2.4 | MIT | LICENSE | https://github.com/rowanwins/point-in-polygon-hao | 0,5 |
| robust-predicates | 3.0.3 | Unlicense | LICENSE | https://github.com/mourner/robust-predicates | 3,4 |
| three | 0.187.0 | MIT | LICENSE | https://github.com/mrdoob/three.js | 636,6 |
| three-conic-polygon-geometry | 2.1.5 | MIT | LICENSE | https://github.com/vasturiano/three-conic-polygon-geometry | 3,6 |
| three-geojson-geometry | 2.1.2 | MIT | LICENSE | https://github.com/vasturiano/three-geojson-geometry | 2,2 |
| three-globe | 2.45.6 | MIT | LICENSE | https://github.com/vasturiano/three-globe | 114,2 |
| three-slippy-map-globe | 1.0.6 | MIT | LICENSE | https://github.com/vasturiano/three-slippy-map-globe | 10,2 |
| tinycolor2 | 1.6.0 | MIT | LICENSE | https://github.com/bgrins/TinyColor | 15,1 |
| topojson-client | 3.1.0 | ISC | LICENSE | https://github.com/topojson/topojson-client | 1,5 |
| world-atlas | 2.0.2 | ISC | LICENSE | https://github.com/topojson/world-atlas | 103,5 |

## 2. Bundle do painel — `static/js/painel.bundle.js`

A O10.7 acrescenta ao bundle do painel só código próprio (`static/js/src/v71/globo/{index,dados,parado}.js`) e usa
`d3-geo` 3.1.2 (ISC) e `topojson-client` 3.1.0 (ISC), que o mapa do Território já empacotava. O inventário
completo das dependências deste bundle fica para a O9.3.
