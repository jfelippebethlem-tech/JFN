# -*- coding: utf-8 -*-
"""gestor_recebe_da_osc — FIA × FUNRIO (SEI-310002/000054/2025): portaria doc 44 × comprovante doc 8."""
from compliance_agent.padroes import _pagamento_comum as C
from compliance_agent.padroes.gestor_recebe_da_osc import _trie_regex, cruzar, nomes_designados, pagamentos_do_nome

PORTARIA_44 = ("RESOLVE: Art. 1º - Designar os servidores abaixo descritos para compor a Comissão de Monitoramento e "
               "Avaliação do Projeto Programa Trabalho Protegido na Adolescência em cumprimento ao art. 35 da Lei nº "
               "13.019/2014: - Patrícia Maria Ribeiro, Id. Funcional 515891-1 ? Gestor da Parceria - Gabriela Pereira "
               "de Almeida, Id. Funcional 5152277-2 ? Membro da Comissão")
COMPROVANTE_8 = ("Comprovante de transferência PIX R$ 10.000,00 Valor PATRICIA MARIA RIBEIRO Nome: Dados de quem recebeu "
                 "FUND APOIO PESQ ENS ASS EMCRJ H. UNIRIO | CNPJ: 004.313.403/0001-41")


def test_designacao_lida():
    nomes = [n for n, _ in nomes_designados(PORTARIA_44)]
    assert "patricia maria ribeiro" in nomes and "gabriela pereira de almeida" in nomes


def test_positivo_pago_e_designado_no_mesmo_processo():
    rx = _trie_regex(["patricia maria ribeiro", "gabriela pereira de almeida"])
    hits = pagamentos_do_nome(C.norm(COMPROVANTE_8), rx)
    assert "patricia maria ribeiro" in hits
    desig = [{"nome": "patricia maria ribeiro", "processo": "SEI-310002/000054/2025", "doc": "doc 44", "trecho": "x"}]
    pags = [{"nome": "patricia maria ribeiro", "processo": "SEI-310002/000054/2025", "doc": "doc 8", "titulo": "t",
             "ocorrencias": 12, "trechos": hits["patricia maria ribeiro"]}]
    a = cruzar(desig, pags)
    assert a and a[0]["grau"] == "forte"


def test_negativo_nome_curto_nao_casa():
    rx = _trie_regex(["patricia maria ribeiro"])
    assert pagamentos_do_nome(C.norm("COORDENADORA PATRICIA RIBEIRO R$10.000,00"), rx) == {}


def test_negativo_gestora_como_destinataria():
    rx = _trie_regex(["patricia maria ribeiro"])
    t = C.norm("À Gestora da Parceria Patrícia Maria Ribeiro: encaminhamos a prestação de contas de R$ 2.832.090,24")
    assert pagamentos_do_nome(t, rx) == {}


def test_negativo_sem_valor_perto():
    rx = _trie_regex(["patricia maria ribeiro"])
    assert pagamentos_do_nome(C.norm("Lista de presença: Patrícia Maria Ribeiro, assinatura"), rx) == {}


def test_negativo_portaria_sem_gestor_ou_comissao():
    assert nomes_designados("Nomear Fulano Beltrano Silva, Id. Funcional 1234 para o cargo de Assessor") == []


def test_negativo_servidor_signatario_com_cargo_apos_o_nome():
    # FUNRIO doc 11 (FP de 19/11): o vice-presidente da FIA assina o ofício juntado à NF; não é pagamento a ele.
    rx = _trie_regex(["arnaldo francisco de alcantara silva junior"])
    t = C.norm("Valor R$ 353.201,77. Arnaldo Francisco de Alcantara Silva Junior Vice-Presidente - FIA/RJ "
               "ID Funcional nº 5089831-0")
    assert pagamentos_do_nome(t, rx) == {}
