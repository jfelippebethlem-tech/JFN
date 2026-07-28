# -*- coding: utf-8 -*-
"""Dossiê que não conseguiu ler NÃO pode virar nota de "0 indícios".

Medido em 2026-07-28 sobre os 157 processos já analisados em série: **4 dossiês** trazem
"lote N não pôde ser lido — nenhum provedor respondeu; os documentos deste lote NÃO entraram
no dossiê", e os **4** geraram nota com `indicios: 0`. Somam **R$ 70.201.773,31**, sendo um
único de R$ 51,6 milhões cuja nota diz, em letras grandes, que nada foi encontrado.

Pior que o dossiê parcial é o dossiê parcial com cara de completo: o cabeçalho ainda declara
"Modo de leitura: leitura integral" e "Documentos com texto: 35", porque essa contagem vem da
CAPTURA, não da leitura. Um fiscal lendo a nota conclui processo limpo.

`0 indícios` só pode significar "procurei e não achei". Quando o modelo não respondeu, o
honesto é "não procurei" — e a nota tem de dizer isso antes de qualquer outra coisa.
"""
from tools.sei_analise_em_serie import _nota_vault, leitura_incompleta

# o contrato de `confronto_responsaveis` — a nota lê todas estas chaves
CONF = {"regex_nomes": [], "ids_regex": [], "ids_dossie": [], "so_no_dossie": [], "so_na_regex": []}

DOSSIE_OK = "# Dossiê\n\n## Fatos\n\n- Contrato assinado em 2024 [doc 001]\n"
DOSSIE_FALHO = (
    "# Dossiê do processo 080001_000744_2024\n\n"
    "| Cobertura | |\n|---|---|\n| Documentos com texto | 35 |\n| Modo de leitura | leitura integral |\n\n"
    "## Outros fatos extraídos\n\n"
    "- _(lote 1 não pôde ser lido — nenhum provedor respondeu; os documentos deste lote "
    "NÃO entraram no dossiê. Relançar o comando retoma só os lotes que faltam.)_\n"
)


def test_reconhece_o_lote_perdido():
    assert leitura_incompleta(DOSSIE_FALHO) == 1
    assert leitura_incompleta(DOSSIE_OK) == 0


def test_dossie_vazio_nao_e_tratado_como_lido():
    assert leitura_incompleta("") == 0  # sem dossiê não há afirmação a fazer


def test_a_nota_avisa_ANTES_de_dizer_quantos_indicios():
    nota = _nota_vault("080001_000744_2024", 51_600_000.0, DOSSIE_FALHO, [], CONF)
    corpo = nota.split("---", 2)[-1]
    assert "não" in corpo.lower() and "lid" in corpo.lower(), "a nota tem de declarar a falha"
    pos_aviso = corpo.lower().find("lote")
    assert pos_aviso >= 0, "o aviso de lote não lido tem de aparecer no corpo"


def test_o_frontmatter_marca_a_leitura_incompleta():
    """Quem varre as notas por metadado precisa enxergar isso sem ler o texto."""
    nota = _nota_vault("080001_000744_2024", 51_600_000.0, DOSSIE_FALHO, [], CONF)
    assert "leitura_incompleta: 1" in nota


def test_processo_lido_por_inteiro_nao_ganha_aviso():
    nota = _nota_vault("qualquer_processo", 1000.0, DOSSIE_OK, [], CONF)
    assert "leitura_incompleta" not in nota
    assert "não pôde ser lido" not in nota
