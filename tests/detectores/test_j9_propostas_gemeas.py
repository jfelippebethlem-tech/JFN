# -*- coding: utf-8 -*-
"""J9 · propostas gêmeas — o detector que existia órfão e agora é alcançável pelo pipeline.

O motor (`sei/conluio_propostas`) tem sua própria bateria em `tests/test_conluio_propostas_gemeas.py`.
Aqui se testa o CONTRATO de detector: schema, `nao_avaliavel` honesto sem par para comparar, grau por
força do indício, exculpatória que rebaixa sem silenciar, e a evidência citável no resultado.
"""
from __future__ import annotations

from compliance_agent.detectores import REGISTRO
from compliance_agent.detectores.j9_propostas_gemeas import J9PropostasGemeas

_D = J9PropostasGemeas()
_CTX = {"processo": "SEI-260007/004415/2025"}


def _itens(fator=1.0, n=6):
    return [{"descricao": f"parafuso sextavado inox 3/{i}", "valor_unitario": (100 + i * 7) * fator}
            for i in range(2, 2 + n)]


def test_esta_no_registro_e_alcancavel():
    """A razão de existir deste arquivo: o motor tinha teste verde e ZERO callers."""
    assert "J9" in REGISTRO
    assert REGISTRO["J9"].familia == "conluio"


def test_sem_par_para_comparar_e_nao_avaliavel_com_motivo():
    """Uma proposta só não é 'sem conluio': é 'sem como comparar'. Campo ausente ≠ 0."""
    r = _D.avaliar({**_CTX, "propostas": [{"fornecedor": "ALFA", "itens": _itens()}]})
    assert r.status == "nao_avaliavel"
    assert r.score == 0.0
    assert "DUAS peças" in r.motivo_refutacao or "mínimo" in r.motivo_refutacao
    assert "PNCP" in r.motivo_refutacao, "o gap de fonte precisa ficar dito no resultado"


def test_contexto_vazio_nao_inventa_indicio():
    """Exigência do registro: detector não pode produzir achado com contexto mínimo."""
    r = _D.avaliar(_CTX)
    assert r.status == "nao_avaliavel" and r.score == 0.0 and r.evidencia == []


def test_markup_de_5_por_cento_confirma_e_traz_evidencia():
    r = _D.avaliar({**_CTX, "propostas": [
        {"fornecedor": "ALFA", "itens": _itens()},
        {"fornecedor": "BETA", "itens": _itens(fator=0.95)}]})
    assert r.status == "confirmado"
    assert r.score >= 0.7, "razão constante em toda a lista é indício FORTE"
    assert r.valores["por_tipo"].get("markup_uniforme") == 1
    assert r.evidencia, "sem evidência o achado não é conferível"
    assert "-5.0%" in r.evidencia[0]["trecho"] or "-5.0" in r.evidencia[0]["trecho"]


def test_trecho_identico_entra_na_evidencia_verbatim():
    """É o pedido do dono: as mesmas frases/parágrafos, citadas — não um índice de similaridade."""
    trecho = ("Declaramos ainda que os precos ofertados incluem todos os tributos encargos sociais "
              "e demais despesas indiretas incidentes sobre o objeto licitado")
    r = _D.avaliar({**_CTX, "propostas": [
        {"fornecedor": "ALFA", "texto": "Proposta da ALFA para o certame. " + trecho},
        {"fornecedor": "BETA", "texto": "Proposta da BETA, outro CNPJ. " + trecho}]})
    assert r.status == "confirmado"
    achou = [e for e in r.evidencia if "trecho idêntico" in e["fonte"]]
    assert achou, "o trecho verbatim tem de chegar à evidência"
    assert "tributos encargos sociais" in achou[0]["trecho"]


def test_dispersao_de_concorrencia_real_e_DESCARTADO_nao_nao_avaliavel():
    """Descartado = houve juízo e não achou. nao_avaliavel = não houve juízo. Não confundir."""
    irregular = [{"descricao": x["descricao"], "valor_unitario": x["valor_unitario"] * f}
                 for x, f in zip(_itens(), (0.88, 1.04, 0.97, 1.12, 0.91, 1.06))]
    r = _D.avaliar({**_CTX, "propostas": [
        {"fornecedor": "ALFA", "itens": _itens()},
        {"fornecedor": "BETA", "itens": irregular}]})
    assert r.status == "descartado"
    assert r.score == 0.0
    assert r.explicacao_inocente


def test_mercado_homogeneo_rebaixa_o_grau_sem_apagar_o_achado():
    """Commodity produz preço igual licitamente — mas o indício continua registrado."""
    iguais = [dict(x) for x in _itens()]
    ctx = {**_CTX, "propostas": [{"fornecedor": "ALFA", "itens": _itens()},
                                 {"fornecedor": "BETA", "itens": iguais}]}
    sem = _D.avaliar(ctx)
    com = _D.avaliar({**ctx, "mercado_homogeneo": True})
    assert sem.status == com.status == "confirmado", "a exculpatória não pode SILENCIAR o achado"
    assert com.score < sem.score, "ela tem de rebaixar o grau"
    assert com.valores["exculpatorias"]["mercado_homogeneo"] is True


def test_schema_serializa_no_padrao_do_spec():
    r = _D.avaliar({**_CTX, "propostas": [
        {"fornecedor": "ALFA", "itens": _itens()},
        {"fornecedor": "BETA", "itens": _itens(fator=0.95)}]})
    d = r.to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "J9"
    assert 0.0 <= d["score"] <= 1.0
