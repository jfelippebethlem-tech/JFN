# -*- coding: utf-8 -*-
"""doerj_anomalia: termo de risco só conta no MESMO ato do favorecido, e ligado a ele.

Medido em 20/11/2026: 29 de 49 vereditos da triagem do Opus para `doerj_anomalia` foram
`provavel_falso_positivo`. A regra casava o favorecido num ato (extrato de contrato) e 'multa' em
OUTRO ato do mesmo bloco do diário (exoneração, designação de comissão de fiscalização de outra
pessoa) — tupla híbrida. Os textos abaixo reproduzem a forma real dos blocos de `publicacoes_doerj`
(vários atos colados, cada um fechado por "Id: NNNNNNN").
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from compliance_agent.database.models import Alerta, Base, OrdemBancaria, PublicacaoDOERJ
from compliance_agent.rules.doerj_casamento import eh_orgao_publico, ocorrencias
from compliance_agent.rules.engine import MotorCompliance

NOME = "ACME SERVICOS DE LIMPEZA LTDA"
CNPJ = "12345678000190"
CNPJ_FMT = "12.345.678/0001-90"

# Bloco com dois atos: o extrato de contrato da ACME (sem termo de risco) e, no ato SEGUINTE,
# uma nomeação de servidor que cita 'multa' sem relação nenhuma com a ACME.
BLOCO_NOMEACAO = (
    "SECRETARIA DE ESTADO DE SAÚDE EXTRATO DE CONTRATO INSTRUMENTO: Contrato nº 10/2026. "
    f"PA R T E S : Estado do Rio de Janeiro e ACME SERVICOS DE LIMPEZA LTDA, CNPJ {CNPJ_FMT}. "
    "OBJETO: limpeza predial. VALOR: R$ 100.000,00. Id: 2740001 "
    "SECRETARIA DE ESTADO DE FAZENDA ATO DO SECRETÁRIO NOMEIA JOÃO DA SILVA, Id. Funcional "
    "nº 5000000-1, para exercer o cargo de Assessor, ficando ciente de que o descumprimento do "
    "Código de Ética sujeita o servidor a multa e demais sanções. Id: 2740002"
)

# Controle POSITIVO: ato sancionador aplicado À própria ACME.
BLOCO_SANCAO = (
    "SECRETARIA DE ESTADO DE POLÍCIA PENAL DESPACHO DO SUBSECRETÁRIO PROCESSO Nº "
    "SEI-210001/000001/2026 - DECIDE pela aplicação à empresa ACME SERVIÇOS DE LIMPE- ZA LTDA, "
    f"CNPJ nº {CNPJ_FMT}, das penalidades de Advertência e Multa de 0,1% ao contrato nº 10/2026 "
    "no valor de R$ 18.185,99. Id: 2740003"
)

# Mesma sanção grafada sem acento/hífen — a forma que a busca SQL (ILIKE no nome) já encontra.
BLOCO_SANCAO_SQL = (
    "SECRETARIA DE ESTADO DE POLÍCIA PENAL DESPACHO DO SUBSECRETÁRIO DECIDE pela aplicação à "
    f"empresa ACME SERVICOS DE LIMPEZA LTDA, CNPJ nº {CNPJ_FMT}, das penalidades de Advertência "
    "e Multa de 0,1% ao contrato nº 10/2026. Id: 2740010"
)

# Rescisão do contrato da ACME (o termo vem ANTES do nome, no título do extrato).
BLOCO_RESCISAO = (
    "SECRETARIA DE ESTADO DE EDUCAÇÃO EXTRATO DE TERMO DE RESCISÃO UNILATERAL INSTRUMENTO: "
    f"Contrato nº 11/2026. PARTES: Estado do Rio de Janeiro e ACME SERVICOS DE LIMPEZA LTDA, CNPJ {CNPJ_FMT}. "
    "Id: 2740004"
)

# Lista do INEA: a multa listada logo ANTES do nome é do autuado anterior (outro CNPJ no meio).
BLOCO_LISTA_VIZINHO = (
    "INSTITUTO ESTADUAL DO AMBIENTE AVISOS AUTO DE INFRAÇÃO N°: 1/2026 NOME: OUTRA EMPRESA LTDA "
    "CNPJ/CPF N°: 99.888.777/0001-66 PENALIDADE: Multa simples Valor: R$ 1.000,00 "
    f"AUTO DE INFRAÇÃO N°: 2/2026 NOME: ACME SERVIÇOS DE LIMPEZA LTDA CNPJ/CPF N°: {CNPJ_FMT} "
    "PENALIDADE: Advertência. Id: 2740005"
)

# Designação de comissão de fiscalização que lista o contrato da ACME e cita 'multa' genérica.
BLOCO_COMISSAO = (
    "PORTARIA SEENEMAR Nº 118 DE 07 DE ABRIL DE 2026 ALTERA COMISSÃO DE FISCALIZAÇÃO do "
    "Contrato nº 10/2026, firmado com ACME SERVICOS DE LIMPEZA LTDA, cabendo aos fiscais "
    "propor a aplicação de multa quando cabível. Id: 2740006"
)


# ── unidade: casamento dentro do ato ─────────────────────────────────────────────────────────

def test_nomeacao_com_multa_em_outro_ato_nao_casa():
    assert ocorrencias(BLOCO_NOMEACAO, NOME, CNPJ) == []


def test_sancao_aplicada_a_empresa_casa_mesmo_com_hifen_de_quebra():
    oc = ocorrencias(BLOCO_SANCAO, NOME, CNPJ)
    assert [o["termo"] for o in oc] == ["multa"]
    assert "ACME" in oc[0]["trecho"] and "Multa" in oc[0]["trecho"]


def test_rescisao_do_contrato_da_empresa_casa():
    assert [o["termo"] for o in ocorrencias(BLOCO_RESCISAO, NOME, "")] == ["rescisão"]


def test_multa_do_vizinho_na_lista_nao_e_do_favorecido():
    assert ocorrencias(BLOCO_LISTA_VIZINHO, NOME, CNPJ) == []


def test_designacao_de_comissao_e_ato_de_pessoal():
    assert ocorrencias(BLOCO_COMISSAO, NOME, CNPJ) == []


def test_plural_conta():
    txt = ("PORTARIA Nº 95 INSTAURA PROCESSO ADMINISTRATIVO SANCIONADOR PARA APURAR POSSÍVEIS "
           "IRREGULARIDADES PRATICADAS PELA EMPRESA ACME SERVIÇOS DE LIMPEZA LTDA. Id: 2740007")
    assert [o["termo"] for o in ocorrencias(txt, NOME, CNPJ)] == ["irregularidade"]


def test_identidade_funcional_nao_corta_o_ato():
    """'ID: 4368780-6' é matrícula de servidor, não fim de ato: cortar ali separava a empresa da multa."""
    txt = ("instaura o presente Processo Administrativo Sancionatório para apurar inexecução "
           f"perpetrada pela empresa ACME SERVICOS DE LIMPEZA LTDA, CNPJ {CNPJ_FMT}. Art. 2º - "
           "Designa o servidor FULANO, ID: 4368780-6, lotado na DIT. " + "x " * 300 +
           "Art. 4º - Fica a Contratada sujeita à sanção de aplicação de multa. Id: 2740008")
    assert [o["termo"] for o in ocorrencias(txt, NOME, CNPJ)] == ["multa"]


@pytest.mark.parametrize("nome,esperado", [
    ("Rio De Janeiro Sec.de Estado Da Defesa Civil", True),
    ("SECRETARIA DE ESTADO DE FAZENDA - SEFAZ", True),
    ("Uniao Norte Fluminense Eng. E Comercio Ltda", False),   # 'uniao' não é a União
    ("Light Servicos De Eletricidade S/a", False),
    (NOME, False),
])
def test_orgao_publico(nome, esperado):
    assert eh_orgao_publico(nome) is esperado


# ── integração: a regra do motor ─────────────────────────────────────────────────────────────

@pytest.fixture()
def sessao():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


# A regra viva busca pela coluna minerada `cnpjs_extraidos` e só na janela recente (`_desde`): datas relativas a hoje.
_BASE = date.today() - timedelta(days=30)


def _ob(s, nome=NOME, cnpj=CNPJ, numero="2026OB00001"):
    s.add(OrdemBancaria(numero_ob=numero, data_emissao=_BASE, ug_codigo="290100",
                        favorecido_cpf=cnpj, favorecido_nome=nome, valor=50_000.0, status="paga"))


def _pub(s, texto, dia=1, tipo="nomeação"):
    cnpjs = sorted(set(re.findall(r"\d{14}", re.sub(r"[./-]", "", texto))))
    s.add(PublicacaoDOERJ(data_publicacao=_BASE + timedelta(days=dia), tipo_ato=tipo,
                          titulo=f"Parte I (Poder Executivo) | bloco {dia}", texto=texto,
                          cnpjs_extraidos=json.dumps(cnpjs)))


def _alertas(s):
    motor = MotorCompliance(s)
    motor._regra_ob_favorecido_doerj_cruzado()
    return [a for a in motor._alertas_novos if a.tipo == "doerj_anomalia"]


def test_reproduz_fp_nomeacao_com_multa_sem_relacao(sessao):
    _ob(sessao)
    _pub(sessao, BLOCO_NOMEACAO)
    sessao.commit()
    assert _alertas(sessao) == []


def test_controle_positivo_sancao_a_empresa_alerta_e_mostra_todas_as_ocorrencias(sessao):
    _ob(sessao)
    _pub(sessao, BLOCO_NOMEACAO, dia=1)
    _pub(sessao, BLOCO_SANCAO_SQL, dia=2, tipo="outros")
    _pub(sessao, BLOCO_RESCISAO, dia=3, tipo="contrato")
    sessao.commit()
    al = _alertas(sessao)
    assert len(al) == 1
    ev = json.loads(al[0].evidencias)
    termos = sorted(s["termo_suspeito"] for s in ev["doerj_suspeitos"])
    assert termos == ["multa", "rescisão"]
    assert all(s["trecho"] for s in ev["doerj_suspeitos"])
    # o contado é o exibido: cada publicação consultada aparece na evidência
    assert ev["doerj_total_hits"] == len(ev["doerj_publicacoes_consultadas"]) == 3
    assert ev["doerj_total_ocorrencias"] == len(ev["doerj_suspeitos"]) == 2


def test_controle_negativo_favorecido_orgao_publico_nao_alerta(sessao):
    _ob(sessao, nome="Rio De Janeiro Sec.de Estado Da Defesa Civil", cnpj="28176998000441")
    _pub(sessao, "EXTRATO DE TERMO DE RESCISÃO. PARTES: Rio De Janeiro Sec.de Estado Da Defesa "
                 "Civil e Município de Pinheiral. Id: 2740009")
    sessao.commit()
    assert _alertas(sessao) == []
