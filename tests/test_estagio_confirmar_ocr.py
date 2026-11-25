# -*- coding: utf-8 -*-
"""E6 `confirmar_ocr` (O3.4): número do OCR só vira confirmado com NÍVEL A (leitura independente, SIAFE do mesmo
processo, código de barras decodificado); fonte abaixo de A (outro documento) não confirma; documento confirmado só
com todos; números só das páginas LIDAS por OCR; idempotência; efeito que pega confirmação sem a fonte. Fontes FALSAS."""
from compliance_agent.aplicacao.estagios import confirmar_ocr as C
from compliance_agent.aplicacao.estagios import estagio_de
from compliance_agent.aplicacao.estagios import ocr as O
from compliance_agent.aplicacao.estagios import texto as T
from compliance_agent.nfe_verifica import digito_verificador
from tests.fluxo_pg import DSN, precisa_pg
from tests.test_estagio_ocr import Falso
from tests.test_estagio_texto import PROC, ctx, pdf_de, pg, rodar_e4  # noqa: F401 — fixture do esquema temporário

LIDO = "Empresa CNPJ 11.222.333/0001-81 — total R$ 1.234,56 em 10/11/2026"


class FontesFalsas:
    def __init__(self, leitura="", siafe=None, barras=None):
        self.l, self.s, self.b = leitura, siafe or {}, barras

    def leitura(self, pdf, paginas, motores):
        return {"leitura:tesseract": self.l} if self.l else {}

    def barras(self, pdf, paginas):
        if self.b is None:
            return {"disponivel": False, "motivo": "teste", "textos": [], "chaves": []}
        return {"disponivel": True, "textos": self.b, "chaves": sorted(C.chaves_de_barras(self.b))}

    def siafe(self, processo):
        return {"disponivel": True, "chaves": {k: sorted(v) for k, v in self.s.items()}}


def _chave_nfe(cnpj: str, numero: str) -> str:
    base = "33" + "2611" + cnpj + "55" + "001" + numero.zfill(9) + "1" + "12345678"
    return base + str(digito_verificador(base))


def test_nivel_a_e_decisao_sem_fonte_b():
    assert C.nivel_a("leitura:tesseract") and C.nivel_a("siafe_ob") and C.nivel_a("barras")
    assert not C.nivel_a("documento_3") and not C.nivel_a(None)
    nums = [{"tipo": "cnpj", "norma": "11222333000181", "literal": "x", "pagina": 1}]
    # o legado aceitava "outro documento do processo": aqui não entra, então fica a conferir
    assert C.decidir(nums, {}, {})[0]["estado"] == C.A_CONFERIR
    assert C.decidir(nums, {}, {"siafe_ob": {("cnpj", "11222333000181")}})[0]["fonte"] == "siafe_ob"


def test_codigo_de_barras_decodificado_da_cnpj_e_nf():
    ch = _chave_nfe("11222333000181", "4321")
    assert C.chaves_de_barras([ch]) == {("cnpj", "11222333000181"), ("nf", "4321")}
    assert C.chaves_de_barras([ch[:-1] + str((int(ch[-1]) + 1) % 10)]) == set()   # DV errado não vale
    assert estagio_de("confirmar_ocr:x") is C.ESTAGIO


def _preparar(nome, tmp_path, monkeypatch, texto=LIDO):
    pdf = pdf_de(tmp_path / "001.pdf", ["nativa", "escaneada"])        # o nativo também tem CNPJ/valor: não conta
    rodar_e4(nome, tmp_path, pdf)
    sha = T.sha256_arquivo(pdf)
    monkeypatch.setattr(O, "obter_executores", lambda no: (Falso("rapidocr", {2: texto}), None))
    pl = {"processo": PROC, "doc_id": "sei:111", "sha256": sha, "arquivo": str(pdf), "dsn": DSN, "esquema": nome,
          "raiz_texto": str(tmp_path / "texto")}
    r = O._handler(pl, ctx("ocr", "sei:111", sha))
    assert O._efeito(pl, ctx("ocr", "sei:111", sha), r)
    return pl, sha


def _e6(pl, sha, fontes, monkeypatch, ficha=1):
    monkeypatch.setattr(C, "obter_fontes", lambda: fontes)
    c = ctx("confirmar_ocr", "sei:111", sha, ficha)
    r = C._handler(pl, c)
    return r, C._efeito(pl, c, r)


@precisa_pg
def test_so_nivel_a_confirma_e_documento_so_com_todos(pg, tmp_path, monkeypatch):  # noqa: F811
    con, nome = pg
    pl, sha = _preparar(nome, tmp_path, monkeypatch)
    r, ok = _e6(pl, sha, FontesFalsas(leitura="total R$ 1.234,56"), monkeypatch)
    assert ok, r.efeito["conferencia"]
    assert r.efeito["estado"] == C.A_CONFERIR and r.efeito["numeros"] == 3 and r.efeito["confirmados"] == 1
    est = dict(con.execute("SELECT tipo, estado FROM ocr_numero").fetchall())
    assert est == {"valor": "confirmado", "cnpj": "a_conferir", "data": "a_conferir"}
    # SIAFE confirma o CNPJ; leitura independente a data ⇒ todos em nível A ⇒ documento confirmado
    f = FontesFalsas(leitura="total R$ 1.234,56 em 10/11/2026", siafe={"siafe_ob": {("cnpj", "11222333000181")}})
    r, ok = _e6(pl, sha, f, monkeypatch, ficha=2)
    assert ok and r.efeito["estado"] == C.CONFIRMADO and r.efeito["por_fonte"] == {"leitura": 2, "siafe_ob": 1}
    assert con.execute("SELECT count(*) FROM ocr_numero").fetchone()[0] == 3          # substituído, não duplicado
    assert con.execute("SELECT count(*) FROM ocr_conferencia").fetchone()[0] == 1


@precisa_pg
def test_barras_confirma_cnpj_e_efeito_pega_confirmacao_sem_fonte(pg, tmp_path, monkeypatch):  # noqa: F811
    con, nome = pg
    pl, sha = _preparar(nome, tmp_path, monkeypatch, texto="NF-e emitente 11.222.333/0001-81")
    r, ok = _e6(pl, sha, FontesFalsas(barras=[_chave_nfe("11222333000181", "1")]), monkeypatch)
    assert ok and r.efeito["estado"] == C.CONFIRMADO and r.efeito["por_fonte"] == {"barras": 1}
    con.execute("UPDATE ocr_numero SET fonte = 'siafe_ob'")             # "confirmado" por fonte que não o tem
    c = ctx("confirmar_ocr", "sei:111", sha)
    assert not C._efeito(pl, c, r)
