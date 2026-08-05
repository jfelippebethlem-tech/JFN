# -*- coding: utf-8 -*-
"""O ÓRGÃO não é o contratado — e o documento diz qual é qual.

Medido em 2026-08-05. O fallback que extrai o CNPJ do contratado a partir do TEXTO devolvia o
**próprio órgão contratante** em processos reais:

  · SEI-330020/000762/2021 → 40.173.726/0001-40, que é o **ITERJ**. O contrato escreve
    "INSTITUTO DE TERRAS E CARTOGRAFIA DO ESTADO DO RIO DE JANEIRO - ITERJ, CNPJ:
    40.173.726/0001-40 doravante denominada CONTRATANTE", e a contratada é a "MGS CLEAN SOLUÇÕES
    E SERVIÇOS LTDA, CNPJ 19.088.605/0001-04". A causa era um teto posicional (`[:12]`) que
    produzia EMPATE 1×1 e o desempatava pela ordem de inserção.
  · SEI-420001/001165/2025 e outros 3 → 40.015.416/0001-06, a **SEGOV**.
  · SEI-510001/001309/2025 → 52.399.071/0001-02, a **SECID**.

Com o órgão no lugar do fornecedor, toda a família C (perfil, fachada, sócio servidor, TAC)
passaria a examinar o próprio contratante.

Nenhum dos três está em `empresas_cadastro`, então o teste de natureza jurídica (1xx =
Administração Pública) não os alcança — é o TEXTO que resolve, porque o instrumento se declara.
Doutrina da casa: o metadado está dentro do dado.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from compliance_agent import processo_360 as P


def _monta(tmp_path: Path, corpo: str) -> tuple[Path, list[dict]]:
    (tmp_path / "texto").mkdir(exist_ok=True)
    (tmp_path / "texto" / "000_doc.txt").write_text(
        "[Contrato 01/2025] (tipo: contrato)\n\n" + corpo, encoding="utf-8")
    docs = [{"i": 0, "titulo": "Contrato 01/2025", "tipo": "contrato", "texto": "texto/000_doc.txt"}]
    (tmp_path / "manifest.json").write_text(json.dumps({"docs": docs}), encoding="utf-8")
    return tmp_path, docs


CONTRATO = (
    "O ESTADO DO RIO DE JANEIRO, neste ato pela SECRETARIA DE ESTADO DE GOVERNO - SEGOV, "
    "inscrita no CNPJ sob o nº 40.015.416/0001-06, doravante denominado CONTRATANTE, "
    "representado neste ato pelo Exmo. Secretário de Estado de Governo, e a empresa PRIME "
    "CONSULTORIA E ASSESSORIA EMPRESARIAL LTDA, inscrita no CNPJ sob o nº 05.340.639/0001-30, "
    "doravante denominada simplesmente CONTRATADA, neste ato representada pela Sra. Renata.")


def test_o_cnpj_marcado_como_CONTRATANTE_nao_vence(tmp_path):
    pasta, docs = _monta(tmp_path, CONTRATO)
    assert P._cnpj_do_texto(pasta, docs) == "05340639000130"


def test_orgao_citado_mais_vezes_ainda_assim_perde(tmp_path):
    """O órgão aparece no cabeçalho de toda página; contar ocorrência sem ler o papel de cada uma
    faz o contratante ganhar por repetição."""
    corpo = CONTRATO + ("\n\nSEGOV - CNPJ 40.015.416/0001-06\n" * 5)
    pasta, docs = _monta(tmp_path, corpo)
    assert P._cnpj_do_texto(pasta, docs) == "05340639000130"


def test_sem_ninguem_sobrando_o_motor_nao_perde_a_identificacao(tmp_path):
    """Se TUDO foi vetado, vale a contagem crua: dizer "não identifiquei" com um CNPJ nos autos
    seria trocar um erro por outro."""
    corpo = ("A empresa AGILE CORP SERVICOS ESPECIALIZADOS LTDA, CNPJ 00.801.512/0001-57, "
             "CONTRATANTE e CONTRATANTE conforme instrumento.")
    pasta, docs = _monta(tmp_path, corpo)
    assert P._cnpj_do_texto(pasta, docs) == "00801512000157"


@pytest.mark.parametrize("cnpj,esperado", [
    ("11128809000110", True),    # FUNDO MUNICIPAL DE SAUDE DE DUQUE DE CAXIAS, natureza 1333
    ("19088605000104", False),   # MGS CLEAN SOLUCOES E SERVICOS LTDA, natureza 2062
])
def test_natureza_juridica_publica_e_reconhecida(cnpj, esperado):
    if not P._DB.exists():
        pytest.skip("compliance.db ausente")
    assert P._e_ente_publico(cnpj) is esperado
