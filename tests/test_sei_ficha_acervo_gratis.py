# -*- coding: utf-8 -*-
"""Coleta GRÁTIS da ficha do acervo (22/11/2026, bancada em ~/.local/state/jfn-bancada-ficha-20261122/).

Regras do dono que estes testes travam: grátis só COLETA (o juízo sai da ficha grátis); a ficha grátis só vale se
NADA do que ela afirma com número/CNPJ/data/citação for inventado — senão o processo vai ao Haiku, como se o grátis
não existisse; grátis que não responde → Haiku; desligável por env; Gemini só nas chaves com prova FreeTier;
OpenRouter só `:free`."""
import json
import sqlite3

import pytest

from tools import sei_ficha_acervo as A

FONTE = ("=== DOCUMENTO: Contrato 12/2025 ===\n"
         "Contratada: ALFA SERVIÇOS LTDA, CNPJ 12.345.678/0001-90, valor global de R$ 1.234.567,89, "
         "assinado em 03/02/2025 pela Secretaria de Estado de Saúde. Pregão Eletrônico 45/2024. "
         "Valor por extenso: um milhão duzentos e trinta e qua- tro mil reais.\n"
         "=== DOCUMENTO: Parecer ===\nOpina pela legalidade com fundamento no art. 75 da Lei 14.133/2021.")

BOA = {
    "objeto": "Serviços de limpeza", "modalidade": "pregão eletrônico", "fundamento_legal": "art. 75 da Lei 14.133/2021",
    "valores": ["R$ 1.234.567,89 (valor global)"], "cnpjs": ["12.345.678/0001-90"], "datas": ["03/02/2025"],
    "partes": ["ALFA SERVIÇOS LTDA", "Secretaria de Saúde (contratante)"],
    "documentos": [{"tipo": "contrato", "ponto": "valor global de R$ 1.234.567,89", "doc_ref": "Contrato 12/2025",
                    "trecho": "valor global de R$ 1.234.567,89"},
                   # OCR corrigido pelo modelo ("qua- tro" → "quatro"): a produção descarta, mas NÃO é invenção
                   {"tipo": "contrato", "ponto": "extenso", "doc_ref": "Contrato 12/2025",
                    "trecho": "um milhão duzentos e trinta e quatro mil reais"}],
    "situacao": "em andamento", "resumo": "Contrato de R$ 1.234.567,89 com a ALFA.",
    # juízo — o grátis não o produz na ficha
    "analise": "Chama atenção o valor.", "nivel_risco": "alto", "relevante": True,
    "red_flags": ['[Doc: Parecer — "Opina pela legalidade"] dispensa'],
    "pericia_contabil": {"achados": ["x"], "verificar": [], "conclusao": "c"},
    "pericia_juridica": {"achados": ["y"], "verificar": [], "conclusao": "c"}, "duvidas": ["d"],
}


def _com(**k):
    return dict(BOA, **k)


def test_ficha_boa_nao_tem_grave_e_o_ocr_corrigido_nao_e_invencao():
    assert A.graves_coleta(BOA, FONTE) == []


@pytest.mark.parametrize("campo,valor", [
    ("valores", ["R$ 9.999.999,99"]),                                   # valor inventado
    ("cnpjs", ["99.999.999/0001-99"]),                                  # CNPJ inventado
    ("datas", ["31/12/2025 (vigência)"]),                               # data inventada
    ("documentos", [{"tipo": "ata", "ponto": "p", "doc_ref": "Ata de Registro de Preços 7/2024",
                     "trecho": "registro de preços"}]),                 # documento que não é peça do processo
    ("documentos", [{"tipo": "nf", "ponto": "p", "doc_ref": "Contrato 12/2025",
                     "trecho": "Nota fiscal 88123 no valor de R$ 50.000,00"}]),   # citação com número inventado
    ("fundamento_legal", "art. 74, III, da Lei 8.666/93"),              # dispositivo ausente do texto
    ("resumo", "Pago R$ 777.777,77 à ALFA."),                           # fato sem fonte no texto corrido
])
def test_um_item_inventado_e_grave(campo, valor):
    assert A.graves_coleta(_com(**{campo: valor}), FONTE)


def test_item_sem_nucleo_conferivel_nao_e_grave():
    """'Jun/2025' e parte com nome parafraseado: a conferência descarta, mas o código não decide — sem juízo."""
    assert A.graves_coleta(_com(datas=["Jun/2025"], partes=["Empresa Alfa"]), FONTE) == []


