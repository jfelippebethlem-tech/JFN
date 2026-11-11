# -*- coding: utf-8 -*-
"""Motor território: objeto → município (Estado) / AP (PCRJ), com as armadilhas do brief v61.

Os textos são objetos REAIS de contrato (PNCP do Estado e Contas Rio) ou variações mínimas deles; o
teste não toca `compliance.db` nem `pcrj.db` — a função de atribuição é pura.
"""
from __future__ import annotations

import pytest

from compliance_agent.territorio import atribui_estado as ae
from compliance_agent.territorio import atribui_pcrj as ap
from compliance_agent.territorio.dicionario import ler_bairros, ler_municipios
from compliance_agent.territorio.geo import RIO, bairros, municipios, norm

REG = ae._unidades_regionais()


def _muns(texto):
    return sorted(a.nome for a in ler_municipios(texto).municipios)


def test_referencia_tem_os_92_municipios_e_os_167_bairros():
    assert len(municipios()) == 92 and len({m["cod_ibge"] for m in municipios()}) == 92
    assert len(bairros()) == 167 and {int(b["ap"]) for b in bairros()} == {1, 2, 3, 4, 5}
    assert norm("Varre-Sai") == "VARRE SAI" and norm("São João de Meriti/RJ") == "SAO JOAO DE MERITI RJ"


# ── (A) Estado → município: casos que TÊM de casar ─────────────────────────────────────────────
@pytest.mark.parametrize("objeto, esperado", [
    ("CONTRATAÇÃO DE EMPRESA PARA EXECUÇÃO DE OBRA EMERGENCIAL DE CONTENÇÃO PARA REFORÇO ESTRUTURAL DO VIADUTO DOM ADRIANO "
     "HIPÓLITO, NA RODOVIA RJ-081, MUNICÍPIO DE NOVA IGUAÇU/RJ.", ["Nova Iguaçu"]),
    ("Despesas estimadas com o consumo de água para o Exercício 2025, do Terminal Rodoviário de Cabo Frio.", ["Cabo Frio"]),
    ("serviço de seguro imobiliário do imóvel onde se encontra sediado o quartel do 15º GBM- Avenida Barão de Rio Branco, "
     "nº 1957 - Centro – Petrópolis", ["Petrópolis"]),
    ("Contratação do grupo musical Os Garotin para a realização de apresentação ao vivo no município de Búzios/RJ",
     ["Armação dos Búzios"]),
    ("Manutenção do posto do DETRAN em Parati", ["Paraty"]),
    ("Reforma da delegacia de Caxias", ["Duque de Caxias"]),
    ("Fornecimento de refeições para a unidade prisional em Campos", ["Campos dos Goytacazes"]),
    ("Recuperação de encostas em Trajano de Morais", ["Trajano de Moraes"]),
    ("Obras de drenagem no município de Varre-Sai", ["Varre-Sai"]),
    ("Construção de escola em São João de Meriti - RJ", ["São João de Meriti"]),
    ("Dragagem do canal de acesso em São João da Barra", ["São João da Barra"]),
    ("Locação de veículos para a delegacia de Barra do Piraí", ["Barra do Piraí"]),
    ("Serviço de limpeza na UPA de Mesquita/RJ", ["Mesquita"]),
    ("Manutenção predial do Fórum de Vassouras", ["Vassouras"]),
    ("Pavimentação da RJ-116 em Rio Bonito", ["Rio Bonito"]),
    ("Locação de imóvel no bairro do Recreio dos Bandeirantes, município do Rio de Janeiro – RJ.", ["Rio de Janeiro"]),
    ("Contratação de serviços de apoio operacional e administrativo a serem executados nas UPA de Jacarepaguá", ["Rio de Janeiro"]),
    ("Apresentação no dia 02/03 no municipio de Eng Paulo de Frontin", ["Engenheiro Paulo de Frontin"]),
])
def test_estado_municipio_casa(objeto, esperado):
    assert _muns(objeto) == esperado


