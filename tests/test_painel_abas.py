"""A lista de abas do painel tem UMA fonte: o proprio painel.

Os dois auditores (contraste e layout) carregavam uma copia manual de 9 abas. O
painel tem 51. Copia de lista diverge — foi assim que a constante de dispensa
ganhou uma terceira copia dentro de um detector e produziu falso positivo publico.
Aqui a divergencia era pior porque silenciosa: o auditor dizia "9 abas limpas" e
o laudo era lido como "o painel esta limpo".

Este teste nao roda navegador — le o HTML. Custa milissegundos e vale na VM-2.
"""

from tools.painel_abas import abas, abas_por_esfera

# Se o painel ganhar ou perder aba, ATUALIZE estes numeros de proposito: a
# mudanca tem de ser uma decisao, nao um efeito colateral que ninguem viu.
TOTAL = 51
POR_ESFERA = {"inicio": 1, "estado": 14, "prefeitura": 14, "geral": 22}


def test_le_todas_as_abas_do_painel():
    lista = abas()
    assert len(lista) == TOTAL, (
        f"o painel tem {len(lista)} abas, o teste esperava {TOTAL} — se a mudanca "
        "foi de proposito, atualize TOTAL e POR_ESFERA aqui"
    )
    assert lista[0] == "i_cockpit", "a primeira aba deixou de ser o cockpit"
    assert len(set(lista)) == len(lista), "id de aba repetido no painel"


def test_agrupa_por_esfera():
    por_esf = abas_por_esfera()
    assert set(por_esf) == set(POR_ESFERA), (
        f"as esferas mudaram: {sorted(por_esf)} != {sorted(POR_ESFERA)}"
    )
    for esf, quantas in POR_ESFERA.items():
        assert len(por_esf[esf]) == quantas, (
            f"esfera {esf}: {len(por_esf[esf])} abas, esperava {quantas}"
        )


def test_os_auditores_usam_a_fonte_unica():
    """Guarda-corpo contra a volta da copia manual.

    Nao basta existir uma fonte unica; os auditores tem de CHAMAR ela. Se alguem
    colar de volta uma lista literal, o laudo volta a cobrir uma fatia e a ser
    lido como o todo.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    for nome in ("auditar_contraste.py", "auditar_layout.py"):
        fonte = (raiz / "tools" / nome).read_text(encoding="utf-8")
        assert "painel_abas" in fonte, (
            f"{nome} nao usa mais tools/painel_abas — a lista de abas voltou a ser copia"
        )
