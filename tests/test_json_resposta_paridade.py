# -*- coding: utf-8 -*-
"""PARIDADE — o parse único não pode perder nada do que os três parsers antigos já acertavam.

Substituir código amplamente exercitado por código novo só se justifica com prova nos DOIS
sentidos (dono, 2026-07-28):

  1. **Não regride** — em todo caso que um parser antigo resolvia, o novo devolve o MESMO objeto.
  2. **Ganha** — existem casos reais de resposta de LLM em que os antigos devolviam `None`
     (evidência descartada) e o novo recupera.

As três implementações originais estão preservadas aqui, verbatim, como referência viva. Se um
dia o novo divergir num caso que o antigo acertava, este teste falha e o veredito é reverter.
"""
import json
import re

import pytest

from compliance_agent.llm.json_resposta import parse_json_llm


# ── as três implementações ANTIGAS, verbatim (referência; não usar em produção) ──────────────

def antigo_direcionamento(raw: str):
    """`compliance_agent/direcionamento_cerebro.py::_parse_json` até 2026-07-28."""
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        pass
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return None


def antigo_base(raw):
    """`compliance_agent/detectores/base.py::_parse_json` até 2026-07-28 (mesma lógica)."""
    return antigo_direcionamento(raw)


def antigo_groq(raw: str):
    """`compliance_agent/llm/groq_agent.py::_parse_json` até 2026-07-28."""
    if raw is None:
        return None
    raw = raw.strip()
    raw = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        idx = raw.find(start_char)
        if idx >= 0:
            depth = 0
            for i, c in enumerate(raw[idx:], idx):
                if c == start_char:
                    depth += 1
                elif c == end_char:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(raw[idx:i + 1])
                        except Exception:  # noqa: BLE001
                            break
    return None


ANTIGOS = (antigo_direcionamento, antigo_base, antigo_groq)


# ── corpus: formas reais de resposta do LLM ──────────────────────────────────────────────────
# Cada entrada é uma resposta que o modelo produz. O corpus é o mesmo para os dois testes: o de
# não-regressão (todo acerto antigo é acerto novo) e o de ganho (algum antigo falhava).

CORPUS = [
    # — o feijão com arroz, que os antigos já acertavam —
    '{"grau":"verde"}',
    '```json\n{"grau":"amarelo","achados":[]}\n```',
    '```\n{"grau":"vermelho"}\n```',
    'lixo antes {"grau":"amarelo","x":1} lixo depois',
    '[{"a":1},{"a":2}]',
    '{"achados":[{"duvida":"socio comum","veredito":"agrava","fontes":["url"]}],"resumo":"ok"}',
    '{"resumo":"acentuação e emoji ✅ preservados","grau":"verde"}',
    '{"n":[1,2,3],"aninhado":{"a":{"b":[{"c":1}]}}}',
    '  \n\n {"grau":"verde"}  \n ',
    '{"texto":"linha 1\\nlinha 2","grau":"verde"}',
    '{"escapado":"aspas \\" no meio","grau":"verde"}',
    # — as formas que faziam ao menos um antigo desistir —
    'Claro! Segue:\n\n```json\n{"grau":"amarelo"}\n```\n\nEspero ter ajudado.',
    'Responderei no formato {chave: valor}: {"grau":"vermelho","n":2}',
    '{"resumo":"o custo } por item destoa","grau":"amarelo"}',
    '{"achados":[{"duvida":"x"},],"grau":"verde",}',
    '{"resumo":"tres achados","achados":[{"duvida":"socio comum","veredito":"agrava"},{"duvida":"end',
    '{"grau":"verde"} {"grau":"vermelho"}',
]

SEM_JSON = ["", None, "não há nada de JSON nesta frase", "{", "}{", "   "]


# A única divergência deliberada: lista no topo. O `antigo_groq` procurava `{` antes de `[` e
# devolvia o PRIMEIRO elemento como se fosse a resposta inteira — ver
# `test_divergencia_deliberada_lista_no_topo` e `tests/test_groq_parse_dict.py`.
LISTA_NO_TOPO = ('[{"a":1},{"a":2}]',)


@pytest.mark.parametrize("raw", [r for r in CORPUS if r not in LISTA_NO_TOPO])
def test_nao_regride_em_nada_que_o_antigo_acertava(raw):
    """Onde QUALQUER parser antigo devolvia um objeto, o novo devolve o mesmo objeto."""
    novo = parse_json_llm(raw)
    for antigo in ANTIGOS:
        esperado = antigo(raw)
        if esperado is None:
            continue  # o antigo desistia; ganho é medido no teste seguinte
        assert isinstance(novo, type(esperado)), f"{antigo.__name__}: mudou o tipo em {raw!r}"
        if isinstance(novo, dict):
            # `_truncado` é sinal novo, jamais dado do modelo: comparar sem ele
            assert {k: v for k, v in novo.items() if k != "_truncado"} == esperado, \
                f"{antigo.__name__}: divergiu em {raw!r}"
        else:
            assert novo == esperado, f"{antigo.__name__}: divergiu em {raw!r}"


@pytest.mark.parametrize("raw", SEM_JSON)
def test_nao_inventa_onde_os_antigos_tambem_nada_achavam(raw):
    assert parse_json_llm(raw) is None
    assert all(antigo(raw) is None for antigo in ANTIGOS)


def test_o_ganho_existe_e_e_medido():
    """A justificativa da troca, em número: casos em que TODOS os antigos descartavam a resposta."""
    resgatados = [raw for raw in CORPUS
                  if all(a(raw) is None for a in ANTIGOS) and parse_json_llm(raw) is not None]
    assert resgatados, "sem ganho medido, a substituição não se justifica — reverter"
    # os três antigos falhavam juntos nestes; documentado aqui para a próxima sessão auditar
    assert len(resgatados) >= 2


def test_divergencia_deliberada_lista_no_topo():
    """A troca muda UM comportamento, e para melhor: lista deixa de virar o seu primeiro item."""
    raw = '[{"a":1},{"a":2}]'
    assert antigo_groq(raw) == {"a": 1}                      # o antigo escondia `{"a":2}`
    assert parse_json_llm(raw) == [{"a": 1}, {"a": 2}]       # o novo entrega o que veio
    assert antigo_direcionamento(raw) == [{"a": 1}, {"a": 2}]  # e concorda com os outros dois


def test_ganho_por_parser_antigo():
    """Quantos casos do corpus cada antigo perdia — o novo não perde nenhum."""
    perdas = {a.__name__: sum(1 for raw in CORPUS if a(raw) is None) for a in ANTIGOS}
    assert all(v > 0 for v in perdas.values()), f"nenhum antigo falhava; troca injustificada: {perdas}"
    assert sum(1 for raw in CORPUS if parse_json_llm(raw) is None) == 0
