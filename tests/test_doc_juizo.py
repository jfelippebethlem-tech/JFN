# -*- coding: utf-8 -*-
"""doc_juizo — seleção/teto puro, trecho literal obrigatório, cache, teto de grau C."""
import json

from compliance_agent.sei import doc_juizo


def _man(n_despachos=3):
    docs = [
        {"i": 0, "titulo": "Justificativa de Dispensa Emergencial (1)", "fase": "selecao",
         "tipo": "contratacao_direta", "texto": "texto/000.txt"},
        {"i": 1, "titulo": "Parecer PGE (2)", "fase": "controle", "tipo": "parecer",
         "texto": "texto/001.txt"},
        {"i": 2, "titulo": "Homologação (3)", "fase": "selecao", "tipo": "homologacao",
         "texto": "texto/002.txt"},
        {"i": 3, "titulo": "Atestado de Execução (4)", "fase": "execucao", "tipo": "aceite",
         "texto": "texto/003.txt"},
    ]
    for k in range(n_despachos):
        docs.append({"i": 4 + k, "titulo": f"Despacho {k} (9{k})", "fase": "tramitacao",
                     "tipo": "despacho", "texto": f"texto/{4 + k:03d}.txt"})
    return {"processo": "SEI-1", "docs": docs}


def _pasta(tmp_path, man):
    (tmp_path / "texto").mkdir()
    for d in man["docs"]:
        (tmp_path / d["texto"]).write_text(
            f"Documento {d['titulo']}. A contratação decorre de risco iminente documentado.",
            encoding="utf-8")
    return tmp_path


def test_selecao_prioriza_e_corta():
    sel = doc_juizo.selecionar(_man(n_despachos=30)["docs"], teto=5)
    assert len(sel) == 5
    assert sel[0]["tipo"] == "contratacao_direta"       # prioridade 1
    assert sel[1]["tipo"] == "parecer"


def test_trecho_inexistente_vira_null(tmp_path):
    man = _man()
    pasta = _pasta(tmp_path, man)
    resposta = json.dumps({"escala": 3, "trecho_literal": "TRECHO QUE NÃO EXISTE NO DOC",
                           "justificativa_curta": "x"})
    out = doc_juizo.julgar_docs(man, pasta, teto=2, gerar=lambda p, s="": resposta, con=None)
    for v in out["vereditos"]:
        assert v["escala"] is None                       # guarda-corpo: sem trecho real, sem juízo
        assert "trecho" in (v.get("aviso") or "")


def test_trecho_real_confirma_e_grau_teto_c(tmp_path):
    man = _man()
    pasta = _pasta(tmp_path, man)
    resposta = json.dumps({"escala": 3, "trecho_literal": "risco iminente documentado",
                           "justificativa_curta": "nexo genérico"})
    out = doc_juizo.julgar_docs(man, pasta, teto=1, gerar=lambda p, s="": resposta, con=None)
    v = out["vereditos"][0]
    assert v["escala"] == 3
    assert v["grau"]["grau"] in ("C", "D")               # LLM sozinho nunca passa de C


def test_gerar_vazio_degrada_honesto(tmp_path):
    man = _man()
    pasta = _pasta(tmp_path, man)
    out = doc_juizo.julgar_docs(man, pasta, teto=2, gerar=lambda p, s="": "", con=None)
    assert all(v["escala"] is None for v in out["vereditos"])
    assert out["cobertura"]["sem_resposta"] == 2


def test_cache_evita_rechamada(tmp_path):
    import sqlite3
    man = _man()
    pasta = _pasta(tmp_path, man)
    con = sqlite3.connect(":memory:")
    chamadas = {"n": 0}

    def gerar(p, s=""):
        chamadas["n"] += 1
        return json.dumps({"escala": 2, "trecho_literal": "risco iminente documentado",
                           "justificativa_curta": "ok"})
    doc_juizo.julgar_docs(man, pasta, teto=2, gerar=gerar, con=con)
    n1 = chamadas["n"]
    doc_juizo.julgar_docs(man, pasta, teto=2, gerar=gerar, con=con)
    assert chamadas["n"] == n1                           # 2ª rodada 100% cache
