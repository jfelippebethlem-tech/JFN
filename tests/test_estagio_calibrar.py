# -*- coding: utf-8 -*-
"""E13 calibrar + ouro sem vazamento + cota da manchete (O5.4)."""
from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest

from compliance_agent.aplicacao.estagios import Contexto
from compliance_agent.aplicacao.estagios import calibrar as C
from compliance_agent.llm import conferencia_risco as R
from compliance_agent.qualidade import detectores as D
from compliance_agent.qualidade import ouro as O

HOJE = date(2026, 11, 24)


def _entrada(**kw):
    e = {"manchete": True, "dominio": "OB paga elegível (E9)", "estado": "ativo",
         "fp_medida": {"data": "2026-11-20", "amostra": "x", "taxa": "x", "fonte_primaria": "x", "onde": "x",
                       "n": 0, "falsos": 0, "estratificada": False, "cobertura": 0.6, "origem": "e13"}}
    e.update(kw)
    return e


def _conf(n, falsos=0, origem="amostra", grave_idx=(), det="d.x"):
    """n itens decididos, todos FORA dos blocos do ouro (a conta da calibração fica exata)."""
    out, i = [], 0
    while len(out) < n:
        it = {"detector": det, "item": f"alerta:{i}", "origem": origem, "revisor": "claude-opus-5-5",
              "processo": None, "entidade": None, "orgao": None, "periodo": None}
        i += 1
        if O.reservado_ouro(O.bloco(it)):
            continue
        j = len(out)
        it["falso"] = j < falsos
        it["grave"] = j in grave_idx
        out.append(it)
    return out


# ── Wilson ──────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("k,n,esperado", [
    (0, 30, (0.0, 0.1135)), (1, 30, (0.0059, 0.1667)), (13, 30, (0.2738, 0.608)),
    (30, 30, (0.8865, 1.0)), (0, 1, (0.0, 0.7935)), (1, 1, (0.2065, 1.0)),
])
def test_wilson_bordas(k, n, esperado):
    lo, hi = D.wilson_ic95(k, n)
    assert lo == pytest.approx(esperado[0], abs=1e-4) and hi == pytest.approx(esperado[1], abs=1e-4)
    assert 0.0 <= lo <= k / n <= hi <= 1.0


def test_wilson_sem_n_e_none():
    assert D.wilson_ic95(0, 0) is None


# ── régua ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_promove_com_n_estratificado_suficiente():
    r = C.calibrar_entrada("d.x", _entrada(), _conf(40), hoje=HOJE, quem="t")
    assert r["depois"]["tier"] == 1 and r["acao"] == "promove"
    assert r["campos"]["fp_medida"]["n"] == 40 and r["campos"]["fp_medida"]["estratificada"] is True
    h = r["campos"]["calibracao"]["historico"][-1]
    assert h["quem"] == "t" and h["n"] == 40 and h["ic95"] == list(D.wilson_ic95(0, 40)) and h["em"]


def test_sem_n_minimo_nao_promove():
    r = C.calibrar_entrada("d.x", _entrada(), _conf(29), hoje=HOJE, quem="t")
    assert r["depois"]["tier"] == 2 and "n=29<30" in r["depois"]["motivo"]


def test_n_grande_mas_nao_estratificado_nao_promove():
    r = C.calibrar_entrada("d.x", _entrada(), _conf(100, origem="legado"), hoje=HOJE, quem="t")
    assert r["depois"]["tier"] == 2 and "amostra_nao_estratificada" in r["depois"]["motivo"]


def test_erro_grave_rebaixa_tier1():
    tier1 = C.calibrar_entrada("d.x", _entrada(), _conf(40), hoje=HOJE, quem="t")
    e1 = {**_entrada(), **tier1["campos"]}
    assert D.avaliar_tier(e1, HOJE)["tier"] == 1
    r = C.calibrar_entrada("d.x", e1, _conf(41, falsos=1, grave_idx=(0,)), hoje=HOJE, quem="t")
    assert r["graves_novos"] == ["alerta:0"]
    assert r["depois"]["tier"] == 2 and "erro_grave_conferido" in r["depois"]["motivo"] and r["acao"] == "rebaixa"
    assert r["campos"]["calibracao"]["erro_grave_aberto"] == ["alerta:0"]


