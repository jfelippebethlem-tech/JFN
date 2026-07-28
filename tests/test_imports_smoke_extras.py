# -*- coding: utf-8 -*-
"""Extra OPCIONAL ausente é `skip` declarado, não falha.

A VM-2 rodou a suíte numa venv montada só com `requirements.txt` e levou 4 falhas de
`test_imports_smoke`: `websocket` (3×) e `selenium` (1×). Nenhuma é regressão — os dois
vivem em `requirements-sei.txt`, que é **opcional por desenho** ("o core do JFN roda só com
requirements.txt", diz o cabeçalho do próprio arquivo).

Transformar extra opcional ausente em FALHA tem dois custos: esconde a falha real no meio do
ruído, e empurra quem só quer rodar o core a instalar Selenium e OCR. Um `skip` que diz o
nome do pacote e onde ele está declarado informa mais e não mente.

O que NÃO muda: qualquer outro `ImportError` continua falhando. Extra opcional é exceção
nomeada, não desculpa genérica.
"""
import pytest

from tests.test_imports_smoke import EXTRAS_OPCIONAIS, extra_opcional_faltando


def test_reconhece_extra_opcional_ausente():
    assert extra_opcional_faltando(ModuleNotFoundError("No module named 'websocket'",
                                                       name="websocket")) == "websocket"


def test_reconhece_submodulo_de_extra_opcional():
    assert extra_opcional_faltando(
        ModuleNotFoundError("...", name="selenium.webdriver")) == "selenium"


def test_modulo_de_producao_ausente_NAO_e_perdoado():
    """Se sumir uma dependência do core, o smoke tem de gritar."""
    assert extra_opcional_faltando(ModuleNotFoundError("...", name="fitz")) is None
    assert extra_opcional_faltando(ModuleNotFoundError("...", name="pandas")) is None


def test_outro_erro_de_import_nao_e_perdoado():
    assert extra_opcional_faltando(ImportError("circular import")) is None


def test_todo_extra_perdoado_esta_declarado_no_requirements_opcional():
    """A lista não pode virar depósito: cada nome tem de existir no requirements-sei.txt."""
    import pathlib

    texto = (pathlib.Path(__file__).resolve().parent.parent / "requirements-sei.txt").read_text()
    dist = {"websocket": "websocket-client", "cv2": "opencv-python", "selenium": "selenium",
            "webdriver_manager": "webdriver-manager", "easyocr": "easyocr",
            "pytesseract": "pytesseract"}
    for modulo in EXTRAS_OPCIONAIS:
        assert modulo in dist, f"{modulo}: acrescente o nome da distribuição ao mapa do teste"
        assert dist[modulo] in texto, f"{modulo} perdoado sem estar em requirements-sei.txt"
