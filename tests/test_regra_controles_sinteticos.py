# -*- coding: utf-8 -*-
"""Controles negativos (e o positivo par) para as hipóteses inocentes que derrubaram manchetes em 13/11/2026.

Regras COR-03, COR-05, COR-09, CNF-07, CNF-11, CNF-13. Dados INVENTADOS (CNPJ/CPF fictícios, nomes genéricos),
código de produção chamado sem banco real (função pura ou sqlite em memória/`tmp_path`). Teste que falha contra
o código atual é ACHADO: fica `xfail(strict=True)` com o porquê — nunca se enfraquece o teste nem se conserta
o código aqui. Os ids destes testes estão em `config/qualidade_detectores.yaml`.
"""
from __future__ import annotations

import sqlite3
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from compliance_agent import pericia_contabil as pc
from compliance_agent import sancao_abrangencia as sa
from compliance_agent.cruzamentos_intel import _pagou_apos_baixa
from compliance_agent.database.models import Base, RegistroFolha
from compliance_agent.detectores.p4_fracionamento import P4Fracionamento
from compliance_agent.duplicidade_competencia import detectar
from compliance_agent.limites_dispensa import limite_dispensa
from compliance_agent.rules.engine import MotorCompliance

CNPJ_A = "11222333000181"   # sintéticos (o par clássico de documentação), só para teste
CNPJ_B = "11444777000161"


# ───────────── a. OB devolvida pelo banco + reemissão não soma duas vezes ─────────────

def _base_obs(tmp_path, linhas):
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = tmp_path / "ob.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, exercicio INTEGER, ug_emitente TEXT, "
                "data_emissao TEXT, processo TEXT, credor TEXT, valor REAL, nl TEXT, competencia TEXT, gd TEXT, "
                "status_envio TEXT, status TEXT)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", linhas)
    con.commit()
    return con


def _ob(num, valor, gd="", envio="", status="Contabilizado", comp="03/2026", data="10/03/2026"):
    return (num, 2026, "900900", data, "SEI-990001/000001/2026", CNPJ_A, valor, "2026NL00001", comp, gd,
            envio, status)


def test_ob_devolvida_e_reemitida_soma_uma_vez(tmp_path):
    con = _base_obs(tmp_path, [_ob("2026OB90001", 10_000.0, gd="2026GD00001", envio="Erro no Pagamento"),
                               _ob("2026OB90002", 10_000.0)])
    obs, _ = pc._obs_por_credor(con, {CNPJ_A})
    assert sum(o[3] for o in obs[CNPJ_A]) == pytest.approx(10_000.0)
    assert pc.sinais_duplicidade(obs[CNPJ_A])["obs_mesma_nl"] == 0


def test_duas_obs_pagas_para_a_mesma_nl_e_competencia_sao_sinal(tmp_path):
    # controle positivo: duas OBs para a mesma NL/competência/valor, em DIAS distintos, as duas com o crédito
    # confirmado pelo banco e nenhuma devolvida — somam e são o único caso que se chama "possível duplicidade"
    con = _base_obs(tmp_path, [_ob("2026OB90001", 10_000.0, envio=pc.PAGO_CONFIRMADO),
                               _ob("2026OB90002", 10_000.0, envio=pc.PAGO_CONFIRMADO, data="24/03/2026")])
    obs, _ = pc._obs_por_credor(con, {CNPJ_A})
    assert sum(o[3] for o in obs[CNPJ_A]) == pytest.approx(20_000.0)
    assert pc.sinais_duplicidade(obs[CNPJ_A])["obs_mesma_nl"] == 1


def test_parcelas_do_mesmo_dia_e_ob_sem_confirmacao_do_banco_nao_sao_duplicidade(tmp_path):
    # controles negativos (verificação de 13/11/2026: 0 de 19 "duplicidades" se sustentaram):
    # N OBs no MESMO dia para a mesma NL são parcelas; sem confirmação do banco nada se afirma (INDISPONÍVEL)
    con = _base_obs(tmp_path, [_ob("2026OB90011", 10_000.0, envio=pc.PAGO_CONFIRMADO),
                               _ob("2026OB90012", 10_000.0, envio=pc.PAGO_CONFIRMADO)])
    obs, _ = pc._obs_por_credor(con, {CNPJ_A})
    s = pc.sinais_duplicidade(obs[CNPJ_A])
    assert s["obs_mesma_nl"] == 0 and s["obs_mesma_nl_mesmo_dia"] == 1
    con = _base_obs(tmp_path / "b", [_ob("2026OB90013", 10_000.0, envio="Enviado ao Banco"),
                                     _ob("2026OB90014", 10_000.0, envio=pc.PAGO_CONFIRMADO, data="24/03/2026")])
    obs, _ = pc._obs_por_credor(con, {CNPJ_A})
    assert pc.sinais_duplicidade(obs[CNPJ_A])["obs_mesma_nl"] == 0