def test_erro_grave_dispara_mesmo_sem_n_novo():
    base = C.calibrar_entrada("d.x", _entrada(), _conf(40), hoje=HOJE, quem="t")
    e1 = {**_entrada(), **base["campos"]}
    conf = _conf(40)
    conf[3].update(falso=True, grave=True)
    r = C.calibrar_entrada("d.x", e1, conf, hoje=HOJE, quem="t")
    assert r["acao"] == "rebaixa" and r["depois"]["tier"] == 2


def test_sem_novidade_nao_grava():
    base = C.calibrar_entrada("d.x", _entrada(), _conf(40), hoje=HOJE, quem="t")
    e1 = {**_entrada(), **base["campos"]}
    r = C.calibrar_entrada("d.x", e1, _conf(43), hoje=HOJE, quem="t")
    assert r["acao"] == "sem_novidade" and r["campos"] is None


def test_medida_manual_maior_nao_e_sobrescrita():
    e = _entrada(fp_medida={"data": "2026-11-19", "amostra": "x", "taxa": "x", "fonte_primaria": "x", "onde": "x",
                            "n": 50, "falsos": 20, "estratificada": True, "cobertura": None})
    r = C.calibrar_entrada("d.x", e, _conf(10), hoje=HOJE, quem="t")
    assert r["campos"]["fp_medida"]["n"] == 50 and r["campos"]["calibracao"]["ultima"]["medida_mantida"] == "manual"


# ── ouro sem vazamento ────────────────────────────────────────────────────────────────────────────────────
def test_vazamento_por_processo_detectado():
    cal = [{"detector": "a", "item": "1", "processo": "SEI-1/2025"}]
    ouro = [{"detector": "b", "item": "2", "processo": "sei-1/2025"}]
    assert any(v.startswith("processo:") for v in O.vazamentos(cal, ouro))


def test_vazamento_por_orgao_periodo_e_item():
    cal = [{"detector": "a", "item": "1", "orgao": "133100", "periodo": "2025"}]
    ouro = [{"detector": "a", "item": "1", "orgao": "133100", "periodo": "2025"}]
    v = O.vazamentos(cal, ouro)
    assert any(x.startswith("orgao_periodo:") for x in v) and any(x.startswith("item:") for x in v)


def test_separar_nunca_vaza():
    itens = [{"detector": "d", "item": str(i), "processo": f"P{i % 17}", "entidade": None, "orgao": None,
              "periodo": None} for i in range(300)]
    cal, ouro = O.separar(itens)
    assert cal and ouro and O.vazamentos(cal, ouro) == []


def test_separar_funde_dimensoes_sem_vazar():
    """Regressão do snapshot de 24/11: entidade A no ouro e entidade B na calibração com o MESMO órgão × período
    vazava pela precedência. Com os componentes, quem divide qualquer chave fica do mesmo lado."""
    itens = [{"detector": f"d{i % 3}", "item": str(i), "processo": None, "entidade": f"E{i}",
              "orgao": f"UG{i % 7}", "periodo": "2026"} for i in range(200)]
    itens += [{"detector": "d9", "item": f"p{i}", "processo": f"P{i}", "entidade": f"E{i}", "orgao": None,
               "periodo": None} for i in range(50)]
    cal, ouro = O.separar(itens)
    assert O.vazamentos(cal, ouro) == []


