# -*- coding: utf-8 -*-
"""Nomeados × candidatos — dados 100% sintéticos (nenhum nome, CPF ou órgão real de pessoa)."""
import json
import sqlite3

import pytest

from compliance_agent import nomeados_candidatos as N

_CAB = ("ANO_ELEICAO;SQ_CANDIDATO;NM_CANDIDATO;NR_CPF_CANDIDATO;DS_CARGO;NM_UE;SG_PARTIDO;"
        "DS_SITUACAO_CANDIDATURA;DS_SIT_TOT_TURNO")


def _csv(dirp, ano, linhas):
    (dirp / f"consulta_cand_{ano}_RJ.csv").write_text(
        "\n".join([_CAB] + [";".join(f'"{c}"' for c in ln) for ln in linhas]) + "\n", encoding="latin-1")


@pytest.fixture
def base(tmp_path):
    tse = tmp_path / "tse"
    tse.mkdir()
    # 2020 com CPF: FULANO (CPF 11122233344 → fragmento 122233) e o homônimo BELTRANO com OUTRO CPF
    _csv(tse, 2020, [
        (2020, 1, "FULANO DE TESTE", "11122233344", "VEREADOR", "CIDADE A", "PX", "APTO", "SUPLENTE"),
        (2020, 1, "FULANO DE TESTE", "11122233344", "VEREADOR", "CIDADE A", "PX", "APTO", "SUPLENTE"),  # 2º turno
        (2020, 2, "BELTRANO EXEMPLO", "99988877766", "PREFEITO", "CIDADE B", "PY", "APTO", "#NULO"),
        (2020, 3, "CICRANA SÓ NOME", "55544433322", "VEREADOR", "CIDADE C", "PZ", "APTO", "#NULO"),
        (2020, 6, "ZULANO AFERIR", "00044433300", "VEREADOR", "CIDADE E", "PZ", "APTO", "#NULO"),
    ])
    # 2024: o TSE publicou sem CPF
    _csv(tse, 2024, [
        (2024, 4, "FULANO DE TESTE", "-4", "VEREADOR", "CIDADE A", "PX", "APTO", "SUPLENTE"),
        (2024, 5, "DELTRANO SEM CPF", "-4", "VEREADOR", "CIDADE D", "PW", "APTO", "#NULO"),
    ])
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE registros_folha (nome, cpf, cargo, vinculo, orgao_nome, fonte, competencia)")
    c.executemany("INSERT INTO registros_folha VALUES (?,?,?,?,?,?,?)", [
        # FULANO (CPF 111.222.333-44): GESPERJ publica os dígitos 4–9 (222333), a Defensoria os 3–8 (122233),
        # ambos gravados como XX......XXX. Dois meses, duas folhas → UMA pessoa VERIFICADA
        ("FULANO DE TESTE", "XX222333XXX", "ASSESSOR", "CARGO COMISSAO", "SECRETARIA X", "gesperj_estado", "2026-05"),
        ("FULANO DE TESTE", "XX222333XXX", "ASSESSOR", "CARGO COMISSAO", "SECRETARIA X", "gesperj_estado", "2026-09"),
        ("FULANO DE TESTE", "XX122233XXX", "ANALISTA", "ATIVO", "DEFENSORIA", "dprj_transparencia", "2020-01"),
        # BELTRANO: o fragmento da GESPERJ lido no deslocamento ERRADO (2) bateria; no certo (3) não → homônimo
        ("BELTRANO EXEMPLO", "XX988877XXX", "ASSESSOR", "EFETIVO", "SECRETARIA Y", "gesperj_estado", "2026-09"),
        # fonte cuja máscara não foi aferida: não confere, fica PENDENTE (e esfera indefinida, fora do Estado)
        ("ZULANO AFERIR", "XX444333XXX", "TECNICO", "EFETIVO", "AUTARQUIA", "fonte_nova", "2026-09"),
        # CICRANA na Câmara (sem CPF, municipal) → PENDENTE, esfera municipal
        ("CICRANA SO NOME", "", "", "ASSISTENTE", "CAMARA", "camara_csv", "1990"),
        # DELTRANO: folha com CPF, mas candidatura de 2024 (sem CPF) → PENDENTE
        ("DELTRANO SEM CPF", "XX777777XXX", "AUXILIAR", "EFETIVO", "SECRETARIA Z", "gesperj_estado", "2026-09"),
        ("NINGUEM CANDIDATO", "XX123123XXX", "AUXILIAR", "EFETIVO", "SECRETARIA Z", "gesperj_estado", "2026-09"),
    ])
    c.execute("CREATE TABLE doacoes_eleitorais (nome_candidato, cargo_candidato, partido, ano_eleicao)")
    c.executemany("INSERT INTO doacoes_eleitorais VALUES (?,?,?,?)", [
        ("FULANO DE TESTE", "Deputado Estadual", "PX", 2018),     # 2018 sem CSV → entra só por nome
        ("FULANO DE TESTE", "Vereador", "PX", 2020),              # 2020 já veio do CSV → não duplica
    ])
    return N.cruzar(c, tse)


def _por_nome(b):
    return {x["nome"]: x for x in b["pessoas"]}


def test_um_cartao_por_pessoa_com_todas_as_candidaturas(base):
    p = _por_nome(base)["FULANO DE TESTE"]
    assert sum(x["nome"] == "FULANO DE TESTE" for x in base["pessoas"]) == 1
    assert [(c["ano"], c["verificacao"]) for c in p["candidaturas"]] == [(2018, "PENDENTE"), (2020, "VERIFICADO"),
                                                                         (2024, "PENDENTE")]
    assert len(p["vinculos"]) == 2 and p["vinculos"][0]["ultima_competencia"] == "2026-09"
    assert {v["fonte"] for v in p["vinculos"]} == {"Executivo estadual (GESPERJ)", "Defensoria Pública do Estado do RJ"}