def test_lixo_na_coluna_gd_nao_e_devolucao(tmp_path):
    # a coluna `gd` traz texto de coleta; só AAAAGDnnnnn é Guia de Devolução
    assert pc.situacao_devolucao("OB já encaminhada ao banco", "Enviado Manualmente") == ""
    assert pc.valor_efetivo_ob(5_000.0, "", None) == (5_000.0, "")
    con = _base_obs(tmp_path, [_ob("2026OB90003", 5_000.0, gd="OB já encaminhada ao banco"),
                               _ob("2026OB90004", 1_000.0, status="Anulado")])
    obs, nao_contab = pc._obs_por_credor(con, {CNPJ_A})
    assert [o[3] for o in obs[CNPJ_A]] == [5_000.0]           # anulada fora; "lixo" na gd conta como paga
    assert sum(nao_contab.values()) == 1


# ───────────── b. sanção sem alcance sobre o Estado, ou fora da vigência, não veda ─────────────

def _veda_no_ato(sancao: dict, data_ato: str) -> bool:
    """O que um detector deve perguntar: a sanção estava vigente NA DATA DO ATO e alcança o Estado do RJ?"""
    return sa.vigente_em(sancao, data_ato) and sa.veda_ente(sancao, "estadual", "RJ")["veda"]


SUSPENSAO_FEDERAL = {"categoria": "Suspensão", "fundamentacao": "Lei 14.133/2021, art. 156, III",
                     "orgao": "Instituto Federal de Educação (órgão federal fictício)", "uf": "RJ",
                     "abrangencia": "No órgão sancionador", "esfera_sancionador": "FEDERAL",
                     "data_inicio": "2026-01-01", "data_fim": "2026-12-31"}
INIDONEIDADE = {"categoria": "Declaração de Inidoneidade sem prazo determinado",
                "fundamentacao": "Lei 8.666/1993, art. 87, IV", "orgao": "Controladoria-Geral da União", "uf": "",
                "data_inicio": "2026-01-01", "data_fim": None}


def test_suspensao_no_orgao_sancionador_federal_nao_veda_o_estado():
    assert sa.classificar_sancao("Suspensão")["abrangencia"] == "orgao"
    assert _veda_no_ato(SUSPENSAO_FEDERAL, "2026-03-10") is False


def test_inidoneidade_vigente_veda_o_estado():
    assert _veda_no_ato(INIDONEIDADE, "2026-03-10") is True


def test_sancao_iniciada_depois_do_ato_nao_vale():
    assert _veda_no_ato(INIDONEIDADE, "2025-12-31") is False


# ───────────── c. pagamento ANTES da baixa não é "pago a empresa morta" ─────────────

_ISO = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"


@pytest.fixture()
def con_receita(tmp_path):
    estab = tmp_path / "estab.db"
    e = sqlite3.connect(estab)
    e.execute("CREATE TABLE estabelecimentos (cnpj TEXT, situacao_cadastral TEXT, data_situacao TEXT, "
              "motivo_situacao TEXT)")
    e.executemany("INSERT INTO estabelecimentos VALUES (?,?,?,?)", [(CNPJ_A, "BAIXADA", "20250601", "01"),
                                                                    (CNPJ_B, "BAIXADA", "20250601", "01")])
    e.commit()
    e.close()
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(f"ATTACH DATABASE '{estab}' AS estab")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (credor TEXT, valor REAL, data_emissao TEXT, status TEXT, "
                "ug_emitente TEXT, processo TEXT)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe (credor, valor, data_emissao, status) "
                    "VALUES (?,?,?,'Contabilizado')", [
        (CNPJ_A, 8_000.0, "10/02/2025"), (CNPJ_A, 9_000.0, "20/05/2025"),   # A: só antes da baixa
        (CNPJ_B, 7_000.0, "10/02/2025"), (CNPJ_B, 3_000.0, "15/07/2025")])  # B: uma depois
    yield con
    con.close()


def test_pagamento_antes_da_baixa_nao_e_pago_a_empresa_morta(con_receita):
    r = _pagou_apos_baixa(con_receita, CNPJ_A, "2025-05-20", _ISO)
    assert r["pagou_apos_baixa"] is False and r["valor_apos_baixa"] == 0.0
    assert r["data_baixa"] == "2025-06-01"


