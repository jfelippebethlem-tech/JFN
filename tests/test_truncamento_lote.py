# -*- coding: utf-8 -*-
"""Lote truncado é conteúdo PERDIDO — e não pode ser apresentado como leitura completa.

MEDIDO em 2026-07-28 no dossiê do processo 030001_004946_2026: **6 dos 7 lotes terminavam no
meio de uma frase**, e o lote 7 tinha 98 caracteres para 37 documentos. O `max_tokens` do passo
de leitura estava em 4.000 — pequeno para um lote de 50+ documentos —, e o dossiê montava tudo
como se fosse extração completa. Quem lesse concluiria que aqueles documentos não tinham nada.

O sinal autoritativo é `finish_reason == "length"`, que o provedor devolve e nós ignorávamos.
Adivinhar truncamento pela pontuação final é heurística; o campo é fato.
"""
from __future__ import annotations

from compliance_agent.sei.dossie_fracionado import aviso_truncamento, marcar_truncado


def test_marcador_e_reconhecivel_e_nao_se_confunde_com_conteudo():
    texto = marcar_truncado("- Objeto: energia elétrica [doc 001.txt]")
    assert "- Objeto: energia elétrica [doc 001.txt]" in texto
    assert aviso_truncamento(texto) is True


def test_texto_normal_nao_e_marcado_como_truncado():
    assert aviso_truncamento("- Objeto: energia elétrica [doc 001.txt]") is False


def test_marcar_duas_vezes_nao_duplica_o_aviso():
    uma = marcar_truncado("conteúdo")
    assert marcar_truncado(uma).count("LEITURA INCOMPLETA") == 1


def test_o_aviso_diz_que_houve_perda_e_nao_apenas_que_terminou():
    """A diferença que importa para quem lê o dossiê depois."""
    texto = marcar_truncado("conteúdo")
    baixo = texto.lower()
    assert "incompleta" in baixo
    assert "não foram lidos" in baixo or "perdid" in baixo


def test_consolidacao_preserva_o_aviso():
    from compliance_agent.sei.dossie_fracionado import consolidar

    md = consolidar([marcar_truncado("- **Valores** — R$ 1.000,00 [doc 001.txt]")])
    assert "LEITURA INCOMPLETA" in md
    assert "[doc 001.txt]" in md


def test_cabecalho_declara_quantos_lotes_ficaram_incompletos():
    from compliance_agent.sei.dossie_fracionado import cabecalho_md, planejar
    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        base = pathlib.Path(d) / "260007_000001_2026"
        (base / "texto").mkdir(parents=True)
        (base / "texto" / "000_a.txt").write_text("conteúdo")
        plano = planejar("p", base, contexto_modelo=128_000)
        md = cabecalho_md(plano, "modelo/x:free", lotes_truncados=3)
        assert "3" in md
        assert "incompleta" in md.lower()


# ── entradas antigas, sem o marcador ───────────────────────────────────────────────────────
# Checkpoints gravados antes de 2026-07-28 têm truncamento INVISÍVEL: o corte aconteceu e nada
# o registrou. Sem a heurística, a retomada congela a perda — o lote incompleto parece pronto e
# nunca é relido. Foi o que aconteceu na 1ª tentativa de reprocessar o dossiê.

import pytest

from compliance_agent.sei.dossie_fracionado import parece_truncado


@pytest.mark.parametrize("fim", [
    "390, 3500, 4104329, 3648652, 3995, 3861949, 4008247, 3393, 3",   # lote 2 real
    '"objeto": "Fornecimento de energia elétrica",     "descricao": "Serviços de fornecimento',
    "- **Autorização de",
])
def test_corte_no_meio_da_frase_e_reconhecido(fim):
    assert parece_truncado(f"- Objeto: energia [doc 001.txt]\n{fim}") is True


@pytest.mark.parametrize("fim", [
    "[doc 016_nota_de_empenho_original_ne_129857902.txt]",
    "- Valor total: R$ 1.504.942,22.",
    "Não consta nos documentos lidos.",
])
def test_extracao_completa_nao_e_acusada(fim):
    assert parece_truncado(f"- Objeto: energia\n{fim}") is False


def test_texto_vazio_nao_e_truncado():
    assert parece_truncado("") is False
    assert parece_truncado("   ") is False
