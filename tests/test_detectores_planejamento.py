# -*- coding: utf-8 -*-
"""Teste TARGETED dos detectores da FASE DE PLANEJAMENTO: P1 (especificação dirigida/marca disfarçada),
P2 (cotações combinadas/orçamentos de fachada), P5 (emergência fabricada) — spec V2 do dono.

Estratégia (leve, VM 2 vCPU/sem swap): fixtures de CONTEXTO (dicts), LLM ausente OU rubrica pré-classificada
injetada (sem rede). Para cada detector: (a) caso que CONFIRMA, (b) caso exculpatório/descartado, (c) ctx sem
campo essencial → nao_avaliavel. As partes OBJETIVAS são determinísticas (limiar no código).
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detectores_planejamento.py -q
"""
from __future__ import annotations

from compliance_agent.detectores import (
    ANCORAS,
    REGISTRO,
    P1EspecificacaoDirigida,
    P2CotacoesCombinadas,
    P5EmergenciaFabricada,
    ResultadoDetector,
    rodar_planejamento,
    score_processo,
)
from compliance_agent.detectores.base import STATUS_VALIDOS


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


# ═══════════════════════════════ P1 — especificação dirigida ═══════════════════════════════
def test_p1_confirma_requisito_nominativo():
    """Requisito nominativo (marca/modelo) sem 'ou equivalente' → crítico (violação do art. 41)."""
    ctx = {
        "processo": "plan-1",
        "requisitos": [
            {"requisito": "Switch gerenciável marca Cisco modelo Catalyst 9300", "nominativo": True},
        ],
    }
    r = P1EspecificacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["critico"]
    assert r.valores["n_requisitos_nominativos"] == 1
    assert r.evidencia


def test_p1_confirma_intersecao_e_sob_medida():
    """Interseção ≤2 produtos + requisito ausente nos análogos → forte/medio combinados."""
    ctx = {
        "processo": "plan-2",
        "requisitos": [{"requisito": "certificação proprietária XYZ", "valor": 173, "unidade": "mm"},
                       {"requisito": "potência 2847 lumens", "valor": 2847, "unidade": "lm"}],
        "datasheets_finalistas": ["produto-A", "produto-B"],   # interseção = 2
        "editais_analogos": [
            {"requisitos": [{"requisito": "iluminância adequada"}]},
            {"requisitos": [{"requisito": "iluminância adequada"}]},
        ],
    }
    r = P1EspecificacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["n_produtos_intersecao"] == 2
    assert r.valores["n_valores_nao_redondos"] >= 2


def test_p1_exculpatorio_padronizacao_rebaixa():
    """Marca citada MAS com processo de padronização formal (art. 43) → rebaixado para no máx 'medio'."""
    ctx = {
        "processo": "plan-3",
        "requisitos": [{"requisito": "impressora marca HP", "nominativo": True}],
        "processo_padronizacao": {"art": 43, "numero": "PAD-2023/01"},
    }
    r = P1EspecificacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score <= ANCORAS["medio"]
    assert r.valores["tem_padronizacao"] is True


def test_p1_exculpatorio_rubrica_essencial():
    """Rubrica de pertinência 'essencial_justificado' (injetada, sem rede) → exculpatória, score ≤ fraco."""
    ctx = {
        "processo": "plan-4",
        "requisitos": [{"requisito": "marca Y exclusiva", "nominativo": True,
                        "_rubrica_pertinencia": {"nivel": "essencial_justificado", "trecho": "uso clínico crítico"}}],
    }
    r = P1EspecificacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.score <= ANCORAS["fraco"]
    assert r.valores["pertinencia"] == "essencial_justificado"


def test_p1_descartado_especificacao_neutra():
    """Requisito genérico com 'ou equivalente', valores redondos → descartado."""
    ctx = {
        "processo": "plan-5",
        "requisitos": [{"requisito": "notebook 8GB RAM ou equivalente", "valor": 8, "unidade": "GB"}],
    }
    r = P1EspecificacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_p1_nao_avaliavel_sem_tr_nem_requisitos():
    r = P1EspecificacaoDirigida().avaliar({"processo": "plan-6"})
    _valido(r)
    assert r.status == "nao_avaliavel"


def test_p1_negacao_de_marca_no_tr_nao_e_nominativo():
    """'É vedada a indicação de marca' é a cláusula que PROÍBE — não pode acionar evidência nominativa."""
    ctx = {
        "processo": "plan-6b",
        "tr_texto": ("As especificações são neutras. É vedada a indicação de marca, modelo ou fabricante, "
                     "nos termos do art. 41 da Lei 14.133/2021."),
    }
    r = P1EspecificacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0
    assert r.valores["n_requisitos_nominativos"] == 0


