# -*- coding: utf-8 -*-
"""Consertos do ensaio O8.5 no E5/E6 (frente A): (1) o Tesseract tira texto e bbox da MESMA imagem (o texto vinha da
pré-processada e a bbox da crua, vazia ⇒ `texto_com_bbox: false`); (2) leitura única DENTRO do job: cada PDF aberto
1× e cada (sha256, página, dpi) rasterizado 1× — hash da imagem, 1º e 2º motor (E5), leitura independente, barras e
recorte (E6). Motores FALSOS (nenhum OCR de verdade); o `get_pixmap` e o `fitz.open` são contados."""
import pytest

from compliance_agent.aplicacao.estagios import ocr as O
from compliance_agent.aplicacao.estagios import texto as T
from tests.test_estagio_ocr import _pdf_repetido


# ── (1) Tesseract: texto e bbox da mesma imagem ──────────────────────────────────────────────────────────────────
def _tesseract_falso(monkeypatch, texto_pre: str, texto_cru: str):
    """Pré-processada = 2D (cinza binarizada), crua = 3D (RGB). Cada imagem tem as SUAS palavras."""
    pytesseract = pytest.importorskip("pytesseract")
    from compliance_agent.sei import ocr_docs

    def texto_de(img):
        return texto_pre if img.ndim == 2 else texto_cru

    def para_string(img, lang=None, **kw):
        return texto_de(img)

    def para_dados(img, lang=None, output_type=None, **kw):
        ps = texto_de(img).split()
        return {"text": ps, "left": [10 * i for i in range(len(ps))], "top": [5] * len(ps),
                "width": [8] * len(ps), "height": [9] * len(ps), "conf": [90.0] * len(ps)}
    monkeypatch.setattr(ocr_docs, "_preprocess_para_ocr", lambda img: img[:, :, 0].copy())
    monkeypatch.setattr(pytesseract, "image_to_string", para_string)
    monkeypatch.setattr(pytesseract, "image_to_data", para_dados)


def test_tesseract_bbox_sai_da_imagem_que_deu_o_texto(monkeypatch):
    """O caso do ensaio (030002/006189/2026 sei:132894206 p3): a pré-processada leu 35 caracteres, a crua nada."""
    import numpy as np
    _tesseract_falso(monkeypatch, "7 ainda de dat o Na Amada pra", "")
    le = O.ExecutorTesseract().ler_img(np.zeros((40, 60, 3), dtype=np.uint8))
    assert O.util(le.texto) and le.linhas                       # antes: texto com 35 chars e 0 linhas
    assert [x["texto"] for x in le.linhas] == le.texto.split()


def test_tesseract_crua_vence_e_a_bbox_e_da_crua(monkeypatch):
    import numpy as np
    _tesseract_falso(monkeypatch, "x", "NOTA FISCAL 123 VALOR TOTAL R$ 1.234,56 " * 3)
    le = O.ExecutorTesseract().ler_img(np.zeros((40, 60, 3), dtype=np.uint8))
    assert le.texto.startswith("NOTA FISCAL") and [x["texto"] for x in le.linhas] == le.texto.split()


def test_ocr_tesseract_da_casa_devolve_o_mesmo_texto(monkeypatch):
    """O `_ocr_tesseract` (usado fora do E5) devolve exatamente o texto do `_ocr_tesseract_lido`."""
    import numpy as np

    from compliance_agent.sei import ocr_docs
    _tesseract_falso(monkeypatch, "lido na pré-processada", "")
    img = np.zeros((40, 60, 3), dtype=np.uint8)
    assert ocr_docs._ocr_tesseract(img, "por") == ocr_docs._ocr_tesseract_lido(img, "por")[0] == \
        "lido na pré-processada"


