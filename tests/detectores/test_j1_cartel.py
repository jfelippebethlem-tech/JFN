# -*- coding: utf-8 -*-
"""Rede de proteção do detector J1 — conluio/cartel por concentração de grupo econômico.

O detector consome o retorno de `grafo_cartel.concentracao_por_grupo` e, opcionalmente, de
`rodizio_temporal.rodizio_orgao`. Os testes INJETAM esses retornos no contexto (é o caminho que o
próprio docstring do detector indica), então nada aqui toca DuckDB nem o banco de produção.

O ponto delicado: mercado restrito genuíno gera concentração SEM cartel. Concentração isolada,
sem sócio-elo, não pode subir acima de 'medio' — senão o detector acusa toda UG que compra de
poucos fornecedores porque só existem poucos.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.j1_cartel import J1Cartel, _share


def _conc(share: float, n_raizes: int, n_cnpjs_grupo: int, n_cnpjs: int = 40) -> dict:
    """Retorno sintético de `concentracao_por_grupo`.

    `n_cnpjs_grupo > n_raizes` é o que materializa o SÓCIO-ELO: dois CNPJs de raízes distintas
    colapsaram no mesmo grupo porque compartilham sócio.
    """
    return {"n_cnpjs": n_cnpjs, "n_grupos_multi": 1,
            "maior_grupo_multi": {"share": share, "n_raizes": n_raizes, "n_cnpjs": n_cnpjs_grupo}}


# ───────────────────────────── leitura do share ───────────────────────────────────────────────

def test_share_ausente_e_zero_nao_none():
    assert _share({}) == 0.0
    assert _share({"maior_grupo_multi": {}}) == 0.0
    assert _share({"maior_grupo_multi": {"share": 42.5}}) == 42.5


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_ug_sem_fornecedores_e_nao_avaliavel():
    """Base vazia ≠ UG limpa. INDISPONÍVEL nunca vira 0."""
    res = J1Cartel().avaliar({"ug": "133100", "concentracao": {"n_cnpjs": 0}})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


def test_concentracao_em_formato_invalido_e_nao_avaliavel():
    res = J1Cartel().avaliar({"ug": "133100", "concentracao": "isto não é um dict"})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0


def test_base_indisponivel_degrada_honesto(monkeypatch):
    """Sem `concentracao` no contexto o detector tenta o DuckDB; falhando, declara — não zera.

    O módulo `grafo_cartel` é caro de importar (DuckDB + compliance.db de produção), e o detector
    o importa DENTRO do `try`. Injetamos um módulo falso em `sys.modules` para exercitar o caminho
    de falha sem tocar em nada real — a primeira versão deste teste travou o pytest por 115 s
    justamente porque deixou o import verdadeiro acontecer.
    """
    import sys
    import types

    falso = types.ModuleType("compliance_agent.grafo_cartel")

    def _explode(*a, **k):
        raise RuntimeError("DuckDB fora do ar")

    falso.concentracao_por_grupo = _explode
    monkeypatch.setitem(sys.modules, "compliance_agent.grafo_cartel", falso)

    res = J1Cartel().avaliar({"ug": "133100"})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "indisponível" in res.motivo_refutacao


# ───────────────────────────── sem grupo multi-CNPJ ───────────────────────────────────────────

def test_share_abaixo_do_minimo_e_descartado():
    res = J1Cartel().avaliar({"ug": "133100", "concentracao": _conc(share=5.0, n_raizes=3,
                                                                    n_cnpjs_grupo=3)})
    assert res.status == "descartado"
    assert res.score == 0.0
    assert res.explicacao_inocente


def test_raiz_unica_nao_e_grupo_multi():
    """Uma empresa só com share alto não é cartel — é fornecedor dominante, que pode ser lícito."""
    res = J1Cartel().avaliar({"ug": "133100", "concentracao": _conc(share=80.0, n_raizes=1,
                                                                    n_cnpjs_grupo=1)})
    assert res.status == "descartado"


def test_min_share_configuravel():
    ctx = {"ug": "133100", "concentracao": _conc(share=20.0, n_raizes=2, n_cnpjs_grupo=2)}
    assert J1Cartel().avaliar(ctx).status == "confirmado"
    assert J1Cartel().avaliar({**ctx, "min_share": 50.0}).status == "descartado"


# ───────────────────────────── concentração sem sócio-elo ─────────────────────────────────────

def test_concentracao_sem_socio_elo_nao_passa_de_medio():
    """FALSO POSITIVO do spec: mercado restrito genuíno concentra sem cartel.

    Sem sócio em comum materializado, o teto é 'medio' — anomalia a confirmar, não conluio.
    """
    res = J1Cartel().avaliar({"ug": "133100", "concentracao": _conc(share=70.0, n_raizes=3,
                                                                    n_cnpjs_grupo=3)})
    assert res.status == "confirmado"
    assert res.score == pytest.approx(ANCORAS["medio"])
    assert res.valores["socio_elo_presente"] is False


# ───────────────────────────── sócio-elo: o achado forte ──────────────────────────────────────

def test_socio_elo_entre_raizes_distintas_e_critico():
    """CNPJs de raízes diferentes unidos por sócio comum, concentrando a UG = concorrência fictícia."""
    res = J1Cartel().avaliar({"ug": "133100", "concentracao": _conc(share=60.0, n_raizes=2,
                                                                    n_cnpjs_grupo=5)})
    assert res.valores["socio_elo_presente"] is True
    assert res.score >= ANCORAS["critico"] or res.score == pytest.approx(1.0)


# ───────────────────────────── rodízio como reforço ───────────────────────────────────────────

def test_rodizio_corrobora_e_eleva():
    sem = J1Cartel().avaliar({"ug": "133100",
                              "concentracao": _conc(share=70.0, n_raizes=3, n_cnpjs_grupo=3)})
    com = J1Cartel().avaliar({"ug": "133100",
                              "concentracao": _conc(share=70.0, n_raizes=3, n_cnpjs_grupo=3),
                              "rodizio": {"indicio": True, "score": 0.7}})
    assert com.score > sem.score
    assert com.valores["rodizio_indicio"] is True


def test_rodizio_ausente_nao_derruba_o_detector():
    """Rodízio é REFORÇO opcional: sua ausência não pode zerar o achado de concentração."""
    res = J1Cartel().avaliar({"ug": "133100",
                              "concentracao": _conc(share=60.0, n_raizes=2, n_cnpjs_grupo=5),
                              "rodizio": None})
    assert res.score > 0


def test_rodizio_em_formato_estranho_nao_quebra():
    res = J1Cartel().avaliar({"ug": "133100",
                              "concentracao": _conc(share=60.0, n_raizes=2, n_cnpjs_grupo=5),
                              "rodizio": "texto inesperado"})
    assert res.status in STATUS_VALIDOS


# ───────────────────────────── schema §1.4 ────────────────────────────────────────────────────

def test_schema_de_saida_conforme_spec():
    res = J1Cartel().avaliar({"ug": "133100",
                              "concentracao": _conc(share=60.0, n_raizes=2, n_cnpjs_grupo=5)})
    d = res.to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "J1"
    assert 0.0 <= d["score"] <= 1.0
