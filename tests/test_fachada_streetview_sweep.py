# -*- coding: utf-8 -*-
"""Testes OFFLINE do fachada_streetview_sweep — coerência foto-vs-Google e validação de imagem.

Sem rede, sem render, sem DB: cobre só a lógica PURA (a regra de coerência e o validador de imagem).
O render Street View e o upload são I/O (cobertos pelo teste AO VIVO no IDESI + 3 suspeitos)."""
from __future__ import annotations

import io

from PIL import Image

from tools.fachada_streetview_sweep import _validar, coerencia_foto_google


# ───────── coerência foto-vs-Google (pedido do dono: cruzar a foto com o negócio do Google) ─────────

def test_coerencia_contradiz_google_acha_mas_foto_rural():
    """Google diz que há empresa operando, mas a foto mostra área rural → CONTRADIZ (indício reforçado)."""
    coer, nota = coerencia_foto_google("area_aberta_rural", 1, "Padaria do Zé")
    assert coer == "contradiz"
    assert "Padaria do Zé" in nota and "area aberta rural" in nota


def test_coerencia_contradiz_baldio_sem_google():
    """Foto baldio + Google sem negócio → ambos apontam ausência de operação → CONTRADIZ (fraco)."""
    coer, _ = coerencia_foto_google("terreno_baldio", 0, "")
    assert coer == "contradiz"


def test_coerencia_contradiz_residencial():
    """Foto residencial conta como incompatível com operação empresarial → CONTRADIZ."""
    assert coerencia_foto_google("casa_residencial", 1, "Tech LTDA")[0] == "contradiz"
    assert coerencia_foto_google("predio_residencial", 0, "")[0] == "contradiz"


def test_coerencia_confirma_comercial_com_google():
    """Foto comercial + Google acha o negócio → CONFIRMA (sede real)."""
    coer, nota = coerencia_foto_google("comercial_industrial", 1, "Hospital Estadual")
    assert coer == "confirma" and "Hospital Estadual" in nota


def test_coerencia_indeterminado_comercial_sem_google():
    """Foto comercial mas Google não acha negócio → INDETERMINADO (Places tem buracos; não acusa)."""
    assert coerencia_foto_google("comercial_industrial", 0, "")[0] == "indeterminado"
    # galpão também é comercial/edificado
    assert coerencia_foto_google("galpao_logistico", 0, "")[0] == "indeterminado"


def test_coerencia_indeterminado_classe_vazia_ou_ambigua():
    assert coerencia_foto_google("indeterminado", 1, "X")[0] == "indeterminado"
    assert coerencia_foto_google("", 0, "")[0] == "indeterminado"


def test_coerencia_places_nome_vazio_nao_conta_como_negocio():
    """places_achou=1 mas nome vazio NÃO conta como negócio (dado incompleto) → não vira 'confirma'."""
    assert coerencia_foto_google("comercial_industrial", 1, "")[0] == "indeterminado"


# ───────── validador de imagem (rejeita >60% branca = tela de erro/API-off) ─────────

def test_validar_rejeita_branco(tmp_path):
    """Imagem majoritariamente branca = tela de erro 'must be used in an iframe' / API-off → rejeita.

    Branca pura comprime minúsculo; p/ exercitar a regra de % de branco (não a de tamanho), insere ruído
    fraco numa MINORIA dos pixels (>>4KB no JPEG, mas ainda >60% branco)."""
    # Réplica fiel da tela de erro real: faixa de "texto" preto no topo + resto BRANCO (como o card
    # 'must be used in an iframe'). Após o downscale 64x64, a grande maioria continua branca (>60%).
    im = Image.new("RGB", (300, 300), (255, 255, 255))
    px = im.load()
    for x in range(0, 280, 6):           # faixa de "texto" no topo (linhas pretas espaçadas)
        for y in range(8, 22):
            px[x, y] = (0, 0, 0)
            px[x + 1, y] = (0, 0, 0)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=95)
    p = tmp_path / "branca.jpg"
    p.write_bytes(buf.getvalue())
    r = _validar(p, branco_max=0.60)
    assert not r["ok"] and "branco" in r["motivo"].lower()


def test_validar_rejeita_arquivo_minusculo(tmp_path):
    p = tmp_path / "mini.jpg"
    p.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
    assert not _validar(p)["ok"]


def test_validar_aceita_imagem_colorida(tmp_path):
    """Imagem colorida e variada (Street View real) passa (grande o suficiente p/ passar o gate de tamanho)."""
    import random
    rnd = random.Random(2)
    im = Image.new("RGB", (300, 300))
    px = im.load()
    for x in range(300):
        for y in range(300):
            px[x, y] = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    p = tmp_path / "real.jpg"
    p.write_bytes(buf.getvalue())
    assert _validar(p, branco_max=0.60)["ok"]


def test_validar_arquivo_inexistente(tmp_path):
    assert not _validar(tmp_path / "nao_existe.jpg")["ok"]