def test_coleta_gratis_tira_o_juizo_e_a_situacao_nao_declarada():
    f = A.coleta_gratis(BOA, FONTE)
    assert f["analise"] == "" and f["red_flags"] == [] and f["pericia_contabil"] == "" and f["pericia_juridica"] == ""
    assert f["duvidas"] == [] and f["relevante"] is False and f["nivel_risco"] == ""
    assert f["situacao"] == ""                                    # o texto não DECLARA o andamento
    assert A.coleta_gratis(_com(situacao="arquivado"), FONTE + "\nArquive-se o processo.")["situacao"] == "arquivado"
    assert f["valores"] == BOA["valores"] and f["documentos"] == BOA["documentos"]


def test_consenso_une_os_itens_e_um_grave_manda_ao_haiku(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "fonte_de_conferencia", lambda pasta, janela: janela)
    monkeypatch.setattr(A, "RECUSAS", tmp_path / "recusas.jsonl")
    a = _com(valores=["R$ 1.234.567,89"], datas=[])
    b = _com(valores=["1.234.567,89 (valor global)"], datas=["03/02/2025 (assinatura)"], objeto="")
    ger = [("m1", lambda s, p: json.dumps(a)), ("m2", lambda s, p: json.dumps(b))]
    ok, verif, modelo = A.ficha_gratis(tmp_path, "s", "p", FONTE, ger)
    assert modelo == "m1+m2" and verif["consenso"] == ["m1", "m2"]
    assert ok["valores"] == ["R$ 1.234.567,89"]                    # o mesmo valor nas duas grafias entra uma vez
    assert ok["datas"] == ["03/02/2025 (assinatura)"]              # o que só o 2º achou entra
    assert ok["objeto"] == "Serviços de limpeza" and ok["red_flags"] == []
    inventa = _com(cnpjs=["99.999.999/0001-99"])
    assert A.ficha_gratis(tmp_path, "s", "p", FONTE, [ger[0], ("m3", lambda s, p: json.dumps(inventa))]) is None
    assert A.ficha_gratis(tmp_path, "s", "p", FONTE, [ger[0], ("m4", lambda s, p: "")]) is None   # um calou


def test_cadeia_desliga_por_env_e_recusa_pago(monkeypatch):
    monkeypatch.setenv("JFN_FICHA_GRATIS", "0")
    assert A.cadeia_gratis() == []
    monkeypatch.delenv("JFN_FICHA_GRATIS")
    assert A.cadeia_gratis() == [("gem", "gemini-3.5-flash-lite"), ("or", "particle-ai/particle-1:free")]
    monkeypatch.setenv("JFN_FICHA_GRATIS", "or:particle-ai/particle-1,gem:gemini-3.5-flash-lite,xx:modelo")
    assert A.cadeia_gratis() == [("gem", "gemini-3.5-flash-lite")]   # OpenRouter sem :free e provedor estranho fora


def test_gemini_so_nas_chaves_com_prova_free_tier(monkeypatch, tmp_path):
    import hashlib
    prova = tmp_path / "prova.json"
    k_ok, k_sem = "chave-com-prova", "chave-sem-prova"
    prova.write_text(json.dumps({"kids": [hashlib.sha1(k_ok.encode()).hexdigest()[:6]]}), encoding="utf-8")
    monkeypatch.setattr(A, "PROVA_FREE_TIER", prova)
    monkeypatch.setattr("compliance_agent.direcionamento_cerebro._gemini_keys", lambda: [k_sem, k_ok])
    assert A._chaves_gemini_free() == [k_ok]
    prova.unlink()
    assert A._chaves_gemini_free() == []                           # sem prova lida = nenhuma chave (nunca todas)


def _banco(tmp_path):
    con = sqlite3.connect(tmp_path / "c.db")
    con.execute("CREATE TABLE sei_ficha (numero_sei TEXT PRIMARY KEY, objeto TEXT, modalidade TEXT, "
                "fundamento_legal TEXT, resumo TEXT, analise TEXT, nivel_risco TEXT, relevante INTEGER, valores TEXT, "
                "cnpjs TEXT, partes TEXT, datas TEXT, red_flags TEXT, documentos TEXT, n_docs INTEGER, "
                "fonte_modelo TEXT, cached_at TEXT, atualizado_em TEXT, situacao TEXT, pericia_contabil TEXT, "
                "pericia_juridica TEXT)")
    con.commit()
    con.close()
    return tmp_path / "c.db"


