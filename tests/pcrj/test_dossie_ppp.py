# -*- coding: utf-8 -*-
"""Testes do dossiê de PPP (``pcrj/dossie_ppp.py``) — foco nos bugs achados testando a base real."""
from compliance_agent.pcrj import db, dossie_ppp


def test_chaves_projeto_deriva_ultimas_palavras():
    ch = dossie_ppp._chaves_projeto("Complexo Hospitalar Souza Aguiar")
    assert "Complexo Hospitalar Souza Aguiar" in ch
    assert "Souza Aguiar" in ch  # variantes ('...Municipal Souza Aguiar') são pegas


def test_contraprestacao_pega_valor_frequente_ignora_pequeno():
    """Número errado é pior que INDISPONÍVEL: pega o valor ≥1M mais frequente, não o 1º pequeno."""
    acts = [{"texto": "GARANTIA R$ 40.000,00. Concessionária SMART HOSPITAL S.A. Smart Hospital "
                       "113.119.337,85 191.773.351,61 191.773.351,61 191.773.351,61", "processos": "[]"}]
    r = dossie_ppp._extrair_resultado(acts)
    assert r["vencedor"] == "SMART HOSPITAL S.A"
    assert r["contraprestacao"] == "191.773.351,61"  # não 40.000,00


def test_contraprestacao_indisponivel_sem_valor_grande():
    acts = [{"texto": "Concessionária X S.A. taxa de R$ 500,00 devida.", "processos": "[]"}]
    r = dossie_ppp._extrair_resultado(acts)
    assert r["contraprestacao"] is None  # nada ≥1M → INDISPONÍVEL, nunca chuta


def test_slug_desconhecido_nao_contamina(tmp_path):
    """Projeto inexistente NÃO pode puxar atos de outro (era hardcode Souza Aguiar/Smart Hospital)."""
    p = tmp_path / "pcrj.db"
    db.inicializar(p)
    con = db.conectar(p)
    con.execute("INSERT INTO pcrj_doe_materia (id_materia,ano,tipo,processos,texto,coletado_em) "
                "VALUES (?,?,?,?,?,?)",
                ("x_1", 2023, "ppp", "[]", "Contrato de PPP do Complexo Souza Aguiar, Smart Hospital.", "2026-07-15"))
    con.commit(); con.close()
    ctx = dossie_ppp.montar_dossie("projeto-inexistente-abc", db_path=p)
    assert ctx["_dados"]["n_atos_do"] == 0
    assert ctx["score"] == 0.0
