# -*- coding: utf-8 -*-
"""Task 4.4 — narrativa de certame por LLM com rubrica-judge (mock de `gerar`, nunca LLM real).

Cenário-base replica o "DUAS famílias" do test_indice_certame: inexigibilidade (transparencia
1.0) + fantasma 50/100 (fraude_cadastral 0.5) → score determinístico 70/100, drivers nas duas
famílias. Cláusula de capital 30% em edital_clausula fornece o trecho citável verbatim.
"""
import json
import sqlite3

import pytest

from compliance_agent.editais.db import init_schema
from compliance_agent.editais.narrativa_certame import (
    ALPHA,
    LIMITE_PROMPT,
    narrar,
    narrar_e_persistir,
    parse_rubrica,
)

CERTAME = "NARR-1-000001/2026"
VENC = "11111111000191"
TRECHO_CLAUSULA = ("Exige-se capital social minimo de 30% do valor estimado da contratacao, "
                   "vedado o somatorio de atestados.")

PNCP_DDL = """CREATE TABLE pncp_resultado (
    certame TEXT, orgao_cnpj TEXT, orgao_nome TEXT, uf TEXT, municipio TEXT,
    modalidade INTEGER, objeto TEXT, data_pub TEXT, item INTEGER,
    fornecedor_cnpj TEXT, fornecedor_nome TEXT, valor_homologado REAL,
    ordem_classificacao INTEGER, porte_fornecedor TEXT, coletado_em TEXT,
    unidade_codigo TEXT, unidade_nome TEXT, item_descricao TEXT,
    unidade_medida TEXT, valor_unitario REAL, quantidade REAL)"""
FANTASMA_DDL = """CREATE TABLE fantasma_score (
    cnpj TEXT PRIMARY KEY, razao_social TEXT, score INTEGER, classificacao TEXT,
    sinais_json TEXT, origem TEXT, avaliado_em TEXT)"""


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    init_schema(con)  # edital_documento, edital_clausula, clausula_veredito, certame_indice
    con.execute(PNCP_DDL)
    con.execute(FANTASMA_DDL)
    con.execute("INSERT INTO pncp_resultado (certame, modalidade, data_pub, item, "
                "fornecedor_cnpj, valor_homologado, ordem_classificacao, item_descricao, "
                "valor_unitario, quantidade) VALUES (?,9,'2026-01-10',1,?,500000,1,"
                "'servico exotico xpto',100,1)", (CERTAME, VENC))
    con.execute("INSERT INTO fantasma_score (cnpj, score, classificacao) VALUES (?, 50, 'medio')",
                (VENC,))
    con.execute("INSERT INTO edital_documento (numero_controle_pncp, objeto) VALUES (?, 'xpto')",
                (CERTAME,))
    con.execute("INSERT INTO edital_clausula (numero_controle_pncp, subtipo, texto) "
                "VALUES (?, 'capital_patrimonio', ?)", (CERTAME, TRECHO_CLAUSULA))
    con.commit()
    yield p, con
    con.close()


def _rubrica_valida() -> str:
    return json.dumps({
        "d1": {"nota": 3, "citacao": TRECHO_CLAUSULA[:60],
               "justificativa": "capital de 30% excede em 3x o teto da Sumula TCU 275"},
        "d2": {"nota": 4, "citacao": TRECHO_CLAUSULA[:40],
               "justificativa": "inexigibilidade sem motivacao visivel nos autos"},
        "d3": None, "d4": None, "d5": None, "d6": None,
        "tese": "Contratacao direta (transparencia) com exigencia de capital acima do teto "
                "e vencedor com sinais cadastrais (fraude_cadastral).",
        "ressalvas": ["indicio a apurar, nao acusacao"],
    })