def test_p1_marca_afirmativa_no_tr_segue_critico():
    """Controle positivo: marca AFIRMATIVA no corpo do TR (sem 'ou equivalente') continua crítico."""
    ctx = {
        "processo": "plan-6c",
        "tr_texto": "O equipamento deverá ser da marca Cisco, modelo Catalyst 9300, novo e lacrado.",
    }
    r = P1EspecificacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["critico"]
    assert r.valores["n_requisitos_nominativos"] == 1


# ═══════════════════════════════ P2 — cotações combinadas ═══════════════════════════════
def test_p2_confirma_vencedor_entre_cotantes():
    """O vencedor está entre os cotantes (cotou o próprio teto) → forte."""
    ctx = {
        "processo": "plan-7",
        "cotacoes": [{"cnpj": "11111111000100", "total": 100.0},
                     {"cnpj": "22222222000100", "total": 140.0},
                     {"cnpj": "33333333000100", "total": 160.0}],
        "vencedor_cnpj": "11111111000100",
    }
    r = P2CotacoesCombinadas().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["vencedor_e_cotante"] is True


def test_p2_confirma_vinculo_socio_e_metadados():
    """Sócio comum entre cotantes + Author idêntico nos PDFs → forte."""
    ctx = {
        "processo": "plan-8",
        "cotacoes": [
            {"cnpj": "11111111000100", "total": 100.0, "metadados_pdf": {"Author": "joao", "CreateDate": "2024-01-01"}},
            {"cnpj": "22222222000100", "total": 130.0, "metadados_pdf": {"Author": "joao", "CreateDate": "2024-01-01"}},
        ],
        "qsa_por_cnpj": {
            "11111111000100": [{"nome": "Maria Sócia"}],
            "22222222000100": [{"nome": "Maria Sócia"}],
        },
    }
    r = P2CotacoesCombinadas().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["vinculos"]["socio_endereco_tel_email"] is True
    assert r.valores["metadados"]["author_repetido"] is True


def test_p2_exculpatorio_contador_isolado():
    """Apenas contador comum, sem outro vínculo → fraco (exculpatória de mercado regional)."""
    ctx = {
        "processo": "plan-9",
        "cotacoes": [{"cnpj": "11111111000100", "total": 100.0, "contador": "Contábil Bairro"},
                     {"cnpj": "22222222000100", "total": 150.0, "contador": "Contábil Bairro"}],
    }
    r = P2CotacoesCombinadas().avaliar(ctx)
    _valido(r)
    assert r.score <= ANCORAS["fraco"]
    assert r.valores["vinculos"]["contador_comum"] is True


def test_p2_exculpatorio_cv_baixo_item_regulado():
    """CV baixo mas item de preço REGULADO (commodity) → não pontua o CV → descartado."""
    ctx = {
        "processo": "plan-10",
        "cotacoes": [{"cnpj": "1", "total": 100.0}, {"cnpj": "2", "total": 101.0}, {"cnpj": "3", "total": 102.0}],
        "item_preco_regulado": True,
    }
    r = P2CotacoesCombinadas().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_p2_descartado_cotacoes_independentes():
    """Sem vínculo, metadados distintos, vencedor fora, valores dispersos → descartado."""
    ctx = {
        "processo": "plan-11",
        "cotacoes": [{"cnpj": "1", "total": 100.0}, {"cnpj": "2", "total": 150.0}],
        "vencedor_cnpj": "9",
    }
    r = P2CotacoesCombinadas().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_p2_nao_avaliavel_menos_de_2_cotacoes():
    r = P2CotacoesCombinadas().avaliar({"processo": "plan-12", "cotacoes": [{"cnpj": "1"}]})
    _valido(r)
    assert r.status == "nao_avaliavel"


def test_p2_cv_com_2_totais_nao_pontua():
    """CV com n=2 não diz nada (2 cotações sempre 'alinham' fácil) → ressalva, não pontua → descartado."""
    ctx = {
        "processo": "plan-13",
        "cotacoes": [{"cnpj": "1", "total": 100.0}, {"cnpj": "2", "total": 100.5}],
    }
    r = P2CotacoesCombinadas().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0
    assert "ressalva_cv_n" in r.valores


def test_p2_cv_com_3_totais_pontua_com_ressalva():
    """n=3 é o mínimo da regra de CV: pontua (fraco) mas registra ressalva de n em valores."""
    ctx = {
        "processo": "plan-14",
        "cotacoes": [{"cnpj": "1", "total": 100.0}, {"cnpj": "2", "total": 100.5}, {"cnpj": "3", "total": 101.0}],
    }
    r = P2CotacoesCombinadas().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["fraco"]
    assert "ressalva_cv_n" in r.valores


