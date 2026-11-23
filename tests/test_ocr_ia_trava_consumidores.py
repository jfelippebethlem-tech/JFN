# -*- coding: utf-8 -*-
"""A trava do OCR por IA nos consumidores que transformam texto SEI em prova: número de documento de IA não
confirmado não vira prova; confirmado vira; documento não-IA inalterado."""
import json
from pathlib import Path

import pytest

from compliance_agent.sei import ocr_ia_prova as P

CNPJ = "05.340.639/0001-30"
CONTRATO = ("A SECRETARIA, inscrita no CNPJ sob o nº 40.015.416/0001-06, doravante denominado CONTRATANTE, e a "
            f"empresa PRIME LTDA, inscrita no CNPJ sob o nº {CNPJ}, doravante denominada simplesmente CONTRATADA.")


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "LEDGER", tmp_path / "conf.jsonl")


def _pasta(tmp_path: Path, corpo: str, motor: str | None, tipo="contrato", tag="330020_000762_2021",
           titulo="Contrato"):
    pasta = tmp_path / "acervo" / tag
    (pasta / "texto").mkdir(parents=True, exist_ok=True)
    (pasta / "texto" / "000_doc.txt").write_text(f"[{titulo}] (tipo: {tipo})\n\n" + corpo, encoding="utf-8")
    d = {"i": 0, "titulo": titulo, "tipo": tipo, "texto": "texto/000_doc.txt"}
    if motor:
        d.update(ocr="True", ocr_motor=motor)
    (pasta / "manifest.json").write_text(json.dumps({"docs": [d]}), encoding="utf-8")
    return pasta, [d]


def _confirmar_tudo(tag, i, texto):
    P.registrar([{"tag": tag, "i": i, **x} for x in P.confirmar_numeros(P.extrair(texto), {"tesseract": texto})])


# ── Processo 360: CNPJ do contratado tirado do texto ──
def test_360_cnpj_de_ia_nao_confirmado_nao_vira_contratado(tmp_path):
    from compliance_agent import processo_360
    pasta, docs = _pasta(tmp_path, CONTRATO, "surya-ocr-2.5")
    assert processo_360._cnpj_do_texto(pasta, docs) is None
    _confirmar_tudo(pasta.name, 0, CONTRATO)
    assert processo_360._cnpj_do_texto(pasta, docs) == "05340639000130"


def test_360_doc_nao_ia_inalterado(tmp_path):
    from compliance_agent import processo_360
    pasta, docs = _pasta(tmp_path, CONTRATO, None)
    assert processo_360._cnpj_do_texto(pasta, docs) == "05340639000130"


# ── duplicidade de NF ──
NF = (f"NOTA FISCAL DE SERVIÇOS ELETRÔNICA\nNúmero da NFS-e: 187\nPrestador CNPJ {CNPJ}\n"
      "Valor dos serviços: R$ 100.033,95")


def _nf(tmp_path, monkeypatch, motor):
    from tools import resolver_duplicidade_nf as R
    pasta, _ = _pasta(tmp_path, NF, motor, tipo="nota_fiscal", tag="080002_000001_2024", titulo="Nota Fiscal 187")
    monkeypatch.setattr(R, "ARQUIVO", pasta.parent)
    return R, pasta


def test_nf_de_ia_sai_marcada_e_confirmada_sai_limpa(tmp_path, monkeypatch):
    R, pasta = _nf(tmp_path, monkeypatch, "surya-ocr-2.5")
    nf, = R.extrair_nfs(R.textos_do_processo(pasta.name))
    assert set(nf["ocr_ia_a_conferir"]) == {"numero", "cnpj", "valor"}
    _confirmar_tudo(pasta.name, 0, NF)
    nf, = R.extrair_nfs(R.textos_do_processo(pasta.name))
    assert "ocr_ia_a_conferir" not in nf and nf["numero"] == "187"


def test_nf_nao_ia_inalterada(tmp_path, monkeypatch):
    R, pasta = _nf(tmp_path, monkeypatch, None)
    nf, = R.extrair_nfs(R.textos_do_processo(pasta.name))
    assert "ocr_ia_a_conferir" not in nf


