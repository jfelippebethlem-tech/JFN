# -*- coding: utf-8 -*-
"""Veredito da FOTO de fachada — a foto precisa provar que é do endereço antes de ser julgada.

Casos reais do acervo (verificacao_sede, conjunto de controle rotulado à mão em 14/11/2026):

- Itaperuna (CEP 28300000, genérico do município): a MESMA foto de um prédio residencial
  ("Vogue") estava gravada para 10 empresas de endereços diferentes, todas com geo_tipo ROOFTOP.
  O geocodificador caiu no centro da cidade; a foto não é de nenhum dos lotes.
- Av. Ayrton Senna 2600, BLC 001 LOJ G (Barra): ROOFTOP, a foto mostra barracos de favela
  ("construcao_precaria_barraco", 90%) — o cadastro diz LOJA em bloco comercial. Foto de outro ponto.
- Estrada da Meia Noite 2687 (São Gonçalo, CEP 24738295, ROOFTOP, coordenada única): terreno
  aberto com mato — a foto que deve virar indício (nunca acusação sozinha).
- Av. Marquês de Baependi 61 (Duque de Caxias): o VLM disse "barraco"; a foto é uma casa de
  alvenaria com portão "GARAGEM" e o número 61 visível — falso positivo do VLM.
- Rodovia BR 040 / GEOMETRIC_CENTER e logradouro "S/N": foto da pista, não de um lote.
"""
from __future__ import annotations

from compliance_agent.fachada_foto import (cep_generico, credito_de_terceiro, prova_de_endereco,
                                           veredito_foto)


def _reg(**kw):
    base = {"visual_classe": "area_aberta_rural", "visual_conf": 0.8, "geo_tipo": "ROOFTOP",
            "endereco": "ESTRADA, DA MEIA NOITE, 2687, SACRAMENTO, SAO GONCALO, RJ, 24738295",
            "numero": "2687", "complemento": "", "cep": "24738295", "enderecos_na_coordenada": 1}
    base.update(kw)
    return base


# ── controle POSITIVO: mato em endereço provado vira indício ───────────────────────────────────

def test_mato_em_endereco_provado_vira_indicio_com_explicacao_inocente():
    v = veredito_foto(_reg())
    assert v["status"] == "INDICIO"
    assert v["prova_endereco"] is True
    assert "in loco" in v["evidencia"]
    assert v["explicacao_inocente"]          # nenhum validador condena sozinho


def test_terreno_baldio_provado_tambem_e_indicio():
    assert veredito_foto(_reg(visual_classe="terreno_baldio"))["status"] == "INDICIO"


def test_classe_do_vlm_com_espaco_ou_caixa_nao_some():
    """'Terreno baldio' (espaço, maiúscula) caía em 'indeterminado' — mato virava normal."""
    assert veredito_foto(_reg(visual_classe="Terreno baldio"))["status"] == "INDICIO"


# ── foto de OUTRO LUGAR: não acusa NEM absolve ───────────────────────────────────────────────

def test_mesma_foto_para_varios_enderecos_nao_prova_nada():
    """Itaperuna: 10 endereços distintos na mesma coordenada ROOFTOP."""
    r = _reg(visual_classe="predio_residencial", enderecos_na_coordenada=10,
             endereco="RUA, RUI BARBOSA, 131, CENTRO, ITAPERUNA, RJ, 28300000", cep="28300000",
             numero="131")
    v = veredito_foto(r)
    assert v["status"] == "INDISPONIVEL"
    assert v["prova_endereco"] is False
    assert any("10 endereços" in m for m in v["motivos_sem_prova"])


def test_coordenada_aproximada_nao_prova_o_lote():
    for tipo in ("GEOMETRIC_CENTER", "APPROXIMATE", "RANGE_INTERPOLATED", None, ""):
        v = veredito_foto(_reg(geo_tipo=tipo))
        assert v["status"] == "INDISPONIVEL", tipo


def test_sem_numero_nao_prova_o_lote():
    for num in ("S/N", "SN", "0", "", None):
        assert veredito_foto(_reg(numero=num))["status"] == "INDISPONIVEL", num


