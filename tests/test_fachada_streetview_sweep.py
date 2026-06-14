# -*- coding: utf-8 -*-
"""Testes OFFLINE do fachada_streetview_sweep — coerência foto-vs-Google e validação de imagem.

Sem rede, sem render, sem DB: cobre só a lógica PURA (a regra de coerência e o validador de imagem).
O render Street View e o upload são I/O (cobertos pelo teste AO VIVO no IDESI + 3 suspeitos)."""
from __future__ import annotations

import io
import sqlite3
from collections import Counter

from PIL import Image

import tools.fachada_streetview_sweep as svs
from tools.fachada_streetview_sweep import _coord_precisa, _validar, coerencia_foto_google


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


# ───────── FIX coord-precisa (o dono caçou: foto saía do LUGAR ERRADO em geo_tipo impreciso) ─────────

class _FakeSG:
    """Stub do sede_google: cota fixa + geocode pré-programado (sem rede)."""
    def __init__(self, cota: int, resultado: dict | None):
        self._cota = cota
        self._resultado = resultado
        self.chamou_geocode = 0

    def cota_restante(self, api):  # noqa: ARG002
        return self._cota

    def geocodificar(self, endereco):  # noqa: ARG002
        self.chamou_geocode += 1
        self._cota -= 1
        return self._resultado


def _row(**kw):
    base = {"cnpj": "11111111000111", "endereco": "RUA X, 100", "municipio": "RIO DE JANEIRO",
            "uf": "RJ", "cep": "20000000", "geo_lat": -22.9, "geo_lon": -43.2, "geo_tipo": "ROOFTOP"}
    base.update(kw)
    return base


def _db(tmp_path, row):
    """DB temporário com 1 linha em verificacao_sede; aponta _DB do módulo p/ ele."""
    p = tmp_path / "sv.db"
    con = sqlite3.connect(str(p))
    con.execute("CREATE TABLE verificacao_sede (cnpj TEXT, geo_lat REAL, geo_lon REAL, geo_tipo TEXT, "
                "geo_municipio TEXT, visual_fonte TEXT, visual_em TEXT, coerencia_nota TEXT)")
    con.execute("INSERT INTO verificacao_sede (cnpj, geo_lat, geo_lon, geo_tipo) VALUES (?,?,?,?)",
                (row["cnpj"], row["geo_lat"], row["geo_lon"], row["geo_tipo"]))
    con.commit()
    con.close()
    return p


def test_coord_rooftop_usa_direto(tmp_path, monkeypatch):
    """geo_tipo ROOFTOP → usa a coord guardada direto, SEM gastar geocoding."""
    monkeypatch.setattr(svs, "_DB", _db(tmp_path, _row()))
    sg = _FakeSG(cota=9999, resultado=None)
    st = Counter()
    r = _coord_precisa(_row(geo_tipo="ROOFTOP"), sg, st)
    assert r["ok"] and r["lat"] == -22.9 and r["lon"] == -43.2
    assert sg.chamou_geocode == 0 and st["rooftop_direto"] == 1


def test_coord_impreciso_regeocoda_para_rooftop_atualiza_db(tmp_path, monkeypatch):
    """geo_tipo impreciso + re-geocode volta ROOFTOP → usa a coord NOVA e ATUALIZA o banco (geo_tipo='ROOFTOP')."""
    row = _row(geo_tipo="GEOMETRIC_CENTER", geo_lat=-21.8698, geo_lon=-43.3453)
    dbp = _db(tmp_path, row)
    monkeypatch.setattr(svs, "_DB", dbp)
    sg = _FakeSG(cota=9999, resultado={"location_type": "ROOFTOP", "lat": -21.8692, "lon": -43.3187,
                                       "formatted": "Rua Real, 100 - Juiz de Fora"})
    st = Counter()
    r = _coord_precisa(row, sg, st)
    assert r["ok"] and r["regeocodou"] and r["lat"] == -21.8692 and r["lon"] == -43.3187
    assert st["regeocode_rooftop"] == 1 and sg.chamou_geocode == 1
    con = sqlite3.connect(str(dbp))
    got = con.execute("SELECT geo_tipo, geo_lat, geo_lon FROM verificacao_sede WHERE cnpj=?",
                      (row["cnpj"],)).fetchone()
    con.close()
    assert got == ("ROOFTOP", -21.8692, -43.3187)   # banco corrigido


def test_coord_impreciso_continua_impreciso_pula(tmp_path, monkeypatch):
    """re-geocode continua impreciso → NÃO renderiza (skip honesto, nunca foto de lugar errado)."""
    row = _row(geo_tipo="APPROXIMATE")
    monkeypatch.setattr(svs, "_DB", _db(tmp_path, row))
    sg = _FakeSG(cota=9999, resultado={"location_type": "APPROXIMATE", "lat": -22.0, "lon": -43.0})
    st = Counter()
    r = _coord_precisa(row, sg, st)
    assert not r["ok"] and r.get("skip_impreciso")
    assert st["regeocode_ainda_impreciso"] == 1


def test_coord_impreciso_sem_cota_adia(tmp_path, monkeypatch):
    """Cota de geocoding esgotada → adia (não chama geocode, marca sem_cota, não renderiza)."""
    row = _row(geo_tipo="RANGE_INTERPOLATED")
    monkeypatch.setattr(svs, "_DB", _db(tmp_path, row))
    sg = _FakeSG(cota=0, resultado={"location_type": "ROOFTOP", "lat": -1, "lon": -1})
    st = Counter()
    r = _coord_precisa(row, sg, st)
    assert not r["ok"] and r.get("sem_cota")
    assert sg.chamou_geocode == 0 and st["sem_cota"] == 1


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
