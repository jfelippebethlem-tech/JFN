# -*- coding: utf-8 -*-
"""P7 — contratação direta de risco com o dado que a casa JÁ TEM (NE do painel da CGE), sem ler os autos.

Confronto CGE × JFN (13/11/2026, lacuna 2): em 5 contratações com irregularidade material segundo a CGE,
o painel de NE já dizia "Inexigibilidade, patrocínio…", "Inexigibilidade, dez ingressos para congresso",
"Dispensa, limpeza" e "Dispensa, Evento" — e nenhum sinal saiu. Critério de aceite: dispara em ≥ 4 dos 5.
Dados SINTÉTICOS (repositório público): os textos imitam a FORMA do histórico, sem nome nem CNPJ reais.
"""
from __future__ import annotations

import sqlite3

from compliance_agent.detectores.p7_direta_de_risco import P7DiretaDeRisco, contextos_do_painel, varrer

D = P7DiretaDeRisco()

# Os 5 casos (a) do confronto, na forma do painel de NE — sintéticos
CASOS_CGE = [
    {"processo": "SINT-1", "modalidade": "Inexigibilidade", "valor": 6_000_000.0, "ano": 2026,
     "credor_nome": "ASSOCIACAO SINTETICA DE ESPORTE", "subitem": "DESPESAS COM FINS CULTURAIS E SOCIAIS",
     "historico": "DESPESA COM O CONTRATO DE PATROCÍNIO PARA REALIZAÇÃO DO EVENTO X 2026, BEM COMO AS CONTRAPARTIDAS"},
    {"processo": "SINT-2", "modalidade": "Inexigibilidade", "valor": 520_000.0, "ano": 2026,
     "credor_nome": "EVENTOS SINTETICOS LTDA", "subitem": "DESPESAS COM FINS CULTURAIS E SOCIAIS",
     "historico": "DESPESA COM O CONTRATO DE PATROCÍNIO PARA REALIZAÇÃO DO FESTIVAL Y"},
    {"processo": "SINT-3", "modalidade": "Inexigibilidade", "valor": 27_500.0, "ano": 2026,
     "credor_nome": "FULANO SINTETICO", "subitem": "DESPESAS COM FINS CULTURAIS E SOCIAIS",
     "historico": "DESPESA COM O PAGAMENTO DE DEZ INGRESSOS PARA PARTICIPAÇÃO DE SERVIDORES NO CONGRESSO Z"},
    {"processo": "SINT-4", "modalidade": "Dispensa de Licitação", "valor": 124_996.80, "ano": 2025,
     "credor_nome": "LIMPEZA SINTETICA LTDA ME", "subitem": "SERVIÇOS DE ASSEIO E HIGIENE",
     "historico": "Contratação de empresa especializada na prestação de serviços de limpeza e conservação predial"},
    {"processo": "SINT-5", "modalidade": "Dispensa de Licitação", "valor": 550_000.0, "ano": 2025,
     "credor_nome": "FUNDACAO SINTETICA", "subitem": "DESPESAS COM FINS CULTURAIS E SOCIAIS",
     "historico": "Evento"},
]

# Controles que NÃO podem disparar
CONTROLES = [
    {"processo": "C-1", "modalidade": "Pregão Eletrônico", "valor": 9_000_000.0, "ano": 2025,
     "historico": "Serviços de limpeza e conservação — contrato decorrente de pregão"},
    {"processo": "C-2", "modalidade": "Dispensa de Licitação", "valor": 12_000.0, "ano": 2025,
     "historico": "Serviço de limpeza de caixa d'água"},                       # abaixo do teto de dispensa
    {"processo": "C-3", "modalidade": "Inexigibilidade", "valor": 300_000.0, "ano": 2025,
     "historico": "Aquisição de licença de software de fornecedor exclusivo"},
    {"processo": "C-4", "modalidade": "Dispensa de Licitação", "valor": 40_000.0, "ano": 2025,
     "historico": "Aquisição de material de expediente"},
]


def test_dispara_em_pelo_menos_4_dos_5_casos_da_cge():
    disparos = [D.avaliar(c) for c in CASOS_CGE]
    assert sum(r.status == "confirmado" for r in disparos) >= 4
    assert all(r.status == "confirmado" for r in disparos)        # hoje, os 5


