"""Toda peca de arte que o painel CITA existe no disco — e a lista de posters bate com a realidade.

POR QUE ESTE TESTE EXISTE. Peca citada e ausente nao quebra nada: nao lanca erro, nao falha teste,
nao aparece em revisao. Ela vira um 404 no console, em toda carga, para sempre. E 404 recorrente
tem um custo que nao esta na rede: ele ensina quem abre o console a ignorar o console — que e onde
os cinco bugs do IIFE (§3 do PAINEL-v59) aparecem.

O caso que criou este arquivo tem duas partes, e a segunda e a mais instrutiva:

1. `nucleoViva` dizia num comentario que `nucleo-holo-rj` "nao tem .jpg — sem poster, sem erro", e
   a linha logo abaixo atribuia o poster SEM CONDICAO. 404 em toda carga das esferas Inicio e
   Estado, as duas mais visitadas.
2. A primeira correcao sondava o `.jpg` por HEAD antes de usar. **Ela nao corrigiu nada**: um HEAD
   para arquivo inexistente e um 404 igual. Trocar GET por HEAD limpa a rede, nao o console — e
   era o console que a correcao existia para limpar. So foi percebido porque o 404 reapareceu na
   vistoria, depois de commitado, com a afirmacao "console sem HTTP>=400" ja escrita.

Dai a forma final: uma lista EXPLICITA no codigo (`NUCLEO_COM_POSTER`) e este teste confrontando-a
com o disco. Custa zero requisicao, e nao pode divergir em silencio — se alguem gerar o poster que
falta e esquecer de anotar, o teste falha dizendo o nome do arquivo.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_ASSETS = _REPO / "static" / "assets"
_FONTES = [
    *(_REPO / "static" / "js" / "src").rglob("*.js"),
    *(_REPO / "static" / "css" / "src").glob("*.css"),
    *(_REPO / "static").glob("jfn-*.html"),
]

# Citacao de peca: `/static/assets/<nome>` em qualquer um dos fontes. So nome literal — peca
# montada em runtime (`'/static/assets/'+nome+'.mp4'`) e coberta pelo teste do poster abaixo e
# pela lista de esferas, que sao os dois unicos lugares onde isso acontece.
_CITACAO = re.compile(r"/static/assets/([A-Za-z0-9_.-]+\.[A-Za-z0-9]+)")


def _citadas() -> dict[str, set[str]]:
    fora: dict[str, set[str]] = {}
    for p in _FONTES:
        for nome in _CITACAO.findall(p.read_text(encoding="utf-8")):
            fora.setdefault(nome, set()).add(p.name)
    return fora


def test_toda_peca_citada_existe_no_disco():
    faltando = {n: sorted(onde) for n, onde in _citadas().items()
                if not (_ASSETS / n).exists()}
    assert not faltando, (
        "peca(s) citada(s) e ausente(s) — cada uma e um 404 em toda carga:\n"
        + "\n".join(f"  {n}  (citada em {', '.join(onde)})" for n, onde in faltando.items())
    )


def test_a_lista_de_posters_do_nucleo_bate_com_o_disco():
    """`NUCLEO_COM_POSTER` e a unica forma de saber quem tem poster sem pedir ao servidor."""
    cena = (_REPO / "static" / "js" / "src" / "cena" / "index.js").read_text(encoding="utf-8")

    m = re.search(r"NUCLEO_COM_POSTER\s*=\s*new Set\(\[([^\]]*)\]\)", cena)
    assert m, "`NUCLEO_COM_POSTER` sumiu de cena/index.js — sem ela o poster volta a ser adivinhado"
    declarados = set(re.findall(r"'([^']+)'", m.group(1)))

    mapa = re.search(r"const mapa=\{([^}]*)\}", cena)
    assert mapa, "o mapa esfera->nucleo sumiu de `nucleoViva`"
    nucleos = set(re.findall(r"'([^']+)'", mapa.group(1)))

    reais = {n for n in nucleos if (_ASSETS / f"{n}.jpg").exists()}
    assert declarados == reais, (
        f"a lista de posters divergiu do disco.\n"
        f"  declarados em NUCLEO_COM_POSTER: {sorted(declarados)}\n"
        f"  com .jpg em static/assets/     : {sorted(reais)}\n"
        f"Sobrando na lista = 404 no console. Faltando na lista = poster gerado que ninguem usa."
    )


@pytest.mark.parametrize("nome", ["mesa-projecao", "consciencia-fundo"])
def test_as_pecas_vivas_tem_o_trio_completo(nome: str):
    """webm + mp4 + jpg. O poster e o que sustenta os dois pisos (`reduced-motion` e modo sobrio):
    sem ele, a degradacao mostra um retangulo preto no lugar da peca."""
    for ext in ("webm", "mp4", "jpg"):
        assert (_ASSETS / f"{nome}.{ext}").exists(), (
            f"{nome}.{ext} faltando — peca viva sem o trio completo degrada para retangulo preto"
        )
