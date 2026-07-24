"""O arquivo tem de REGISTRAR os documentos da árvore que não foram capturados.

Antes, sei_arquivar iterava só os PDFs em disco — um doc que existe na árvore mas
falhou a captura (formato raro: ZIP de PDFs, .odt, etc.) sumia do arquivo SEM RASTRO.
O auditor via menos documentos que a árvore tem e não sabia o quê faltava (INDISPONÍVEL
≠ 0). Agora cada doc da árvore não-capturado entra no arquivo marcado
`nao_capturado: True` — MAS não conta a fase dele (não temos o conteúdo, não se pode
afirmar que a fase está coberta, senão lacunas() mentiria).
"""
import json

import fitz

from tools.sei_arquivar import arquivar


def _pdf(caminho, texto="EDITAL DE PREGAO objeto do certame"):
    d = fitz.open()
    d.new_page().insert_text((60, 60), texto)
    d.save(str(caminho))
    d.close()


def test_doc_nao_capturado_entra_marcado_no_arquivo(tmp_path):
    origem = tmp_path / "integra_080001_009999_2025"
    origem.mkdir()
    _pdf(origem / "000.pdf")                    # doc 0 capturado
    # manifesto (formato novo) declara 2 docs; o doc 1 NÃO tem PDF (falhou captura)
    (origem / "manifest.json").write_text(json.dumps({
        "processo": "080001/009999/2025", "total_arvore": 2, "completo": True,
        "docs": [
            {"i": 0, "arquivo": "000.pdf", "titulo": "Edital", "ok": True},
            {"i": 1, "arquivo": "001.pdf", "titulo": "Programação de Desembolso - PD zipadas",
             "ok": False}]}), encoding="utf-8")

    m = arquivar(origem, tmp_path / "arq", processo="080001/009999/2025", ocr=False)

    idxs = {d["i"]: d for d in m["docs"]}
    assert 0 in idxs and 1 in idxs, "AMBOS os docs da árvore têm de constar do arquivo"
    assert idxs[1].get("nao_capturado") is True, "o doc que falhou é marcado, não sumido"
    assert "zipadas" in idxs[1]["titulo"], "o título fica registrado p/ o auditor achar"
    assert not idxs[0].get("nao_capturado"), "o capturado não é marcado"
    assert m.get("nao_capturados") == 1


def test_fase_do_nao_capturado_nao_conta_para_lacunas(tmp_path):
    """Doc não-capturado NÃO pode 'cobrir' uma fase — não temos o conteúdo dele."""
    origem = tmp_path / "integra_080001_008888_2025"
    origem.mkdir()
    _pdf(origem / "000.pdf", "Despacho de encaminhamento")     # só um despacho capturado
    (origem / "manifest.json").write_text(json.dumps({
        "processo": "080001/008888/2025", "total_arvore": 2, "completo": True,
        "docs": [
            {"i": 0, "arquivo": "000.pdf", "titulo": "Despacho", "ok": True},
            {"i": 1, "arquivo": "001.pdf", "titulo": "Edital de Licitação", "ok": False}]}),
        encoding="utf-8")

    m = arquivar(origem, tmp_path / "arq", processo="080001/008888/2025", ocr=False)

    # o Edital não-capturado NÃO pode fazer a fase de seleção parecer presente
    faltas = " ".join(l.get("falta", "") for l in (m.get("lacunas") or [])).lower()
    assert "seleção" in faltas or "selecao" in faltas, (
        "o Edital não-capturado não tem seu conteúdo — a fase de seleção segue em falta"
    )
