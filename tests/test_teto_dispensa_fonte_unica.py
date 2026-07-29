# -*- coding: utf-8 -*-
"""Trava arquitetural: o teto de dispensa tem UMA fonte.

Este teste existe porque o projeto já teve **cinco** cópias divergentes do mesmo número, e o
módulo canônico (`compliance_agent/limites_dispensa.py`) traz no próprio docstring a proibição de
duplicar a tabela — que foi ignorada cinco vezes.

Duas delas congelavam o valor de 2024 (R$ 59.906,02) e o aplicavam a TODOS os exercícios:
falso positivo em 2025 e 2026 (tetos reais R$ 62.725,59 e R$ 65.492,11) e falso negativo em
2021-2023. Num detector de fracionamento, isso significa acusar quem estava dentro do limite e
inocentar quem estourou.

O teste falha se alguém reintroduzir um literal de teto fora da fonte única.
"""
from __future__ import annotations

import pathlib


import pytest

from compliance_agent.limites_dispensa import LIMITES, ato_normativo, limite_dispensa

# Onde o valor PODE aparecer literalmente: a própria tabela e este teste.
_PERMITIDO = {
    "compliance_agent/limites_dispensa.py",
    "tests/test_teto_dispensa_fonte_unica.py",
}


def _valores_de_teto() -> set[float]:
    """Todos os tetos conhecidos, como NÚMERO.

    Comparar por dígitos (removendo a pontuação) era tentador e estava errado: o teto de obras de
    2021 é R$ 100.000,00, cujos dígitos são '10000000' — exatamente iguais aos de `10_000_000`.
    A primeira versão deste teste acusou meia dúzia de arquivos por causa dessa colisão.
    """
    # Só os tetos CORRIGIDOS por IPCA-E entram na trava. Os de 2021 são os valores originais da
    # lei — R$ 50.000,00 e R$ 100.000,00 — números redondos que aparecem legitimamente em qualquer
    # base como limiar, faixa ou piso. Guardá-los produziria 25 falsos positivos e o teste seria
    # desligado na primeira semana. Os valores corrigidos (59.906,02; 119.812,02; 62.725,59…) não
    # surgem por coincidência: se estão no código, são cópia.
    return {float(LIMITES[ano][tipo]) for ano in LIMITES if ano >= 2022
            for tipo in ("compras", "obras")}


def _literais_de_teto(caminho: pathlib.Path) -> set[str]:
    """Números de CÓDIGO que valem exatamente um dos tetos da tabela.

    Usa `tokenize` em vez de regex sobre o texto cru, e a distinção é o que torna o teste
    utilizável: um teto citado em COMENTÁRIO ou DOCSTRING é documentação legítima — inclusive
    esta base é cheia de comentários explicando por que o valor mudou de ano para ano. O que
    não pode existir é o número **operando** no código, fora da fonte única.
    """
    import tokenize

    achados: set[str] = set()
    validos = _valores_de_teto()
    try:
        with open(caminho, "rb") as fh:
            tokens = list(tokenize.tokenize(fh.readline))
    except (tokenize.TokenError, SyntaxError, OSError):
        return achados
    for tok in tokens:
        if tok.type != tokenize.NUMBER:
            continue
        try:
            valor = float(tok.string.replace("_", ""))
        except ValueError:
            continue
        if any(abs(valor - v) < 0.005 for v in validos):
            achados.add(tok.string)
    return achados


# ───────────────────────────── a tabela canônica ──────────────────────────────────────────────

@pytest.mark.parametrize("ano,compras,obras", [
    (2023, 57208.33, 114416.65),
    (2024, 59906.02, 119812.02),
    (2025, 62725.59, 125451.15),
    (2026, 65492.11, 130984.20),
])
def test_tetos_por_exercicio(ano, compras, obras):
    assert limite_dispensa(ano, "compras") == pytest.approx(compras)
    assert limite_dispensa(ano, "obras") == pytest.approx(obras)


def test_teto_muda_de_ano_para_ano():
    """O ponto que as cópias congeladas ignoravam: o número NÃO é constante."""
    anos = sorted(LIMITES)
    valores = [limite_dispensa(a, "compras") for a in anos]
    assert len(set(valores)) == len(valores), "cada exercício tem seu próprio teto"
    assert valores == sorted(valores), "o teto só sobe (correção por IPCA-E, art. 182)"


def test_ano_fora_da_tabela_usa_o_mais_recente_e_nao_quebra():
    assert limite_dispensa(2099, "compras") == limite_dispensa(max(LIMITES), "compras")