# ═══════════════════════════════ P5 — emergência fabricada ═══════════════════════════════
def test_p5_confirma_inercia_apos_vencimento():
    """Dispensa aberta APÓS o vencimento conhecido do contrato anterior → forte (inércia/desídia)."""
    ctx = {
        "processo": "plan-13",
        "data_abertura_processo": "2024-03-10",
        "contrato_anterior": {"vencimento": "2024-03-01"},
    }
    r = P5EmergenciaFabricada().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["delta_vencimento_abertura_dias"] == 9


def test_p5_confirma_proposta_anterior_pre_escolha():
    """Proposta do contratado anterior à abertura do processo → forte (fornecedor pré-escolhido)."""
    ctx = {
        "processo": "plan-14",
        "data_abertura_processo": "2024-03-10",
        "data_proposta": "2024-03-01",   # 9 dias ANTES da abertura
    }
    r = P5EmergenciaFabricada().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["delta_proposta_abertura_dias"] == 9


def test_p5_exculpatorio_desastre_confirmado():
    """Desastre real confirmado (Defesa Civil/imprensa) → legitima a dispensa, score rebaixado ≤ fraco."""
    ctx = {
        "processo": "plan-15",
        "data_abertura_processo": "2024-03-10",
        "contrato_anterior": {"vencimento": "2024-03-01"},
        "desastre_confirmado": True,
    }
    r = P5EmergenciaFabricada().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score <= ANCORAS["fraco"]
    assert r.valores["desastre_confirmado"] is True


def test_p5_exculpatorio_certame_fracassado_rebaixa():
    """Certame anterior fracassado documentado → exculpatória parcial da inércia (rebaixa ≤ medio)."""
    ctx = {
        "processo": "plan-16",
        "data_abertura_processo": "2024-03-10",
        "contrato_anterior": {"vencimento": "2024-03-01"},
        "certame_anterior_fracassado": True,
    }
    r = P5EmergenciaFabricada().avaliar(ctx)
    _valido(r)
    assert r.score <= ANCORAS["medio"]


def test_p5_descartado_dispensa_tempestiva():
    """Abertura bem antes do vencimento, sem pré-escolha, sem recorrência → descartado."""
    ctx = {
        "processo": "plan-17",
        "data_abertura_processo": "2024-01-01",
        "contrato_anterior": {"vencimento": "2024-06-01"},   # abriu 5 meses antes
    }
    r = P5EmergenciaFabricada().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_p5_nao_avaliavel_sem_data_abertura():
    r = P5EmergenciaFabricada().avaliar({"processo": "plan-18"})
    _valido(r)
    assert r.status == "nao_avaliavel"


# ═══════════════════════════════ orquestrador + registro ═══════════════════════════════
def test_registro_tem_os_novos_planejamento():
    assert {"P1", "P2", "P5"} <= set(REGISTRO)
    # não quebrou os existentes (J1/P3/P4/C/E1/E2/E3)
    assert {"P4", "J1", "P3", "C", "E1", "E2", "E3"} <= set(REGISTRO)


def test_rodar_planejamento_combina_p1_p2_p5():
    ctx = {
        # P1
        "requisitos": [{"requisito": "marca Cisco modelo X", "nominativo": True}],
        # P2
        "cotacoes": [{"cnpj": "11111111000100", "total": 100.0},
                     {"cnpj": "22222222000100", "total": 140.0}],
        "vencedor_cnpj": "11111111000100",
        # P5
        "data_abertura_processo": "2024-03-10",
        "contrato_anterior": {"vencimento": "2024-03-01"},
    }
    res = rodar_planejamento("processo-x", contexto=ctx)
    ids = {r.detector for r in res}
    assert {"P1", "P2", "P5"} <= ids
    for r in res:
        _valido(r)
    from compliance_agent.detectores import PESOS_DETECTOR
    s = score_processo(res, PESOS_DETECTOR)
    assert 0.0 <= s <= 1.0


def test_rodar_planejamento_exculpatoria_degrada_sem_llm():
    """exculpatoria=True com gerar que SIMULA LLM offline → não refuta, não quebra (honesto)."""
    def _gerar_offline(prompt, sistema):
        raise RuntimeError("LLM offline")

    ctx = {"data_abertura_processo": "2024-03-10", "contrato_anterior": {"vencimento": "2024-03-01"}}
    res = rodar_planejamento("processo-y", contexto=ctx, exculpatoria=True, gerar=_gerar_offline)
    for r in res:
        _valido(r)
        if r.status == "confirmado":
            assert r.refutada is False
