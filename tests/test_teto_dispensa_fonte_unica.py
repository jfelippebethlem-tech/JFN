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
