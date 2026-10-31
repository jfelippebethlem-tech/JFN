# -*- coding: utf-8 -*-
"""A fila do fiscal ordenava só por achado de DETECTOR — a inteligência não mudava a ordem.

A casa passou a sessão inteira construindo inteligência sobre as empresas (agente público no
quadro societário, autos correndo no próprio órgão do agente, participante de certame dividindo
contato com o concorrente) e nada disso mudava a ordem em que os autos são abertos. Correlacionar
é isto: o que se sabe da empresa muda o que se lê primeiro.

A PONTUAÇÃO É MODESTA DE PROPÓSITO. Achado de detector é vício LIDO NOS AUTOS; sinal OSINT é
indício SOBRE A EMPRESA, casado por nome ou por contato. Deixar o indício empurrar o vício para
baixo inverteria a hierarquia da prova.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_ranking_com_osint.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))


def _escrever(tmp_path, achados):
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "osint_x_processos.json").write_text(
        json.dumps({"achados": achados}), encoding="utf-8")


def test_conflito_de_orgao_pesa_mais_que_comissionado_que_pesa_mais_que_socio(tmp_path,
                                                                              monkeypatch):
    import processo_360_ranking as R

    monkeypatch.setattr(R, "REPO", tmp_path)
    _escrever(tmp_path, [
        {"processo": "SEI-1", "agentes": [{"nome": "A", "cargo": "x", "entidade": "E",
                                           "comissionado": True,
                                           "conflito_pelo_processo": "ÓRGÃO X"}]},
        {"processo": "SEI-2", "agentes": [{"nome": "B", "cargo": "x", "entidade": "E",
                                           "comissionado": True,
                                           "conflito_pelo_processo": ""}]},
        {"processo": "SEI-3", "agentes": [{"nome": "C", "cargo": "x", "entidade": "E",
                                           "comissionado": False,
                                           "conflito_pelo_processo": ""}]},
    ])
    o = R.sinal_osint()
    assert o["SEI-1"]["pontos"] == 3
    assert o["SEI-2"]["pontos"] == 2
    assert o["SEI-3"]["pontos"] == 1
    assert "PRÓPRIO órgão" in o["SEI-1"]["motivo"]


def test_o_indicio_nao_pode_superar_o_vicio_lido_nos_autos(tmp_path, monkeypatch):
    """Um processo SÓ com sinal OSINT (3 pts) não pode passar à frente de um com pagamento sem
    execução (5 pts). Hierarquia da prova: o que está nos autos vale mais."""
    import processo_360_ranking as R

    monkeypatch.setattr(R, "REPO", tmp_path)
    _escrever(tmp_path, [{"processo": "SEI-1", "agentes": [
        {"nome": "A", "cargo": "x", "entidade": "E", "comissionado": True,
         "conflito_pelo_processo": "ÓRGÃO X"}]}])
    maximo_osint = max(v["pontos"] for v in R.sinal_osint().values())
    pts_vicio, _ = R.pontuar(
        [{"codigo": "F_EXECUCAO_SEM_EVIDENCIA", "gravidade": "critica",
          "diz": "pagamento sem evidência de execução"}], {})
    assert maximo_osint < pts_vicio, (
        f"o indício ({maximo_osint}) alcançou o vício lido nos autos ({pts_vicio})")


def test_processo_sem_agente_nao_pontua(tmp_path, monkeypatch):
    """Terceiro setor sozinho não é sinal de agente — sem agente, sem ponto."""
    import processo_360_ranking as R

    monkeypatch.setattr(R, "REPO", tmp_path)
    _escrever(tmp_path, [{"processo": "SEI-9", "agentes": [], "terceiro_setor": ["123"]}])
    assert R.sinal_osint() == {}


def test_sem_o_arquivo_a_ordem_volta_a_ser_a_anterior(tmp_path, monkeypatch):
    """Prioridade que quebra a fila seria pior que prioridade nenhuma."""
    import processo_360_ranking as R

    monkeypatch.setattr(R, "REPO", tmp_path)
    assert R.sinal_osint() == {}
