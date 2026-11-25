# -*- coding: utf-8 -*-
"""O8.4 — a automelhoria consome o E18: SLO fora vira item da fila com o `remediar:` declarado; automático só com
critério forte (remédio de fluxo/remedios.py, sem ⚖️/🔒); swap cheio com PSI de memória ~0 é DEGRADADO."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compliance_agent.fluxo import sensores as S  # noqa: E402
from tools import automelhoria_executor as X  # noqa: E402
from tools import automelhoria_geral as A  # noqa: E402

SLOS = S.carregar_slos()
AGORA = 1_800_000_000.0


def _ln(no, nome, v, idade=60):
    return {"no": no, "nome": nome, "valor": v, "quando": AGORA - idade, "rotulos": {}}


def _item(estado: dict, slo: str, no: str = "vm1") -> dict:
    return next(i for i in estado["itens"] if i["slo"] == slo and i["no"] == no)


# ── swap × PSI (pedido do dono registrado na O8.1) ─────────────────────────────────────────────────────────────
def test_swap_cheio_sem_pressao_de_memoria_e_degradado_nao_bloqueado():
    est = S.estado_slos([_ln("vm1", "swap.uso_pct", 95.42), _ln("vm1", "psi.mem_some", 0.25)], SLOS, AGORA)
    it = _item(est, "swap")
    assert it["estado"] == "DEGRADADO" and "atenuado" in it["motivo"] and "psi.mem_some" in it["motivo"]


def test_swap_cheio_com_pressao_real_segue_bloqueado():
    est = S.estado_slos([_ln("vm1", "swap.uso_pct", 95.0), _ln("vm1", "psi.mem_some", 4.0)], SLOS, AGORA)
    assert _item(est, "swap")["estado"] == "BLOQUEADO"


def test_swap_sem_psi_medido_ou_velho_nao_atenua():
    est = S.estado_slos([_ln("vm1", "swap.uso_pct", 95.0)], SLOS, AGORA)                  # PSI nunca medido
    assert _item(est, "swap")["estado"] == "BLOQUEADO" and "sem atenuação" in _item(est, "swap")["motivo"]
    velho = S.estado_slos([_ln("vm1", "swap.uso_pct", 95.0), _ln("vm1", "psi.mem_some", 0.1, idade=4000)],
                          SLOS, AGORA)                                                     # além da janela do PSI
    assert _item(velho, "swap")["estado"] == "BLOQUEADO"


def test_swap_saudavel_e_degradado_pelo_limite_nao_mudam():
    est = S.estado_slos([_ln("vm1", "swap.uso_pct", 30.0), _ln("vm1", "psi.mem_some", 0.0)], SLOS, AGORA)
    assert _item(est, "swap")["estado"] == "SAUDAVEL"
    est = S.estado_slos([_ln("vm1", "swap.uso_pct", 70.0), _ln("vm1", "psi.mem_some", 9.0)], SLOS, AGORA)
    assert _item(est, "swap")["estado"] == "DEGRADADO"


def test_atenua_se_cita_sensor_com_slo():
    import pytest
    base = SLOS.slos["swap"].model_dump()
    base["atenua_se"] = {"sensor": "nao.existe", "menor_que": 1, "ate": "DEGRADADO"}
    with pytest.raises(ValueError):
        S.Slos(versao=1, slos={"swap": S.Slo(**base)})


# ── E18 → fila única ──────────────────────────────────────────────────────────────────────────────────────────
def _estado(*itens, nao_medidos=()):
    return {"itens": list(itens), "nao_medidos": list(nao_medidos)}


def _it(slo, estado, remediar, decisao=None, no="vm1"):
    return {"slo": slo, "estado": estado, "no": no, "escopo": "maquina", "remediar": remediar, "decisao": decisao,
            "motivo": "m", "severidade": "alta", "dono": "infra"}


def test_slo_fora_vira_item_com_remediar_declarado_e_saudavel_nao():
    ps = A.problemas_e18(_estado(_it("a", "SAUDAVEL", "x"), _it("disco_tendencia", "DEGRADADO", "achar quem cresce")),
                         remedios={"painel_travado"})
    assert [p["assinatura"] for p in ps] == ["e18:disco_tendencia@vm1"]
    assert ps[0]["remediar"] == "" and ps[0]["acao_humana"] == "achar quem cresce"      # texto ⇒ humano


def test_remedio_automatico_so_com_criterio_forte():
    ps = A.problemas_e18(_estado(
        _it("painel_resposta", "DEGRADADO", "remediar:painel_travado (python -m …): restart só com 2 falhas"),
        _it("x", "BLOQUEADO", "remediar:inexistente (…)"),                                  # nome fora de REMEDIOS
        _it("y", "BLOQUEADO", "remediar:painel_shm (…)", decisao="🔒")), remedios={"painel_travado", "painel_shm"})
    por = {p["assinatura"]: p for p in ps}
    assert por["e18:painel_resposta@vm1"]["remediar"].endswith("compliance_agent.fluxo.remedios painel_travado")
    assert por["e18:x@vm1"]["remediar"] == ""                                            # não declarado ⇒ humano
    assert por["e18:y@vm1"]["remediar"] == "" and por["e18:y@vm1"]["ao_dono"] == "🔒"       # 🔒 nunca automático


def test_remedios_reais_casam_com_o_slos_yaml():
    from compliance_agent.fluxo.remedios import REMEDIOS
    declarados = {m[1] for s in SLOS.slos.values() if (m := A._REMEDIO_DECLARADO.match(s.remediar))}
    assert declarados and declarados <= set(REMEDIOS)            # todo `remediar:<nome>` existe de verdade
    assert all(s.remediar for s in SLOS.slos.values())           # `remediar:` para cada SLO


def test_sem_medida_vira_um_item_agregado_nunca_ok():
    ps = A.problemas_e18(_estado(nao_medidos=[f"s{i}@vm1" for i in range(30)]), remedios=set())
    assert len(ps) == 1 and ps[0]["assinatura"] == "e18:sem-medida" and "30 SLO" in ps[0]["titulo"]


def test_ao_dono_persiste_na_fila_e_nao_e_executado(tmp_path):
    p = A._p("e18", "z", "t", remediar="echo x", acao_humana="h", ao_dono="⚖️")
    assert p["remediar"] == ""                                   # marca ⚖️/🔒 apaga qualquer comando
    r = A.conciliar([p], tmp_path / "f.json", agora=AGORA)
    assert r["fila"]["e18:z"]["ao_dono"] == "⚖️"
    executados = []
    A.remediar(r["fila"], agora=AGORA, executar=lambda c, log: executados.append(c))
    assert executados == []
    assert "⚖️ precisa do seu ✅" in A.resumo(r["fila"])


def test_sensor_e18_registrado_na_automelhoria():
    assert "e18" in A.SENSORES and "avisos" in A.SENSORES


# ── executor noturno: critério forte ──────────────────────────────────────────────────────────────────────────
def test_executor_criterio_forte_exige_teste_no_diff():
    assert X.criterio_forte(["tools/x.py", "tests/test_x.py"])[0] is True
    forte, motivo = X.criterio_forte(["tools/x.py", "tests/helpers.py"])
    assert forte is False and "FRACO" in motivo
    assert X.criterio_forte([])[0] is False


def test_executor_nunca_pega_item_do_dono():
    fila = {"a": {"assinatura": "catraca:a", "status": "aberto", "area": "catraca", "primeiro": "1"},
            "b": {"assinatura": "catraca:b", "status": "aberto", "area": "catraca", "primeiro": "0", "ao_dono": "⚖️"}}
    assert [i["assinatura"] for i in X.escolher(fila, {}, 5, agora=AGORA)] == ["catraca:a"]