def test_separacao_e_global_entre_detectores():
    """O mesmo processo em dois detectores vai para o MESMO lado (nunca calibra um e é ouro do outro)."""
    conf = [{"detector": d, "item": f"{d}:{i}", "falso": False, "origem": "amostra", "processo": f"P{i}"}
            for d in ("a", "b") for i in range(60)]
    marcados = C.marcar_ouro(conf)
    lado = {}
    for c in marcados:
        assert lado.setdefault(c["processo"], c["_ouro"]) == c["_ouro"]
    cal = [c for c in marcados if not c["_ouro"]]
    res = [c for c in marcados if c["_ouro"]]
    assert res and O.vazamentos(cal, res) == []


def test_calibracao_ignora_bloco_do_ouro():
    itens = [{"detector": "d.x", "item": f"alerta:{i}", "falso": False, "origem": "amostra", "processo": f"P{i}"}
             for i in range(100)]
    r = C.calibrar_entrada("d.x", _entrada(), itens, hoje=HOJE, quem="t")
    assert r["reservados_ouro"] > 0 and r["calibracao"] + r["reservados_ouro"] == 100
    assert r["medida"]["n"] == r["calibracao"]


def test_ouro_congelado_recusa_adulteracao_e_rotulo_tardio(tmp_path):
    rot = [O.Rotulo("d", "1", "falso", "dono", "2026-11-20", negativo_proximo=False),
           O.Rotulo("d", "2", "verdadeiro", "dono", "2026-11-21", negativo_proximo=True)]
    arq = O.congelar(rot, tmp_path, "2026-11-22")
    assert len(O.ler_congelado(arq)) == 2 and len(O.negativos_proximos(O.ler_congelado(arq))) == 1
    with pytest.raises(O.ErroOuro):
        O.congelar(rot, tmp_path, "2026-11-22")              # nunca regravar
    with pytest.raises(O.ErroOuro):
        O.congelar([O.Rotulo("d", "3", "falso", "dono", "2026-11-23")], tmp_path, "2026-11-22")
    arq.write_text(arq.read_text(encoding="utf-8").replace("falso", "verdadeiro"), encoding="utf-8")
    with pytest.raises(O.ErroOuro):
        O.ler_congelado(arq)


def test_kappa_e_dois_revisores():
    assert O.kappa_cohen(["falso", "verdadeiro"] * 5, ["falso", "verdadeiro"] * 5) == 1.0
    assert O.kappa_cohen(["falso", "verdadeiro"], ["verdadeiro", "falso"]) == -1.0
    assert O.kappa_cohen([], []) is None
    so_opus = [O.Rotulo("d", str(i), "falso", "claude-opus-5-5", "2026-11-20") for i in range(6)]
    assert not O.estado_revisao_tier1(so_opus, "d")["pronto"]
    dono = [O.Rotulo("d", str(i), "falso", "dono", "2026-11-20") for i in range(6)]
    assert O.estado_revisao_tier1(dono, "d")["pendencia"] == "pendente_2o_revisor"
    pronto = O.estado_revisao_tier1(dono + so_opus, "d")
    assert pronto["pronto"] and pronto["kappa"] == 1.0 and pronto["n_pareados"] == 6


# ── cota da manchete ─────────────────────────────────────────────────────────────────────────────────────
def test_cota_reservada_so_manchete_ate_30():
    reg = {"m1": _entrada(), "m2": _entrada(estado="fundido", fundido_em="m1"), "s": _entrada(manchete=False)}
    cota = C.cota_reservada(reg, _conf(10, det="m1"))
    assert cota == {"m1": 20}
    assert C.cota_reservada({"m1": _entrada()}, _conf(30, det="m1")) == {}


def test_cota_entra_em_classificar_lote_antes_da_amostra():
    itens = [{"id": i, "chave": f"k{i}", "tarefa": "t", "item": None, "motor": "m", "nivel": 0, "baixa": False,
              "valor": None, "valor_aplica": False, "divergente": False, "detector": "m1" if i < 10 else None}
             for i in range(40)]
    out = R.classificar_lote(itens, limiar=1e12, cota={"m1": 3})
    assert sum(i["motivos"] == ["cota"] for i in out) == 3
    assert all(i["detector"] == "m1" for i in out if i["motivos"] == ["cota"])
    sem = R.classificar_lote([dict(i, motivos=None) for i in itens], limiar=1e12)
    assert not any(i["motivos"] == ["cota"] for i in sem)