# ──────────────── 1. rubrica válida → llm, tese cita driver, α ≤ 0,3, teto 1,0 ────────────────
def test_rubrica_valida_llm(db):
    p, _ = db
    prompts = []

    def gerar(prompt):
        prompts.append(prompt)
        return _rubrica_valida()

    r = narrar(CERTAME, p, gerar=gerar)
    assert r["origem"] == "llm" and r["prompt_versao"] == "v1"
    # tese cita ≥1 driver determinístico (transparencia/fraude_cadastral)
    fams = {d["familia"] for d in r["drivers"]}
    assert any(f in r["tese"].lower() for f in fams)
    # α ≤ 0,3 sobre score normalizado 0-1, teto 1,0: det=0.70, média=(3+4)/2=3.5 → +0.2625
    assert r["score_det"] == pytest.approx(0.70, abs=0.001)
    assert r["score_final"] <= r["score_det"] + ALPHA + 1e-9
    assert r["score_final"] <= 1.0
    assert r["score_final"] == pytest.approx(min(1.0, 0.70 + ALPHA * (3.5 / 4)), abs=0.001)
    assert r["alpha_aplicado"] == ALPHA
    assert len(r["citacoes"]) == 2 and r["rubrica_crua"] == _rubrica_valida()
    # prompt: < 8000 chars, norma injetada, driver e trecho da cláusula presentes
    prompt = prompts[0]
    assert len(prompt) < LIMITE_PROMPT
    assert "Súmula TCU 263" in prompt and "Súmula TCU 275" in prompt
    assert "inexigibilidade" in prompt          # evidência do driver de transparencia
    assert TRECHO_CLAUSULA[:60] in prompt       # trecho de edital_clausula recortado


# ──────────────── 2. dimensão com nota mas SEM citação → nota None ────────────────
def test_nota_sem_citacao_vira_none(db):
    p, _ = db
    txt = json.dumps({
        "d1": {"nota": 4, "citacao": "", "justificativa": "sem ancora textual"},
        "d2": {"nota": 2, "citacao": "   ", "justificativa": "citacao vazia"},
        "d3": None, "d4": None, "d5": None, "d6": None,
        "tese": "tese sem lastro por transparencia", "ressalvas": [],
    })
    rub = parse_rubrica(txt)
    assert rub is not None
    assert rub["d1"]["nota"] is None and rub["d2"]["nota"] is None
    # em narrar: nenhuma dimensão avaliável → α não aplicado, score_final = score_det
    r = narrar(CERTAME, p, gerar=lambda _: txt)
    assert r["origem"] == "llm" and r["alpha_aplicado"] == 0.0
    assert r["score_final"] == r["score_det"] and r["citacoes"] == []


# ──────────────── 3. JSON malformado → template determinístico ────────────────
def test_json_malformado_template(db):
    p, _ = db
    assert parse_rubrica("nao sou json { d1: quebrado") is None
    assert parse_rubrica(json.dumps({"d1": None, "ressalvas": []})) is None  # sem tese
    r = narrar(CERTAME, p, gerar=lambda _: "nao sou json { d1: quebrado")
    assert r["origem"] == "template" and r["rubrica"] is None
    assert CERTAME in r["tese"] and "evidências:" in r["tese"]
    assert any(d["familia"] in r["tese"] for d in r["drivers"])  # tese montada dos drivers
    assert r["alpha_aplicado"] == 0.0 and r["score_final"] == r["score_det"]


# ──────────────── 4. gerar=None + cérebro indisponível → template, não exceção ────────────────
def test_cerebro_indisponivel_template(db, monkeypatch):
    p, _ = db

    def boom(prompt, *a, **k):
        raise RuntimeError("nenhum LLM respondeu (ou em cooldown)")

    monkeypatch.setattr("compliance_agent.direcionamento_cerebro.gerar_sync", boom)
    r = narrar(CERTAME, p, gerar=None)   # não pode levantar exceção
    assert r["origem"] == "template"
    assert r["score_final"] == r["score_det"] == pytest.approx(0.70, abs=0.001)


# ──────────────── persistência opcional: certame_indice.narrativa_json ────────────────
def test_narrar_e_persistir(db):
    p, con = db
    r = narrar_e_persistir(CERTAME, p, gerar=lambda _: _rubrica_valida())
    row = con.execute("SELECT narrativa_json FROM certame_indice WHERE certame=?",
                      (CERTAME,)).fetchone()
    assert row is not None and row[0]
    js = json.loads(row[0])
    assert js["prompt_versao"] == "v1" and js["origem"] == "llm"
    assert js["score_final"] == r["score_final"]
    # idempotente (ALTER aditivo + UPDATE): segunda rodada não duplica nem quebra
    narrar_e_persistir(CERTAME, p, gerar=lambda _: "quebrado")
    n = con.execute("SELECT COUNT(*) FROM certame_indice WHERE certame=?", (CERTAME,)).fetchone()[0]
    assert n == 1
    assert json.loads(con.execute("SELECT narrativa_json FROM certame_indice WHERE certame=?",
                                  (CERTAME,)).fetchone()[0])["origem"] == "template"
