# -*- coding: utf-8 -*-
"""Testes da camada física OSM (geo/osm_local) — httpx MOCKADO, zero rede.

Cobrem: precisão rooftop/city no geocode, Overpass com edificação, erro de rede → apuravel=False
(honesto, nunca finge vazio), e cache SQLite (hit não repete request; falha não é cacheada)."""
import httpx
import pytest

import compliance_agent.geo.osm_local as osm
from compliance_agent.providers.base import CacheSQLite


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _isola(monkeypatch, tmp_path):
    """Cache fresco por teste (não toca data/providers_cache.db) e throttle zerado (sem sleep)."""
    monkeypatch.setattr(osm, "_cache", CacheSQLite(str(tmp_path / "cache.db")))
    monkeypatch.setattr(osm, "_ult_publico", [0.0])
    monkeypatch.delenv("NOMINATIM_LOCAL_URL", raising=False)
    monkeypatch.delenv("OVERPASS_URL", raising=False)


# ── geocodificar ─────────────────────────────────────────────────────────────

def test_geocode_rooftop(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp(200, [
        {"lat": "-22.90", "lon": "-43.20", "osm_type": "way", "category": "building",
         "type": "yes"}]))
    out = osm.geocodificar("Av Rio Branco 156, Rio de Janeiro")
    assert out == {"lat": -22.90, "lon": -43.20, "precisao": "rooftop", "fonte": "nominatim_publico"}


def test_geocode_city_coarse(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp(200, [
        {"lat": "-22.81", "lon": "-43.30", "osm_type": "node", "category": "place",
         "type": "city"}]))
    out = osm.geocodificar("Duque de Caxias RJ")
    assert out["precisao"] == "city"


def test_geocode_zero_resultados_none(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp(200, []))
    assert osm.geocodificar("Rua Que Nao Existe 999, Nada, ZZ") is None


def test_geocode_erro_rede_none(monkeypatch):
    def _boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx, "get", _boom)
    assert osm.geocodificar("Av Rio Branco 156") is None


def test_geocode_local_url_muda_fonte(monkeypatch):
    monkeypatch.setenv("NOMINATIM_LOCAL_URL", "http://127.0.0.1:8088")
    urls = []

    def _get(url, *a, **k):
        urls.append(url)
        return _Resp(200, [{"lat": "-22.9", "lon": "-43.2", "osm_type": "way",
                            "category": "building", "type": "yes"}])
    monkeypatch.setattr(httpx, "get", _get)
    out = osm.geocodificar("Av Rio Branco 156")
    assert out["fonte"] == "nominatim_local"
    assert urls == ["http://127.0.0.1:8088/search"]


def test_geocode_cache_hit_nao_repete_request(monkeypatch):
    n = [0]

    def _get(*a, **k):
        n[0] += 1
        return _Resp(200, [{"lat": "-22.9", "lon": "-43.2", "osm_type": "way",
                            "category": "building", "type": "yes"}])
    monkeypatch.setattr(httpx, "get", _get)
    a = osm.geocodificar("Av Rio Branco 156")
    b = osm.geocodificar("Av Rio Branco 156")
    assert a == b and n[0] == 1


# ── edificacao_no_ponto ──────────────────────────────────────────────────────

def test_overpass_building_true(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(200, {"elements": [
        {"type": "way", "tags": {"building": "yes"}},
        {"type": "node", "tags": {"shop": "bakery"}}]}))
    out = osm.edificacao_no_ponto(-22.9, -43.2)
    assert out["apuravel"] is True
    assert out["tem_building"] is True and out["tem_shop"] is True and out["tem_office"] is False
    assert {"building": "yes"} in out["tags"]


def test_overpass_vazio_tudo_false_mas_apuravel(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(200, {"elements": []}))
    out = osm.edificacao_no_ponto(-22.9, -43.2)
    assert out == {"tem_building": False, "tem_shop": False, "tem_office": False,
                   "tags": [], "apuravel": True}


def test_overpass_erro_rede_inapuravel_e_nao_cacheia(monkeypatch):
    def _boom(*a, **k):
        raise httpx.ReadTimeout("timeout")
    monkeypatch.setattr(httpx, "post", _boom)
    assert osm.edificacao_no_ponto(-22.9, -43.2) == {"apuravel": False}
    # a falha NÃO ficou cacheada: com a rede de volta, o mesmo ponto apura
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(200, {"elements": [
        {"type": "way", "tags": {"building": "yes"}}]}))
    assert osm.edificacao_no_ponto(-22.9, -43.2)["apuravel"] is True


def test_overpass_cache_hit_nao_repete_request(monkeypatch):
    n = [0]

    def _post(*a, **k):
        n[0] += 1
        return _Resp(200, {"elements": [{"type": "way", "tags": {"building": "yes"}}]})
    monkeypatch.setattr(httpx, "post", _post)
    a = osm.edificacao_no_ponto(-22.9, -43.2)
    b = osm.edificacao_no_ponto(-22.9, -43.2)
    assert a == b and n[0] == 1
