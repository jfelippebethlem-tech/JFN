"""v70 · alvos de clique do RELEVO (faixa de cinema do mapa) — contornos por município alinhados ao ÚLTIMO
quadro do vídeo `mapa3d` (o que fica parado depois de tocar).

Entrada: `alvos_<W>x<H>.json` do Blender (`tools/v68_blender_cenas.py -- alvos ...`, no it-campo): cada face de
cada município projetada pela MESMA câmera do vídeo, no quadro 959, + distância à câmera. Aqui (vm1):

  1. silhueta = união das faces projetadas (shapely);
  2. oclusão: do mais perto para o mais longe, cada silhueta perde o que os mais próximos já cobrem — o alvo
     é só a parte VISÍVEL, sem sobreposição (clique não cai no município de trás);
  3. leva para o espaço do vídeo publicado (desktop 3840×2160 → 1920×1080; celular 1080×1920 → recorte
     1080×1080 em y=460, igual a `tools/v68_cenas_enc.ps1`) e simplifica a ~1 px.

Saída: `static/assets/v68/mapa3d_alvos.json` = {d: {w, h, a: [[cod, valor_retrato, n_retrato, path]]}, m: {...}}.
Valor/nº são os do RETRATO que deu a altura (mapa.json) — o vivo vem da API na hora do hover.

Uso: python3 tools/v70_mapa_alvos.py <alvos_3840x2160.json> <alvos_1080x1920.json> <mapa.json> [saida]
"""
import json
import sys

from shapely.affinity import affine_transform
from shapely.geometry import Polygon, box
from shapely.ops import unary_union


def _poligonos(g):
    return [g] if g.geom_type == 'Polygon' else [p for p in getattr(g, 'geoms', []) if p.geom_type == 'Polygon']


def _path(g, minimo):
    partes = []
    for p in _poligonos(g):
        if p.area < minimo:
            continue
        for anel in [p.exterior, *p.interiors]:
            xy = list(anel.coords)[:-1]
            if len(xy) < 3:
                continue
            partes.append('M' + 'L'.join(f'{x:.1f},{y:.1f}'.replace('.0,', ',') for x, y in xy) + 'Z')
    return ''.join(partes)


def alvos(src, escala, dy, w, h, dados):
    a = json.load(open(src))
    sil = []
    for m in a['municipios']:
        fs = [Polygon(f).buffer(0) for f in m['faces'] if len(f) >= 3]
        u = unary_union([f for f in fs if not f.is_empty])
        sil.append((m['dist'], m['cod'], affine_transform(u, [escala, 0, 0, escala, 0, -dy])))
    quadro = box(0, 0, w, h)
    coberto, out = None, []
    for _, cod, g in sorted(sil):                       # perto → longe
        vis = g if coberto is None else g.difference(coberto)
        coberto = g if coberto is None else unary_union([coberto, g])
        vis = vis.intersection(quadro).simplify(.6, preserve_topology=True)
        d = _path(vis, 6.0)
        if d:
            v = dados.get(cod, {})
            out.append([cod, v.get('valor') or 0, v.get('n') or 0, d])
    out.sort(key=lambda x: x[0])
    return {'w': w, 'h': h, 'a': out}


if __name__ == '__main__':
    ad, am, mp = sys.argv[1:4]
    saida = sys.argv[4] if len(sys.argv) > 4 else 'static/assets/v68/mapa3d_alvos.json'
    mapa = json.load(open(mp))
    dados = {m['cod']: m for m in mapa['municipios']}
    r = {'fonte': 'Blender (câmera do vídeo mapa3d, quadro 959) + ' + mapa['fonte'],
         'atualizado_em': mapa.get('atualizado_em'),
         'd': alvos(ad, .5, 0, 1920, 1080, dados),
         'm': alvos(am, 1.0, 460, 1080, 1080, dados)}
    json.dump(r, open(saida, 'w'), separators=(',', ':'), ensure_ascii=False)
    print('ok', saida, len(r['d']['a']), len(r['m']['a']))
