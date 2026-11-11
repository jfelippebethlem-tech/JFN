import json
import sys
base, repo = sys.argv[1], sys.argv[2]
g = json.load(open(base + '/ibge/rj.geojson'))
nomes = {str(m['id']): m for m in json.load(open(base + '/nomes/mun.json'))}
for f in g['features']:
    c = f['properties']['codarea']; m = nomes[c]
    f['properties'] = {'cod_ibge': c, 'nome': m['nome']}
assert len(g['features']) == 92 and len({f['properties']['cod_ibge'] for f in g['features']}) == 92
json.dump(g, open(base + '/out/mun_in.json', 'w'), ensure_ascii=False)
# lista de referência dos 92 (para o motor territorio)
ref = []
for c, m in sorted(nomes.items()):
    ri = (m.get('regiao-imediata') or {}); rint = (ri.get('regiao-intermediaria') or {})
    mic = (m.get('microrregiao') or {}); meso = (mic.get('mesorregiao') or {})
    ref.append({'cod_ibge': c, 'nome': m['nome'], 'mesorregiao': meso.get('nome'), 'microrregiao': mic.get('nome'),
                'regiao_intermediaria': rint.get('nome'), 'regiao_imediata': ri.get('nome')})
json.dump({'fonte': 'IBGE — API de localidades v1 (estados/33/municipios)', 'municipios': ref},
          open(base + '/out/municipios_rj.json', 'w'), ensure_ascii=False, indent=1)
b = json.load(open(repo + '/data/tse_cache/bairros_pcrj_oficial.geojson'))
xs = []
for f in b['features']:
    p = f['properties']
    f['properties'] = {'bairro': p['nome'].strip(), 'ra': ' '.join(p['regiao_adm'].split()).title(), 'codra': int(p['codra']),
                       'ap': int(p['area_plane']), 'rp': p['rp'].strip(), 'cod_rp': str(p['cod_rp']).strip()}
    geo = f['geometry']; ring = geo['coordinates'][0] if geo['type'] == 'Polygon' else geo['coordinates'][0][0]
    xs.append(ring[0])
print('bairros', len(b['features']), 'amostra coord', xs[0], 'lon', min(x[0] for x in xs), max(x[0] for x in xs), 'lat', min(x[1] for x in xs), max(x[1] for x in xs))
json.dump(b, open(base + '/out/bairros_in.json', 'w'), ensure_ascii=False)
ras = sorted({(f['properties']['ap'], f['properties']['codra'], f['properties']['ra']) for f in b['features']})
print(len(ras), 'RAs;', ras[:6])
