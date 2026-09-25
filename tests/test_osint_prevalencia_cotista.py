# -*- coding: utf-8 -*-
"""A PREVALÊNCIA do QSA tem de viajar com o achado — e pesar na régua.

Medido em 2026-08-09, depois de ler os autos por inteiro: a MEDVIVA (contratada da FSERJ) tem
**125 sócios, 109 deles entrados no MESMO dia (27/01/2025) e UM administrador**. O agente público
encontrado no QSA é um cotista entre 125 — é sociedade de médicos / pejotização de equipe, o mesmo
desenho do caso AVIV (205 cotistas). A fila curada (`agente_publico_fila.json`) JÁ media
`socios_no_qsa`, mas `osint_x_processos` descartava o campo ao montar o achado: o relatório dizia
"agente público no quadro societário da contratada" sem o denominador, e quem lê entende DONO.

Duas correções, ambas conservadoras (o achado NÃO some — servidor do órgão contratante no QSA
segue sendo impedimento, art. 9º c/c 14 da Lei 14.133/2021):
1. `socios_no_qsa`/`servidores_no_qsa` viajam no achado e aparecem na linha do relatório;
2. cotista (QSA > 20) perde 1 ponto na régua do ranking, nunca caindo abaixo de 1.
"""
from __future__ import annotations

import inspect
import json

import tools.osint_x_processos as OXP
import tools.processo_360_ranking as PR


def _corpo(socios: int | None, *, conflito: bool = True) -> dict:
    return {"achados": [{
        "processo": "SEI-080002/014914/2024",
        "agentes": [{"nome": "FULANO DE TAL", "cargo": "DIRETOR GERAL", "orgao": "FUNDACAO X",
                     "comissionado": True, "entidade": "SOCIEDADE MEDICA LTDA",
                     "socios_no_qsa": socios,
                     "conflito_de_orgao": "", "conflito_pelo_processo": "FUNDACAO X" if conflito else ""}],
    }]}


def _pontos(tmp_path, monkeypatch, corpo: dict) -> tuple[int, str]:
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "osint_x_processos.json").write_text(json.dumps(corpo), encoding="utf-8")
    monkeypatch.setattr(PR, "REPO", tmp_path)
    r = PR.sinal_osint()["SEI-080002/014914/2024"]
    return r["pontos"], r["motivo"]


def test_cotista_de_sociedade_grande_pesa_menos(tmp_path, monkeypatch):
    pts_dono, _ = _pontos(tmp_path, monkeypatch, _corpo(2))
    pts_cotista, motivo = _pontos(tmp_path, monkeypatch, _corpo(125))
    assert pts_dono == 3, "conflito pelo processo deixou de valer 3"
    assert pts_cotista == 2, "cotista de sociedade de 125 pesa igual a sócio de empresa de dois"
    assert "125 sócios" in motivo, "o denominador não aparece no motivo — o leitor entende DONO"


def test_cotista_nunca_zera_o_sinal(tmp_path, monkeypatch):
    """Impedimento (art. 9º/14) não desaparece por ser cota pequena — só pesa menos."""
    pts, _ = _pontos(tmp_path, monkeypatch, _corpo(125, conflito=False))
    assert pts >= 1


def test_qsa_desconhecido_nao_rebaixa(tmp_path, monkeypatch):
    """Sem o dado, NADA muda — ausência de medida não é medida de ausência."""
    pts, motivo = _pontos(tmp_path, monkeypatch, _corpo(None))
    assert pts == 3 and "COTISTA" not in motivo


def test_correlacao_carrega_o_denominador():
    fonte = inspect.getsource(OXP.correlacionar)
    assert "socios_no_qsa" in fonte, (
        "a correlação voltou a descartar a prevalência do QSA da fila curada")
