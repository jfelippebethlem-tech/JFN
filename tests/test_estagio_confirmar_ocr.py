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

    def recorte(self, pdf, e5, numeros):
        return list(getattr(self, "rec", []))


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


# ── O3.6: SIAFE creditado (concordantes + precedência), recorte como fonte de nível A ─────────────────────────────
def test_siafe_concordante_nao_some_atras_da_leitura():
    """A causa do 'SIAFE 0/1.288': o legado creditava a 1ª fonte (a leitura) e o SIAFE, que também tinha o número,
    não aparecia. Agora todas as fontes ficam em `concordantes` e a gravada é a mais forte."""
    nums = [{"tipo": "cnpj", "norma": "11222333000181", "literal": "x", "pagina": 1},
            {"tipo": "valor", "norma": "1234.56", "literal": "1.234,56", "pagina": 1}]
    leituras = {"leitura:tesseract": "CNPJ 11.222.333/0001-81 total 1.234,56"}
    legado = C.P.confirmar_numeros(nums, leituras, {"siafe_ob": {("cnpj", "11222333000181")}}, None)
    assert {d["fonte"] for d in legado} == {"leitura:tesseract"}          # o defeito, medido no legado
    dec = {d["tipo"]: d for d in C.decidir(nums, leituras, {"siafe_ob": {("cnpj", "11222333000181")}})}
    assert dec["cnpj"]["fonte"] == "siafe_ob" and dec["cnpj"]["concordantes"] == ["siafe_ob", "leitura:tesseract"]
    assert dec["valor"]["fonte"] == "leitura:tesseract" and dec["valor"]["concordantes"] == ["leitura:tesseract"]
    ext = {"barras": {("cnpj", "11222333000181")}, "recorte:rapidocr@x": {("cnpj", "11222333000181")}}
    d = C.decidir(nums[:1], leituras, ext | {"siafe_ob": {("cnpj", "11222333000181")}})[0]
    assert d["concordantes"] == ["barras", "siafe_ob", "recorte:rapidocr@x", "leitura:tesseract"]
    assert C.nivel_a("recorte:rapidocr@x")


def test_siafe_chave_do_processo_pela_tag_do_acervo():
    """A tag do acervo (`030001_087722_2024`) e o número SEI dão a MESMA chave do join com o SIAFE."""
    from compliance_agent.ob_processo import chave_processo
    assert chave_processo("030001_087722_2024") == chave_processo("SEI-030001/087722/2024") == "030001/87722/2024"


@precisa_pg
def test_recorte_confirma_e_efeito_rederiva_do_texto(pg, tmp_path, monkeypatch):  # noqa: F811
    import json
    con, nome = pg
    pl, sha = _preparar(nome, tmp_path, monkeypatch, texto="emitente 11.222.333/0001-81")
    f = FontesFalsas(siafe={"siafe_ob": {("cnpj", "11222333000181")}})
    f.rec = [{"tipo": "cnpj", "norma": "11222333000181", "pagina": 2, "estado": "confere", "motor": "rapidocr@t",
              "bbox": [1, 2, 3, 4], "texto": "11.222.333/0001-81"}]
    r, ok = _e6(pl, sha, f, monkeypatch)
    assert ok, r.efeito["conferencia"]
    assert r.efeito["por_fonte"] == {"siafe_ob": 1} and r.efeito["por_fonte_concordante"] == {"siafe_ob": 1,
                                                                                              "recorte": 1}
    # recorte "confere" sem o número no texto guardado não conta (o efeito re-deriva do texto, não do estado)
    arq = T.caminho_lateral(PROC, "sei:111", sha, "e6", tmp_path / "texto")
    d = json.loads(arq.read_text(encoding="utf-8"))
    d["recortes"][0]["texto"] = "ilegível"
    T.gravar_lateral(arq, d)
    con.execute("UPDATE ocr_conferencia SET fontes = jsonb_set(fontes, '{lateral_sha}', to_jsonb(%s::text))",
                (T.ler_lateral(arq)[1],))
    c = C.conferir(con, r.efeito)
    assert not c["ok"] and not c["concordantes_na_fonte"] and c["confirmado_na_fonte"]


def test_barras_usa_todos_os_decodificadores_a_300dpi(tmp_path, monkeypatch):
    """O3.6: a união dos decodificadores (zxing-cpp + pyzbar) a 300 dpi; sem nenhum, indisponível declarado."""
    ch = _chave_nfe("11222333000181", "4321")
    pdf = pdf_de(tmp_path / "nf.pdf", ["escaneada"])
    vistos = []
    monkeypatch.setattr(C, "_decodificadores", lambda: [("a", lambda img: vistos.append(img.shape) or [ch]),
                                                       ("b", lambda img: [ch, "http://qr"])])
    r = C.barras(pdf, [1])
    assert r["disponivel"] and r["textos"] == [ch, "http://qr"] and r["dpi"] == 300
    assert r["chaves"] == [("cnpj", "11222333000181"), ("nf", "4321")] and len(vistos[0]) == 2   # cinza
    assert abs(vistos[0][0] - 842 * 300 / 72) <= 2                                   # 300 dpi
    monkeypatch.setattr(C, "_decodificadores", lambda: [])
    assert C.barras(pdf, [1])["disponivel"] is False


def test_leitura_independente_por_pagina_nunca_a_mesma_familia(monkeypatch, tmp_path):
    """O3.6: com páginas de motores diferentes (Surya + Tesseract, a volta), a página do Tesseract é relida pelo
    RapidOCR e só as outras pelo Tesseract — antes o Tesseract relia TODAS e confirmava a si mesmo."""
    pedidas = {}

    class CPU:
        def motor(self):
            return "rapidocr@t"

        def ler(self, pdf, paginas):
            pedidas["rapidocr"] = list(paginas)
            return {n: O.Leitura(f"rapid p{n}") for n in paginas}

    monkeypatch.setattr(O, "ExecutorCPU", CPU)
    monkeypatch.setattr(C.P, "ler_pdf", lambda pdf, pags, max_paginas, raster=None: pedidas.setdefault("tesseract", list(pags))
                        and {"leituras": {"tesseract": "tess"}})
    r = C.leitura_independente(tmp_path / "x.pdf", [1, 2, 3], {1: "surya@a", 2: "tesseract@b", 3: "rapidocr@c"})
    assert pedidas == {"rapidocr": [2], "tesseract": [1, 3]}
    assert r == {"leitura:rapidocr@t": "rapid p2", "leitura:tesseract": "tess"}
