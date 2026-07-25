"""Trava de regressão: dinheiro em documento brasileiro nunca sai no padrão americano.

O `f"{v:,.2f}"` do Python produz `57,208.00`. Num alerta que vai para o Telegram do dono,
ou num relatório de controle externo, isso se lê como **cinquenta e sete reais** — é erro
de leitura, não de estética. O formatador da casa é
`compliance_agent.reporting.intel_base.moeda`, que devolve `57.208,00`.

Duas travas:
  1. o formatador continua correto (milhar com ponto, decimal com vírgula, negativo);
  2. nenhuma linha do código volta a montar um `R$` com o formato americano.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from compliance_agent.reporting.intel_base import moeda

RAIZ = Path(__file__).resolve().parents[1]
PASTAS = ("compliance_agent", "tools", "reporting")
# o `{expr:,.2f}` de f-string — é ele que produz o formato americano
PLACEHOLDER = re.compile(r"\{[^{}]*:,\.2f\}")
# o idioma correto da casa: formata em americano e converte na sequência. Quem faz isso
# na mesma linha está certo — é assim que `moeda()` e os `_brl()` locais são escritos.
JA_CONVERTE = re.compile(r':,\.2f\}?"?\s*\.replace\(')


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        (1234567.89, "1.234.567,89"),
        (57208, "57.208,00"),
        (0, "0,00"),
        (-45.5, "-45,50"),
        (999.999, "1.000,00"),
        (1_000_000_000, "1.000.000.000,00"),
    ],
)
def test_moeda_no_padrao_brasileiro(entrada, esperado):
    assert moeda(entrada) == esperado


def test_moeda_nunca_devolve_ponto_decimal():
    """O sinal inequívoco do padrão americano: ponto separando os centavos."""
    for v in (1234.5, 1_000_000.01, 7.07):
        assert not re.search(r"\.\d{2}$", moeda(v)), moeda(v)


def _linhas_com_real_no_formato_americano() -> list[str]:
    achados = []
    for pasta in PASTAS:
        base = RAIZ / pasta
        if not base.exists():
            continue
        for py in base.rglob("*.py"):
            # `_arquivo/` é código aposentado (não produz documento hoje). A regra da
            # casa é mencionar código morto, não reescrevê-lo — então ele fica fora da
            # trava em vez de virar churn num arquivo que ninguém executa.
            if "_arquivo" in py.parts:
                continue
            try:
                texto = py.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for n, linha in enumerate(texto.splitlines(), 1):
                if "R$" in linha and PLACEHOLDER.search(linha) and not JA_CONVERTE.search(linha):
                    achados.append(f"{py.relative_to(RAIZ)}:{n}: {linha.strip()[:110]}")
    return achados


def test_nenhum_real_montado_no_padrao_americano():
    """Varre o código: `R$ {v:,.2f}` na mesma linha é o padrão americano num texto BR.

    Se esta trava falhar, troque o placeholder por `{moeda(v)}` — não conserte só o
    sintoma no relatório em que ele apareceu.
    """
    achados = _linhas_com_real_no_formato_americano()
    assert not achados, "R$ no padrão americano em %d linha(s):\n  %s" % (
        len(achados),
        "\n  ".join(achados[:40]),
    )