def test_resolver_competencia_com_nf_de_ia_a_conferir_e_indeterminado(tmp_path, monkeypatch):
    R, pasta = _nf(tmp_path, monkeypatch, "surya-ocr-2.5")
    monkeypatch.setattr(R, "afastado_pelo_historico", lambda comp, obs: None)
    obs = [{"numero_ob": "2024OB1", "processo": "SEI-080002/000001/2024", "valor": 100033.95},
           {"numero_ob": "2024OB2", "processo": "SEI-080002/000001/2024", "valor": 100033.95}]
    r = R.resolver_competencia("05340639000130", "01/2024", obs)
    assert r["veredito"] == "INDETERMINADO" and r["camada"] == "ocr_ia_a_conferir"


# ── ficha do acervo: fonte de conferência ──
def test_ficha_nao_confere_numero_de_ia_nao_confirmado(tmp_path):
    from tools import sei_ficha_acervo as F
    pasta, _ = _pasta(tmp_path, CONTRATO, "surya-ocr-2.5")
    fonte = F.fonte_de_conferencia(pasta, "janela " + CONTRATO)
    assert CNPJ not in fonte and P.MARCA in fonte and "PRIME LTDA" in fonte
    _confirmar_tudo(pasta.name, 0, CONTRATO)
    assert CNPJ in F.fonte_de_conferencia(pasta, "janela " + CONTRATO)


def test_ficha_doc_nao_ia_inalterada(tmp_path):
    from tools import sei_ficha_acervo as F
    pasta, _ = _pasta(tmp_path, CONTRATO, None)
    assert P.MARCA not in F.fonte_de_conferencia(pasta, CONTRATO)


# ── detectores de padrão (todas as famílias) ──
def test_achado_com_prova_de_ia_nao_confirmada_cai_para_fraco(tmp_path, monkeypatch):
    from compliance_agent.padroes import _comum
    from compliance_agent.sei import acervo_texto
    pasta, _ = _pasta(tmp_path, CONTRATO + " Valor global R$ 1.500.000,00.", "surya-ocr-2.5")
    monkeypatch.setattr(acervo_texto, "RAIZ", pasta.parent)
    a = {"processo": "SEI-330020/000762/2021", "grau": "forte", "prova": "valor global R$ 1.500.000,00"}
    b = {"processo": "SEI-330020/000762/2021", "grau": "forte", "prova": "sem número nenhum"}
    _comum.travar_ocr_ia([a, b])
    assert (a["grau"], a["grau_antes_ocr_ia"], a["ocr_ia_a_conferir"]) == ("fraco", "forte", ["1.500.000,00"])
    assert b["grau"] == "forte" and "ocr_ia_a_conferir" not in b


def test_achado_de_processo_sem_ia_intocado(tmp_path, monkeypatch):
    from compliance_agent.padroes import _comum
    from compliance_agent.sei import acervo_texto
    pasta, _ = _pasta(tmp_path, CONTRATO + " R$ 1.500.000,00", None)
    monkeypatch.setattr(acervo_texto, "RAIZ", pasta.parent)
    a = {"processo": "SEI-330020/000762/2021", "grau": "forte", "prova": "R$ 1.500.000,00"}
    assert _comum.travar_ocr_ia([dict(a)]) == [a]


# ── juízo por documento ──
def test_juizo_de_doc_ia_leva_os_numeros_a_conferir(tmp_path):
    from compliance_agent.sei import doc_juizo
    pasta, docs = _pasta(tmp_path, CONTRATO, "surya-ocr-2.5")
    v = doc_juizo._anotar_ocr_ia({"escala": 1}, pasta, docs[0], CONTRATO)
    assert CNPJ in v["ocr_ia_a_conferir"]
    pasta2, docs2 = _pasta(tmp_path / "b", CONTRATO, None)
    assert "ocr_ia_a_conferir" not in doc_juizo._anotar_ocr_ia({"escala": 1}, pasta2, docs2[0], CONTRATO)
