# -*- coding: utf-8 -*-
"""Dossiê 360 — o PDF deve renderizar TODOS os blocos que dossie() coleta (bug 2026-07-12:
o documento saía com 2 páginas ignorando cadastro/QSA/sanções/conflito/rede/mídia/links)."""
from compliance_agent.dossie import _ctx_dossie

_D = {
    "ok": True, "alvo": "03686998000118", "gerado_em": "2026-07-12T00:00:00",
    "cadastro": {
        "razao_social": "CENTRO DE PESQUISAS CPASC", "nome_fantasia": "CPASC",
        "situacao": "ATIVA", "data_abertura": "2000-01-01", "capital_social": 10000,
        "natureza_jur": "Associação Privada", "atividade": "Pesquisa social",
        "municipio": "RIO DE JANEIRO", "uf": "RJ",
        "socios": [{"nome": "FULANO DIRIGENTE", "qualificacao": "Presidente",
                    "data_entrada": "2025-05-14"}],
    },
    "sancoes": {"verificado": True, "sancionado": True,
                "sancoes": [{"tipo": "CEIS", "orgao": "CGU", "inicio": "2024-01-01"}]},
    "midia_adversa": {"ok": True, "n_total": 5, "n_adversos": 2, "adversos": [
        {"titulo": "Entidade investigada por desvio", "fonte": "jornal", "url": "http://x", "data": "2026-01-02"}]},
    "links_investigacao": [{"fonte": "RedeCNPJ", "categoria": "societário", "url": "http://y"}],
    "ob": {"total_ob": 208468555.26, "n_ob": 63, "n_ugs": 7, "concentracao_top_ug": 0.35,
           "ugs": [{"ug": "1", "nome": "Secretaria X", "total": 100.0}]},
    "conflito": {"n": 1, "rede": [{"doador": "FULANO DIRIGENTE", "candidato": "BELTRANO",
                                   "partido": "PXX", "ano": 2024, "valor_doacao": 5000.0,
                                   "total_ob": 1000000.0, "via": "direto", "sinais": ["nome_socio"]}]},
    "rede": {"n_nos": 81, "n_arestas": 90, "nos": [{"id": "03686998000118", "tipo": "empresa",
                                                    "rotulo": "CPASC"}]},
    "red_flags_estruturais": [{"flag": "troca_controle_pos_receita", "obs": "Ingresso no QSA..."}],
    "score": {"score": 47.7, "faixa": "ALTO", "contribuicoes": [{"flag": "conflito_doador",
                                                                 "contribuicao": 20}]},
}


def _html_total(ctx) -> str:
    return " ".join(s.get("html", "") + s.get("titulo", "") for s in ctx["secoes"]).lower()


def test_ctx_dossie_renderiza_todos_os_blocos():
    ctx = _ctx_dossie(_D)
    corpo = _html_total(ctx)
    # cadastro + QSA
    assert "cadastral" in corpo and "fulano dirigente" in corpo and "presidente" in corpo
    # sanções (CEIS detalhe) — doméstico
    assert "ceis" in corpo
    # conflito doador↔contrato com a linha da rede
    assert "beltrano" in corpo and "5.000,00" in corpo.replace("5,000.00", "5.000,00")
    # rede de poder
    assert "81" in corpo
    # mídia adversa com manchete
    assert "desvio" in corpo
    # pistas de investigação
    assert "redecnpj" in corpo
    # red flags estruturais preservadas
    assert "qsa" in corpo


def test_ctx_dossie_honesto_quando_indisponivel():
    d = dict(_D, sancoes={"verificado": False, "sancionado": None,
                          "_nota": "INDISPONÍVEL: sem chave"},
             midia_adversa={"ok": False, "erro": "rate-limit"}, links_investigacao=[],
             cadastro={"error": "HTTP 429"}, conflito={"n": 0, "rede": []},
             rede={"_nota": "INDISPONÍVEL: compliance.db ausente"})
    ctx = _ctx_dossie(d)
    corpo = _html_total(ctx)
    # INDISPONÍVEL declarado, nunca tratado como "limpo"
    assert "indispon" in corpo
    assert "limpo" not in corpo or "≠" in corpo or "nao e" in corpo or "não é" in corpo
