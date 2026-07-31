# -*- coding: utf-8 -*-
"""O RAG não pode perder o que já embeddou — senão a cota é queimada todo dia pelo mesmo trecho.

Defeito medido (31/07/2026): `data/hermes_rag_cron.log` tinha 28 ocorrências de `Cohere 429
persistente` e o índice em `data/rag/` estava parado em 28/07 06:56. A causa não era a cota: era
`build()` ser tudo-ou-nada. `_embed` levantava no lote que estourava o limite, a exceção subia e o
`np.save` no fim de `build()` nunca rodava — os lotes JÁ embeddados com sucesso iam para o lixo.

No dia seguinte o cron reindexava do zero, gastava a cota de novo nos mesmos lotes iniciais e
morria no mesmo ponto. Um laço de Sísifo que consome chave trial e nunca avança um chunk.

Duas regras nascem daqui:
  • progresso parcial é PERSISTIDO — a próxima rodada começa de onde parou;
  • em build parcial o `corpus_hash` NÃO é gravado, senão `build_se_mudou` passa a achar que está
    em dia e o acervo congela pela metade para sempre.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

import tools.hermes_rag as R


@pytest.fixture()
def rag(tmp_path, monkeypatch):
    """Índice de mentira em tmp_path + um corpus de 5 chunks."""
    monkeypatch.setattr(R, "RAGDIR", tmp_path)
    monkeypatch.setattr(R, "EMB", tmp_path / "embeddings.npy")
    monkeypatch.setattr(R, "CHUNKS", tmp_path / "chunks.jsonl")
    monkeypatch.setattr(R, "HASH", tmp_path / "corpus_hash.txt")

    # cada parágrafo precisa passar de `_chunk(alvo=1100)` sozinho, senão os 5 viram 1 chunk só
    # e o caminho parcial nunca é exercitado (foi o que aconteceu na 1ª versão deste teste).
    corpo = tmp_path / "corpus.md"
    corpo.write_text("\n\n".join(f"Parágrafo número {i}. " + f"texto do bloco {i} " * 90
                                 for i in range(5)), encoding="utf-8")
    monkeypatch.setattr(R, "_arquivos_corpus", lambda: [str(corpo)])
    monkeypatch.setattr(R, "corpus_hash", lambda: "hash-do-corpus")
    return tmp_path


def _embed_que_para_em(n_ok: int):
    """`_embed` que devolve `n_ok` vetores e então estoura, como o 429 persistente faz."""
    def _fake(textos, _input_type):
        vecs = [[float(i), 1.0, 0.0] for i in range(min(n_ok, len(textos)))]
        if len(textos) > n_ok:
            raise R.EmbedParcial("Cohere 429 persistente", vecs)
        return vecs
    return _fake


def test_build_parcial_persiste_o_que_ja_embeddou(rag, monkeypatch):
    """Estourar no meio não pode zerar o trabalho: o que saiu do Cohere vai para o disco."""
    monkeypatch.setattr(R, "_embed", _embed_que_para_em(2))

    R.build()

    assert R.EMB.exists(), "build parcial tem que gravar o índice mesmo assim"
    assert np.load(R.EMB).shape[0] == 2
    assert sum(1 for _ in open(R.CHUNKS, encoding="utf-8")) == 2, "índice e chunks têm que casar"


def test_build_parcial_nao_grava_o_corpus_hash(rag, monkeypatch):
    """Gravar o hash num build pela metade faria `build_se_mudou` congelar o acervo incompleto."""
    monkeypatch.setattr(R, "_embed", _embed_que_para_em(2))

    R.build()

    assert not R.HASH.exists(), "corpus_hash só pode ser gravado em build COMPLETA"
    assert R.corpus_mudou() is True, "com build parcial o corpus segue 'mudado' — há trabalho a fazer"


def test_rodada_seguinte_continua_de_onde_parou(rag, monkeypatch):
    """O ponto do defeito: a 2ª rodada não pode re-embeddar o que a 1ª já pagou."""
    monkeypatch.setattr(R, "_embed", _embed_que_para_em(2))
    R.build()
    ja_pagos = np.load(R.EMB).shape[0]

    pedidos: list[int] = []

    def _embed_resto(textos, _input_type):
        pedidos.append(len(textos))
        return [[9.0, 1.0, 0.0] for _ in textos]

    monkeypatch.setattr(R, "_embed", _embed_resto)
    R.build()

    total = np.load(R.EMB).shape[0]
    assert ja_pagos > 0, "a 1ª rodada tem que ter deixado progresso no disco"
    assert pedidos == [total - ja_pagos], (
        f"a 2ª rodada pediu {pedidos} de {total} chunks — devia pedir só os {total - ja_pagos} "
        f"que faltavam, não re-embeddar os {ja_pagos} já pagos")
    assert R.HASH.exists(), "agora que completou, o hash pode ser gravado"


def test_build_completa_continua_gravando_tudo(rag, monkeypatch):
    """Guarda-costas: sem falha, nada muda no caminho feliz."""
    monkeypatch.setattr(R, "_embed", lambda textos, _t: [[1.0, 0.0, 0.0] for _ in textos])

    R.build()

    regs = [json.loads(l) for l in open(R.CHUNKS, encoding="utf-8")]
    assert np.load(R.EMB).shape[0] == len(regs) > 0
    assert R.HASH.read_text() == "hash-do-corpus"


def test_embed_parcial_ainda_e_runtime_error():
    """Compatibilidade: quem já capturava `RuntimeError` continua capturando."""
    assert issubclass(R.EmbedParcial, RuntimeError)
