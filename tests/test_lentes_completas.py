# -*- coding: utf-8 -*-
"""O7.2 — as 8 lentes completas de config/lentes.yaml, cada uma com PARIDADE contra o script/relatório antigo que ela
substitui (compliance_agent/aplicacao/lentes_paridade.py roda a régua antiga e a nova sobre a mesma base) ou com a
diferença explicada; o recorte do painel (compliance_agent/aplicacao/lentes_resumo.py) com INDISPONÍVEL ≠ 0 e
indeterminados ao lado do valor; a visão `lente_<nome>` do E15 e as rotas /api/esteira/*; e O7.3 no servidor
(/api/manchetes/estado: só Tier 1 vira manchete; com 0 Tier 1, "nenhuma manchete calibrada" com o porquê).

Números do snapshot da parada (24/11/2026) ficam no `paridade:` de cada lente; aqui a régua é reproduzida em fixture.
"""
import json
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from compliance_agent.aplicacao import lentes_paridade as P
from compliance_agent.aplicacao import lentes_resumo as R
from compliance_agent.fluxo import lentes as L

RAIZ = Path(__file__).resolve().parents[1]
NOMES = {"bombeiros", "couto", "mgs_iterj", "beneficios", "fserj", "pcrj_saude", "emendas", "obras"}
INDICE = {"160100": "SEDEC", "166100": "FUNESBOM", "161601": "Sedec", "133100": "ITERJ", "294200": "FS",
          "226300": "FSERJ", "300100": "OUTRA"}


# ── fixtures ────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def indice(tmp_path, monkeypatch):
    p = tmp_path / "ug_index.json"
    p.write_text(json.dumps({"atualizado_em": "x", "ugs": INDICE}), encoding="utf-8")
    monkeypatch.setattr(L, "INDICE_UG", p)
    return p


def _ob(f, numero, ug, data, valor, processo="", credor="", status="Contabilizado", envio="", reg="", ex=None,
        nome=""):
    f.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (numero, ug, data, status, envio, reg, processo, valor, ex or int(data[-4:]), credor, nome or credor,
               "2026-11-24", "", ""))


