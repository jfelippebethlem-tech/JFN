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


def test_artigo_sem_NENHUMA_marca_de_fundamento_NAO_entra():
    """Citar não é fundamentar — mas eu tinha errado ONDE fica a fronteira.

    A versão anterior deste teste afirmava que `na forma do art. 90 da Lei 287/79` era "rotina, não
    fundamento", e exigia que a regra o IGNORASSE. Medido depois, com outro leitor: o art. 90 da Lei
    287/1979 **é** a autoridade estadual de liquidação e pagamento, e é o fundamento correto de um
    processo de despesa. A IA acertava e a minha régua é que estava recusando o acerto.

    A fronteira certa é a FÓRMULA: menção solta não entra; menção introduzida por fórmula de
    autoridade entra.
    """
    d = extrair_deterministico("O art. 90 trata da liquidação, como se sabe.\n")
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


def test_as_formulas_de_autoridade_mais_comuns_da_redacao_administrativa():
    """Terceira rodada de âncoras, e de novo vieram do TEXTO, não do palpite.

    Com o leitor novo, a IA passou a citar `arts. 90, 91, 92 da Lei 287/1979` — a autoridade
    estadual de liquidação e pagamento, que é o fundamento CORRETO de processo de despesa — e a
    regra não os colhia. Faltavam as três fórmulas mais comuns do despacho brasileiro.
    """
    for trecho in ("na forma dos artigos 90, 91, e 92 da Lei Estadual 287/1979",
                   "em conformidade com o que estabelece os art. 90 a 92 da Lei nº 287/1979",
                   "preenchidos os requisitos dispostos nos Artigos 90, 91, 92 da Lei nº 287"):
        assert extrair_deterministico(trecho + "\n")["dispositivo"]["valor"].startswith("art. 90"), (
            f"fórmula não reconhecida: {trecho[:40]!r}")


def test_o_plural_de_artigo_nao_pode_quebrar_o_casamento():
    """`artigoS 90` falhava porque o padrão só aceitava `artigo` e `art.` — um `s` custava o
    fundamento inteiro de processos de pagamento."""
    d = extrair_deterministico("na forma dos artigos 90, 91 e 92 da Lei 287/1979\n")
    assert d["dispositivo"]["valor"] == "art. 90"


def test_o_rodape_da_assinatura_eletronica_NAO_e_o_fundamento_do_processo():
    """O falso positivo mais caro do campo, e a IA estava certa ao calar.

    `art. 28` era o campeão em dezenas de leituras. O texto é o carimbo que o SEI põe em TODO
    documento assinado: `Documento assinado eletronicamente por X, conforme horário oficial de
    Brasília, com fundamento nos art. 28º e 29º do Decreto nº 48.209`. É o embasamento da
    ASSINATURA, não da despesa — e, como a régua desempata por frequência, quanto MAIS documentos o
    processo tem, mais "fundamentado" no decreto de assinatura ele parecia.
    """
    rodape = ("Documento assinado eletronicamente por Fulano, Coordenador, em 09/10/2024, conforme "
              "horário oficial de Brasília, com fundamento nos art. 28º e 29º do Decreto nº 48.209.\n")
    assert not extrair_deterministico(rodape)["dispositivo"]["valor"]


def test_o_fundamento_de_verdade_sobrevive_ao_lado_do_rodape():
    """A guarda não pode cegar a leitura: o mesmo documento tem rodapé E fundamento."""
    texto = ("Autorizo a liquidação na forma dos artigos 90, 91 e 92 da Lei 287/1979.\n"
             "Documento assinado eletronicamente por Fulano, conforme horário oficial de Brasília, "
             "com fundamento nos art. 28º e 29º do Decreto nº 48.209.\n")
    d = extrair_deterministico(texto)["dispositivo"]
    assert d["valor"] == "art. 90"
