# -*- coding: utf-8 -*-
"""Testes de sede_google — verificação HONESTA da realidade da sede via 3 APIs Google.

100% offline: httpx mockado por monkeypatch (as funções fazem `import httpx` local, então
patcheamos `httpx.get`/`httpx.post` direto). A cota é isolada em tmp_path (`_QUOTA_DIR`) p/
nunca tocar `data/quota_*.json` real. `verdict_de_sinais` (o coração honesto) é exercitado com
dicts de sinais montados à mão — indício ≠ acusação, ausência ≠ prova."""
import json

import pytest

import compliance_agent.sede_google as sg


# ───────────────────────────── helpers ─────────────────────────────
class _FakeResp:
    """Resposta httpx falsa (cobre .json() do geocode e .status_code/.json() de POST)."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _isola_cota(monkeypatch, tmp_path):
    """Isola o diretório de cota e garante chave Google setada + teto folgado."""
    monkeypatch.setattr(sg, "_QUOTA_DIR", tmp_path)
    monkeypatch.setenv("GOOGLE_MAPS_KEY", "chave-falsa-de-teste")
    # tetos folgados p/ não barrar nas chamadas de parse
    monkeypatch.setenv("GEOCODING_MAX_31D", "9999")
    monkeypatch.setenv("ADDRVAL_MAX_31D", "9999")
    monkeypatch.setenv("PLACES_MAX_31D", "9999")


# ───────────────────────────── 1. predio_key ─────────────────────────────
def test_predio_key_exemplo_canonico():
    k = sg.predio_key("AVENIDA, ALMIRANTE BARROSO, 6, APT 1111, CENTRO", "20031-000")
    assert k == "AVENIDA ALMIRANTE BARROSO|6|20031000"


def test_predio_key_sala_apto_nao_muda_mesmo_predio():
    # sala/apto/bloco não fazem parte da chave → mesmo prédio = mesma chave (dedup de cota)
    a = sg.predio_key("AVENIDA, ALMIRANTE BARROSO, 6, APT 1111, CENTRO", "20031-000")
    b = sg.predio_key("AVENIDA, ALMIRANTE BARROSO, 6, SALA 302", "20031-000")
    c = sg.predio_key("AVENIDA ALMIRANTE BARROSO 6 BLOCO B", "20031000")
    assert a == b == c


def test_predio_key_cep_diferente_muda():
    a = sg.predio_key("RUA DA QUITANDA, 50", "20011-030")
    b = sg.predio_key("RUA DA QUITANDA, 50", "20091-005")
    assert a != b
    assert a.endswith("|20011030")
    assert b.endswith("|20091005")


def test_predio_key_sem_numero():
    k = sg.predio_key("PRACA MAUA, S/N", "20081-240")
    # 'S/N' não tem dígito antes do CEP → número vazio; chave ainda determinística
    # (vírgula vira espaço; barra é preservada por _norm)
    assert k == "PRACA MAUA S/N||20081240"


# ───────────────────────────── 2. cep_de ─────────────────────────────
def test_cep_de_so_digitos_8():
    assert sg.cep_de("20031-000") == "20031000"
    assert sg.cep_de("20031000") == "20031000"
    assert sg.cep_de("CEP: 20.031-000") == "20031000"


def test_cep_de_curto_vazio():
    assert sg.cep_de("123") == ""
    assert sg.cep_de("") == ""
    assert sg.cep_de(None) == ""


def test_cep_de_trunca_a_8():
    assert sg.cep_de("200310001234") == "20031000"


# ───────────────────────────── 3. _nomes_batem ─────────────────────────────
def test_nomes_batem_token_significativo():
    assert sg._nomes_batem("HEBARA DISTRIBUIDORA LTDA", "Hebara Distribuidora") is True


def test_nomes_batem_negocio_de_terceiro_false():
    assert sg._nomes_batem("NRTT SOLUCOES LTDA", "Fit Auto Posto") is False


def test_nomes_batem_so_genericos_false():
    # só tokens societários/genéricos em comum (COMERCIO/SERVICOS/SA/LTDA) → não distingue → False
    assert sg._nomes_batem("X COMERCIO LTDA", "Y SERVICOS SA") is False


def test_nomes_batem_ignora_acento_e_caixa():
    assert sg._nomes_batem("CONSTRUTORA ÁGUIA LTDA", "construtora aguia") is True


# ───────────────────────────── 4. cota: _consome_cota / cota_restante ─────────────────────────────
def test_consome_cota_decrementa(monkeypatch, tmp_path):
    monkeypatch.setattr(sg, "_QUOTA_DIR", tmp_path)
    monkeypatch.setenv("GEOCODING_MAX_31D", "5")
    assert sg.cota_restante("geocoding") == 5
    assert sg._consome_cota("geocoding") is True
    assert sg.cota_restante("geocoding") == 4
    assert sg._consome_cota("geocoding") is True
    assert sg.cota_restante("geocoding") == 3


def test_consome_cota_atinge_teto_retorna_false(monkeypatch, tmp_path):
    monkeypatch.setattr(sg, "_QUOTA_DIR", tmp_path)
    monkeypatch.setenv("GEOCODING_MAX_31D", "2")
    assert sg._consome_cota("geocoding") is True
    assert sg._consome_cota("geocoding") is True
    assert sg._consome_cota("geocoding") is False  # teto atingido
    assert sg.cota_restante("geocoding") == 0


def test_cota_isolada_por_api(monkeypatch, tmp_path):
    monkeypatch.setattr(sg, "_QUOTA_DIR", tmp_path)
    monkeypatch.setenv("GEOCODING_MAX_31D", "1")
    monkeypatch.setenv("PLACES_MAX_31D", "1")
    assert sg._consome_cota("geocoding") is True
    assert sg._consome_cota("geocoding") is False
    # places tem arquivo/cota própria → não foi afetada
    assert sg.cota_restante("places") == 1
    assert sg._consome_cota("places") is True


def test_cota_persiste_em_arquivo(monkeypatch, tmp_path):
    monkeypatch.setattr(sg, "_QUOTA_DIR", tmp_path)
    monkeypatch.setenv("GEOCODING_MAX_31D", "9999")
    sg._consome_cota("geocoding")
    f = tmp_path / "quota_geocoding.json"
    assert f.exists()
    st = json.loads(f.read_text("utf-8"))
    assert st["count"] == 1


# ───────────────────────────── 5. coletores (geocodificar/validar/buscar_negocio) ─────────────────────────────
def test_geocodificar_ok_parse(monkeypatch, tmp_path):
    _isola_cota(monkeypatch, tmp_path)
    payload = {
        "status": "OK",
        "results": [{
            "geometry": {"location": {"lat": -22.9, "lng": -43.17}, "location_type": "ROOFTOP"},
            "address_components": [
                {"long_name": "Rio de Janeiro", "types": ["administrative_area_level_2", "political"]},
            ],
            "formatted_address": "Av. Almirante Barroso, 6 - Centro, Rio de Janeiro - RJ",
        }],
    }
    monkeypatch.setattr("httpx.get", lambda *a, **k: _FakeResp(payload))
    out = sg.geocodificar("AVENIDA ALMIRANTE BARROSO 6")
    assert out["lat"] == -22.9
    assert out["lon"] == -43.17
    assert out["location_type"] == "ROOFTOP"
    assert out["municipio"] == "Rio de Janeiro"
    assert out["status"] == "OK"


def test_geocodificar_status_nao_ok_e_sinal_nao_erro(monkeypatch, tmp_path):
    _isola_cota(monkeypatch, tmp_path)
    monkeypatch.setattr("httpx.get", lambda *a, **k: _FakeResp({"status": "ZERO_RESULTS", "results": []}))
    out = sg.geocodificar("RUA QUE NAO EXISTE 9999")
    assert out is not None  # não é erro, é sinal
    assert out["location_type"] == ""
    assert out["lat"] is None
    assert out["status"] == "ZERO_RESULTS"


def test_geocodificar_sem_chave_none(monkeypatch, tmp_path):
    monkeypatch.setattr(sg, "_QUOTA_DIR", tmp_path)
    monkeypatch.delenv("GOOGLE_MAPS_KEY", raising=False)
    monkeypatch.delenv("STREETVIEW_KEY", raising=False)
    out = sg.geocodificar("QUALQUER ENDERECO 1")
    assert out is None


def test_geocodificar_sem_cota_none(monkeypatch, tmp_path):
    _isola_cota(monkeypatch, tmp_path)
    monkeypatch.setenv("GEOCODING_MAX_31D", "0")  # cota esgotada

    def _boom(*a, **k):
        raise AssertionError("httpx.get não deveria ser chamado sem cota")

    monkeypatch.setattr("httpx.get", _boom)
    assert sg.geocodificar("RUA X 1") is None


def test_validar_parse(monkeypatch, tmp_path):
    _isola_cota(monkeypatch, tmp_path)
    payload = {"result": {
        "verdict": {
            "addressComplete": True,
            "validationGranularity": "PREMISE",
            "geocodeGranularity": "PREMISE",
            "inputGranularity": "PREMISE",
            "possibleNextAction": "ACCEPT",
        },
        "metadata": {"residential": True, "business": False},
    }}
    monkeypatch.setattr("httpx.post", lambda *a, **k: _FakeResp(payload))
    out = sg.validar("AV ALMIRANTE BARROSO 6, Rio de Janeiro, RJ")
    assert out["completo"] is True
    assert out["validacao"] == "PREMISE"
    assert out["residencial"] is True
    assert out["acao"] == "ACCEPT"


def test_validar_http_erro_none(monkeypatch, tmp_path):
    _isola_cota(monkeypatch, tmp_path)
    monkeypatch.setattr("httpx.post", lambda *a, **k: _FakeResp({}, status_code=500))
    assert sg.validar("RUA X 1") is None


def test_buscar_negocio_achou(monkeypatch, tmp_path):
    _isola_cota(monkeypatch, tmp_path)
    payload = {"places": [{
        "displayName": {"text": "Hebara Distribuidora"},
        "businessStatus": "OPERATIONAL",
        "formattedAddress": "Av. Almirante Barroso, 6 - Centro, Rio de Janeiro - RJ",
        "types": ["wholesaler", "store"],
    }]}
    monkeypatch.setattr("httpx.post", lambda *a, **k: _FakeResp(payload))
    out = sg.buscar_negocio("HEBARA DISTRIBUIDORA LTDA", "AV ALMIRANTE BARROSO 6", "Rio de Janeiro")
    assert out["achou"] is True
    assert out["status"] == "OPERATIONAL"
    assert out["nome"] == "Hebara Distribuidora"
    assert out["bate_nome"] is True
    assert out["bate_mun"] is True


def test_buscar_negocio_sem_places(monkeypatch, tmp_path):
    _isola_cota(monkeypatch, tmp_path)
    monkeypatch.setattr("httpx.post", lambda *a, **k: _FakeResp({"places": []}))
    out = sg.buscar_negocio("EMPRESA FANTASMA LTDA", "RUA X 1", "Niterói")
    assert out["achou"] is False
    assert out["nome"] == ""


def test_buscar_negocio_terceiro_nome_nao_bate(monkeypatch, tmp_path):
    _isola_cota(monkeypatch, tmp_path)
    payload = {"places": [{
        "displayName": {"text": "Fit Auto Posto"},
        "businessStatus": "OPERATIONAL",
        "formattedAddress": "Rua Y, 10 - Centro, Niterói - RJ",
        "types": ["gas_station"],
    }]}
    monkeypatch.setattr("httpx.post", lambda *a, **k: _FakeResp(payload))
    out = sg.buscar_negocio("NRTT SOLUCOES LTDA", "RUA Y 10", "Niterói")
    assert out["achou"] is True
    assert out["bate_nome"] is False  # comércio de terceiro, não prova a empresa


# ───────────────────────────── 6. verdict_de_sinais (o coração honesto) ─────────────────────────────
def test_verdict_negocio_operante_da_empresa_afasta():
    sinais = {
        "geocode": {"location_type": "ROOFTOP"},
        "validacao": {"completo": True, "validacao": "PREMISE", "residencial": False},
        "places": {"achou": True, "status": "OPERATIONAL", "nome": "Hebara Distribuidora",
                   "bate_nome": True, "bate_mun": True, "endereco": "..."},
    }
    out = sg.verdict_de_sinais(sinais, total_pago=500_000)
    assert out["status"] == "AFASTADO"


def test_verdict_geocode_rooftop_sem_negocio_baixo_afasta():
    sinais = {
        "geocode": {"location_type": "ROOFTOP"},
        "validacao": {"completo": True, "residencial": False, "validacao": "PREMISE"},
        "places": {"achou": False, "status": "", "nome": "", "bate_nome": None, "bate_mun": None},
    }
    out = sg.verdict_de_sinais(sinais, total_pago=10_000)  # R$ baixo
    assert out["status"] == "AFASTADO"  # existe fisicamente


def test_verdict_residencial_indicio():
    sinais = {
        "geocode": {"location_type": "ROOFTOP"},
        "validacao": {"completo": True, "residencial": True, "validacao": "PREMISE"},
        "places": {"achou": False, "status": "", "nome": "", "bate_nome": None, "bate_mun": None},
    }
    out = sg.verdict_de_sinais(sinais, total_pago=50_000)
    assert out["status"] == "INDICIO"


def test_verdict_residencial_alto_valor_sem_negocio_nivel_alto():
    sinais = {
        "geocode": {"location_type": "GEOMETRIC_CENTER"},
        "validacao": {"completo": True, "residencial": True, "validacao": "PREMISE"},
        "places": {"achou": False, "status": "", "nome": "", "bate_nome": None, "bate_mun": None},
    }
    out = sg.verdict_de_sinais(sinais, total_pago=2_000_000)  # > R$ 1M
    assert out["status"] == "INDICIO"
    assert out["nivel"] == "ALTO"


def test_verdict_comercio_terceiro_com_residencial_indicio_nao_afasta():
    # places achou mas nome não bate (comércio de terceiro) + residencial → NÃO pode AFASTAR
    sinais = {
        "geocode": {"location_type": "ROOFTOP"},
        "validacao": {"completo": True, "residencial": True, "validacao": "PREMISE"},
        "places": {"achou": True, "status": "OPERATIONAL", "nome": "Fit Auto Posto",
                   "bate_nome": False, "bate_mun": True, "endereco": "Rua Y, 10"},
    }
    out = sg.verdict_de_sinais(sinais, total_pago=50_000)
    assert out["status"] == "INDICIO"


def test_verdict_approximate_incompleto_indicio():
    sinais = {
        "geocode": {"location_type": "APPROXIMATE"},
        "validacao": {"completo": False, "residencial": None, "validacao": "OTHER"},
        "places": {"achou": None, "status": "", "nome": "", "bate_nome": None, "bate_mun": None},
    }
    out = sg.verdict_de_sinais(sinais, total_pago=0)
    assert out["status"] == "INDICIO"  # endereço não confirmado


def test_verdict_tudo_vazio_indisponivel():
    sinais = {"geocode": None, "validacao": None, "places": None}
    out = sg.verdict_de_sinais(sinais, total_pago=0)
    assert out["status"] == "INDISPONIVEL"


def test_verdict_shape_completo():
    out = sg.verdict_de_sinais({"geocode": None, "validacao": None, "places": None})
    assert set(out.keys()) == {"status", "nivel", "evidencia", "pos", "neg"}
    assert isinstance(out["pos"], list)
    assert isinstance(out["neg"], list)
    assert out["evidencia"].endswith(".")


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