@pytest.fixture()
def fonte():
    f = sqlite3.connect(":memory:")
    f.executescript("""
    CREATE TABLE ob_orcamentaria_siafe (numero_ob, ug_emitente, data_emissao, status, status_envio, tipo_regularizacao,
      processo, valor, exercicio, credor, nome_credor, coletado_em, tipo_ob, finalidade);
    CREATE TABLE ob_reemitida (ob, ug);
    CREATE TABLE contratos_tcerj (processo, unidade, objeto, valor_contrato, fornecedor, cnpj);
    CREATE TABLE emendas (codigo, ano, recorte, uf_destino, localidade_gasto, empenhado, liquidado, pago);
    CREATE TABLE socios_fornecedor (cnpj, razao, socio_nome, socio_nome_norm, socio_doc, qualificacao);
    """)
    # bombeiros: 120 OB do prefixo 27 na FUNESBOM e 1 de outra UG no mesmo prefixo — posse 120/121 ≥ 0,95 com ≥ 100
    # OB (a régua REAL do config/lentes.yaml): o prefixo 27 é derivado
    for i in range(120):
        _ob(f, f"2026OB{i}", "166100", "10/04/2026", 10.0 * (i + 1), f"SEI-270006/{i:06d}/2026", "11111111000111")
    _ob(f, "2026OBX", "300100", "10/04/2026", 1.0, "SEI-270006/000099/2026", "22222222000122")
    # ITERJ × MGS: 2 pagas, 1 anulada, 1 sem processo, 1 com nº que não é SEI
    _ob(f, "2025OB1", "133100", "05/05/2025", 100.0, "SEI-330005/000001/2025", P.MGS)
    _ob(f, "2025OB2", "133100", "06/05/2025", 50.0, "", P.MGS)
    _ob(f, "2025OB3", "133100", "07/05/2025", 70.0, "SEI-330005/000002/2025", P.MGS, status="Anulado")
    _ob(f, "2025OB4", "133100", "08/05/2025", 30.0, "123/2024", "33333333000133")
    # Couto (desde 23/03/2026): 1 paga normal, 1 complementar, 1 reemitida, 1 devolvida, 1 sem número, 1 antes
    _ob(f, "2026OBC1", "300100", "24/03/2026", 1000.0, "SEI-080001/000001/2026", "44444444000144")
    _ob(f, "2026OBC2", "300100", "25/03/2026", 200.0, "SEI-080001/000001/2026", "44444444000144",
        envio="Enviado Manualmente", reg="Pagamento Complementar")
    _ob(f, "2026OBC3", "300100", "26/03/2026", 300.0, "SEI-080001/000002/2026", "44444444000144")
    f.execute("INSERT INTO ob_reemitida VALUES ('2026OBC3', '300100')")
    _ob(f, "2026OBC4", "300100", "27/03/2026", 400.0, "SEI-080001/000003/2026", "44444444000144",
        envio="Erro no Pagamento")
    _ob(f, "", "300100", "28/03/2026", 500.0, "SEI-080001/000004/2026", "44444444000144")
    _ob(f, "2026OBC6", "300100", "22/03/2026", 9.0, "SEI-080001/000005/2026", "44444444000144")
    # FSERJ: OB na UG 294200 (FS); contrato do TCE-RJ com a sigla FSERJ (226300 no índice)
    _ob(f, "2025OBF1", "294200", "10/02/2025", 77.0, "SEI-080007/000010/2025", "55555555000155")
    f.executemany("INSERT INTO contratos_tcerj VALUES (?,?,?,?,?,?)", [
        ("SEI-270003/000010/2024", "FUNESBOM - FUNDO ESPECIAL", "AQUISIÇÃO DE VIATURAS", 10.0, "X", "1"),
        ("SEI-080007/000010/2025", "FSERJ - FUNDAÇÃO SAÚDE DO EST. DO RIO DE JANEIRO", "MEDICAMENTOS", 5.0, "Y", "2"),
        ("0123/2025", "FSERJ - FUNDAÇÃO SAÚDE DO EST. DO RIO DE JANEIRO", "LUVAS", 5.0, "Z", "3"),
        # obras: 2 obras de verdade, 3 falsos positivos do critério antigo
        ("SEI-150001/000001/2025", "OUTRA - X", "OBRAS DE REFORMA DA ESCOLA", 900.0, "O", "4"),
        ("SEI-150001/000002/2025", "OUTRA - X", "CONSTRUÇÃO DE PONTE", 800.0, "O", "4"),
        ("SEI-150001/000003/2025", "OUTRA - X", "LIMPEZA COM FORNECIMENTO DE MÃO DE OBRA", 700.0, "M", "5"),
        ("SEI-150001/000004/2025", "OUTRA - X", "PRODUTOS QUÍMICOS COM RECURSOS DE CONVÊNIO PETROBRAS", 60.0, "M", "6"),
        ("SEI-150001/000005/2025", "OUTRA - X", "SERVIÇO DE COBRANÇA BANCÁRIA", 50.0, "M", "7"),
    ])
    _ob(f, "2025OBO1", "300100", "01/06/2025", 4000.0, "SEI-150001/000001/2025", "66666666000166")
    _ob(f, "2025OBO2", "300100", "02/06/2025", 3000.0, "SEI-150001/000003/2025", "77777777000177")
    f.executemany("INSERT INTO emendas VALUES (?,?,?,?,?,?,?,?)", [
        ("1", 2025, "AMBOS", "RJ", "NITERÓI - RJ", 100.0, 80.0, 60.0),
        ("2", 2025, "DESTINO_RJ", "RJ", "CAMPOS - RJ", 50.0, 50.0, 40.0),
        ("3", 2025, "AUTOR_RJ", None, "NACIONAL", 900.0, 900.0, 900.0),
        ("4", 2024, "AUTOR_RJ", "SP", "SÃO PAULO - SP", 10.0, 0.0, 0.0),
    ])
    return f


