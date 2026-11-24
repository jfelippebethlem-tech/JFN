# -*- coding: utf-8 -*-
"""O4.1 — `dominio.digitos`: um `so_digitos` + DV + máscara, com PARIDADE contra as cópias antigas.

Cópias de "só dígitos" achadas em 24/11/2026 (grep `def (_)?(so_)?digitos`), todas com a mesma intenção:
  str(v or "") + \\D   collectors/beneficios_sociais:69, collectors/formato:67, detectores/c6_vinculo_politico:74,
                       editais/indice_certame:125, fachada_doubt:190, reporting/intel_base:92, sei/extrair_cpf:22,
                       tools/gabarito_claude:41, tools/sei_confronto_llm:114
  (s or "") + \\D       cruzamento:41, indeterminados:294, territorio/atribui_estado:435   → só str/None (int quebra)
  str(v) + \\D          llm/verificacao:36                                                 → 0 vira "0"
  isdigit()            editais/coletor_propostas:58, tools/sei_inventario_captura:44, rodizio_grafo:44 ((s or "")),
                       receita/ingest_estabelecimentos:61 (só str)                        → mantém "²", "①"
Nenhum CPF literal com DV válido aqui (pre-commit `tools/scan_pii`): os CPFs são gerados em tempo de execução.
"""
from __future__ import annotations

import importlib
import random
import re

import pytest

from compliance_agent.dominio import digitos as D

ENTRADAS_STR = ["12.345.678/0001-90", " 123 ", "", "abc", "R$ 1.234,56", "SEI-080001/000123/2024", "１２３", "١٢٣",
                "x²y³", "①②", "00", "a1b2c3", "\t9\n8", "–7—"]
ENTRADAS_OUTRAS = [None, 123, 0, 0.0, 12.5, False]


def _f(caminho: str):
    mod, nome = caminho.rsplit(":", 1)
    return getattr(importlib.import_module(mod), nome)


IGUAIS_SEMPRE = ["compliance_agent.collectors.beneficios_sociais:_so_digitos", "compliance_agent.collectors.formato:so_digitos",
                 "compliance_agent.detectores.c6_vinculo_politico:_so_digitos",
                 "compliance_agent.editais.indice_certame:_so_digitos", "compliance_agent.fachada_doubt:_digitos",
                 "compliance_agent.reporting.intel_base:so_digitos", "compliance_agent.sei.extrair_cpf:_digitos",
                 "tools.gabarito_claude:_so_digitos", "tools.sei_confronto_llm:_digitos"]
SO_STR_OU_NONE = ["compliance_agent.cruzamento:_so_digitos", "compliance_agent.indeterminados:_digitos",
                  "compliance_agent.territorio.atribui_estado:_digitos"]
ISDIGIT = {"compliance_agent.editais.coletor_propostas:_so_digitos": True,     # aceita None
           "tools.sei_inventario_captura:so_digitos": True,
           "compliance_agent.rodizio_grafo:_so_digitos": True,
           "compliance_agent.receita.ingest_estabelecimentos:_so_digitos": False}   # só str


def test_so_digitos_e_a_fonte_unica_reexportada():
    from compliance_agent import cpf_cnpj
    assert D.so_digitos is cpf_cnpj.digitos
    assert D.cpf_valido is cpf_cnpj.cpf_valido and D.cnpj_valido is cpf_cnpj.cnpj_valido
    assert D.mascarar_cpf is cpf_cnpj.mascarar_cpf


@pytest.mark.parametrize("caminho", IGUAIS_SEMPRE)
def test_paridade_copias_str_v_or_vazio(caminho):
    antiga = _f(caminho)
    for v in ENTRADAS_STR + ENTRADAS_OUTRAS:
        assert antiga(v) == D.so_digitos(v), (caminho, v)


@pytest.mark.parametrize("caminho", SO_STR_OU_NONE)
def test_paridade_copias_s_or_vazio(caminho):
    """Mesma regra; o contrato delas é str|None (`int` levanta TypeError nelas — limite, não divergência de valor)."""
    antiga = _f(caminho)
    for v in ENTRADAS_STR + [None]:
        assert antiga(v) == D.so_digitos(v), (caminho, v)


def _tem_digito_nao_decimal(v: str) -> bool:
    return any(c.isdigit() and not re.match(r"\d", c) for c in v)


@pytest.mark.parametrize("caminho", sorted(ISDIGIT))
def test_paridade_copias_isdigit(caminho):
    """DIVERGÊNCIA DOCUMENTADA: `str.isdigit()` é True para sobrescritos e circulados ("²", "①", categoria Unicode
    No); o `\\d` do `re` (categoria Nd) não. "x²" daria "2" — um expoente virando dígito de CNPJ. A nova descarta;
    fora desses caracteres, igualdade exata."""
    antiga = _f(caminho)
    entradas = ENTRADAS_STR + ([None] if ISDIGIT[caminho] else [])
    for v in entradas:
        if v is not None and _tem_digito_nao_decimal(v):
            assert antiga(v) != D.so_digitos(v)
            assert D.so_digitos(v) == "".join(c for c in v if re.match(r"\d", c))
        else:
            assert antiga(v) == D.so_digitos(v), (caminho, v)


