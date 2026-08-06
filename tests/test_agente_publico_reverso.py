# -*- coding: utf-8 -*-
"""Agente público × quadro societário do país — e as três recusas que impedem a lista de acusar.

O eixo é potente e por isso perigoso: casar 251.472 nomes de folha contra 27,6 milhões de linhas de
QSA produz 72.456 pessoas e 686.964 vínculos. Sozinho, esse número não vale nada — 41,6% dos nomes
que casam têm MAIS DE UM CPF mascarado no próprio índice, ou seja, são homônimos comprovados.

O que estes testes travam não é o SQL, é o que a casa promete: homônimo separado, explicação
institucional declarada ao lado do achado, e nome curto fora.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_agente_publico_reverso.py -q
"""
from __future__ import annotations

import pytest

from tools.agente_publico_reverso import explicacao_institucional, norm, semente


class _Con:
    """Conexão de mentira com o mínimo que `semente` consulta."""

    def __init__(self, folha, alerj):
        self._folha, self._alerj = folha, alerj

    def execute(self, sql, *a):
        return iter(self._alerj if "alerj_folha" in sql else self._folha)


def test_nome_curto_nao_entra():
    """"JOSE SILVA" casa com meio estado. Menos de três termos não é identificação, é sorteio."""
    con = _Con([("JOSE SILVA", "ASSESSOR", "CARGO COMISSAO", "SEC X"),
                ("MARIA DAS DORES PEREIRA", "ASSESSOR", "CARGO COMISSAO", "SEC X")], [])
    alvo = semente(con)
    assert "JOSE SILVA" not in alvo
    assert "MARIA DAS DORES PEREIRA" in alvo


def test_alerj_prevalece_e_marca_comissionado():
    """Mandato e gabinete são o poder que interessa — e vencem o registro na folha do Estado."""
    con = _Con([("ANA PAULA DE SOUZA", "PROFESSOR DOCENTE I", "EFETIVO", "SEEDUC")],
               [("ANA PAULA DE SOUZA", "ASSESSOR PARLAMENTAR V")])
    alvo = semente(con)["ANA PAULA DE SOUZA"]
    assert alvo["origem"] == "alerj" and alvo["comissionado"] == 1


def test_efetivo_de_concurso_nao_e_comissionado():
    """O marcador tem de separar quem entra por concurso de quem entra por nomeação."""
    con = _Con([("CARLOS EDUARDO DA MOTA", "PROFESSOR DOCENTE I", "EFETIVO", "SEEDUC")], [])
    assert semente(con)["CARLOS EDUARDO DA MOTA"]["comissionado"] == 0


@pytest.mark.parametrize("razao,classe", [
    ("ASSOCIACAO DE APOIO A ESCOLA CIEP 052", "apoio_a_escola"),
    ("FUNDACAO APOIO A PESQUISA ENSINO E ASSISTENCIA", "fundacao_de_apoio_universitaria"),
    ("MUTUA DOS MAGISTRADOS DO ESTADO DO RIO DE JANEIRO", "associacao_de_classe"),
    ("COOPERATIVA DE TRABALHO MEDICO", "cooperativa"),
])
def test_explicacao_institucional_e_o_desenho_do_programa(razao, classe):
    """35,1% dos pares defensáveis são Associação de Apoio à Escola — a entidade que a própria rede
    estadual usa para descentralizar recurso à unidade, dirigida por desenho por um professor
    daquela escola. Sem este veto a lista acusaria um terço do magistério."""
    assert explicacao_institucional(razao) == classe


def test_empresa_comum_nao_ganha_explicacao_de_graca():
    """Controle positivo: vetar demais é tão ruim quanto vetar de menos."""
    assert explicacao_institucional("MEDVIVA SERVICOS MEDICOS LTDA") == ""
    assert explicacao_institucional("LIFECARE - GESTAO, ASSISTENCIA E EDUCACAO") == ""


def test_norm_nao_funde_pessoas_por_acento_nem_separa_por_ele():
    assert norm("JOSÉ D'ÁVILA-NETO") == norm("JOSE D AVILA NETO")