def test_pagamento_depois_da_baixa_e_acusado_so_pelo_que_veio_depois(con_receita):
    r = _pagou_apos_baixa(con_receita, CNPJ_B, "2025-07-15", _ISO)
    assert r["pagou_apos_baixa"] is True
    assert r["valor_apos_baixa"] == 3_000.0 and r["n_ob_apos_baixa"] == 1


# ───────────── d. acúmulo: CPF mascarado igual com nomes diferentes não agrupa ─────────────

def _motor(linhas):
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    for cpf, nome, orgao in linhas:
        s.add(RegistroFolha(cpf=cpf, nome=nome, orgao_codigo=orgao, orgao_nome=f"ORGAO {orgao}",
                            competencia="2026-10", remuneracao_bruta=1_000.0))
    s.commit()
    return MotorCompliance(s)


@pytest.mark.xfail(strict=True, reason="ACHADO: _regra_acumulo_cargo agrupa só pelo CPF mascarado (group_by cpf) e "
                                       "alerta 'alta' juntando pessoas diferentes — a correção de 13/11 só chegou "
                                       "a _regra_emprego_multiplo_orgaos")
def test_acumulo_cargo_cpf_mascarado_nomes_diferentes_nao_agrupa():
    m = _motor([("***123456**", "PESSOA UM", "01"), ("***123456**", "PESSOA DOIS", "02"),
                ("***123456**", "PESSOA TRES", "03")])
    m._regra_acumulo_cargo("2026-10")
    assert [a for a in m._alertas_novos if a.tipo == "acumulacao"] == []


def test_acumulo_cargo_mesma_pessoa_em_tres_orgaos_acusa():
    m = _motor([("***123456**", "PESSOA UM", o) for o in ("01", "02", "03")])
    m._regra_acumulo_cargo("2026-10")
    assert len([a for a in m._alertas_novos if a.tipo == "acumulacao"]) == 1
# Dois cargos de professor (CF art. 37, XVI, "a"): nenhuma regra do motor exclui hoje — sem teste falso; dívida
# registrada em `hipoteses_inocentes` com `excluida_por: null`.


# ───────────── e. duplicidade de competência: parcela ≠ duplicidade ─────────────

def _serie(meses=range(1, 7), valor=50_000.0):
    return [{"competencia": f"{m:02d}/2026", "valor": valor, "re": f"RE{m}", "numero_ob": f"OB{m}"} for m in meses]


def test_parcela_do_mesmo_re_nao_e_duplicidade():
    obs = _serie() + [{"competencia": "03/2026", "valor": 50_000.0, "re": "RE3", "numero_ob": "OB3b"}]
    assert [f for f in detectar(obs) if f["tipo_indicio"] == "competencia_dobrada"] == []


def test_complemento_pequeno_de_reajuste_nao_e_duplicidade():
    obs = _serie() + [{"competencia": "03/2026", "valor": 1_500.0, "re": "RE99", "numero_ob": "OB99"}]
    assert [f for f in detectar(obs) if f["tipo_indicio"] == "competencia_dobrada"] == []


def test_mes_dobrado_com_res_distintos_e_vizinhos_presentes_acusa():
    obs = _serie() + [{"competencia": "03/2026", "valor": 50_000.0, "re": "RE77", "numero_ob": "OB77"}]
    (f,) = [f for f in detectar(obs) if f["tipo_indicio"] == "competencia_dobrada"]
    assert f["competencia"] == "03/2026" and f["severidade"] == "media"


# ───────────── f. teto de dispensa do ano do ato, limite inclusivo, anos não se somam ─────────────

P4 = P4Fracionamento()


def _dispensas(valores_datas):
    return {"contratacoes": [{"objeto": "material de limpeza", "valor": v, "dispensa": True, "data": d,
                              "unidade": "UG TESTE", "enquadramento_legal": "Art. 75, inciso II"}
                             for v, d in valores_datas]}


def test_soma_exatamente_igual_ao_teto_nao_excede():
    teto = limite_dispensa(2025, "compras")
    a = round(teto / 2, 2)
    r = P4.avaliar(_dispensas([(a, "2025-03-01"), (round(teto - a, 2), "2025-05-01")]))
    assert r.status in ("descartado", "nao_avaliavel") or r.score <= 0.3, (r.status, r.score)


def test_um_centavo_acima_do_teto_excede():
    teto = limite_dispensa(2025, "compras")
    a = round(teto / 2, 2)
    r = P4.avaliar(_dispensas([(a, "2025-03-01"), (round(teto - a + 0.01, 2), "2025-05-01")]))
    assert r.score >= 0.6