def test_controles_nao_disparam():
    for c in CONTROLES:
        r = D.avaliar(c)
        assert r.status != "confirmado", (c["processo"], r.evidencia)


def test_regras_sao_nomeadas_e_o_valor_e_empenho_nao_pago():
    r = D.avaliar(CASOS_CGE[0])
    assert "inexigibilidade_patrocinio_evento" in r.valores["regras"]
    assert "inexigibilidade_vulto_a_associacao_ou_me" in r.valores["regras"]   # R$ 6 mi a associação
    assert r.valores["natureza_valor"].startswith("empenhado")              # empenho ≠ pagamento
    assert r.explicacao_inocente


def test_dispensa_de_servico_continuo_cita_o_teto_da_fonte_unica():
    from compliance_agent.limites_dispensa import limite_dispensa
    r = D.avaliar(CASOS_CGE[3])
    assert "dispensa_servico_continuo_acima_do_teto" in r.valores["regras"]
    assert r.valores["teto_dispensa"] == limite_dispensa(2025, "compras")


def test_credor_sem_historico_na_ug_agrava_inexigibilidade_de_vulto():
    c = {"processo": "C-5", "modalidade": "Inexigibilidade", "valor": 2_500_000.0, "ano": 2025,
         "credor_nome": "CONSULTORIA SINTETICA S.A.", "historico": "Serviço técnico especializado",
         "credor_novo_na_ug": True}
    assert "inexigibilidade_vulto_a_credor_novo_na_ug" in D.avaliar(c).valores["regras"]


def test_sem_modalidade_ou_valor_e_nao_avaliavel():
    assert D.avaliar({"processo": "x", "historico": "patrocínio"}).status == "nao_avaliavel"


def test_varrer_le_o_painel_agrupa_por_ne_e_marca_credor_novo(tmp_path):
    db = tmp_path / "da.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE cge_ne_credor (ano TEXT, data_de_emissao TEXT, nota_de_empenho TEXT, credor TEXT, "
                "cnpj_cpf TEXT, unidade_gestora TEXT, subitem TEXT, tipo_de_licitacao TEXT, licitacao TEXT, "
                "despesas_empenhadas REAL, despesas_liquidadas REAL, despesas_pagas REAL, historico TEXT, "
                "natureza_despesa TEXT, processos_sei TEXT)")
    linhas = [
        ("2026", "2026-03-01", "2026NE00001", "ASSOCIACAO SINTETICA", "00000000000191", "UG SINTETICA",
         "DESPESAS COM FINS CULTURAIS", "Inexigibilidade", None, 6_000_000.0, 0, 0,
         "DESPESA COM O CONTRATO DE PATROCÍNIO DO EVENTO X", "339039", "[]"),
        ("2025", "2025-05-01", "2025NE00002", "LIMPEZA SINTETICA ME", "00000000000272", "UG SINTETICA",
         "SERVIÇOS DE ASSEIO E HIGIENE", "Dispensa de Licitação", None, 124_996.80, 0, 0,
         "Prestação de serviços de limpeza", "339039", '["SEI-000000/000001/2025"]'),
        ("2025", "2025-06-01", "2025NE00003", "LIMPEZA SINTETICA ME", "00000000000272", "UG SINTETICA",
         "SERVIÇOS DE ASSEIO E HIGIENE", "Dispensa de Licitação", None, 0.0, 0, 0,
         "Prestação de serviços de limpeza", "339039", '["SEI-000000/000001/2025"]'),
        ("2025", "2025-02-01", "2025NE00004", "PAPELARIA SINTETICA", "00000000000353", "UG SINTETICA",
         "MATERIAL DE EXPEDIENTE", "Pregão Eletrônico", None, 80_000.0, 0, 0, "Material", "339030", "[]"),
    ]
    con.executemany("INSERT INTO cge_ne_credor VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", linhas)
    con.commit()
    ctxs = contextos_do_painel(con)
    assert len(ctxs) == 2                                    # pregão fora; as 2 NE do mesmo processo viram 1
    limpeza = next(c for c in ctxs if "limpeza" in c["historico"].lower())
    assert limpeza["valor"] == 124_996.80 and limpeza["processo"] == "SEI-000000/000001/2025"
    assert all(c["credor_novo_na_ug"] for c in ctxs)          # 1ª aparição do credor na UG
    res = varrer(con)
    assert {r.status for r in res} == {"confirmado"} and len(res) == 2
