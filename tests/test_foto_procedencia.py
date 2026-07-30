# -*- coding: utf-8 -*-
"""Procedência da foto de execução: veio de campo ou da internet?

PEDIDO DO DONO (2026-07-30): "criar um detector de imagens pra saber se as fotos de execucao dos
contratos vem do google e so foram falsamente colocadas la."

O QUE ESTES TESTES TRAVAM — cada um nasceu de um erro que EU cometi escrevendo o módulo:

  1. A primeira versão dava grau `fraco` para qualquer foto sem EXIF, porque o sinal de recompressão
     acendia sozinho. Como o acervo perde EXIF ao virar PDF e ser reextraído, isso marcaria quase
     toda a base — o erro do P1 (71% dos certames) e o do perfil de laranja (55%). Agora esse sinal
     COMPÕE e não INICIA, e `test_foto_sem_exif_sozinha_nao_acusa` trava isso.
  2. A regex de marca d'água incluía o símbolo `©`. Medido nos 7.318 arquivos de texto dos 122
     processos com foto: 8 acendimentos, TODOS por `©` isolado, nenhum era imagem de terceiro —
     nota fiscal, certidão de falência, rodapé de software. Removido.

MEDIÇÃO NO DADO REAL (a casa só aceita FP medido no acervo, não em fixture): 220 fotos sorteadas com
seed fixa de 5.525 → **0 acendimento**. O detector é silencioso neste acervo, e o motivo é honesto:
a extração do PDF destrói tanto o EXIF quanto as dimensões originais, que são os dois sinais offline
mais fortes. O que sobra com poder real aqui é o casamento contra o corpus de imagens que a casa
baixou da web, e a busca reversa — que é paga e fica desligada.
"""
from __future__ import annotations

import subprocess

import pytest

from compliance_agent import foto_procedencia as FP

Image = pytest.importorskip("PIL.Image")


def _jpg(p, w, h, qualidade=85):
    Image.new("RGB", (w, h), (110, 130, 150)).save(p, "JPEG", quality=qualidade)
    return p


# ── a regra que não pode ser violada ────────────────────────────────────────────────────────────
def test_foto_sem_exif_sozinha_nao_acusa(tmp_path):
    """EXIF ausente é LIMITAÇÃO, não achado — está escrito em foto_medicao e vale aqui."""
    r = FP.analisar(_jpg(tmp_path / "a.jpg", 2311, 1733))
    assert r["grau"] == "descartado"
    assert r["pontuacao"] == 0
    assert any("perde EXIF" in x for x in r["limitacoes"])


def test_o_sinal_de_recompressao_compoe_mas_nao_inicia(tmp_path):
    """Peso 0 quando é o único; peso 1 quando reforça outro. Foi o bug da 1ª versão."""
    sozinho = FP.analisar(_jpg(tmp_path / "b.jpg", 2311, 1733))
    s = [x for x in sozinho["sinais"] if x["tipo"] == "recompressao_sem_camera"]
    assert s and s[0]["peso"] == 0

    acompanhado = FP.analisar(_jpg(tmp_path / "c.jpg", 1200, 630))
    s2 = [x for x in acompanhado["sinais"] if x["tipo"] == "recompressao_sem_camera"]
    assert s2 and s2[0]["peso"] == 1


def test_simbolo_de_copyright_isolado_nao_e_marca_de_banco_de_imagens():
    """Medido: 8 de 8 acendimentos no acervo real eram nota fiscal/certidão/rodapé."""
    assert not FP._MARCAS.search("Nota Fiscal — Sistema XPTO © 2024 Todos os direitos reservados")
    assert not FP._MARCAS.search("Certidão negativa de falência © Tribunal de Justiça")
    assert FP._MARCAS.search("Foto: Shutterstock")
    assert FP._MARCAS.search("imagem meramente ilustrativa")