# ── gravação no registro e contrato do estágio ─────────────────────────────────────────────────────────────
REG_YAML = """# registro de teste
detectores:
  d.x:
    modulo: m.py
    manchete: true
    dominio: OB paga elegível
    # comentário que fica
    fp_medida:
      data: '2026-11-20'
      n: 0
    tier: 3
  d.y:
    modulo: m.py
    manchete: false
    fp_medida: null
"""


def test_trocar_campos_so_calibracao(tmp_path):
    arq = tmp_path / "reg.yaml"
    arq.write_text(REG_YAML, encoding="utf-8")
    r = C.calibrar_entrada("d.x", D.carregar(arq)["d.x"], _conf(40), hoje=HOJE, quem="t")
    assert C.gravar_registro([r], arq, HOJE) == ["d.x"]
    txt = arq.read_text(encoding="utf-8")
    assert "# comentário que fica" in txt
    reg = D.carregar(arq)
    assert reg["d.x"]["fp_medida"]["n"] == 40 and reg["d.x"]["tier"] == D.avaliar_tier(reg["d.x"], HOJE)["tier"]
    assert reg["d.y"] == {"modulo": "m.py", "manchete": False, "fp_medida": None}


def _fonte(tmp_path, n=12, fp=3):
    db = tmp_path / "extrato.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE alertas(id INTEGER PRIMARY KEY, tipo TEXT, severidade TEXT, titulo TEXT, descricao TEXT,"
                " evidencias TEXT, status TEXT, data_referencia TEXT, created_at TEXT)")
    con.execute("CREATE TABLE alertas_triagem(alerta_id INTEGER PRIMARY KEY, leitura_opus TEXT, verificado_por TEXT,"
                " em TEXT, opus_pendente INTEGER)")
    for i in range(n):
        con.execute("INSERT INTO alertas VALUES(?,?,?,?,?,?,?,?,?)",
                    (i, "emendas_d6_empenho_sem_pagamento", "alta" if i == 0 else "baixa", "t", "d",
                     json.dumps({"exercicio": 2025, "cnpj": f"{i:014d}"}), "aberto", None, "2026-11-20"))
        con.execute("INSERT INTO alertas_triagem VALUES(?,?,?,?,0)",
                    (i, "provavel_falso_positivo" if i < fp else "monitorar", "claude-opus-5-5", "2026-11-21"))
    con.execute("INSERT INTO alertas VALUES(99,'emendas_d6_empenho_sem_pagamento','alta','t',"
                "'NÃO é acusação: x','{}','aberto',NULL,'2026-11-20')")
    con.execute("INSERT INTO alertas_triagem VALUES(99,'provavel_falso_positivo','claude-opus-5-5','2026-11-21',0)")
    con.commit()
    con.close()
    return db


def test_handler_e_efeito_em_sombra(tmp_path):
    db = _fonte(tmp_path)
    saida = tmp_path / "sombra.json"
    ctx = Contexto(no="t", tipo="calibrar:emendas.D6", chave="calibrar:emendas.D6", ficha=1, tentativa=1)
    p = {"fonte": str(db), "saida": str(saida), "hoje": "2026-11-24"}
    res = C._handler(p, ctx)
    assert C._efeito(p, ctx, res)
    corpo = json.loads(saida.read_text(encoding="utf-8"))
    r = corpo["resultados"][0]
    assert r["detector"] == "emendas.D6" and r["conferidos"] == 12      # "NÃO é acusação" fica fora
    assert r["medida"]["n"] + r["reservados_ouro"] == 12
    # declarar efeito que não houve: a contagem do arquivo adulterada não passa
    corpo["resultados"][0]["medida"]["n"] += 1
    saida.write_text(json.dumps(corpo), encoding="utf-8")
    assert not C._efeito(p, ctx, res)
