# -*- coding: utf-8 -*-
"""Validadores independentes de sede (pedido do dono, 14/11/2026) e a COMBINAÇÃO deles.

Nenhum validador condena sozinho: o veredito sai da soma, com grau e explicação inocente.
Testes offline — a página do site é injetada; nada aqui toca a rede.
"""
from __future__ import annotations

from compliance_agent.fachada_validadores import (analisar_pagina, checar_site, dominio_corporativo,
                                                  veredito_combinado)

_HTML_IDESI = """<html><body><h1>Instituto IDESI</h1><p>Instituto de Desenvolvimento para Educação, Saúde
e Inclusão — CNPJ 28.470.707/0001-80 · Praça Manoel de Castro, 11, sala 207</p>
<a href="https://www.instagram.com/institutoidesi/">insta</a>
<a href="https://facebook.com/idesi.oficial">fb</a></body></html>"""


def test_dominio_corporativo_descarta_webmail_governo_e_contabilidade():
    assert dominio_corporativo("direcao@institutoidesi.org") == "institutoidesi.org"
    assert dominio_corporativo("fulano@gmail.com") is None
    assert dominio_corporativo("x@educacao.rj.gov.br") is None
    assert dominio_corporativo("meucnpj@contabilizei.com.br", n_empresas_no_dominio=20) is None
    assert dominio_corporativo("") is None and dominio_corporativo("sem-arroba") is None


def test_pagina_que_cita_cnpj_razao_e_endereco():
    r = analisar_pagina(_HTML_IDESI, cnpj="28470707000180",
                        razao="INSTITUTO DE DESENVOLVIMENTO PARA EDUCACAO SAUDE E INCLUSAO",
                        logradouro="PRACA MANOEL DE CASTRO")
    assert r["cita_cnpj"] and r["cita_razao"] and r["cita_endereco"]
    assert sorted(r["redes"]) == ["facebook", "instagram"]


def test_pagina_de_outra_empresa_nao_cita():
    r = analisar_pagina("<html>Loja de sapatos CNPJ 11.222.333/0001-81</html>", cnpj="28470707000180",
                        razao="INSTITUTO DE DESENVOLVIMENTO PARA EDUCACAO", logradouro="PRACA MANOEL DE CASTRO")
    assert not (r["cita_cnpj"] or r["cita_razao"] or r["cita_endereco"])


def test_checar_site_usa_fetch_injetado_e_classifica():
    r = checar_site("institutoidesi.org", "28470707000180", "INSTITUTO IDESI", "PRACA MANOEL DE CASTRO",
                    fetch=lambda url: (200, _HTML_IDESI), usar_cache=False)
    assert r["estado"] == "cita_cnpj"
    fora = checar_site("x.com.br", "28470707000180", "X", "Y", fetch=lambda url: (None, ""), usar_cache=False)
    assert fora["estado"] == "fora_do_ar"


# ── combinação: nenhum validador sozinho condena ─────────────────────────────────────────────

def test_um_sinal_sozinho_nunca_vira_vermelho():
    for sinal in ({"foto": "INDICIO"}, {"cep": False}, {"telefone_compartilhado": 5},
                  {"site": "fora_do_ar"}, {"sala_compartilhada": 3}):
        v = veredito_combinado(**sinal)
        assert v["grau"] != "🔴", sinal
        assert v["explicacao_inocente"]


def test_inexistencia_de_fato_mais_foto_de_mato_e_vermelho():
    v = veredito_combinado(foto="INDICIO", inexistente_de_fato=True)
    assert v["grau"] == "🔴"


def test_site_que_cita_o_cnpj_pesa_contra_a_suspeita():
    v = veredito_combinado(foto="INDICIO", cep=False, site="cita_cnpj")
    assert v["grau"] in ("🟢", "🟡")
    assert any("site" in s for s in v["substancia"])


def test_sem_nenhum_validador_e_indisponivel_nao_verde():
    v = veredito_combinado()
    assert v["grau"] == "⚪"
