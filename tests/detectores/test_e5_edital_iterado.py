# -*- coding: utf-8 -*-
"""Rede de proteção do detector E5 — edital iterado (republicações dirigidas).

O padrão: republica-se o edital várias vezes até que a redação sirva a um perfil. Três regras
objetivas — volume de republicações, ciclo que termina em dispensa após rodadas desertas, e
impugnação seguida de mudança que EXCLUI justamente o impugnante.

Dois guards que separam este detector de um contador ingênuo de versões:
· **origem legítima** (determinação do TCE, erro material) não conta como iteração — é
  republicação DEVIDA, e o detector transforma isso em evidência exculpatória;
· mudança que **AMPLIA** a competição pós-impugnação é o comportamento CORRETO e zera a rodada.

Sem rede, sem banco, sem LLM.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.e5_edital_iterado import E5EditalIterado

_P = {"processo": "SEI-TESTE/000014/2026"}


def _retif(n: int, origem: str | None = None, nova_versao: bool = True) -> list[dict]:
    return [{"secao": f"item {i}", "origem": origem, "nova_versao": nova_versao}
            for i in range(n)]


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_sem_versoes_nem_retificacoes_e_nao_avaliavel():
    res = E5EditalIterado().avaliar({**_P})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


def test_uma_versao_unica_e_nao_avaliavel():
    """Edital publicado uma vez não tem o que iterar."""
    res = E5EditalIterado().avaliar({**_P, "versoes": [{"n": 1}]})
    assert res.status == "nao_avaliavel"


def test_duas_versoes_sem_padrao_nao_pontuam():
    res = E5EditalIterado().avaliar({**_P, "versoes": [{"n": 1}, {"n": 2}]})
    assert res.score == 0.0
    assert res.status == "descartado"


# ───────────────────────────── volume de republicações ────────────────────────────────────────

@pytest.mark.parametrize("n_versoes,esperado", [(3, 0.0), (4, ANCORAS["medio"]), (5, ANCORAS["forte"])])
def test_volume_de_republicacoes(n_versoes, esperado):
    res = E5EditalIterado().avaliar({**_P, "versoes": [{"n": i} for i in range(n_versoes)]})
    assert res.score == pytest.approx(esperado)


def test_retificacao_de_origem_legitima_nao_conta_como_iteracao():
    """Determinação do TCE é republicação DEVIDA. Contá-la puniria o órgão por obedecer."""
    res = E5EditalIterado().avaliar({**_P, "versoes": [{"n": i} for i in range(5)],
                                     "retificacoes": _retif(4, origem="tce")})
    assert res.valores["n_retificacoes_legitimas"] == 4
    assert res.score == 0.0
    assert "TCE" in res.motivo_refutacao


def test_erro_material_tambem_e_origem_legitima():
    res = E5EditalIterado().avaliar({**_P, "versoes": [{"n": i} for i in range(5)],
                                     "retificacoes": _retif(4, origem="erro_material")})
    assert res.valores["n_retificacoes_legitimas"] == 4
    assert res.score == 0.0


def test_esclarecimento_nao_entra_no_contador_de_volume():
    """Esclarecimento não republica o edital — entra no diff, não no volume."""
    retif = [{"secao": "x", "tipo": "esclarecimento", "nova_versao": False} for _ in range(6)]
    res = E5EditalIterado().avaliar({**_P, "versoes": [{"n": 1}, {"n": 2}], "retificacoes": retif})
    assert res.valores["n_retificacoes_no_volume"] == 0


def test_retificacao_que_reabre_prazo_conta_no_volume():
    retif = [{"secao": f"s{i}", "reabriu_prazo": True} for i in range(4)]
    res = E5EditalIterado().avaliar({**_P, "versoes": [{"n": 1}], "retificacoes": retif})
    assert res.valores["n_retificacoes_no_volume"] == 4
    assert res.score >= ANCORAS["forte"]


# ───────────────────────────── ciclo que termina em dispensa ──────────────────────────────────

def test_ciclo_deserto_que_termina_em_dispensa_e_forte():
    """Republica até dar deserto e então contrata direto — a motivação foi fabricada."""
    res = E5EditalIterado().avaliar({**_P, "versoes": [{"n": 1}, {"n": 2}],
                                     "resultados_rodadas": ["deserto", "deserto"],
                                     "resultado_final": "dispensa"})
    assert res.score >= ANCORAS["forte"]
    assert res.valores["n_rodadas_fracassadas"] == 2


def test_dispensa_sem_rodada_fracassada_nao_aciona_a_regra():
    res = E5EditalIterado().avaliar({**_P, "versoes": [{"n": 1}, {"n": 2}],
                                     "resultados_rodadas": ["homologado"],
                                     "resultado_final": "dispensa"})
    assert res.score == 0.0


def test_ciclo_que_termina_em_homologacao_nao_pontua():
    res = E5EditalIterado().avaliar({**_P, "versoes": [{"n": 1}, {"n": 2}],
                                     "resultados_rodadas": ["deserto", "homologado"],
                                     "resultado_final": "homologado"})
    assert res.score == 0.0


# ───────────────────────────── impugnação que exclui o impugnante ─────────────────────────────

def test_impugnacao_seguida_de_mudanca_que_exclui_o_impugnante():
    """O licitante reclamou e o edital mudou para eliminá-lo. É resposta dirigida à exclusão."""
    res = E5EditalIterado().avaliar({
        **_P, "versoes": [{"n": 1}, {"n": 2}],
        "impugnacoes": [{"licitante": "ACME", "pedido": "aceitar atestado equivalente",
                         "mudanca_exclui_impugnante": True, "atendida": False}]})
    assert res.score >= ANCORAS["forte"]
    assert res.valores["impugnacao_exclui_impugnante"] is True


def test_impugnacao_atendida_ampliando_competicao_nao_pontua():
    """Atender a impugnação relaxando exigência é o comportamento CORRETO."""
    res = E5EditalIterado().avaliar({
        **_P, "versoes": [{"n": 1}, {"n": 2}],
        "impugnacoes": [{"licitante": "ACME", "mudanca_exclui_impugnante": False,
                         "atendida": True}]})
    assert res.score == 0.0
    assert res.valores["impugnacao_exclui_impugnante"] is False


# ───────────────────────────── schema §1.4 ────────────────────────────────────────────────────

def test_schema_de_saida_conforme_spec():
    d = E5EditalIterado().avaliar({**_P, "versoes": [{"n": i} for i in range(5)]}).to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "E5"
    assert d["status"] in STATUS_VALIDOS