# ── (2) rasterização única no job ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def conta(monkeypatch):
    """{"pix": {(arquivo, página, dpi): n}, "open": {arquivo: n}} de tudo que o código rasteriza/abre."""
    import fitz
    c = {"pix": {}, "open": {}}
    orig_pix, orig_open = fitz.Page.get_pixmap, fitz.open

    def get_pixmap(self, *a, **kw):
        k = (self.parent.name.rsplit("/", 1)[-1], self.number + 1, kw.get("dpi"))
        c["pix"][k] = c["pix"].get(k, 0) + 1
        return orig_pix(self, *a, **kw)

    def abrir(*a, **kw):
        if a and str(a[0]).endswith(".pdf"):
            c["open"][str(a[0]).rsplit("/", 1)[-1]] = c["open"].get(str(a[0]).rsplit("/", 1)[-1], 0) + 1
        return orig_open(*a, **kw)
    monkeypatch.setattr(fitz.Page, "get_pixmap", get_pixmap)
    monkeypatch.setattr(fitz, "open", abrir)
    return c


class Motor:
    """Executor que rasteriza de verdade (`O._imagens`, como os reais) e lê por tabela {cor do pixel: texto}."""

    def __init__(self, familia, por_cor):
        self.familia, self.por_cor, self.imagens = familia, por_cor, 0

    def motor(self):
        return f"{self.familia}@teste"

    def ler(self, pdf, paginas):
        return {n: self.ler_img(img) for n, img, _, _ in O._imagens(pdf, paginas)}

    def ler_img(self, img):
        self.imagens += 1
        t = self.por_cor.get(int(img[img.shape[0] // 2, img.shape[1] // 2, 0]), "")
        return O.Leitura(t, [{"texto": t, "bbox": [1, 2, 3, 4], "conf": 0.9}] if t else [], img.shape[1],
                         img.shape[0])


def test_e5_rasteriza_cada_pagina_uma_vez_e_o_resultado_nao_muda(tmp_path, conta):
    pdf = _pdf_repetido(tmp_path / "e5.pdf", [200, 150, 100])
    e4 = T.extrair(pdf)

    def rodar():
        conta["pix"].clear()
        conta["open"].clear()
        # a página de cor 150 sai vazia no 1º motor e o 2º lê (o caminho do caso do ensaio)
        return O.ocr_documento(pdf, e4, Motor("rapidocr", {200: "NF 1 R$ 10,00", 100: "recibo"}),
                               Motor("tesseract", {150: "lido pelo segundo"}), None)
    antes = rodar()
    assert conta["pix"][("e5.pdf", 2, O.DPI)] == 3 and conta["open"]["e5.pdf"] == 3     # o defeito: hash+m1+m2
    with O.rasterizacao_unica() as ras:
        depois = rodar()
    assert set(conta["pix"].values()) == {1} and len(conta["pix"]) == 3 and conta["open"] == {"e5.pdf": 1}
    assert depois == antes                                       # mesmas leituras, mesmos hashes, mesmo composto
    assert ras.resumo() == {"rasterizacoes": 3, "rasterizacoes_distintas": 3, "rasterizacoes_repetidas": 0,
                            "pdf_aberturas": 1}


def test_e5_em_lotes_cada_pagina_rasterizada_uma_vez_com_o_orcamento_de_um_lote(tmp_path, conta, monkeypatch):
    """Achado 1.10: documento acima do teto é lido em lotes; o lote solta as imagens dele antes do próximo, então o
    orçamento de UM lote basta e nenhuma página é renderizada 2× (hash, 1º e 2º motor na mesma imagem)."""
    monkeypatch.setattr(O, "MAX_PAGINAS", 2)
    pdf = _pdf_repetido(tmp_path / "lotes.pdf", [200, 150, 100])
    with O.rasterizacao_unica(orcamento=0) as medida:
        uma = medida.imagem(pdf, 1)
    conta["pix"].clear()
    with O.rasterizacao_unica(orcamento=2 * uma.nbytes) as ras:
        r = O.ocr_documento(pdf, T.extrair(pdf), Motor("rapidocr", {200: "um", 100: "tres"}),
                            Motor("tesseract", {150: "dois"}), None)
    assert r["pendentes"] == [] and r["paginas"]["2"]["motor"] == "tesseract@teste"
    assert ras.resumo()["rasterizacoes_repetidas"] == 0 and len(conta["pix"]) == 3


def test_e6_barras_leitura_e_recorte_uma_renderizacao_por_pagina_e_dpi(tmp_path, conta, monkeypatch):
    import numpy as np

    from compliance_agent.aplicacao.estagios import confirmar_ocr as C
    from compliance_agent.aplicacao.estagios import ocr_recorte as R
    from compliance_agent.sei import ocr_docs
    from tests.test_ocr_recorte import NUM, LeitorFalso, _e5
    pdf = _pdf_repetido(tmp_path / "e6.pdf", [230])
    vistas = []
    monkeypatch.setattr(ocr_docs, "_ocr_tesseract", lambda img, lang: vistas.append(np.asarray(img).copy()) or "")

    def fontes():
        list(C._paginas_cinza(pdf, [1]))                         # barras: 300 dpi, cinza
        C.leitura_independente(pdf, [1], {1: "surya@a"})        # Tesseract da casa a 200 dpi
        R.conferir(pdf, _e5(), NUM, {"rapidocr": LeitorFalso("rapidocr", "R$ 1.234,56")})   # recorte a 200 dpi
    fontes()
    assert conta["pix"][("e6.pdf", 1, O.DPI)] == 2 and conta["open"]["e6.pdf"] == 3     # o defeito
    sem = vistas.pop()
    conta["pix"].clear()
    conta["open"].clear()
    with O.rasterizacao_unica() as ras:
        fontes()
    assert conta["pix"] == {("e6.pdf", 1, C.DPI_BARRAS): 1, ("e6.pdf", 1, O.DPI): 1} and conta["open"] == {"e6.pdf": 1}
    assert np.array_equal(vistas.pop(), sem)                     # o Tesseract recebe os mesmos pixels
    assert ras.resumo()["rasterizacoes_repetidas"] == 0


def test_imagem_guardada_e_so_leitura_e_orcamento_estourado_e_contado(tmp_path):
    pdf = _pdf_repetido(tmp_path / "o.pdf", [10, 20])
    with O.rasterizacao_unica(orcamento=0) as ras:
        a = ras.imagem(pdf, 1)
        ras.imagem(pdf, 1)
        with pytest.raises(ValueError):
            a[0, 0, 0] = 1                                       # quem mudasse a imagem no lugar corromperia o hash
    assert ras.resumo() == {"rasterizacoes": 2, "rasterizacoes_distintas": 1, "rasterizacoes_repetidas": 1,
                            "pdf_aberturas": 1}
    assert O.raster_atual() is None


# ── (3) todo OCR vai ao E6, com ou sem número (frente B1: a porta do E8 exige a conferência do E6) ────────────────
from tests.fluxo_pg import precisa_pg  # noqa: E402
from tests.test_estagio_texto import ctx, pg  # noqa: E402,F401 — fixture do esquema temporário


@precisa_pg
def test_ocr_sem_numero_vai_ao_e6_e_e6_confirma_com_zero(pg, tmp_path, monkeypatch):  # noqa: F811
    """O caso 330002/028372/2026 sei:142180617: OCR sem número crítico não emitia `numero_ia` ⇒ o E6 nunca rodava ⇒
    o processo ficava fora da porta do E8 para sempre."""
    from compliance_agent.aplicacao.estagios import confirmar_ocr as C
    from tests.test_estagio_confirmar_ocr import FontesFalsas, _e6, _preparar
    con, nome = pg
    pl, sha = _preparar(nome, tmp_path, monkeypatch, texto="Ofício de encaminhamento ao setor competente")
    r = O._handler(pl, ctx("ocr", "sei:111", sha, 9))
    ev = {e["tipo"]: e for e in r.eventos}
    assert list(ev) == ["texto_novo", "numero_ia"] and ev["numero_ia"]["detalhe"]["numeros"] == 0
    r6, ok = _e6(pl, sha, FontesFalsas(), monkeypatch)
    assert ok, r6.efeito.get("conferencia")
    assert r6.efeito["estado"] == C.CONFIRMADO and r6.efeito["numeros"] == 0
    assert con.execute("SELECT estado, numeros FROM ocr_conferencia").fetchall() == [("confirmado", 0)]


# ── (4) reprocessar com versão nova do estágio grava linha nova (a transformação é histórico) ─────────────────────
@precisa_pg
def test_reprocessar_com_versao_nova_grava_linha_nova_e_efeito_ok(pg, tmp_path, monkeypatch):  # noqa: F811
    """e5-2 → e5-3 com o MESMO motor@versão e o MESMO texto (só a bbox mudou): antes, conflito ⇒ DO NOTHING ⇒ linha
    velha com o lateral_sha velho ⇒ efeito falhava para sempre."""
    from tests.fluxo_pg import DSN
    from tests.test_estagio_ocr import Falso, _e5
    from tests.test_estagio_texto import pdf_de, rodar_e4
    con, nome = pg
    pdf = pdf_de(tmp_path / "001.pdf", ["nativa", "escaneada"])
    rodar_e4(nome, tmp_path, pdf)
    sha = T.sha256_arquivo(pdf)

    class OutraBbox(Falso):
        def ler(self, pdf, paginas):
            return {n: O.Leitura(le.texto, [dict(x, bbox=[5, 6, 7, 8]) for x in le.linhas], le.largura, le.altura)
                    for n, le in super().ler(pdf, paginas).items()}
    texto = {2: "Ofício 12/2026 ao setor competente"}
    monkeypatch.setattr(O, "VERSAO", "e5-2")
    r, ok = _e5(nome, tmp_path, pdf, sha, (Falso("rapidocr", texto), None), monkeypatch)
    assert ok, r.efeito["conferencia"]
    monkeypatch.setattr(O, "VERSAO", "e5-3")
    r, ok = _e5(nome, tmp_path, pdf, sha, (OutraBbox("rapidocr", texto), None), monkeypatch, ficha=2)
    assert ok, r.efeito["conferencia"]
    linhas = con.execute("SELECT versao_estagio, parametros->>'lateral_sha' FROM transformacao WHERE tipo = 'ocr' "
                         "ORDER BY id").fetchall()
    assert [v for v, _ in linhas] == ["e5-2", "e5-3"] and linhas[0][1] != linhas[1][1]
    # mesma versão de novo: idempotente (nenhuma linha a mais) e o efeito continua conferindo
    r, ok = _e5(nome, tmp_path, pdf, sha, (OutraBbox("rapidocr", texto), None), monkeypatch, ficha=3)
    assert ok and con.execute("SELECT count(*) FROM transformacao WHERE tipo = 'ocr'").fetchone()[0] == 2
    # a migração reaplicada não apaga nem muda linha
    T.aplicar_schema(DSN, nome)
    assert con.execute("SELECT count(*) FROM transformacao WHERE tipo = 'ocr'").fetchone()[0] == 2


@precisa_pg
def test_e4_reprocessar_com_versao_nova_grava_linha_nova_e_efeito_ok(pg, tmp_path, monkeypatch):  # noqa: F811
    """O mesmo para o E4 (e4-x → e4-y, mesmo binário): antes, a linha velha ficava e o lateral_sha não conferia."""
    from tests.test_estagio_texto import pdf_de, rodar_e4
    con, nome = pg
    pdf = pdf_de(tmp_path / "001.pdf", ["nativa", "escaneada"])
    monkeypatch.setattr(T, "VERSAO", "e4-x")
    r, ok, _, _ = rodar_e4(nome, tmp_path, pdf)
    assert ok, r.efeito.get("conferencia")
    monkeypatch.setattr(T, "VERSAO", "e4-y")
    r, ok, _, _ = rodar_e4(nome, tmp_path, pdf, ficha=2)
    assert ok, r.efeito.get("conferencia")
    vs = [v for (v,) in con.execute("SELECT versao_estagio FROM transformacao WHERE tipo = %s ORDER BY id",
                                    (T.TIPO_TRANSFORMACAO,))]
    assert vs == ["e4-x", "e4-y"]
    r, ok, _, _ = rodar_e4(nome, tmp_path, pdf, ficha=3)                  # mesma versão: idempotente
    assert ok and con.execute("SELECT count(*) FROM transformacao WHERE tipo = %s",
                              (T.TIPO_TRANSFORMACAO,)).fetchone()[0] == 2
