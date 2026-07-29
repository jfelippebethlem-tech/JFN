# -*- coding: utf-8 -*-
"""Invariantes do REGISTRO inteiro de detectores.

Pega o que teste individual não pega: detector novo que entre no REGISTRO sem rede de proteção,
sem família com peso, ou que quebre/invente indício quando o contexto vem vazio.

Roda uma vez sobre os 31 detectores registrados — é o teste que impede a regressão silenciosa
que o projeto já viveu (10 detectores em produção sem nenhum teste).
"""
from __future__ import annotations

import pathlib

import pytest

from compliance_agent.detectores import REGISTRO
from compliance_agent.detectores.base import PESOS_FAMILIA, STATUS_VALIDOS

_CTX_MINIMO = {"processo": "SEI-TESTE/000000/2026"}


def test_registro_nao_esta_vazio():
    assert len(REGISTRO) >= 30, f"esperados ~31 detectores, encontrados {len(REGISTRO)}"


def test_chave_do_registro_bate_com_o_id_do_detector():
    divergentes = {k: d.id for k, d in REGISTRO.items() if d.id != k}
    assert not divergentes, f"chave ≠ id: {divergentes}"


def test_todo_detector_tem_nome_preenchido():
    sem_nome = [k for k, d in REGISTRO.items() if not d.nome or d.nome == "?"]
    assert not sem_nome, f"detectores sem nome: {sem_nome}"


def test_familia_de_todo_detector_tem_peso_na_convergencia():
    """Família fora de PESOS_FAMILIA cai no default silenciosamente e distorce o score do processo."""
    orfaos = {k: d.familia for k, d in REGISTRO.items() if d.familia not in PESOS_FAMILIA}
    assert not orfaos, f"família sem peso declarado (§7.2): {orfaos}"


@pytest.mark.parametrize("did", sorted(REGISTRO))
def test_contexto_vazio_nunca_quebra_e_nunca_inventa(did):
    """Chamada mínima, sem dado nenhum. Dois invariantes ao mesmo tempo:

    1. nenhum detector pode estourar exceção (o pipeline inteiro cairia junto);
    2. sem dado, o veredito é `nao_avaliavel` com score 0 — nunca 'descartado' (que afirmaria
       ter verificado e aprovado) e nunca score > 0 (que seria indício inventado).
    """
    det = REGISTRO[did]
    res = det.avaliar(dict(_CTX_MINIMO))
    assert res.status in STATUS_VALIDOS, f"{did}: status inválido {res.status!r}"
    assert res.score == 0.0, f"{did}: score {res.score} sem dado algum"
    assert res.status == "nao_avaliavel", (
        f"{did}: sem dado o veredito tem de ser nao_avaliavel, veio {res.status!r} — "
        "'descartado' afirmaria ao fiscal que o item foi verificado e aprovado")


@pytest.mark.parametrize("did", sorted(REGISTRO))
def test_nao_avaliavel_sempre_explica_o_porque(did):
    """`nao_avaliavel` sem motivo é indistinguível de bug. O fiscal precisa saber o que faltou."""
    res = REGISTRO[did].avaliar(dict(_CTX_MINIMO))
    assert res.motivo_refutacao.strip(), f"{did}: nao_avaliavel sem motivo declarado"


@pytest.mark.parametrize("did", sorted(REGISTRO))
def test_schema_de_saida_conforme_spec(did):
    d = REGISTRO[did].avaliar(dict(_CTX_MINIMO)).to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d, f"{did}: schema §1.4 exige {campo}"