def test_paridade_llm_verificacao_str_sem_or():
    """DIVERGÊNCIA DOCUMENTADA: `llm.verificacao._digitos` faz `str(v)` sem `or ""` — 0 vira "0" lá e "" aqui.
    Lá o uso é número extraído (`numero_no_trecho`), onde 0 é valor; por isso NÃO vai delegar à nova sem decidir."""
    antiga = _f("compliance_agent.llm.verificacao:_digitos")
    for v in ENTRADAS_STR + [None, 123, 12.5]:
        assert antiga(v) == D.so_digitos(v), v
    for v in (0, 0.0, False):
        assert antiga(v) in ("0", "00", "") and D.so_digitos(v) == ""
    assert antiga(0) == "0"


# ── DV e máscara ─────────────────────────────────────────────────────────────────────────────────────

def _cpf_sintetico(rng: random.Random) -> str:
    b = [rng.randrange(10) for _ in range(9)]
    for n in (9, 10):
        s = sum(v * p for v, p in zip(b, range(n + 1, 1, -1)))
        b.append((s * 10 % 11) % 10)
    return "".join(map(str, b))


def _cnpj_sintetico(rng: random.Random) -> str:
    b = [rng.randrange(10) for _ in range(12)]
    for pesos in ((5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2), (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)):
        r = sum(v * p for v, p in zip(b, pesos)) % 11
        b.append(0 if r < 2 else 11 - r)
    return "".join(map(str, b))


def _amostra(gerador, n=300, tam=11):
    rng = random.Random(4101)
    validos = [gerador(rng) for _ in range(n)]
    invalidos = [v[:-1] + str((int(v[-1]) + 1) % 10) for v in validos] + [str(d) * tam for d in range(10)]
    return validos, invalidos


def test_cpf_valido_paridade_com_copias():
    from compliance_agent.cpf_corpus import cpf_valido as corpus
    from compliance_agent.resolucao_cpf import _dv_cpf
    from compliance_agent.sei.extrair_cpf import validar_cpf
    from tools.scan_pii import cpf_valido as scan
    validos, invalidos = _amostra(_cpf_sintetico)
    for c in validos:
        pontuado = f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"
        assert D.cpf_valido(c) and D.cpf_valido(pontuado)
        assert validar_cpf(c) and validar_cpf(pontuado) and scan(c) and scan(pontuado)
        assert corpus(pontuado) == c and _dv_cpf(c[:9]) == c[9:]
    for c in invalidos:
        assert not D.cpf_valido(c) and not validar_cpf(c) and not scan(c) and corpus(c) == ""
    for v in (None, "", "123", "1234567890123"):
        assert D.cpf_valido(v) is False and validar_cpf(v) is False


def test_cnpj_valido_paridade_com_copias():
    from compliance_agent.cerebro_fts import cnpj_valido as fts
    validos, invalidos = _amostra(_cnpj_sintetico, tam=14)
    for c in validos:
        assert D.cnpj_valido(c) and D.cnpj_valido(f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}") and fts(c)
    for c in invalidos:
        assert not D.cnpj_valido(c) and not fts(c)
    # `cerebro_fts` só aceita os 14 dígitos crus (cópia de propósito: não importa nada do JFN); a nova ignora pontuação.
    assert not fts(f"{validos[0][:2]}.{validos[0][2:]}") and D.cnpj_valido(f"{validos[0][:2]}.{validos[0][2:]}")


def test_mascara_cpf_pad04_e_copia_relatorio_riscos_expoe_os_mesmos_digitos():
    """DIVERGÊNCIA DOCUMENTADA (só formato): `relatorio_riscos/collectors/cnpj_receita._mascarar_cpf` escreve
    `***456789**` sem pontuação; a PAD-04 escreve `***.456.789-**`. Os dígitos expostos são os MESMOS (4–9) —
    nenhuma janela combinada revela o CPF."""
    from relatorio_riscos.collectors.cnpj_receita import _mascarar_cpf
    c = _cpf_sintetico(random.Random(7))
    assert D.mascarar_cpf(c) == f"***.{c[3:6]}.{c[6:9]}-**"
    assert re.sub(r"\D", "", _mascarar_cpf(c)) == re.sub(r"\D", "", D.mascarar_cpf(c)) == c[3:9]
    assert c not in D.mascarar_cpf_no_texto(f"CPF {c} e mais")
