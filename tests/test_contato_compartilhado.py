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


# ── filial não é outra empresa (2026-08-06) ──────────────────────────────────

def _base_com(tmp_path, linhas):
    """Base de estabelecimentos mínima: (cnpj, telefone1, telefone2, email)."""
    import sqlite3
    p = tmp_path / "estab.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE estabelecimentos (cnpj TEXT PRIMARY KEY, telefone1 TEXT, "
                "telefone2 TEXT, correio_eletronico TEXT)")
    con.executemany("INSERT INTO estabelecimentos VALUES (?,?,?,?)", linhas)
    con.commit()
    con.close()
    return str(p)


def test_filiais_do_destino_valem_uma_aresta_so(tmp_path):
    """O filtro `substr(cnpj,1,8)<>?` tirava as filiais do PRÓPRIO alvo, mas as do DESTINO
    contavam uma a uma. Medido em 2026-08-06 sobre os 120 CNPJs vencedores do acervo: das 252
    arestas, **65 eram 21 pares de raiz repetidos por filial** — a APPA SERVIÇOS TEMPORÁRIOS e a
    OBJETIVA SERVIÇOS TERCEIRIZADOS dividem o telefone 1147593220 e apareciam 3×, porque a
    OBJETIVA tem 3 filiais com o mesmo número. A aresta é UMA."""
    from compliance_agent.osint.contato_compartilhado import vinculos_por_contato

    db = _base_com(tmp_path, [
        ("05969071000110", "1147593220", "", ""),
        ("10874523000978", "1147593220", "", ""),
        ("10874523001192", "1147593220", "", ""),
        ("10874523001001", "1147593220", "", ""),
    ])
    ar = vinculos_por_contato(["05969071000110"], db_estab=db)["arestas"]
    assert len(ar) == 1, f"filial contada como empresa distinta: {ar}"
    assert ar[0]["para"][:8] == "10874523"


def test_fanout_conta_RAIZ_e_recupera_o_vinculo_real(tmp_path):
    """O erro simétrico, e pior: um telefone compartilhado com 6 filiais de UMA empresa media
    fan-out 7 e era DESCARTADO como contato de prestador — quando é exatamente o vínculo
    procurado. Contar por raiz recupera o falso negativo (fan-out de telefone caiu 30 → 26 e o de
    e-mail 14 → 12 na amostra real)."""
    from compliance_agent.osint.contato_compartilhado import vinculos_por_contato

    linhas = [("05969071000110", "2133334444", "", "")]
    linhas += [(f"108745230009{i:02d}", "2133334444", "", "") for i in range(1, 7)]
    ar = vinculos_por_contato(["05969071000110"], db_estab=_base_com(tmp_path, linhas))["arestas"]
    assert len(ar) == 1, "6 filiais de uma empresa não são fan-out de 7"


def test_mesmo_numero_nos_dois_campos_nao_duplica(tmp_path):
    """Empresa que cadastra o telefone em `telefone1` e `telefone2` gerava a aresta duas vezes —
    foi o único par ainda repetido depois da agregação por raiz."""
    from compliance_agent.osint.contato_compartilhado import vinculos_por_contato

    db = _base_com(tmp_path, [("11389387000136", "2227851280", "2227851280", ""),
                              ("11412771000102", "2227851280", "", "")])
    ar = vinculos_por_contato(["11389387000136"], db_estab=db)["arestas"]
    assert len(ar) == 1, f"o mesmo número em dois campos virou duas arestas: {ar}"


@pytest.mark.parametrize("na,nb,tem", [
    ("2151", "2062", True),   # consórcio × LTDA
    ("2062", "2127", True),   # LTDA × SCP
    ("1333", "2062", True),   # fundo público × LTDA
    ("2143", "2062", True),   # cooperativa × LTDA
    ("2062", "2062", False),  # duas LTDAs — aí o contato dividido pede explicação
    ("2054", "2062", False),  # S/A fechada × LTDA
])
def test_estrutura_juridica_explica_o_contato_dividido(na, nb, tem):
    """Ao percorrer 850 credores, as empresas mais ligadas por contato eram CONSÓRCIOS.

    Consórcio divide telefone e e-mail com as consorciadas POR DESENHO — a lei o define como
    reunião de empresas sem personalidade própria. Idem SCP (aparece o sócio ostensivo) e fundo
    público (que não é empresa). Medido sobre 761 arestas: 9,1% citam "CONSORCIO" no nome, e entre
    os nós há 59 de natureza 2151, 53 de 2127 e 79 de 1333.

    O corte é pela NATUREZA JURÍDICA e nunca pelo nome: `CONSTRUTORA METROPOLITANA S.A. SCP
    ACADEMIA DE BOMBEIROS` traz as duas palavras e é o que o código disser.
    """
    from compliance_agent.osint.contato_compartilhado import explicacao_estrutural

    assert bool(explicacao_estrutural(na, nb)) is tem


@pytest.mark.parametrize("email,servico", [
    # o caso que escapou: contador com domínio livre e o nome na PARTE LOCAL
    ("burgarellicontabilidade@outlook.com", True),
    ("144consultoriacontabil@gmail.com", True),
    ("escritoriomartins@gmail.com", True),
    ("assessoriafiscal@hotmail.com", True),
    # domínio de serviço continua valendo
    ("abertura@maismei.com.br", True),
    ("contato@contabilidadexyz.com.br", True),
    # e-mail comum da própria empresa NÃO é de serviço
    ("fiscal@medmax.com.br", False),
    ("compras@empresa.com.br", False),
    ("financeiro@biosys.com.br", False),
])
def test_contato_de_servico_olha_a_parte_local_tambem(email, servico):
    """A regra via um terço do problema.

    `burgarellicontabilidade@outlook.com` uniu LUGOM SOLUÇÕES e AVANTTE num mesmo certame como se
    fosse elo societário — e é escritório de contabilidade com domínio livre. Medido na base de
    6,17 milhões de estabelecimentos: **126.537 e-mails trazem "contabil" na parte local com
    domínio livre**, contra 76.078 no domínio.
    """
    from compliance_agent.osint.contato_compartilhado import _de_servico

    assert _de_servico(email) is servico
