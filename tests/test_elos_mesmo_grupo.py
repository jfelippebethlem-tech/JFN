# -*- coding: utf-8 -*-
"""Grupo econômico declarado não pode poluir a fila de ELOS OCULTOS do fiscal.

O bucket "sem explicação" dos elos ocultos é a lista de prioridade: pares de empresas que dividem
telefone/e-mail E ambas recebem do Estado, sem forma jurídica que as una. Se um par óbvio de MESMO
GRUPO cai ali, o fiscal gasta atenção com o que não é achado — e o ruído esconde o elo real.

O DEFEITO (medido em 2026-08-08 no acervo real). `_marca` pegava a primeira palavra distintiva com
≥3 letras. "OI S.A. - EM RECUPERAÇÃO JUDICIAL" tem "OI" com 2 letras (pulado), então a marca virava
"RECUPERACAO" — boilerplate jurídico. "OI MÓVEL" virava "MOVEL". Marcas diferentes ⇒ o par
OI S.A. × OI MÓVEL (R$ 24,2 mi somados) caía em "sem explicação" como se fosse elo oculto, quando é
o mesmo grupo de telecom em recuperação judicial.

Duas correções, ambas conservadoras (marcar grupo à toa ESCONDE elo real):
1. Boilerplate jurídico e palavras-tipo entram nas genéricas — RECUPERAÇÃO/JUDICIAL/APOIO/ESCOLA
   nunca são marca.
2. Comparação por PREFIXO DE TOKENS além da marca — "OI" ⊂ "OI MÓVEL", pega matriz/subsidiária com
   marca curta que o limiar de 3 letras deixava passar.
"""
from __future__ import annotations

import pytest

from tools.elos_ocultos import _mesmo_grupo


@pytest.mark.parametrize("a,b,e_grupo", [
    # matriz/subsidiária de marca CURTA (2 letras) — o caso que motivou o conserto
    ("OI S.A. - EM RECUPERACAO JUDICIAL", "OI MOVEL S.A. - EM RECUPERACAO JUDICIAL", True),
    ("LIGHT S.A.", "LIGHT SERVICOS DE ELETRICIDADE S.A.", True),
    # mesma marca distintiva, sufixo diferente
    ("EXTREME DIGITAL CONSULTORIA E RENOVACAO", "EXTREME DIGITAL SERVICES SOCIEDADE", True),
    ("TAPEVAS SOLUCOES INTEGRADAS LTDA", "TAPEVAS SOLUCAO INTEGRADA LTDA", True),
    # NÃO são grupo: nomes distintos que só dividem palavra genérica
    ("AMIL ASSISTENCIA MEDICA", "COI CLINICAS ONCOLOGICAS", False),
    ("SERVICOS ALFA LTDA", "SERVICOS BETA LTDA", False),
    ("BANCO DO BRASIL S.A.", "BRASIL FOODS S.A.", False),
    # armadilha: duas associações de escolas DIFERENTES não são o mesmo grupo
    ("ASSOCIACAO DE APOIO A ESCOLA DOM PEDRO", "ASSOCIACAO DE APOIO A ESCOLA SANTA RITA", False),
    ("COSTA CAMARGO COM DE PRODUTOS HOSPITALARES", "UNIQUE DISTRIBUIDORA DE MEDICAMENTOS", False),
])
def test_mesmo_grupo_pega_o_obvio_sem_agrupar_o_alheio(a, b, e_grupo):
    assert bool(_mesmo_grupo(a, b)) is e_grupo, (
        f"{a!r} × {b!r} → {_mesmo_grupo(a, b)!r}, esperava grupo={e_grupo}")


def test_boilerplate_juridico_nunca_e_marca():
    """Duas empresas quaisquer em recuperação judicial não são o mesmo grupo pela situação."""
    from tools.elos_ocultos import _marca
    assert _marca("XYZ COMERCIO - EM RECUPERACAO JUDICIAL") != "RECUPERACAO"
    assert _marca("ABC INDUSTRIA - MASSA FALIDA") not in ("MASSA", "FALIDA")
    # e o par de falidas SEM marca comum não vira grupo
    assert not _mesmo_grupo("XYZ COMERCIO - EM RECUPERACAO JUDICIAL",
                            "ABC INDUSTRIA - EM RECUPERACAO JUDICIAL")


def test_grupo_e_conservador_prefixo_exige_primeiro_token_igual():
    """`SERVIÇOS X` e `SERVIÇOS Y` não viram grupo — SERVIÇOS é genérica e sai dos tokens.

    Prefixo que ignorasse o primeiro token uniria meia base pela palavra comum, ESCONDENDO elos
    reais. O primeiro token distintivo tem de coincidir.
    """
    assert not _mesmo_grupo("SERVICOS GERAIS DELTA", "SERVICOS GERAIS OMEGA")
    assert _mesmo_grupo("DELTA SERVICOS GERAIS", "DELTA SERVICOS ESPECIAIS")


def test_email_de_servico_e_reconferido_na_leitura():
    """Aresta `mesmo_email` de contador persistida ANTES do fix de parte-local não pode virar elo.

    O grafo é idempotente e não reclassifica o que já gravou. `contabilidade@loges-es.com.br` unia
    COSTA CAMARGO × UNIQUE como elo oculto (2026-08-08) porque a aresta foi persistida antes de
    `_de_servico` olhar a parte local do e-mail. `levantar()` reconfere na leitura — barato e cobre
    o passado sem reprocessar o grafo.
    """
    from tools.elos_ocultos import _RX_EMAIL
    from compliance_agent.osint.contato_compartilhado import _de_servico

    desc = "e-mail contabilidade@loges-es.com.br · 36325157000134 × 23864942000113"
    m = _RX_EMAIL.search(desc)
    assert m and _de_servico(m.group(0)), "o e-mail de contador não foi reconhecido no texto da aresta"

    # e-mail comum no texto NÃO é reclassificado
    desc2 = "e-mail flavios496@hotmail.com · 09175434000105 × 21116118000311"
    m2 = _RX_EMAIL.search(desc2)
    assert m2 and not _de_servico(m2.group(0))
