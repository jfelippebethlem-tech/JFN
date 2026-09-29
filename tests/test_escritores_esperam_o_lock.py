# -*- coding: utf-8 -*-
"""Quem ESCREVE no compliance.db tem de esperar o lock, não morrer nele.

O banco tem vários escritores concorrentes (sweeps do SEI, avaliação 360, cruzamentos de
inteligência, coleta do SIAFE) e o `sqlite3.connect` sem `timeout` espera só **5 segundos** antes
de levantar `database is locked`.

Medido em 2026-08-09: a recoleta do SIAFE — que custa MINUTOS de browser por fatia — morreu com
`database is locked` **depois de 18 fatias já colhidas**. Perder trabalho caro por não esperar
alguns segundos é o pior negócio possível; e o erro aparece longe da causa, o que faz perder tempo
procurando bug de coleta onde há disputa de escrita.

Conexões de LEITURA (`mode=ro`) ficam de fora de propósito: leitor não bloqueia ninguém e um
timeout longo ali só esconderia lentidão.
"""
from __future__ import annotations

import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parent.parent
# módulos que escrevem no banco principal e já foram corrigidos — a catraca impede a regressão
ESCRITORES = [
    "compliance_agent/siafe_ob_orcamentaria.py",
    "compliance_agent/cruzamento.py",
    "compliance_agent/lex_base_empirica.py",
    "compliance_agent/rede_societaria.py",
]
# `[^)]*` pararia no primeiro `)` e cortaria `sqlite3.connect(str(_DB), timeout=120)` em
# "str(_DB" — o detector acusaria a conexão que ele mesmo acabou de proteger. Equilibra parênteses.
def _args_da_chamada(texto: str, inicio: int) -> str:
    nivel, i = 0, inicio
    while i < len(texto):
        if texto[i] == "(":
            nivel += 1
        elif texto[i] == ")":
            nivel -= 1
            if nivel == 0:
                return texto[inicio + 1:i]
        i += 1
    return texto[inicio:inicio + 120]


def _sem_timeout(texto: str) -> list[str]:
    fora = []
    for m in re.finditer(r"sqlite3\.connect\(", texto):
        args = _args_da_chamada(texto, m.end() - 1)
        if "mode=ro" in args or "timeout=" in args or ":memory:" in args:
            continue
        fora.append(args.strip()[:60])
    return fora


def test_escritores_conhecidos_esperam_o_lock():
    for arq in ESCRITORES:
        p = RAIZ / arq
        assert p.exists(), f"{arq} sumiu — atualize a lista desta catraca"
        faltando = _sem_timeout(p.read_text(encoding="utf-8"))
        assert not faltando, (
            f"{arq} voltou a abrir o banco para ESCRITA sem `timeout=`: {faltando}. "
            "Sem ele, 5 s de disputa matam a passada — e a coleta do SIAFE custa minutos por fatia")


def test_a_catraca_reconhece_conexao_protegida():
    """Se o reconhecedor quebrar, a catraca passa a valer nada — então ele também é testado."""
    assert _sem_timeout("sqlite3.connect(str(_DB), timeout=120)") == []
    assert _sem_timeout('sqlite3.connect(f"file:{db}?mode=ro", uri=True)') == []
    assert _sem_timeout("sqlite3.connect(_DB)") == ["_DB"]