def test_consorcio_e_agencia_executiva_tem_teto_dobrado():
    """Art. 75 §2º. Sem isso, o teto aplicado a esses entes seria METADE do legal e o detector
    acusaria fracionamento onde a lei não vê nenhum."""
    assert limite_dispensa(2026, "compras", duplicado=True) == pytest.approx(
        2 * limite_dispensa(2026, "compras"))


def test_todo_exercicio_cita_o_ato_normativo():
    """Peça de controle externo precisa citar o decreto — sem isso o número é inverificável."""
    for ano in LIMITES:
        ato = ato_normativo(ano)
        assert ato and ("Decreto" in ato or "Lei" in ato), f"{ano}: ato normativo ausente"


# ───────────────────────────── a trava contra a 6ª cópia ──────────────────────────────────────

def _tetos_formatados() -> set[str]:
    """O mesmo teto, nas grafias em que ele aparece dentro de TEXTO.

    A trava numérica acima usa `tokenize` e só enxerga tokens NUMBER — por isso deixou passar
    seis cópias escondidas em *strings*: system-prompts de LLM (`llm/groq_agent.py`,
    `llm/hermes_agent.py`), base de conhecimento injetada no prompt (`llm/memoria.py`,
    `knowledge/base_legal.py`) e mensagem de alerta (`scheduler.py`). Um teto escrito no prompt é
    pior que no código: o modelo o repete como se fosse a lei vigente, e ninguém revisa prompt.
    """
    grafias: set[str] = set()
    for v in _valores_de_teto():
        inteiro = int(v)
        grafias.add(f"{inteiro:,}".replace(",", "."))          # 57.208
        grafias.add(f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))  # 57.208,33
        grafias.add(str(inteiro))                              # 59906  (default de env)
        grafias.add(f"{v:.2f}")                                # 59906.02
    return grafias


def _tetos_em_string(caminho: pathlib.Path) -> set[str]:
    """Tetos dentro de literais de string que NÃO são docstring.

    Usa `ast`, não `tokenize`, por dois motivos: comentários simplesmente não existem na árvore
    (ficam isentos de graça, como já são na trava numérica) e docstring é identificável por
    `ast.get_docstring` — explicar por que o número mudou de ano continua legítimo. O que não
    pode é o número **operar**: virar prompt, alerta ou verbete de base legal.
    """
    import ast

    achados: set[str] = set()
    grafias = _tetos_formatados()
    try:
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return achados
    docs = {
        d for no in ast.walk(arvore)
        if isinstance(no, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        for d in [ast.get_docstring(no, clean=False)] if d
    }
    for no in ast.walk(arvore):
        if not (isinstance(no, ast.Constant) and isinstance(no.value, str)):
            continue
        if no.value in docs:
            continue
        achados |= {g for g in grafias if g in no.value}
    return achados


def test_nenhum_prompt_nem_texto_repete_o_valor_do_teto():
    """A 6ª cópia não estava no código — estava no prompt.

    `llm/groq_agent.py` mandava ao modelo "R$ 57.208 compras / R$ 114.416 obras" (valores de
    2023) enquanto o teto de 2026 é R$ 65.492,11 / R$ 130.984,20 — 12% de defasagem numa
    instrução que o modelo trata como lei. É a violação literal da regra escrita em
    `compliance_agent/detectores/base.py:7`: limiar numérico fica no código, nunca no prompt.
    """
    raiz = pathlib.Path(__file__).resolve().parent.parent
    ofensores: dict[str, list[str]] = {}
    alvos = list(raiz.glob("compliance_agent/**/*.py")) + list(raiz.glob("tools/**/*.py"))
    for f in alvos:
        rel = f.relative_to(raiz).as_posix()
        if rel in _PERMITIDO:
            continue
        achados = _tetos_em_string(f)
        if achados:
            ofensores[rel] = sorted(achados)
    assert not ofensores, (
        "teto de dispensa escrito em TEXTO (prompt, alerta ou base de conhecimento) — o valor é "
        "por exercício e deve ser injetado de compliance_agent.limites_dispensa em tempo de "
        f"execução, nunca redigido: {ofensores}")


def test_nenhum_modulo_repete_o_valor_do_teto():
    raiz = pathlib.Path(__file__).resolve().parent.parent
    ofensores: dict[str, list[str]] = {}
    alvos = list(raiz.glob("compliance_agent/**/*.py")) + list(raiz.glob("tools/**/*.py"))
    for f in alvos:
        rel = f.relative_to(raiz).as_posix()
        if rel in _PERMITIDO:
            continue
        achados = _literais_de_teto(f)
        if achados:
            ofensores[rel] = sorted(achados)
    assert not ofensores, (
        "teto de dispensa DUPLICADO — importar de compliance_agent.limites_dispensa "
        f"(o valor é por exercício, não constante): {ofensores}")
