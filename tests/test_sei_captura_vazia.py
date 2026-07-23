"""Captura vazia do SEI NÃO é processo sem documentos (INDISPONÍVEL ≠ 0).

Achado em 2026-07-23: 94 dos 354 processos arquivados tinham ZERO documento
capturado (a íntegra voltou vazia do SEI) e mesmo assim o manifesto declarava
"🔴 LACUNA (alta): falta Seleção (edital, julgamento, homologação)" — ou seja,
o sistema acusava o processo de não ter edital quando nós é que não baixamos nada.
Acusação falsa alimentando análise e relatório.
"""
import json

from tools.sei_arquivar import arquivar


def test_captura_vazia_nao_inventa_lacuna(tmp_path):
    origem = tmp_path / "integra_270006_014152_2025"
    origem.mkdir()
    (origem / "manifest.json").write_text("[]", encoding="utf-8")  # nada baixado
    destino = tmp_path / "arq"

    m = arquivar(origem, destino, processo="270006/014152/2025", ocr=False)

    assert m["docs"] == []
    assert m["lacunas"] == [], "sem documento capturado não se afirma o que falta nos autos"
    assert m.get("captura_vazia") is True, "a captura vazia tem de ser declarada"


def _pdf(caminho):
    """PDF mínimo legível pelo fitz, para simular documento já baixado."""
    import fitz
    d = fitz.open()
    d.new_page().insert_text((60, 60), "TERMO DE REFERENCIA - objeto")
    d.save(str(caminho))
    d.close()


def test_captura_parcial_nao_afirma_lacuna(tmp_path):
    """Morte no meio do download: o que veio vale, mas não se afirma o que falta nos autos."""
    origem = tmp_path / "integra_260007_018055_2024"
    origem.mkdir()
    _pdf(origem / "000.pdf")
    (origem / "manifest.json").write_text(json.dumps({
        "processo": "260007/018055/2024", "total_arvore": 120, "completo": False,
        "docs": [{"i": 0, "arquivo": "000.pdf", "titulo": "Termo de Referência",
                  "contexto": "", "url": "", "ok": True}]}), encoding="utf-8")

    m = arquivar(origem, tmp_path / "arq", processo="260007/018055/2024", ocr=False)

    assert len(m["docs"]) == 1
    assert m["captura_completa"] is False
    assert m["lacunas"] == [], "captura interrompida não autoriza afirmar lacuna nos autos"
    assert "PARCIAL" in m["aviso"] and "120" in m["aviso"]


def test_formato_antigo_lista_continua_funcionando(tmp_path):
    """Os 355 processos já arquivados usam manifesto em LISTA — não podem quebrar."""
    origem = tmp_path / "integra_030001_004933_2026"
    origem.mkdir()
    _pdf(origem / "000.pdf")
    (origem / "manifest.json").write_text(json.dumps(
        [{"i": 0, "arquivo": "000.pdf", "titulo": "Contrato", "contexto": "", "url": "",
          "ok": True}]), encoding="utf-8")

    m = arquivar(origem, tmp_path / "arq", processo="030001/004933/2026", ocr=False)

    assert len(m["docs"]) == 1
    assert m["docs"][0]["titulo"] == "Contrato"
    assert m["captura_completa"] is None, "manifesto antigo não declara — não mentir True/False"


def test_captura_vazia_nao_destroi_arquivo_bom(tmp_path):
    """Rerun com cache vazio NÃO pode apagar um arquivo que já tinha documentos.

    Aconteceu em 2026-07-06: 33 processos ficaram com manifesto 'docs: []' enquanto
    9,2 MB de texto extraído (um deles com 210 documentos) seguiam no disco —
    invisíveis para todo consumidor E ignorados pela fila, que os via como prontos.
    """
    destino = tmp_path / "arq"
    (destino / "texto").mkdir(parents=True)
    (destino / "texto" / "000_contrato.txt").write_text("teor do contrato", encoding="utf-8")
    (destino / "manifest.json").write_text(json.dumps({
        "processo": "080001/007110/2023", "docs": [{"i": 0, "titulo": "Contrato",
        "fase": "contratacao", "tipo": "contrato", "texto": "texto/000_contrato.txt",
        "chars": 16, "ocr": False, "fotos": []}], "lacunas": [], "fotos_total": 0,
    }), encoding="utf-8")

    origem = tmp_path / "integra_080001_007110_2023"
    origem.mkdir()
    (origem / "manifest.json").write_text("[]", encoding="utf-8")   # captura falhou

    m = arquivar(origem, destino, processo="080001/007110/2023", ocr=False)

    assert len(m["docs"]) == 1, "arquivo bom preservado"
    gravado = json.loads((destino / "manifest.json").read_text(encoding="utf-8"))
    assert len(gravado["docs"]) == 1, "manifesto no disco NÃO foi zerado"


def test_manifesto_gravado_preserva_a_declaracao(tmp_path):
    origem = tmp_path / "integra_000001_000001_2025"
    origem.mkdir()
    (origem / "manifest.json").write_text("[]", encoding="utf-8")
    destino = tmp_path / "arq"
    arquivar(origem, destino, processo="000001/000001/2025", ocr=False)

    gravado = json.loads((destino / "manifest.json").read_text(encoding="utf-8"))
    assert gravado["captura_vazia"] is True
    assert gravado["lacunas"] == []


def _pdf_branco(caminho):
    """PDF em branco: sem texto e sem imagem — o SEI não serviu o conteúdo."""
    import fitz
    d = fitz.open()
    d.new_page()
    d.save(str(caminho))
    d.close()


def test_pdf_em_branco_marca_sem_conteudo(tmp_path):
    """Documento em branco fica MARCADO para reprocessar — sem afirmar a causa.

    (A causa se apurou depois: era o nosso insert_textbox falhando calado. O dado
    guarda o FATO 'não tem teor', não o diagnóstico.)
    """
    origem = tmp_path / "integra_070002_004135_2025"
    origem.mkdir()
    _pdf_branco(origem / "000.pdf")
    _pdf(origem / "001.pdf")            # este tem texto de verdade
    (origem / "manifest.json").write_text(json.dumps([
        {"i": 0, "arquivo": "000.pdf", "titulo": "Despacho", "contexto": "", "url": "", "ok": True},
        {"i": 1, "arquivo": "001.pdf", "titulo": "Termo de Referência", "contexto": "",
         "url": "", "ok": True}]), encoding="utf-8")

    m = arquivar(origem, tmp_path / "arq", processo="070002/004135/2025", ocr=False)

    assert m["sem_conteudo"] == 1, "só o documento em branco conta"
    assert m["docs"][0].get("sem_conteudo") is True
    assert not m["docs"][1].get("sem_conteudo"), "documento com texto tem teor"
