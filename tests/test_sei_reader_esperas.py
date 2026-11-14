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
