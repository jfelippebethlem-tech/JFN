# -*- coding: utf-8 -*-
"""O4.10 — decisões delegadas de 24/11/2026 fechadas no código (sombra): D5, D7, D9, D10 e o fechamento dos 4 erros
graves do `rules.ob_favorecido_doerj_cruzado`. Cada decisão tem controle positivo E negativo.
Fontes e efeito medido: ~/vault/refatoracao/RELATORIO-JURIDICO-UNICO-20261124.md."""
from __future__ import annotations

from datetime import date as D

import pytest

from compliance_agent.aplicacao.estagios import calibrar as C
from compliance_agent.aplicacao.estagios import elegibilidade as E
from compliance_agent.dominio.pagamento import NaturezaPagamento as NP, natureza_pagamento
from compliance_agent.limites_dispensa import (PUBLICACAO_MP961, limite_dispensa, situacao_no_teto, teto_dispensa,
                                               teto_para_valor, TetoIndeterminado)
from compliance_agent.qualidade import detectores as Q
from compliance_agent.qualidade import ouro as O


# ── D9: exercício partido sem data do fato → faixa; o valor decide ──────────────────────────────────────────────
@pytest.mark.parametrize("kw, faixa", [
    (dict(lei="8666", tipo="compras", ano=2018), (8000.00, 17600.00)),       # D9412 em 19/07/2018
    (dict(lei="8666", tipo="obras", ano=2018), (15000.00, 33000.00)),
    (dict(lei="8666", tipo="compras", ano=2020), (17600.00, 50000.00)),      # calamidade/MP 961
    (dict(lei="8666", tipo="obras", ano=2020), (33000.00, 100000.00)),
    (dict(lei="8666", tipo="compras", data_fato=D(2020, 4, 10)), (17600.00, 50000.00)),   # antes da MP existir
    (dict(lei="8666", tipo="compras", ano=2018, ente="consorcio_publico"), (16000.00, 35200.00)),
])
def test_d9_faixa_quando_o_exercicio_e_partido(kw, faixa):
    t = teto_dispensa(**kw)
    assert t.estado == "INDETERMINADO" and t.valor is None and t.faixa == faixa and t.inclusivo is True


@pytest.mark.parametrize("valor, sit, teto", [
    (8000.00, "DENTRO", 8000.00),         # "até": inclusivo sob as duas leis
    (8000.01, "INDETERMINADO", None),     # entre os dois tetos: a data decide e ela não está na base
    (17600.00, "INDETERMINADO", None),
    (17600.01, "ACIMA", 17600.00),        # acima de todos: acima sob qualquer data
    (None, "INDETERMINADO", None),
])
def test_d9_o_valor_decide_so_quando_todas_as_datas_concordam(valor, sit, teto):
    t = teto_dispensa(lei="8666", tipo="compras", ano=2018)
    assert situacao_no_teto(valor, t) == sit and teto_para_valor(valor, t) == teto


def test_d9_controle_negativo_com_data_o_teto_e_determinado():
    assert teto_dispensa(lei="8666", tipo="compras", data_fato=D(2018, 7, 18)).valor == 8000.00
    assert teto_dispensa(lei="8666", tipo="compras", data_fato=D(2018, 7, 19)).valor == 17600.00
    assert teto_dispensa(lei="8666", tipo="compras", data_fato=PUBLICACAO_MP961).valor == 50000.00
    assert teto_dispensa(lei="8666", tipo="obras", data_fato=D(2020, 3, 19)).valor == 33000.00
    t = teto_dispensa(lei="8666", tipo="compras", data_fato=D(2019, 5, 2))
    assert t.estado == "DETERMINADO" and t.faixa is None and situacao_no_teto(17600.00, t) == "DENTRO"
    assert situacao_no_teto(17600.01, t) == "ACIMA"


