# -*- coding: utf-8 -*-
"""Testa o progressive-disclosure do RAG do Hermes (tiers + gate de relevância).

Nugget canibalizado do claude-mem: índice barato (snippets) p/ a cauda + texto
completo só nos top, dentro do MESMO teto de chars. Ver ~/vault/aprendizados/claude-mem-veredito.md.
Não chama Cohere — monkeypatcha `consultar` (retrieval local).
"""
from tools import hermes_rag


def _hits(specs):
    return [{"score": s, "fonte": f, "texto": t} for s, f, t in specs]


def test_tiers_full_e_indice(monkeypatch):
    """Top-k_full viram texto completo; a cauda relevante entra como índice (snippet), não full."""
    curto = lambda nome: f"{nome} " + ("palavra " * 8)  # ~70 chars
    hits = _hits([
        (0.80, "~/a.md", curto("ALPHA")),
        (0.70, "~/b.md", curto("BRAVO")),
        (0.60, "~/c.md", curto("CHARLIE")),
        (0.50, "~/d.md", curto("DELTA")),
        (0.45, "~/e.md", curto("ECHO_CAUDA")),
        (0.40, "~/f.md", curto("FOXTROT_CAUDA")),
    ])
    monkeypatch.setattr(hermes_rag, "consultar", lambda p, k=6: hits[:k])
    out = hermes_rag.contexto("q", k=10, max_chars=4000, k_full=4, piso=0.28)
    assert out.count("[FONTE:") == 4                      # exatamente os 4 top em texto completo
    assert "OUTROS TRECHOS" in out                        # cauda vira seção de índice
    assert "ECHO_CAUDA" in out and "FOXTROT_CAUDA" in out  # cauda presente (como ponteiro)


def test_gate_de_relevancia_corta_ruido(monkeypatch):
    """Hit abaixo do piso de score é descartado (hoje entrava só porque 'cabia' no max_chars)."""
    hits = _hits([(0.80, "~/bom.md", "ALPHA conteudo util"),
                  (0.10, "~/ruido.md", "RUIDO irrelevante")])
    monkeypatch.setattr(hermes_rag, "consultar", lambda p, k=6: hits[:k])
    out = hermes_rag.contexto("q", piso=0.28)
    assert "ALPHA" in out
    assert "RUIDO" not in out


def test_nunca_vazio_com_hit_unico_fraco(monkeypatch):
    """Se o único hit está abaixo do piso, mantém o melhor (não retorna vazio)."""
    hits = _hits([(0.12, "~/fraco.md", "FRACO mas e o unico que ha")])
    monkeypatch.setattr(hermes_rag, "consultar", lambda p, k=6: hits[:k])
    out = hermes_rag.contexto("q", piso=0.28)
    assert "FRACO" in out


def test_budget_de_chars_respeitado(monkeypatch):
    """O teto de max_chars é respeitado mesmo com chunks longos (economia de token)."""
    longo = "X" * 1500
    hits = _hits([(0.9 - i * 0.05, f"~/{i}.md", f"DOC{i} {longo}") for i in range(10)])
    monkeypatch.setattr(hermes_rag, "consultar", lambda p, k=6: hits[:k])
    out = hermes_rag.contexto("q", k=10, max_chars=3000)
    assert len(out) <= 3000


def test_sem_hits_retorna_vazio(monkeypatch):
    monkeypatch.setattr(hermes_rag, "consultar", lambda p, k=6: [])
    assert hermes_rag.contexto("q") == ""
