# -*- coding: utf-8 -*-
"""Fonte única de esfera do órgão (escopo RJ do JFN) — controles positivos, negativos e catraca.

Dono, 19/11/2026: "esquece a parte federal, nao queremos tratar disso" / "existe uma defensoria em cada
estado da federacao e um tce tambem. tem que ser do RJ". Antes, o nome "SECRETARIA DE ESTADO"/"TRIBUNAL DE
CONTAS DO ESTADO" de QUALQUER estado saía "estadual-rj", e UNIRIO e os conselhos regionais "DO ESTADO DO RIO
DE JANEIRO" (federais) também.

Os fatos (natureza jurídica e sede) dos CNPJs reais abaixo foram lidos da Receita (dump 2026-10) e do PNCP
em 19/11/2026 e vão INJETADOS — o teste não depende da base da VM. Um bloco à parte confere na base real
quando ela existe.
"""
import re
from pathlib import Path

import pytest

from compliance_agent import esfera_orgao as eo

RAIZ = Path(__file__).resolve().parents[1]

# cnpj, nome, natureza (Receita), uf, municipio (código Receita), poder esperado
RJ = [
    ("30051023000196", "TRIBUNAL DE CONTAS DO ESTADO DO RIO DE JANEIRO", "1058", "RJ", "6001", "Tribunal de Contas"),
    ("31443526000170", "DEFENSORIA PUBLICA DO ESTADO DO RIO DE JANEIRO-DPE", "1171", "RJ", "6001", "Defensoria Pública"),
    ("28305936000140", "MINISTERIO PUBLICO DO ESTADO DO RIO DE JANEIRO", "1171", "RJ", "6001", "Ministério Público"),
    ("28538734000148", "TRIBUNAL DE JUSTICA DO ESTADO DO RIO DE JANEIRO", "1082", "RJ", "6001", "Judiciário"),
    ("30449862000167", "RIO DE JANEIRO ASSEMBLEIA LEGISLATIVA", "1058", "RJ", "6001", "Legislativo"),
    # nomes SEM "RIO DE JANEIRO": só a natureza + sede salvam (não podem cair fora)
    ("32855236000104", "SECRETARIA DE ESTADO DE POLICIA CIVIL", "1023", "RJ", "6001", "Executivo"),
    ("42498675000152", "SECRETARIA DE ESTADO DE FAZENDA - SEFAZ", "1023", "RJ", "6001", "Executivo"),
]
FORA = [
    # cnpj, nome, fatos, esfera esperada
    ("34023077000107", "UNIVERSIDADE FEDERAL DO ESTADO DO RIO DE JANEIRO",
     {"natureza": "1139", "uf": "RJ", "municipio": "6001"}, "federal"),
    ("42147611000107", "CONSELHO REGIONAL DE MEDICINA VETERINARIA DO ESTADO DO RIO DE JANEIRO (CRMV - RJ )",
     {"natureza": "1104", "uf": "RJ", "municipio": "6001"}, "federal"),
    ("33618698000162", "CONSELHO REGIONAL DOS TECNICOS INDUSTRIAIS DO ESTADO DO RIO DE JANEIRO - CRT-RJ",
     {"natureza": "1104", "uf": "RJ", "municipio": "6001"}, "federal"),
    ("21154885000148", "TRIBUNAL DE CONTAS DO ESTADO DE MINAS GERAIS",
     {"natureza": "1058", "uf": "MG", "municipio": "4123"}, "outro-estado"),
    ("08036157000189", "DEFENSORIA PUBLICA DO ESTADO DE SAO PAULO",
     {"natureza": "1171", "esfera_pncp": "E", "uf": "SP", "fonte_uf": "PNCP unidades"}, "outro-estado"),
    ("00394544000185", "MINISTERIO DA SAUDE", {"natureza": "1015", "uf": "DF"}, "federal"),
]


@pytest.mark.parametrize("cnpj,nome,nat,uf,mun,poder", RJ)
def test_controle_positivo_orgaos_do_rj(cnpj, nome, nat, uf, mun, poder):
    r = eo.classificar(cnpj, nome, fatos={"natureza": nat, "uf": uf, "municipio": mun})
    assert r["esfera"] == "estadual-rj" and r["no_rj"], r
    assert r["poder"] == poder, r
    assert r["via"] == "natureza+uf" and nat in r["prova"]


@pytest.mark.parametrize("cnpj,nome,fatos,esperado", FORA)
def test_controle_negativo_federal_e_outros_estados(cnpj, nome, fatos, esperado):
    r = eo.classificar(cnpj, nome, fatos=fatos)
    assert r["esfera"] == esperado and not r["no_rj"], r


