# -*- coding: utf-8 -*-
"""Catracas estáticas das regras de qualidade (`config/qualidade_regras.yaml`).

Cada regra tem dois testes: a CATRACA (a dívida medida no repositório não pode passar da base em
`tests/golden/qualidade_base.json`; arquivo novo nasce em zero) e a PROVA (regra COR-15: o defeito é injetado
em texto sintético e o verificador tem de acusar; o texto conforme tem de passar). Catraca que não fica
vermelha com o defeito é enfeite.

Curou dívida? `python -m compliance_agent.qualidade base --apertar` e commite a base menor. A base nunca sobe
por ferramenta.
"""
from __future__ import annotations

import pytest

from compliance_agent.qualidade import catraca, catracas
from compliance_agent.qualidade.catracas import CATRACAS


def _barrar(nome: str) -> None:
    c = CATRACAS[nome]
    excesso = c.excesso()
    assert not excesso, catraca.mensagem(c.regra, c.o_que, excesso)


# ───────────────────────────── as catracas ─────────────────────────────
def test_linguagem_painel_so_desce():
    _barrar("linguagem_painel")                # PAD-08


def test_ob_sem_filtro_de_paga_so_desce():
    _barrar("ob_sem_filtro_de_paga")           # CNF-02


def test_sancao_sem_alcance_so_desce():
    _barrar("sancao_sem_alcance")              # CNF-03


def test_teto_legal_copiado_so_desce():
    _barrar("teto_legal_copiado")              # CNF-06 / CST-09


def test_cpf_versionado_so_desce():
    _barrar("cpf_versionado")                  # CNF-08


def test_segredo_versionado_so_desce():
    _barrar("segredo_versionado")              # CNF-14


def test_chave_paga_fora_do_teto_so_desce():
    _barrar("chave_paga_fora_do_teto")         # CNF-10


def test_cnpj_literal_no_codigo_so_desce():
    _barrar("cnpj_literal_no_codigo")          # PAD-12


def test_pkill_por_padrao_so_desce():
    _barrar("pkill_por_padrao")                # CNF-16


def test_grupo_por_cpf_mascarado_so_desce():
    _barrar("grupo_por_cpf_mascarado")         # COR-06


def test_toda_catraca_tem_base_gravada():
    """Catraca sem base aceitaria qualquer coisa como "zero" — ou barraria tudo. A base é gravada uma vez."""
    import json
    base = json.loads(catraca.BASE.read_text(encoding="utf-8"))
    faltando = [n for n in CATRACAS if n not in base]
    assert not faltando, f"catraca sem base em {catraca.BASE.name}: {faltando}"


# ───────────────────────────── as provas (COR-15) ─────────────────────────────
# CPF e CNPJ abaixo são SINTÉTICOS: montados para ter dígito verificador válido, sem titular.
_CPF_SINT = "111.444.777-35"
_CNPJ_SINT = "11222333000181"

PROVAS = [
    ("linguagem_painel", "static/js/src/x.js", "el.textContent='Empresas fantasma pagas pelo órgão';",
     "el.textContent='Empresas com indício de perfil fantasma';"),
    ("ob_sem_filtro_de_paga", "compliance_agent/x.py",
     'con.execute("SELECT SUM(valor) FROM ob_orcamentaria_siafe WHERE credor=?")',
     'con.execute("SELECT SUM(valor) FROM ob_orcamentaria_siafe WHERE status=\'Contabilizado\' AND credor=?")'),
    ("sancao_sem_alcance", "compliance_agent/x.py", 'q = "SELECT cnpj FROM sancoes_federais WHERE cnpj=?"',
     'from compliance_agent import sancao_abrangencia\nq = "SELECT cnpj FROM sancoes_federais WHERE cnpj=?"'),
    ("teto_legal_copiado", "compliance_agent/x.py", "TETO = 59906.02", "TETO = limite_dispensa(2024)"),
    ("cpf_versionado", "docs/x.md", f"servidor de CPF {_CPF_SINT}", "servidor de CPF ***.444.777-**"),
    ("segredo_versionado", "tools/x.py", 'CHAVE = "gsk_' + "a" * 48 + '"', 'CHAVE = os.environ.get("GROQ_API_KEY")'),
    ("chave_paga_fora_do_teto", "tools/x.py", 'k = os.environ["ANTHROPIC_API_KEY"]', "k = claude_motor.pensar"),
    ("cnpj_literal_no_codigo", "compliance_agent/x.py", f'if cnpj == "{_CNPJ_SINT}": grau = "alto"',
     'if score >= LIMIAR: grau = "alto"'),
    ("pkill_por_padrao", "tools/x.sh", "pkill -f sei_sweep", 'kill "$(cat data/sei.pid)"'),
    ("grupo_por_cpf_mascarado", "compliance_agent/x.py",
     'q = "SELECT cpf_mascarado, SUM(v) FROM folha GROUP BY cpf_mascarado"',
     'q = "SELECT cpf_mascarado, nome_norm, SUM(v) FROM folha GROUP BY cpf_mascarado, nome_norm"'),
]


@pytest.mark.parametrize("nome,rel,defeito,conforme", PROVAS, ids=[p[0] for p in PROVAS])
def test_prova_catraca_acusa_o_defeito_e_aceita_o_conforme(nome, rel, defeito, conforme):
    achar = CATRACAS[nome].achar
    assert achar(rel, defeito), f"{nome}: a catraca NÃO acusou o defeito injetado"
    assert not achar(rel, conforme), f"{nome}: a catraca acusou texto conforme (falso positivo): {achar(rel, conforme)}"


def test_prova_toda_catraca_registrada_tem_prova():
    assert {p[0] for p in PROVAS} == set(CATRACAS), "catraca registrada sem prova (ou prova sem catraca)"


def test_prova_arquivo_novo_nasce_em_zero_e_base_so_desce(tmp_path):
    base = tmp_path / "base.json"
    catraca.gravar_base("x", {"a.py": 3, "b.py": 1}, base)                      # primeira gravação: o real
    assert catraca.cresceu({"a.py": 3, "novo.py": 1}, catraca.ler_base("x", base)) == ["novo.py: 1 (base 0)"]
    assert catraca.cresceu({"a.py": 4}, catraca.ler_base("x", base)) == ["a.py: 4 (base 3)"]
    assert not catraca.cresceu({"a.py": 2}, catraca.ler_base("x", base))
    catraca.gravar_base("x", {"a.py": 9, "c.py": 5}, base)                      # apertar NUNCA sobe nem inclui
    assert catraca.ler_base("x", base) == {"a.py": 3}
    assert catraca.folga({"a.py": 1}, {"a.py": 3}) == 2


def test_prova_chave_de_objeto_nao_e_rotulo():
    """Identificador ('fantasma' como chave de aba) não é texto exibido: contar isso faria a catraca mentir."""
    assert not catracas.achar_linguagem("static/js/src/x.js", "TABS={fantasma:{id:'fantasma'}}")


def test_prova_consulta_de_metadado_declarada_passa():
    sql = '# ob-qualquer-status: cobertura da coleta, não soma\ncon.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe")'
    assert not catracas.achar_ob_sem_filtro("compliance_agent/x.py", sql)
