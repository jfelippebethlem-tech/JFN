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


def test_satelite_nunca_acusa_baldio_barraco(monkeypatch):
    # lição Banco do Brasil: satélite (entorno, impreciso) classificou banco como 'barraco' → NÃO pode acusar
    monkeypatch.delenv("GOOGLE_MAPS_KEY", raising=False)
    monkeypatch.delenv("STREETVIEW_KEY", raising=False)
    monkeypatch.setattr(ve, "_fetch_satelite_esri", lambda lat, lon, delta=0.0009: b"\x89PNGfake")
    monkeypatch.setattr(ve, "_vlm_classificar", lambda img, fonte, endereco="": {
        "ok": True, "classe": "construcao_precaria_barraco", "confianca": 0.8, "descricao": "x"})
    out = ve.classificar_local_por_imagem(-15.77, -47.98, "Banco do Brasil")
    assert out["status"] == "INDISPONIVEL"  # satélite não acusa
    assert "Street View" in out["evidencia"]


def test_streetview_acusa_barraco(monkeypatch):
    # com fonte PRECISA (Street View) o barraco vira indício de verdade
    monkeypatch.setenv("GOOGLE_MAPS_KEY", "k")
    monkeypatch.setattr(ve, "_fetch_streetview_google", lambda lat, lon, chave: b"\xff\xd8\xfffake")
    monkeypatch.setattr(ve, "_vlm_classificar", lambda img, fonte, endereco="": {
        "ok": True, "classe": "terreno_baldio", "confianca": 0.7, "descricao": "lote vazio"})
    out = ve.classificar_local_por_imagem(-22.9, -43.2, "Rua X")
    assert out["status"] == "INDICIO" and "Street View" in out["fonte"]


