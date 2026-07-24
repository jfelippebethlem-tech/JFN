"""OCR de documento escaneado longo NÃO pode truncar em silêncio.

`MAX_PAGINAS_OCR` limita o OCR às primeiras N páginas (memória/CPU). Um Diário de Obra
de 31-45 páginas tinha as páginas 16+ descartadas SEM AVISO — o leitor achava que tinha
o diário inteiro (INDISPONÍVEL ≠ 0). São provas de execução diárias: perder metade das
páginas é perder metade da prova. Agora o cap é maior e, quando ainda assim trunca, o
texto DECLARA quantas páginas ficaram de fora.
"""
from compliance_agent.sei.ocr_docs import _texto_ocr_com_ressalva


def test_declara_quando_trunca():
    partes = [f"pagina {i} conteudo do diario de obra" for i in range(40)]
    txt = _texto_ocr_com_ressalva(partes, n_pag=45, n_feitas=40)
    assert "pagina 0" in txt
    assert "PARCIAL" in txt
    assert "40" in txt and "45" in txt, "tem de dizer 40 de 45 páginas"


def test_nao_declara_quando_cobre_tudo():
    partes = [f"pagina {i}" for i in range(12)]
    txt = _texto_ocr_com_ressalva(partes, n_pag=12, n_feitas=12)
    assert "PARCIAL" not in txt
    assert "pagina 11" in txt


def test_vazio_nao_inventa_ressalva():
    """Sem nenhum texto OCR, não anexa ressalva (não há o que ressalvar)."""
    assert _texto_ocr_com_ressalva([], n_pag=45, n_feitas=40) == ""
    assert _texto_ocr_com_ressalva(["", ""], n_pag=45, n_feitas=40) == ""


def test_orcamento_para_no_tempo_e_nunca_perde_o_que_fez(monkeypatch):
    """O coração inteligente: OCR para quando o tempo acaba, guarda o que fez, sem
    acoplar a nº de páginas. 20 páginas 'lentas', orçamento curto → faz algumas e para."""
    import compliance_agent.sei.ocr_docs as O

    def _ocr_lento(img, lang):
        import time
        time.sleep(0.05)            # cada página 'custa' 50ms
        return f"texto de {img}"
    monkeypatch.setattr(O, "_ocr_pil", _ocr_lento)

    imagens = [f"pg{i}" for i in range(20)]
    partes, n = O._ocr_ate_orcamento(imagens, "por", budget_s=0.15)  # ~3 páginas cabem

    assert 1 <= n < 20, f"parou cedo por orçamento (fez {n} de 20), não truncou tudo nem foi até o fim"
    assert len(partes) == n
    assert all(p for p in partes), "cada página feita tem seu texto — nada perdido"


def test_orcamento_cobre_tudo_quando_da_tempo(monkeypatch):
    import compliance_agent.sei.ocr_docs as O
    monkeypatch.setattr(O, "_ocr_pil", lambda img, lang: f"t{img}")
    imagens = [f"pg{i}" for i in range(5)]
    partes, n = O._ocr_ate_orcamento(imagens, "por", budget_s=999)
    assert n == 5, "com tempo de sobra, faz todas"
