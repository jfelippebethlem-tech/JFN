# -*- coding: utf-8 -*-
"""Revisão cética 13/11/2026: sanção só conta "à época" se VIGENTE na data E com ALCANCE sobre o ente
pagador/comprador; o sinal fênix do radar só com pagamento após a baixa confirmado, sem truncar em 120."""
from __future__ import annotations

import sqlite3

from compliance_agent import cruzamentos_intel as C

ALFA, BETA, GAMA = "11111111000111", "22222222000122", "33333333000133"


def _base(tmp_path):
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE sancoes_federais (cadastro TEXT, cpf_cnpj TEXT, nome TEXT, categoria TEXT, data_inicio TEXT,
        data_fim TEXT, orgao TEXT, uf TEXT, processo TEXT, fundamentacao TEXT, abrangencia TEXT,
        esfera_sancionador TEXT, data_publicacao TEXT);
    CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT,
        credor TEXT, nome_credor TEXT, valor REAL);
    CREATE TABLE pncp_resultado (certame TEXT, orgao_cnpj TEXT, orgao_nome TEXT, uf TEXT, municipio TEXT,
        data_pub TEXT, fornecedor_cnpj TEXT, fornecedor_nome TEXT, valor_homologado REAL,
        ordem_classificacao INTEGER, unidade_nome TEXT);
    """)
    S = "INSERT INTO sancoes_federais VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
    con.executemany(S, [
        # ALFA: suspensão "no órgão sancionador" federal — não alcança o Estado do RJ
        ("CEIS", ALFA, "ALFA", "Suspensão", "2026-03-25", "2027-03-25", "Instituto Federal Ficticio", "RJ", "p",
         "LEI 8666 - ART. 87, III", "No órgão sancionador", "FEDERAL", "2026-03-26"),
        # BETA: impedimento do próprio Estado do RJ, vigente — alcança
        ("CEIS", BETA, "BETA", "Impedimento/proibição de contratar com prazo determinado", "2026-01-01",
         "2026-12-31", "Secretaria de Estado Ficticia", "RJ", "p", "LEI 14133 - ART. 156, III",
         "Em todos os Poderes da Esfera do órgão sancionador", "ESTADUAL", None),
        # GAMA: inidoneidade que só começa DEPOIS do pagamento
        ("CEIS", GAMA, "GAMA", "Declaração de Inidoneidade sem prazo determinado", "2026-09-01", None,
         "Controladoria Federal Ficticia", "DF", "p", "LEI 14133 - ART. 156, IV",
         "Todas as Esferas em todos os Poderes", "FEDERAL", None),
    ])
    O = "INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?)"
    con.executemany(O, [
        ("2026OB00001", "100100", "26/03/2026", "Contabilizado", ALFA, "ALFA", 1_000.0),
        ("2026OB00002", "100100", "10/05/2026", "Contabilizado", BETA, "BETA", 2_000.0),
        ("2026OB00003", "100100", "10/05/2026", "Contabilizado", GAMA, "GAMA", 3_000.0),
    ])
    con.commit()
    con.close()
    return str(db)


def test_sancao_sem_alcance_ou_posterior_nao_conta_a_epoca(tmp_path):
    d = C.sancionadas_contratadas(_base(tmp_path))
    por = {e["cnpj"]: e for e in d["empresas"]}
    assert por[ALFA]["estado"]["obs_durante"] == 0          # "no órgão sancionador" (federal) ≠ Estado
    assert por[ALFA]["estado"]["obs_vigente_sem_alcance"] == 1
    assert por[BETA]["estado"]["obs_durante"] == 1          # impedimento do Estado do RJ, vigente
    assert por[GAMA]["estado"]["obs_durante"] == 0          # sanção posterior ao pagamento
    assert d["n_a_epoca"] == 1


def test_radar_so_marca_sancao_a_epoca_com_alcance(tmp_path, monkeypatch):
    db = _base(tmp_path)
    monkeypatch.setattr(C, "conluio_qsa", lambda *a, **k: {"pares": []})
    monkeypatch.setattr(C, "empresa_fenix", lambda *a, **k: {"achados": []})
    monkeypatch.setattr(C, "capital_incompativel", lambda *a, **k: {"achados": []})
    r = {a["cnpj"]: {s["sinal"] for s in a["sinais"]} for a in C.radar_risco(db)["achados"]}
    assert r[BETA] == {"sancao_a_epoca"}
    assert "sancao_a_epoca" not in r.get(ALFA, set())
    assert "sancao_a_epoca" not in r.get(GAMA, set())


def test_radar_fenix_so_com_pagamento_apos_baixa_e_sem_truncar(tmp_path, monkeypatch):
    db = _base(tmp_path)
    vistos = {}

    def fenix(db_path=None, limite=120):
        vistos["limite"] = limite
        base = [{"cnpj": f"{i:014d}", "tipo": "defunta", "pagou_apos_baixa": False} for i in range(1, 200)]
        base.append({"cnpj": "99999999000199", "tipo": "defunta", "pagou_apos_baixa": True, "situacao": "BAIXADA"})
        base.append({"cnpj": "88888888000188", "tipo": "recem_aberta", "situacao": "ATIVA"})
        return {"achados": base if limite is None else base[:limite]}

    monkeypatch.setattr(C, "conluio_qsa", lambda *a, **k: {"pares": []})
    monkeypatch.setattr(C, "empresa_fenix", fenix)
    monkeypatch.setattr(C, "capital_incompativel", lambda *a, **k: {"achados": []})
    achados = C.radar_risco(db, limite=1000)["achados"]
    com_fenix = {a["cnpj"] for a in achados if any(s["sinal"] == "fenix" for s in a["sinais"])}
    assert com_fenix == {"99999999000199"}                  # o 201º da lista, que o corte em 120 perdia
    assert vistos["limite"] is None