def test_raizes_do_estado_e_do_municipio():
    assert eo.classificar("42498600000171", fatos={})["esfera"] == "estadual-rj"
    assert eo.classificar("42.498.733/0001-48", fatos={})["esfera"] == "municipal-rio"


def test_municipal_pela_sede():
    rio = eo.classificar("27532498000190", "TRIBUNAL DE CONTAS DO MUNICIPIO DO RIO DE JANEIRO",
                         fatos={"natureza": "1066", "uf": "RJ", "municipio": "6001"})
    assert rio["esfera"] == "municipal-rio" and rio["poder"] == "Tribunal de Contas"
    nit = eo.classificar("x", "MUNICIPIO DE NITEROI", fatos={"natureza": "1244", "uf": "RJ", "municipio": "5865"})
    assert nit["esfera"] == "outro-municipio"


def test_estatal_federal_vence_o_esferaid_errado_do_pncp():
    # o PNCP marca a INB (federal) como esfera "E"
    r = eo.classificar("00322818000120", "INDUSTRIAS NUCLEARES DO BRASIL S/A",
                       fatos={"natureza": "2011", "esfera_pncp": "E", "uf": "RJ", "municipio": "6001"})
    assert r["esfera"] == "federal"


def test_privado_nao_e_orgao_mesmo_com_esferaid():
    # SEBRAE-RJ (serviço social autônomo, natureza 3077) e FIOTEC (fundação privada) — o PNCP dá "M"
    for nat, nome in (("3077", "SEBRAE/RJ"), ("3069", "FIOTEC - FUNDACAO PARA O DESENVOLVIMENTO")):
        r = eo.classificar("x", nome, fatos={"natureza": nat, "esfera_pncp": "M", "uf": "RJ", "municipio": "6001"})
        assert r["esfera"] == "indefinido", r


def test_consorcio_intermunicipal_nao_e_estado():
    r = eo.classificar("63994897000136", "CONSORCIO MULTIFINALITARIO DOS MUNICIPIOS DO ESTADO DO RIO DE JANEIRO",
                       fatos={"natureza": "1210", "uf": "RJ", "municipio": "6001"})
    assert r["esfera"] == "outro-municipio"


def test_natureza_estadual_sem_sede_nao_chuta():
    assert eo.classificar("x", "SECRETARIA DE ESTADO DE SAUDE", fatos={"natureza": "1023"})["esfera"] == "indefinido"
    assert eo.classificar("x", "SECRETARIA DE ESTADO DE SAUDE DO RIO DE JANEIRO",
                          fatos={"natureza": "1023"})["esfera"] == "estadual-rj"


@pytest.mark.parametrize("nome,esperado", [
    # estadual SÓ com marca do RJ
    ("SECRETARIA DE ESTADO DE SAUDE", "indefinido"),
    ("TRIBUNAL DE CONTAS DO ESTADO", "indefinido"),
    ("SECRETARIA DE ESTADO DE SAUDE DO RIO DE JANEIRO", "estadual-rj"),
    ("MINISTERIO PUBLICO DO ESTADO DO RIO DE JANEIRO", "estadual-rj"),
    ("FUNDACAO SAUDE DO ESTADO DO RIO DE JANEIRO", "estadual-rj"),
    ("TRIBUNAL DE CONTAS DO ESTADO DE MINAS GERAIS", "outro-estado"),
    ("DEFENSORIA PUBLICA DO ESTADO DE SAO PAULO", "outro-estado"),
    # federal ANTES de estadual
    ("UNIVERSIDADE FEDERAL DO ESTADO DO RIO DE JANEIRO", "federal"),
    ("CONSELHO REGIONAL DE MEDICINA DO ESTADO DO RIO DE JANEIRO", "federal"),
    ("INSTITUTO FEDERAL DO RIO DE JANEIRO", "federal"),
    ("COMANDO DA MARINHA", "federal"),
    ("MINISTERIO DA SAUDE", "federal"),
    # municipal
    ("PREFEITURA MUNICIPAL DO RIO DE JANEIRO", "municipal-rio"),
    ("MUNICIPIO DE NITEROI", "outro-municipio"),
    ("", "indefinido"),
])
def test_nome_e_o_ultimo_recurso(nome, esperado):
    assert eo.classificar("", nome, fatos={})["esfera"] == esperado


@pytest.fixture
def sem_base(monkeypatch):
    monkeypatch.setattr(eo, "fatos_do_cnpj", lambda c: {})
    eo._classificar_unidade.cache_clear()
    yield
    eo._classificar_unidade.cache_clear()


