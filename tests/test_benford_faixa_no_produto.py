# -*- coding: utf-8 -*-
"""A ressalva do Benford tem de chegar ao LEITOR, não morrer no módulo.

`analysis/benford.py` já era honesto: mede a confiabilidade da faixa de Nigrini pelo `n` e devolve
`mad_confiavel` / `faixa_confiavel` / `faixa_nota`. O número que ele declara foi medido em
2026-07-29 sobre 200 séries sintéticas perfeitamente benfordianas por tamanho:

      n  |   50   100   200   400   800  1500
  falso  | 100%   95%   64%   20%    2%    0%

**Em n=50 a taxa de falso positivo é de CEM POR CENTO** — toda série impecável é rotulada "NÃO
CONFORMIDADE" por puro ruído amostral.

Só que os três caminhos de relatório conferiam apenas `suficiente` (isto é, `n >= min_n = 50`) — o
exato limiar em que o teste sempre erra. O pior era `intel_analise.py`: escrevia "NÃO conformidade
… indício estatístico de fracionamento/valores fabricados" **dentro do parecer** com n≥50. Um parecer
de controle externo afirmando red flag a partir de um teste que, naquele tamanho, dispara sempre.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_benford_faixa_no_produto.py -q
"""
from __future__ import annotations

import random
import re
from pathlib import Path

from compliance_agent.analysis.benford import (
    N_CONFIAVEL_MAD,
    benford,
    confiabilidade_mad,
)

_RAIZ = Path(__file__).resolve().parent.parent


def _serie_benfordiana(n: int, semente: int = 42) -> list[float]:
    """10^U é benfordiana por construção — qualquer 'não conformidade' aqui é ruído."""
    rnd = random.Random(semente)
    return [10 ** (rnd.random() * 4) for _ in range(n)]


def test_o_modulo_declara_que_a_faixa_e_ilegivel_em_n_pequeno():
    assert confiabilidade_mad(50)["confiavel"] is False
    assert confiabilidade_mad(400)["classe"] == "marginal"
    assert confiabilidade_mad(N_CONFIAVEL_MAD)["confiavel"] is True


def test_serie_impecavel_em_n_50_e_marcada_como_nao_confiavel():
    """A faixa pode até sair "NÃO CONFORMIDADE" — o que não pode é sair sem a ressalva."""
    r = benford(_serie_benfordiana(50))
    assert r["n"] == 50
    assert r["suficiente"] is True, "n=50 satisfaz o min_n padrão — e é justamente o problema"
    assert r["mad_confiavel"] is False, (
        "em n=50 a faixa de Nigrini não é legível: 100% das séries benfordianas são rotuladas "
        "'NÃO CONFORMIDADE' por ruído amostral"
    )
    assert r["primeiro_digito"]["faixa_confiavel"] is False


def test_suficiente_nao_pode_ser_o_criterio_de_leitura_da_faixa():
    """`suficiente` responde 'há dados?'; `mad_confiavel` responde 'a faixa significa algo?'.
    Confundir os dois é o defeito, e a asserção abaixo é a prova de que são coisas diferentes."""
    r = benford(_serie_benfordiana(60))
    assert r["suficiente"] and not r["mad_confiavel"]


# ── os três caminhos de relatório ────────────────────────────────────────────

_CONSUMIDORES = (
    "compliance_agent/reporting/intel_md.py",
    "compliance_agent/reporting/intel_analise.py",
    "compliance_agent/reporting/intel_pdf.py",
)


def test_todo_consumidor_da_faixa_confere_a_confiabilidade():
    """Quem imprime `faixa_nigrini` tem de consultar `mad_confiavel`/`faixa_confiavel` por perto.

    Não é rigor de estilo: é a diferença entre "indício a verificar" e "artefato de amostra pequena
    apresentado como achado".
    """
    faltando = []
    for rel in _CONSUMIDORES:
        fonte = (_RAIZ / rel).read_text()
        if "faixa_nigrini" not in fonte:
            continue
        if not re.search(r"(mad_confiavel|faixa_confiavel)", fonte):
            faltando.append(rel)
    assert not faltando, (
        "imprime a faixa de Nigrini sem consultar a confiabilidade — em n=50 isso é falso positivo "
        f"garantido: {faltando}"
    )


def test_o_parecer_nao_afirma_fracionamento_com_faixa_ilegivel():
    """A pior das três: `intel_analise` escreve o achado DENTRO do parecer jurídico."""
    fonte = (_RAIZ / "compliance_agent/reporting/intel_analise.py").read_text()
    bloco = fonte.split("benford(", 1)[-1][:1400]
    assert re.search(r"(mad_confiavel|faixa_confiavel)", bloco), (
        "o parecer decide o achado de Benford sem checar se a faixa é legível naquele n"
    )
    assert "suficiente" not in bloco.split("NÃO CONFORM")[0][-260:] or \
challenge_ok(bloco), "o gate do parecer continua sendo `suficiente` (n>=50), que é o limiar do erro"


def challenge_ok(bloco: str) -> bool:
    """`suficiente` pode continuar aparecendo, desde que a confiabilidade também condicione."""
    return bool(re.search(r"(mad_confiavel|faixa_confiavel)", bloco))
