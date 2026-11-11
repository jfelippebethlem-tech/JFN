# -*- coding: utf-8 -*-
"""NÃO DETERMINADO não é ponto de atenção (pedido do dono, 11/11/2026).

Medido em 11/11 (`pericia_fornecedor`, 33.744 pares): 8.772 🟡, dos quais ~8.761 só estavam
amarelos porque dois testes que NÃO conseguem determinar nada gravavam INDICIO:
  • T08 (lacuna de competência) apontava 28.754 pares (85%) — aplicado a compra pontual, CPF,
    UG e faturamento bimestral, sem saber se havia contrato contínuo nem a periodicidade;
  • T02 (OB anulada) apontava 5.803 pares "se qualquer agregado as somar" — sem agregado nenhum
    para testar (ninguém fornece `relatorio_total_pago`) e anulação com reemissão é rotina.
Além disso: o filtro de não-contratuais testava o CÓDIGO do credor (nunca casava: 246 🟡 de folha,
RIOPREV e precatório, R$ 233 bi), o total pago somava OB anulada/excluída, e a API apagava o ⚪.

Regra: o que não pôde ser verificado é INDISPONÍVEL (⚪), nunca 🟡.
"""
import sqlite3

import pytest

from compliance_agent import auditoria_contrato as ac
from compliance_agent import pericia_sweep as ps


def _ob(n, comp, valor=1000.0, status="Contabilizado", data=None):
    mm, aaaa = comp.split("/")
    return {"numero_ob": n, "status": status, "nl": "NL", "re": "RE" + n, "pd": "PD" + n,
            "valor": valor, "competencia": comp, "data_emissao": data or f"10/{mm}/{aaaa}",
            "processo": ""}


def _acao(achados, codigo):
    return next(a for a in achados if a["codigo"] == codigo)


# ───────────────────────── T08 ─────────────────────────
OBS_COM_LACUNA = [_ob("1", "01/2023"), _ob("2", "02/2023"), _ob("3", "05/2023"), _ob("4", "06/2023")]


def test_t08_sem_contrato_continuo_e_indisponivel_nao_indicio():
    h = ac._t08_gap({"obs": OBS_COM_LACUNA})
    assert h["status"] == "INDISPONIVEL", h
    assert "005/2021" not in h["evidencia"] + h["base_legal"]


def test_t08_continuo_sem_periodicidade_tambem_e_indisponivel():
    h = ac._t08_gap({"obs": OBS_COM_LACUNA, "servico_continuo": True})
    assert h["status"] == "INDISPONIVEL"


def test_t08_continuo_mensal_com_lacuna_e_indicio_e_cita_o_contrato_do_par():
    h = ac._t08_gap({"obs": OBS_COM_LACUNA, "servico_continuo": True, "periodicidade_meses": 1,
                     "contrato_ref": "123/2022"})
    assert h["status"] == "INDICIO"
    assert "03/2023" in h["evidencia"] and "04/2023" in h["evidencia"]
    assert "123/2022" in h["evidencia"] and "005/2021" not in h["evidencia"] + h["base_legal"]


def test_t08_bimestral_nao_e_lacuna():
    # 33644865000140/310100: OBs em 03, 05, 09, 11/2023 é faturamento bimestral
    obs = [_ob("1", "03/2023"), _ob("2", "05/2023"), _ob("3", "07/2023"), _ob("4", "09/2023")]
    h = ac._t08_gap({"obs": obs, "servico_continuo": True, "periodicidade_meses": 2})
    assert h["status"] == "AFASTADO", h


def test_texto_005_2021_so_no_caso_mgs():
    res = ac.auditar_contrato({"obs": OBS_COM_LACUNA, "favorecido": "ACME LTDA", "orgao": "310100"})
    texto = repr(res)
    assert "005/2021" not in texto, [k for k in res["cobertura"]]


