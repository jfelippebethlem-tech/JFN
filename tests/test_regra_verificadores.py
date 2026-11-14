# -*- coding: utf-8 -*-
"""Verificadores puros das regras de qualidade — cada teste é a PROVA (COR-15): injeta o defeito em texto
sintético e exige a acusação; depois dá o texto conforme e exige silêncio. Nada aqui é dado real: CPF e valores
são inventados (o CPF abaixo tem dígito verificador válido por construção e não pertence a ninguém conhecido)."""
from __future__ import annotations

from compliance_agent.llm import verificacao
from compliance_agent.qualidade import verificadores as v

CPF_SINT = "111.444.777-35"


def test_moeda_fora_do_padrao_e_acusada():
    for ruim in ("R$ 1234.56", "R$ 1,234.56", "R$ 1234567,89", "R$ 1.234.567", "R$1234"):
        assert v.moeda_fora_do_padrao(f"pagou {ruim} ao credor"), ruim
    for bom in ("R$ 1.234.567,89", "R$ 0,50", "R$ 16,4 mi", "R$ 2,47 bi", "R$ 13 mil", "R$ 592,8 mi"):
        assert not v.moeda_fora_do_padrao(f"pagou {bom} ao credor"), bom


def test_cpf_exposto_e_acusado():
    msgs = v.cpf_exposto(f"servidor de CPF {CPF_SINT} acumula")
    assert msgs and CPF_SINT not in msgs[0] and "***.444.777-**" in msgs[0]     # a própria mensagem não vaza
    assert v.cpf_exposto("cpf: 11144477735")                                    # sem pontuação, com a palavra
    assert not v.cpf_exposto("CPF ***.444.777-**")                              # mascarado
    assert not v.cpf_exposto("protocolo 111.444.777-36")                        # dígito verificador inválido
    assert not v.cpf_exposto("OB 20261144477735 emitida")                       # número longo sem a palavra


def test_linguagem_acusatoria_e_acusada():
    assert v.linguagem_acusatoria("Melhor detector: concentra fraude 2,12×")
    assert v.linguagem_acusatoria("Empresa fantasma recebeu do órgão")
    assert not v.linguagem_acusatoria("Indício de perfil fantasma, a verificar no cadastro")
    assert not v.linguagem_acusatoria("Sanção não é prova de fraude; é sinal para priorizar a leitura")
    assert not v.linguagem_acusatoria("Laranjal Paulista assinou o convênio")      # palavra dentro de outra não conta


def test_estado_fora_do_vocabulario_e_acusado():
    assert v.estado_invalido(None) and v.estado_invalido("") and v.estado_invalido("ok")
    assert not v.estado_invalido("VERIFICADO") and not v.estado_invalido("indisponível")


def test_natureza_ausente_e_acusada():
    assert v.natureza_ausente(None) and v.natureza_ausente("gasto")
    assert not v.natureza_ausente("pago") and not v.natureza_ausente("teto_de_ata")


def test_proveniencia_incompleta_e_acusada():
    assert v.proveniencia_incompleta({"total": 10}) == ["PAD-01 sem bloco `proveniencia`"]
    meio = {"proveniencia": {"fonte": "SIAFE", "data_ref": "2026-11-12", "cobertura": "", "estado": "talvez",
                             "natureza": "pago", "esfera": "marte"}}
    regras_acusadas = {m.split()[0] for m in v.proveniencia_incompleta(meio)}
    assert regras_acusadas == {"PAD-01", "PAD-02", "PAD-06"}
    completa = {"proveniencia": {"fonte": "SIAFE · ob_orcamentaria_siafe", "data_ref": "2026-11-12",
                                 "cobertura": "OB de 2021 a 2026, 100% das UGs do Executivo", "estado": "PENDENTE",
                                 "natureza": "pago", "esfera": "estadual"}}
    assert not v.proveniencia_incompleta(completa)