def test_satelite_afasta_area_construida(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_KEY", raising=False)
    monkeypatch.setattr(ve, "_fetch_satelite_esri", lambda lat, lon, delta=0.0009: b"\x89PNGfake")
    monkeypatch.setattr(ve, "_vlm_classificar", lambda img, fonte, endereco="": {
        "ok": True, "classe": "comercial_industrial", "confianca": 0.8, "descricao": "prédios"})
    out = ve.classificar_local_por_imagem(-22.9, -43.17, "Av Rio Branco")
    assert out["status"] == "AFASTADO"


def test_imagem_indisponivel_sem_foto(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_KEY", raising=False)
    monkeypatch.setattr(ve, "_fetch_satelite_esri", lambda lat, lon, delta=0.0009: None)
    out = ve.classificar_local_por_imagem(-22.9, -43.2)
    assert out["status"] == "INDISPONIVEL" and not out["ok"]


# ───────── cont.18+: Mapillary (grátis) prioritário + casebre + teto do Street View ─────────

def test_ordem_fontes_default_mapillary_primeiro(monkeypatch):
    monkeypatch.delenv("IMG_FONTE_ORDEM", raising=False)
    assert ve._fontes_rua_ordenadas() == ["mapillary", "streetview"]
    monkeypatch.setenv("IMG_FONTE_ORDEM", "streetview,mapillary")
    assert ve._fontes_rua_ordenadas() == ["streetview", "mapillary"]


def test_mapillary_prioritario_nao_gasta_streetview(monkeypatch):
    """Com Mapillary cobrindo o ponto, o Street View (PAGO) NÃO é chamado — economia."""
    monkeypatch.setenv("MAPILLARY_TOKEN", "tok")
    monkeypatch.setenv("GOOGLE_MAPS_KEY", "k")
    monkeypatch.setattr(ve, "_fetch_mapillary", lambda lat, lon, token, raio_m=50.0: b"\xff\xd8\xffmly")
    def _boom(*a, **k):
        raise AssertionError("Street View não deveria ser chamado quando o Mapillary cobre")
    monkeypatch.setattr(ve, "_fetch_streetview_google", _boom)
    monkeypatch.setattr(ve, "_vlm_classificar", lambda img, fonte, endereco="": {
        "ok": True, "classe": "comercial_industrial", "confianca": 0.8, "descricao": "loja"})
    out = ve.classificar_local_por_imagem(-22.9, -43.2, "Rua X")
    assert out["status"] == "AFASTADO" and "Mapillary" in out["fonte"]


def test_mapillary_acusa_casebre_mesmo_edificado(monkeypatch):
    """Pedido do dono: mesmo edificado, casebre/barraco (rente ao chão) vira INDÍCIO — Mapillary é PRECISO."""
    monkeypatch.setenv("MAPILLARY_TOKEN", "tok")
    monkeypatch.delenv("GOOGLE_MAPS_KEY", raising=False)
    monkeypatch.setattr(ve, "_fetch_mapillary", lambda lat, lon, token, raio_m=50.0: b"\xff\xd8\xffmly")
    monkeypatch.setattr(ve, "_vlm_classificar", lambda img, fonte, endereco="": {
        "ok": True, "classe": "construcao_precaria_barraco", "confianca": 0.7, "descricao": "casebre"})
    out = ve.classificar_local_por_imagem(-22.9, -43.2, "Rua Y")
    assert out["status"] == "INDICIO" and "Mapillary" in out["fonte"]


def test_streetview_teto_31d_bloqueia(monkeypatch, tmp_path):
    monkeypatch.setattr(ve, "_SV_QUOTA_FILE", tmp_path / "sv_quota.json")
    monkeypatch.setenv("STREETVIEW_MAX_31D", "2")
    assert [ve._streetview_consome_cota() for _ in range(4)] == [True, True, False, False]


def test_imagem_casebre_precede_edificado_osm(monkeypatch, tmp_path):
    """Pedido do dono: mesmo com OSM dizendo 'edificado', foto de rua acusando casebre vira INDÍCIO."""
    monkeypatch.setattr(ve, "_cache", None)
    monkeypatch.setattr(ve, "_CACHE_FILE", tmp_path / "c.json")
    monkeypatch.setattr(ve, "geocodificar", lambda *a, **k: {
        "ok": True, "lat": -22.9, "lon": -43.2, "classe": "building", "tipo": "yes",
        "display": "...", "municipio_geo": "Rio de Janeiro", "bate_municipio": True, "exato": True})
    monkeypatch.setattr(ve, "edificacao_no_ponto", lambda *a, **k: {
        "ok": True, "tem_predio": True, "n_predios": 3, "landuses": []})  # OSM: edificado
    monkeypatch.setattr(ve, "_classificar_visual", lambda lat, lon: {
        "ok": True, "status": "INDICIO", "nivel": "ALTO", "classe": "construcao_precaria_barraco",
        "confianca": 0.7, "fonte": "Mapillary (foto de rua)", "evidencia": "casebre na fachada"})
    out = ve.analisar_endereco("RUA Z 10", "Rio de Janeiro", "RJ", usar_imagem=True)
    assert out["status"] == "INDICIO" and out["nivel"] == "ALTO"
    assert out["sinais"]["imagem"]["classe"] == "construcao_precaria_barraco"


def test_sem_usar_imagem_edificado_afasta(monkeypatch, tmp_path):
    """Sem usar_imagem (default), o mesmo ponto edificado é AFASTADO — o visual é opt-in."""
    monkeypatch.setattr(ve, "_cache", None)
    monkeypatch.setattr(ve, "_CACHE_FILE", tmp_path / "c2.json")
    monkeypatch.setattr(ve, "geocodificar", lambda *a, **k: {
        "ok": True, "lat": -22.9, "lon": -43.2, "classe": "building", "tipo": "commercial",
        "display": "...", "municipio_geo": "Rio de Janeiro", "bate_municipio": True, "exato": True})
    monkeypatch.setattr(ve, "edificacao_no_ponto", lambda *a, **k: {
        "ok": True, "tem_predio": True, "n_predios": 3, "landuses": []})
    out = ve.analisar_endereco("RUA Z 10", "Rio de Janeiro", "RJ")  # usar_imagem=False default
    assert out["status"] == "AFASTADO"
