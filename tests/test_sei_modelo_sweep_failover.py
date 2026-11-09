"""O modelo grátis do sweep SEI SAI DO CATÁLOGO sem aviso (09/11/2026: `meituan/longcat-2.0:free` -> 404
"no longer free" desde 25/09; o sweep ficou 6 semanas parado). A chamada tem que trocar sozinha para o
próximo da lista `MODELOS_SWEEP` — e não confundir cota/instabilidade (429/5xx) com modelo morto."""
import asyncio

import pytest

import tools.sei_ficha as sf


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._p, self.text = status, payload or {}, text

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Cliente:
    def __init__(self, por_modelo, vistos):
        self.por_modelo, self.vistos = por_modelo, vistos

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def post(self, _url, **kw):
        m = kw["json"]["model"]
        self.vistos.append(m)
        return self.por_modelo[m]


@pytest.fixture(autouse=True)
def _limpo(monkeypatch):
    monkeypatch.setattr(sf, "MODELOS_SWEEP", ["a:free", "b:free"])
    monkeypatch.setattr(sf, "_MORTOS", set())
    monkeypatch.setenv("NOUS_API_KEY", "chave-falsa-de-teste")


def _ok(txt):
    return _Resp(200, {"choices": [{"finish_reason": "stop", "message": {"content": txt}}]})


def _monta(monkeypatch, por_modelo):
    import httpx
    vistos = []
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Cliente(por_modelo, vistos))
    return vistos


def test_404_no_longer_free_troca_para_o_proximo(monkeypatch):
    vistos = _monta(monkeypatch, {"a:free": _Resp(404, text='{"error":"model is no longer free"}'),
                                  "b:free": _ok('{"objeto": "x"}')})
    assert asyncio.run(sf._chamar_nous("t", "a:free")) == '{"objeto": "x"}'
    assert vistos == ["a:free", "b:free"]


def test_morto_fica_lembrado_no_processo(monkeypatch):
    vistos = _monta(monkeypatch, {"a:free": _Resp(410, text="gone"), "b:free": _ok("{}")})
    asyncio.run(sf._chamar_nous("t", "a:free"))
    asyncio.run(sf._chamar_nous("t", "a:free"))
    assert vistos == ["a:free", "b:free", "b:free"], "não pode bater de novo no modelo morto"
    assert sf.modelo_sweep() == "b:free"


def test_429_nao_e_modelo_morto(monkeypatch):
    vistos = _monta(monkeypatch, {"a:free": _Resp(429, text="rate limit for model"), "b:free": _ok("{}")})
    with pytest.raises(RuntimeError):
        asyncio.run(sf._chamar_nous("t", "a:free"))
    assert vistos == ["a:free"] and not sf._MORTOS


def test_todos_mortos_deixa_o_erro_aparecer(monkeypatch):
    _monta(monkeypatch, {"a:free": _Resp(404, text="x"), "b:free": _Resp(404, text="x")})
    with pytest.raises(RuntimeError):
        asyncio.run(sf._chamar_nous("t", "a:free"))


def test_so_ids_free_entram_na_lista(monkeypatch):
    import importlib
    monkeypatch.setenv("SEI_MODELOS_SWEEP", "pago/modelo,c:free")
    monkeypatch.delenv("SEI_MODELO_SWEEP", raising=False)
    mod = importlib.reload(sf)
    try:
        assert mod.MODELOS_SWEEP == ["c:free"]
    finally:
        monkeypatch.delenv("SEI_MODELOS_SWEEP")
        importlib.reload(sf)