@pytest.fixture()
def pcrj():
    c = sqlite3.connect(":memory:")
    c.executescript("""
    CREATE TABLE contasrio_contrato (contrato, favorecido_doc, favorecido_nome, orgao, ug, valor_atualizado,
      total_empenhado, total_liquidado, total_pago, coletado_em);
    CREATE TABLE pcrj_ppp (slug, orgao_gestor);
    """)
    c.executemany("INSERT INTO contasrio_contrato VALUES (?,?,?,?,?,?,?,?,?,?)", [
        ("c1", "12345678000199", "HOSP S/A", "1803 - FUNDO MUNICIPAL DE SAÚDE",
         "180061 - HOSPITAL MUNICIPAL SOUZA AGUIAR - COORDENADORIA GERAL DE EMERGÊNCIA DA AP 1", 10.0, 9.0, 8.0, 7.0, "x"),
        ("c2", "12345678901", "PESSOA FISICA", "1801 - SECRETARIA MUNICIPAL DE SAÚDE", "180001 - SMS", 5.0, 5.0, 5.0,
         None, "x"),
        ("c3", "98765432000111", "OUTRA", "1433 - FUNDO DE ASSISTÊNCIA A SAÚDE DO SERVIDOR", "140033 - FASS", 99.0,
         99.0, 99.0, 99.0, "x"),
        ("c4", "98765432000112", "RIOSAUDE", "1851 - EMPRESA PÚBLICA DE SAÚDE DO RIO DE JANEIRO", "180051 - RS", 1.0,
         1.0, 1.0, 1.0, "x"),
    ])
    c.execute("INSERT INTO pcrj_ppp VALUES ('complexo-hospitalar-souza-aguiar', 'CCPAR')")
    return c


def _cfg(indice, nomes=None):
    cfg = L.carregar(indice=indice)
    return {n: cfg[n] for n in (nomes or cfg)}


# ── configuração real ───────────────────────────────────────────────────────────────────────────────────────────
def test_config_real_tem_as_8_lentes_e_referencias_resolvidas():
    from compliance_agent import foco
    from compliance_agent.aplicacao.estagios import periciar
    from compliance_agent.governo_couto import INICIO
    cfg = L.carregar()                                         # UGs conferidas contra data/ug_index_siafe.json real
    assert set(cfg) == NOMES
    assert cfg["couto"].desde == INICIO and cfg["couto"].desde_ref == "governo_couto.INICIO"
    f = foco.config()
    assert cfg["couto"].cota_esforco == (f["fracao"] if f["ligado"] else 0.0) == 0.5
    assert cfg["fserj"].ugs == {"294200", "226300"} and cfg["mgs_iterj"].ugs == {"133100"}
    assert cfg["pcrj_saude"].esfera == "prefeitura" and cfg["emendas"].esfera == "emendas"
    assert periciar.eixos_da_lente(["beneficios"]) == ["beneficios"] and set(cfg["beneficios"].eixos_extra) <= set(
        periciar.NOMES_EIXOS)
    assert cfg["bombeiros"].prioridade == 0.2 and all(cfg[n].prioridade == 0.0 for n in NOMES - {"bombeiros"})
    for n in NOMES:
        assert cfg[n].paridade and cfg[n].descricao, n


@pytest.mark.parametrize("trecho, erro", [
    ("data_fato_desde: '2026-03-23'", "nunca a data escrita"),
    ("credor: ['11111111000111']", "derivado da fonte"),
    ("processo: {derivar: qualquer}", "derivado da fonte"),
])
def test_valor_escrito_a_mao_e_recusado(tmp_path, indice, trecho, erro):
    p = tmp_path / "l.yaml"
    p.write_text(f"versao: 1\nlentes:\n  x:\n    filtro:\n      {trecho}\n", encoding="utf-8")
    with pytest.raises(L.ErroLente, match=erro):
        L.carregar(p, indice)


