# -*- coding: utf-8 -*-
"""Processo enfileirado à mão (hipótese do vault) SEM OB no SIAFE tem de entrar na fila do sweep."""
from __future__ import annotations

from tools.sei_sweep import _aplicar_fatia, _incluir_dirigidos_fora_do_universo, na_minha_fatia

_ROWS = [("SEI-040047/001174/2023", 36, 2415045300.0), ("SEI-080002/010538/2024", 3, 3300000.0)]


def test_dirigido_sem_ob_entra_no_fim_com_zero():
    out = _incluir_dirigidos_fora_do_universo(_ROWS, {"SEI-080001/000803/2021"}, filtrado=False)
    assert out[-1] == ("SEI-080001/000803/2021", 0, 0.0) and len(out) == 3


def test_dirigido_que_ja_tem_ob_nao_duplica():
    out = _incluir_dirigidos_fora_do_universo(_ROWS, {"SEI-080002/010538/2024"}, filtrado=False)
    assert out == _ROWS


def test_com_filtro_de_ug_ou_cnpj_nada_entra():
    assert _incluir_dirigidos_fora_do_universo(_ROWS, {"SEI-510001/001163/2025"}, filtrado=True) == _ROWS


def test_lixo_sem_prefixo_sei_fica_de_fora():
    assert _incluir_dirigidos_fora_do_universo(_ROWS, {"080001/000803/2021"}, filtrado=False) == _ROWS


def test_dirigido_sobrevive_a_fatia_da_outra_maquina():
    rows = [("SEI-080002/003231/2026", 0, 0.0), ("SEI-040047/001174/2023", 36, 1.0)]
    fora = [r for r in rows if not na_minha_fatia(r[0], 0, 2)]      # os que cairiam na VM-2
    out = _aplicar_fatia(rows, 0, 2, {"0800020032312026"})
    assert ("SEI-080002/003231/2026", 0, 0.0) in out                  # dirigido fica, esteja na fatia ou não
    for r in fora:
        if r[0] != "SEI-080002/003231/2026":
            assert r not in out                                      # o resto respeita a fatia


def test_dirigido_com_pesquisa_vazia_recente_sai_da_fila_e_volta_depois_do_prazo():
    """'Nenhum resultado' é resposta definitiva de acesso: reler a cada ciclo custava ~50 s por processo (10/09)."""
    from datetime import datetime
    from tools.sei_sweep import _sem_pesquisa_vazia_recente
    reg = {"0800020185912026": {"pesquisa_vazia": True, "ultima": "2026-09-10 06:32"},
           "0800020231312026": {"pesquisa_vazia": True, "ultima": "2026-08-20 06:32"},
           "0800020000010026": {"pesquisa_vazia": False, "ultima": "2026-09-10 06:32"}}
    d = {"SEI-080002/018591/2026", "SEI-080002/023131/2026", "SEI-080002/000010/026", "SEI-030001/999999/2026"}
    agora = datetime(2026, 9, 10, 12, 0)
    assert _sem_pesquisa_vazia_recente(d, reg, agora) == {"SEI-080002/023131/2026", "SEI-080002/000010/026", "SEI-030001/999999/2026"}
    assert _sem_pesquisa_vazia_recente(d, {}, agora) == d


def test_dirigido_de_unidade_NUNCA_tentada_vem_antes_dos_legiveis(tmp_path, monkeypatch):
    """23/09/2026: 5 TACs da SEDSODH (310001, unidade que o leitor nunca tentou) enfileirados à mão caíram na
    posição 125.587 de 256.279 — atrás de todo processo de unidade legível. 'Legível' só se aprende lendo:
    sem este degrau a unidade nova nunca é lida e nunca vira legível."""
    import sqlite3
    import tools.sei_sweep as S
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (processo TEXT, credor TEXT, nome_credor TEXT, valor REAL, status TEXT, ug_emitente TEXT)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,'12345678000199','',?,'Contabilizado','010100')",
                    [("SEI-080002/000001/2026", 9e8), ("SEI-080002/000002/2026", 5e8), ("SEI-999999/000003/2026", 1e9)])
    con.execute("CREATE TABLE sei_fila_captura (numero_sei, sei_norm, motivo, total_pago, n_docs, visto_em)")
    con.execute("INSERT INTO sei_fila_captura VALUES ('SEI-310001/000714/2025','3100010007142025','hipotese_tac_sedsodh: x',0,0,'')")
    con.commit(); con.close()
    monkeypatch.setattr(S, "DB", p)
    monkeypatch.setattr(S, "_unidades_legiveis", lambda: {"080002"})
    monkeypatch.setattr(S, "_raizes_com_sinal_osint", lambda: set())
    monkeypatch.setattr(S, "_fila_com_lacuna_provada", lambda con: set())
    monkeypatch.setattr(S, "fatia_desta_maquina", lambda: (0, 1))
    fila = [r[0] for r in S._fila(None, 10)]
    assert fila[0] == "SEI-310001/000714/2025"
    assert fila[1:3] == ["SEI-080002/000001/2026", "SEI-080002/000002/2026"]   # legíveis antes do resto
    assert fila[-1] == "SEI-999999/000003/2026"                                  # não-legível sem alvo segue atrás
