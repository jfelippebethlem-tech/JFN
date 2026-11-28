"""27/11/2026 — regra única #53: contrato → processo da licitação, só pela citação no documento que fala dela."""
from tools import e2_licitacao_relacionada as L


def test_so_documento_que_fala_de_licitacao_e_nunca_o_proprio():
    t = "Conforme o Pregão Eletrônico nº 12/2025, processo SEI-270006/000111/2025; contrato no SEI-270006/000999/2025."
    assert L.relacionados(t, "270006/000999/2025") == {"270006/000111/2025"}
    assert L.relacionados("Despacho: ver SEI-270006/000111/2025.", "270006/000999/2025") == set()   # sem licitação


def test_varre_o_arquivo_e_grava_fila_no_formato_das_antigas(tmp_path):
    (tmp_path / "270006_000999_2025" / "texto").mkdir(parents=True)
    (tmp_path / "270006_000999_2025" / "texto" / "001.txt").write_text("Edital nº 3/2025 — SEI 270006/000111/2025")
    itens = L.varrer(tmp_path)
    assert itens == [{"sei": "270006/000111/2025", "origem": "270006/000999/2025",
                      "documento": "270006_000999_2025/texto/001.txt"}]
