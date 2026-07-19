# Nominatim local (extrato RJ) — geocoding ilimitado sob demanda

Instância própria do Nominatim (mediagis/nominatim) com o extrato do RJ da Geofabrik, para
geocodificar em volume sem o throttle de 1 req/s do serviço público.

> **⚠ Subir SOB DEMANDA, não 24h.** A VM tem 2 vCPU e o jfn.service em produção — o Postgres do
> Nominatim + import comem CPU/RAM. Subir para o sweep, derrubar ao terminar (`restart: "no"` no
> compose é proposital).

## Uso

```bash
cd ~/JFN/deploy/nominatim
docker compose up -d          # 1ª vez: import do .pbf (~30-90 min no extrato RJ; volume persiste)
curl 'http://127.0.0.1:8088/search?q=Av+Rio+Branco+156,+Rio+de+Janeiro&format=jsonv2'  # smoke
```

Apontar o JFN para o local (no `.env`):

```bash
NOMINATIM_LOCAL_URL=http://127.0.0.1:8088
```

Com a env setada, `compliance_agent/geo/osm_local.py` e `verificacao_endereco.geocodificar` usam o
local primeiro (sem throttle); sem a env, tudo segue no público com 1 req/s — comportamento intacto.

Ao terminar o sweep:

```bash
docker compose down           # o volume nominatim-data preserva o import (próximo up é rápido)
```

## Notas

- `IMPORT_STYLE: address` importa só o necessário p/ geocode de endereço (mais leve p/ 2 vCPU).
- Se o recorte `sudeste/rio-de-janeiro-latest.osm.pbf` não existir na Geofabrik, trocar `PBF_URL`
  pelo `sudeste-latest.osm.pbf` (~1,5 GB; import mais longo).
- Overpass continua no público (`OVERPASS_URL` no env permite apontar p/ instância própria depois).
- Porta exposta só em `127.0.0.1` — sem superfície externa.
