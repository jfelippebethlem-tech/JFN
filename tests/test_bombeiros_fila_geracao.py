# -*- coding: utf-8 -*-
"""A lane dos bombeiros lê os CONTRATOS antes da cascata de "licitação de licitação".

Medido em 13/11/2026 em `data/bombeiros_sei_fila.json` (9.659 itens) × progresso do sweep:
`bombeiros_achar_edital` põe NO TOPO todo SEI 270xxx citado em qualquer documento lido, com
score 40 e herdando valor/fornecedor de quem o citou — e os itens enfileirados assim também são
lidos e citam outros. **7.105 itens são de 2ª geração ou mais** (pai também é "LICITACAO"); 3.202
carregam o mesmo "R$ 617,10" herdado de um único fornecedor. Resultado: a lane gastou 91 h desde
30/10 nessa cascata (37% com 0 docs) enquanto **1.051 CONTRATOS — o alvo da lane — nunca foram
lidos**. Laudo dos motores: 58% das leituras de 12/11 eram processos "R$ 617".

Rebaixar, não excluir (a cascata rendeu documento): contrato e licitação direta do contrato
primeiro, cascata depois, preservando a ordem do arquivo dentro de cada grupo.
"""
import json

import tools.sei_bombeiros_sweep as B


def _fila(tmp_path, itens):
    f = tmp_path / "fila.json"
    f.write_text(json.dumps(itens), encoding="utf-8")
    return f


def test_cascata_vai_para_o_fim_contrato_e_1a_geracao_na_frente(tmp_path, monkeypatch):
    monkeypatch.setenv("BBM_INCLUIR_CASCATA", "1")          # a ordem com a cascata incluída (opt-in)
    itens = [
        {"sei": "SEI-270000/000003/2023", "valor": 617.1, "tipo": "LICITACAO",
         "flags": ["LICITACAO_DE:SEI-270000/000002/2023"]},                  # pai é LICITACAO → 2ª geração
        {"sei": "SEI-270000/000002/2023", "valor": 617.1, "tipo": "LICITACAO",
         "flags": ["LICITACAO_DE:SEI-270000/000001/2023"]},                  # pai é contrato → 1ª geração
        {"sei": "SEI-270000/000001/2023", "valor": 617.1, "tipo": "LICITADO", "flags": []},
        {"sei": "SEI-270000/000009/2024", "valor": 77_000_000, "tipo": "DIRETA", "flags": []},
    ]
    monkeypatch.setattr(B, "FILA", _fila(tmp_path, itens))
    ordem = [p for p, _, _ in B._carregar_fila()]
    # fora da cascata: o de R$ 77 mi antes dos de R$ 617 (piso de valor), estes na ordem do arquivo
    assert ordem == ["SEI-270000/000009/2024", "SEI-270000/000002/2023",
                     "SEI-270000/000001/2023", "SEI-270000/000003/2023"]


def test_valor_infimo_vai_para_o_fim_do_proprio_grupo(tmp_path, monkeypatch):
    monkeypatch.setenv("BBM_INCLUIR_CASCATA", "1")
    itens = [
        {"sei": "A", "valor": 617.1, "tipo": "LICITADO"},
        {"sei": "B", "valor": 0, "tipo": "LICITADO"},            # sem valor = INDISPONÍVEL, não ínfimo
        {"sei": "C", "valor": 19500, "tipo": "LICITADO"},
        {"sei": "D", "valor": 900, "tipo": "LICITACAO", "flags": ["LICITACAO_DE:A"]},
    ]
    monkeypatch.setattr(B, "FILA", _fila(tmp_path, itens))
    assert [p for p, _, _ in B._carregar_fila()] == ["B", "C", "A", "D"]


def test_com_opt_in_nada_e_excluido(tmp_path, monkeypatch):
    monkeypatch.setenv("BBM_INCLUIR_CASCATA", "1")
    itens = [{"sei": f"SEI-270000/{i:06d}/2023", "valor": 1, "tipo": "LICITACAO",
              "flags": [f"LICITACAO_DE:SEI-270000/{i + 1:06d}/2023"]} for i in range(5)]
    monkeypatch.setattr(B, "FILA", _fila(tmp_path, itens))
    assert len(B._carregar_fila()) == 5


def test_padrao_e_so_contratos_e_licitacao_de_1a_geracao(tmp_path, monkeypatch):
    """Decisão do dono (13/11/2026, "continue tudo" sobre a proposta): a lane fica nos CONTRATOS; a
    "licitação de licitação" (2ª geração ou mais, 7.108 itens = 74% da fila) sai. `BBM_INCLUIR_CASCATA=1`
    devolve o comportamento anterior (rebaixada, não excluída)."""
    monkeypatch.delenv("BBM_INCLUIR_CASCATA", raising=False)
    itens = [
        {"sei": "SEI-270000/000003/2023", "valor": 617.1, "tipo": "LICITACAO",
         "flags": ["LICITACAO_DE:SEI-270000/000002/2023"]},                  # cascata → fora
        {"sei": "SEI-270000/000002/2023", "valor": 617.1, "tipo": "LICITACAO",
         "flags": ["LICITACAO_DE:SEI-270000/000001/2023"]},                  # licitação do contrato → fica
        {"sei": "SEI-270000/000001/2023", "valor": 617.1, "tipo": "LICITADO", "flags": []},
        {"sei": "SEI-270000/000009/2024", "valor": 77_000_000, "tipo": "DIRETA", "flags": []},
    ]
    monkeypatch.setattr(B, "FILA", _fila(tmp_path, itens))
    assert [p for p, _, _ in B._carregar_fila()] == [
        "SEI-270000/000009/2024", "SEI-270000/000001/2023", "SEI-270000/000002/2023"]


def test_formato_da_tupla_mantido(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "FILA", _fila(tmp_path, [{"sei": "SEI-1", "valor": "12.5"}]))
    assert B._carregar_fila() == [("SEI-1", 1, 12.5)]
