"""Candidatos do TSE trazidos de fora da nuvem: importador → cache → leitor, sem rede."""
import zipfile

import requests

from compliance_agent.pcrj import tse_candidatos as T
from tools import tse_importar as I

CAB = b'"DT_GERACAO";"HH_GERACAO";"ANO_ELEICAO";"SG_UF";"NM_UE";"NM_CANDIDATO"\n'


def _csv(ano: int) -> bytes:
    return CAB + b"".join(f'"x";"y";"{ano}";"RJ";"NITEROI";"FULANO {i}"\n'.encode() for i in range(150))


def test_zip_oficial_vai_para_o_cache_e_o_leitor_nao_usa_rede(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "_cache_path", lambda ano: tmp_path / f"consulta_cand_{ano}_RJ.csv")
    monkeypatch.setattr("compliance_agent.pcrj.comissionados_candidatos._cache_path",
                        lambda ano: tmp_path / f"consulta_cand_{ano}_RJ.csv")
    z = tmp_path / "consulta_cand_2026.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("consulta_cand_2026_RJ.csv", _csv(2026))
        f.writestr("consulta_cand_2026_SP.csv", _csv(2026))
    assert I.importar(z) == [2026]

    def sem_rede(*a, **k):
        raise AssertionError("não devia baixar: o cache existe")
    monkeypatch.setattr(requests, "get", sem_rede)
    assert T._csv_do_ano(2026) == _csv(2026)


def test_csv_solto_ano_pela_coluna(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "_cache_path", lambda ano: tmp_path / f"c_{ano}.csv")
    f = tmp_path / "candidatos.csv"
    f.write_bytes(_csv(2022))
    assert I.importar(f) == [2022]
    assert (tmp_path / "c_2022.csv").exists()