def test_enriquecer_mgs_no_iterj_traz_o_contrato_005_2021():
    d = ps.enriquecer({"obs": [], "favorecido": "MGS CLEAN", "orgao": "133100", "_cnpj": "19088605000104"}, None)
    assert d["contrato_ref"] == "005/2021" and d["servico_continuo"] and d["periodicidade_meses"] == 1
    outro = ps.enriquecer({"obs": [], "favorecido": "MGS CLEAN", "orgao": "296100", "_cnpj": "19088605000104"}, None)
    assert "contrato_ref" not in outro and not outro.get("servico_continuo")


# ───────────────────────── T02 ─────────────────────────
def test_t02_anulada_com_reemissao_e_afastado():
    obs = [_ob("1", "01/2023", 500.0, "Anulado", "10/01/2023"), _ob("2", "01/2023", 500.0, data="20/01/2023")]
    assert ac._t02_status_pago({"obs": obs})["status"] == "AFASTADO"


def test_t02_anulada_sem_reemissao_mas_sem_coleta_na_janela_e_indisponivel():
    # única OB contabilizada está a 1 ano: não dá para saber se a reemissão existe (cobertura SIAFE parcial)
    obs = [_ob("1", "01/2023", 500.0, "Anulado", "10/01/2023"), _ob("2", "01/2024", 900.0, data="10/01/2024")]
    assert ac._t02_status_pago({"obs": obs})["status"] == "INDISPONIVEL"


def test_t02_anulada_sem_reemissao_com_coleta_na_janela_e_indicio():
    obs = [_ob("1", "01/2023", 500.0, "Excluído", "10/01/2023"), _ob("2", "01/2023", 900.0, data="25/01/2023")]
    h = ac._t02_status_pago({"obs": obs})
    assert h["status"] == "INDICIO" and "sem reemissão" in h["evidencia"]


def test_t02_total_declarado_que_soma_a_anulada_continua_confirmado():
    obs = [_ob("1", "01/2023", 500.0, "Anulado"), _ob("2", "02/2023", 900.0)]
    assert ac._t02_status_pago({"obs": obs, "relatorio_total_pago": 1400.0})["status"] == "CONFIRMADO"


# ───────────────────────── grau ─────────────────────────
def test_par_sem_contrato_continuo_e_anulada_reemitida_nao_fica_amarelo():
    obs = OBS_COM_LACUNA + [_ob("9", "02/2023", 1000.0, "Anulado", "05/02/2023")]
    res = ac.auditar_contrato({"obs": obs, "favorecido": "ACME"})
    assert res["grau"] == "🟢" and res["n_indicios"] == 0, [(a["codigo"], a["status"]) for a in res["achados"]]


def test_nada_verificado_e_grau_branco():
    res = ac.auditar_contrato({"obs": []})
    assert res["grau"] == "⚪" and res["n_indicios"] == 0


