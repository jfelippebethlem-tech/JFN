# -*- coding: utf-8 -*-
"""E7 `arquivar` (O3.4): NÃO APAGA SEM HASH (cópia sem o md5 local ⇒ o original fica e o efeito falha), nada que o
E5 ainda precisa sai da VM-2 (página escaneada sem OCR terminado; item na fila legada de OCR), o arquivo tem de ser a
versão, apagar só a pedido, idempotência (o já arquivado é `ja_arquivado`) e efeito que confere no índice. Destino
FALSO (a porta única de verdade sobe para a nuvem: nunca em teste)."""
import pytest

from compliance_agent.aplicacao.estagios import ErroPermanente, estagio_de
from compliance_agent.aplicacao.estagios import arquivar as E7
from compliance_agent.aplicacao.estagios import ocr as O
from compliance_agent.aplicacao.estagios import texto as T
from tests.fluxo_pg import DSN, precisa_pg
from tests.test_estagio_ocr import Falso
from tests.test_estagio_texto import PROC, ctx, pdf_de, pg, rodar_e4  # noqa: F401 — fixture do esquema temporário


class NuvemFalsa:
    nome = "teste"

    def __init__(self, corromper=False, fora=False):
        self.guardado, self.corromper, self.fora, self.apagados = {}, corromper, fora, []

    def guardar(self, arquivo):
        if self.fora:
            raise RuntimeError("nuvem fora do ar — fica quente")
        md5 = E7.md5_arquivo(arquivo)
        chave = f"vm2/{arquivo.name}"
        self.guardado[chave] = "0" * 32 if self.corromper else md5         # cópia que não bate com o local
        return {"chave": chave, "md5": self.guardado[chave], "copias": {"gdrive": "ok"}}

    def conferir(self, chave, md5):
        return self.guardado.get(chave) == md5

    def registrar_apagado(self, chave, arquivo):
        self.apagados.append(chave)


def _e7(nome, tmp_path, pdf, sha, nuvem, monkeypatch, ficha=1, legada=(), **extra):
    monkeypatch.setattr(E7, "obter_destino", lambda: nuvem)
    monkeypatch.setattr(E7, "obter_fila_legada", lambda: set(legada))
    c = ctx("arquivar", "sei:111", sha, ficha)
    pl = {"processo": PROC, "doc_id": "sei:111", "sha256": sha, "arquivo": str(pdf), "dsn": DSN, "esquema": nome,
          "raiz_texto": str(tmp_path / "texto"), **extra}
    r = E7._handler(pl, c)
    return r, E7._efeito(pl, c, r)


def test_registro():
    assert estagio_de("arquivar:x") is E7.ESTAGIO and E7.ESTAGIO.recursos == ["disco"]


@precisa_pg
def test_nao_apaga_sem_hash(pg, tmp_path, monkeypatch):  # noqa: F811
    con, nome = pg
    pdf = pdf_de(tmp_path / "001.pdf", ["nativa"])
    rodar_e4(nome, tmp_path, pdf)
    sha = T.sha256_arquivo(pdf)
    r, ok = _e7(nome, tmp_path, pdf, sha, NuvemFalsa(corromper=True), monkeypatch)
    assert not ok and pdf.is_file() and not r.efeito["apagado"] and r.eventos == []
    assert con.execute("SELECT count(*) FROM arquivamento").fetchone()[0] == 0
    with pytest.raises(RuntimeError, match="fica quente"):
        _e7(nome, tmp_path, pdf, sha, NuvemFalsa(fora=True), monkeypatch)
    assert pdf.is_file()


@precisa_pg
def test_escaneada_sem_ocr_nao_sai_e_depois_do_ocr_sai(pg, tmp_path, monkeypatch):  # noqa: F811
    con, nome = pg
    pdf = pdf_de(tmp_path / "001.pdf", ["nativa", "escaneada"])
    rodar_e4(nome, tmp_path, pdf)
    sha = T.sha256_arquivo(pdf)
    with pytest.raises(E7.OcrPendente):
        _e7(nome, tmp_path, pdf, sha, NuvemFalsa(), monkeypatch)
    assert pdf.is_file()
    monkeypatch.setattr(O, "obter_executores", lambda no: (Falso("rapidocr", {2: "lido"}), None))
    pl = {"processo": PROC, "doc_id": "sei:111", "sha256": sha, "arquivo": str(pdf), "dsn": DSN, "esquema": nome,
          "raiz_texto": str(tmp_path / "texto")}
    assert O._efeito(pl, ctx("ocr", "sei:111", sha), O._handler(pl, ctx("ocr", "sei:111", sha)))
    nuvem = NuvemFalsa()
    r, ok = _e7(nome, tmp_path, pdf, sha, nuvem, monkeypatch)
    assert ok and r.efeito["apagado"] and not pdf.exists() and nuvem.apagados == [f"vm2/{pdf.name}"]
    assert r.efeito["liberado_bytes"] > 0 and r.eventos[0]["tipo"] == "arquivado"
    # idempotente: de novo, o original já saiu com cópia conferida
    r2, ok2 = _e7(nome, tmp_path, pdf, sha, nuvem, monkeypatch, ficha=2)
    assert ok2 and r2.efeito["ja_arquivado"]
    assert con.execute("SELECT count(*), bool_and(apagado) FROM arquivamento").fetchone() == (1, True)


