# -*- coding: utf-8 -*-
"""Fracionamento é por OBJETO (art. 75 §1º, Lei 14.133/2021), não por fornecedor.

Pedido do dono (19/11/2026): "não se trata da mesma empresa e sim do mesmo objeto ser fracionado".
Controles positivo e negativo do sweep (tools/sweep_fracionamento_tcerj.py) e da tela
(compliance_agent/fracionamento_objeto.py). Limite 2024, compras (art. 75, II): R$ 59.906,02.
Jurisprudência que os casos espelham (TCU, base oficial em data/tcu_juris.db):
  · 3.550/2008-1ª Câm. — somatório do exercício da mesma despesa acima do teto veda a dispensa;
  · 706/2007-1ª Câm. — aquisições frequentes do mesmo produto em processos distintos;
  · 2.195/2008-1ª Câm. (agrupar por natureza) e 1.540/2014-Plen. (objetos distintos e independentes não se somam).
"""
from __future__ import annotations

import json
import sqlite3

from compliance_agent import objeto_similaridade as OS
from compliance_agent.fracionamento_objeto import fracionamento_por_objeto
from tools.sweep_fracionamento_tcerj import _tipo_obj, carregar_grupos, ligar_ob_siafe, rodar_sweep


def _db(tmp_path, rows, ob=None):
    db = tmp_path / "f.db"
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE compras_diretas_tcerj (
        id TEXT, processo TEXT, sei_norm TEXT, ano_processo INT, valor REAL, objeto TEXT,
        afastamento TEXT, enquadramento_legal TEXT, unidade TEXT, fornecedor TEXT,
        item TEXT, quantidade REAL, valor_unitario REAL, ingerido_em TEXT)""")
    con.executemany("INSERT INTO compras_diretas_tcerj (processo, ano_processo, valor, objeto, afastamento, unidade,"
                    " fornecedor) VALUES (?,?,?,?,?,?,?)", rows)
    con.execute("""CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, status TEXT, status_envio TEXT,
        tipo_regularizacao TEXT, processo TEXT, credor TEXT, nome_credor TEXT, valor REAL, data_emissao TEXT)""")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?)", ob or [])
    con.commit()
    con.close()
    return db


_D = "Dispensa de Licitação"


def test_positivo_mesmo_objeto_fornecedores_diferentes_acende(tmp_path):
    """Coffee break picado em 3 dispensas, 3 empresas DIFERENTES, soma R$ 172.300 > R$ 59.906,02."""
    db = _db(tmp_path, [
        ("SEI-1/001/2024", 2024, 59_500.0, "serviço de alimentação para fornecimento de coffee break", _D, "UG A", "BUFFET UM"),
        ("SEI-1/002/2024", 2024, 58_800.0, "fornecimento de coffee break e brunch para evento", _D, "UG A", "BUFFET DOIS"),
        ("SEI-1/003/2024", 2024, 54_000.0, "coffee break e almoço para seminário", _D, "UG A", "RESTAURANTE TRES"),
    ])
    achados = rodar_sweep(carregar_grupos(db_path=db))
    assert len(achados) == 1
    a = achados[0]
    assert a["soma_acima_do_teto"] is True
    assert a["n_fornecedores_distintos"] == 3            # o fornecedor NÃO é o critério
    assert a["natureza"] == "alimentacao" and a["criterio_natureza"] == "ramo_de_atividade"
    assert {c["processo"] for c in a["contratacoes"]} == {"SEI-1/001/2024", "SEI-1/002/2024", "SEI-1/003/2024"}


def test_negativo_mesma_empresa_objetos_distintos_nao_acende(tmp_path):
    """Uma empresa só, três objetos de ramos distintos somando acima do teto: NÃO é fracionamento."""
    db = _db(tmp_path, [
        ("SEI-2/001/2024", 2024, 50_000.0, "aquisição de combustível gasolina", _D, "UG B", "COMERCIAL X"),
        ("SEI-2/002/2024", 2024, 45_000.0, "aquisição de cadeiras e mobiliário", _D, "UG B", "COMERCIAL X"),
        ("SEI-2/003/2024", 2024, 40_000.0, "impressão de banners e material gráfico", _D, "UG B", "COMERCIAL X"),
    ])
    assert [a for a in rodar_sweep(carregar_grupos(db_path=db)) if a["soma_acima_do_teto"]] == []


def test_negativo_objetos_distintos_somando_acima_do_teto_nao_acende(tmp_path):
    db = _db(tmp_path, [
        ("SEI-3/001/2024", 2024, 50_000.0, "aquisição de medicamentos", _D, "UG C", "FARMA"),
        ("SEI-3/002/2024", 2024, 50_000.0, "aquisição de notebooks", _D, "UG C", "INFO"),
        ("SEI-3/003/2024", 2024, 50_000.0, "serviço de vigilância patrimonial", _D, "UG C", "SEGURA"),
    ])
    assert rodar_sweep(carregar_grupos(db_path=db)) == []


def test_ramo_nao_faz_ponte_transitiva_pelo_objeto_sem_ramo(monkeypatch):
    """Dado real SEDSODH 2024: coffee break ~ 'objeto sem ramo' ~ material gráfico (textos parecidos) virava UMA
    natureza pelo union-find. Ramos fixados por stub para isolar a regra da ponte."""
    lote = [{"objeto": "serviço para o seminário regional de direitos humanos itens A"},
            {"objeto": "serviço para o seminário regional de direitos humanos itens B"},
            {"objeto": "serviço para o seminário regional de direitos humanos itens C"}]
    ramos = {"A": "alimentacao", "B": None, "C": "grafica"}
    monkeypatch.setattr(OS, "ramo_atividade", lambda o: ramos[o[-1]])
    assert OS.agrupar(lote, por_ramo=False) == [[0, 1, 2]]       # o texto, sozinho, juntaria os três
    assert OS.agrupar(lote, por_ramo=True) == [[0], [1], [2]]    # com ramo, nenhuma ponte


def test_negativo_credenciamento_e_inscricao_nao_somam(tmp_path):
    db = _db(tmp_path, [
        ("SEI-4/001/2024", 2024, 40_000.0, "chamada pública para credenciamento de oficineiros", _D, "UG D", "P1"),
        ("SEI-4/002/2024", 2024, 40_000.0, "chamada pública para credenciamento de oficineiros", _D, "UG D", "P2"),
        ("SEI-4/003/2024", 2024, 30_000.0, "inscrição de servidores em congresso", _D, "UG D", "ASSOC"),
        ("SEI-4/004/2024", 2024, 30_000.0, "inscrição de servidores em congresso nacional", _D, "UG D", "ASSOC2"),
    ])
    assert rodar_sweep(carregar_grupos(db_path=db)) == []


def test_processo_irmao_de_sufixo_com_mesmo_valor_conta_uma_vez(tmp_path):
    """000778 × 000778A, mesmo valor, outro fornecedor: um registro só (soma não dobra)."""
    db = _db(tmp_path, [
        ("SEI-5/000778/2024", 2024, 40_000.0, "fornecimento de coffee break", _D, "UG E", "BUFFET A"),
        ("SEI-5/000778A/2024", 2024, 40_000.0, "fornecimento de coffee break", _D, "UG E", "BUFFET B"),
    ])
    assert len(carregar_grupos(db_path=db)[("UG E", 2024)]) == 1


def test_mesmo_processo_com_grafias_diferentes_conta_uma_vez(tmp_path):
    db = _db(tmp_path, [
        ("SEI 310001/001411/2024", 2024, 58_300.0, "locação de palco e sonorização", _D, "UG F", "PROD"),
        ("SEI-310001/001411/2024", 2024, 58_300.0, "locação de palco e sonorização", _D, "UG F", "PROD"),
    ])
    assert len(carregar_grupos(db_path=db)[("UG F", 2024)]) == 1


def test_obra_e_compra_somam_cada_uma_contra_o_proprio_teto():
    assert _tipo_obj("AQUISIÇÃO DE MATERIAL DE CONSTRUÇÃO CIVIL PARA MANUTENÇÃO PREDIAL") == "compras"
    assert _tipo_obj("CONTRATAÇÃO DE EMPRESA ESPECIALIZADA EM REFORMA E IMPERMEABILIZAÇÃO DA CISTERNA") == "obras"
    assert _tipo_obj("SERVIÇO DE SONORIZAÇÃO, COM MATERIAL E MÃO DE OBRA") == "compras"


def test_ob_paga_ligada_pelo_processo_e_ausencia_e_indisponivel(tmp_path):
    db = _db(tmp_path, [
        ("SEI-6/001/2024", 2024, 59_000.0, "fornecimento de coffee break", _D, "UG G", "BUFFET A"),
        ("SEI-6/002/2024", 2024, 58_000.0, "fornecimento de coffee break e brunch", _D, "UG G", "BUFFET B"),
    ], ob=[("2024OB1", "1", "Contabilizado", "", "", "SEI-6/001/2024", "1", "BUFFET A", 59_000.0, "01/03/2024")])
    achados = rodar_sweep(carregar_grupos(db_path=db))
    cob = ligar_ob_siafe(achados, db_path=db)
    assert cob == {"processos": 2, "processos_com_ob": 1}
    por = {c["processo"]: c for c in achados[0]["contratacoes"]}
    assert por["SEI-6/001/2024"]["ob_pago"] == 59_000.0
    assert por["SEI-6/002/2024"]["ob_pago"] is None     # INDISPONÍVEL ≠ 0


def test_tela_lista_so_soma_acima_do_teto_e_diz_o_conceito(tmp_path):
    arq = tmp_path / "s.json"
    arq.write_text(json.dumps([
        {"unidade": "UG A", "exercicio": 2024, "natureza": "alimentacao", "criterio_natureza": "ramo_de_atividade",
         "soma_acima_do_teto": True, "n_fornecedores_distintos": 3, "fornecedores": ["A", "B", "C"],
         "valores": {"soma_cluster": 172_300.0, "limite_dispensa_vigente": 59_906.02, "n_dispensas_cluster": 3},
         "contratacoes": []},
        {"unidade": "UG B", "exercicio": 2024, "natureza": "grafica", "criterio_natureza": "ramo_de_atividade",
         "soma_acima_do_teto": False, "valores": {"soma_cluster": 40_000.0, "limite_dispensa_vigente": 59_906.02}},
    ]), encoding="utf-8")
    d = fracionamento_por_objeto(arq)
    assert d["ok"] and d["n"] == 1 and d["criterio"] == "objeto"
    assert "fornecedor não entra no critério" in d["conceito"]
    g = d["grupos"][0]
    assert g["excesso"] == round(172_300.0 - 59_906.02, 2) and g["grau"] == "indicio"


def test_tela_sem_sweep_e_indisponivel_nao_zero(tmp_path):
    d = fracionamento_por_objeto(tmp_path / "nao_existe.json")
    assert d["ok"] is False and d["n"] is None
