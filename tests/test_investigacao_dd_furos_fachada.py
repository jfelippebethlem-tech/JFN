# -*- coding: utf-8 -*-
"""Furos do detector de fachada medidos no acervo real em 14/11/2026 ("tá super furado").

Cada teste reproduz um caso real com os números da base (SIAFE OB contabilizada + dump da Receita):

1. H-SITUACAO "forte" para empresa INCORPORADA. Dos 99 CONFIRMADO/ALTO da base, 34 tinham motivo 02
   (incorporação) — R$ 469,22 mi. Ex.: Telemar Norte Leste (33.000.118/0001-79), baixada por incorporação
   em 03/05/2021, último pagamento 26/08/2025. A sucessora existe e responde: não é fachada.
2. A Receita declarar INEXISTÊNCIA DE FATO (motivo 15) é o sinal mais forte de fachada e saía com o mesmo
   peso de qualquer baixa. Ex.: IDESI (28.470.707/0001-80), INAPTA desde 28/01/2026, pago até 24/03/2026.
3. H-PORTE comparava a SOMA de todos os anos com o teto ANUAL da LC 123. Ex.: 08.746.676/0001-30, EPP,
   R$ 5.568.761,43 somados — nenhum ano passou de R$ 4.514.679,95 (2022), abaixo de R$ 4,8 mi.
4. Foto de terreno/mato com endereço provado não chegava à investigação (só o painel via a classe).
5. A razão capital × recebido saía "1,005×" (separador inglês) para 1.005 vezes.
"""
from __future__ import annotations

import datetime as dt

from compliance_agent import investigacao_dd as I


def _inv(cad, total=0.0, cnpj="11222333000181"):
    return I.investigar(cnpj, cadastral=cad, pagamentos={"total_pago": total},
                        usar_rede=False, geocode=False, usar_beneficios=False)


def _hip(out, codigo):
    return [h for h in out["hipoteses"] if h["codigo"] == codigo]


def _sem_foto(monkeypatch):
    monkeypatch.setattr(I, "_veredito_foto", lambda cnpj: None)


# ── 1/2. motivo da situação cadastral ────────────────────────────────────────────────────────

def test_baixada_por_incorporacao_nao_e_confirmado_de_fachada(monkeypatch):
    _sem_foto(monkeypatch)
    monkeypatch.setattr(I, "_situacao_com_data", lambda c, db_path=None: ("BAIXADA", dt.date(2021, 5, 3)))
    monkeypatch.setattr(I, "_motivo_situacao", lambda c: "02")
    monkeypatch.setattr(I, "_ultimo_pagamento_ob", lambda c, db_path=None: dt.date(2025, 8, 26))
    out = _inv({"situacao": "BAIXADA"}, total=142_040_222.53, cnpj="33000118000179")
    h = _hip(out, "H-SITUACAO")
    assert len(h) == 1
    assert h[0]["status"] == "INDICIO" and h[0]["nivel"] == "BAIXO"
    assert "incorpora" in h[0]["evidencia"].lower()
    assert "sucessora" in h[0]["evidencia"].lower()


def test_inexistencia_de_fato_e_o_sinal_mais_forte(monkeypatch):
    _sem_foto(monkeypatch)
    monkeypatch.setattr(I, "_situacao_com_data", lambda c, db_path=None: ("INAPTA", dt.date(2026, 1, 28)))
    monkeypatch.setattr(I, "_motivo_situacao", lambda c: "15")
    monkeypatch.setattr(I, "_ultimo_pagamento_ob", lambda c, db_path=None: dt.date(2026, 3, 24))
    out = _inv({"situacao": "INAPTA"}, total=568_209_565.72, cnpj="28470707000180")
    h = _hip(out, "H-SITUACAO")[0]
    assert h["status"] == "CONFIRMADO" and h["nivel"] == "ALTO"
    assert "inexist" in h["titulo"].lower()
    assert h["peso"] > 20


def test_baixa_comum_com_pagamento_posterior_segue_confirmada(monkeypatch):
    _sem_foto(monkeypatch)
    monkeypatch.setattr(I, "_situacao_com_data", lambda c, db_path=None: ("BAIXADA", dt.date(2024, 1, 10)))
    monkeypatch.setattr(I, "_motivo_situacao", lambda c: "01")
    monkeypatch.setattr(I, "_ultimo_pagamento_ob", lambda c, db_path=None: dt.date(2024, 6, 1))
    h = _hip(_inv({"situacao": "BAIXADA"}, total=1_000_000), "H-SITUACAO")[0]
    assert h["status"] == "CONFIRMADO" and h["peso"] == 20