def test_d9_mp961_publicada_em_07_05_2020_e_o_caminho_antigo_nao_muda():
    assert PUBLICACAO_MP961 == D(2020, 5, 7)            # MPV961.htm: "publicado no DOU de 7.5.2020"; art. 3º
    with pytest.raises(TetoIndeterminado):              # o atalho com lei/data segue levantando, sem número
        limite_dispensa(2018, "compras", lei="8666")
    assert limite_dispensa(2018, "compras") == 17600.00  # caminho antigo (sem lei/ente/data): exatamente o anterior


# ── D10: 14.065 sem o dobro do art. 24 §1º → faixa só para consórcio e agência executiva ─────────────────────────
@pytest.mark.parametrize("ente, tipo, faixa", [
    ("consorcio_publico", "compras", (50000.00, 100000.00)),
    ("agencia_executiva", "obras", (100000.00, 200000.00)),
])
def test_d10_faixa_dobrada_so_para_consorcio_e_agencia(ente, tipo, faixa):
    t = teto_dispensa(lei="14065", tipo=tipo, ano=2020, ente=ente)
    assert t.estado == "INDETERMINADO" and t.faixa == faixa
    assert situacao_no_teto(faixa[0], t) == "DENTRO" and situacao_no_teto(faixa[0] + 0.01, t) == "INDETERMINADO"
    assert situacao_no_teto(faixa[1] + 0.01, t) == "ACIMA"


def test_d10_controle_negativo_administracao_direta_e_estatal_sem_faixa():
    t = teto_dispensa(lei="14065", tipo="compras", ano=2020)
    assert t.estado == "DETERMINADO" and t.valor == 50000.00 and t.faixa is None
    t = teto_dispensa(lei="14065", tipo="compras", ano=2020, ente="empresa_publica")
    assert t.valor == 50000.00 and any("13.303" in r for r in t.ressalvas)


# ── D9 na E9: o teto por valor ────────────────────────────────────────────────────────────────────────────────
def test_d9_e9_teto_por_valor():
    assert E._teto("L8666", "II", 2018, None, False, 5000.00)[0] == 8000.00
    v, fonte = E._teto("L8666", "II", 2018, None, False, 12000.00)
    assert v is None and "INDETERMINADO" in fonte
    assert E._teto("L8666", "II", 2018, None, False, 40000.00)[0] == 17600.00
    assert E._teto("L8666", "II", 2019, None, False, 12000.00)[0] == 17600.00       # negativo: ano inteiro


# ── D5 / D7: natureza do pagamento ──────────────────────────────────────────────────────────────────────────────
def test_d5_mod50_sem_contraprestacao_nao_decide_fornecedor():
    for nd in ("335041", "335043"):
        d = natureza_pagamento(natureza_despesa=nd, natureza_juridica_credor="3999")
        assert d.natureza is NP.TRANSFERENCIA and d.credor_e_fornecedor is None and d.nao_e_contratacao_nova
        assert any("AAE" in r for r in d.ressalvas)
    f = E.Fatos(unidade="ob_siafe", chave="x", paga=True, credor_classe="OS_OSC", natureza_despesa="335043",
                natureza_pagamento="TRANSFERENCIA", nao_e_contratacao_nova=True, credor_e_fornecedor=None)
    assert E._ob_fornecedor(f) == "?:TRANSFERENCIA_INSTRUMENTO" and E._ob_execucao(f) == "?:TRANSFERENCIA_INSTRUMENTO"
    assert E._ob_soma_art75(f) == "I:REGIME_PROPRIO_MROSC"


def test_d5_controle_negativo_contrato_de_gestao_segue_fornecedor():
    d = natureza_pagamento(natureza_despesa="335085", natureza_juridica_credor="3999")
    assert d.credor_e_fornecedor is True                      # OS (el. 85): fornecedor de regime próprio (dono)
    d = natureza_pagamento(natureza_despesa="335039", natureza_juridica_credor="3999")
    assert d.credor_e_fornecedor is True


