# -*- coding: utf-8 -*-
"""Todo pacote de terceiros que o código importa tem de estar declarado.

Achado pela VM-2 em 2026-07-28, montando uma venv NOVA: a coleta do pytest morreu com 8
erros de import antes de rodar um único teste. Faltavam `fitz` (PyMuPDF, em 6 módulos),
`xlrd` e `requests` — nenhum declarado em `requirements.txt`. Na VM-1 nada disso aparece
porque a venv é antiga e já os tem: o requirements estava mentindo havia tempo, em
silêncio, e só uma instalação limpa denuncia.

O custo real não é o pytest: `fitz` é importado por `sei/pdf_texto.py` e `sei/ocr_docs.py`
— a leitura de PDF do SEI, espinha do acervo. Uma instalação nova quebraria exatamente ali.

A catraca é a mesma dos `except Exception`: o número não pode CRESCER. Import local (um
`.py` do próprio projeto) não conta; apelido de distribuição (`fitz` -> PyMuPDF, `cv2` ->
opencv, `PIL` -> pillow) é resolvido pelo mapa abaixo.
"""
from __future__ import annotations

import ast
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
PACOTES = ("compliance_agent", "tools", "rotas")
IGNORA_CAMINHO = ("_arquivo", "_SANDBOX", "__pycache__")

# nome importado -> nome da distribuição no requirements
APELIDOS = {
    "fitz": "pymupdf", "cv2": "opencv-python-headless", "PIL": "pillow", "yaml": "pyyaml",
    "bs4": "beautifulsoup4", "dotenv": "python-dotenv", "sklearn": "scikit-learn",
    "dateutil": "python-dateutil", "docx": "python-docx", "fpdf": "fpdf2",
    "pdfminer": "pdfminer.six", "websocket": "websocket-client", "attr": "attrs",
}

# Exceção NOMEADA e presa ao arquivo, nunca um baseline numérico: um número cego deixaria o
# próximo import não declarado entrar de graça no lugar deste. `oci` é o SDK da Oracle, pesado,
# usado só para provisionar VM — fora do caminho de análise. Se ele aparecer em qualquer outro
# arquivo, o teste falha, que é o comportamento desejado.
EXCECOES = {("oci", "tools/criar_vm_oracle2.py")}


def _modulos_locais() -> set[str]:
    """Todo `.py` e todo diretório-pacote do projeto — import deles não pede requirements."""
    locais = {p.name for p in RAIZ.iterdir() if p.is_dir() and not p.name.startswith(".")}
    for py in RAIZ.rglob("*.py"):
        if not any(k in str(py) for k in IGNORA_CAMINHO):
            locais.add(py.stem)
    return locais


def _importados() -> set[tuple[str, str]]:
    """`(módulo, arquivo)` — o arquivo importa para prender a exceção ao seu único uso legítimo."""
    achados: set[tuple[str, str]] = set()
    for pacote in PACOTES:
        for py in (RAIZ / pacote).rglob("*.py"):
            if any(k in str(py) for k in IGNORA_CAMINHO):
                continue
            try:
                arvore = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            onde = str(py.relative_to(RAIZ))
            for no in ast.walk(arvore):
                if isinstance(no, ast.Import):
                    achados.update((a.name.split(".")[0], onde) for a in no.names)
                elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
                    achados.add((no.module.split(".")[0], onde))
    return achados


def _declarados() -> set[str]:
    decl: set[str] = set()
    for req in RAIZ.glob("requirements*.txt"):
        for linha in req.read_text(encoding="utf-8").splitlines():
            nome = linha.strip().split("#")[0].split("[")[0]
            for sep in ("==", ">=", "<=", "~=", ">", "<", ";"):
                nome = nome.split(sep)[0]
            nome = nome.strip().lower().replace("_", "-")
            if nome and not nome.startswith("-"):
                decl.add(nome)
    return decl


def nao_declarados() -> list[tuple[str, str]]:
    locais, declarados = _modulos_locais(), _declarados()
    fora = []
    for mod, onde in _importados():
        if mod in locais or mod in sys.stdlib_module_names or mod == "__future__":
            continue
        if (mod, onde) in EXCECOES:
            continue
        if APELIDOS.get(mod, mod).lower().replace("_", "-") not in declarados:
            fora.append((mod, onde))
    return sorted(fora)


def test_todo_import_de_terceiros_esta_declarado():
    fora = nao_declarados()
    assert not fora, (
        f"{len(fora)} import(s) de terceiros sem declaração em requirements*.txt: {fora}. "
        "Uma venv NOVA quebra nesses módulos — foi assim que a coleta do pytest morreu com "
        "8 erros na VM-2. Declare o pacote (com versão) ou registre o apelido em APELIDOS."
    )


def test_a_excecao_do_oci_vale_so_no_arquivo_que_a_justifica():
    """Se `oci` aparecer no caminho de análise, a exceção não pode cobri-lo."""
    assert EXCECOES == {("oci", "tools/criar_vm_oracle2.py")}, \
        "exceção nova em EXCECOES: justifique no comentário por que o pacote não é declarado"


def test_os_tres_que_quebraram_a_venv_nova_estao_declarados():
    """Regressão nomeada: PyMuPDF, xlrd e requests. `fitz` é a leitura de PDF do SEI."""
    declarados = _declarados()
    for pacote in ("pymupdf", "xlrd", "requests"):
        assert pacote in declarados, f"{pacote} sumiu do requirements — a venv nova quebra de novo"
