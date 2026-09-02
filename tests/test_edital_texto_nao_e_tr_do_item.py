# -*- coding: utf-8 -*-
"""O texto do EDITAL não é o TR do ITEM — e confundi-los fabricou 175 achados.

O `_trecho_completo` do E7 realoca a cláusula no edital e alarga a janela até a fronteira de
frase; sem o texto no contexto, a evidência chegava ao fiscal cortada no meio — *"9.3.2 Prova de
possuir no seu quadro permanente, na data da Concorrência, profissional ou"* — perdendo justamente
o que decide o caso, que vem depois (*"a comprovação … deverá ser feita através de cópia de sua
ficha de registro de EMPREGADO"*, isto é, vínculo empregatício exigido na data da licitação).

Ao ligar esse texto eu usei a chave `tr_texto`, e a reavaliação devolveu **175 achados P1 do nada,
44 deles críticos**. Todos falsos, e a prova estava na evidência que eles próprios imprimiam:

  · "QUANTIDADE RECEBIDA: 50.150 UNID. MARCA: N/C"     → termo de recebimento; N/C é "não consta"
  · "LOTE FABRICAÇÃO | VALIDADE | Marca | RECEBIDA"    → cabeçalho de tabela de entrega
  · "solicitações de troca de marca/prorrogação"       → e-mail de execução do contrato

`_fontes_de_edital` aceita documento pelo CONTEÚDO — certo para localizar uma cláusula num
processo de 498 peças, errado como "descrição do item", que é o que o P1 entende por `tr_texto`.
Chave própria (`edital_texto`) resolve: o E7 ganha a cláusula inteira e o P1 volta a dizer
`nao_avaliavel`, que é honesto.
"""
from __future__ import annotations

from compliance_agent.detectores.coletor_edital import montar_ctx_de_sei

EDITAL = (
    "EDITAL DE CONCORRÊNCIA Nº 01/2022. 9.3.1 Certidão de Registro do Licitante no CREA. "
    "9.3.2 Prova de possuir no seu quadro permanente, na data da Concorrência, profissional ou "
    "profissionais de nível superior detentores de atestado de responsabilidade técnica. "
    "9.3.2.1 A comprovação de que o detentor do referido Atestado é vinculado à licitante deverá "
    "ser feita através de cópia de sua ficha de registro de empregado.")

RECEBIMENTO = (
    "TERMO DE RECEBIMENTO referente ao edital 01/2022. LOTE FABRICAÇÃO | VALIDADE | Marca | "
    "QUANTIDADE RECEBIDA: 50.150 UNID. MARCA: N/C")


def _ctx(*docs):
    return montar_ctx_de_sei({"numero": "000000/000000/2022", "texto": "",
                              "documentos": [d for d, _ in docs],
                              "conteudo_documentos": [{"doc": d, "conteudo": c} for d, c in docs]})


def test_o_texto_do_edital_viaja_em_chave_propria():
    ctx = _ctx(("Edital de Concorrência 01/2022", EDITAL))
    assert "edital_texto" in ctx and "9.3.2" in ctx["edital_texto"]


def test_nao_preenche_tr_texto_que_e_do_ITEM():
    """`tr_texto` é a descrição do item, e o P1 o lê como tal. Preenchê-lo com o processo inteiro
    faz o P1 caçar a palavra 'marca' em nota de recebimento e e-mail de troca de marca."""
    ctx = _ctx(("Edital de Concorrência 01/2022", EDITAL),
               ("Termo de Recebimento 55", RECEBIMENTO))
    assert "tr_texto" not in ctx, "P1 passaria a avaliar o processo inteiro como se fosse o TR"


def test_sem_documento_de_edital_nao_ha_texto():
    ctx = _ctx(("Despacho de Encaminhamento 12", "Encaminho os autos para providências."))
    assert "edital_texto" not in ctx