# ── as armadilhas: NÃO podem virar município ───────────────────────────────────────────────────
@pytest.mark.parametrize("objeto", [
    "Serviços de vigilância para as unidades do Estado do Rio de Janeiro",           # "Rio" sozinho é o Estado
    "Aquisição de vassouras e material de limpeza para a SEEDUC",                    # vassoura não é Vassouras
    "Aquisição de insumos para o Centro de Tratamento de Queimados",                 # queimados não é Queimados
    "Campos de futebol society para a SUDERJ",                                       # campos não é Campos
    "Obras na Rua Barão de Mesquita",                                                # logradouro não é Mesquita
    "Reforma do Colégio Estadual Casimiro de Abreu",                                 # homenagem não é o município
    "Reforma do Colégio Estadual Duque de Caxias",                                   # idem
    "Monitoramento da qualidade da água do Rio Paraíba do Sul",                      # rio não é Paraíba do Sul
    "Contratação do ator para o espetáculo Copacabana (Tu) Não Me Engana, uma revuette carioca",   # título, não lugar
    "Integralização de capital social da companhia",                                 # "capital" financeiro
    "Aquisição de móveis da marca Itatiaia",                                         # marca
])
def test_estado_armadilha_nao_casa(objeto):
    assert _muns(objeto) == []


def test_rio_das_ostras_rio_bonito_e_rio_claro_nao_sao_a_capital():
    assert _muns("Pavimentação em Rio das Ostras, Rio Bonito e no município de Rio Claro") == ["Rio Bonito", "Rio Claro", "Rio das Ostras"]
    assert RIO not in [a.cod_ibge for a in ler_municipios("Obras em Rio das Ostras").municipios]


def test_regiao_nao_espalha_valor():
    lei = ler_municipios("Atendimento às unidades de saúde da Região Serrana")
    assert lei.municipios == [] and lei.regiao == "Região Serrana"
    at = ae.atribuir("Atendimento às unidades da Baixada Fluminense", "FUNDO ESTADUAL DE SAÚDE", REG, [])
    assert at["cod_ibge"] is None and at["multi"] == 0 and at["regiao"] == "Baixada Fluminense"


def test_varios_municipios_viram_multi_sem_dividir():
    at = ae.atribuir("transporte escolar para alunos residentes em Barra Mansa e Volta Redonda", "SECRETARIA DE ESTADO DE EDUCACAO", REG, [])
    assert at["multi"] == 1 and at["cod_ibge"] is None
    assert sorted(m["nome"] for m in at["municipios"]) == ["Barra Mansa", "Volta Redonda"]


def test_sede_do_orgao_nao_e_local_de_execucao_mas_unidade_de_sitio_unico_e():
    # secretaria com sede na capital: sem pista no objeto, fica SEM município
    assert ae.atribuir("Aquisição de gêneros alimentícios", "SECRETARIA DE ESTADO DE EDUCACAO", REG, [])["cod_ibge"] is None
    at = ae.atribuir("Diazepam 5 mg cp", "HOSPITAL UNIVERSITARIO PEDRO ERNESTO", REG, [])
    assert at["cod_ibge"] == RIO and at["metodo"] == "campo" and at["confianca"] == "alta"
    at = ae.atribuir("Aquisição de gases químicos.", "Univ Est do Norte Fluminense Darcy Rib", REG, [])
    assert at["cod_ibge"] == "3301009" and at["confianca"] == "media"


def test_metodo_mais_forte_vence_e_todos_ficam_guardados():
    at = ae.atribuir("Manutenção de equipamento, entrega na Rua X, CEP 20551-030, e no polo de Resende/RJ", "HOSPITAL UNIVERSITARIO PEDRO ERNESTO", REG, [])
    assert at["metodo"] == "campo" and [m["metodo"] for m in at["metodos"]] == ["campo", "endereco", "texto"]


def test_cep_so_resolve_a_faixa_da_capital():
    assert ae.atribuir("Reforma no endereço Av. Erasmo Braga 118, CEP 20020-000", "PROCURADORIA GERAL DO ESTADO", REG, [])["metodo"] == "endereco"
    assert ae.atribuir("Entrega no CEP 28013-602", "SECRETARIA DE ESTADO DE EDUCACAO", REG, [])["cod_ibge"] is None


