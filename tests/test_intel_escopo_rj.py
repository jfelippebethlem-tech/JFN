# -*- coding: utf-8 -*-
"""Escopo da casa nos cruzamentos de intel: só RJ — Estado e Prefeitura do Rio, estanques; federal fora (20/11/2026).

1. `sancionadas_contratadas` (parte PNCP): o código comparava a esfera no vocabulário do PNCP ("estado",
   "prefeitura") contra ("federal", "estadual", "municipal") — só "federal" casava. Resultado medido na base
   viva: as 5 empresas "à época" só-PNCP eram TODAS de órgão federal (Marinha, Instituto Benjamin Constant…),
   e vitória no Estado ou na Prefeitura sob sanção vigente e com alcance NUNCA era marcada.
2. `aditivos_estouro` sem esfera varria a `pcrj_contratos` inteira: 68 dos 120 achados servidos eram de órgão
   federal e o "de quantos" (90.905) era a tabela toda.
"""
from __future__ import annotations

import sqlite3

from compliance_agent import cruzamentos_intel as C

ESTADO, PCRJ, EXERCITO = "42498600000171", "42498733000148", "00394452000103"
BETA, DELTA, EPSILON, ZETA = "22222222000122", "44444444000144", "55555555000155", "66666666000166"


def _base_sancoes(tmp_path) -> str:
    db = tmp_path / "s.db"
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE sancoes_federais (cadastro TEXT, cpf_cnpj TEXT, nome TEXT, categoria TEXT, data_inicio TEXT,
        data_fim TEXT, orgao TEXT, uf TEXT, processo TEXT, fundamentacao TEXT, abrangencia TEXT,
        esfera_sancionador TEXT, data_publicacao TEXT);
    CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT,
        credor TEXT, nome_credor TEXT, valor REAL);
    CREATE TABLE pncp_resultado (certame TEXT, orgao_cnpj TEXT, orgao_nome TEXT, uf TEXT, municipio TEXT,
        data_pub TEXT, fornecedor_cnpj TEXT, fornecedor_nome TEXT, valor_homologado REAL,
        ordem_classificacao INTEGER, unidade_nome TEXT);
    """)
    imp = "Impedimento/proibição de contratar com prazo determinado"
    ente = "Em todos os Poderes da Esfera do órgão sancionador"
    con.executemany("INSERT INTO sancoes_federais VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        # BETA: impedimento do Estado do RJ — alcança compra do Estado do RJ
        ("CEIS", BETA, "BETA", imp, "2026-01-01", "2026-12-31", "Secretaria de Estado Ficticia", "RJ", "p",
         "LEI 14133 - ART. 156, III", ente, "ESTADUAL", None),
        # DELTA: inidoneidade (alcance total), mas só vence em órgão FEDERAL — fora do escopo da casa
        ("CEIS", DELTA, "DELTA", "Declaração de Inidoneidade com prazo determinado", "2026-01-01", "2026-12-31",
         "Controladoria Federal Ficticia", "DF", "p", "LEI 14133 - ART. 156, IV",
         "Todas as Esferas em todos os Poderes", "FEDERAL", None),
        # EPSILON: impedimento da Prefeitura de NITERÓI — não alcança a Prefeitura do Rio
        ("CEIS", EPSILON, "EPSILON", imp, "2026-01-01", "2026-12-31", "Prefeitura Municipal de Niterói", "RJ", "p",
         "LEI 14133 - ART. 156, III", ente, "MUNICIPAL", None),
        # ZETA: impedimento do Município do Rio — alcança a Prefeitura do Rio
        ("CEIS", ZETA, "ZETA", imp, "2026-01-01", "2026-12-31", "Prefeitura da Cidade do Rio de Janeiro", "RJ", "p",
         "LEI 14133 - ART. 156, III", ente, "MUNICIPAL", None),
    ])
    con.executemany("INSERT INTO pncp_resultado VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        ("c-estado", ESTADO, "ESTADO DO RIO DE JANEIRO", "RJ", "Rio de Janeiro", "2026-05-10", BETA, "BETA", 100.0, 1, "SES"),
        ("c-federal", EXERCITO, "COMANDO DO EXERCITO", "RJ", "Rio de Janeiro", "2026-05-10", DELTA, "DELTA", 900.0, 1, "BATALHAO"),
        ("c-rio-niteroi", PCRJ, "MUNICIPIO DE RIO DE JANEIRO", "RJ", "Rio de Janeiro", "2026-05-10", EPSILON, "EPSILON", 300.0, 1, "SMS"),
        ("c-rio", PCRJ, "MUNICIPIO DE RIO DE JANEIRO", "RJ", "Rio de Janeiro", "2026-05-10", ZETA, "ZETA", 400.0, 1, "SMS"),
    ])
    con.commit()
    con.close()
    return str(db)


def test_pncp_do_estado_sob_sancao_com_alcance_conta_a_epoca(tmp_path):
    """Controle positivo — era o falso negativo: vocabulário trocado nunca deixava o Estado casar."""
    d = C.sancionadas_contratadas(_base_sancoes(tmp_path))
    por = {e["cnpj"]: e for e in d["empresas"]}
    assert por[BETA]["pncp"]["vitorias_durante"] == 1
    assert por[BETA]["pncp"]["exemplos_durante"][0]["esfera"] == "estado"


def test_pncp_federal_fica_fora_do_escopo_e_e_contado(tmp_path):
    """Controle negativo — órgão federal não entra na lista nem no 'à época'; fica contado em `pncp_fora_do_escopo`."""
    d = C.sancionadas_contratadas(_base_sancoes(tmp_path))
    assert DELTA not in {e["cnpj"] for e in d["empresas"]}
    assert d["pncp_fora_do_escopo"] == {"federal": 1}
    assert d["n_a_epoca"] == 2                       # BETA (Estado) e ZETA (Prefeitura) — DELTA não


def test_prefeitura_do_rio_so_e_alcancada_por_sancao_do_proprio_municipio(tmp_path):
    por = {e["cnpj"]: e for e in C.sancionadas_contratadas(_base_sancoes(tmp_path))["empresas"]}
    assert por[ZETA]["pncp"]["vitorias_durante"] == 1
    assert por[EPSILON]["pncp"]["vitorias_durante"] == 0            # Niterói não veda a Prefeitura do Rio
    assert por[EPSILON]["pncp"]["vitorias_vigente_sem_alcance"] == 1
    assert por[EPSILON]["pncp"]["esferas"] == {"prefeitura": 1}


# ── aditivos: sem esfera = RJ (Estado + Prefeitura), nunca a tabela inteira ───────────────────────────────

def _base_aditivos(tmp_path) -> str:
    db = tmp_path / "a.db"
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE pcrj_contratos (numero_controle_pncp TEXT, fornecedor_nome TEXT, fornecedor_documento TEXT,
        orgao_nome TEXT, unidade TEXT, objeto TEXT, valor_inicial REAL, valor_global REAL, num_aditivos INTEGER,
        vigencia_fim TEXT);
    CREATE TABLE contrato_aditivo (numero_controle_pncp TEXT, qualif_acrescimo TEXT, valor_acrescido REAL, objeto TEXT);
    """)
    for cnpj, orgao in ((ESTADO, "ESTADO DO RIO DE JANEIRO"), (PCRJ, "MUNICIPIO DE RIO DE JANEIRO"),
                        (EXERCITO, "COMANDO DO EXERCITO")):
        con.execute("INSERT INTO pcrj_contratos VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (f"{cnpj}-2-000001/2025", "FORN", "11111111000111", orgao, orgao, "serviço de manutenção",
                     100000.0, 140000.0, 4, "2026-12-31"))
    con.commit()
    con.close()
    return str(db)


