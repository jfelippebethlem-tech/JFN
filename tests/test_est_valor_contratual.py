# -*- coding: utf-8 -*-
"""Valor contratual excedido sem aditivo e aditivo acima do teto — ESFERA ESTADUAL (análogo do d11 municipal).

Confronto CGE × JFN 13/11/2026 (lacuna 5): a CGE apontou contrato pago acima do valor sem aditivo e aditivo de
45,4% num contrato estadual — o JFN só tinha o detector no município (`pcrj/pericia_gastos.d11`). Pago = só OB
Contabilizada do SIAFE, do MESMO credor e do MESMO processo (a ponte só por processo casava credores alheios).
Teto do art. 125 vem de `limites_aditivo` (fonte única). Dados SINTÉTICOS.
"""
from __future__ import annotations

import sqlite3

from compliance_agent.detectores import est_valor_contratual as E

CNPJ = "11222333000181"
PROC = "SEI-000001/000002/2025"


def _ob(valor, status="Contabilizado", credor=CNPJ, processo="SEI-000001/000002/25"):
    return {"numero_ob": "OB", "status": status, "credor": credor, "processo": processo, "valor": valor}


def _contrato(**kw):
    c = {"id": "c1", "processo": PROC, "valor_contrato": 100_000.0, "cnpj": CNPJ,
         "objeto": "Serviço de manutenção predial", "unidade": "UG SINTETICA"}
    c.update(kw)
    return c


def test_processo_canonico_casa_ano_de_dois_digitos():
    assert E.processo_canonico("SEI-000001/000002/25") == E.processo_canonico("SEI-000001/000002/2025")
    assert E.processo_canonico("sei-000001/000002/2025") == "0000010000022025"
    assert E.processo_canonico("") is None


def test_pago_acima_do_contratado_sem_aditivo_registrado():
    r = {x.detector: x for x in E.avaliar(_contrato(), [_ob(60_000.0), _ob(70_000.0)], aditivos=None)}
    v = r["EST-VALOR-EXCEDIDO"]
    assert v.status == "confirmado"
    assert v.valores["pago_ob_contabilizada"] == 130_000.0 and round(v.valores["pct_excedente"], 1) == 30.0
    assert "aditivos_nao_coletados" in v.valores["lacunas"]          # não coletado ≠ inexistente
    assert v.score == 0.6                                 # sem os aditivos, 'forte' seria às cegas
    v = {x.detector: x for x in E.avaliar(_contrato(), [_ob(60_000.0), _ob(70_000.0)], aditivos=[])}
    assert v["EST-VALOR-EXCEDIDO"].score >= 0.85          # aditivos conhecidos (nenhum) e 30% > teto de 25%


def test_ob_anulada_de_outro_credor_ou_outro_processo_nao_soma():
    obs = [_ob(90_000.0), _ob(50_000.0, status="Anulado"), _ob(50_000.0, credor="99888777000166"),
           _ob(50_000.0, processo="SEI-000009/000009/2025")]
    r = {x.detector: x for x in E.avaliar(_contrato(), obs, aditivos=None)}
    assert r["EST-VALOR-EXCEDIDO"].status == "descartado"
    assert r["EST-VALOR-EXCEDIDO"].valores["pago_ob_contabilizada"] == 90_000.0


def test_aditivo_de_valor_que_cobre_o_pago_afasta():
    ads = [{"objeto": "Acréscimo de quantitativos de 20%", "valor_acrescido": 20_000.0}]
    r = {x.detector: x for x in E.avaliar(_contrato(), [_ob(115_000.0)], aditivos=ads)}
    assert r["EST-VALOR-EXCEDIDO"].status == "descartado"
    assert r["EST-ADITIVO-TETO"].status == "descartado"


def test_aditivo_acima_do_teto_e_reforma_tem_50():
    ads = [{"objeto": "Acréscimo de serviços", "valor_acrescido": 45_400.0}]
    r = {x.detector: x for x in E.avaliar(_contrato(), [], aditivos=ads)}
    assert r["EST-ADITIVO-TETO"].status == "confirmado" and r["EST-ADITIVO-TETO"].valores["teto"] == 0.25
    r = {x.detector: x for x in E.avaliar(_contrato(objeto="Reforma de edifício-sede"), [], aditivos=ads)}
    assert r["EST-ADITIVO-TETO"].status == "descartado" and r["EST-ADITIVO-TETO"].valores["teto"] == 0.50


def test_reajuste_nao_conta_no_teto_mas_cobre_o_pago():
    ads = [{"objeto": "Reajuste anual pelo IPCA", "valor_acrescido": 30_000.0}]
    r = {x.detector: x for x in E.avaliar(_contrato(), [_ob(125_000.0)], aditivos=ads)}
    assert r["EST-ADITIVO-TETO"].status == "descartado"
    assert r["EST-VALOR-EXCEDIDO"].status == "descartado"


def test_tipo_objeto_reforma_vem_da_fonte_unica():
    from compliance_agent.limites_aditivo import teto_acrescimo, tipo_objeto
    assert tipo_objeto("Reforma do prédio anexo") == "reforma" and teto_acrescimo(tipo_objeto("Reforma do prédio")) == 0.5
    assert tipo_objeto("Construção de escola") is None and teto_acrescimo(tipo_objeto("Construção")) == 0.25


def test_sem_valor_contratado_e_nao_avaliavel():
    r = E.avaliar(_contrato(valor_contrato=None), [_ob(1.0)], aditivos=None)
    assert {x.status for x in r} == {"nao_avaliavel"}


def test_varrer_le_tce_e_siafe(tmp_path):
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE contratos_tcerj (id TEXT, processo TEXT, valor_contrato REAL, cnpj TEXT, objeto TEXT, "
                "unidade TEXT, fornecedor TEXT, data_contratacao TEXT)")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, status TEXT, credor TEXT, processo TEXT, "
                "valor REAL, data_emissao TEXT)")
    con.execute("CREATE TABLE contrato_aditivo (numero_controle_pncp TEXT, objeto TEXT, valor_acrescido REAL, "
                "processo TEXT, prazo_aditado_dias INTEGER, qualif_acrescimo TEXT, qualif_vigencia TEXT, "
                "qualif_reajuste TEXT, fundamento_legal TEXT)")
    con.execute("INSERT INTO contratos_tcerj VALUES ('c1', ?, 100000, ?, 'Manutenção', 'UG', 'F', '2025-01-01')",
                (PROC, CNPJ))
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?)",
                    [("1", "Contabilizado", CNPJ, "SEI-000001/000002/25", 80_000.0, "2025-03-01"),
                     ("2", "Contabilizado", CNPJ, "SEI-000001/000002/2025", 60_000.0, "2025-06-01")])
    con.commit()
    res = E.varrer(con)
    assert [r.detector for r in res] == ["EST-VALOR-EXCEDIDO"]
    assert res[0].valores["pago_ob_contabilizada"] == 140_000.0