# ── o que DEVE acender ──────────────────────────────────────────────────────────────────────────
def test_dimensao_canonica_de_web_acende(tmp_path):
    r = FP.analisar(_jpg(tmp_path / "w.jpg", 1200, 630))
    assert "dimensao_de_web" in [s["tipo"] for s in r["sinais"]]
    assert r["grau"] in ("medio", "forte")


def test_credito_de_terceiro_na_pagina_e_indicio_forte(tmp_path):
    r = FP.analisar(_jpg(tmp_path / "w.jpg", 1200, 630),
                    texto_da_pagina="Registro fotográfico. Foto: Divulgação / Secretaria")
    assert r["grau"] == "forte"


def test_igualdade_com_imagem_baixada_da_web_e_achado_objetivo(tmp_path):
    """Bate com foto que a CASA obteve da web (fachada por Static View) = achado, custo zero."""
    from compliance_agent.foto_medicao import dhash

    p = _jpg(tmp_path / "x.jpg", 900, 700)
    h = dhash(p)
    if h is None:
        pytest.skip("dhash indisponível nesta imagem sintética")
    r = FP.analisar(p, corpus_web={h: "static-view fachada CNPJ 00.000.000/0001-00"})
    assert r["grau"] == "forte"
    assert any(s["tipo"] == "igual_a_imagem_da_web" for s in r["sinais"])


# ── o que DEVE inocentar ────────────────────────────────────────────────────────────────────────
def test_metadado_de_camera_INOCENTA(tmp_path):
    """A presença de campo de câmera vale como negativo — é o uso correto do sinal."""
    if not FP.shutil.which("exiftool"):
        pytest.skip("exiftool ausente")
    p = _jpg(tmp_path / "campo.jpg", 4032, 3024, qualidade=92)
    subprocess.run(["exiftool", "-overwrite_original", "-Make=Apple", "-Model=iPhone 13",
                    "-FNumber=1.6", str(p)], capture_output=True, timeout=60)
    r = FP.analisar(p)
    assert r["pontuacao"] < 0
    assert r["grau"] == "descartado"
    assert "tem_metadado_de_camera" in [s["tipo"] for s in r["sinais"]]


# ── honestidade ─────────────────────────────────────────────────────────────────────────────────
def test_imagem_ilegivel_e_nao_avaliavel_e_nao_limpa(tmp_path):
    ruim = tmp_path / "quebrada.jpg"
    ruim.write_bytes(b"isto nao e um jpeg")
    r = FP.analisar(ruim)
    assert r["grau"] == "nao_avaliavel"
    assert r["limitacoes"]


def test_arquivo_ausente_nao_inventa_veredito(tmp_path):
    r = FP.analisar(tmp_path / "nao_existe.jpg")
    assert r["grau"] == "nao_avaliavel" and r["sinais"] == []


def test_busca_reversa_vem_DESLIGADA_com_motivo(tmp_path):
    """Serviço pago/bloqueado: a casa nunca assume free tier. Sem callable, INDISPONIVEL explícito."""
    r = FP.buscar_reversa(_jpg(tmp_path / "a.jpg", 800, 600))
    assert r["status"] == "INDISPONIVEL"
    assert "free tier" in r["motivo"] or "pago" in r["motivo"]


def test_busca_reversa_usa_o_provedor_injetado(tmp_path):
    r = FP.buscar_reversa(_jpg(tmp_path / "a.jpg", 800, 600),
                          buscar=lambda c: [{"url": "https://exemplo/foto.jpg", "titulo": "obra X"}])
    assert r["status"] == "ok" and r["n"] == 1


def test_provedor_que_falha_nao_derruba_o_veredito(tmp_path):
    def _explode(_):
        raise RuntimeError("cota estourada")

    r = FP.buscar_reversa(_jpg(tmp_path / "a.jpg", 800, 600), buscar=_explode)
    assert r["status"] == "INDISPONIVEL" and "cota" in r["motivo"]
