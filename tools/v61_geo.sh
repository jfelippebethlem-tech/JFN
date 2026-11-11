#!/usr/bin/env bash
# v61_geo — gera a geometria do mapa do painel v61 (static/assets/geo/*.topo.json).
#
# Fontes (oficiais, gratuitas):
#   · Municípios do RJ (92): IBGE, API de malhas v3 (estados/33, intrarregiao=municipio, qualidade
#     intermediária) + API de localidades v1 (nomes e regiões). SIRGAS 2000 ≈ WGS84.
#   · Cidade do Rio: "Limite de Bairros" do Data.Rio/IPP (167 bairros com RA e AP), já em WGS84 em
#     data/tse_cache/bairros_pcrj_oficial.geojson (cache local, fora do git). RAs (33) e APs (5) são
#     DISSOLVIDAS dos bairros — mesmas divisas, sem malha desenhada à mão.
# Saídas: static/assets/geo/rj-municipios.topo.json (cod_ibge, nome)
#         static/assets/geo/rio-aps.topo.json       (objetos aps, ras, bairros; ap, codra, ra, bairro)
#         compliance_agent/territorio/dados/municipios_rj.json (lista de referência dos 92)
# Uso: tools/v61_geo.sh   (precisa de rede; mapshaper vem por npm num diretório temporário)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"; mkdir -p "$T/ibge" "$T/nomes" "$T/out" "$T/ferr"
curl -sS -m 90 -A "Mozilla/5.0" -o "$T/ibge/rj.geojson" \
  "https://servicodados.ibge.gov.br/api/v3/malhas/estados/33?intrarregiao=municipio&formato=application/vnd.geo%2Bjson&qualidade=intermediaria"
curl -sS -m 60 -A "Mozilla/5.0" -o "$T/nomes/mun.json" \
  "https://servicodados.ibge.gov.br/api/v1/localidades/estados/33/municipios"
python3 -I "$REPO/tools/v61_geo_prep.py" "$T" "$REPO"
( cd "$T/ferr" && npm init -y >/dev/null 2>&1 && npm i mapshaper --ignore-scripts >/dev/null 2>&1 )
M="$T/ferr/node_modules/.bin/mapshaper"
nice -n 10 "$M" "$T/out/mun_in.json" name=municipios -o format=topojson quantization=50000 "$T/out/rj-municipios.topo.json"
nice -n 10 "$M" "$T/out/bairros_in.json" name=bairros -simplify 14% keep-shapes \
  -dissolve codra copy-fields=ra,ap + name=ras -target bairros -dissolve ap + name=aps \
  -o target=aps,ras,bairros format=topojson quantization=20000 "$T/out/rio-aps.topo.json"
mkdir -p "$REPO/static/assets/geo" "$REPO/compliance_agent/territorio/dados"
cp "$T/out/rj-municipios.topo.json" "$T/out/rio-aps.topo.json" "$REPO/static/assets/geo/"
cp "$T/out/municipios_rj.json" "$REPO/compliance_agent/territorio/dados/"
ls -la "$REPO/static/assets/geo/"
rm -rf "$T"
