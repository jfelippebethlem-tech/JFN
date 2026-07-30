# -*- coding: utf-8 -*-
"""Telefone e e-mail compartilhados — item I.1.2, e os guardas que impedem a aresta de afogar.

A régua declara `mesmo_telefone` (0,70) e `mesmo_email` (0,80) desde sempre — bem acima de
`mesmo_predio` (0,05) e na faixa de `mesma_sala` (0,75). Nunca foram usadas porque não havia fonte.
E havia: `data/receita_estab.db` guarda 6.171.766 estabelecimentos com telefone e e-mail (83,9% e
69,0%), já indexados. Dado ingerido e sem consumidor — o terceiro caso desta sessão.

O QUE ESTE TESTE PROTEGE são os cortes, não a consulta. Um `GROUP BY` cru daria centenas de milhares
de "vínculos", e a medição mostra por quê:

  · os cinco telefones mais compartilhados do país são `00` (129.152 empresas), `210` (28.628),
    `2122222222` (21.238), `2199999999` (13.234) — preenchimento, não vínculo;
  · 43 telefones ligam mais de mil empresas cada; a faixa com sentido é 2 a 5 (446 mil telefones);
  · os cinco e-mails mais compartilhados são de contabilidade e abertura de empresa
    (`maismei`, `contabilizei`, `btgpactual`, `xpi`) — que é literalmente a explicação inocente que
    a régua já registra em `mesmo_contador` (0,30).

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_contato_compartilhado.py -q
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.osint.contato_compartilhado import (
    TETO_FANOUT,
    TETO_FANOUT_EMAIL,
    dominio_de,
    telefone_valido,
    vinculos_por_contato,
)
from compliance_agent.osint.vinculos import TIPOS_ARESTA

_DDL = """
CREATE TABLE estabelecimentos (
  cnpj TEXT PRIMARY KEY, cnpj_basico TEXT, telefone1 TEXT, telefone2 TEXT,
  correio_eletronico TEXT);