def test_dispensas_de_exercicios_diferentes_nao_somam_contra_o_teto():
    r = P4.avaliar(_dispensas([(40_000.0, "2024-11-01"), (40_000.0, "2025-02-01")]))
    assert r.status in ("descartado", "nao_avaliavel") or r.score <= 0.3, (r.status, r.score)


# ───────────── CNF-11: parceria/repasse fora do domínio da régua pró-rata ─────────────

def _pericia_um(tmp_path, objeto, valor_ob=900_000.0):
    db = tmp_path / "p.db"
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE contratos_tcerj (id TEXT, processo TEXT, sei_norm TEXT, data_contratacao TEXT, valor_contrato REAL,
      status TEXT, unidade TEXT, objeto TEXT, fornecedor TEXT, cnpj TEXT, vig_inicio TEXT, vig_fim TEXT,
      num_contratacao TEXT);
    CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, ug_pagadora TEXT, data_emissao TEXT,
      status TEXT, credor TEXT, nome_credor TEXT, processo TEXT, valor REAL, exercicio INTEGER,
      nl TEXT DEFAULT '', competencia TEXT DEFAULT '', gd TEXT DEFAULT '', status_envio TEXT DEFAULT '');
    CREATE TABLE ordens_bancarias (numero_ob TEXT, ug_codigo TEXT, data_emissao TEXT, valor REAL);
    """)
    con.execute("INSERT INTO contratos_tcerj (id,processo,sei_norm,data_contratacao,valor_contrato,status,unidade,"
                "objeto,fornecedor,cnpj,vig_inicio,vig_fim) VALUES ('P','SEI-990001/000009/2026','','2026-01-01',"
                "1200000.0,'Ativo','ORG',?,'ENTIDADE TESTE',?,'01/01/2026','31/12/2026')", (objeto, CNPJ_A))
    con.execute("INSERT INTO ob_orcamentaria_siafe (numero_ob,ug_emitente,ug_pagadora,data_emissao,status,credor,"
                "nome_credor,processo,valor,exercicio) VALUES ('2026OB90009','900900','900900','15/01/2026',"
                "'Contabilizado',?,'ENTIDADE TESTE','SEI-990001/000009/2026',?,2026)", (CNPJ_A, valor_ob))
    con.commit()
    con.close()
    return pc.avaliar_estado(db, corte=date(2026, 4, 1))[0]


def test_servico_continuo_pago_acima_do_valor_contratado_e_a_maior(tmp_path):
    # controle positivo: R$ 1,3 mi pagos num contrato de R$ 1,2 mi
    r = _pericia_um(tmp_path, "PRESTAÇÃO DE SERVIÇOS DE VIGILÂNCIA CONTÍNUA", valor_ob=1_300_000.0)
    assert r["categoria"] == "A_MAIOR", r


def test_pago_a_frente_do_pro_rata_dentro_do_valor_nao_e_a_maior(tmp_path):
    # controle negativo: 75% pagos no 1º trimestre, DENTRO do valor contratado — classe própria, não "pago a maior"
    r = _pericia_um(tmp_path, "PRESTAÇÃO DE SERVIÇOS DE VIGILÂNCIA CONTÍNUA")
    assert r["categoria"] == "ADIANTADO", r


def test_contrato_de_gestao_com_repasse_antecipado_nao_e_a_maior(tmp_path):
    # CNF-11: parceria/contrato de gestão com desembolso antecipado não pode sair "pago a maior" por pró-rata.
    # (Até 13/11/2026 saía A_MAIOR — achado desta catraca; a verificação independente criou a classe ADIANTADO.)
    r = _pericia_um(tmp_path, "CONTRATO DE GESTÃO COM ORGANIZAÇÃO SOCIAL - GERENCIAMENTO DE UNIDADE DE SAÚDE")
    assert r["categoria"] in ("ADIANTADO", "INDETERMINADO"), r


def test_ob_com_duas_ou_mais_guias_e_devolucao():
    # 14/11/2026: OB com várias guias no campo ("2024GD00010,2024GD00017") passava como paga inteira —
    # 331 OB e R$ 983,76 mi só em 2024 (medido pela aba Orçamento por órgão).
    assert pc.situacao_devolucao("2024GD00010,2024GD00017", "Processado e Pago") == "gd"
    assert pc.situacao_devolucao("2024GD00010, 2024GD00017", "Parcialmente Pago") == "gd"
    assert pc.situacao_devolucao("2024GD00010", "Processado e Pago") == "gd"
    # controle negativo: texto de coleta continua não sendo guia
    assert pc.situacao_devolucao("OB já encaminhada ao banco", "Processado e Pago") == ""
