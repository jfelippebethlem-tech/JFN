# -*- coding: utf-8 -*-
"""O risco da investigação autônoma não pode sair de `substring in texto`.

A classificação vivia em três linhas dentro de `investigar_alvo`:

    if riscos_web or "alto" in texto or "irregular" in texto or "fraude" in texto:
        resultado["risco"] = "alto"

Um parecer que conclui **"não há indício de fraude"** contém a palavra "fraude" e era classificado
como risco ALTO — o que cria `Alerta` de severidade alta no banco e dispara Telegram. Falso
positivo por construção, e no canal mais barulhento do sistema: a negação é justamente a forma
mais provável de a palavra aparecer num parecer honesto.

"alto" é pior ainda: casa com "alto" isolado, mas também com qualquer texto que contenha a
sequência — inclusive "Planalto", "altos valores", "resultado alterado".

Estes testes travam o comportamento novo: sinal ESTRUTURADO decide; texto livre só decide por
rubrica fechada com citação conferida na fonte; sem LLM o veredito é `indeterminado`, nunca
`baixo` (INDISPONÍVEL ≠ regular).
"""
from __future__ import annotations

import json

import pytest

from compliance_agent.llm.orquestrador import _classificar_risco

# ─────────────────────────────── negação e colisão ────────────────────────────────────────────


@pytest.mark.parametrize("conclusao", [
    "Não há indício de fraude nem de irregularidade nos contratos analisados.",
    "Nada consta. Não foram encontrados indícios de irregularidade.",
    "A empresa não possui registro de fraude em nenhuma base consultada.",
])
def test_negacao_nao_vira_risco_alto(conclusao):
    """O bug original: a palavra aparece porque o parecer a NEGA."""
    r = _classificar_risco(conclusao, riscos_web=[], gerar=None)
    assert r["risco"] != "alto", f"negação classificada como alto: {r}"


@pytest.mark.parametrize("conclusao", [
    "Sede no Planalto Central, sem outras observações.",
    "Os altos valores decorrem do porte do contrato, já justificado nos autos.",
    "Resultado alterado após diligência: a pendência foi sanada.",
])
def test_substring_acidental_nao_vira_risco_alto(conclusao):
    """'alto' casava dentro de Planalto, altos, alterado."""
    r = _classificar_risco(conclusao, riscos_web=[], gerar=None)
    assert r["risco"] != "alto", f"colisão de substring classificada como alto: {r}"


# ─────────────────────────────── sinal estruturado ────────────────────────────────────────────


def test_sinal_estruturado_decide_sozinho():
    """`riscos_web` vem do coletor, já estruturado — este SIM é sinal, não texto."""
    r = _classificar_risco("", riscos_web=["condenação por improbidade"], gerar=None)
    assert r["risco"] == "alto"
    assert r["fonte"] == "estruturado"
    assert "condenação por improbidade" in json.dumps(r, ensure_ascii=False)


# ─────────────────────────────── ausência de LLM ──────────────────────────────────────────────


def test_sem_llm_texto_livre_fica_indeterminado():
    """INDISPONÍVEL ≠ baixo. Sem juízo, o sistema não afirma regularidade."""
    r = _classificar_risco("Texto longo e ambíguo sobre a empresa.", riscos_web=[], gerar=None)
    assert r["risco"] == "indeterminado"
    assert r["fonte"] == "indisponivel"


def test_llm_que_estoura_nao_derruba_a_classificacao():
    def _explode(_prompt, _sistema=None):
        raise RuntimeError("provedor fora do ar")

    r = _classificar_risco("qualquer coisa", riscos_web=[], gerar=_explode)
    assert r["risco"] == "indeterminado"


# ─────────────────────────────── rubrica fechada ──────────────────────────────────────────────


def test_rubrica_valida_com_citacao_ancorada_decide():
    conclusao = "A empresa foi declarada inidônea pelo TCU em 2024 e segue contratando."
    def _gerar(_prompt, _sistema=None):
        return json.dumps({"risco": "alto",
                           "citacao": "declarada inidônea pelo TCU em 2024",
                           "justificativa": "sanção impeditiva vigente"})

    r = _classificar_risco(conclusao, riscos_web=[], gerar=_gerar)
    assert r["risco"] == "alto"
    assert r["fonte"] == "rubrica_llm"


def test_citacao_que_nao_existe_no_texto_e_descartada():
    """Grounding conferido, não declarado — a citação tem de estar na fonte."""
    def _gerar(_prompt, _sistema=None):
        return json.dumps({"risco": "alto",
                           "citacao": "condenada por desvio de R$ 40 milhões",
                           "justificativa": "inventada"})

    r = _classificar_risco("Empresa regular, sem apontamentos.", riscos_web=[], gerar=_gerar)
    assert r["risco"] == "indeterminado"
    assert r["fonte"] == "citacao_nao_ancorada"


def test_risco_fora_da_escala_e_descartado():
    def _gerar(_prompt, _sistema=None):
        return json.dumps({"risco": "gravíssimo", "citacao": "abc", "justificativa": "x"})

    r = _classificar_risco("abc", riscos_web=[], gerar=_gerar)
    assert r["risco"] == "indeterminado"


def test_resposta_sem_json_nao_quebra():
    r = _classificar_risco("abc", riscos_web=[], gerar=lambda *_a, **_k: "desculpe, não sei")
    assert r["risco"] == "indeterminado"


# ─────────────────────────────── trava anti-regressão ─────────────────────────────────────────


def test_modulo_nao_classifica_risco_por_substring():
    """Se alguém reintroduzir `"fraude" in texto`, este teste morde."""
    import ast
    import inspect

    from compliance_agent.llm import orquestrador

    # Olha a ÁRVORE, não o texto: `"fraude" in texto` é uma comparação `In` cujo lado esquerdo é
    # uma string literal. Procurar a sequência no código-fonte cru acusaria a própria docstring
    # que explica por que a construção foi banida.
    arvore = ast.parse(inspect.getsource(orquestrador))
    ofensores = [
        no.left.value
        for no in ast.walk(arvore)
        if isinstance(no, ast.Compare)
        and any(isinstance(op, ast.In) for op in no.ops)
        and isinstance(no.left, ast.Constant)
        and isinstance(no.left.value, str)
        and len(no.left.value) > 3          # `"x" in dict` com chave curta é uso legítimo
    ]
    assert not ofensores, (
        f"classificação por substring reintroduzida ({ofensores}) — "
        "use _classificar_risco com rubrica fechada e citação ancorada")
