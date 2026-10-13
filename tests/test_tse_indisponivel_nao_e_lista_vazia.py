"""TSE recusando o download NÃO pode virar "0 candidatos" calado (28/09/2026: 33 meses marcados como cruzados à toa)."""
import pytest
import requests

from compliance_agent.pcrj import comissionados_candidatos as CC


def test_sem_download_e_sem_cache_levanta(tmp_path, monkeypatch):
    monkeypatch.setattr(CC, "_cache_path", lambda ano: tmp_path / f"c_{ano}.csv")
    def _403(*a, **k):
        raise requests.HTTPError("403 Client Error: Forbidden")
    monkeypatch.setattr(CC.requests, "get", _403)
    with pytest.raises(CC.TSEIndisponivel):
        CC._candidatos([2024], None)


def test_cache_local_supre_o_download_recusado(tmp_path, monkeypatch):
    cab = ";".join(f"c{i}" for i in range(max(CC._C.values()) + 1))
    linha = [""] * (max(CC._C.values()) + 1)
    linha[CC._C["nome"]], linha[CC._C["uf"]], linha[CC._C["munic"]] = "FULANO DE TAL", "RJ", "NITERÓI"
    linha[CC._C["ano"]], linha[CC._C["cargo"]] = "2024", "VEREADOR"
    (tmp_path / "c_2024.csv").write_bytes((cab + "\n" + ";".join(linha) + "\n").encode("latin-1"))
    monkeypatch.setattr(CC, "_cache_path", lambda ano: tmp_path / f"c_{ano}.csv")
    monkeypatch.setattr(CC.requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.HTTPError("403")))
    cands = CC._candidatos([2024], None)
    assert list(cands.values())[0]["cidade"] == "NITERÓI"