def test_aditivos_sem_esfera_e_so_rj_com_quebra(tmp_path):
    d = C.aditivos_estouro(db_path=_base_aditivos(tmp_path))
    assert {a["esfera"] for a in d["achados"]} == {"estado", "prefeitura"}       # federal fora
    assert d["contratos_analisados"] == 2                                          # o "de quantos" é o do escopo
    assert d["por_esfera"] == {"estado": 1, "prefeitura": 1}
    assert d["fora_do_escopo"] == {"federal": 1}


def test_aditivos_esfera_explicita_e_todas(tmp_path):
    db = _base_aditivos(tmp_path)
    assert [a["esfera"] for a in C.aditivos_estouro(db_path=db, esfera="prefeitura")["achados"]] == ["prefeitura"]
    assert C.aditivos_estouro(db_path=db, esfera="todas")["n"] == 3               # opt-in explícito de pesquisa


# ── detectores "da Prefeitura": lista branca (só municipal-rio), não lista negra de federal/Estado ────────

def _base_municipio(tmp_path) -> str:
    db = tmp_path / "m.db"
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE sancoes_federais (cadastro TEXT, cpf_cnpj TEXT, nome TEXT, categoria TEXT, data_inicio TEXT,
        data_fim TEXT, orgao TEXT, uf TEXT, processo TEXT, fundamentacao TEXT);
    CREATE TABLE pcrj_contratos (numero_controle_pncp TEXT, orgao_cnpj TEXT, orgao_nome TEXT, objeto TEXT,
        fornecedor_documento TEXT, fornecedor_nome TEXT, valor_global REAL, valor_inicial REAL,
        data_assinatura TEXT, fonte TEXT);
    """)
    con.execute("INSERT INTO sancoes_federais VALUES ('CEIS',?,'FORN','Declaração de Inidoneidade com prazo "
                "determinado','2024-01-01','2026-12-31','CGU','DF','p','LEI 14133 - ART. 156, IV')", (BETA,))
    for i, (orgao_cnpj, orgao) in enumerate(((PCRJ, "MUNICIPIO DE RIO DE JANEIRO"),
                                             ("", "PREFEITURA MUNICIPAL DE NITEROI"),      # outro município
                                             ("", "ASSOCIACAO DE MORADORES X"))):          # sem sinal: indefinido
        for k in range(8):
            con.execute("INSERT INTO pcrj_contratos VALUES (?,?,?,?,?,?,?,?,?,'pncp')",
                        (f"n{i}-{k}", orgao_cnpj, orgao, "serviço de limpeza predial", BETA, "FORN",
                         1000.0, 1000.0, "2025-06-10"))
    con.commit()
    con.close()
    return str(db)


def test_sancionadas_municipio_nao_aceita_outro_municipio_nem_indefinido(tmp_path):
    d = C.sancionadas_municipio(db_path=_base_municipio(tmp_path))
    assert d["empresas"][0]["contratos"] == 8                       # só os da Prefeitura do Rio
    assert d["descartados_outra_esfera"]["municipal-outro"] == 8
    assert d["descartados_outra_esfera"]["indefinido"] == 8


def test_concentracao_municipio_nao_aceita_outro_municipio_nem_indefinido(tmp_path):
    d = C.concentracao_municipio(db_path=_base_municipio(tmp_path))
    assert sum(o["n_contratos"] for o in d["orgaos"]) == 8
    assert d["descartados_outra_esfera"]["municipal-outro"] == 8
    assert d["descartados_outra_esfera"]["indefinido"] == 8
