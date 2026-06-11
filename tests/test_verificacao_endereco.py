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


def test_municipio_divergente_so_quando_exato(monkeypatch, tmp_path):
    # divergência só vale com o NÚMERO resolvido (exato=True); senão é ruído de match coarse
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(ve, "geocodificar", lambda *a, **k: {
        "ok": True, "lat": -22.9, "lon": -43.2, "classe": "place", "tipo": "house",
        "display": "...", "municipio_geo": "Niterói", "bate_municipio": False, "exato": True})
    monkeypatch.setattr(ve, "edificacao_no_ponto", lambda *a, **k: {"ok": False})
    out = ve.analisar_endereco("RUA X 1", "Rio de Janeiro", "RJ")
    assert out["status"] == "INDICIO" and out["nivel"] == "ALTO"
    assert "Niterói" in out["evidencia"]


def test_divergencia_coarse_nao_acusa(monkeypatch, tmp_path):
    # lição 036100: match coarse (exato=False) em município diferente NÃO vira indício — INDISPONÍVEL honesto
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(ve, "geocodificar", lambda *a, **k: {
        "ok": True, "lat": -22.8, "lon": -42.3, "classe": "place", "tipo": "city",
        "display": "...", "municipio_geo": "Araruama", "bate_municipio": False, "exato": False})
    out = ve.analisar_endereco("RUA, CONSELHEIRO SARAIVA, 28", "Rio de Janeiro", "RJ", "20091030")
    assert out["status"] == "INDISPONIVEL"
    assert "logradouro/CEP" in out["evidencia"]


def test_terreno_nao_edificado_baldio(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(ve, "geocodificar", lambda *a, **k: {
        "ok": True, "lat": -22.9, "lon": -43.2, "classe": "highway", "tipo": "residential",
        "display": "...", "municipio_geo": "Rio de Janeiro", "bate_municipio": True, "exato": True})
    monkeypatch.setattr(ve, "edificacao_no_ponto", lambda lat, lon, raio=35: {
        "ok": True, "tem_predio": False, "n_predios": 0, "landuse_vago": True,
        "landuses": ["brownfield"], "motivo": ""})
    out = ve.analisar_endereco("RUA Y 2", "Rio de Janeiro", "RJ")
    assert out["status"] == "INDICIO"
    assert "baldio" in out["evidencia"].lower()
    assert "incompleta" in out["evidencia"].lower()  # ressalva honesta de cobertura OSM


def test_logradouro_existe_mas_numero_nao_geolocalizado(monkeypatch, tmp_path):
    # lição NEW LINK: a via existe (resolveu por CEP/logradouro), mas não o nº → sem veredito de baldio
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(ve, "geocodificar", lambda *a, **k: {
        "ok": True, "lat": -22.79, "lon": -43.33, "classe": "highway", "tipo": "residential",
        "display": "...", "municipio_geo": "São João de Meriti", "bate_municipio": True, "exato": False})
    out = ve.analisar_endereco("TAPAJOS, 60", "São João de Meriti", "RJ", "25585650")
    assert out["status"] == "INDISPONIVEL"
    assert "logradouro/CEP" in out["evidencia"]


def test_cep_fmt_e_variantes():
    assert ve._cep_fmt("25585650") == "25585-650"
    assert ve._cep_fmt("123") == ""
    vs = ve._variantes_consulta("TAPAJOS, 60, PARQUE ANALANDIA", "São João de Meriti", "RJ", "25585650")
    assert any("25585-650" in v for v in vs)          # usa o CEP
    assert any(v.lower().startswith("rua tapajos") for v in vs)  # tenta prefixo 'Rua'


def test_comercial_afastado(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(ve, "geocodificar", lambda *a, **k: {
        "ok": True, "lat": -22.9, "lon": -43.2, "classe": "building", "tipo": "commercial",
        "display": "...", "municipio_geo": "Rio de Janeiro", "bate_municipio": True, "exato": True})
    monkeypatch.setattr(ve, "edificacao_no_ponto", lambda lat, lon, raio=35: {
        "ok": True, "tem_predio": True, "n_predios": 3, "landuse_vago": False,
        "landuses": ["commercial"], "motivo": ""})
    out = ve.analisar_endereco("AV COMERCIAL 100", "Rio de Janeiro", "RJ")
    assert out["status"] == "AFASTADO"


def test_backoff_escalona_e_limpa(monkeypatch):
    monkeypatch.setattr(ve, "_backoff", {"ate": 0.0, "nivel": 0})
    assert ve.em_backoff() == 0.0
    ve._marca_backoff()
    assert ve.em_backoff() > 0  # entrou em trégua
    assert ve._backoff["nivel"] == 1
    ve._marca_backoff()
    assert ve._backoff["nivel"] == 2  # escalona
    ve._limpa_backoff()
    assert ve.em_backoff() == 0.0 and ve._backoff["nivel"] == 0


def test_imagem_sem_chave_indisponivel(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_KEY", raising=False)
    monkeypatch.delenv("STREETVIEW_KEY", raising=False)
    monkeypatch.delenv("MAPILLARY_TOKEN", raising=False)
    out = ve._classificar_visual(-22.9, -43.2)
    assert not out["ok"] and "INDISPONIVEL" in out["motivo"]