def test_numero_extraido_do_endereco_quando_falta_o_campo():
    r = _reg(numero=None, endereco="RODOVIA, BR 040, SN, RODOVIA BR 040, AREAL, RJ, 25845000")
    r.pop("numero")
    assert prova_de_endereco(r)[0] is False


def test_cep_generico_de_municipio_nao_prova_o_lote():
    assert cep_generico("28300000") and cep_generico("26900000")
    assert not cep_generico("24738295") and not cep_generico("")
    assert veredito_foto(_reg(cep="28300000"))["status"] == "INDISPONIVEL"


def test_imagem_de_terceiro_nao_prova_o_lote():
    """Painéis enviados por usuários (© The TMax, dashcam BLACKVUE) não têm posição garantida."""
    assert credito_de_terceiro("ee PMR © The Titax")
    assert credito_de_terceiro("KUVJE DR9IB@M-1CH/UHD")
    assert not credito_de_terceiro("| ' Se \"fg Google")
    assert not credito_de_terceiro("")
    assert veredito_foto(_reg(credito_imagem="© Oncompany"))["status"] == "INDISPONIVEL"


def test_loja_em_bloco_comercial_com_foto_de_barraco_e_outro_ponto():
    """Av. Ayrton Senna 2600 BLC 001 LOJ G: cadastro comercial × foto de favela = foto de outro ponto."""
    r = _reg(visual_classe="terreno_baldio", complemento="BLC 001 LOJ G BLC 004 SAL 0226", numero="02600",
             endereco="AVENIDA, AYRTON SENNA, 02600, BLC 001 LOJ G, BARRA DA TIJUCA, RIO DE JANEIRO, RJ, 22775003",
             cep="22775003")
    v = veredito_foto(r)
    assert v["status"] == "INDISPONIVEL"
    assert "contradiz" in v["evidencia"].lower()


# ── falso positivo do VLM: 'barraco' não acusa sozinho ───────────────────────────────────────

def test_barraco_do_vlm_vai_para_revisao_humana_e_nao_acusa():
    """Marquês de Baependi 61: casa de alvenaria classificada 'barraco'."""
    v = veredito_foto(_reg(visual_classe="construcao_precaria_barraco", numero="61", cep="25223360"))
    assert v["status"] == "INDISPONIVEL"
    assert v["revisar_humano"] is True


# ── fachada boa: só absolve com endereço provado ─────────────────────────────────────────────

def test_comercial_em_endereco_provado_afasta():
    assert veredito_foto(_reg(visual_classe="comercial_industrial"))["status"] == "AFASTADO"


def test_comercial_em_coordenada_aproximada_nao_absolve():
    """Foto da rua genérica classificada 'comercial' não pode virar 'sede real'."""
    v = veredito_foto(_reg(visual_classe="comercial_industrial", geo_tipo="GEOMETRIC_CENTER"))
    assert v["status"] == "INDISPONIVEL"


def test_sem_foto_e_indisponivel_nunca_zero():
    v = veredito_foto(_reg(visual_classe=""))
    assert v["status"] == "INDISPONIVEL" and v["prova_endereco"] is None


def test_mesmo_lote_com_zero_a_esquerda_e_um_endereco_so():
    from compliance_agent.fachada_foto import _chave_endereco
    assert (_chave_endereco("AVENIDA, NELSON CARDOSO, 00309, SAL 0502, TAQUARA")
            == _chave_endereco("AVENIDA, NELSON CARDOSO, 309, LOJA A, TAQUARA"))


def test_estabelecimento_fechado_abandonado_vai_para_revisao_e_nao_absolve():
    """15/11/2026, controle sintético (Higgsfield): loja com porta de aço trancada, grafite e letreiro vazio saía
    'comercial_industrial' → AFASTADO ("compatível com sede real"). Fechada na hora da foto não é inexistente
    (domingo, noite), então nem absolve nem acusa: olho humano."""
    v = veredito_foto(_reg(visual_classe="estabelecimento_fechado_abandonado"))
    assert v["status"] == "INDISPONIVEL" and v["revisar_humano"] is True
    assert "fora do expediente" in v["explicacao_inocente"]


def test_vlm_conhece_a_classe_fechado_abandonado():
    from compliance_agent.verificacao_endereco import _CLASSES_VISUAIS
    assert "estabelecimento_fechado_abandonado" in _CLASSES_VISUAIS
