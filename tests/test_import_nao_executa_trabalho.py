# -*- coding: utf-8 -*-
"""Importar um módulo não pode EXECUTAR o trabalho dele.

Achado pela VM-2 em 2026-07-28, rodando a suíte numa máquina sem browser: a coleta do
pytest morria porque `tests/test_sei_pagina_de_unidade.py` importa uma função de
`tools/sei_integra_completa.py`, e esse módulo terminava com `asyncio.run(main())` **solto
no nível do módulo**, sem `if __name__ == "__main__"`. O import não trazia a função: ele
abria Chromium, baixava PDF e mandava Telegram.

Dois estragos, e o segundo é o pior:

1. Em máquina sem browser, o erro de coleta derruba a suíte INTEIRA — 0 teste executado.
   Um verde de 3.786 numa venv antiga escondia isso, porque lá o browser existe.
2. Em máquina COM browser, é pior: a suíte dispara captura real e envio ao Telegram como
   efeito colateral de importar uma função pura de 15 linhas.

`PROC = sys.argv[1]` no topo do mesmo módulo é a mesma doença: sob pytest, `sys.argv[1]` é
um argumento do pytest.

A catraca vale para toda a pasta `tools/`, não só para o módulo que denunciou.
"""
from __future__ import annotations

import ast
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parent.parent
IGNORA = ("_arquivo", "__pycache__", "_SANDBOX")

# chamadas que significam "faz o trabalho", não "define o trabalho"
EXECUTORAS = {"run", "main", "run_until_complete", "serve", "start"}

# Exceção NOMEADA (nunca contagem): `enviar_forense_telegram.py` é script de caso encerrado
# (veredito ITERJ×MGS, junho/2026) escrito inteiro no nível do módulo, sem função importável e
# sem `main()`. Pô-lo sob guard exigiria reindentar um script que ninguém importa — conferido:
# nenhum `import` dele existe no projeto. Reescrever caso encerrado é risco sem retorno.
EXCECOES = {"tools/enviar_forense_telegram.py"}


def _chamadas_de_trabalho_no_topo(caminho: pathlib.Path) -> list[str]:
    """Chamadas executadas na importação do módulo (fora de def/class e de `if __main__`)."""
    try:
        arvore = ast.parse(caminho.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []
    achados = []
    for no in arvore.body:                       # SÓ o corpo do módulo — não desce em def/class
        if isinstance(no, ast.If):               # `if __name__ == "__main__":` é o lugar certo
            continue
        if not isinstance(no, ast.Expr) or not isinstance(no.value, ast.Call):
            continue
        f = no.value.func
        nome = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if nome in EXECUTORAS:
            achados.append(f"{caminho.relative_to(RAIZ)}:{no.lineno} -> {nome}()")
    return achados


def test_nenhum_modulo_de_tools_executa_trabalho_ao_ser_importado():
    fora = []
    for py in (RAIZ / "tools").rglob("*.py"):
        if any(k in str(py) for k in IGNORA) or str(py.relative_to(RAIZ)) in EXCECOES:
            continue
        fora += _chamadas_de_trabalho_no_topo(py)
    assert not fora, (
        "módulo(s) executando trabalho no import — qualquer `from tools.X import f` dispara: "
        f"{fora}. Ponha sob `if __name__ == \"__main__\":`. Em máquina sem browser isso "
        "derruba a COLETA e a suíte inteira roda 0 teste."
    )


def test_sei_integra_completa_pode_ser_importado_sem_argumento_de_linha_de_comando():
    """`PROC = sys.argv[1]` no topo quebra sob pytest, onde argv é do pytest."""
    import sys

    salvo = sys.argv
    sys.argv = ["sei_integra_completa"]           # sem argumento nenhum, como num import limpo
    try:
        import importlib

        mod = importlib.import_module("tools.sei_integra_completa")
        assert callable(mod.parece_pagina_de_unidade)
    finally:
        sys.argv = salvo
