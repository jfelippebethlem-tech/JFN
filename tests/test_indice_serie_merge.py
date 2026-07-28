# -*- coding: utf-8 -*-
"""Gravar o índice não pode desfazer o que outro escreveu no disco.

Aconteceu hoje, com consequência real: removi 22 processos de `data/analise_serie.json` para
que a série os relesse (leitura antiga feita com tacada acima do teto de contexto). O lote que
já estava em execução tinha lido o índice ANTES da remoção e, ao terminar, gravou de volta a
sua cópia em memória — os 22 reapareceram como "já analisados", **sem que um único dossiê
fosse refeito** (mtime dos dossiês continuava em 08:55–13:09; o índice foi reescrito às
18:29).

É o clássico read-modify-write sem merge. O mesmo vale para dois lotes concorrentes: o que
terminar por último apaga o trabalho do outro, em silêncio.

A semântica correta não é "unir tudo": é **este processo só afirma o que ele mesmo analisou**.
Adições de terceiros ficam; remoções de terceiros são respeitadas — a menos que este processo
tenha analisado o mesmo item agora, caso em que o fato novo prevalece.
"""
import json

from tools.sei_analise_em_serie import gravar_indice_mesclado


def test_preserva_o_que_outro_processo_acrescentou(tmp_path):
    idx = tmp_path / "i.json"
    idx.write_text(json.dumps({"A": 1, "B": 2}), encoding="utf-8")
    gravar_indice_mesclado(idx, {"C": 3})            # esta rodada analisou só C
    assert json.loads(idx.read_text()) == {"A": 1, "B": 2, "C": 3}


def test_respeita_remocao_feita_por_fora(tmp_path):
    """O caso de hoje: alguém tirou B para reanálise; gravar não pode ressuscitá-lo."""
    idx = tmp_path / "i.json"
    idx.write_text(json.dumps({"A": 1}), encoding="utf-8")   # B já foi removido no disco
    gravar_indice_mesclado(idx, {"C": 3})                    # a rodada não tocou em B
    assert "B" not in json.loads(idx.read_text())


def test_o_que_esta_rodada_analisou_prevalece(tmp_path):
    """Se o processo foi REALMENTE reanalisado agora, o fato novo entra mesmo assim."""
    idx = tmp_path / "i.json"
    idx.write_text(json.dumps({"A": {"n": 1}}), encoding="utf-8")
    gravar_indice_mesclado(idx, {"A": {"n": 2}})
    assert json.loads(idx.read_text())["A"] == {"n": 2}


def test_indice_inexistente_e_criado(tmp_path):
    idx = tmp_path / "sub" / "i.json"
    gravar_indice_mesclado(idx, {"A": 1})
    assert json.loads(idx.read_text()) == {"A": 1}


def test_indice_corrompido_nao_apaga_o_trabalho_da_rodada(tmp_path):
    idx = tmp_path / "i.json"
    idx.write_text("{lixo", encoding="utf-8")
    gravar_indice_mesclado(idx, {"A": 1})
    assert json.loads(idx.read_text()) == {"A": 1}
