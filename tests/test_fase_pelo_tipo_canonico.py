# -*- coding: utf-8 -*-
"""A fase tem de aproveitar o TIPO que o manifesto já resolveu.

Achado na leitura integral do SEI-080007/001365/2024 (2026-08-03): o processo tem Termo de
Referência de 20.000 caracteres com ONZE anexos (síntese do plano de manutenção, acordo de nível
de serviço, ferramentas, modelos) — e o sistema acusou "falta Planejamento (ETP/TR/pesquisa de
preços)" com gravidade média.

Causa: `fases.classificar()` decide pelo TÍTULO, e o título deste TR é "Formulário de solicitação
de material ou serviço" — que não casa nenhum padrão. Só que o classificador de documentos JÁ
tinha acertado: o manifesto traz `tipo: termo_referencia`. A fase ignorava o que a casa já sabia
e devolvia `indefinida`.

Uma peça sem fase não conta como fase presente, então a lacuna é cobrada mesmo com a peça nos
autos — e o processo inteiro sobe de score por um documento que está lá.
"""
from compliance_agent.sei import fases


def test_fase_do_tipo_conhece_os_tipos_canonicos():
    assert fases.fase_do_tipo("termo_referencia") == "planejamento"
    assert fases.fase_do_tipo("parecer") == "controle"
    assert fases.fase_do_tipo("ordem_bancaria") == "despesa"


def test_tipo_desconhecido_nao_inventa_fase():
    assert fases.fase_do_tipo("outro") == "indefinida"
    assert fases.fase_do_tipo("") == "indefinida"
    assert fases.fase_do_tipo("coisa_que_nao_existe") == "indefinida"


def test_titulo_que_nao_diz_nada_cai_no_tipo():
    """O caso real: título genérico, tipo canônico correto."""
    assert fases.classificar("Formulário de solicitação de material ou serviço 67136232") == (
        "indefinida", "outro")
    assert fases.classificar_com_tipo(
        "Formulário de solicitação de material ou serviço 67136232",
        "termo_referencia") == ("planejamento", "termo_referencia")


def test_titulo_explicito_MANDA_sobre_o_tipo():
    """A doutrina da casa não muda: quando o título diz, é o título que vale (o classificador por
    conteúdo já rotulou certidão como parecer e nota fiscal como contrato)."""
    assert fases.classificar_com_tipo("Parecer 462 (74886257)", "contrato") == (
        "controle", "parecer")


def test_sem_tipo_o_comportamento_e_o_de_sempre():
    assert fases.classificar_com_tipo("Despacho de Encaminhamento 123", "") == fases.classificar(
        "Despacho de Encaminhamento 123")
