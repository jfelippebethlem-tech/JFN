# -*- coding: utf-8 -*-
"""C8 — servidor público no QSA. Três situações jurídicas distintas, e uma armadilha de dado.

A armadilha: as duas fontes mascaram o CPF em JANELAS DIFERENTES. A RFB publica os dígitos D4–D9
(`***364817**`) e a folha publica D3–D8 (`XX000057XXX`). O trecho comparável é D4–D8. Comparar as
strings inteiras como se fossem a mesma janela descartaria como "homônimo" quase todo casamento
verdadeiro — e o teste abaixo prova que a régua certa é a do deslocamento.

As três situações: impedimento do art. 9º (servidor do PRÓPRIO órgão) · vedação de gerência
(administra empresa privada, ainda que de outro órgão) · mero quotista, que pode ser lícito.
"""
from __future__ import annotations

from compliance_agent.detectores.c8_servidor_socio import C8ServidorSocio, casa_fragmento

D = C8ServidorSocio()


def _ctx(socios=None, servidores=None, orgao=None):
    return {"processo": "P1", "socios": socios, "servidores": servidores,
            "orgao_contratante": orgao}


def _socio(nome="JOSE DA SILVA", doc="***364817**", qual="49-Sócio-Administrador"):
    return {"nome": nome, "doc": doc, "qualificacao": qual}


def _serv(nome="JOSE DA SILVA", cpf="XX036481XXX", orgao="SECRETARIA DE OBRAS",
          cargo="ENGENHEIRO", vinculo="EFETIVO"):
    return {"nome": nome, "cpf": cpf, "orgao": orgao, "cargo": cargo, "vinculo": vinculo}


# ─────────────────── a janela desalinhada das duas máscaras ───────────────────────────────────

def test_fragmentos_da_MESMA_pessoa_casam_apesar_do_deslocamento():
    """RFB `***364817**` (D4–D9) × folha `XX036481XXX` (D3–D8) — o comum é D4–D8."""
    assert casa_fragmento("364817", "036481") is True


def test_fragmentos_de_pessoas_diferentes_nao_casam():
    assert casa_fragmento("364817", "999999") is False


def test_sem_fragmento_de_um_dos_lados_o_resultado_e_indeterminado():
    """`None` ≠ `False`: não poder conferir não é conferir e dar errado."""
    assert casa_fragmento("", "036481") is None
    assert casa_fragmento("364817", "") is None


def test_comparar_as_strings_inteiras_seria_o_erro():
    """Se a régua fosse igualdade direta, o casamento verdadeiro acima daria False."""
    assert "364817" != "036481"


# ─────────────────── as três situações jurídicas ──────────────────────────────────────────────

def test_gerencia_no_PROPRIO_orgao_contratante_e_critico_e_objetivo():
    r = D.avaliar(_ctx([_socio()], [_serv()], orgao="SECRETARIA DE OBRAS"))
    assert r.status == "confirmado" and r.score == 1.0
    assert r.valores["teste_objetivo"] == "violado"
    assert "art. 9" in r.evidencia[0]


def test_gerencia_em_orgao_DIVERSO_e_alto_e_nao_e_teste_objetivo():
    r = D.avaliar(_ctx([_socio()], [_serv(orgao="SECRETARIA DE SAUDE")],
                       orgao="SECRETARIA DE OBRAS"))
    assert r.status == "confirmado" and 0.7 <= r.score < 1.0
    assert r.valores["teste_objetivo"] == "nao_aferivel"
    assert "gerência" in r.evidencia[0]


def test_quotista_SEM_gerencia_em_orgao_diverso_nao_passa_de_medio():
    """Servidor que herdou cotas não é o mesmo caso que servidor que administra a contratada."""
    r = D.avaliar(_ctx([_socio(qual="22-Sócio")], [_serv(orgao="SECRETARIA DE SAUDE")],
                       orgao="SECRETARIA DE OBRAS"))
    assert r.status == "confirmado" and r.score <= 0.6
    assert "pode ser" in r.evidencia[0] or "lícita" in r.evidencia[0]


def test_quotista_no_PROPRIO_orgao_ainda_e_alto():
    """O art. 9º veda a participação, direta ou INDIRETA — não exige gerência."""
    r = D.avaliar(_ctx([_socio(qual="22-Sócio")], [_serv()], orgao="SECRETARIA DE OBRAS"))
    assert 0.7 <= r.score < 1.0


# ─────────────────── corroboração e homônimo ──────────────────────────────────────────────────

def test_casamento_so_por_NOME_rebaixa_um_nivel_e_declara():
    r = D.avaliar(_ctx([_socio(doc="")], [_serv(cpf="")], orgao="SECRETARIA DE OBRAS"))
    assert r.status == "confirmado" and r.score < 1.0
    assert "APENAS POR NOME" in r.evidencia[0]


def test_fragmento_CONFLITANTE_e_homonimo_descartado():
    r = D.avaliar(_ctx([_socio()], [_serv(cpf="XX999999XXX")], orgao="SECRETARIA DE OBRAS"))
    assert r.status == "descartado"
    assert r.valores["homonimos_descartados"] == 1


def test_homonimo_com_UM_candidato_certo_entre_varios_nao_se_perde():
    """Dois servidores com o mesmo nome: um conflita, o outro casa. O certo tem de vencer."""
    r = D.avaliar(_ctx([_socio()],
                       [_serv(cpf="XX999999XXX", orgao="OUTRO"), _serv()],
                       orgao="SECRETARIA DE OBRAS"))
    assert r.status == "confirmado" and r.score == 1.0


# ─────────────────── honestidade ──────────────────────────────────────────────────────────────

def test_sem_QSA_ou_sem_folha_e_nao_avaliavel_nunca_limpo():
    assert D.avaliar(_ctx(None, [_serv()])).status == "nao_avaliavel"
    assert D.avaliar(_ctx([_socio()], None)).status == "nao_avaliavel"


def test_folha_vazia_e_descartado_com_motivo():
    r = D.avaliar(_ctx([_socio()], []))
    assert r.status == "descartado" and "folhas de pagamento" in r.motivo_refutacao


def test_socio_que_nao_esta_na_folha_nao_produz_achado():
    r = D.avaliar(_ctx([_socio(nome="MARIA PRIVADA")], [_serv()]))
    assert r.status == "descartado"


def test_sem_orgao_contratante_nao_inventa_impedimento_do_art_9():
    """Sem saber qual é o órgão, não há como afirmar 'mesmo órgão' — e não se presume."""
    r = D.avaliar(_ctx([_socio()], [_serv()]))
    assert r.valores["orgao_contratante_informado"] is False
    assert r.valores["teste_objetivo"] == "nao_aferivel"


def test_varios_socios_na_folha_saem_contados():
    r = D.avaliar(_ctx([_socio(), _socio(nome="ANA SERVIDORA", doc="***111222**")],
                       [_serv(), _serv(nome="ANA SERVIDORA", cpf="XX011122XXX")],
                       orgao="SECRETARIA DE OBRAS"))
    assert r.valores["n_achados"] == 2
    assert "Outros 1" in r.evidencia[-1]