@precisa_pg
def test_fila_legada_de_ocr_segura_o_original(pg, tmp_path, monkeypatch):  # noqa: F811
    _, nome = pg
    raiz = tmp_path / "frio"
    (raiz / "integra_270006_000236_2026").mkdir(parents=True)
    pdf = pdf_de(raiz / "integra_270006_000236_2026" / "007.pdf", ["escaneada"])
    monkeypatch.setenv(O.ENV_RAIZES, str(raiz))
    rel = "integra_270006_000236_2026/007.pdf"
    with pytest.raises(E7.OcrPendente, match="fila legada"):
        _e7(nome, tmp_path, pdf, "", NuvemFalsa(), monkeypatch, legada={rel}, rel=rel, arquivo=None)
    r, ok = _e7(nome, tmp_path, pdf, "", NuvemFalsa(), monkeypatch, rel=rel, arquivo=None, apagar=False)
    assert ok and pdf.is_file() and not r.efeito["apagado"] and r.efeito["sha256"] == T.sha256_arquivo(pdf)


@precisa_pg
def test_arquivo_que_nao_e_a_versao_e_permanente(pg, tmp_path, monkeypatch):  # noqa: F811
    _, nome = pg
    pdf = pdf_de(tmp_path / "001.pdf", ["nativa"])
    rodar_e4(nome, tmp_path, pdf)
    sha = T.sha256_arquivo(pdf)
    pdf.write_bytes(pdf.read_bytes() + b"%outro")
    with pytest.raises(ErroPermanente):
        _e7(nome, tmp_path, pdf, sha, NuvemFalsa(), monkeypatch)
    assert pdf.is_file()


@precisa_pg
def test_insert_que_falha_nao_apaga_o_original(pg, tmp_path, monkeypatch):  # noqa: F811
    """Revisão de falhas caladas 1.4: o registro no PG vem ANTES do unlink — INSERT que falha deixa o original."""
    con, nome = pg
    pdf = pdf_de(tmp_path / "001.pdf", ["nativa"])
    rodar_e4(nome, tmp_path, pdf)
    sha = T.sha256_arquivo(pdf)
    con.execute("ALTER TABLE arquivamento ADD CONSTRAINT t_falha CHECK (false) NOT VALID")    # todo INSERT falha
    nuvem = NuvemFalsa()
    with pytest.raises(Exception, match="t_falha"):
        _e7(nome, tmp_path, pdf, sha, nuvem, monkeypatch)
    assert pdf.is_file() and nuvem.apagados == []


@precisa_pg
def test_retomada_termina_registro_apagado_false_cujo_arquivo_sumiu(pg, tmp_path, monkeypatch):  # noqa: F811
    """1.4: queda entre o unlink e o UPDATE deixa apagado=false sem arquivo; a retomada confere a cópia e termina."""
    con, nome = pg
    pdf = pdf_de(tmp_path / "001.pdf", ["nativa"])
    rodar_e4(nome, tmp_path, pdf)
    sha = T.sha256_arquivo(pdf)
    con.execute("ALTER TABLE arquivamento ADD CONSTRAINT t_falha CHECK (NOT apagado) NOT VALID")  # UPDATE falha
    nuvem = NuvemFalsa()
    with pytest.raises(Exception, match="t_falha"):
        _e7(nome, tmp_path, pdf, sha, nuvem, monkeypatch)
    assert not pdf.exists()
    assert con.execute("SELECT count(*), bool_or(apagado) FROM arquivamento").fetchone() == (1, False)
    con.execute("ALTER TABLE arquivamento DROP CONSTRAINT t_falha")
    # cópia que não confere: não marca
    with pytest.raises(RuntimeError, match="não confere"):
        _e7(nome, tmp_path, pdf, sha, NuvemFalsa(), monkeypatch, ficha=2)
    assert con.execute("SELECT bool_or(apagado) FROM arquivamento").fetchone() == (False,)
    r, ok = _e7(nome, tmp_path, pdf, sha, nuvem, monkeypatch, ficha=3)
    assert ok and r.efeito["ja_arquivado"] and r.efeito["apagado"]
    assert con.execute("SELECT count(*), bool_and(apagado) FROM arquivamento").fetchone() == (1, True)
