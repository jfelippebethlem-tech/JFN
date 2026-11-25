# -*- coding: utf-8 -*-
"""Conferência por recorte (O3.6): o número do OCR é re-lido NO RECORTE da bbox da linha por motor de OUTRA família;
confirma só com o número normalizado igual; bbox fora da página, número sem linha e nó sem o motor da outra família
ficam declarados (nunca confirmados); a família nunca é a mesma do motor da página. Leitor FALSO."""
from compliance_agent.aplicacao.estagios import ocr_recorte as R
from tests.test_estagio_ocr import _pdf_repetido


class LeitorFalso:
    def __init__(self, familia, texto):
        self.familia, self.texto, self.formas = familia, texto, []

    def motor(self):
        return f"{self.familia}@teste"

    def ler_imagem(self, img):
        self.formas.append(img.shape)
        return self.texto


def _e5(motor="surya@0.24 (vLLM)", linhas=None):
    return {"paginas": {"1": {"estado": "texto", "motor": motor, "texto": "x", "linhas": linhas if linhas is not None
                              else [{"texto": "Total R$ 1.234,56", "bbox": [100, 200, 300, 230]},
                                    {"texto": "CNPJ 11.222.333/0001-81", "bbox": [100, 300, 400, 330]}]}}}


NUM = [{"tipo": "valor", "norma": "1234.56", "pagina": 1}, {"tipo": "cnpj", "norma": "11222333000181", "pagina": 1},
       {"tipo": "nf", "norma": "77", "pagina": 1}]


def test_familia_do_recorte_nunca_e_a_da_pagina():
    assert R.familia_para("surya@0.24 (vLLM, GPU it-campo) dpi200") == "rapidocr"
    assert R.familia_para("gpu@teste") == "rapidocr"
    assert R.familia_para("rapidocr@3.10 PP-OCRv5 mobile+latin (CPU) dpi200") == "tesseract"
    assert R.familia_para("reserva:rapidocr@legado") == "tesseract"
    assert R.familia_para("tesseract@5.3 por dpi200") == "rapidocr"


def test_recorte_confirma_so_o_numero_igual_e_amplia(tmp_path):
    pdf = _pdf_repetido(tmp_path / "a.pdf", [230])
    lt = LeitorFalso("rapidocr", "Total R$ 1.234,56  CNPJ 11.222.333/0001-81")
    out = {r["tipo"]: r for r in R.conferir(pdf, _e5(), NUM, {"rapidocr": lt})}
    assert out["valor"]["estado"] == "confere" and out["cnpj"]["estado"] == "confere"
    assert "nf" not in out                                               # NF depende de palavra-chave: fora do recorte
    assert lt.formas[0][:2] == ((230 - 200 + 2 * R.MARGEM) * R.ESCALA, (300 - 100 + 2 * R.MARGEM) * R.ESCALA)
    assert R.chaves_confirmadas(list(out.values())) == {"recorte:rapidocr@teste": {("valor", "1234.56"),
                                                                                   ("cnpj", "11222333000181")}}
    lt2 = LeitorFalso("rapidocr", "Total R$ 1.284,56")                   # dígito trocado no recorte: não confere
    r = {x["tipo"]: x for x in R.conferir(pdf, _e5(), NUM, {"rapidocr": lt2})}
    assert r["valor"]["estado"] == "nao_confere" and R.chaves_confirmadas(list(r.values())) == {}


def test_declarados_sem_bbox_sem_leitor_e_bbox_fora(tmp_path):
    pdf = _pdf_repetido(tmp_path / "b.pdf", [230])
    lt = LeitorFalso("rapidocr", "1.234,56")
    r = R.conferir(pdf, _e5(linhas=[{"texto": "Total R$", "bbox": [1, 1, 9, 9]}]), NUM[:1], {"rapidocr": lt})
    assert r[0]["estado"] == "sem_bbox" and lt.formas == []
    r = R.conferir(pdf, _e5(), NUM[:1], {"tesseract": LeitorFalso("tesseract", "1.234,56")})
    assert r[0]["estado"] == "sem_leitor" and r[0]["familia_pedida"] == "rapidocr"
    fora = _e5(linhas=[{"texto": "R$ 1.234,56", "bbox": [90000, 90000, 90010, 90010]}])
    r = R.conferir(pdf, fora, NUM[:1], {"rapidocr": lt})
    assert r[0]["estado"] == "nao_confere" and lt.formas == []           # recorte fora da imagem nem é lido
    # "confere" forjado sem o número no texto guardado não vira chave
    assert R.chaves_confirmadas([{"tipo": "valor", "norma": "1234.56", "estado": "confere", "motor": "m",
                                  "texto": "nada"}]) == {}


def test_espaco_colado_no_separador_sai_digito_espaco_digito_fica():
    assert R.compactar("R$ 82.526, 42 e R$ 0 , 00") == "R$ 82.526,42 e R$ 0,00"
    assert R.compactar("18.051,9 8") == "18.051,9 8"                       # não funde dígito com dígito
    assert R.chaves_confirmadas([{"tipo": "valor", "norma": "82526.42", "estado": "confere", "motor": "m",
                                  "texto": "mão de obra R$ 82.526, 42"}]) == {"recorte:m": {("valor", "82526.42")}}


def test_mesma_bbox_lida_uma_vez(tmp_path):
    """Bloco grande do Surya com vários números: o recorte é lido UMA vez e serve a todos."""
    pdf = _pdf_repetido(tmp_path / "c.pdf", [230])
    e5 = _e5(linhas=[{"texto": "Total R$ 1.234,56 CNPJ 11.222.333/0001-81", "bbox": [100, 200, 900, 400]}])
    lt = LeitorFalso("rapidocr", "Total R$ 1.234,56 CNPJ 11.222.333/0001-81")
    out = R.conferir(pdf, e5, NUM, {"rapidocr": lt})
    assert len(lt.formas) == 1 and {r["estado"] for r in out} == {"confere"}
