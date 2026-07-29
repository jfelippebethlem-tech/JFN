# -*- coding: utf-8 -*-
"""Índice doutrinário — e a trava que impede um índice de teses virar fábrica de citação.

`jurisprudencia` guarda súmulas e acórdãos; `base_legal` guarda dispositivos. Falta a TESE, que é
o que liga o dispositivo ao caso na fundamentação. Um índice desses é perigoso por natureza: tese
soa plausível por construção, e a auditoria de 2026-07-27 já achou quatro acórdãos
aritmeticamente impossíveis dentro da base curada da própria casa.

Daí as duas regras que estes testes travam: verbete não conferido sai SEMPRE marcado, e verbete
sem efeito operacional não entra — índice que cresce sem critério vira enciclopédia que ninguém
consulta.
"""
from __future__ import annotations

from compliance_agent.knowledge.doutrina import (
    MARCA_NAO_VERIFICADO,
    VERBETES,
    citar,
    nao_verificados,
    obter,
    por_dispositivo,
    resumo,
    validar,
)


def test_integridade_do_indice():
    assert validar() == []


def test_todo_verbete_declara_efeito_operacional():
    """Doutrina interessante e inconsequente fica de fora."""
    for v in VERBETES.values():
        assert v.efeito, f"{v.id} sem efeito no motor"


def test_verificado_declara_ONDE_foi_conferido():
    for v in VERBETES.values():
        if v.verificado:
            assert v.onde_confere, f"{v.id} verificado sem procedência"


def test_citacao_de_verbete_NAO_conferido_sai_marcada():
    pendentes = nao_verificados()
    assert pendentes, "um índice 100% verificado seria suspeito"
    assert MARCA_NAO_VERIFICADO in citar(pendentes[0])


def test_citacao_de_verbete_conferido_sai_limpa():
    assert MARCA_NAO_VERIFICADO not in citar("dolo_especifico")
    assert "Lei 8.429" in citar("dolo_especifico")


def test_verbete_inexistente_devolve_vazio_nao_quebra():
    assert citar("nao_existe") == "" and obter("") is None


def test_busca_por_dispositivo():
    achados = por_dispositivo("art. 11 V")
    assert achados and achados[0].id == "finalidade_de_beneficio"


def test_resumo_expoe_os_pendentes():
    """A lista de não conferidos nunca pode ficar escondida."""
    r = resumo()
    assert r["nao_verificados"] > 0
    assert set(r["pendentes"]) == set(nao_verificados())


def test_as_teses_que_mudaram_o_codigo_estao_conferidas():
    """As quatro que decidem enquadramento não podem depender de memória."""
    for vid in ("dolo_especifico", "dano_efetivo", "finalidade_de_beneficio",
                "art124_incisos_opostos"):
        assert obter(vid).verificado is True, f"{vid} deveria estar conferido"


def test_a_tese_do_art_124_registra_os_dois_lados_do_teto():
    v = obter("art124_incisos_opostos")
    assert "sujeito ao art. 125" in v.tese and "fora do teto" in v.tese


def test_o_bdi_aponta_para_o_acordao_CORRETO():
    """A base curada trazia 2.622/2015, que o acervo devolve como não confirmado."""
    v = obter("bdi_iss_municipal")
    assert "2.622/2013" in v.fonte and v.verificado is True


def test_verbete_conferido_no_acervo_passa_no_gate_de_citacoes():
    """Fecha o círculo: a fonte citada aqui tem de sobreviver ao anti-alucinação da casa."""
    from compliance_agent.knowledge.tcu_juris_index import verificar_citacao

    achados = verificar_citacao(obter("bdi_iss_municipal").fonte)
    assert achados
    assert achados[0]["status"] in {"confirmado", "indice_ausente"}, achados[0]