# ───────────────────────── sweep ─────────────────────────
def _banco(tmp_path, linhas):
    c = sqlite3.connect(tmp_path / "c.db")
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE ob_orcamentaria_siafe(numero_ob TEXT, status TEXT, nl TEXT, re TEXT, pd TEXT,
        valor REAL, competencia TEXT, data_emissao TEXT, processo TEXT, nome_credor TEXT, credor TEXT,
        ug_emitente TEXT)""")
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,'','','',?,?,?,'',?,?,?)", linhas)
    c.execute(ps._DDL)
    c.commit()
    return c


def _linhas(credor, nome, ug, n=3, status="Contabilizado", valor=100.0):
    return [(f"{credor}{status[:2]}{i}", status, valor, f"0{i + 1}/2023", f"10/0{i + 1}/2023", nome, credor, ug)
            for i in range(n)]


@pytest.fixture
def banco(tmp_path, monkeypatch):
    linhas = (_linhas("11111111000199", "ACME SERVICOS LTDA", "310100")
              + _linhas("11111111000199", "ACME SERVICOS LTDA", "310100", 2, "Excluído", 5000.0)
              + _linhas("CG0004700", "FOLHA DE PAGAMENTOS", "310100")
              + _linhas("123400", "FUNDO UNICO DE PREVIDENCIA DO ESTADO DO RJ.", "310100")
              + _linhas("22222222000188", "Fundo Unico De Prev.do Erj-rioprevidencia", "310100")
              + _linhas("RP0000123", "EC 37 PRECATORIOS", "310100")
              + _linhas("33333333000177", "Prefeitura Municipal De Paraty", "310100"))
    c = _banco(tmp_path, linhas)
    # par antigo, gravado por um sweep de antes do conserto: tem de SAIR
    c.execute("INSERT INTO pericia_fornecedor(cnpj,ug,grau) VALUES ('CG0004700','310100','🟡')")
    c.commit(); c.close()
    monkeypatch.setattr(ps, "DB", tmp_path / "c.db")
    return tmp_path / "c.db"


def test_total_pago_soma_so_contabilizado(banco):
    c = sqlite3.connect(banco); c.row_factory = sqlite3.Row
    res = ps.periciar("11111111000199", "310100", c)
    assert res["total_pago"] == pytest.approx(300.0)  # sem os R$ 10.000,00 excluídos


def test_sweep_filtra_folha_previdencia_precatorio_orgao_e_poda_par_antigo(banco):
    r = ps.sweep(min_obs=3)
    c = sqlite3.connect(banco)
    pares = {row[0] for row in c.execute("SELECT cnpj FROM pericia_fornecedor")}
    assert pares == {"11111111000199"}, pares
    assert r["removidos"] >= 1


def test_filtro_le_o_nome_e_o_codigo():
    assert ps._fora_da_bateria("CG0004700", "FOLHA DE PAGAMENTOS")
    assert ps._fora_da_bateria("123400", "QUALQUER NOME")           # código de UG = repasse intragoverno
    assert ps._fora_da_bateria("RF0001", "Fulano")                    # precatório/RPV
    assert ps._fora_da_bateria("22222222000188", "Fundo Único De Previdência")
    assert not ps._fora_da_bateria("11111111000199", "ACME SERVICOS LTDA")
    assert not ps._fora_da_bateria("CS0000012", "CONSORCIO RJ-186")


# ───────────────────────── API ─────────────────────────
def test_api_pericias_nao_converte_branco_em_verde(tmp_path, monkeypatch):
    import json
    from rotas import investigacao as inv
    (tmp_path / "data").mkdir()
    c = sqlite3.connect(tmp_path / "data" / "compliance.db")
    c.execute(ps._DDL)
    c.executemany("INSERT INTO pericia_fornecedor(cnpj,ug,favorecido,grau,score,total_pago) VALUES (?,?,?,?,?,?)",
                  [("11111111000199", "1", "A", "⚪", 0, 1.0), ("22222222000188", "1", "B", "⚪", 0, 1.0),
                   ("22222222000188", "2", "B", "🟢", 0, 1.0)])
    # tabelas que o /api/perfil lê além da perícia (vazias: só o grau importa aqui)
    for ddl in ("ordens_bancarias(favorecido_cpf, valor, ug_codigo, ug_nome, favorecido_nome)",
                "socios_fornecedor(cnpj, socio_nome, qualificacao, socio_servidor)",
                "verificacao_sede(cnpj, razao, endereco, municipio, uf, status, nivel, evidencia, geo_lat, geo_lon,"
                " addr_residencial)",
                "pncp_resultado(fornecedor_cnpj, certame, valor_homologado, orgao_cnpj, ordem_classificacao)"):
        c.execute(f"CREATE TABLE {ddl}")
    c.commit(); c.close()
    monkeypatch.setattr(inv, "RAIZ", tmp_path)
    itens = json.loads(inv.api_pericias().body)["itens"]
    graus = {i["cnpj"]: i["grau"] for i in itens}
    assert graus == {"11111111000199": "⚪", "22222222000188": "🟢"}
    perfil = json.loads(inv.api_perfil("11111111000199").body)
    assert perfil["pericia"]["grau"] == "⚪"


# ───────────────────────── Telegram ─────────────────────────
def test_triagem_amarelos_nao_manda_amarelo_so_de_t08_t02_antigos(tmp_path, monkeypatch):
    import json
    from tools import triagem_amarelos as ta
    c = sqlite3.connect(tmp_path / "c.db")
    c.execute(ps._DDL)
    c.execute("CREATE TABLE sancoes_federais(cpf_cnpj TEXT)")
    velho = json.dumps([{"codigo": "T08-GAP-COMPETENCIA", "status": "INDICIO", "peso": 15},
                        {"codigo": "T02-STATUS-PAGO", "status": "INDICIO", "peso": 25}])
    real = json.dumps([{"codigo": "T07-DUPLICIDADE-COMP", "status": "INDICIO", "peso": 25},
                       {"codigo": "T04-REAJUSTE-MO-CCT", "status": "INDICIO", "peso": 15}])
    c.executemany("INSERT INTO pericia_fornecedor(cnpj,ug,favorecido,grau,score,total_pago,n_obs,achados_json) "
                  "VALUES (?,?,?,?,?,?,?,?)",
                  [("11111111000199", "1", "SO T08 T02", "🟡", 40, 1e6, 3, velho),
                   ("22222222000188", "1", "T07 T04", "🟡", 40, 1e6, 3, real),
                   ("CG0004700", "1", "FOLHA DE PAGAMENTOS", "🟡", 65, 1e9, 3, real)])
    c.commit(); c.close()
    monkeypatch.setattr(ta, "DB", tmp_path / "c.db")
    assert [r["cnpj"] for r in ta.top_amarelos(10)] == ["22222222000188"]


# ───────────────────────── Lex (parecer externo) ─────────────────────────
def test_lex_nao_imprime_t08_t02_indeterminados_como_indicio(banco):
    """O Lex chama `periciar` ao vivo (lex.py: aud_contrato) e imprime a II-E.2: T08/T02 sem base saíam
    "🟡 INDÍCIO" no PDF que vai para fora. Agora vão para o bloco INDISPONÍVEL, sem "005/2021"."""
    from compliance_agent.lex_render import _secao_auditoria_contrato
    c = sqlite3.connect(banco); c.row_factory = sqlite3.Row
    aud = ps.periciar("11111111000199", "310100", c)
    linhas: list[str] = []
    _secao_auditoria_contrato(linhas.append, aud)
    md = "\n".join(linhas)
    assert "005/2021" not in md
    t08 = md.split("### T08-GAP-COMPETENCIA")[1].split("###")[0] if "### T08-GAP-COMPETENCIA" in md else ""
    assert "INDÍCIO" not in t08, t08[:200]
    # o par do fixture tem 2 OB Excluídas de R$ 5.000,00 SEM reemissão e com OB contabilizada na janela:
    # aí o T02 é indício DETERMINADO — e o laudo diz por quê, não "se qualquer agregado as somar"
    t02 = md.split("### T02-STATUS-PAGO")[1].split("###")[0]
    assert "sem reemissão" in t02 and "se qualquer agregado" not in t02


# ───────────────── rodada 2 (11/11/2026, conferência dos 308 🟡 que sobraram) ─────────────────
def test_t07_competencia_parada_em_meses_diferentes_e_indisponivel():
    """UG 403200: 7 pagamentos mensais de R$ 46.336,19, de abr a ago/2026, TODOS com competência '01/2024'.
    O campo não é a competência do pagamento — é um rótulo parado. Sem ele não há como ver duplicidade."""
    obs = [_ob(f"OB{i}", "01/2024", 46336.19, data=f"10/{m:02d}/2026") for i, m in enumerate(range(3, 10))]
    h = ac._t07_duplicidade({"obs": obs})
    assert h["status"] == "INDISPONIVEL", h


def test_filtro_pega_abreviacao_do_siafe():
    assert ps._fora_da_bateria("11384874000106", "Fundo Mun. De Saude De Campos Dos Goytacazes")
    assert ps._fora_da_bateria("30134050000122", "Ipalerj")
