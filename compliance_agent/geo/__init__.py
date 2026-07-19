# -*- coding: utf-8 -*-
"""Camada geográfica (OSM local-first): geocode Nominatim + edificação Overpass."""
from compliance_agent.geo.osm_local import edificacao_no_ponto, geocodificar

__all__ = ["geocodificar", "edificacao_no_ponto"]
