# -*- coding: utf-8 -*-
"""Checkpoint de dossiê: retomar do lote errado entrega dado errado em silêncio.

BUG MEDIDO em 2026-07-28. O checkpoint era indexado só pelo NÚMERO do lote. Quando o modelo
escolhido muda, o contexto muda, o plano é refeito e o mesmo processo passa de 16 lotes para 4 —
mas os índices 1..4 continuavam existindo no arquivo. Resultado: a retomada colou as extrações
dos lotes 1..4 do plano ANTIGO (~57 documentos) num plano NOVO que diz cobrir 291, e gravou o
dossiê sem nenhum aviso. O log exibia `retomando: 16 de 4 lote(s)`, que é a assinatura.

Índice de lote não identifica conteúdo. A identidade do checkpoint tem de incluir o PLANO.
"""
from __future__ import annotations

import json

from tools.sei_dossie_md import assinatura_do_plano, ler_checkpoint, gravar_lote


class _Lote:
    def __init__(self, indice, n_docs, tokens):
        self.indice, self.docs, self.tokens = indice, [None] * n_docs, tokens


class _Plano:
    def __init__(self, n_lotes, n_docs, orcamento):
        self.lotes = [_Lote(i, 2, 100) for i in range(1, n_lotes + 1)]
        self.n_docs, self.orcamento = n_docs, orcamento


def test_assinatura_muda_quando_o_plano_muda():
    """É o que impede a confusão: 16 lotes e 4 lotes são planos diferentes."""
    a = assinatura_do_plano(_Plano(16, 291, 144_179))
    b = assinatura_do_plano(_Plano(4, 291, 550_000))
    assert a != b


def test_assinatura_estavel_para_o_mesmo_plano():
    assert assinatura_do_plano(_Plano(4, 291, 550_000)) == \
           assinatura_do_plano(_Plano(4, 291, 550_000))


def test_retoma_quando_o_plano_e_o_mesmo(tmp_path):
    plano = _Plano(4, 291, 550_000)
    ck = tmp_path / "p.jsonl"
    gravar_lote(ck, plano, 1, "extração do lote 1")
    gravar_lote(ck, plano, 2, "extração do lote 2")
    assert ler_checkpoint(ck, plano) == {1: "extração do lote 1", 2: "extração do lote 2"}


def test_descarta_o_checkpoint_de_outro_plano(tmp_path):
    """O caso real: checkpoint de 16 lotes reaproveitado num plano de 4."""
    ck = tmp_path / "p.jsonl"
    antigo = _Plano(16, 291, 144_179)
    for i in range(1, 17):
        gravar_lote(ck, antigo, i, f"lote {i} do plano de 16")
    assert ler_checkpoint(ck, _Plano(4, 291, 550_000)) == {}, \
        "plano diferente não pode reaproveitar lote nenhum"


def test_checkpoint_de_plano_novo_convive_com_o_antigo_no_mesmo_arquivo(tmp_path):
    """Trocar de modelo e voltar não deve custar as duas medições."""
    ck = tmp_path / "p.jsonl"
    p16, p4 = _Plano(16, 291, 144_179), _Plano(4, 291, 550_000)
    gravar_lote(ck, p16, 1, "do plano de 16")
    gravar_lote(ck, p4, 1, "do plano de 4")
    assert ler_checkpoint(ck, p16) == {1: "do plano de 16"}
    assert ler_checkpoint(ck, p4) == {1: "do plano de 4"}


def test_linha_corrompida_e_ignorada_sem_derrubar_o_resto(tmp_path):
    ck = tmp_path / "p.jsonl"
    plano = _Plano(4, 291, 550_000)
    gravar_lote(ck, plano, 1, "bom")
    with ck.open("a") as fh:
        fh.write("{ não é json\n")
    gravar_lote(ck, plano, 2, "também bom")
    assert ler_checkpoint(ck, plano) == {1: "bom", 2: "também bom"}


def test_arquivo_inexistente_devolve_vazio(tmp_path):
    assert ler_checkpoint(tmp_path / "nao_existe.jsonl", _Plano(4, 291, 550_000)) == {}


def test_formato_antigo_sem_assinatura_e_ignorado(tmp_path):
    """Checkpoints gravados antes do conserto não têm assinatura — e como não se sabe de que
    plano vieram, não podem ser reaproveitados."""
    ck = tmp_path / "p.jsonl"
    ck.write_text(json.dumps({"lote": 1, "texto": "de antes do conserto"}) + "\n")
    assert ler_checkpoint(ck, _Plano(4, 291, 550_000)) == {}