def test_unidade_corrige_o_ente(sem_base):
    est = "42498600000171"
    # unidade municipal do interior sob o ente "Estado do RJ"
    assert eo.classificar_unidade(est, "ESTADO DO RIO DE JANEIRO", "PREFEITURA MUNICIPAL DE MARICA",
                                  "Maricá")["esfera"] == "outro-municipio"
    # Theatro Municipal é fundação ESTADUAL — "MUNICIPAL" no nome não muda de esfera
    assert eo.classificar_unidade(est, "ESTADO DO RIO DE JANEIRO", "FUNDAÇÃO TEATRO MUNICIPAL DO RIO DE JANEIRO",
                                  "Rio de Janeiro")["esfera"] == "estadual-rj"
    # compras da Prefeitura do Rio lançadas sob o CNPJ do Fundo de Saúde de Itatiaia (dado real do PNCP)
    assert eo.classificar_unidade("10476365000140", "FUNDO MUNICIPAL DE SAUDE DE ITATIAIA",
                                  "PREFEITURA MUNICIPAL DO RIO DE JANEIRO - RJ", "Rio de Janeiro",
                                  esfera_pncp="M")["esfera"] == "municipal-rio"
    # município vazio ≠ Rio (bug de 20/07/2026)
    assert eo.classificar_unidade("29131075000193", "MUNICIPIO DE MARICA", "", "",
                                  esfera_pncp="M")["esfera"] == "outro-municipio"


# ── base real (só onde ela existe) ───────────────────────────────────────────────────────────────────
_TEM_BASE = eo.DB_RECEITA.exists()


@pytest.mark.skipif(not _TEM_BASE, reason="sem data/receita_estab.db")
@pytest.mark.parametrize("cnpj", [c for c, *_ in RJ])
def test_base_real_rj(cnpj):
    assert eo.classificar(cnpj)["esfera"] == "estadual-rj"


@pytest.mark.skipif(not _TEM_BASE, reason="sem data/receita_estab.db")
@pytest.mark.parametrize("cnpj", ["34023077000107", "42147611000107", "33618698000162", "00394544000185"])
def test_base_real_fora(cnpj):
    assert not eo.classificar(cnpj)["no_rj"]


# ── catraca ─────────────────────────────────────────────────────────────────────────────────────────
_GATILHO = re.compile(r"SECRETARIA DE ESTADO|TRIBUNAL DE CONTAS DO ESTADO|GOVERNO DO ESTADO|\\\\bESTAD|"
                      r"TRIBUNAL DE JUSTI|POL\[")
_ROTULO = re.compile(r"""return\s+["'](estadual-rj|estado|estadual)["']""")


def _regex_de_nome_estadual(texto: str) -> list[str]:
    if not _ROTULO.search(texto):
        return []
    return [m.group(0)[:80] for m in re.finditer(r"re\.compile\((?:[^()]|\([^()]*\))*\)", texto, re.S)
            if _GATILHO.search(m.group(0))]


def test_catraca_detecta_o_padrao_antigo():
    antigo = ('_ESTADUAL_RJ = re.compile(r"ESTADO DO RIO DE JANEIRO|SECRETARIA DE ESTADO|'
              'TRIBUNAL DE CONTAS DO ESTADO", re.I)\n'
              'def classificar(n):\n    if _ESTADUAL_RJ.search(n):\n        return "estadual-rj"\n')
    assert _regex_de_nome_estadual(antigo)


def test_catraca_nenhuma_regex_de_nome_estadual_fora_da_fonte_unica():
    """Classificar órgão como estadual por regex de nome (sem UF) é o defeito de 19/11/2026 — mora só em
    compliance_agent/esfera_orgao.py, onde estadual exige marca do RJ e vem depois do federal."""
    achados = []
    for d in ("compliance_agent", "rotas", "tools"):
        for py in (RAIZ / d).rglob("*.py"):
            if py.name == "esfera_orgao.py" or "_arquivo" in py.parts:
                continue
            r = _regex_de_nome_estadual(py.read_text(encoding="utf-8", errors="ignore"))
            if r:
                achados.append(f"{py.relative_to(RAIZ)}: {r[0]}")
    assert not achados, "regex de nome estadual sem UF fora da fonte única: " + "; ".join(achados)


def test_constante_das_raizes_num_lugar_so():
    from compliance_agent.pcrj import esfera as pe
    assert pe._ROOTS is eo.RAIZES_RJ
