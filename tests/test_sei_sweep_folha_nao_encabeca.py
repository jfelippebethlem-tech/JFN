# -*- coding: utf-8 -*-
"""A fila do sweep gastava as vagas mais caras lendo FOLHA DE PAGAMENTO.

A ordem da fila termina em `-valor`, e a própria casa já escreveu que "valor não é risco". Faltava
notar o que o valor bruto de fato ranqueia: `CG0004700` (**FOLHA DE PAGAMENTOS**), `123400`/`123499`
(RIOPREV / plano previdenciário) e `CG0006026` (RIOPREV/INATIVOS) — credor genérico, não fornecedor.

MEDIDO NA FILA REAL, por estrato (2026-08-11). A medição corrige a primeira leitura, que foi feita
no ranking por valor PURO (82% do top-50 era folha) e teria exagerado o efeito:

    estrato                                    processos   folha no seu top-50
    legível + lacuna provada                       2.346          0
    legível + sinal OSINT no credor                2.346         22
    legível, sem sinal (o estrato de trabalho)    77.748         30
    não legível, sem sinal                        38.423         48

Na cabeça de HOJE não muda nada — lacuna provada e OSINT ocupam as primeiras vagas e são de
fornecedor. O desperdício está no estrato onde o sweep passa a vida (77.748 processos) e no estrato
do próprio sinal OSINT, onde 22 das 50 primeiras vagas iam para a folha. O sweep lê ~16 processos
por dia com browser: é o recurso mais escasso da casa.

NÃO é exclusão — é REBAIXAMENTO, e dentro do mesmo estrato. Folha tem irregularidade própria
(a casa já tem perícia de benefício×vínculo); o que não pode é ela chegar antes do fornecedor
por um critério — o tamanho do pagamento — que não mede risco nenhum.
"""
from __future__ import annotations

import sqlite3

import tools.sei_sweep as S


def _db(tmp_path, linhas):
    """linhas: (processo, credor, valor)"""
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (processo TEXT, credor TEXT, nome_credor TEXT,"
                " valor REAL, status TEXT, ug_emitente TEXT)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,'',?,'Contabilizado','010100')",
                    linhas)
    con.commit()
    return p, con


def test_credor_generico_marca_o_processo_como_folha(tmp_path):
    p, con = _db(tmp_path, [
        ("SEI-1/1/2024", "CG0004700", 500_000_000.0),   # FOLHA DE PAGAMENTOS
        ("SEI-1/1/2024", "12345678000199", 1_000.0),    # migalha de fornecedor no mesmo processo
        ("SEI-2/2/2024", "12345678000199", 900_000.0),  # fornecedor de verdade
    ])
    folha = S._processos_de_folha(con)
    con.close()
    assert "SEI-1/1/2024" in folha
    assert "SEI-2/2/2024" not in folha


def test_processo_MISTO_com_fornecedor_majoritario_NAO_e_folha(tmp_path):
    """O corte é por PESO do dinheiro, não por presença. Um processo com consignação ao lado do
    pagamento ao fornecedor continua sendo processo de fornecedor."""
    p, con = _db(tmp_path, [
        ("SEI-3/3/2024", "CG0004700", 10_000.0),
        ("SEI-3/3/2024", "12345678000199", 90_000.0),
    ])
    folha = S._processos_de_folha(con)
    con.close()
    assert "SEI-3/3/2024" not in folha


def test_cpf_conta_como_fornecedor(tmp_path):
    """Pessoa física contratada é fornecedor; o que descaracteriza é o credor GENÉRICO (folha,
    fundo previdenciário), que não tem CPF nem CNPJ."""
    p, con = _db(tmp_path, [("SEI-4/4/2024", "11122233344", 50_000.0)])
    folha = S._processos_de_folha(con)
    con.close()
    assert "SEI-4/4/2024" not in folha


def test_sem_nenhuma_OB_conhecida_NAO_e_folha(tmp_path):
    """Na dúvida o processo segue como fornecedor: rebaixar por ausência de dado seria esconder
    trabalho, e a casa não fecha por osmose."""
    p, con = _db(tmp_path, [("SEI-5/5/2024", "", 0.0)])
    folha = S._processos_de_folha(con)
    con.close()
    assert "SEI-5/5/2024" not in folha


def test_a_fila_poe_o_fornecedor_MENOR_antes_da_folha_MAIOR(tmp_path, monkeypatch):
    """O teste que descreve o defeito: R$ 500 mi de folha encabeçava R$ 900 mil de fornecedor."""
    p, con = _db(tmp_path, [
        ("SEI-1/1/2024", "CG0004700", 500_000_000.0),
        ("SEI-2/2/2024", "12345678000199", 900_000.0),
    ])
    con.close()
    monkeypatch.setattr(S, "DB", p)
    monkeypatch.setattr(S, "_unidades_legiveis", lambda: set())
    monkeypatch.setattr(S, "_raizes_com_sinal_osint", lambda: set())
    monkeypatch.setattr(S, "_fila_com_lacuna_provada", lambda con: set())
    monkeypatch.setattr(S, "fatia_desta_maquina", lambda: (0, 1))
    fila = [r[0] for r in S._fila(None, 10)]
    assert fila == ["SEI-2/2/2024", "SEI-1/1/2024"]


def test_o_rebaixamento_NAO_tira_a_folha_da_fila(tmp_path, monkeypatch):
    """Rebaixar não é excluir: o processo de folha continua alcançável, atrás dos fornecedores."""
    p, con = _db(tmp_path, [("SEI-1/1/2024", "CG0004700", 500_000_000.0)])
    con.close()
    monkeypatch.setattr(S, "DB", p)
    monkeypatch.setattr(S, "_unidades_legiveis", lambda: set())
    monkeypatch.setattr(S, "_raizes_com_sinal_osint", lambda: set())
    monkeypatch.setattr(S, "_fila_com_lacuna_provada", lambda con: set())
    monkeypatch.setattr(S, "fatia_desta_maquina", lambda: (0, 1))
    assert [r[0] for r in S._fila(None, 10)] == ["SEI-1/1/2024"]


def test_lacuna_PROVADA_vence_o_rebaixamento_de_folha(tmp_path, monkeypatch):
    """A precedência não muda: se o parecer PROVA que falta documento, o processo entra na frente
    mesmo sendo de folha. Ali não há hipótese — o documento existe e nós não o temos."""
    p, con = _db(tmp_path, [
        ("SEI-1/1/2024", "CG0004700", 500_000_000.0),
        ("SEI-2/2/2024", "12345678000199", 900_000.0),
    ])
    con.close()
    monkeypatch.setattr(S, "DB", p)
    monkeypatch.setattr(S, "_unidades_legiveis", lambda: set())
    monkeypatch.setattr(S, "_raizes_com_sinal_osint", lambda: set())
    monkeypatch.setattr(S, "_fila_com_lacuna_provada", lambda con: {"SEI-1/1/2024"})
    monkeypatch.setattr(S, "fatia_desta_maquina", lambda: (0, 1))
    assert [r[0] for r in S._fila(None, 10)] == ["SEI-1/1/2024", "SEI-2/2/2024"]
