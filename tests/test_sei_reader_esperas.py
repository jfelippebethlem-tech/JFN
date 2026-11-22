"""Esperas do leitor do SEI por CONDIÇÃO, não por teto (vazão do it-campo, 14/11/2026).

Medido no it-campo: mediana de 6,3 s por documento (o laço comparava a URL do frame, e anexo externo é
servido sempre pela mesma URL) e ~170 s para o SEI declarar um processo restrito (4 repetições da mesma
pesquisa sem resultado + 24 s à espera de uma árvore que não viria).
"""
import asyncio

from tools import sei_reader as SR


class _Frame:
    def __init__(self, name="", url="", respostas=None, html=""):
        self.name, self.url, self._resp, self._html = name, url, list(respostas or []), html
        self.scripts = []

    async def evaluate(self, js, *a):
        self.scripts.append(js)
        return self._resp.pop(0) if self._resp else None

    async def content(self):
        return self._html


class _Pagina:
    def __init__(self, frames=()):
        self.frames, self.esperas, self.url = list(frames), 0, "https://sei/x"

    async def wait_for_timeout(self, ms):
        self.esperas += 1


def test_aviso_restrito_e_a_frase_do_sei():
    corpo = "Menu\nUnidade atual não possui acesso ao processo restrito SEI-270042/001731/2022.\nRodapé"
    assert SR.aviso_restrito(corpo) == "Unidade atual não possui acesso ao processo restrito SEI-270042/001731/2022"
    assert SR.aviso_restrito("Nenhum resultado encontrado.") is None
    assert SR.aviso_restrito("") is None


def test_abrir_processo_nao_repete_pesquisa_sem_resultado(monkeypatch):
    chamadas = {"cracked": 0, "quick": 0, "arvore": 0}

    async def cracked(pg, proc):
        chamadas["cracked"] += 1
        return {"documentos": [], "sem_resultado": True}

    async def quick(pg, proc):
        chamadas["quick"] += 1
        return {"documentos": [], "restrito_declarado": "Unidade atual não possui acesso ao processo restrito X"}

    async def esperar(pg, *a, **k):
        chamadas["arvore"] += 1
        return False

    monkeypatch.setattr(SR, "_ler_cracked", cracked)
    monkeypatch.setattr(SR, "_abrir_por_quicksearch", quick)
    monkeypatch.setattr(SR, "_esperar_arvore", esperar)
    assert asyncio.run(SR.abrir_processo(_Pagina(), "270042/001731/2022")) is None
    assert chamadas == {"cracked": 1, "quick": 1, "arvore": 0}


def test_abrir_processo_ainda_retenta_falha_de_leitura(monkeypatch):
    """Controle negativo: sem a resposta "nenhum resultado", as 4 tentativas continuam (a 1ª às vezes falha)."""
    n = {"cracked": 0}

    async def cracked(pg, proc):
        n["cracked"] += 1
        return {"documentos": [], "erro_cracked": "campo de pesquisa não apareceu"}

    async def quick(pg, proc):
        return {"documentos": []}

    async def esperar(pg, *a, **k):
        return False

    monkeypatch.setattr(SR, "_ler_cracked", cracked)
    monkeypatch.setattr(SR, "_abrir_por_quicksearch", quick)
    monkeypatch.setattr(SR, "_esperar_arvore", esperar)
    assert asyncio.run(SR.abrir_processo(_Pagina(), "270042/001731/2022")) is None
    assert n["cracked"] == 4


def _pagina_com_documento(respostas_vf):
    arv = _Frame(name="ifrArvore", respostas=[1, True])          # nº de âncoras; clique dado
    vf = _Frame(name="ifrVisualizacao", url="https://sei/controlador.php?acao=arvore_processar_html",
                respostas=respostas_vf)
    return _Pagina([arv, vf]), vf


def test_documento_novo_e_lido_mesmo_com_a_url_do_frame_igual():
    """Externo depois de externo: a URL do frame não muda. A marca no documento anterior é o sinal."""
    nativo = "Despacho de encaminhamento. " * 10
    pg, vf = _pagina_com_documento([0,                       # _frame_arvore conta âncoras no vf
                                    None,                    # grava a marca
                                    None, None,              # ainda o documento anterior (marca presente)
                                    ["loading", ""],         # o novo chegando
                                    ["complete", nativo]])
    res = asyncio.run(SR._conteudo_via_arvore(pg, {"url": "https://sei/?id_documento=42", "texto": "Despacho"}))
    assert res and res["via"] == "arvore" and res["conteudo"] == nativo.strip()
    assert pg.esperas == 4, "leu assim que o documento novo ficou pronto, sem girar até o teto"


def test_documento_que_nao_troca_nao_vira_teor_do_anterior():
    """Controle negativo: a marca nunca some (o frame não carregou nada novo) ⇒ nenhum teor é atribuído."""
    pg, vf = _pagina_com_documento([0, None] + [None] * 60 + [[]])   # 60 sondagens com a marca; depois os links
    res = asyncio.run(SR._conteudo_via_arvore(pg, {"url": "https://sei/?id_documento=42", "texto": "Despacho"}))
    assert res is None
    assert pg.esperas == 60