def test_candidatura_sem_cpf_nao_herda_a_verificacao_do_cartao(base):
    cs = {c["ano"]: c for c in _por_nome(base)["FULANO DE TESTE"]["candidaturas"]}
    assert cs[2020]["nota"] == "CPF confere"
    assert cs[2024]["verificacao"] == "PENDENTE" and "mesmo município" in cs[2024]["nota"]
    assert cs[2018]["nota"] == "possível homônimo — não verificado"   # sem município para apoiar


def test_mascara_nao_aferida_nao_confere(base):
    p = _por_nome(base)["ZULANO AFERIR"]
    assert p["verificacao"] == "PENDENTE" and "não foi aferida" in p["motivo_verificacao"]
    assert p["esfera"] == "indefinida"


def test_cpf_parcial_confere_vira_verificado_e_comissionado_vem_do_vinculo(base):
    p = _por_nome(base)["FULANO DE TESTE"]
    assert p["verificacao"] == "VERIFICADO" and "CPF parcial" in p["motivo_verificacao"]
    assert p["comissionado"] is True   # GESPERJ põe "CARGO COMISSAO" no vínculo, não no cargo


def test_cpf_parcial_divergente_e_homonimo_descartado(base):
    assert "BELTRANO EXEMPLO" not in _por_nome(base)
    assert base["homonimos_descartados"] == 1


def test_so_nome_e_possivel_homonimo_nao_verificado(base):
    p = _por_nome(base)
    assert p["CICRANA SO NOME"]["verificacao"] == "PENDENTE"
    assert "possível homônimo — não verificado" in p["CICRANA SO NOME"]["motivo_verificacao"]
    assert p["DELTRANO SEM CPF"]["verificacao"] == "PENDENTE"
    assert "possível homônimo — não verificado" in p["DELTRANO SEM CPF"]["motivo_verificacao"]


def test_esfera_pela_fonte_da_folha(base):
    p = _por_nome(base)
    assert p["CICRANA SO NOME"]["esfera"] == "municipal"
    assert p["DELTRANO SEM CPF"]["esfera"] == "estado"
    est = N.recortar(base, "estado")
    assert "CICRANA SO NOME" not in {x["nome"] for x in est["itens"]}
    assert N.recortar(base, "municipal")["total"] == 1


def test_totais_reais_do_recorte(base):
    r = N.recortar(base, "todos")
    assert r["total"] == len(r["itens"]) == 4
    assert (r["n_verificados"], r["n_pendentes"]) == (1, 3)
    assert r["n_comissionados"] == 1 and r["n_comissionados_verificados"] == 1
    e = N.recortar(base, "estado")
    assert (e["total"], e["n_verificados"], e["n_pendentes"]) == (2, 1, 1)
    assert r["cobertura_tse"]["2024"]["com_cpf"] == 0 and r["cobertura_tse"]["2016"]["estado"].startswith("INDISP")


def test_verificados_primeiro(base):
    assert base["pessoas"][0]["verificacao"] == "VERIFICADO"


def test_cpf_nunca_sai_nem_o_fragmento(base):
    s = json.dumps(base, ensure_ascii=False)
    for frag in ("11122233344", "122233", "222333", "XX122233XXX", "777777", "55544433322", "444333"):
        assert frag not in s


def test_rota_pagina_e_declara_total_real(base, monkeypatch):
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    import rotas.investigacao as RI
    monkeypatch.setattr(RI, "_cache_calc", lambda chave, ttl, f: base)
    app = FastAPI()
    app.include_router(RI.router)
    d = TestClient(app).get("/api/poder/nomeados_candidatos?esfera=todos&limite=2").json()
    assert d["ok"] and d["total"] == 4 and len(d["itens"]) == 2 and d["truncado"] is True
    d = TestClient(app).get("/api/poder/nomeados_candidatos").json()   # padrão: Estado
    assert d["esfera"] == "estado" and d["total"] == 2 and d["truncado"] is False
    # o padrão não pode cortar a base real (5.708 pessoas em 13/11/2026; o primeiro padrão, 5.000, cortava)
    import inspect
    assert inspect.signature(RI.api_nomeados_candidatos).parameters["limite"].default >= 20000


def test_pdf_separa_verificados_de_pendentes(base):
    from compliance_agent.intel_relatorio import _b_nomeados
    r = N.recortar(base, "estado")
    titulo, sub, secoes, _ = _b_nomeados({"ok": True, **r, "n": r["total"]})
    assert "1 VERIFICADAS" in sub and "1 PENDENTES" in sub
    assert "VERIFICADOS" in secoes[0]["titulo"] and "FULANO DE TESTE" in secoes[0]["html"]
    assert "possível homônimo" in secoes[1]["titulo"] and "DELTRANO SEM CPF" in secoes[1]["html"]


def test_rota_corpo_pronto_troca_quando_a_base_e_recalculada(base, monkeypatch):
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    import rotas.investigacao as RI
    app = FastAPI()
    app.include_router(RI.router)
    monkeypatch.setattr(RI, "_NC_CORPO", {})
    monkeypatch.setattr(RI, "_cache", {"nomcand:v2": (1.0, base)})
    monkeypatch.setattr(RI, "_cache_calc", lambda chave, ttl, f: RI._cache[chave][1])
    assert TestClient(app).get("/api/poder/nomeados_candidatos?esfera=todos").json()["total"] == 4
    menor = dict(base, pessoas=base["pessoas"][:1])
    RI._cache["nomcand:v2"] = (2.0, menor)                       # recalculada: geração nova
    assert TestClient(app).get("/api/poder/nomeados_candidatos?esfera=todos").json()["total"] == 1
