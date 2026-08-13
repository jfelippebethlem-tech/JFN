# -*- coding: utf-8 -*-
"""Artigo CITADO não é o artigo que FUNDAMENTA.

Medido em 58 leituras: **30 discordâncias no `dispositivo`** — e ao abrir os casos, os dois leitores
citavam artigos diferentes e AMBOS REAIS. A regra devolvia `art. 90` (rotina de liquidação da Lei
287/79), `art. 124`, `art. 27`; a IA achava o enquadramento da contratação (art. 75 VIII da 14.133,
art. 37 XXI da CF). Documento administrativo cita dezenas de artigos e a frequência elege o mais
rotineiro — a mesma doença do `favorecido`, que elegia o órgão por aparecer no cabeçalho.

Duas tentativas, e a segunda só funcionou depois de eu ler o texto em vez de supor:

1. Exigir fórmula de prosa ("com fulcro em", "nos termos do") → **zero achados**. Estreitar no
   escuro é tão ruim quanto não estreitar.
2. O documento traz um CAMPO ESTRUTURADO: `Enquadramento Legal:\\nLei n 14.133/2021, Art. 75, VIII`.
   Rótulo de formulário é âncora melhor que retórica de despacho — mas o rótulo e o artigo ficam em
   LINHAS diferentes, e o `[^\\n]` do primeiro rascunho zerava justamente o caso mais limpo.

O gabarito é o caso AGILE do vault (dispensa emergencial, `SEI-350010/025576/2026`).
"""
from __future__ import annotations

import pytest

from tools.sei_confronto_llm import texto_do_processo
from tools.sei_leitura_dupla import extrair_deterministico

AGILE = "350010/025576/2026"


@pytest.fixture(scope="module")
def texto():
    t = texto_do_processo(AGILE, max_chars=150_000)
    if not t:
        pytest.skip("processo fora do acervo nesta máquina")
    return t


def test_acha_o_enquadramento_do_gabarito_do_vault(texto):
    d = extrair_deterministico(texto, ano_proc=2026)["dispositivo"]
    assert d["valor"] == "art. 75, VIII", f"gabarito é dispensa emergencial; veio {d['valor']!r}"


def test_o_rotulo_e_o_artigo_podem_estar_em_linhas_diferentes():
    """Guarda direta do defeito 2: com `[^\\n]` no lugar de `[\\s\\S]` isto volta a zerar."""
    d = extrair_deterministico("Enquadramento Legal:\nLei n 14.133/2021, Art. 75, VIII\n")
    assert d["dispositivo"]["valor"] == "art. 75, VIII"


def test_artigo_de_rotina_sem_marca_de_fundamento_NAO_entra():
    """`art. 90 da Lei 287/79` aparece em quase todo processo de pagamento — citar não é fundamentar."""
    d = extrair_deterministico("Segue para liquidação na forma do art. 90 da Lei 287/1979.\n")
    assert not d["dispositivo"]["valor"]


def test_casa_o_rotulo_com_letras_espacadas_da_extracao_de_pdf():
    """`F U N D A M E N TA Ç Ã O :` é como a extração de PDF do Diário devolve maiúsculas. Nenhum
    regex de palavra inteira casa com isso — e era justamente onde a IA achava `art. 75, VIII`
    (dispensa emergencial) e a regra não colhia nada."""
    d = extrair_deterministico("F U N D A M E N TA Ç Ã O : Art. 75, inciso VIII da Lei nº 14.133\n")
    assert d["dispositivo"]["valor"] == "art. 75, VIII"


def test_casa_o_rotulo_Emb_Legal():
    """`Emb. Legal` (embasamento legal) é outro rótulo de formulário do empenho."""
    d = extrair_deterministico("Mod. Licitação 05 - Dispensa de Licitação "
                               "Emb. Legal Lei n 14.133/2021, Art. 75, VIII Origem 1\n")
    assert d["dispositivo"]["valor"] == "art. 75, VIII"


def test_o_dispositivo_guarda_MAIS_candidatos_que_os_demais_campos():
    """Para o dispositivo a lista de candidatos É a resposta — o despacho fundamenta em vários, e
    cortar em 4 jogava fora justamente o que a IA tinha achado."""
    texto = "".join(f"nos termos do art. {n}, da Lei 14.133/2021.\n" for n in range(1, 15))
    d = extrair_deterministico(texto)["dispositivo"]
    assert len(d["alternativas"]) > 4
