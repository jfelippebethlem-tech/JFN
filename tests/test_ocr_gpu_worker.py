"""Trabalhador do OCR por IA (it-campo): página nativa não vai à GPU e o fluxo contínuo devolve o texto na ordem."""
import importlib.util
import sys
import threading
import types
from pathlib import Path

import fitz
import pytest
from PIL import Image

_spec = importlib.util.spec_from_file_location(
    "ocr_gpu_worker", Path(__file__).resolve().parent.parent / "deploy/itcampo/ocr_gpu/ocr_gpu_worker.py")
W = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(W)

TEXTO = "Nota fiscal 001234567 CNPJ 12.345.678/0001-90 valor R$ 1.234,56 " * 5   # > 200 caracteres


def _pdf(caminho: Path, paginas: list[str]) -> Path:
    """'nativa' = texto vetorial; 'escaneada' = imagem de página inteira; 'curta' = pouco texto, sem imagem."""
    doc = fitz.open()
    for tipo in paginas:
        pg = doc.new_page(width=595, height=842)
        if tipo == "nativa":
            pg.insert_textbox(fitz.Rect(40, 40, 555, 800), TEXTO, fontsize=9)
        elif tipo == "escaneada":
            img = Image.new("RGB", (400, 560), "white")
            import io
            b = io.BytesIO(); img.save(b, "PNG")
            pg.insert_image(pg.rect, stream=b.getvalue())
        elif tipo == "curta":
            pg.insert_text((40, 60), "Anexo I")
    doc.save(caminho)
    return caminho


@pytest.fixture(autouse=True)
def _base_temporaria(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "BASE", tmp_path)                 # o log do trabalhador vai para a pasta do teste
    monkeypatch.setattr(W, "SINAL", tmp_path / "SESSAO_ATIVA")


class RecFalso:
    """Imita o RecognitionPredictor: uma resposta por imagem, com o tamanho da imagem no texto."""

    def __init__(self, falhar_em: int | None = None):
        self.imagens, self.trava, self.falhar_em = 0, threading.Lock(), falhar_em

    def __call__(self, imgs):
        with self.trava:
            self.imagens += len(imgs)
            n = self.imagens
        if self.falhar_em is not None and n == self.falhar_em:
            raise RuntimeError("vLLM caiu")
        return [types.SimpleNamespace(blocks=[types.SimpleNamespace(html=f"<p>ocr {im.size[0]}</p>", reading_order=0)])
                for im in imgs]


def test_pagina_nativa_so_com_texto_visivel_e_sem_imagem_grande(tmp_path):
    d = fitz.open(_pdf(tmp_path / "a.pdf", ["nativa", "escaneada", "curta"]))
    assert W.pagina_nativa(d.load_page(0)) is True
    assert W.pagina_nativa(d.load_page(1)) is False      # imagem de página inteira = escaneada
    assert W.pagina_nativa(d.load_page(2)) is False      # pouco texto: vai ao OCR (pode ser texto desenhado)


def test_pagina_com_texto_invisivel_de_ocr_antigo_vai_para_a_gpu(tmp_path):
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_textbox(fitz.Rect(40, 40, 555, 800), TEXTO, fontsize=9, render_mode=3)   # camada de OCR invisível
    doc.save(tmp_path / "inv.pdf")
    assert W.pagina_nativa(fitz.open(tmp_path / "inv.pdf").load_page(0)) is False


def test_ler_lote_nativa_nao_vai_a_gpu_e_ordem_das_paginas_e_mantida(tmp_path):
    a = _pdf(tmp_path / "a.pdf", ["escaneada", "nativa", "escaneada"])
    b = _pdf(tmp_path / "b.pdf", ["nativa", "nativa"])
    c = _pdf(tmp_path / "c.pdf", ["escaneada"] * 5)
    rec = RecFalso()
    res, ruins, refazer = W.ler_lote([("x/a.pdf", a), ("x/b.pdf", b), ("x/c.pdf", c)], rec, em_voo=3)
    assert ruins == [] and refazer == []
    assert rec.imagens == 7                                   # 2 de a + 5 de c; as 3 nativas não foram à GPU
    assert res["x/a.pdf"]["nativas"] == [1] and res["x/b.pdf"]["nativas"] == [0, 1]
    assert res["x/a.pdf"]["textos"][0].startswith("ocr ") and "Nota fiscal 001234567" in res["x/a.pdf"]["textos"][1]
    assert res["x/c.pdf"]["paginas"] == 5 and len(res["x/c.pdf"]["textos"]) == 5