def test_cota_e_orgaos_da_prefeitura_conferidos(tmp_path, indice, pcrj):
    p = tmp_path / "l.yaml"
    p.write_text("versao: 1\nlentes:\n  x:\n    filtro: {data_fato_desde: governo_couto.INICIO}\n    cota_esforco: 0.5\n",
                 encoding="utf-8")
    with pytest.raises(L.ErroLente, match="nunca o número escrito"):
        L.carregar(p, indice)
    p.write_text("versao: 1\nlentes:\n  s:\n    esfera: prefeitura\n    filtro: {orgao_pcrj: ['1803']}\n"
                 "    conferir_pcrj: {'1803': FUNDO MUNICIPAL DA SAÚDE}\n", encoding="utf-8")
    with pytest.raises(L.ErroLente, match="não confere com o ContasRio"):
        L.resolver(L.carregar(p, indice), None, fonte_pcrj=pcrj)
    p.write_text("versao: 1\nlentes:\n  s:\n    esfera: prefeitura\n    filtro: {orgao_pcrj: ['1803', '1801']}\n"
                 "    conferir_pcrj: {'1803': FUNDO MUNICIPAL DE SAÚDE}\n", encoding="utf-8")
    with pytest.raises(L.ErroLente, match="conferir_pcrj"):
        L.carregar(p, indice)


def test_recorte_de_emendas_inexistente_e_recusado(tmp_path, indice, fonte):
    p = tmp_path / "l.yaml"
    p.write_text("versao: 1\nlentes:\n  e:\n    esfera: emendas\n    filtro: {emendas: {recorte: [DESTINO_SP]}}\n",
                 encoding="utf-8")
    with pytest.raises(L.ErroLente, match="recorte de emendas ausente"):
        L.resolver(L.carregar(p, indice), fonte)


def test_lente_sem_derivacao_nao_responde_calada(indice):
    cfg = _cfg(indice)
    with pytest.raises(L.ErroLente, match="derivação pendente"):
        L.casa(cfg["beneficios"], set(), "080001/000001/2026", {"11111111000111"})
    assert L.bonus(cfg, {"166100"}, "x") == (0.2, ["bombeiros"])   # não derivada não rotula (e não explode)


# ── paridade por lente ──────────────────────────────────────────────────────────────────────────────────────────
def test_paridade_bombeiros_fila_antiga(indice, fonte):
    res, _ = L.resolver(_cfg(indice, ["bombeiros"]), fonte)
    fila = [{"sei": "SEI-270006/000001/2026", "tipo": "CONTRATO"},          # prefixo 27 (posse derivada do SIAFE)
            {"sei": "SEI-270003/000010/2024", "tipo": "LICITADO"},          # UG pela sigla do TCE-RJ
            {"sei": "SEI-270099/000001/2024", "tipo": "LICITACAO", "flags": ["LICITACAO_DE:SEI-270006/000001/2026"]},
            {"sei": "SEI-270098/000001/2024", "tipo": "LICITACAO", "flags": ["LICITACAO_DE:SEI-270099/000001/2024"]},
            {"sei": "SEI-120228/000263/2023", "tipo": "CONTRATO", "flags": ["FDRM_IRM_INDUCTA"]}]   # à mão, outro órgão
    r = P.bombeiros(res["bombeiros"], fila, fonte, indice)
    assert r["antigo"] == {"fila": 5, "sem_cascata": 4}                  # a cascata de 2ª geração sai (dono, 13/11)
    assert r["novo"]["na_lente"] == 3 and r["novo"]["por_motivo"] == {"orgao_sei": 2, "ug": 1}
    assert r["diferencas"]["fora_da_lente"] == ["120228/000263/2023"]   # a diferença explicada no YAML
    assert "FDRM_IRM_INDUCTA" in res["bombeiros"].paridade


BOMB_2026 = (121, 72601.0)          # as 121 OB de abril/2026 dos bombeiros também são do período Couto