def test_todo_detector_do_registro_tem_arquivo_de_teste():
    """Rede de proteção obrigatória: detector novo no REGISTRO exige teste no mesmo commit.

    O mapa é explícito de propósito — casamento por substring de nome daria falso positivo e
    deixaria passar exatamente o que este teste existe para impedir.
    """
    esperado = {
        "P1": "test_p1_especificacao_dirigida.py",
        "P2": "test_p2_cotacoes_combinadas.py",
        "P3": "test_p3_sobrepreco.py",
        "P4": "test_p4_fracionamento.py",
        "P5": "test_p5_emergencia_fabricada.py",
        "P6": "test_p6_direta_indevida.py",
        "E1": "test_e1_barreira.py",
        "E2": "test_e2_prazos.py",
        "E3": "test_e3_lote_pacote.py",
        "E4": "test_e4_visita_tecnica.py",
        "E5": "test_e5_edital_iterado.py",
        "E6": "test_e6_pontuacao_dirigida.py",
        "E7": "test_detector_e7.py",
        "E8": "test_e8_deserto_dirigido.py",
        "J1": "test_j1_cartel.py",
        "J2": "test_j2_propostas_cobertura.py",
        "J3": "test_j3_desconto_anomalo.py",
        "J4": "test_j4_supressao_propostas.py",
        "J5": "test_j5_digitais_compartilhadas.py",
        "J6": "test_j6_subcontratacao_cruzada.py",
        "J7": "test_j7_inabilitacao_seletiva.py",
        "J8": "test_atestado_cruzado.py",
        "C": "test_c_fachada.py",
        "C6": "test_detector_c6.py",
        "C7": "test_c7_sancionada_contratada.py",
        "C8": "test_c8_servidor_socio.py",
        "X1": "test_detector_x1.py",
        "X2": "test_x2_prorrogacao_perpetua.py",
        "X3": "test_detector_x3.py",
        "X4": "test_x4_carona_abusiva.py",
        "X5": "test_x5_jogo_planilha.py",
        "X6": "test_x6_entrega_fantasma.py",
        "X7": "test_x7_reequilibrio.py",
        "X8": "test_x8_aditivo_retroativo.py",
        "X9": "test_x9_supressao_abusiva.py",
        "X10": "test_x10_aditivo_desinstruido.py",
        "X11": "test_x11_objeto_descaracterizado.py",
        "X12": "test_x12_benford_quantitativos.py",
    }
    raiz = pathlib.Path(__file__).resolve().parent.parent
    existentes = {p.name for p in raiz.rglob("test_*.py")}

    sem_mapa = sorted(set(REGISTRO) - set(esperado))
    assert not sem_mapa, (
        f"detector novo sem entrada no mapa deste teste: {sem_mapa} — "
        "acrescente o id e o arquivo de teste correspondente")

    # CATRACA DE DÍVIDA TÉCNICA. Esta lista só pode ENCOLHER.
    #
    # Medição honesta de 2026-07-27: antes desta sessão apenas 6 dos 31 detectores tinham teste
    # (P4, E7, J8, C6, X1, X3). Uma medição anterior chegou a relatar "23 com teste" — estava
    # errada: casava o id do detector como substring do nome do arquivo, e a chave "C" casa com
    # quase qualquer nome. Números de cobertura precisam de mapa explícito, nunca de heurística.
    # DÍVIDA ZERADA em 2026-07-27: os 31 detectores do REGISTRO têm arquivo de teste.
    # A partir daqui a catraca é absoluta — detector novo sem teste falha na hora.
    DIVIDA_CONHECIDA: set[str] = set()
    sem_arquivo = {did for did in REGISTRO if esperado[did] not in existentes}

    novos = sorted(sem_arquivo - DIVIDA_CONHECIDA)
    assert not novos, (
        "detector SEM teste que não está na dívida conhecida — teste é obrigatório no mesmo "
        f"commit do detector: {', '.join(f'{d} (esperado {esperado[d]})' for d in novos)}")

    quitados = sorted(DIVIDA_CONHECIDA - sem_arquivo)
    assert not quitados, (
        "dívida quitada — REMOVA estes ids de DIVIDA_CONHECIDA para a catraca não afrouxar: "
        + ", ".join(quitados))