def test_valor_nunca_e_somado_as_cegas_entre_fontes():
    """Um total único esconderia que as torneiras não são a mesma coisa.

    `siafe_ob` é Ordem Bancária do sistema do Estado; `pcrj_despesa` é o campo `pago` do arquivo de
    empenhos do município (cobre só 2019–2023); `emenda_favorecidos` é OB federal. E `pcrj_contratos`
    NÃO é dinheiro: contrato assinado é obrigação, não desembolso — entra na procedência e some do
    valor. Sem essa separação, um par apareceria com R$ 2,6 bilhões sem que o leitor soubesse que o
    número veio do portal municipal e não de uma OB.
    """
    import sqlite3

    from tools.agente_publico_reverso import dinheiro_publico

    con = sqlite3.connect(":memory:")
    con.executescript("""
      CREATE TABLE ob_orcamentaria_siafe (credor TEXT, status TEXT, valor REAL);
      INSERT INTO ob_orcamentaria_siafe VALUES ('11111111000100','Contabilizado',100.0),
                                               ('11111111000100','Anulado',9999.0);
      CREATE TABLE pcrj_despesa (credor_documento TEXT, pago REAL);
      INSERT INTO pcrj_despesa VALUES ('11111111000100', 50.0), ('22222222000100', 7.0);
      CREATE TABLE emenda_favorecidos (documento_favorecido TEXT, fase TEXT, valor REAL);
      INSERT INTO emenda_favorecidos VALUES ('11111111000100','Pagamento',5.0),
                                            ('11111111000100','Empenho',888.0);
      CREATE TABLE pcrj_contratos (fornecedor_documento TEXT, valor_global REAL, valor_inicial REAL);
      INSERT INTO pcrj_contratos VALUES ('33333333000100', 1000.0, 1000.0);
    """)
    valor, fontes = dinheiro_publico(con)
    con.close()

    assert valor["11111111"] == {"siafe_ob": 100.0, "pcrj_despesa": 50.0,
                                 "emenda_favorecidos": 5.0}, "OB anulada ou empenho entraram"
    assert valor["33333333"] == {}, "contrato assinado não é desembolso"
    assert "pcrj_contratos" in fontes["33333333"], "mas a procedência tem de constar"
    assert fontes["22222222"] == ["pcrj_despesa"]


def test_contrato_nao_desaparece_da_fila_por_nao_ter_valor():
    """Vetar o valor não pode virar vetar o par: contrato municipal é justamente o que o SIAFE
    estadual não enxerga, e foi ele que trouxe 127 dos 458 pares."""
    import sqlite3

    from tools.agente_publico_reverso import dinheiro_publico

    con = sqlite3.connect(":memory:")
    con.executescript(
        "CREATE TABLE pcrj_contratos (fornecedor_documento TEXT, valor_global REAL, "
        "valor_inicial REAL);"
        "INSERT INTO pcrj_contratos VALUES ('44444444000100', NULL, 10.0);")
    valor, _ = dinheiro_publico(con)
    con.close()
    assert "44444444" in valor


@pytest.mark.parametrize("nat,esperado", [
    ("2011", "ente_publico_ou_estatal"),   # empresa pública
    ("2038", "ente_publico_ou_estatal"),   # sociedade de economia mista
    ("1244", "ente_publico_ou_estatal"),   # administração pública / autarquia
    ("2054", ""),                          # S/A FECHADA é privada — vetar aqui seria vetar demais
    ("2062", ""),                          # LTDA
    ("3999", ""),                          # associação privada
])
def test_ente_publico_nao_tem_socio_tem_dirigente(nat, esperado):
    """O primeiro item da fila no painel era a RIOSAÚDE com dois Capitães BM no "quadro societário".

    Empresa pública não tem sócio: tem diretoria indicada pelo governo, como manda a lei das
    estatais. O corte é por NATUREZA JURÍDICA e para em 2038 — `2054` é S/A fechada e pegaria
    CONDOR S/A INDÚSTRIA QUÍMICA e CABERJ INTEGRAL SAÚDE, que são privadas. Medido: 15 dos 538.
    """
    assert explicacao_institucional("QUALQUER RAZAO SOCIAL S/A", nat) == esperado