def test_d7_el37_sem_vinculo_indeterminado_mas_fora_da_soma():
    d = natureza_pagamento(natureza_despesa="339037")
    assert d.natureza is NP.INDETERMINADO and d.nao_e_contratacao_nova is True and d.credor_e_fornecedor is True
    f = E.Fatos(unidade="ob_siafe", chave="x", paga=True, credor_classe="PJ_PRIVADA", natureza_despesa="339037",
                elemento="37", natureza_pagamento=d.natureza.value, nao_e_contratacao_nova=True,
                credor_e_fornecedor=True)
    assert E._ob_soma_art75(f) == "I:SERVICO_CONTINUO" and E._ob_execucao(f) == "?:SEM_VINCULO"
    assert E._ob_fornecedor(f) == "E"


def test_d7_controle_negativo_vinculo_conferido_ou_negado():
    assert natureza_pagamento(natureza_despesa="339037", vinculo_contrato=True).natureza is NP.PARCELA_CONTRATO
    d = natureza_pagamento(natureza_despesa="339037", vinculo_contrato=False)
    assert d.natureza is NP.CONTRATACAO_NOVA and d.nao_e_contratacao_nova is False


# ── doerj: erro grave fechado na origem não reabre pelo mesmo conferido ───────────────────────────────────────
def _itens_fora_do_ouro(n):
    """ids de alerta que NÃO caem nos blocos reservados ao ouro (senão a calibração não os conta)."""
    out, i = [], 0
    while len(out) < n:
        it = {"detector": "d.x", "item": f"alerta:{i}", "processo": None, "entidade": None, "orgao": None,
              "periodo": None}
        i += 1
        if not O.reservado_ouro(O.bloco(it)):
            out.append(it["item"])
    return out


A1, A2 = _itens_fora_do_ouro(2)


def _entrada_fechada():
    return {"manchete": False, "dominio": "OB recente", "estado": "ativo",
            "fp_medida": {"data": "2026-11-24", "amostra": "x", "taxa": "x", "fonte_primaria": "x", "onde": "x",
                          "n": 5, "falsos": 4, "estratificada": False, "cobertura": None},
            "calibracao": {"erro_grave_aberto": None,
                           "erro_grave_fechado": [{"id": A1, "motivo": "corrigido_na_origem"}]}}


def _conf(item, grave=True):
    return {"detector": "d.x", "item": item, "origem": "legado", "revisor": "claude-opus-5-5", "processo": None,
            "entidade": None, "orgao": None, "periodo": None, "falso": True, "grave": grave}


def test_erro_grave_fechado_nao_reabre_pelo_conferido_antigo():
    r = C.calibrar_entrada("d.x", _entrada_fechada(), [_conf(A1)], hoje=D(2026, 11, 25), quem="t", forcar=True)
    assert r["graves_novos"] == []
    assert not r["campos"]["calibracao"]["erro_grave_aberto"]
    assert r["campos"]["calibracao"]["erro_grave_fechado"][0]["id"] == A1


def test_erro_grave_novo_reabre_controle_positivo():
    r = C.calibrar_entrada("d.x", _entrada_fechada(), [_conf(A1), _conf(A2)], hoje=D(2026, 11, 25), quem="t",
                           forcar=True)
    assert r["graves_novos"] == [A2] and r["campos"]["calibracao"]["erro_grave_aberto"] == [A2]


def test_registro_doerj_fechado_e_tier2():
    e = Q.carregar()["rules.ob_favorecido_doerj_cruzado"]
    fech = {g["id"] for g in e["calibracao"]["erro_grave_fechado"]}
    assert fech == {"alerta:96896", "alerta:96904", "alerta:155748", "alerta:158978"}
    assert all(g["motivo"] == "corrigido_na_origem" for g in e["calibracao"]["erro_grave_fechado"])
    assert not e["calibracao"]["erro_grave_aberto"] and e["manchete"] is False
    assert Q.avaliar_tier(e, D(2026, 11, 25))["tier"] == 2