def test_empenho_apresentado_como_pago_e_acusado():
    assert v.empenho_como_pago("Total pago ao fornecedor: R$ 10.000,00 empenhados em 2026")
    assert not v.empenho_como_pago("Empenhado R$ 10.000,00; pago (OB) R$ 4.000,00")
    assert not v.empenho_como_pago("Empenho não é pagamento: foram pagos R$ 4.000,00")


def test_culpa_ao_acesso_sem_controle_e_acusada():
    assert v.culpa_ao_acesso("Não foi possível ler: acesso negado pelo portal")
    assert v.culpa_ao_acesso("consulta bloqueada pelo WAF")
    assert not v.culpa_ao_acesso("bloqueado pelo WAF — controle positivo: o processo de referência também não abriu")
    assert not v.culpa_ao_acesso("o seletor do menu mudou; defeito nosso")


def test_ausencia_sem_controle_e_acusada():
    assert v.ausencia_sem_controle("Não há contrato entre o órgão e a empresa")
    assert v.ausencia_sem_controle("A empresa tem zero OB no período")
    assert not v.ausencia_sem_controle("Sem OB na base até 12/11/2026 (cobertura parcial) — INDISPONÍVEL")
    assert not v.ausencia_sem_controle("Não há contrato; controle positivo: a mesma busca acha o contrato de referência")


def test_contagem_no_teto_e_acusada():
    assert v.contagem_no_teto(100) and v.contagem_no_teto(1000) and not v.contagem_no_teto(137)
    assert v.listas_no_teto({"achados": [0] * 100})                               # teto sem total = parcial calado
    assert not v.listas_no_teto({"achados": [0] * 100, "n": 554})                  # "100 de 554": cortada e declarada
    assert not v.listas_no_teto({"achados": [0] * 37})
    assert v.listas_no_teto({"bloco": {"itens": [0] * 50}})                        # aninhada também


def test_concentracao_alta_e_acusada():
    assert v.concentracao_alta([95, 1, 1, 1, 1, 1])                                # um registro responde por 95%
    assert not v.concentracao_alta([10] * 20)
    assert v.concentracao([5, 5]) is None                                          # ≤ k itens: nada a medir


def test_variacao_brusca_e_acusada():
    assert v.variacao_brusca(592_785_486.56, 16_390_000.00)                        # a manchete desabou
    assert v.variacao_brusca(771, 59_024)                                          # ou explodiu
    assert v.variacao_brusca(10.0, 0.0) and v.variacao_brusca(0.0, 10.0)           # zerou / saiu do zero
    assert v.variacao_brusca(10.0, None)                                           # sumiu
    assert not v.variacao_brusca(None, 10.0)                                       # primeira leitura
    assert not v.variacao_brusca(100.0, 110.0) and not v.variacao_brusca(7.0, 7.0)


def test_divergencia_entre_superficies_e_acusada():
    assert v.divergencia(375_000_000.00, 568_200_000.00)
    assert v.divergencia(10.0, None)                                               # um lado mudo NÃO é igualdade
    assert not v.divergencia(10.0, 10.004)
    assert v.parte_maior_que_todo(25_873_309.21, 5_976_128.58)                     # a parte não excede o todo
    assert not v.parte_maior_que_todo(5.0, 10.0)


def test_citacao_ausente_da_fonte_nao_verifica():
    """COR-01: a conferência por código é a que já existia (`llm/verificacao`); aqui fica a prova de que recusa."""
    fonte = "O contrato foi assinado em 12 de março de 2026 pelo valor de R$ 1.250.000,00."
    assert verificacao.citacao_existe("assinado em 12 de março de 2026", fonte)
    assert not verificacao.citacao_existe("assinado em 25 de março de 2026", fonte)
    assert verificacao.estado_dupla_leitura("alto", "alto") == "VERIFICADO"
    assert verificacao.estado_dupla_leitura("alto", "baixo") == "PENDENTE"


def test_extrair_caminho_pontilhado_e_com_indice():
    p = {"a": {"b": [{"c": 7}, {"c": 9}]}}
    assert v.extrair(p, "a.b.1.c") == 9 and v.extrair(p, "a.b[0].c") == 7
    assert v.extrair(p, "a.x.c") is None and v.extrair(p, "a.b.5.c") is None