def test_paridade_couto_diferenca_e_exatamente_complementar_mais_reemitida(indice, fonte):
    r = P.couto(_cfg(indice, ["couto"])["couto"], fonte)
    # antigo (governo_couto._execucao): C1 + C2 (complementar) + C3 (reemitida); devolvida, sem número e 22/03 fora
    assert r["antigo"] == {"n_obs": BOMB_2026[0] + 3, "pago": BOMB_2026[1] + 1500.0}
    assert r["novo"] == {"n_obs": BOMB_2026[0] + 1, "pago": BOMB_2026[1] + 1000.0}
    d = r["diferencas"]
    assert d["pagamento_complementar"] == {"n": 1, "valor": 200.0, "causa": d["pagamento_complementar"]["causa"]}
    assert d["reemitida"]["n"] == 1 and d["reemitida"]["valor"] == 300.0
    assert d["sem_explicacao"] == {"n": 0, "valor": 0.0} and r["contido"] is True


def test_paridade_mgs_iterj(indice, fonte):
    res, _ = L.resolver(_cfg(indice, ["mgs_iterj"]), fonte)
    r = P.mgs_iterj(res["mgs_iterj"], fonte)
    assert r["contido"] and r["antigo"]["obs_iterj_mgs"] == 3 and r["novo"]["pagas"] == 2
    assert r["novo"]["valor_pago"] == 150.0 and r["diferencas"]["nao_pagas_pela_regua"] == 1


def test_paridade_fserj(indice, fonte):
    r = P.fserj(_cfg(indice, ["fserj"])["fserj"], fonte, indice)
    assert r["contido"] and r["antigo"] == {"contratos": 2, "processos_legiveis": 1}
    assert r["diferencas"]["contrato_sem_processo_legivel"] == 1


def test_paridade_obras_so_tira_falso_positivo(indice, fonte):
    res, med = L.resolver(_cfg(indice, ["obras"]), fonte)
    r = P.obras(res["obras"], fonte)
    assert r["contido"] and r["antigo"]["contratos"] == 5 and r["novo"]["contratos"] == 2
    assert r["diferencas"]["fora_do_criterio_novo"] == {"mão de obra": 1, "substring:petrobras": 1,
                                                        "substring:cobrança": 1}
    assert res["obras"].processos == {"150001/000001/2025", "150001/000002/2025"}
    for o, e in (("OBRAS PÚBLICAS", True), ("obra", True), ("MANOBRA DE VEÍCULOS", False), ("DESDOBRAMENTO", False),
                 ("REFORMA DO TELHADO", True), ("FORNECIMENTO DE MAO-DE-OBRA", False), ("OBRASPÚBLICAS", True)):
        assert L.e_obra(o) is e, o


def test_paridade_emendas_fora_e_so_autor_sem_destino_rj(indice, fonte):
    cfg = _cfg(indice, ["emendas"])
    r = P.emendas(cfg["emendas"], fonte)
    assert r["antigo"]["emendas"] == 4 and r["novo"]["emendas"] == 2
    assert r["diferencas"]["fora_por_recorte"] == {"AUTOR_RJ": 2}
    assert r["diferencas"]["fora_por_uf_destino"] == {"(sem UF)": 1, "SP": 1}


def test_paridade_pcrj_saude(indice, pcrj):
    res, med = L.resolver(_cfg(indice, ["pcrj_saude"]), None, fonte_pcrj=pcrj)
    assert med["pcrj_saude"]["orgao_pcrj"] == {"1801": 1, "1803": 1, "1851": 1}
    r = P.pcrj_saude(res["pcrj_saude"], pcrj)
    assert r["contido"] and r["antigo"]["contratos_hospital_souza_aguiar"] == 1
    assert r["diferencas"]["ppp_orgao_gestor"] == "CCPAR"