def test_no_de_captura_nao_monta_o_pdf_unico_que_o_lote_nao_leva():
    """O desvio fica DEPOIS do manifesto completo e ANTES da junção; sem a variável, a junção segue (VM-1)."""
    from pathlib import Path
    src = (Path(SR.__file__).parent / "sei_integra_completa.py").read_text(encoding="utf-8")
    completo, desvio, juncao = (src.index("_grava(manifest, not cortado_janela)"), src.index('"SEI_SEM_PDF_UNICO") == "1"'),
                                src.index("out = fitz.open()"))
    assert completo < desvio < juncao
    lote = (Path(SR.__file__).parent / "sei_integra_vm2.py").read_text(encoding="utf-8")
    assert 'itens[f"cache/integra_{tag}"]' in lote and 'itens[f"cache/INTEGRA_' not in lote


def _integra_com_um_escaneado(tmp_path):
    import fitz
    origem = tmp_path / "integra_270001_000001_2026"
    origem.mkdir()
    d = fitz.open(); d.new_page(); d.save(str(origem / "000.pdf")); d.close()      # página sem texto = "escaneado"
    return origem


def test_arquivador_usa_o_ocr_que_a_captura_ja_fez(tmp_path, monkeypatch):
    from tools import sei_arquivar as A
    origem = _integra_com_um_escaneado(tmp_path)
    (origem / "000.ocr.txt").write_text("NOTA FISCAL 123 — teor lido pelo OCR na captura", encoding="utf-8")
    monkeypatch.setattr(A, "_ocr_pdf", lambda b: (_ for _ in ()).throw(AssertionError("OCR refeito")))
    man = A.arquivar(origem, tmp_path / "arq", "270001/000001/2026")
    doc = man["docs"][0]
    assert doc["ocr"] is True and doc["chars"] == len("NOTA FISCAL 123 — teor lido pelo OCR na captura")


def test_arquivador_sem_texto_da_captura_roda_o_ocr(tmp_path, monkeypatch):
    """Controle negativo: sem o `.ocr.txt` (ou com ele mais VELHO que o PDF), o OCR roda como sempre."""
    import os
    from tools import sei_arquivar as A
    origem = _integra_com_um_escaneado(tmp_path)
    velho = origem / "000.ocr.txt"
    velho.write_text("texto de outra captura", encoding="utf-8")
    os.utime(velho, (1, 1))
    chamadas = []
    monkeypatch.setattr(A, "_ocr_pdf", lambda b: chamadas.append(1) or "TEOR DO OCR FEITO AGORA")
    man = A.arquivar(origem, tmp_path / "arq", "270001/000001/2026")
    assert chamadas == [1] and man["docs"][0]["chars"] == len("TEOR DO OCR FEITO AGORA")


def test_liberar_memoria_pdf_nao_quebra_e_o_leitor_chama_depois_do_ocr():
    from pathlib import Path
    from compliance_agent.sei import ocr_docs
    ocr_docs.liberar_memoria_pdf()                      # idempotente, sem PDF aberto, em qualquer libc
    src = Path(SR.__file__).read_text(encoding="utf-8")
    assert src.index("ocr_documento(body, tipo=tipo))") < src.index("liberar_memoria_pdf()       #")


class _PaginaPesquisa(_Pagina):
    """Página da pesquisa: `corpo` = innerText; `tem_link` = há link de processo (procedimento_trabalhar)."""
    def __init__(self, frames=(), corpo="", tem_link=False):
        super().__init__(frames)
        self.corpo, self.tem_link = corpo, tem_link

    async def evaluate(self, js, *a):
        return self.tem_link if "procedimento_trabalhar" in js else self.corpo


def test_resposta_da_pesquisa_nao_confunde_o_formulario_com_a_resposta():
    """22/11/2026: o submit do cracked esperava `expect_navigation` (25 s, não dispara no frameset) + `networkidle`
    (15 s, nunca chega) — 28–41 s por processo com a resposta já na tela. A espera nova volta quando a RESPOSTA
    pintou; o formulário de pesquisa (antes do clique) não pode contar como resposta."""
    r = lambda pg: asyncio.run(SR._resposta_da_pesquisa(pg))
    assert r(_PaginaPesquisa(corpo="Pesquisar em: Processos Documentos  Protocolo: [  ]")) is False
    assert r(_PaginaPesquisa(frames=[_Frame(name="ifrArvore")])) is True
    assert r(_PaginaPesquisa(corpo="Nenhum resultado encontrado.")) is True
    assert r(_PaginaPesquisa(corpo="Unidade atual não possui acesso ao processo restrito SEI-270006/000001/2024")) is True
    assert r(_PaginaPesquisa(corpo="1 registro", tem_link=True)) is True
