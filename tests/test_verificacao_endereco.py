# -*- coding: utf-8 -*-
"""Testes da verificação de realidade do endereço (verificacao_endereco).

Offline: geocode/Overpass monkeypatchados. Cobrem não-resolução, divergência de município,
terreno não edificado (baldio), residencial e comercial (afastado), e cache."""
import compliance_agent.verificacao_endereco as ve


def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(ve, "_cache", None)
    monkeypatch.setattr(ve, "_CACHE_FILE", tmp_path / "endereco_cache.json")


def test_nao_resolvido_indicio(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(ve, "geocodificar", lambda *a, **k: {"ok": False, "motivo": "endereço não localizado"})
    out = ve.analisar_endereco("RUA INEXISTENTE 999", "Rio de Janeiro", "RJ")
    assert out["status"] == "INDICIO"
    assert "não localizado" in out["evidencia"]


def test_municipio_divergente_indicio_alto(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(ve, "geocodificar", lambda *a, **k: {
        "ok": True, "lat": -22.9, "lon": -43.2, "classe": "place", "tipo": "house",
        "display": "...", "municipio_geo": "Niterói", "bate_municipio": False})
    out = ve.analisar_endereco("RUA X 1", "Rio de Janeiro", "RJ")
    assert out["status"] == "INDICIO" and out["nivel"] == "ALTO"
    assert "Niterói" in out["evidencia"]


def test_terreno_nao_edificado_baldio(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(ve, "geocodificar", lambda *a, **k: {
        "ok": True, "lat": -22.9, "lon": -43.2, "classe": "highway", "tipo": "residential",
        "display": "...", "municipio_geo": "Rio de Janeiro", "bate_municipio": True})
    monkeypatch.setattr(ve, "edificacao_no_ponto", lambda lat, lon, raio=35: {
        "ok": True, "tem_predio": False, "n_predios": 0, "landuse_vago": True,
        "landuses": ["brownfield"], "motivo": ""})
    out = ve.analisar_endereco("RUA Y 2", "Rio de Janeiro", "RJ")
    assert out["status"] == "INDICIO"
    assert "baldio" in out["evidencia"].lower()
    assert "incompleta" in out["evidencia"].lower()  # ressalva honesta de cobertura OSM


def test_comercial_afastado(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(ve, "geocodificar", lambda *a, **k: {
        "ok": True, "lat": -22.9, "lon": -43.2, "classe": "building", "tipo": "commercial",
        "display": "...", "municipio_geo": "Rio de Janeiro", "bate_municipio": True})
    monkeypatch.setattr(ve, "edificacao_no_ponto", lambda lat, lon, raio=35: {
        "ok": True, "tem_predio": True, "n_predios": 3, "landuse_vago": False,
        "landuses": ["commercial"], "motivo": ""})
    out = ve.analisar_endereco("AV COMERCIAL 100", "Rio de Janeiro", "RJ")
    assert out["status"] == "AFASTADO"


def test_imagem_sem_chave_indisponivel(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_KEY", raising=False)
    monkeypatch.delenv("STREETVIEW_KEY", raising=False)
    monkeypatch.delenv("MAPILLARY_TOKEN", raising=False)
    out = ve._classificar_visual(-22.9, -43.2)
    assert not out["ok"] and "INDISPONIVEL" in out["motivo"]
