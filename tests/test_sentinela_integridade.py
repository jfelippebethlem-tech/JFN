# -*- coding: utf-8 -*-
"""A sentinela de integridade precisa GRITAR nas falhas de 2026-08-02 — e calar no dado bom.

Toda falha daquela madrugada passou verde no `pipelines_slo`: produziram no prazo, com conteúdo
corrompido. Estes testes travam as invariantes contra os três padrões reais (cache inflado por
binário, texto amputado no teto, processo arquivado sem texto) usando dados sintéticos.
"""
import json

import pytest

from tools import sei_purgar_anexo_cache as purga
from tools import sentinela_integridade as S


@pytest.fixture()
def acervo(tmp_path, monkeypatch):
    arq = tmp_path / "sei_arquivo"
    cac = tmp_path / "sei_cache"
    arq.mkdir()
    cac.mkdir()
    monkeypatch.setattr(S, "ARQUIVO", arq)
    monkeypatch.setattr(S, "CACHE", cac)
    monkeypatch.setattr(S, "TETO_CHARS", 1000)
    monkeypatch.setattr(S, "TETO_CACHE_MB", 0.001)   # 1 KB, para caber no teste
    return arq, cac


def _manifest(base, nome, docs):
    d = base / nome
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"processo": nome, "docs": docs}), encoding="utf-8")
    return d


def test_cache_obeso_grita_e_aponta_o_arquivo(acervo):
    _, cac = acervo
    (cac / "cdp_gordo.json").write_text("x" * 5000, encoding="utf-8")
    (cac / "cdp_magro.json").write_text("{}", encoding="utf-8")
    r = S.inv_cache_obeso()
    assert r["estado"] == "violado" and r["medida"] == 1
    assert r["evidencia"][0]["arquivo"] == "cdp_gordo.json"


def test_cache_dentro_do_limite_nao_grita(acervo):
    _, cac = acervo
    (cac / "cdp_ok.json").write_text("{}", encoding="utf-8")
    assert S.inv_cache_obeso()["estado"] == "ok"


def test_corte_no_teto_denuncia_amputacao(acervo):
    arq, _ = acervo
    _manifest(arq, "proc_cortado", [{"i": i, "chars": 1000} for i in range(10)])
    r = S.inv_corte_no_teto()
    assert r["estado"] == "violado", "10/10 documentos exatamente no teto tem de gritar"
    assert r["medida"] == 100.0


def test_documento_longo_isolado_nao_e_amputacao(acervo):
    arq, _ = acervo
    docs = [{"i": i, "chars": 300} for i in range(50)] + [{"i": 99, "chars": 1000}]
    _manifest(arq, "proc_normal", docs)
    assert S.inv_corte_no_teto()["estado"] == "ok", "1 doc no teto em 51 é normal, não amputação"


def test_arquivo_sem_texto_e_captura_vazia_silenciosa(acervo):
    arq, _ = acervo
    _manifest(arq, "proc_vazio", [{"i": 0, "chars": 0}, {"i": 1, "chars": 12}])
    r = S.inv_arquivo_sem_texto() if hasattr(S, "inv_arquivo_sem_texto") else S.inv_arquivo_vazio()
    assert r["estado"] == "violado" and "proc_vazio" in r["evidencia"]


def test_captura_vazia_declarada_nao_conta_como_violacao(acervo):
    """Manifest que DIZ que a captura foi vazia é honesto — o problema é o silêncio."""
    arq, _ = acervo
    d = arq / "proc_declarado"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"docs": [], "captura_vazia": True}), encoding="utf-8")
    r = S.inv_arquivo_vazio()
    assert "proc_declarado" not in r["evidencia"]