def test_enviar_grava_a_ficha_gratis_limpa_e_manda_o_resto_ao_haiku(monkeypatch, tmp_path):
    db = _banco(tmp_path)
    monkeypatch.setattr(A, "DB", db)
    monkeypatch.setattr(A, "ESTADO", tmp_path / "estado.json")
    monkeypatch.setattr(A, "ACERVO", tmp_path)
    monkeypatch.setattr(A, "MIN_TEXTO", 10)
    monkeypatch.setattr(A, "RECUSAS", tmp_path / "recusas.jsonl")
    cands = [{"pasta": p, "numero": f"SEI-{p.replace('_', '/')}", "pago": 0.0, "bytes": 999}
             for p in ("030001_000001_2025", "030001_000002_2025", "030001_000003_2025")]
    for c in cands:
        (tmp_path / c["pasta"]).mkdir()
    monkeypatch.setattr(A, "fila", lambda con, estado: cands)
    monkeypatch.setattr(A, "texto_para_ficha", lambda pasta: (FONTE + f"\n[{pasta.name}]", {"chars": len(FONTE)}))
    monkeypatch.setattr(A, "fonte_de_conferencia", lambda pasta, janela: janela)
    respostas = {"000001": json.dumps(BOA, ensure_ascii=False),                             # limpa → grátis
                 "000002": json.dumps(_com(valores=["R$ 9.999.999,99"]), ensure_ascii=False),  # grave → Haiku
                 "000003": ""}                                                                 # não respondeu → Haiku

    def gerar(sistema, prompt):
        return next(v for k, v in respostas.items() if f"030001_{k}_2025" in prompt)
    monkeypatch.setattr(A, "_gerar_gratis", lambda prov, modelo: gerar)
    from compliance_agent.llm import claude_api as C
    enviados = {}
    monkeypatch.setattr(C, "registrar_restantes", lambda *a, **k: None)
    monkeypatch.setattr(C, "enviar_lote", lambda tarefa, itens, **k: enviados.update(itens=itens) or "lote_x")
    monkeypatch.setenv("JFN_FICHA_GRATIS", "gem:gemini-3.5-flash-lite")
    r = A.enviar(A._ler_estado(), 10)
    assert [cid for cid, _ in enviados["itens"]] == ["030001_000002_2025", "030001_000003_2025"]
    assert r["gratis"]["gravadas"] == 1 and r["gratis"]["ao_haiku"] == 2 and r["enviados"] == 2
    con = sqlite3.connect(db)
    fm, v, rf, an = con.execute("SELECT fonte_modelo, verificacao, red_flags, analise FROM sei_ficha").fetchone()
    assert con.execute("SELECT COUNT(*) FROM sei_ficha").fetchone()[0] == 1
    assert fm == "gemini-3.5-flash-lite@gratis#acervo-v2-coleta" and "#acervo-" in fm
    assert json.loads(rf) == [] and an == "" and json.loads(v)["juizo"].startswith("fora")
    recusas = [json.loads(x) for x in (tmp_path / "recusas.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["pasta"] for r in recusas] == ["030001_000002_2025"]          # o grave fica para a automelhoria
    assert "9.999.999,99" in recusas[0]["tentativas"][0]["graves"][0]


def test_enviar_sem_cadeia_vai_tudo_ao_haiku(monkeypatch, tmp_path):
    db = _banco(tmp_path)
    monkeypatch.setattr(A, "DB", db)
    monkeypatch.setattr(A, "ESTADO", tmp_path / "estado.json")
    monkeypatch.setattr(A, "ACERVO", tmp_path)
    monkeypatch.setattr(A, "MIN_TEXTO", 10)
    monkeypatch.setattr(A, "RECUSAS", tmp_path / "recusas.jsonl")
    (tmp_path / "030001_000001_2025").mkdir()
    monkeypatch.setattr(A, "fila", lambda con, estado: [{"pasta": "030001_000001_2025", "numero": "x", "pago": 0.0}])
    monkeypatch.setattr(A, "texto_para_ficha", lambda pasta: (FONTE, {}))
    monkeypatch.setattr(A, "_gerar_gratis", lambda prov, modelo: pytest.fail("grátis chamado com a cadeia desligada"))
    from compliance_agent.llm import claude_api as C
    enviados = {}
    monkeypatch.setattr(C, "registrar_restantes", lambda *a, **k: None)
    monkeypatch.setattr(C, "enviar_lote", lambda tarefa, itens, **k: enviados.update(itens=itens) or "lote_x")
    monkeypatch.setenv("JFN_FICHA_GRATIS", "0")
    r = A.enviar(A._ler_estado(), 10)
    assert r["enviados"] == 1 and len(enviados["itens"]) == 1