@pytest.mark.parametrize("unidade, esfera", [
    ("FUNDO ESTADUAL DE SAÚDE", "estadual"), ("ADMINISTRACAO CENTRAL", "estadual"), ("FUNDAÇÃO LEÃO XIII", "estadual"),
    ("FUND DEP ESTRADAS DE RODAGEM DO ESTADO DO RJ", "estadual"), ("Univ Est do Norte Fluminense Darcy Rib", "estadual"),
    ("PREF.MUN.DO RIO DE JANEIRO/RJ", "municipal"), ("FUNDAÇAO DE ARTE DE NITEROI", "municipal"),
    ("FUNDO COMUNITÁRIO DE VOLTA REDONDA", "municipal"), ("INSTITUTO PREV.SERV.PÚB.DE SÃO P.DA ALDEIA/RJ", "municipal"),
    ("AUTARQUIA DE SERVIÇOS DE OBRAS DE MARICÁ", "municipal"), ("PORTO REAL", "municipal"),
    ("DEFENSORIA PÚBLICA DO EST DO RIO DE JANEIRO", "outro"), ("CONSELHO DE ARQUITETURA E URBANISMO RJ", "outro"),
])
def test_contrato_de_prefeitura_fica_fora(unidade, esfera):
    assert ae.esfera_unidade(unidade) == esfera


def test_status_rescisao_vem_como_termo_de_rescisao():
    assert ae.eh_rescisao("Termo de Rescisão") and ae.eh_rescisao("Rescisão") and not ae.eh_rescisao("Termo Aditivo")
    assert not ae.eh_rescisao(None) and not ae.eh_rescisao("Termo de Apostilamento")
    assert ae.status_de(True, "2030-01-01", "2026-11-11") == "rescindido"            # rescindido vence a vigência
    assert ae.status_de(False, "2026-11-11", "2026-11-11") == "em_execucao"          # vence hoje: ainda em execução
    assert ae.status_de(False, "2026-11-10", "2026-11-11") == "executado"
    assert ae.status_de(False, None, "2026-11-11") == "executado"


# ── (B) PCRJ → AP ──────────────────────────────────────────────────────────────────────────────
ORG = ap.orgaos_regionais()
CRE = ap.cre_para_ap(ORG)


@pytest.mark.parametrize("ug, objeto, esperado, metodo", [
    ("160008 - 7ª COORDENADORIA REGIONAL DE EDUCAÇÃO", "MANUTENÇÃO PREVENTIVA E CORRETIVA DE ELEVADORES", 4, "orgao"),
    ("160002 - 1ª COORDENADORIA REGIONAL DE EDUCAÇÃO", "Fornecimento de água", 1, "orgao"),
    ("160016 - 11ª COORDENADORIA REGIONAL DE EDUCAÇÃO", "Fornecimento de água", 3, "orgao"),     # 11ª ≠ 1ª
    ("180012 - COORDENADORIA GERAL DE ATENÇÃO PRIMÁRIA DA AP 5.1", "Serviço de limpeza", 5, "orgao"),
    ("180070 - HOSPITAL MUNICIPAL SALGADO FILHO - COORDENADORIA GERAL DE EMERGÊNCIA DA AP 3.2", "ALIMENTAÇÃO", 3, "orgao"),
    ("180067 - HOSPITAL MUNICIPAL JESUS", "ESTERILZAÇÃO DE MATERIAIS", 2, "orgao"),
    ("1501 - SECRETARIA MUNICIPAL DE INFRAESTRUTURA", "OBRAS NA RUA DAS ARARAS, NO BAIRRO DE SEPETIBA - XIX R.A. - AP 5.3", 5, "orgao"),
    ("1601 - SECRETARIA MUNICIPAL DE EDUCAÇÃO", "Abastecimento de água nas Unidades Escolares da E/8ª CRE", 5, "orgao"),
    ("3001 - FUNDO MUNICIPAL DE HABITAÇÃO", "REGULARIZAÇÃO URBANISTICA NA COMUNIDADE DENOMINADA COMPLEXO DO ALEMÃO", 3, "texto"),
    ("1201 - SECRETARIA MUNICIPAL DE CULTURA", "PROJETO CORO DA ROCINHA", 2, "texto"),
    ("2001 - SECRETARIA MUNICIPAL DE TRABALHO E RENDA", "distribuição de alimentos na unidade de Bangu do Restaurante Popular", 5, "texto"),
    ("1501 - SECRETARIA MUNICIPAL DE INFRAESTRUTURA", "Obras no bairro de Santa Cruz", 5, "texto"),
])
def test_pcrj_ap(ug, objeto, esperado, metodo):
    at = ap.atribuir(objeto, ug, ORG, CRE, [])
    assert (at["ap"], at["metodo"]) == (esperado, metodo)


