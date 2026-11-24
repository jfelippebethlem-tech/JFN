# -*- coding: utf-8 -*-
"""O5.2 — contrato único `compliance_agent/dominio/achado.py` (plano mestre v2 §5; doc 2 §17.2 e §35.1).

Regra recusada = teste vermelho: a regra não decide (status de decisão só via DecisaoHumana), CONCLUSAO_REVISADA
só com confirmado/refutado, ABSTEVE com motivo, INDICIO com Fato de suporte, hash de entradas canônico."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from compliance_agent.dominio.achado import (Achado, DecisaoHumana, ExecucaoRegra, Fato, Papel, StatusAchado,
                                             decidir, hash_entradas)
from compliance_agent.dominio.estados import EstadoSaida

H = "a" * 64


def _exe(**kw):
    d = {"regra_id": "det.X1CrescimentoAditivo", "versao": "x1@abc", "entradas_hash": H, "resultado": {"s": 1},
         "origem": "achado_execucao:1|X1"}
    d.update(kw)
    return ExecucaoRegra(**d)


def _fato(papel=Papel.SUPORTE, **kw):
    d = {"papel": papel, "tipo": "ob", "fonte": "ob_orcamentaria_siafe", "referencia": "2026OB00001",
         "valor": Decimal("1000.00")}
    d.update(kw)
    return Fato(**d)


def _achado(**kw):
    d = {"execucao": _exe(), "estado": EstadoSaida.INDICIO, "observacao": "OB 2026OB00001 de R$ 1.000,00",
         "inferencia": "acréscimo acima do teto", "hipotese": "aditivo acima de 25%",
         "hipoteses_alternativas": ["reforma tem teto de 50%"], "evidencias": [_fato()]}
    d.update(kw)
    return Achado.de_regra(**d)


def test_hash_de_entradas_e_canonico():
    assert hash_entradas({"b": 1, "a": [1, 2]}) == hash_entradas({"a": [1, 2], "b": 1})
    assert hash_entradas({"v": Decimal("1.10")}) != hash_entradas({"v": Decimal("1.1")})   # texto literal conta
    assert len(hash_entradas(None)) == 64


def test_achado_valido_nasce_em_triagem_com_os_tres_planos():
    a = _achado()
    assert a.status is StatusAchado.TRIAGEM and a.qualificacao is None
    assert a.observacao and a.inferencia and a.hipotese


@pytest.mark.parametrize("status", [StatusAchado.CONFIRMADO, StatusAchado.REFUTADO, StatusAchado.ARQUIVADO])
def test_regra_nao_emite_status_de_decisao(status):
    with pytest.raises((ValueError, ValidationError)):
        _achado(status=status, estado=EstadoSaida.CONCLUSAO_REVISADA)


def test_conclusao_revisada_so_com_confirmado_ou_refutado():
    with pytest.raises(ValidationError):
        Achado(**{**_achado().model_dump(), "estado": EstadoSaida.CONCLUSAO_REVISADA})
    with pytest.raises(ValidationError):
        Achado(**{**_achado().model_dump(), "status": StatusAchado.CONFIRMADO})


def test_absteve_exige_motivo():
    with pytest.raises(ValidationError):
        _achado(estado=EstadoSaida.ABSTEVE)
    assert _achado(estado=EstadoSaida.ABSTEVE, motivo_estado="sem texto do contrato").motivo_estado


def test_indicio_exige_fato_de_suporte():
    with pytest.raises(ValidationError):
        _achado(evidencias=[_fato(papel=Papel.CONTEXTO)])
    assert _achado(estado=EstadoSaida.AUSENTE, evidencias=[]).estado is EstadoSaida.AUSENTE


def test_campos_invalidos_sao_recusados():
    with pytest.raises(ValidationError):
        _exe(entradas_hash="xyz")
    with pytest.raises(ValidationError):
        _fato(papel="apoio")
    with pytest.raises(ValidationError):
        _fato(estado="provado")
    with pytest.raises(ValidationError):
        _fato(documento_sha256="nao-hex")
    with pytest.raises(ValidationError):
        _achado(campo_novo=1)                                       # extra="forbid"


def test_decisao_humana_separada_e_com_autor():
    agora = datetime(2026, 11, 24, tzinfo=timezone.utc)
    with pytest.raises(ValidationError):
        DecisaoHumana(autor="  ", status=StatusAchado.CONFIRMADO, justificativa="x", decidido_em=agora)
    with pytest.raises(ValidationError):
        DecisaoHumana(autor="fiscal", status=StatusAchado.TRIAGEM, justificativa="x", decidido_em=agora)
    a = _achado()
    d = DecisaoHumana(autor="fiscal", status=StatusAchado.CONFIRMADO, justificativa="termo aditivo conferido",
                      decidido_em=agora, encaminhamento="diligência")
    c = decidir(a, d)
    assert (c.status, c.estado) == (StatusAchado.CONFIRMADO, EstadoSaida.CONCLUSAO_REVISADA)
    assert a.status is StatusAchado.TRIAGEM                          # o original não muda
    arq = decidir(c, DecisaoHumana(autor="fiscal", status=StatusAchado.ARQUIVADO, justificativa="prescrito",
                                   decidido_em=agora))
    assert (arq.status, arq.estado) == (StatusAchado.ARQUIVADO, EstadoSaida.INDICIO)


def test_achado_e_imutavel():
    a = _achado()
    with pytest.raises(ValidationError):
        a.status = StatusAchado.CONFIRMADO
