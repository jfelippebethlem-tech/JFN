import json

import fitz

from tools import sei_depurar_pdfs as D


def _pdf_texto(p, paginas=2):
    d = fitz.open()
    for i in range(paginas):
        d.new_page().insert_text((72, 72), f"Despacho {i} do processo SEI com texto suficiente para contar")
    d.save(str(p))


def _pdf_imagem(p):
    d = fitz.open()
    pg = d.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 400, 400), 0)
    pix.clear_with(200)
    pg.insert_image(pg.rect, pixmap=pix)
    d.save(str(p))


def test_nativo_vira_texto_com_registro(tmp_path):
    pasta = tmp_path / "integra_x"
    pasta.mkdir()
    _pdf_texto(pasta / "000.pdf")
    (pasta / "manifest.json").write_text(json.dumps({"docs": [{"arquivo": "000.pdf", "url": "https://sei/x"}]}))
    sha = D._sha256(pasta / "000.pdf")
    r = D.depurar_pasta(pasta, aplicar=True)
    assert r["nativos"] == 1 and not (pasta / "000.pdf").exists()
    assert "Despacho 1" in (pasta / "000.txt").read_text(encoding="utf-8")
    reg = json.loads((pasta / "depurados.json").read_text())
    assert reg["000.pdf"]["sha256"] == sha and reg["000.pdf"]["paginas"] == 2 and reg["000.pdf"]["url"] == "https://sei/x"


def test_imagem_fica_como_pdf(tmp_path):
    pasta = tmp_path / "integra_y"
    pasta.mkdir()
    _pdf_imagem(pasta / "000.pdf")
    r = D.depurar_pasta(pasta, aplicar=True)
    assert r["imagem"] == 1 and (pasta / "000.pdf").exists() and not (pasta / "000.txt").exists()


def test_ensaio_nao_mexe(tmp_path):
    pasta = tmp_path / "integra_z"
    pasta.mkdir()
    _pdf_texto(pasta / "000.pdf")
    D.depurar_pasta(pasta, aplicar=False)
    assert (pasta / "000.pdf").exists() and not (pasta / "depurados.json").exists()


def test_pasta_recente_ou_sem_arquivo_nao_e_elegivel(tmp_path):
    cache, arq = tmp_path / "cache", tmp_path / "arq"
    (cache / "integra_a").mkdir(parents=True)
    _pdf_texto(cache / "integra_a" / "000.pdf")
    assert D.pastas_elegiveis(cache, 3.0, None) == []                     # recém-capturada
    futuro = __import__("time").time() + 4 * 3600
    assert D.pastas_elegiveis(cache, 3.0, arq, agora=futuro) == []         # sem sei_arquivo/<tag>
    (arq / "a").mkdir(parents=True)
    (arq / "a" / "manifest.json").write_text("{}")
    assert [p.name for p in D.pastas_elegiveis(cache, 3.0, arq, agora=futuro)] == ["integra_a"]


def test_arquivar_nao_reescreve_pasta_depurada(tmp_path):
    from tools import sei_arquivar as A
    origem, destino = tmp_path / "integra_q", tmp_path / "arq"
    origem.mkdir()
    destino.mkdir()
    (destino / "manifest.json").write_text(json.dumps({"docs": [{"i": 0}, {"i": 1}]}))
    (origem / "depurados.json").write_text("{}")
    _pdf_texto(origem / "001.pdf")
    m = A.arquivar(origem, destino)
    assert len(m["docs"]) == 2
    assert json.loads((destino / "manifest.json").read_text())["docs"] == [{"i": 0}, {"i": 1}]