"""


@pytest.fixture()
def base(tmp_path):
    caminho = tmp_path / "estab.db"
    con = sqlite3.connect(caminho)
    con.executescript(_DDL)
    con.commit()
    con.close()
    return str(caminho)


def _ins(caminho, cnpj, tel="", tel2="", email=""):
    con = sqlite3.connect(caminho)
    con.execute("INSERT OR REPLACE INTO estabelecimentos VALUES (?,?,?,?,?)",
                (cnpj, cnpj[:8], tel, tel2, email))
    con.commit()
    con.close()


# ── telefone de preenchimento ────────────────────────────────────────────────

@pytest.mark.parametrize("tel", ["00", "0", "210", "2122222222", "2199999999", "0000000000",
                                 "9999999999", "123"])
def test_telefone_de_preenchimento_e_recusado(tel: str):
    assert telefone_valido(tel) is False, f"{tel} liga dezenas de milhares de empresas — é lixo"


@pytest.mark.parametrize("tel", ["2125550123", "21998877665", "1139650118"])
def test_telefone_plausivel_passa(tel: str):
    assert telefone_valido(tel) is True


# ── as arestas ───────────────────────────────────────────────────────────────

def test_telefone_compartilhado_gera_aresta_forte(base):
    _ins(base, "11111111000100", tel="2125550123")
    _ins(base, "22222222000100", tel="2125550123")
    r = vinculos_por_contato(["11111111000100"], db_estab=base)
    assert len(r["arestas"]) == 1
    a = r["arestas"][0]
    assert a["tipo"] == "mesmo_telefone"
    assert a["forca"] == pytest.approx(TIPOS_ARESTA["mesmo_telefone"].forca)
    assert a["para"] == "22222222000100"
    assert a["explicacao_inocente"], "aresta sem explicação inocente não entra em peça"
    assert a["fonte"].startswith("Receita Federal")


def test_matriz_e_filial_nao_sao_vinculo_entre_empresas(base):
    """Apareceu na primeira amostra real: 00028682000140 × 00028682000655 dividem telefone porque
    são a MESMA empresa. Duas agências do Banco do Brasil pelo e-mail do webmaster, idem."""
    _ins(base, "00028682000140", tel="1135956755", email="contato@x.com.br")
    _ins(base, "00028682000655", tel="1135956755", email="contato@x.com.br")
    r = vinculos_por_contato(["00028682000140"], db_estab=base)
    assert r["arestas"] == [], "matriz/filial da mesma raiz não é vínculo entre empresas"


def test_fanout_de_telefone_derruba_a_aresta(base):
    """Acima do teto o telefone é de prestador de serviço, não elo."""
    _ins(base, "11111111000100", tel="2125550123")
    for i in range(TETO_FANOUT + 2):
        _ins(base, f"9{i}222222000100", tel="2125550123")
    r = vinculos_por_contato(["11111111000100"], db_estab=base)
    assert r["arestas"] == []
    assert r["descartados"]["fanout_telefone"] == 1, "o descarte tem de ser CONTADO, não silencioso"


def test_email_de_contabilidade_vira_mesmo_contador_nao_mesmo_email(base):
    """`abertura@maismei.com.br` liga 17.665 empresas. Força 0,30, não 0,80 — e é a explicação
    inocente que a régua já registrava."""
    _ins(base, "11111111000100", email="abertura@maismei.com.br")
    _ins(base, "22222222000100", email="abertura@maismei.com.br")
    r = vinculos_por_contato(["11111111000100"], db_estab=base)
    assert r["arestas"], "e-mail de contador não desaparece — vira aresta FRACA declarada"
    a = r["arestas"][0]
    assert a["tipo"] == "mesmo_contador"
    assert a["forca"] == pytest.approx(0.30)
    assert "prestador de serviço" in a["explicacao_inocente"]
    assert r["descartados"]["email_de_servico"] == 1


def test_email_muito_compartilhado_tambem_rebaixa(base):
    _ins(base, "11111111000100", email="socios@grupo.com.br")
    for i in range(TETO_FANOUT_EMAIL + 3):
        _ins(base, f"9{i}222222000100", email="socios@grupo.com.br")
    r = vinculos_por_contato(["11111111000100"], db_estab=base)
    assert all(a["tipo"] == "mesmo_contador" for a in r["arestas"])
    assert r["descartados"]["fanout_email"] == 1


def test_email_de_grupo_pequeno_vale_forte(base):
    _ins(base, "11111111000100", email="financeiro@grupoalfa.com.br")
    _ins(base, "22222222000100", email="financeiro@grupoalfa.com.br")
    r = vinculos_por_contato(["11111111000100"], db_estab=base)
    a = r["arestas"][0]
    assert a["tipo"] == "mesmo_email" and a["forca"] == pytest.approx(0.80)


def test_cobertura_declara_quem_nao_tem_registro(base):
    """Empresa sem contato publicado NÃO é empresa sem telefone — é lacuna de fonte."""
    _ins(base, "11111111000100", tel="2125550123")
    r = vinculos_por_contato(["11111111000100", "33333333000100"], db_estab=base)
    c = r["cobertura"]
    assert c["pedidos"] == 2 and c["com_registro"] == 1 and c["sem_registro"] == 1
    assert "lacuna de fonte" in c["nota"]


def test_a_regua_viaja_com_o_resultado(base):
    _ins(base, "11111111000100", tel="2125550123")
    _ins(base, "22222222000100", tel="2125550123")
    r = vinculos_por_contato(["11111111000100"], db_estab=base)
    assert r["regua"]["mesmo_telefone"] == pytest.approx(0.70)
    assert r["regua"]["teto_fanout_telefone"] == TETO_FANOUT
    assert "afogaria" in r["regua"]["por_que"]


def test_base_ausente_e_indisponivel_nao_zero():
    r = vinculos_por_contato(["11111111000100"], db_estab="/tmp/nao_existe_xyz.db")
    assert r["arestas"] == [] and r.get("erro"), (
        "base ausente tem de devolver erro declarado, não lista vazia que se lê como 'sem vínculo'"
    )


def test_dominio_de():
    assert dominio_de("a@b.com.br") == "b.com.br"
    assert dominio_de("sem-arroba") == ""
