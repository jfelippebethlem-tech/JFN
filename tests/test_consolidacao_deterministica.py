# -*- coding: utf-8 -*-
"""Consolidação do dossiê SEM IA — porque consolidar não é raciocinar, é agrupar.

MEDIDO em 2026-07-28, duas tentativas, dois modelos: nenhum modelo grátis produziu as sete
seções ao consolidar 7 lotes. Ambos devolveram o próprio raciocínio em inglês, truncado. E é
uma tarefa em que o modelo não agrega nada: as extrações JÁ vêm rotuladas por tema pelo `map`,
e juntar rótulo com rótulo é trabalho de código — determinístico, gratuito, sem cota, sem
alucinação, e sem perder uma única citação.

A regra que este módulo respeita: nada é descartado. O que não se classifica vai para uma
seção própria, porque item extraído e jogado fora é pior que item mal arrumado.
"""
from __future__ import annotations

from compliance_agent.sei.dossie_fracionado import SECOES, classificar_tema, consolidar

_LOTE_1 = """- **Objeto e descrição**: Fornecimento de energia elétrica [doc 000_planilha.txt]

- **Valores (estimado, contratado, pago) com data**:
  - Valor total bruto (julho/2026): R$ 1.536.847,42 [doc 000_planilha.txt]
  - Juros e multa (julho/2026): R$ 7.093,26 [doc 008_despacho.txt]

- **Responsáveis**: Ordenador de Despesas: Nívea Dias Moreira Salgado, ID 5098630-9 [doc 017.txt]
"""

_LOTE_2 = """- **Objeto e descrição**: Fornecimento de energia elétrica [doc 000_planilha.txt]

- **Inconsistências entre documentos do próprio lote**: a NL cita R$ 1.504.942,22 e o
  despacho cita R$ 1.536.847,42 [doc 007_nl.txt]

- **Assunto sem rótulo previsto**: nota sobre protocolo interno [doc 099_outro.txt]
"""


def test_classifica_os_temas_do_roteiro():
    assert classificar_tema("Objeto e descrição") == "Objeto e enquadramento"
    assert classificar_tema("Valores (estimado, contratado, pago) com data") == "Valores"
    assert classificar_tema("Responsáveis") == "Partes e responsáveis"
    assert classificar_tema("Prazos, prorrogações e aditivos") == "Linha do tempo"
    assert classificar_tema("Inconsistências entre documentos") == "Contradições entre documentos"
    assert classificar_tema("Cláusulas que restrinjam a competição") == "Indícios a verificar"


def test_tema_desconhecido_nao_e_descartado():
    """Item extraído e jogado fora é pior que item mal arrumado."""
    assert classificar_tema("Assunto sem rótulo previsto") == "Outros fatos extraídos"


def test_consolida_agrupando_por_secao():
    md = consolidar([_LOTE_1, _LOTE_2])
    assert "## Objeto e enquadramento" in md
    assert "## Valores" in md
    assert "## Partes e responsáveis" in md
    assert "## Contradições entre documentos" in md


def test_preserva_todas_as_citacoes():
    """A citação é o que torna o achado utilizável em peça — nenhuma pode sumir na junção."""
    md = consolidar([_LOTE_1, _LOTE_2])
    for doc in ("000_planilha.txt", "008_despacho.txt", "017.txt", "007_nl.txt", "099_outro.txt"):
        assert f"[doc {doc}]" in md, f"citação de {doc} sumiu"


def test_deduplica_fato_repetido_entre_lotes():
    """O mesmo objeto aparece em 6 dos 7 lotes; repeti-lo 6× polui sem informar."""
    md = consolidar([_LOTE_1, _LOTE_2])
    assert md.count("Fornecimento de energia elétrica") == 1


def test_nao_inventa_secao_vazia():
    md = consolidar(["- **Objeto e descrição**: energia [doc a.txt]"])
    assert "## Lacunas" not in md


def test_secoes_saem_na_ordem_do_roteiro():
    md = consolidar([_LOTE_1, _LOTE_2])
    posicoes = [md.index(f"## {s}") for s in SECOES if f"## {s}" in md]
    assert posicoes == sorted(posicoes)


def test_bloco_vazio_ou_lixo_nao_quebra():
    assert consolidar(["", "   ", "texto solto sem estrutura nenhuma"])


def test_texto_sem_rotulo_vira_outros_e_nao_some():
    md = consolidar(["parágrafo solto com um fato e sua fonte [doc x.txt]"])
    assert "[doc x.txt]" in md


def test_monologo_do_modelo_some_da_consolidacao():
    """Nem todo modelo grátis separa raciocínio de resposta — veio monólogo em 9 dos 16 lotes
    da primeira execução. É ruído do processo de leitura, não fato do processo administrativo."""
    from compliance_agent.sei.dossie_fracionado import limpar_monologo
    bruto = ("Let me go through the documents systematically.\n"
             "I need to find the values.\n"
             "- **Valores** — R$ 1.504.942,22 [doc 007_nl.txt]")
    limpo = limpar_monologo(bruto)
    assert "Let me go" not in limpo
    assert "I need to find" not in limpo
    assert "R$ 1.504.942,22" in limpo


def test_linha_com_citacao_nunca_e_removida():
    """Critério de segurança: perder fato para limpar ruído é péssimo negócio."""
    from compliance_agent.sei.dossie_fracionado import limpar_monologo
    linha = "We must note the value R$ 68.143,66 de juros [doc 091_despacho.txt]"
    assert limpar_monologo(linha) == linha