def test_par_explicado_nao_lidera_a_fila():
    """Quem abre a tela lê o PRIMEIRO item como o mais grave — e ele era a RIOSAÚDE.

    Ordenar só por valor punha no topo o par que a própria ferramenta já explicava (empresa
    pública, dirigente nomeado), à frente de todo caso que de fato precisa de diligência. A fila é
    de TRABALHO: explicado por último, comissionado primeiro, valor só desempata.
    """
    from tools import agente_publico_reverso as M

    linhas = [
        # (nome_norm, nome, raiz, cargo, orgao, comissionado, origem)
        ("A A A", "A A A", "11111111", "DIRETOR", "X", 0, "folha_estado"),   # estatal, R$ 9 bi
        ("B B B", "B B B", "22222222", "ASSESSOR", "Y", 1, "folha_estado"),  # comissionado, R$ 10
        ("C C C", "C C C", "33333333", "TECNICO", "Z", 0, "folha_estado"),   # simples, R$ 1.000
    ]
    razao = {"11111111": ("ESTATAL S/A", "2011"), "22222222": ("PRIVADA LTDA", "2062"),
             "33333333": ("OUTRA LTDA", "2062")}
    pago = {"11111111": {"siafe_ob": 9e9}, "22222222": {"siafe_ob": 10.0},
            "33333333": {"siafe_ob": 1000.0}}

    ordem = sorted(
        [{"agente": n, "comissionado": bool(c),
          "valor_recebido": sum(pago[r].values()),
          "explicacao_institucional": M.explicacao_institucional(*razao[r])}
         for _, n, r, _cg, _o, c, _og in linhas],
        key=lambda x: (bool(x["explicacao_institucional"]), not x["comissionado"],
                       -x["valor_recebido"]))
    assert [x["agente"] for x in ordem] == ["B B B", "C C C", "A A A"], (
        "o par já explicado não pode encabeçar uma fila de trabalho")


@pytest.mark.parametrize("orgao_agente,pagador,casa", [
    # o fundo da corporação É a corporação — duas palavras distintivas em comum
    ("SECRETARIA DE ESTADO DE POLICIA MILITAR", "Fundo Especial da Polícia Militar", True),
    ("FUNDAÇÃO PARA INFÂNCIA E ADOLESCÊNCIA", "Fundação para a Infância e Adolescência", True),
    ("FUNDAÇÃO DEPARTAMENTO DE ESTRADAS DE RODAGEM",
     "Fund Dep Estradas de Rodagem do Estado do RJ", True),
    # CONTROLE NEGATIVO: duas secretarias diferentes não podem casar pelo vocabulário comum
    ("SECRETARIA DE ESTADO DE SAUDE", "Secretaria de Estado de Educação", False),
    ("SECRETARIA DE ESTADO DE EDUCACAO", "Fundação Saúde do Estado do Rio de Janeiro", False),
    ("SECRETARIA DE ESTADO DE POLICIA MILITAR", "Secretaria de Estado de Defesa Civil", False),
])
def test_conflito_so_acende_quando_o_pagador_e_o_proprio_orgao(orgao_agente, pagador, casa):
    """O discriminador que separa o comum do grave — e o risco dele é acender para todo mundo.

    Médico servidor sócio de PJ médica que vende ao Estado é frequente (25,9% dos pares sem
    explicação são PJ médica). O que não tem explicação banal é o servidor ser sócio de empresa que
    a SUA PRÓPRIA unidade paga: art. 9º, III da Lei 8.429/1992 e o impedimento do art. 20 da Lei
    9.784/1999. Sem tirar `SECRETARIA`, `ESTADO` e `FUNDAÇÃO` do cotejo, duas unidades quaisquer
    casariam por essas palavras e o eixo acusaria a folha inteira — por isso os controles negativos
    valem tanto quanto os positivos. Medido: 7 pares em 538.
    """
    from tools.agente_publico_reverso import conflito_de_orgao

    assert bool(conflito_de_orgao(orgao_agente, {pagador})) is casa


def test_conflito_nao_inventa_pagador_quando_nao_ha():
    from tools.agente_publico_reverso import conflito_de_orgao

    assert conflito_de_orgao("SECRETARIA DE ESTADO DE SAUDE", set()) == ""
    assert conflito_de_orgao("", {"Secretaria de Estado de Saúde"}) == ""
