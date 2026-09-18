# -*- coding: utf-8 -*-
"""Pipeline íntegra→arquivo compacto (tools/sei_arquivar.py). Offline:
constrói uma 'íntegra' sintética (PDF textual + relatório fotográfico com
imagem) e verifica: txt por documento, fotos preservadas em JPEG, manifest
com fase por doc, linha do tempo e lacunas."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz


def _integra_fake(base: Path) -> Path:
    d = base / "integra_TESTE"
    d.mkdir(parents=True)
    # doc 0: contrato textual
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((50, 100), "CONTRATO 011/2025 - Cláusula primeira: o objeto é "
                              "a reforma predial. Valor: R$ 457.179,31." * 3)
    doc.save(str(d / "000.pdf")); doc.close()
    # doc 1: relatório fotográfico (página com imagem grande e quase sem texto)
    doc = fitz.open()
    pg = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 320, 240), False)
    pix.set_rect(pix.irect, (200, 120, 40))     # "foto" laranja
    pg.insert_image(fitz.Rect(30, 60, 560, 740), pixmap=pix)
    doc.save(str(d / "001.pdf")); doc.close()
    (d / "manifest.json").write_text(json.dumps([
        {"i": 0, "arquivo": "000.pdf", "titulo": "Contrato 011/2025", "ok": True},
        {"i": 1, "arquivo": "001.pdf",
         "titulo": "Relatório Fotográfico - 5ª Medição", "ok": True},
    ], ensure_ascii=False), encoding="utf-8")
    return d


def test_arquivar_integra_sintetica(tmp_path):
    from tools.sei_arquivar import arquivar

    origem = _integra_fake(tmp_path)
    destino = tmp_path / "arquivo"
    m = arquivar(origem, destino, processo="000000/000000/0000")

    raiz = destino
    man = json.loads((raiz / "manifest.json").read_text(encoding="utf-8"))
    assert man["processo"] == "000000/000000/0000"
    docs = {d["i"]: d for d in man["docs"]}

    # contrato: texto extraído, fase certa
    assert docs[0]["fase"] == "contratacao"
    txt0 = (raiz / docs[0]["texto"]).read_text(encoding="utf-8")
    assert "457.179,31" in txt0

    # relatório fotográfico: fase execução + foto JPEG preservada
    assert docs[1]["fase"] == "execucao"
    assert docs[1]["tipo"] == "relatorio_fotografico"
    assert docs[1]["fotos"], "fotos do relatório fotográfico devem ser preservadas"
    foto = raiz / docs[1]["fotos"][0]
    assert foto.exists() and foto.stat().st_size > 1000
    assert foto.suffix == ".jpg"

    # linha do tempo e lacunas calculadas
    assert man["linha_do_tempo"]["contratacao"] == 1
    assert man["linha_do_tempo"]["execucao"] == 1
    assert isinstance(man["lacunas"], list)
    # o retorno é o mesmo manifest
    assert m["docs"][0]["fase"] == "contratacao"


def test_arquivar_e_idempotente(tmp_path):
    from tools.sei_arquivar import arquivar

    origem = _integra_fake(tmp_path)
    destino = tmp_path / "arquivo"
    arquivar(origem, destino, processo="P")
    m2 = arquivar(origem, destino, processo="P")   # 2ª rodada não duplica
    assert len(m2["docs"]) == 2
    fotos = list((destino / "fotos").glob("*.jpg"))
    assert len(fotos) == len(set(f.name for f in fotos))


def test_preservar_toca_o_mtime_do_manifesto(tmp_path, monkeypatch):
    """Preservar o arquivo maior é certo — mas TEM de tocar o mtime, ou a fila não anda.

    `arquivar_pendentes` monta a fila por "cache mais novo que o manifesto". Preservando sem
    tocar, o processo reaparece em TODO disparo, e o OCR roda ANTES da decisão de preservar:
    medido em 2026-08-23, os dois primeiros processos comiam os 25 min do `timeout` e o lane
    terminava em 124 sem alcançar o resto da fila. É o mesmo bug que `sei_arquivar_do_cache`
    corrigiu em 2026-08-15 — o irmão tinha o conserto, este não.
    """
    import os
    import time

    from tools.sei_arquivar import arquivar

    origem = _integra_fake(tmp_path)
    destino = tmp_path / "arq"
    (destino / "texto").mkdir(parents=True)
    # manifesto anterior com MAIS docs capturados do que a íntegra sintética (2) tem
    mdest = destino / "manifest.json"
    mdest.write_text(json.dumps({"docs": [{"i": i, "titulo": f"d{i}"} for i in range(9)]}),
                     encoding="utf-8")
    antigo = time.time() - 86_400          # manifesto de ontem
    os.utime(mdest, (antigo, antigo))

    devolvido = arquivar(origem, destino, processo="030001/087722/2024", ocr=False)

    assert len(devolvido["docs"]) == 9, "preservou o manifesto errado — regrediu para o menor"
    assert mdest.stat().st_mtime > antigo + 3600, (
        "preservou sem tocar o mtime: o processo volta à fila em todo disparo e o lane "
        "nunca alcança o resto"
    )


def _pdf_min(caminho, texto="conteudo do documento " * 20):
    doc = fitz.open()
    doc.new_page().insert_text((50, 100), texto)
    doc.save(str(caminho)); doc.close()


def test_slug_malformado_e_ignorado(tmp_path, monkeypatch, capsys):
    """`integra_____080002_...` é resíduo do bug do prefixo `SEI-`, já corrigido na captura.

    Sem esta guarda o lane tentaria arquivá-lo em TODO disparo e criaria `sei_arquivo/____0800...`
    — lixo NOVO a partir de lixo velho. Os processos reais já estão arquivados sob o slug correto.
    """
    from tools import sei_arquivar

    cache = tmp_path / "cache"; arq = tmp_path / "arq"
    cache.mkdir(); arq.mkdir()
    ruim = cache / "integra_____080002_000803_2025"; ruim.mkdir()
    _pdf_min(ruim / "000.pdf")
    monkeypatch.setattr(sei_arquivar, "CACHE", cache)
    monkeypatch.setattr(sei_arquivar, "ARQUIVO", arq)

    sei_arquivar.arquivar_pendentes(ocr=False)

    assert "slug malformado" in capsys.readouterr().out
    assert not (arq / "____080002_000803_2025").exists(), "criou lixo a partir do resíduo"
    assert list(arq.iterdir()) == [], "não devia ter arquivado nada"


def test_fila_ordena_por_CUSTO_e_nao_por_nome(tmp_path, monkeypatch):
    """Alfabético não é prioridade: é sorteio pelo nome — e o maior bloqueia a fila no timeout.

    Medido em 2026-08-23: o 1º alfabético trazia 741 PDFs / 548 MB e sozinho estourava o
    `timeout 1500` do lane; o `080002/019206/2025` (3º, 40 PDFs) nunca era alcançado.
    """
    from tools import sei_arquivar

    cache = tmp_path / "cache"; arq = tmp_path / "arq"
    cache.mkdir(); arq.mkdir()
    # `010001_...` é o primeiro em ordem alfabética E o mais pesado; `990001_...` é o último e leve
    pesado = cache / "integra_010001_000001_2024"; pesado.mkdir()
    for i in range(4):
        _pdf_min(pesado / f"{i:03d}.pdf", "texto longo " * 400)
    leve = cache / "integra_990001_000001_2024"; leve.mkdir()
    _pdf_min(leve / "000.pdf", "curto")
    monkeypatch.setattr(sei_arquivar, "CACHE", cache)
    monkeypatch.setattr(sei_arquivar, "ARQUIVO", arq)

    ordem = []
    original = sei_arquivar.arquivar
    monkeypatch.setattr(sei_arquivar, "arquivar",
                        lambda o, d, **kw: (ordem.append(o.name), original(o, d, **kw))[1])
    sei_arquivar.arquivar_pendentes(ocr=False)

    assert ordem[0] == "integra_990001_000001_2024", (
        f"a fila continua alfabética: {ordem} — o pesado bloqueia o leve no timeout")


def test_retomada_nao_refaz_o_que_ja_esta_pronto(tmp_path, monkeypatch):
    """Sem retomada, processo grande NUNCA completa — o timeout corta sempre no mesmo ponto.

    Medido em 2026-08-23 no `080002/019206/2025` (40 PDFs): cada disparo refazia do `000.pdf`, o
    `timeout 1500` cortava perto do 13º, e os txt de 000-012 reapareciam com hora nova. Trabalho
    refeito e jogado fora — e nada no log denunciava, porque cada disparo PARECIA progresso.
    """
    import time

    from tools.sei_arquivar import arquivar

    origem = _integra_fake(tmp_path)
    destino = tmp_path / "arq"

    man1 = arquivar(origem, destino, processo="", ocr=False)   # 1ª passada: extrai
    txts = sorted((destino / "texto").glob("*.txt"))
    assert txts, "nada foi extraído na primeira passada"
    antes = {t.name: t.stat().st_mtime_ns for t in txts}
    conteudo = {t.name: t.read_text(encoding="utf-8") for t in txts}

    time.sleep(0.01)
    man = arquivar(origem, destino, processo="", ocr=False)    # 2ª passada: deve REAPROVEITAR

    depois = {t.name: t.stat().st_mtime_ns for t in (destino / "texto").glob("*.txt")}
    assert depois == antes, f"reescreveu texto já pronto: {set(depois) ^ set(antes) or 'mtime mudou'}"
    for nome, txt in conteudo.items():
        assert (destino / "texto" / nome).read_text(encoding="utf-8") == txt, f"{nome} mudou"
    assert all(d.get("reaproveitado") for d in man["docs"]), "manifesto não marcou reaproveitamento"
    # `chars` tem de bater com a extração original — não basta reaproveitar o arquivo e perder a
    # contagem. Comparar com a 1ª passada, e não exigir >0: relatório fotográfico é 0 por direito.
    assert ({d["i"]: d["chars"] for d in man["docs"]}
            == {d["i"]: d["chars"] for d in man1["docs"]}), "reaproveitou e mudou a contagem"


def test_retomada_REEXTRAI_quando_o_pdf_e_mais_novo(tmp_path):
    """PDF recapturado depois do txt tem conteúdo novo — aí reaproveitar seria servir o velho.

    ATENÇÃO ao ler: este teste é GUARDA, não detector. Ele passa mesmo SEM a retomada (sem ela o
    código sempre reextrai), então não prova que a retomada existe — quem prova isso é o teste
    acima. O papel deste é impedir que a retomada, uma vez presente, sirva texto velho depois de
    uma recaptura. Conferido rodando com o bloco removido: acima falha, este passa.
    """
    import os
    import time

    from tools.sei_arquivar import arquivar

    origem = _integra_fake(tmp_path)
    destino = tmp_path / "arq"
    arquivar(origem, destino, processo="", ocr=False)
    alvo = sorted((destino / "texto").glob("*.txt"))[0]
    antes = alvo.stat().st_mtime_ns

    time.sleep(0.01)
    futuro = time.time() + 60                                   # PDF "recapturado" agora
    for pdf in origem.glob("*.pdf"):
        os.utime(pdf, (futuro, futuro))
    arquivar(origem, destino, processo="", ocr=False)

    assert sorted((destino / "texto").glob("*.txt"))[0].stat().st_mtime_ns != antes, (
        "não reextraiu apesar de o PDF ser mais novo que o txt")
