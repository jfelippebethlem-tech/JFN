"""O auditor de contraste mede o PIXEL, e acerta os quatro casos de gabarito.

Por que este teste existe
-------------------------
Uma regra de projeto ("nunca decore o fundo de quem carrega texto") nasceu de um
laudo de 1,02:1 no cabecalho de tabela. O laudo era FALSO: a unica coisa clara era
uma faixa de 1px encostada na borda de baixo, longe do glifo. A regra curou o
sintoma removendo capacidade de design e deixou o instrumento torto.

Medido em 2026-07-25 contra `tests/fixtures/contraste_gabarito.html`, o auditor de
paradas acerta **1 dos 4** casos:

    c1 gradiente sob os glifos        gabarito reprova   antigo reprova   OK
    c2 faixa de 1px longe do texto    gabarito aprova    antigo reprova   FALSO POSITIVO
    c3 camada de cima transparente    gabarito reprova   antigo aprova    FALSO NEGATIVO
    c4 fundo em url()                 gabarito reprova   antigo mudo      NAO MEDIDO

O auditor de pixel acerta os 4. Este teste trava esse resultado: se alguem
"simplificar" o `auditar_contraste_pixel.py`, o gabarito diz exatamente o que
quebrou. Falso negativo (c3) e o mais grave dos tres — deixa passar falha real,
calado.

Precisa de Chrome no CDP 9222. Onde nao houver (a VM-2 roda a suite e nao tem
Chrome), o teste PULA em vez de falhar: a base de falhas nao pode crescer por
causa de ambiente.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request as ur
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
GABARITO = f"file://{RAIZ}/tests/fixtures/contraste_gabarito.html"

# gabarito: id do bloco -> verdade conhecida
VERDADE = {"c1": "reprova", "c2": "aprova", "c3": "reprova", "c4": "reprova"}


def _tem_cdp() -> bool:
    try:
        json.load(ur.urlopen("http://127.0.0.1:9222/json", timeout=3))
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


pytestmark = pytest.mark.skipif(
    not _tem_cdp(), reason="sem Chrome no CDP 9222 (a VM-2 roda a suite sem navegador)"
)


@pytest.fixture(scope="module")
def laudo() -> dict[str, dict]:
    """Mede o gabarito uma vez e indexa por id do bloco."""
    from tools.auditar_contraste_pixel import auditar

    return {o["id"]: o for o in auditar(GABARITO) if o["id"] in VERDADE}


def test_o_gabarito_inteiro_foi_medido(laudo):
    """Nenhum caso pode sair mudo — 'nao medido' foi o defeito nº 3 do auditor antigo."""
    faltando = sorted(set(VERDADE) - set(laudo))
    assert not faltando, f"caso(s) do gabarito nao medido(s): {faltando}"
    mudos = sorted(k for k, o in laudo.items() if o.get("cr") is None)
    assert not mudos, f"caso(s) medido(s) sem veredito: {mudos}"


@pytest.mark.parametrize("bloco", sorted(VERDADE))
def test_veredito_bate_com_o_gabarito(laudo, bloco):
    o = laudo[bloco]
    dito = "aprova" if o["passa"] else "reprova"
    assert dito == VERDADE[bloco], (
        f"{bloco}: gabarito diz {VERDADE[bloco]}, auditor disse {dito} "
        f"({o['cr']}:1, exige {o['exige']}, fundo {o.get('fundo')})"
    )


def test_a_mascara_vem_das_duas_sondas_e_nao_da_captura_natural(laudo):
    """O caso 4 e a prova viva do bug que a 1a versao tinha.

    Texto quase da cor do fundo: comparando a captura NATURAL com a captura sem
    texto, a diferenca cai abaixo de qualquer limiar e a mascara esvazia — o
    elemento sairia como 'glifo nao pintou' exatamente onde o contraste e o pior
    possivel. Com sonda preta contra sonda branca a mascara e maxima e independe
    do fundo. Se a contagem de glifos do c4 voltar a zero, a regressao e essa.
    """
    assert laudo["c4"]["pixels"] > 500, (
        "a mascara do caso 4 esvaziou — alguem trocou as duas sondas pela captura "
        "natural, e o auditor voltou a ser cego onde o contraste e pior"
    )


def test_nao_ficou_permissivo(laudo):
    """Contraprova: o caso 1 e falha real e obvia. Auditor que aprova tudo tambem
    'acerta' os falsos positivos — este teste impede essa saida barata."""
    assert not laudo["c1"]["passa"], "o auditor virou permissivo: aprovou branco sobre branco"
    assert laudo["c1"]["cr"] < 1.5
