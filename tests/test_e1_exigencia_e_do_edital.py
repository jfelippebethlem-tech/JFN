# -*- coding: utf-8 -*-
"""O edital EXIGE; o contrato social do licitante DECLARA. O E1 confundia os dois.

Medido em 2026-08-04 nos 6 disparos do E1 no acervo: a evidência vinha de documentos entregues
PELA EMPRESA — contrato social e ata de assembleia —, ingeridos junto com o processo:

    "O CAPITAL SOCIAL é de R$ 16.000.000,00 (dezesseis milhões de reais)" → "exige 1066,7% do estimado"
    "Aumentar o capital social de R$ 6.000.000,00 para R$ ..."            → "exige 59,8% do estimado"
    "CLÁUSULA NONA — aprovação prévia de sócios representando no mínimo 75% do capital social"

O último veio do "Documento HABILITAÇÃO - CONSTRUTORA BRASFORM", contrato social registrado na
Junta Comercial: é a governança interna da empresa, não uma barreira imposta pelo órgão. E
"1066,7% do estimado" descreve uma empresa grande concorrendo, não uma exigência ilegal.

Duas guardas, nos dois níveis:
  · o documento do LICITANTE (`tipo == habilitacao`) não é fonte de edital, mesmo que seu conteúdo
    cite o edital em algum ponto — título que identifica positivamente vence heurística de texto;
  · a cláusula precisa ter LINGUAGEM DE OBRIGAÇÃO ("deverá comprovar", "mínimo de", "não inferior
    a"); "o capital social é de" é fato, não exigência.

Efeito: E1 6 → 0 no acervo, e o detector segue disparando em exigência de edital de verdade — é o
que o último teste garante.
"""
from compliance_agent.detectores import REGISTRO
from compliance_agent.detectores.coletor_edital import _fontes_de_edital


def _leitura(doc, conteudo):
    return {"conteudo_documentos": [{"doc": doc, "conteudo": conteudo}]}


def test_documento_de_habilitacao_do_licitante_nao_e_fonte_de_edital():
    """Mesmo citando o edital no corpo — o arquivo real tem 22 mil caracteres e o cita."""
    conteudo = ("CONTRATO SOCIAL. CLÁUSULA NONA — Para a prática dos seguintes atos, faz-se "
                "necessária aprovação prévia de sócios representando no mínimo 75% do capital "
                "social. Junta Comercial do Estado do Rio de Janeiro. Consta ainda o edital de "
                "licitação e o termo de referência anexos.")
    fontes = _fontes_de_edital(_leitura("Documento HABILITAÇÃO - CONSTRUTORA BRASFORM (64069756)",
                                        conteudo))
    assert fontes == []


def test_edital_de_verdade_continua_sendo_fonte():
    fontes = _fontes_de_edital(_leitura("Edital de Pregão Eletrônico 12/2024 (123456)",
                                        "1. DO OBJETO. 2. DA HABILITAÇÃO."))
    assert len(fontes) == 1


def test_exigencia_de_capital_do_EDITAL_dispara():
    """A guarda não pode esvaziar o detector: exigência real segue sendo achado."""
    e1 = REGISTRO["E1"]
    r = e1.avaliar({"processo": "X", "valor_estimado": 1_000_000.0,
                    "exigencias_habilitacao": [
                        {"tipo": "capital_social", "valor": 500_000.0,
                         "texto": "a licitante deverá comprovar capital social mínimo de R$ 500.000,00",
                         "prov": "edital"}]})
    assert r.status == "confirmado" and r.score >= 0.85


def test_declaracao_de_capital_SEM_obrigacao_nao_dispara():
    e1 = REGISTRO["E1"]
    r = e1.avaliar({"processo": "X", "valor_estimado": 1_000_000.0,
                    "exigencias_habilitacao": [
                        {"tipo": "capital_social", "valor": 16_000_000.0,
                         "texto": "O CAPITAL SOCIAL é de R$ 16.000.000,00 (dezesseis milhões de reais)",
                         "prov": "contrato social do licitante"}]})
    assert not any("capital" in str(e.get("trecho", "")).lower() and "exige" in str(e.get("trecho", ""))
                   for e in (r.evidencia or []))