def test_paridade_beneficios_mesma_funcao_do_relatorio(tmp_path, indice, monkeypatch):
    """A lente deriva os credores pela MESMA analisar() do relatório antigo, sobre bancos de fixture."""
    from compliance_agent.pcrj import db as PDB
    ben, comp = tmp_path / "benef.db", tmp_path / "compliance.db"
    b = sqlite3.connect(ben)
    b.execute("CREATE TABLE pcrj_beneficio (nome_norm, cpf_frag, beneficio, competencia, municipio)")
    b.executemany("INSERT INTO pcrj_beneficio VALUES (?,?,?,?,?)", [
        ("JOAO DA SILVA", "123456", "BOLSA FAMILIA", "2025-01", "RIO DE JANEIRO"),
        ("MARIA SOUZA", "999999", "BOLSA FAMILIA", "2025-01", "RIO DE JANEIRO"),
        ("ANA LIMA", "", "BPC", "2025-02", "RIO DE JANEIRO")])
    b.commit()
    b.close()
    c = sqlite3.connect(comp)
    c.executescript("""CREATE TABLE socios_fornecedor (cnpj, razao, socio_nome, socio_nome_norm, socio_doc, qualificacao);
      CREATE TABLE ob_orcamentaria_siafe (numero_ob, ug_emitente, data_emissao, status, status_envio, processo, valor,
        exercicio, credor, nome_credor);""")
    c.executemany("INSERT INTO socios_fornecedor VALUES (?,?,?,?,?,?)", [
        ("11111111000111", "EMPRESA A", "JOAO DA SILVA", "JOAO DA SILVA", "***123456**", "SOCIO"),   # ALTA
        ("22222222000122", "EMPRESA B", "MARIA SOUZA", "MARIA SOUZA", "***111111**", "SOCIO"),       # DESCARTADO
        ("33333333000133", "EMPRESA C", "ANA LIMA", "ANA LIMA", "***222222**", "SOCIO")])            # SEM_FRAGMENTO
    c.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('2025OB9','300100','01/02/2025','Contabilizado','',"
              "'SEI-080001/000009/2025',10.0,2025,'11111111000111','EMPRESA A')")
    c.commit()
    monkeypatch.setattr(PDB, "BENEF_DB", ben)
    monkeypatch.setattr(PDB, "COMPLIANCE_DB", comp)
    res, med = L.resolver(_cfg(indice, ["beneficios"]), None, externas=True)
    assert res["beneficios"].credores == {"11111111000111", "33333333000133"}
    assert med["beneficios"]["credor"]["registros"] == 2
    r = P.beneficios(res["beneficios"])
    assert r["contido"] and not r["diferencas"]["so_na_lente"]
    assert L.casa(res["beneficios"], {"300100"}, "080001/000009/2025", {"11111111000111"}) == "credor:11111111000111"
    corpo = R.recorte_ob(c, res["beneficios"])
    assert corpo["universo"]["obs_pagas"] == 1 and corpo["universo"]["valor_pago"] == 10.0
    c.close()


# ── o recorte do painel ─────────────────────────────────────────────────────────────────────────────────────────
def test_recorte_estado_indeterminado_ao_lado_do_valor(indice, fonte):
    res, _ = L.resolver(_cfg(indice, ["mgs_iterj"]), fonte)
    d = R.recorte_ob(fonte, res["mgs_iterj"])
    u = d["universo"]
    assert u["obs"] == 4 and u["obs_pagas"] == 3 and u["valor_pago"] == 180.0
    assert u["fora_da_soma"] == {"obs": 1, "valor": 70.0, "o_que_e": u["fora_da_soma"]["o_que_e"]}
    assert d["determinavel"]["obs"] == 1 and d["determinavel"]["valor"] == 100.0
    assert d["indeterminado"]["sem_processo"] == {"obs": 1, "valor": 50.0}
    assert d["indeterminado"]["processo_nao_sei"]["obs"] == 1 and d["indeterminado"]["processo_nao_sei"]["valor"] == 30.0
    assert d["cobertura"]["fracao_do_pago_ligavel_ao_sei"] == round(100 / 180, 4)


def test_recorte_couto_e_o_da_regua_canonica(indice, fonte):
    d = R.recorte_ob(fonte, _cfg(indice, ["couto"])["couto"])
    assert d["universo"]["obs_pagas"] == BOMB_2026[0] + 1                          # 22/03 e as não pagas ficam fora
    assert d["universo"]["valor_pago"] == BOMB_2026[1] + 1000.0


