# -*- coding: utf-8 -*-
"""Fotos de medição: reciclagem entre processos, EXIF e coerência com o objeto (plano #4, item 1.2).

O dono vetou qualquer coisa paga. A parte que mais acusa NÃO precisa de IA nenhuma: se a MESMA foto
lastreia a medição de dois processos diferentes, isso é objetivo, verificável e grave. Hash perceptual
(dHash) pega isso mesmo com recompressão/redimensionamento — e roda de graça, offline.
O VLM (local e gratuito) entra só como camada subjetiva INJETADA, para dizer se a foto bate com o objeto.
"""
from __future__ import annotations

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from compliance_agent import foto_medicao as FM  # noqa: E402


def _foto(path, cor=(120, 120, 120), n=6, tamanho=(320, 240)):
    """Imagem com contraste de FOTO (desvio de luminância ~40, como as fotos reais de medição) — a
    versão pobre anterior tinha desvio 7 e caía no filtro de 'quase uniforme'."""
    img = Image.new("RGB", tamanho, cor)
    d = ImageDraw.Draw(img)
    larg, alt = tamanho
    for i in range(n):
        x, y = (i * larg) // n, (i * alt) // max(n, 1)
        tom = 0 if i % 2 else 255
        d.rectangle([x, y, x + larg // 3, y + alt // 3], fill=(tom, 255 - tom, (40 * i) % 256))
    img.save(path)
    return path


# ───────────────────────────── hash perceptual ─────────────────────────────

def test_mesma_foto_mesmo_hash(tmp_path):
    a = _foto(tmp_path / "a.jpg")
    b = _foto(tmp_path / "b.jpg")
    assert FM.dhash(a) == FM.dhash(b)


def test_foto_recomprimida_e_redimensionada_continua_igual(tmp_path):
    a = _foto(tmp_path / "a.png")
    img = Image.open(a).resize((640, 480))
    b = tmp_path / "b.jpg"
    img.save(b, quality=60)
    assert FM.distancia(FM.dhash(a), FM.dhash(b)) <= FM.LIMIAR_IGUAL


def test_fotos_diferentes_tem_hash_distante(tmp_path):
    a = _foto(tmp_path / "a.jpg", cor=(10, 10, 10), n=3)
    b = _foto(tmp_path / "b.jpg", cor=(240, 240, 240), n=9)
    assert FM.distancia(FM.dhash(a), FM.dhash(b)) > FM.LIMIAR_IGUAL


def test_arquivo_invalido_nao_quebra(tmp_path):
    ruim = tmp_path / "x.jpg"
    ruim.write_bytes(b"nao sou imagem")
    assert FM.dhash(ruim) is None


# ───────── imagens NÃO informativas (falsos positivos medidos no arquivo SEI real) ─────────

def test_pagina_em_branco_nao_e_foto_de_medicao(tmp_path):
    # medido no dado real: 47 processos "compartilhavam" a mesma imagem — era página em branco
    # extraída do PDF. Acusar reciclagem por isso seria acusar o extrator, não o gestor.
    branca = tmp_path / "branca.jpg"
    Image.new("RGB", (900, 1200), (255, 255, 255)).save(branca)
    assert FM.informativa(branca) is False


def test_pagina_preta_ou_quase_uniforme_tambem_sai(tmp_path):
    preta = tmp_path / "preta.jpg"
    Image.new("RGB", (900, 1200), (3, 3, 3)).save(preta)
    assert FM.informativa(preta) is False


def test_logo_pequeno_nao_conta(tmp_path):
    logo = _foto(tmp_path / "logo.png", tamanho=(64, 64))
    assert FM.informativa(logo) is False


def test_foto_de_verdade_e_informativa(tmp_path):
    assert FM.informativa(_foto(tmp_path / "obra.jpg", tamanho=(800, 600))) is True


def test_paginas_em_branco_em_processos_distintos_nao_viram_achado(tmp_path):
    p1, p2 = tmp_path / "SEI-1" / "fotos", tmp_path / "SEI-2" / "fotos"
    p1.mkdir(parents=True); p2.mkdir(parents=True)
    for p in (p1 / "b1.jpg", p2 / "b2.jpg"):
        Image.new("RGB", (900, 1200), (255, 255, 255)).save(p)
    r = FM.reciclagem([p1.parent, p2.parent])
    assert r["n_grupos"] == 0
    assert r["n_descartadas_nao_informativas"] == 2


# ───────────────────────────── reciclagem entre processos ─────────────────────────────

def test_mesma_foto_em_dois_processos_e_achado_forte(tmp_path):
    p1, p2 = tmp_path / "SEI-1" / "fotos", tmp_path / "SEI-2" / "fotos"
    p1.mkdir(parents=True); p2.mkdir(parents=True)
    _foto(p1 / "medicao1.jpg"); _foto(p2 / "medicao9.jpg")          # idêntica
    _foto(p2 / "outra.jpg", cor=(5, 200, 5), n=2)
    r = FM.reciclagem([p1.parent, p2.parent])
    assert r["grau"] == "vermelho"
    assert r["n_grupos"] == 1
    grupo = r["grupos"][0]
    assert {g["processo"] for g in grupo["ocorrencias"]} == {"SEI-1", "SEI-2"}
    assert "processos" in r["resumo"].lower()


def test_foto_repetida_no_MESMO_processo_nao_acusa(tmp_path):
    # repetir a mesma foto dentro do próprio processo é comum (anexo duplicado) — não é reciclagem
    p = tmp_path / "SEI-1" / "fotos"
    p.mkdir(parents=True)
    _foto(p / "a.jpg"); _foto(p / "b.jpg")
    r = FM.reciclagem([p.parent])
    assert r["grau"] == "verde" and r["n_grupos"] == 0


def test_sem_fotos_e_resolvido_e_honesto(tmp_path):
    r = FM.reciclagem([tmp_path])
    assert r["grau"] == "nao_aplicavel"
    assert r["grau"] not in ("indeterminado", "indisponivel")
    assert "≠" in r["ressalva"] or "indispon" in r["ressalva"].lower()


# ───────────────────────────── EXIF ─────────────────────────────

def test_exif_ausente_e_registrado_sem_acusar(tmp_path):
    a = _foto(tmp_path / "a.jpg")
    e = FM.exif_resumo(a)
    assert e["tem_exif"] is False
    assert "não" in e["observacao"].lower() and "prova" not in e["observacao"].lower()[:40]


# ───────────────────────────── camada VLM (injetada, gratuita) ─────────────────────────────

def test_vlm_injetado_confronta_foto_com_objeto(tmp_path):
    p = tmp_path / "SEI-1" / "fotos"
    p.mkdir(parents=True)
    _foto(p / "a.jpg")
    chamadas = []

    def descrever(caminho):
        chamadas.append(caminho)
        return "sala de escritório com mesas e computadores"

    r = FM.avaliar_fotos(p.parent, objeto="Reforma de telhado — 1.200 m²", descrever=descrever)
    assert chamadas
    assert r["grau"] in ("amarelo", "vermelho")
    assert any("telhado" in s["observacao"].lower() or "objeto" in s["observacao"].lower()
               for s in r["sinais"])


def test_sem_vlm_a_parte_objetiva_continua(tmp_path):
    p = tmp_path / "SEI-1" / "fotos"
    p.mkdir(parents=True)
    _foto(p / "a.jpg")
    r = FM.avaliar_fotos(p.parent, objeto="Reforma de telhado", descrever=None)
    assert r["grau"] not in ("indeterminado", "indisponivel")
    assert r["n_fotos"] == 1
    assert r["coerencia_objeto"]["grau"] == "pendente_reprocessar"   # honesto: não rodou, não é verde


def test_vlm_que_falha_nao_derruba_o_veredito(tmp_path):
    p = tmp_path / "SEI-1" / "fotos"
    p.mkdir(parents=True)
    _foto(p / "a.jpg")

    def descrever(_):
        raise RuntimeError("modelo local fora do ar")

    r = FM.avaliar_fotos(p.parent, objeto="Reforma", descrever=descrever)
    assert r["grau"] not in ("indeterminado", "indisponivel")
    assert r["coerencia_objeto"]["grau"] == "pendente_reprocessar"


def test_pagina_de_documento_escaneada_nao_e_foto_de_medicao(tmp_path):
    """Medido no arquivo real: 16 processos 'compartilhavam' uma imagem — era FOLHA DE PONTO digitalizada,
    cujo rodapé padrão se repete em todo processo. Documento tem brilho ~250 e saturação ~0; fotografia de
    obra tem brilho 134-168 e saturação 38-67."""
    doc = tmp_path / "ponto.jpg"
    img = Image.new("RGB", (900, 1200), (252, 252, 252))
    d = ImageDraw.Draw(img)
    for linha in range(14):                     # linhas de texto escuro sobre fundo branco
        d.rectangle([60, 40 + linha * 30, 840, 52 + linha * 30], fill=(30, 30, 30))
    img.save(doc)
    assert FM.informativa(doc) is False


def test_foto_colorida_de_obra_continua_valendo(tmp_path):
    obra = tmp_path / "obra.jpg"
    img = Image.new("RGB", (900, 700), (90, 120, 60))
    d = ImageDraw.Draw(img)
    for i in range(8):
        d.rectangle([i * 100, i * 60, i * 100 + 220, i * 60 + 180],
                    fill=((30 * i) % 256, (200 - 20 * i) % 256, (90 + 15 * i) % 256))
    img.save(obra)
    assert FM.informativa(obra) is True
