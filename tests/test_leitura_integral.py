# -*- coding: utf-8 -*-
"""Leitura integral comprovada — piloto (docs/PLANO-PLATAFORMA-EVIDENCIAS.md, Fase 1). Regras do dono (23/11/2026):
ler 100% do texto, nunca resumo de IA como substituto; fato só vale com citação literal conferida por código."""
import json

import pytest

from compliance_agent import leitura_integral as L


def _pasta(raiz, tag, docs):
    p = raiz / tag
    (p / "texto").mkdir(parents=True)
    man = []
    for i, (titulo, texto) in enumerate(docs):
        rel = f"texto/{i:03d}_x.txt"
        (p / rel).write_text(texto, encoding="utf-8")
        man.append({"i": i, "titulo": titulo, "tipo": "despacho", "texto": rel, "chars": len(texto)})
    (p / "manifest.json").write_text(json.dumps({"processo": tag.replace("_", "/"), "docs": man}), encoding="utf-8")
    return p


# ── fatiamento: 100% do texto, sem cortar documento quando cabe ─────────────────────────────────────────
def test_fatias_cobrem_todo_o_texto_sem_cortar_documento_que_cabe(tmp_path):
    p = _pasta(tmp_path, "100001_000001_2025", [("Contrato (11111111)", "A" * 300), ("Nota (22222222)", "B" * 300),
                                                 ("Atesto (33333333)", "C" * 300)])
    fatias, cob = L.fatiar(p, alvo=700)
    assert [[d["doc_id"] for d in f["docs"]] for f in fatias] == [["sei:11111111", "sei:22222222"], ["sei:33333333"]]
    assert cob == {"chars_existentes": 900, "chars_enviados": 900, "chars_tabela": 0, "docs_tabela": [], "fracao": 1.0,
                   "leitura": "integral"}


def test_documento_maior_que_a_fatia_e_dividido_com_sobreposicao_e_nada_se_perde(tmp_path):
    paragrafos = "\n\n".join(f"parágrafo {k} " + "x" * 90 for k in range(30))
    p = _pasta(tmp_path, "100001_000002_2025", [("Planilha de medição (44444444)", paragrafos)])
    fatias, cob = L.fatiar(p, alvo=1000, sobreposicao=100)
    assert len(fatias) > 1 and cob["leitura"] == "integral"
    juntado = "".join(f["docs"][0]["texto"] for f in fatias)
    for k in range(30):
        assert f"parágrafo {k} " in juntado


# ── máscara reversível: CPF e conta nunca saem da VM ───────────────────────────────────────────────────
def test_mascara_cpf_e_conta_e_desfaz_localmente():
    t = "Pague a João, CPF 123.456.789-09, Agência 1234-5 Conta corrente nº 98765-4. CNPJ 12.345.678/0001-90."
    m, mapa = L.mascarar(t)
    assert "123.456.789-09" not in m and "98765-4" not in m and "[CPF_1]" in m and "[CONTA_1]" in m
    assert "12.345.678/0001-90" in m                                        # CNPJ é público: não mascara
    assert L.desmascarar(m, mapa) == t


# ── verificador de citação ─────────────────────────────────────────────────────────────────────────────
TXT = "O valor global do contrato é de R$ 483.333,33 (quatrocentos…),\n  pago   em 12 parcelas."


def test_citacao_literal_aceita_espacos_diferentes_e_recusa_inventada():
    ok = {"tipo": "valor", "valor": "483333.33", "citacao": "valor global do contrato é de R$ 483.333,33", "doc_id": "d"}
    assert L.verificar(ok, {"d": TXT})["estado"] == "VERIFICADO"
    esp = dict(ok, tipo="quantidade", valor="12", citacao="pago em 12 parcelas")   # quebra de linha/espaços
    assert L.verificar(esp, {"d": TXT})["estado"] == "VERIFICADO"
    inventada = dict(ok, citacao="valor global de R$ 500.000,00")
    assert L.verificar(inventada, {"d": TXT})["estado"] == "INDISPONIVEL"
    valor_fora = dict(ok, valor="999.00")                                  # citação existe, valor não está nela
    assert L.verificar(valor_fora, {"d": TXT})["estado"] == "INDISPONIVEL"
    doc_errado = dict(ok, doc_id="outro")
    assert L.verificar(doc_errado, {"d": TXT})["estado"] == "INDISPONIVEL"


def test_resposta_do_modelo_vira_fatos_verificados_e_json_quebrado_nao_vira_fato():
    resp = json.dumps({"fatos": [{"tipo": "valor", "valor": "483333.33", "doc_id": "d",
                                  "citacao": "R$ 483.333,33"},
                                 {"tipo": "cnpj", "valor": "11.111.111/0001-11", "doc_id": "d",
                                  "citacao": "CNPJ 11.111.111/0001-11"}]})
    fatos = L.interpretar(resp, {"d": TXT})
    assert [f["estado"] for f in fatos] == ["VERIFICADO", "INDISPONIVEL"]
    assert L.interpretar("isto não é json", {"d": TXT}) is None             # resposta inválida ≠ "sem fatos"


# ── projeção de custo antes de gastar ──────────────────────────────────────────────────────────────────
def test_projecao_de_custo_usa_o_preco_do_lote_e_conta_todas_as_fatias():
    pj = L.projetar([{"texto": "x" * 25_000}, {"texto": "y" * 25_000}], saida_tokens=1000)
    assert pj["fatias"] == 2 and pj["tokens_entrada"] >= 20_000 and pj["usd"] > 0
    assert pj["usd"] == pytest.approx(pj["usd_sem_lote"] / 2)


def test_planilha_vai_para_o_leitor_por_codigo_e_continua_na_cobertura(tmp_path):
    planilha = "\n".join(f"{k} | 1.234,{k % 100:02d} | 0,00" for k in range(3000))
    p = _pasta(tmp_path, "100001_000003_2025", [("Despacho (55555555)", "Encaminhe-se o processo. " * 20),
                                                 ("Planilha orçamentária (66666666)", planilha)])
    fatias, cob = L.fatiar(p)
    assert [d["doc_id"] for f in fatias for d in f["docs"]] == ["sei:55555555"]
    assert cob["docs_tabela"] == ["sei:66666666"] and cob["chars_tabela"] == len(planilha)
    assert cob["chars_enviados"] + cob["chars_tabela"] == cob["chars_existentes"]