def test_pcrj_sem_ap_e_multi():
    assert ap.atribuir("Manutenção da Secretaria Municipal de Saúde", "1801 - SECRETARIA MUNICIPAL DE SAÚDE", ORG, CRE, [])["ap"] is None
    assert ap.atribuir("Evento no Centro", "1201 - SECRETARIA MUNICIPAL DE CULTURA", ORG, CRE, [])["ap"] is None   # "Centro" é ambíguo
    at = ap.atribuir("Intervenções urgentes e pontuais nas AP-1 e AP-2.1", "GEO-RIO", ORG, CRE, [])
    assert at["multi"] == 1 and at["ap"] is None and at["aps"] == [1, 2]


def test_bairro_ambiguo_so_com_locativo():
    assert ler_bairros("Hospital da Penha") == [] and [b["bairro"] for b in ler_bairros("Obras no bairro da Penha")] == ["Penha"]
    assert ler_bairros("Secretaria Municipal de Saúde") == []


# ── API ────────────────────────────────────────────────────────────────────────────────────────
def test_api_territorio(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from compliance_agent.territorio import agrega, api, base
    monkeypatch.setattr(base, "DATA", tmp_path)
    monkeypatch.setattr(base, "DB", tmp_path / "territorio.db")
    app = FastAPI()
    app.include_router(api.router)
    cli = TestClient(app)
    assert cli.get("/api/territorio/estado").status_code == 503          # motor nunca rodou: INDISPONÍVEL, não zero
    db = base.abrir(escrita=True)
    linhas = [("c1", "3301009", 0, '[{"cod_ibge":"3301009","nome":"Campos dos Goytacazes"}]', 1000.0, 400.0, "em_execucao", "texto"),
              ("c2", None, 0, "[]", 500.0, None, "executado", None),
              ("c3", None, 1, '[{"cod_ibge":"3301009","nome":"Campos dos Goytacazes"},{"cod_ibge":"3302403","nome":"Macaé"}]', 900.0, None, "em_execucao", "texto")]
    for cid, cod, multi, js, valor, pago, status, met in linhas:
        db.execute("INSERT INTO territorio_contrato_estado(contrato_id,fonte,orgao,fornecedor_cnpj,objeto,valor,vig_ini,vig_fim,status,pago,"
                   "cod_ibge,multi,municipios_json,metodo,confianca) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (cid, "t", "ORG", "1", "obj", valor, "2025-01-01", "2030-01-01", status, pago, cod, multi, js, met, "media"))
    db.commit()
    db.close()
    agrega.rodar(log=lambda m: None)
    r = cli.get("/api/territorio/estado?periodo=tudo")
    j = r.json()
    assert r.status_code == 200 and r.headers["etag"] and "max-age=600" in r.headers["cache-control"]
    assert cli.get("/api/territorio/estado?periodo=tudo", headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    assert len(j["municipios"]) == 92 and j["fonte"] and j["atualizado_em"]
    campos = next(m for m in j["municipios"] if m["cod_ibge"] == "3301009")
    assert campos["valor_contratado"] == 1000.0 and campos["pago"] == 400.0 and campos["n_multi"] == 1    # o multi NÃO soma valor
    macae = next(m for m in j["municipios"] if m["cod_ibge"] == "3302403")
    assert macae["n_contratos"] == 0 and macae["pago"] is None and macae["n_multi"] == 1                 # sem pagamento = None, não 0
    assert j["baldes"]["sem_municipio"] == {"n": 1, "valor": 500.0} and j["baldes"]["multimunicipio"] == {"n": 1, "valor": 900.0}
    f = cli.get("/api/territorio/estado/3301009?periodo=tudo").json()
    assert f["kpis"]["n_em_execucao"] == 1 and f["kpis"]["n_multi"] == 1 and len(f["contratos"]) == 2 and f["alertas"] is None
    assert cli.get("/api/territorio/estado/0000000").status_code == 404 and cli.get("/api/territorio/pcrj/7").status_code == 404
    assert len(cli.get("/api/territorio/pcrj").json()["aps"]) == 5
    assert cli.get("/api/territorio/baldes").json()["estado"]["multimunicipio"]["n"] == 1