def test_checar_nunca_levanta_mesmo_com_acervo_quebrado(acervo, monkeypatch):
    monkeypatch.setattr(S, "inv_cache_obeso", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(S, "INVARIANTES", (S.inv_cache_obeso, S.inv_arquivo_vazio))
    res = S.checar()
    assert any(r["estado"] == "erro" for r in res), "a sentinela não pode derrubar o cron"


# ---- purga do anexo_bytes ----

def test_purga_remove_so_o_binario_e_preserva_o_texto():
    d = {"numero": "X", "conteudo_documentos": [
        {"doc": "parecer", "conteudo": "TEXTO QUE IMPORTA", "via": "arvore", "anexo_bytes": "b'%PDF-1.4...'"},
        {"doc": "outro", "conteudo": "mais texto", "via": "ocr"},
    ]}
    limpo, n = purga.purgar_dict(d)
    assert n == 1
    assert "anexo_bytes" not in limpo["conteudo_documentos"][0]
    assert limpo["conteudo_documentos"][0]["conteudo"] == "TEXTO QUE IMPORTA"
    assert limpo["conteudo_documentos"][1] == d["conteudo_documentos"][1]


def test_purga_e_idempotente():
    d = {"conteudo_documentos": [{"conteudo": "t"}]}
    limpo, n = purga.purgar_dict(d)
    assert n == 0 and limpo == d


def test_purga_de_arquivo_escreve_atomico_e_encolhe(tmp_path):
    p = tmp_path / "cdp_teste.json"
    p.write_text(json.dumps({"conteudo_documentos": [
        {"conteudo": "curto", "anexo_bytes": "b'" + "A" * 20000 + "'"}]}), encoding="utf-8")
    antes = p.stat().st_size
    r = purga.purgar_arquivo(p, aplicar=True)
    assert r["removidos"] == 1
    assert p.stat().st_size < antes / 5
    assert json.loads(p.read_text(encoding="utf-8"))["conteudo_documentos"][0]["conteudo"] == "curto"
    assert not list(tmp_path.glob("*.purga")), "sobrou arquivo temporário"


# ---- reparo dos arquivos sem texto ----

def test_reparo_declara_captura_vazia_e_refila(tmp_path, monkeypatch):
    """Captura incompleta virada acervo: a cura é DECLARAR (não apagar) e devolver à fila."""
    import json as _j

    from tools import sei_reparar_truncados as R

    arq = tmp_path / "sei_arquivo"
    (arq / "080002_014849_2026").mkdir(parents=True)
    (arq / "080002_014849_2026" / "manifest.json").write_text(
        _j.dumps({"processo": "080002/014849/2026", "docs": [{"i": 0, "chars": 0}, {"i": 1, "chars": 10}]}),
        encoding="utf-8")
    (arq / "070002_000001_2024").mkdir(parents=True)
    (arq / "070002_000001_2024" / "manifest.json").write_text(
        _j.dumps({"docs": [{"i": 0, "chars": 900}]}), encoding="utf-8")   # tem texto: não mexer

    prog = tmp_path / "progress.json"
    prog.write_text(_j.dumps({"feitos": {"SEI-080002/014849/2026": {"n_docs": 25, "tentativas": 1}}}))
    monkeypatch.setattr(R, "RAIZ", tmp_path)
    monkeypatch.setattr(R, "PROGRESS", prog)
    monkeypatch.setattr(R, "CACHE", tmp_path / "sei_cache")
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setattr(R, "RAIZ", tmp_path)
    # a função monta o caminho como RAIZ/data/sei_arquivo — espelha isso
    (tmp_path / "data").mkdir(exist_ok=True)
    import shutil
    shutil.move(str(arq), str(tmp_path / "data" / "sei_arquivo"))

    r = R.reparar_sem_texto(aplicar=True, max_n=10)
    assert r["encontrados"] == 1, "só o processo SEM texto entra"
    m = _j.loads((tmp_path / "data" / "sei_arquivo" / "080002_014849_2026" / "manifest.json").read_text())
    assert m["captura_vazia"] is True and "reprocessar" in m["aviso"]
    intacto = _j.loads((tmp_path / "data" / "sei_arquivo" / "070002_000001_2024" / "manifest.json").read_text())
    assert "captura_vazia" not in intacto, "processo com texto não pode ser marcado"
    feitos = _j.loads(prog.read_text())["feitos"]
    assert feitos["SEI-080002/014849/2026"]["n_docs"] == 0, "não voltou à fila"