def test_pdf_ilegivel_vai_para_ruins_e_falha_da_gpu_devolve_so_aquele_pdf(tmp_path):
    (tmp_path / "ruim.pdf").write_bytes(b"isto nao e pdf")
    a = _pdf(tmp_path / "a.pdf", ["escaneada"])
    b = _pdf(tmp_path / "b.pdf", ["escaneada", "escaneada"])
    rec = RecFalso(falhar_em=2)                               # a 2ª página enviada falha
    res, ruins, refazer = W.ler_lote([("r.pdf", tmp_path / "ruim.pdf"), ("a.pdf", a), ("b.pdf", b)], rec, em_voo=1)
    assert ruins == ["r.pdf"]
    assert refazer == ["b.pdf"] and list(res) == ["a.pdf"]   # o PDF com página falhada volta à fila inteiro


def test_corte_de_paginas_respeita_max_pag(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "MAX_PAG", 2)
    a = _pdf(tmp_path / "a.pdf", ["escaneada"] * 4)
    res, _, _ = W.ler_lote([("a.pdf", a)], RecFalso(), em_voo=2)
    assert res["a.pdf"]["paginas"] == 2 and res["a.pdf"]["paginas_pdf"] == 4


def test_entrega_so_apaga_o_que_tem_md5_igual_nas_duas_pontas(tmp_path, monkeypatch):
    """20/11/2026: a entrega da GPU apagava out/ inteiro com rc 0 do rsync, sem conferir. Agora md5 de cada arquivo
    nas duas pontas (como a reserva): igual → sai de out/; divergente ou ausente na VM-1 → fica e volta no lote seguinte."""
    import hashlib
    out = tmp_path / "out"
    monkeypatch.setattr(W, "OUT", out)
    (out / "integra_t").mkdir(parents=True)
    for n in ("000", "001"):
        (out / "integra_t" / f"{n}.ocr_gpu.txt").write_text(f"texto {n}")
        (out / "integra_t" / f"{n}.ocr_gpu.json").write_text("{}")
    md5 = {a: hashlib.md5((out / a).read_bytes()).hexdigest()
           for a in ("integra_t/000.ocr_gpu.txt", "integra_t/000.ocr_gpu.json", "integra_t/001.ocr_gpu.json")}
    md5["integra_t/001.ocr_gpu.json"] = "0" * 32                  # chegou diferente; 001.txt nem chegou
    chamadas = []

    def falso(argv, **kw):
        chamadas.append(argv)
        if argv[0] == "rsync":
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        assert argv[-1] == "cd JFN/data/sei_cache/ && xargs -d '\\n' md5sum --" and argv[-2] == "vm1-ts"
        pedidos = kw["input"].decode().split()
        linhas = "".join(f"{md5[a]}  {a}\n" for a in pedidos if a in md5)
        return types.SimpleNamespace(returncode=1, stdout=linhas.encode(), stderr=b"")
    monkeypatch.setattr(W.subprocess, "run", falso)
    rc, ruins = W.entregar()
    assert rc == 0 and sorted(ruins) == ["integra_t/001.ocr_gpu.json", "integra_t/001.ocr_gpu.txt"]
    assert sorted(p.name for p in (out / "integra_t").iterdir()) == ["001.ocr_gpu.json", "001.ocr_gpu.txt"]
    assert [c[0] for c in chamadas] == ["rsync", "ssh"]


def test_entrega_com_rsync_falho_nao_apaga_nada(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr(W, "OUT", out)
    (out / "integra_t").mkdir(parents=True)
    (out / "integra_t" / "000.ocr_gpu.txt").write_text("x")
    monkeypatch.setattr(W.subprocess, "run", lambda argv, **kw: types.SimpleNamespace(returncode=12, stdout="", stderr="caiu"))
    assert W.entregar() == (12, [])
    assert (out / "integra_t" / "000.ocr_gpu.txt").exists()


def test_pdf_local_procura_em_todas_as_raizes_na_ordem_e_hd_ausente_nao_quebra(tmp_path, monkeypatch):
    """23/11/2026: os PDFs migraram para o HD externo (D:\\JFN-Frio\\sei\\…); o trabalhador lê local de várias
    raízes, na ordem. HD desplugado = a raiz não existe e o item segue para o caminho antigo (VM-2)."""
    c, hd = tmp_path / "c", tmp_path / "hd_desplugado"
    (c / "integra_1").mkdir(parents=True)
    (c / "integra_1" / "001.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(W, "ARQUIVOS_LOCAIS", [hd, c])
    assert W.pdf_local("integra_1/001.pdf") == c / "integra_1" / "001.pdf"
    assert W.pdf_local("integra_1/002.pdf") is None
