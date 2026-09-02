# -*- coding: utf-8 -*-
"""Resposta cortada não é resposta perdida — e leitura que falhou não é leitura feita.

Medido em 37 processos do acervo: **9 (24%) caíam em `nao_parseei`**. Abrindo o bruto, o modelo
tinha respondido CERTO — o JSON começa correto e é cortado no meio porque `chama_atencao` (lista de
objetos) estoura o limite de saída antes de fechar a chave. Contrato, dispositivo e pregão já
preenchidos iam para o lixo por causa de um `}` que faltou.

Duas exigências, e as duas doem se quebrarem:

1. **Salvar só o que está inteiro.** Par sem a aspa de fechamento pode estar cortado no meio do
   valor, e meio valor num laudo de fiscalização é pior que nenhum.
2. **Reenfileirar quem falhou.** Gravado na tabela, o processo nunca mais voltaria à fila — os 9
   sumiriam do acervo em silêncio, que é a família de falha "coletado ≠ utilizável".
"""
from __future__ import annotations

import sqlite3

from tools.sei_leitura_dupla import _pendentes, extrair_interpretativo

_CORTADO = ('{\n "contrato": "00000000 - SEM CONTRATO",\n "dispositivo": "Art. 37, XXI da CF",\n'
            ' "pregao": "NAO_CONSTA",\n "o_que_e": "Trata-se de pagamento de apoio a municip')


def test_salva_os_campos_inteiros_de_uma_resposta_cortada():
    r = extrair_interpretativo("t", "p", gerar=lambda *a, **k: _CORTADO)
    assert r["estado"] == "ok_parcial", "não pode virar `ok`: quem lê tem de saber que veio cortada"
    assert r["fatos"]["contrato"] == "00000000 - SEM CONTRATO"
    assert r["fatos"]["dispositivo"] == "Art. 37, XXI da CF"


def test_NAO_salva_o_valor_cortado_no_meio():
    r = extrair_interpretativo("t", "p", gerar=lambda *a, **k: _CORTADO)
    assert not r["interpretacao"]["o_que_e"], (
        "`o_que_e` foi cortado sem fechar a aspa — meio valor num laudo é pior que nenhum")


def test_quem_falhou_volta_para_a_fila(tmp_path, monkeypatch):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE sei_leitura_dupla (numero_sei TEXT PRIMARY KEY, ia TEXT)")
    con.execute("INSERT INTO sei_leitura_dupla VALUES ('030001/000009/2024', ?)",
                ('{"estado": "nao_parseei", "bruto": "..."}',))
    con.execute("INSERT INTO sei_leitura_dupla VALUES ('030001/000001/2024', ?)",
                ('{"estado": "ok", "fatos": {}}',))
    for proc in ("030001_000009_2024", "030001_000001_2024"):
        (tmp_path / proc / "texto").mkdir(parents=True)
        (tmp_path / proc / "texto" / "a.txt").write_text("x" * 100, encoding="utf-8")
    monkeypatch.setattr("tools.sei_leitura_dupla._ARQ", tmp_path)
    fila = _pendentes(con, 10)
    assert "030001/000009/2024" in fila, "o que falhou tem de voltar — senão some em silêncio"
    assert "030001/000001/2024" not in fila, "o que foi lido de verdade não pode ser relido"