def test_calcular_inteiro_com_achados_e_fila(indice, fonte):
    ach = sqlite3.connect(":memory:")
    ach.execute("CREATE TABLE achado_detector (ug, detector, processo, escopo, score, status)")
    ach.executemany("INSERT INTO achado_detector VALUES (?,?,?,?,?,?)", [
        ("166100", "C7", "SEI-270006/000001/2026", "", 1, "nao_avaliavel"),
        ("FUNESBOM - FUNDO ESPECIAL", "C7", "", "", 1, "confirmado"),
        ("ORGAO SEM SIGLA NO INDICE", "C7", "", "", 1, "confirmado"),
        ("300100", "C7", "SEI-080001/000001/2026", "", 1, "confirmado")])
    d = R.calcular("bombeiros", fonte=fonte, achados=ach, sinais={}, lentes_cfg=_cfg(indice))
    a = d["achados"]
    assert a["totais"] == {"confirmado": 1, "descartado": 0, "nao_avaliavel": 1}   # nao_avaliavel VISÍVEL
    assert a["base_ug_em_texto_nao_conferivel"]["achados"] == 1
    assert a["detectores"][0]["registro"] and "tier" in a["detectores"][0]
    fl = d["fila"]
    assert "NÃO é probabilidade" in fl["rotulo"] and fl["itens"][0]["processo"] == "270006/000119/2026"
    assert set(fl["itens"][0]["componentes"]) >= {"escalar_valor", "bonus_lente", "couto", "manual"}
    assert fl["itens"][0]["componentes"]["bonus_lente"] == 0.2 and fl["itens"][0]["lente_motivo"] == "ug:166100"
    assert d["universo"]["n"] == 121 and d["derivacao"]["orgao_sei"] == ["27"] and d["ok"] is True


def test_achados_de_lente_por_data_sao_indeterminaveis(indice, fonte):
    ach = sqlite3.connect(":memory:")
    ach.execute("CREATE TABLE achado_detector (ug, detector, processo, escopo, score, status)")
    d = R.calcular("couto", fonte=fonte, achados=ach, sinais={}, lentes_cfg=_cfg(indice))
    assert d["achados"]["estado"] == "INDETERMINAVEL" and d["fila"]["estado"] == "NAO_SE_APLICA"


def test_recorte_prefeitura_e_emendas_separam_fases(indice, fonte, pcrj):
    d = R.calcular("pcrj_saude", fonte_pcrj=pcrj, lentes_cfg=_cfg(indice))
    u = d["universo"]
    assert u["contratos"] == 3 and u["pago"] == 8.0 and u["empenhado"] == 15.0      # FASS (1433) fora
    assert d["indeterminado"]["contratos_sem_pago_informado"] == 1                    # INDISPONÍVEL ≠ R$ 0,00
    assert all("*" in x["doc"] for x in d["favorecidos_topo"] if x["tipo"] == "CPF")  # CPF mascarado
    e = R.calcular("emendas", fonte=fonte, lentes_cfg=_cfg(indice))
    assert e["universo"] == {"n": 2, "emendas": 2, "empenhado": 150.0, "liquidado": 130.0, "pago": 100.0}
    assert "SIAFI" in e["fonte"] and e["fora_da_lente"]["emendas"] == 2