# ── 3. porte: teto ANUAL contra o pico ANUAL ─────────────────────────────────────────────────

def test_soma_plurianual_acima_do_teto_sem_nenhum_ano_acima_nao_dispara(monkeypatch):
    _sem_foto(monkeypatch)
    monkeypatch.setattr(I, "_pico_anual_ob", lambda c: (2022, 4_514_679.95))
    out = _inv({"porte": "Empresa de Pequeno Porte"}, total=5_568_761.43, cnpj="08746676000130")
    assert not _hip(out, "H-PORTE")
    assert out["cobertura"]["porte"].startswith("verificado")


def test_ano_acima_do_teto_dispara_citando_o_ano(monkeypatch):
    _sem_foto(monkeypatch)
    monkeypatch.setattr(I, "_pico_anual_ob", lambda c: (2025, 15_639_990.33))
    out = _inv({"porte": "Microempresa"}, total=19_429_176.40, cnpj="35208086000127")
    h = _hip(out, "H-PORTE")[0]
    assert "2025" in h["evidencia"] and "15.639.990,33" in h["evidencia"]


def test_teto_e_limite_inclusivo(monkeypatch):
    """LC 123 art. 3º: 'igual ou inferior a' — exatamente no teto é lícito."""
    _sem_foto(monkeypatch)
    monkeypatch.setattr(I, "_pico_anual_ob", lambda c: (2024, 360_000.00))
    assert not _hip(_inv({"porte": "Microempresa"}, total=700_000), "H-PORTE")


def test_sem_pico_anual_degrada_para_baixo_declarando_o_limite(monkeypatch):
    _sem_foto(monkeypatch)
    monkeypatch.setattr(I, "_pico_anual_ob", lambda c: None)
    h = _hip(_inv({"porte": "Microempresa"}, total=2_000_000), "H-PORTE")[0]
    assert h["nivel"] == "BAIXO" and "não foi apurado" in h["evidencia"]


# ── 4. foto do lote ──────────────────────────────────────────────────────────────────────────

def test_foto_de_mato_com_endereco_provado_vira_hipotese(monkeypatch):
    monkeypatch.setattr(I, "_veredito_foto", lambda cnpj: {
        "status": "INDICIO", "nivel": "MEDIO", "evidencia": "Foto ... mostra **area aberta rural** ... in loco.",
        "explicacao_inocente": "imagem antiga", "prova_endereco": True, "motivos_sem_prova": []})
    out = _inv({}, total=2_000_000, cnpj="12768193000104")
    h = _hip(out, "H-FOTO-TERRENO")
    assert h and h[0]["status"] == "INDICIO"
    assert out["cobertura"]["foto_sede"].startswith("INDICIO")


def test_foto_que_nao_prova_endereco_fica_indisponivel_e_nao_vira_hipotese(monkeypatch):
    monkeypatch.setattr(I, "_veredito_foto", lambda cnpj: {
        "status": "INDISPONIVEL", "evidencia": "não prova", "prova_endereco": False,
        "motivos_sem_prova": ["coordenada aproximada (GEOMETRIC_CENTER)"]})
    out = _inv({}, total=2_000_000)
    assert not _hip(out, "H-FOTO-TERRENO")
    assert out["cobertura"]["foto_sede"].startswith("INDISPONIVEL")
    assert "GEOMETRIC_CENTER" in out["cobertura"]["foto_sede"]


# ── 5. formato da razão ──────────────────────────────────────────────────────────────────────

def test_razao_capital_em_padrao_brasileiro(monkeypatch):
    _sem_foto(monkeypatch)
    h = _hip(_inv({"capital": 10_000}, total=10_046_946.73), "H-CAPITAL")[0]
    assert "1.005×" in h["evidencia"] and "1,005×" not in h["evidencia"]


def test_investigacao_devolve_a_combinacao_dos_validadores(monkeypatch):
    _sem_foto(monkeypatch)
    out = _inv({}, total=1_000)
    assert "validadores_sede" in out
    v = out["validadores_sede"]
    assert v is None or (v["grau"] in ("🔴", "🟡", "🟢", "⚪") and v["explicacao_inocente"])
