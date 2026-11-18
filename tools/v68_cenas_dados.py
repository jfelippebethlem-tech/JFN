"""v68 · exporta os DADOS REAIS das cenas 3D (Blender, it-campo) — só geometria e números, sem nomes.

  galaxia.json  nós de /api/galaxia (x, y, tipo, cluster, peso, crítico) + arestas (índices). Nenhum rótulo
                (nome de órgão/fornecedor/pessoa) sai da vm1: o vídeo não tem texto e o it-campo não precisa dele.
  mapa.json     os 92 municípios (anéis em km, projeção equirretangular local) + valor_contratado (métrica
                padrão da aba Mapa: contratos VIGENTES do Executivo estadual atribuídos ao município, graus
                explícito+unidade) e n_contratos. Não é pago (OB) — é valor de contrato.

Uso: python3 tools/v68_cenas_dados.py <galaxia.json> <territorio_estado.json> <saida/>
"""
import json
import math
import sys
from pathlib import Path

def galaxia(src):
    d = json.load(open(src))
    nos = d['nos']; idx = {}; lim = d.get('critico') or 50      # limiar de score do painel (galaxia/render.js)
    cls = {}; out = []
    for i, n in enumerate(nos):
        idx[i] = len(out)
        c = cls.setdefault(n.get('cl') or '', len(cls))
        out.append([round(n.get('x', 0), 2), round(n.get('y', 0), 2), n.get('t', ''), c,
                    n.get('s') or n.get('g') or 1,
                    int(n.get('t') == 'cnpj' and (n.get('s') or 0) >= lim)])
    ar = [[a[0], a[1], a[2] if len(a) > 2 else 0] for a in d['arestas'] if a[0] < len(nos) and a[1] < len(nos)]
    tipos = {}
    for n in nos: tipos[n.get('t')] = tipos.get(n.get('t'), 0) + 1
    return {'fonte': '/api/galaxia', 'gerado_em': d.get('gerado_em'), 'campos': ['x', 'y', 't', 'cl', 'peso', 'critico'],
            'tipos': tipos, 'critico_api': d.get('critico'), 'nos': out, 'arestas': ar}

def mapa(topo_p, terr_p):
    t = json.load(open(topo_p)); terr = json.load(open(terr_p))
    sx, sy = t['transform']['scale']; tx, ty = t['transform']['translate']
    arcs = []
    for a in t['arcs']:
        x = y = 0; pts = []
        for dx, dy in a:
            x += dx; y += dy; pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    def arco(i): return arcs[i] if i >= 0 else arcs[~i][::-1]
    lat0 = -22.25; kx = 111.32 * math.cos(math.radians(lat0)); ky = 110.57
    lon0 = -42.9
    val = {m['cod_ibge']: m for m in terr['municipios']}
    mun = []
    for g in t['objects']['municipios']['geometries']:
        polys = g['arcs'] if g['type'] == 'MultiPolygon' else [g['arcs']]
        aneis = []
        for p in polys:
            for ring in p[:1]:                       # só o contorno externo (furos são irrelevantes no voo)
                pts = []
                for ai in ring:
                    seg = arco(ai); pts.extend(seg[1:] if pts else seg)
                aneis.append([[round((lo - lon0) * kx, 3), round((la - lat0) * ky, 3)] for lo, la in pts])
        m = val.get(g['properties']['cod_ibge'], {})
        mun.append({'cod': g['properties']['cod_ibge'], 'valor': m.get('valor_contratado') or 0,
                    'n': m.get('n_contratos') or 0, 'aneis': aneis})
    return {'fonte': '/api/territorio/estado + static/assets/geo/rj-municipios.topo.json',
            'metrica': terr.get('metrica'), 'periodo': terr.get('periodo'), 'atualizado_em': terr.get('atualizado_em'),
            'unidade': 'km', 'municipios': mun}

if __name__ == '__main__':
    gx, te, saida = sys.argv[1], sys.argv[2], Path(sys.argv[3]); saida.mkdir(parents=True, exist_ok=True)
    json.dump(galaxia(gx), open(saida / 'galaxia.json', 'w'), separators=(',', ':'))
    json.dump(mapa('static/assets/geo/rj-municipios.topo.json', te), open(saida / 'mapa.json', 'w'), separators=(',', ':'))
    print('ok', saida)