# ── E15 + rotas ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_visao_de_lente_no_e15_e_rota_so_le(tmp_path, monkeypatch, indice, fonte):
    from compliance_agent.aplicacao.estagios import materializar as M
    db = tmp_path / "c.db"
    disco = sqlite3.connect(db)
    fonte.commit()                          # backup de conexão com transação aberta fica em SQLITE_BUSY para sempre
    fonte.backup(disco)
    disco.close()
    monkeypatch.setenv(R.ENV_FONTE, str(db))
    monkeypatch.setenv(R.ENV_ACHADOS, str(tmp_path / "nao_existe.db"))
    monkeypatch.setattr("compliance_agent.aplicacao.estagios.arvore.sinais_sweep", lambda f: {})
    assert {f"lente_{n}" for n in NOMES} <= set(M.VISOES)
    from rotas import esteira
    cli = TestClient(_app(esteira))
    antes = cli.get("/api/esteira/lente", params={"lente": "mgs_iterj"})
    assert antes.status_code == 503 and antes.json()["estado"] == "INDISPONIVEL"      # nunca calcula em request
    assert M.main(["rodar", "--visao", "lente_mgs_iterj"]) == 0
    r = cli.get("/api/esteira/lente", params={"lente": "mgs_iterj"})
    assert r.status_code == 200 and r.headers["X-JFN-Lente"] == "mgs_iterj" and r.headers["X-JFN-Visao"]
    assert r.json()["universo"]["valor_pago"] == 180.0
    assert M.ler_meta("lente_mgs_iterj")["universo"] == 4
    assert cli.get("/api/esteira/lente", params={"lente": "orgao_x"}).status_code == 404
    cat = cli.get("/api/esteira/lentes").json()
    assert cat["ok"] and {x["lente"] for x in cat["lentes"]} == NOMES
    assert {x["lente"]: x["visao"]["estado"] for x in cat["lentes"]}["mgs_iterj"] == "FRESCA"


def _app(*mods):
    from fastapi import FastAPI
    app = FastAPI()
    for m in mods:
        app.include_router(m.router)
    return app


# ── O7.3 no servidor ────────────────────────────────────────────────────────────────────────────────────────────
def test_manchetes_estado_sem_tier1_fecha_tudo_e_explica():
    from rotas import qualidade
    d = TestClient(_app(qualidade)).get("/api/manchetes/estado").json()
    assert d["ok"] and d["por_tier"]["1"] == 0 and not d["manchetes_efetivas"]
    assert d["explicacao"].startswith("Nenhuma manchete calibrada")
    gated = [s for s in d["superficies"] if s["detector"]]
    assert gated and not any(s["liberada"] for s in gated)
    assert all("não é manchete" in s["motivo"] for s in gated)
    assert all(s["liberada"] for s in d["superficies"] if not s["detector"])          # medição do sistema segue


def test_manchetes_estado_libera_so_o_tier1(monkeypatch):
    from compliance_agent.qualidade import detectores as RG
    from compliance_agent.qualidade import manchete_painel as MP
    original, alvo = RG.campos_calculados, RG.carregar()["rules.engine"]

    def falso(e, hoje=None):
        c = original(e, hoje)
        return {**c, "tier": 1, "tier_motivo": "cumpre_tier1", "manchete_efetiva": bool(e.get("manchete"))} \
            if e is alvo else c
    monkeypatch.setattr(RG, "campos_calculados", falso)
    d = MP.estado()
    lib = {s["id"] for s in d["superficies"] if s["detector"] and s["liberada"]}
    assert lib == {"cki-alertas", "v63-alertas"} and d["manchetes_efetivas"] == ["rules.engine"]


def test_inventario_e_js_toda_manchete_de_detector_passa_pelo_gate():
    import yaml
    inv = yaml.safe_load((RAIZ / "config/qualidade_inventario.yaml").read_text(encoding="utf-8"))
    src = {p.name: p.read_text(encoding="utf-8") for p in (RAIZ / "static/js/src").rglob("*.js")}
    tudo = "\n".join(src.values())
    for m in inv["manchetes"]:
        if not m.get("detector"):
            continue
        i = m["id"]
        if i.startswith("cki-"):        # os cartões passam por ckFill, que consulta mancheteLiberada('cki-'+id)
            assert "mancheteLiberada('cki-'+id)" in src["cockpit.js"]
        else:
            assert f"mancheteLiberada('{i}')" in tudo, i
    assert not re.search(r"34 (alertas )?conferidos|13 não se sustentaram|conferidos 34", tudo)   # sai o "34/13"
