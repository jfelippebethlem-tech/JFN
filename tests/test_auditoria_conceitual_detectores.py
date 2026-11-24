# -*- coding: utf-8 -*-
"""Auditoria conceitual dos detectores (23/11/2026): pagamento ≠ contratação, ente público ≠ fornecedor,
regime legal do exercício. Cada teste tem controle POSITIVO (o que deve acender) e NEGATIVO (o que não pode).

Medido no compliance.db antes do conserto:
- `rules.ob_fracionamento`: 106 dos 107 alertas gravados tinham OB individual ACIMA do teto (Riocard, Amil,
  Barcas) — parcela de contrato/concessão, não compra fatiada.
- `intel.corrida_dezembro`: 45 dos 70 eram transferência (Associação de Apoio à Escola, Funasa, FNDE).
- peneiras de nome: 222 credores de natureza jurídica 1xxx passavam; e `GRU`/`pessoal`/`uni[ãa]o`/`energia`
  soltos tiravam fornecedor privado da fila (Grupo Hospitalar do RJ, Uniao Norte Fluminense Eng.).
- `limites_dispensa(2019)` devolvia o teto de 2026 (R$ 65.492,11) em vez do da Lei 8.666 (R$ 17.600,00).
- emergência: "Inciso IV, do Art. 24 da lei 8666/93" (357 processos) e Lei 13.303 art. 29, XV fora da régua;
  art. 75, XVIII lido como VIII; objeto "emergencial" sobrepunha enquadramento de dispensa por valor.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

# ── peneiras canônicas: palavra inteira, ente pelo que é ─────────────────────────────────────────────────


@pytest.mark.parametrize("nome", [
    "Funco Municipal De Saude De Itaguai", "Fms De Sao Francisco De Itabapoana",
    "CONTROLADORIA GERAL DA UNIAO - CGU", "UNIAO-ROYALTIES", "Uniao Federal", "FUNDO MUNICIPAL DE SAUDE",
])
def test_canonica_reconhece_ente_publico_nas_grafias_reais(nome):
    from compliance_agent.entidades_gov import eh_nao_fornecedor
    assert eh_nao_fornecedor(nome)


@pytest.mark.parametrize("nome", [
    "Uniao Norte Fluminense Eng. E Comercio Ltda", "UNIAO QUIMICA FARMACEUTICA NACIONAL S A",
    "UNIÃO DE TECNOLOGIA E INFORMAÇÃO DO BRASIL LTDA", "FMS SERVICOS LTDA",
])
def test_canonica_nao_varre_fornecedor_privado(nome):
    from compliance_agent.entidades_gov import eh_nao_fornecedor
    assert not eh_nao_fornecedor(nome)


def test_natureza_1xxx_e_administracao_publica_estatal_nao():
    from compliance_agent.entidades_gov import eh_administracao_publica
    assert eh_administracao_publica("1023") and eh_administracao_publica("1333")
    assert not eh_administracao_publica("2011")        # empresa pública: estatal, regime da 13.303
    assert not eh_administracao_publica("2062") and not eh_administracao_publica(None)


@pytest.mark.parametrize("nome", [
    "Light Servicos De Eletricidade S/a", "Ampla Energia E Servicos S.a.", "Energisa Minas Gerais-distr.de Energia S.a",
    "VIBRA ENERGIA S.A", "CLARO S.A.", "Vivo S.a", "GRU - GUIA DE RECOLHIMENTO", "FOLHA DE PAGAMENTO DO PESSOAL",
])
def test_nao_licitavel_pega_concessionaria_e_tributo(nome):
    from compliance_agent.fracionamento_siafe import _CREDOR_NAO_LICITAVEL
    assert _CREDOR_NAO_LICITAVEL.search(nome)


@pytest.mark.parametrize("nome", [
    "Grupo Hospitalar Do Rio De Janeiro Ltda", "SONIPREV PREVENCAO E DIAGNOSTICO UNIPESSOAL LTDA",
    "PLASVIVO - DISTRIBUIDORA DE ARTIGOS EM GERAL LTDA", "INDUCTA SOLUÇÃO EM ENERGIA LTDA",
    "Uniao Norte Fluminense Eng. E Comercio Ltda",
])
def test_nao_licitavel_nao_e_gulosa(nome):
    from compliance_agent.fracionamento_siafe import _CREDOR_NAO_LICITAVEL
    assert not _CREDOR_NAO_LICITAVEL.search(nome)


# ── teto do exercício: Lei 8.666 antes da 14.133 ─────────────────────────────────────────────────────────

def test_teto_antes_de_2021_e_o_da_8666():
    from compliance_agent.limites_dispensa import ato_normativo, limite_dispensa
    assert limite_dispensa(2019) == 17600.00 and limite_dispensa(2019, "obras") == 33000.00   # Decreto 9.412/2018
    assert limite_dispensa(2020) == 50000.00 and limite_dispensa(2020, "obras") == 100000.00  # Lei 14.065/2020
    assert "14.065" in ato_normativo(2020)
    assert limite_dispensa(2016) == 8000.00 and limite_dispensa(2016, "obras") == 15000.00    # Lei 9.648/1998
    assert "8.666" in ato_normativo(2019)


def test_teto_da_14133_continua():
    from compliance_agent.limites_dispensa import limite_dispensa
    assert limite_dispensa(2021) == 50000.00 and limite_dispensa(2026) == 65492.11
    assert limite_dispensa(2099) == 65492.11            # ano à frente da tabela: o mais recente conhecido


def test_cruzamentos_usa_o_teto_8666_no_case():
    from compliance_agent.cruzamentos_intel import _TETO_DISPENSA
    assert _TETO_DISPENSA[2019] == 17600.00 and _TETO_DISPENSA[2026] == 65492.11


# ── emergência: o dispositivo manda, em todas as redações ───────────────────────────────────────────────

@pytest.mark.parametrize("enq", [
    "Em conformidade com o Inciso IV, do Art. 24 da lei 8666/93", "CONFORME ARTIGO 24 DO INCISO IV DA LEI 8.666/93",
    "Lei 13.303/2016, Art. 29, XV", "Art. 29 - XV da Lei federal n° 13.303/2016.", "Lei n 14.133/2021, Art. 75, VIII",
])
def test_emergencia_reconhecida_pelo_enquadramento(enq):
    from compliance_agent.fracionamento_emergencia import eh_emergencial
    assert eh_emergencial("PEITO DE FRANGO", enq)


@pytest.mark.parametrize("enq", [
    "Lei n 14.133/2021, Art. 75, XVIII", "Lei nº 14.133/2021, Art. 75º, II", "Lei n 14.133/2021, Art. 74, I",
    "Lei 13.303/2016, Art. 29, II", "art. 24, inciso XIV",
])
def test_objeto_emergencial_nao_sobrepoe_outro_dispositivo(enq):
    from compliance_agent.fracionamento_emergencia import eh_emergencial
    assert not eh_emergencial("AQUISIÇÃO EMERGENCIAL DE INSUMOS", enq)


def test_sem_dispositivo_nomeado_o_objeto_ainda_vale():
    from compliance_agent.fracionamento_emergencia import eh_emergencial
    assert eh_emergencial("CONTRATAÇÃO EMERGENCIAL", "Art. 24 L8666/93")
    assert eh_emergencial("CONTRATAÇÃO EMERGENCIAL", "")


# ── cruzamentos_intel sobre base real em miniatura ──────────────────────────────────────────────────────

PUBLICO = "11111111000100"      # natureza 1023, nome que nenhuma regex de nome pega
PRIVADO = "22222222000100"


@pytest.fixture()
def base(tmp_path):
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT,"
                " status_envio TEXT, tipo_regularizacao TEXT, credor TEXT, nome_credor TEXT, processo TEXT, valor REAL)")
    con.execute("CREATE TABLE empresas_cadastro (cnpj_basico TEXT, natureza_cod TEXT)")
    con.executemany("INSERT INTO empresas_cadastro VALUES (?,?)", [(PUBLICO[:8], "1023"), (PRIVADO[:8], "2062")])
    con.commit()
    return db, con


def _ob(con, credor, nome, valor, data, processo, ug="294200"):
    n = con.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe").fetchone()[0]
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"2025OB{n:05d}", ug, data, "Contabilizado", "", "", credor, nome, processo, valor))


def test_corrida_dezembro_tira_ente_publico_pela_natureza(base):
    from compliance_agent.cruzamentos_intel import corrida_dezembro
    db, con = base
    for c, nm in ((PUBLICO, "Rio De Janeiro Sec.de Estado Da Defesa Civil"), (PRIVADO, "GESPED GESTAO LTDA")):
        _ob(con, c, nm, 3_000_000.0, "15/12/2025", "SEI-1")
    con.commit()
    achados = {a["cnpj"] for a in corrida_dezembro(str(db), min_total=1.0)["achados"]}
    assert PRIVADO in achados and PUBLICO not in achados


def test_fracionamento_exige_processos_distintos(base):
    """Cinco OBs coladas no teto do MESMO processo são parcelas de um contrato; em cinco processos, sinal."""
    from compliance_agent.cruzamentos_intel import fracionamento
    db, con = base
    for i in range(5):
        _ob(con, PRIVADO, "GESPED GESTAO LTDA", 60_000.0, f"{i + 1:02d}/03/2025", "SEI-UNICO")
    con.commit()
    assert fracionamento(str(db), min_obs=5, min_colado=3)["n"] == 0
    for i in range(5):
        _ob(con, PRIVADO, "GESPED GESTAO LTDA", 60_000.0, f"{i + 1:02d}/04/2025", f"SEI-{i}")
    con.commit()
    r = fracionamento(str(db), min_obs=5, min_colado=3)
    assert r["n"] == 1 and "sinal" in r["natureza"]


def test_fracionamento_nao_acusa_ente_publico(base):
    from compliance_agent.cruzamentos_intel import fracionamento
    db, con = base
    for i in range(5):
        _ob(con, PUBLICO, "Rio De Janeiro Sec.de Estado Da Defesa Civil", 60_000.0, f"{i + 1:02d}/04/2025", f"S-{i}")
    con.commit()
    assert fracionamento(str(db), min_obs=5, min_colado=3)["n"] == 0


# ── rules.ob_fracionamento: OB acima do teto é parcela, não fatia ───────────────────────────────────────

def _sessao(obs):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from compliance_agent.database.models import Base, OrdemBancaria
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    dia = date.today() - timedelta(days=3)
    s.add_all([OrdemBancaria(numero_ob=f"OB{i}", data_emissao=dia, ug_codigo="294200", favorecido_cpf=c,
                             favorecido_nome=nm, valor=v, numero_processo=p, status="paga")
               for i, (c, nm, v, p) in enumerate(obs)])
    s.commit()
    return s


def _alertas(obs):
    from compliance_agent.rules.engine import MotorCompliance
    m = MotorCompliance(_sessao(obs))
    m._alertas_novos = []
    m._regra_ob_fracionamento()
    return m._alertas_novos


def test_ob_acima_do_teto_nao_e_fracionamento():
    assert _alertas([(PRIVADO, "RIOCARD TECNOLOGIA LTDA", 68_000_000.0, "SEI-A"),
                     (PRIVADO, "RIOCARD TECNOLOGIA LTDA", 68_000_000.0, "SEI-B")]) == []


def test_parcelas_do_mesmo_processo_nao_sao_fracionamento():
    assert _alertas([(PRIVADO, "GESPED GESTAO LTDA", 40_000.0, "SEI-A")] * 3) == []


def test_obs_pequenas_em_processos_distintos_acendem():
    a = _alertas([(PRIVADO, "GESPED GESTAO LTDA", 40_000.0, f"SEI-{i}") for i in range(3)])
    assert len(a) == 1


def test_ente_publico_nao_acende_no_motor():
    assert _alertas([(PUBLICO, "Funco Municipal De Saude De Itaguai", 40_000.0, f"SEI-{i}") for i in range(3)]) == []


# ── anomalias.R_FRACIONAMENTO_SAMEDAY: a mesma régua (cada OB abaixo do teto) ──────────────────────────

def _flags_sameday(valores):
    pd = pytest.importorskip("pandas")
    from compliance_agent import anomalias
    con = sqlite3.connect(":memory:")
    anomalias._ddl(con)
    df = pd.DataFrame([{"id": i + 1, "favorecido_cpf": PRIVADO, "favorecido_nome": "GESPED GESTAO LTDA",
                        "ug_codigo": "294200", "data_emissao": "2025-03-10", "exercicio": 2025, "valor": v}
                       for i, v in enumerate(valores)])
    anomalias.regras(df, con)
    return [r[0] for r in con.execute("SELECT regra FROM ob_redflag WHERE regra='R_FRACIONAMENTO_SAMEDAY'")]


def test_sameday_com_ob_acima_do_teto_nao_acende():
    assert _flags_sameday([5_000_000.0, 5_000_000.0]) == []


def test_sameday_com_obs_abaixo_do_teto_acende():
    assert _flags_sameday([40_000.0, 40_000.0]) == ["R_FRACIONAMENTO_SAMEDAY"]


# ── conhecimento-base do LLM: teto de convite da 8.666 (Decreto 9.412/2018) e correção do seed ─────────

def test_memoria_convite_8666_e_seed_corrige_o_banco():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from compliance_agent.database.models import Base, MemoriaAprendizado
    from compliance_agent.llm import memoria
    texto = dict(memoria.CONTEXTO_INICIAL)["limite_convite_antigo"]
    assert "R$ 330.000 para obras" in texto and "R$ 176.000 para compras" in texto
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    s.add(MemoriaAprendizado(categoria="contexto_admin", chave="limite_convite_antigo",
                             valor="convite até R$ 176.000 para obras", confianca=0.9, fonte="humano"))
    s.add(MemoriaAprendizado(categoria="contexto_admin", chave="limite_convite_antigo_x",
                             valor="aprendido", confianca=0.5, fonte="llm"))
    s.commit()
    memoria.garantir_contexto_inicial(session=s)
    v = s.query(MemoriaAprendizado).filter_by(chave="limite_convite_antigo").one().valor
    assert v == texto
    assert s.query(MemoriaAprendizado).filter_by(chave="limite_convite_antigo_x").one().valor == "aprendido"


# ── decisões do dono 24/11/2026 ─────────────────────────────────────────────────────────────────────────

def _base_triagem(natureza):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (ug_emitente TEXT, credor TEXT, nome_credor TEXT, data_emissao TEXT,"
                " valor REAL, processo TEXT, numero_ob TEXT, status TEXT, nl TEXT, exercicio INT)")
    con.execute("CREATE TABLE nl_siafe (numero TEXT, ug_emitente TEXT, ne TEXT, exercicio INT)")
    con.execute("CREATE TABLE ne_siafe (numero TEXT, ug_emitente TEXT, natureza TEXT)")
    for i in range(6):
        con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('294200',?,?,?,?,?,?,?,?,2025)",
                    (PRIVADO, "PLASMA LABORATORIO LTDA", f"{i + 1:02d}/03/2025", 40_000.0, f"SEI-{i}", f"OB{i}",
                     "Contabilizado", f"2025NL{i}"))
        con.execute("INSERT INTO nl_siafe VALUES (?, '294200', ?, 2025)", (f"2025NL{i}", f"2025NE{i}"))
        con.execute("INSERT INTO ne_siafe VALUES (?, '294200', ?)", (f"2025NE{i}", natureza))
    return con


def test_triagem_tira_dea_e_indenizacao_pela_natureza_do_empenho():
    from compliance_agent.fracionamento_siafe import triagem
    r = triagem(_base_triagem("339092"), exercicio=2025, min_obs=5)
    assert r["candidatos"] == [] and r["obs_descartadas_natureza"] == 6


def test_triagem_mantem_material_de_consumo_e_se_declara_sinal():
    from compliance_agent.fracionamento_siafe import triagem
    r = triagem(_base_triagem("339030"), exercicio=2025, min_obs=5)
    assert len(r["candidatos"]) == 1 and "sinal" in r["candidatos"][0]["natureza_sinal"]


def test_d07_e_sinal_nao_manchete():
    from compliance_agent.governo_couto_regras import GRAU_REGRA
    assert GRAU_REGRA["D07"] == "⚪"


@pytest.fixture()
def sem_receita(monkeypatch):
    from compliance_agent import credor_institucional as ci
    from compliance_agent import governo_couto_regras as g
    monkeypatch.setattr(ci, "_receita", lambda cnpj: None)
    g._CACHE_REGIME_PROPRIO.clear()


def test_d01_tira_estatal_13303_concessionaria_e_correios(sem_receita):
    from compliance_agent.governo_couto_regras import _direta_de_regime_proprio as f
    linha = lambda enq: [(2026, 1.0, "obj", "Dispensa", enq, "U", "F")]  # noqa: E731
    assert f("", "PLENA LOCACAO", linha("Lei 13.303/2016, Art. 29, XV"))
    assert f("", "LIGHT SERVICOS DE ELETRICIDADE SA", linha("Lei n 14.133/2021, Art. 74, Caput"))
    assert f("", "EMPRESA BRASILEIRA DE CORREIOS E TELEGRAFOS", linha("Lei n 14.133/2021, Art. 75, IX"))


def test_d01_mantem_fornecedor_comum_e_licitado(sem_receita):
    from compliance_agent.governo_couto_regras import _direta_de_regime_proprio as f
    assert f("", "NFL DO BRASIL LTDA", [(2026, 1.0, "evento", "Inexigibilidade", "Art. 74, III", "U", "F")]) is None
    assert f("", "LIGHT SERVICOS DE ELETRICIDADE SA", []) is None      # não é direta: não sai da conta


def test_d01_concessionaria_pelo_cnae_da_receita(monkeypatch):
    from compliance_agent import credor_institucional as ci
    from compliance_agent import governo_couto_regras as g
    monkeypatch.setattr(ci, "_receita", lambda cnpj: ("2054", "3600601"))     # Águas do Rio: só o CNAE diz
    g._CACHE_REGIME_PROPRIO.clear()
    assert g._direta_de_regime_proprio("42644220000106", "AGUAS DO RIO 4 SPE S.A",
                                       [(2026, 1.0, "água", "Inexigibilidade", "Art. 74, Caput", "U", "F")])


@pytest.mark.parametrize("natureza_ne, esperado", [("339034", "contrato de gestão"), ("335043", "parceria com OSC"),
                                                    ("339039", "regime a confirmar")])
def test_os_osc_fica_na_lista_com_o_regime(base, natureza_ne, esperado):
    from compliance_agent.cruzamentos_intel import regime_do_credor
    db, con = base
    osc = "33333333000100"
    con.execute("INSERT INTO empresas_cadastro VALUES (?, '3999')", (osc[:8],))
    con.execute("CREATE TABLE ne_siafe (credor TEXT, natureza TEXT, valor REAL)")
    con.execute("INSERT INTO ne_siafe VALUES (?,?,1e6)", (osc, natureza_ne))
    con.commit()
    r = regime_do_credor(con, osc)
    assert esperado in r["regime"] and r["regime_regra"]
    assert regime_do_credor(con, PRIVADO) == {}                     # fornecedor comercial: régua comum


def test_emenda_paga_em_restos_a_pagar_nao_e_anuncio_sem_execucao():
    from compliance_agent.emendas.pericia import d6_empenho_sem_pagamento
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE emendas (codigo TEXT, ano INT, autor_norm TEXT, localidade_gasto TEXT, empenhado REAL,"
                " liquidado REAL, pago REAL, resto_cancelado REAL, resto_pago REAL)")
    con.execute("INSERT INTO emendas VALUES ('E-RP', 2024, 'A', 'RJ', 100, 0, 0, 60, 40)")   # paga em RP
    con.execute("INSERT INTO emendas VALUES ('E-NADA', 2024, 'A', 'RJ', 100, 0, 0, 60, 0)")  # nada pago
    codigos = {a["codigo_emenda"] for a in d6_empenho_sem_pagamento(con)}
    assert codigos == {"E-NADA"}


def test_lex_nao_diz_50_por_cento_para_servicos():
    from compliance_agent.lex_sancoes import RF_PARA_GRAVIDADE
    nota = RF_PARA_GRAVIDADE["R9"][2]
    assert "serviços)" not in nota and "reforma" in nota


# ── aditivos_estouro: "série" é de ACRÉSCIMOS, não de qualquer termo ───────────────────────────────────

def _base_aditivos(tmp_path, termos):
    db = tmp_path / "a.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE pcrj_contratos (numero_controle_pncp TEXT, fornecedor_nome TEXT, fornecedor_documento TEXT,"
                " orgao_nome TEXT, unidade TEXT, objeto TEXT, valor_inicial REAL, valor_global REAL, num_aditivos INT,"
                " vigencia_fim TEXT)")
    con.execute("CREATE TABLE contrato_aditivo (numero_controle_pncp TEXT, objeto TEXT, valor_acrescido REAL,"
                " data_assinatura TEXT, sequencial_termo INT, tipo_termo TEXT)")
    con.execute("INSERT INTO pcrj_contratos VALUES ('C1','VIG LTDA','22222222000100','SEEDUC','U',"
                "'serviço de vigilância',1000000,1150000,3,'2027-01-01')")
    for i, (obj, v) in enumerate(termos):
        con.execute("INSERT INTO contrato_aditivo VALUES ('C1',?,?,?,?, 'Termo Aditivo')",
                    (obj, v, f"2025-0{i + 1}-10", i + 1))
    con.commit()
    return str(db)


def test_tres_prorrogacoes_nao_sao_serie_de_acrescimo(tmp_path):
    from compliance_agent.cruzamentos_intel import aditivos_estouro
    db = _base_aditivos(tmp_path, [("Prorrogação do prazo de vigência por 12 meses", 0)] * 3)
    assert aditivos_estouro(db, esfera="todas")["n_serie"] == 0


def test_tres_acrescimos_em_datas_distintas_sao_serie(tmp_path):
    from compliance_agent.cruzamentos_intel import aditivos_estouro
    db = _base_aditivos(tmp_path, [("Acréscimo quantitativo de 5% do objeto", 50000)] * 3)
    r = aditivos_estouro(db, esfera="todas")
    assert r["n_serie"] == 1 and r["achados"][0]["n_termos_acrescimo"] == 3
