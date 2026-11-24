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
    assert limite_dispensa(2019) == 17600.00 and limite_dispensa(2020, "obras") == 33000.00   # Decreto 9.412/2018
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
