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
    assert ae.status_de(False, None, "2026-11-11") == "sem_vigencia"                 # a fonte não diz o fim: não é "executado"


# ── fase 7b: unidades (CNES, ISP), distritos e abrangência ─────────────────────────────────────
UNID = ae.carregar_unidades()


@pytest.mark.parametrize("objeto, esperado, metodo", [
    ("serviços assistenciais a serem executados no Hospital Estadual Azevedo Lima", ["Niterói"], "unidade"),
    ("serviços médicos no Hospital Estadual Ricardo Cruz", ["Nova Iguaçu"], "unidade"),              # CNES grava "DR RICARDO CRUZ"
    ("APOIO ASSISTENCIAL COM EQUIPE MULTIDISCIPLINAR - HERCRUZ", ["Nova Iguaçu"], "unidade"),         # sigla → CNES
    ("manutenção predial do IECAC", ["Rio de Janeiro"], "unidade"),
    ("coleta de resíduos do Hospital Estadual Getulio Vargas", ["Rio de Janeiro"], "unidade"),
    ("materiais para a Policlínica Piquet Carneiro", ["Rio de Janeiro"], "unidade"),
    ("Reforma da 105ª DP", ["Petrópolis"], "unidade"),                                                # ISP: circunscrição da delegacia
    ("AQUISIÇÃO DE MATERIAL DE CONSTRUÇÃO PARA O 14° BPM.", ["Rio de Janeiro"], "unidade"),           # AISP de município único
    ("obras no quartel do 16º GBM, em Itaipava", ["Petrópolis"], "texto"),                            # distrito (IBGE)
    ("pavimentação no distrito de Posse", ["Petrópolis"], "texto"),                                   # distrito genérico só com âncora
    ("recuperação da estrada em Xerém", ["Duque de Caxias"], "texto"),
])
def test_unidades_e_distritos(objeto, esperado, metodo):
    at = ae.atribuir(objeto, "FUNDAÇÃO SAÚDE DO EST. DO RIO DE JANEIRO", REG, UNID)
    assert (sorted(m["nome"] for m in at["municipios"]), at["metodo"]) == (esperado, metodo)


def test_bpm_de_varios_municipios_e_distrito_generico_nao_casam():
    assert ae.atribuir("viaturas para o 10º BPM", "SEPM", REG, UNID)["cod_ibge"] is None      # AISP com mais de um município
    assert ae.atribuir("posse de terreno pela companhia", "CEHAB", REG, UNID)["cod_ibge"] is None


@pytest.mark.parametrize("objeto, orgao, trecho", [
    ("AQUISIÇÃO DE MEDICAMENTOS", "FUNDO ESTADUAL DE SAÚDE", "aquisição distribuída à rede"),
    ("licença de software para elaboração de orçamento de obras", "Fundo Especial de Adm Fazendária", "tecnologia corporativa"),
    ("aquisição de Material de Apoio Pedagógico para a Rede Pública Estadual de Ensino", "SECRETARIA DE ESTADO DE EDUCACAO", "rede estadual"),
    ("CREDENCIAMENTO DE SERVIÇOS DE UNIDADES HOSPITALARES DO SETOR PRIVADO", "FUNDO ESTADUAL DE SAÚDE", "âmbito estadual"),
    ("Aquisição de deionizador", "Secretaria de Estado da Casa Civil", "órgão-meio"),
])
def test_balde_estado_inteiro_tem_motivo_gravado(objeto, orgao, trecho):
    at = ae.atribuir(objeto, orgao, REG, UNID)
    assert at["cod_ibge"] is None and at["abrangencia"] == "estado_inteiro" and trecho in at["evidencia"]


def test_sem_pista_continua_sem_municipio_e_lugar_vence_a_abrangencia():
    at = ae.atribuir("Conforme consta no Processo nº. 350006/002446/2025.", "Secretaria de Estado de Polícia Militar", REG, UNID)
    assert at["cod_ibge"] is None and at["abrangencia"] is None                                # não se sabe ≠ estado inteiro
    at = ae.atribuir("seguro do imóvel do quartel do 15º GBM, Centro – Petrópolis", "FUNDO ESPECIAL DO CORPO DE BOMBEIROS", REG, UNID)
    assert at["cod_ibge"] == "3303906" and at["abrangencia"] is None                           # "seguro" não rouba contrato que tem lugar


def test_pcrj_unidades_ra_e_cidade_inteira():
    saude, ras = ap.unidades_saude(), ap.ra_para_ap()
    f = lambda o, ug="1801 - SECRETARIA MUNICIPAL DE SAÚDE": ap.atribuir(o, ug, ORG, CRE, [], saude, ras, ug)   # noqa: E731
    assert (f("locação de ambulância para o HOSPITAL MUNICIPAL ROCHA FARIA")["ap"], f("x HOSPITAL MUNICIPAL ROCHA FARIA")["metodo"]) == (5, "unidade")
    assert f("OBRAS NA ESTRADA DO TINGUI, NA ÁREA DA XVIII R.A.")["ap"] == 5                    # XVIII RA = Campo Grande
    assert f("Conservação de pavimentos na Área da AP1 e AP2")["aps"] == [1, 2]                 # "AP1" colado
    assert f("locação de imóvel, apartamento AP 101")["ap"] is None
    assert f("OBRAS DO PARQUE - AVENIDA CESÁRIO DE MELO, 6851 - CAMPO GRANDE")["ap"] == 5       # nº do logradouro ancora o bairro
    at = f("LEI MUNICIPAL DE INCENTIVO À CULTURA PROJETO ?PROGRAMAÇÃO BANGU 2024? C.I. HOSPITAIS INTEGRADOS DA GAVEA", "1201 - CULTURA")
    assert at["ap"] == 5 and at["multi"] == 0                                                   # patrocinador não é lugar
    at = f("UNIFORME ESCOLAR", "1601 - SECRETARIA MUNICIPAL DE EDUCAÇÃO")
    assert at["ap"] is None and at["abrangencia"] == "cidade_inteira"
    assert f("Termo de cooperação técnica")["abrangencia"] is None


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
                   "cod_ibge,multi,municipios_json,metodo,confianca,grau) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (cid, "t", "ORG", "1", "obj", valor, "2025-01-01", "2030-01-01", status, pago, cod, multi, js, met, "media",
                    "explicito" if cod else None))
    db.commit()
    db.close()
    agrega.rodar(log=lambda m: None)
    assert cli.get("/api/territorio/estado").status_code == 503          # banco de versão anterior do motor: INDISPONÍVEL
    db = base.abrir(escrita=True)
    base.por_meta(db, "estado_versao", "12")
    db.commit()
    db.close()
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
    assert f["kpis"]["n_em_execucao"] == 1 and f["kpis"]["n_multi"] == 1 and len(f["contratos"]) == 2 and f["alertas"] == []
    assert cli.get("/api/territorio/estado/0000000").status_code == 404 and cli.get("/api/territorio/pcrj/7").status_code == 404
    assert len(cli.get("/api/territorio/pcrj").json()["aps"]) == 5
    assert cli.get("/api/territorio/baldes").json()["estado"]["multimunicipio"]["n"] == 1


# ── fase 12 (14/11/2026): universo, junção um-para-um, grau de certeza, pago da perícia, ficha por ano e mês ──
SEDES = ae.carregar_sedes()


def test_reparo_do_interrogacao_do_siga():
    # controle positivo: "S?O GONCALO" (ã perdido na fonte) volta a ser São Gonçalo
    at = ae.atribuir("EXECUC?O DE OBRAS DE DRENAGEM NO MUNICIPIO DE S?O GONCALO", "EMOP", REG, UNID)
    assert at["cod_ibge"] == "3304904" and at["grau"] == "explicito"
    assert ae.reparar_texto("AC?ES E M?O DE OBRA DOS ORG?OS") == "ACOES E MAO DE OBRA DOS ORGAOS"
    # controle negativo: interrogação de verdade (fim de frase, fora de palavra) não é mexida
    assert ae.reparar_texto("O que comprar? Onde?") == "O que comprar? Onde?"


def test_unidade_de_saude_grafada_sem_z_e_upa_estadual():
    longo = "CONTRATACAO DE EMPRESA ESPECIALIADA NA PRESTACAO DE SERVICOS TECNICOS ASSISTENCIAIS A SEREM EXECUTADOS NO "
    at = ae.atribuir(longo + "HOSPITAL ESTADUAL AEVEDO LIMA HEAL", "FSERJ - FUNDAÇÃO SAÚDE DO EST. DO RIO DE JANEIRO", REG, UNID)
    assert at["cod_ibge"] == "3303302" and at["grau"] == "unidade" and "sem a letra Z" in at["evidencia"]
    # negativo: texto curto, ou texto que TEM a letra Z, não entra na comparação sem Z
    assert ae.atribuir("HOSPITAL ESTADUAL AEVEDO LIMA", "FSERJ", REG, UNID)["cod_ibge"] is None
    assert ae.atribuir(longo.replace("ESPECIALIADA", "ESPECIALIZADA") + "HOSPITAL ESTADUAL AEVEDO LIMA", "FSERJ", REG, UNID)["cod_ibge"] is None
    at = ae.atribuir("serviços de limpeza na UPA 24h de Botafogo", "FUNDO ESTADUAL DE SAÚDE", REG, UNID)
    assert at["cod_ibge"] == RIO and at["grau"] == "unidade"
    # lista de UPAs: o primeiro nome não é o lugar do contrato inteiro → não atribui pela UPA
    assert ae.atribuir("serviços médicos nas UPAs Botafogo, Mesquita e Queimados", "FSERJ", REG, UNID)["metodo"] != "unidade"
    assert ae.atribuir("serviços médicos na UPA Botafogo e Mesquita", "FSERJ", REG, UNID)["metodo"] != "unidade"


def test_unidade_de_sitio_unico_citada_no_objeto_de_outro_comprador():
    at = ae.atribuir("apoio administrativo a ser prestado no Hospital Universitário Pedro Ernesto", "UERJ - ADMINISTRACAO CENTRAL", REG, UNID)
    assert at["cod_ibge"] == RIO and at["metodo"] == "unidade" and at["grau"] == "unidade"


def test_grau_sede_so_para_objeto_da_organizacao_e_sede_conferida():
    cc = "SECC - SECRETARIA DE ESTADO DA CASA CIVIL"
    at = ae.atribuir("Aquisição de deionizador", cc, REG, UNID, sedes=SEDES)                 # órgão-meio, sede no cadastro do PNCP
    assert at["cod_ibge"] == RIO and at["grau"] == "sede" and at["confianca"] == "baixa" and "PNCP" in at["evidencia"]
    # negativos: (1) aquisição para a REDE e frota são do Estado inteiro, nunca da sede
    at = ae.atribuir("AQUISIÇÃO DE MEDICAMENTOS", "FES - FUNDO ESTADUAL DE SAÚDE", REG, UNID, sedes=SEDES)
    assert at["cod_ibge"] is None and at["abrangencia"] == "estado_inteiro"
    # (2) órgão cuja sede o cadastro do PNCP registra na capital mas fica fora dela: NÃO atribui
    at = ae.atribuir("licença de software de gestão", "EMATER-RIO - EMPR DE ASSIST TÉCN E EXT RURAL DO EST DO RJ", REG, UNID, sedes=SEDES)
    assert at["cod_ibge"] is None and at["abrangencia"] == "estado_inteiro" and "não conferida" in at["evidencia"]
    # (3) órgão territorial sem pista continua SEM município (não é da sede)
    at = ae.atribuir("CONTRATAÇÃO DE EMPRESA ESPECIALIZADA EM SERVIÇOS DE VIGILÂNCIA", "SEPM - SECRETARIA DE ESTADO DE POLÍCIA MILITAR", REG, UNID, sedes=SEDES)
    assert at["cod_ibge"] is None and at["abrangencia"] is None and at["grau"] is None
    # (4) lugar escrito vence a sede
    at = ae.atribuir("licença de software para o campus de Resende/RJ", cc, REG, UNID, sedes=SEDES)
    assert at["cod_ibge"] == "3304201" and at["grau"] == "explicito"


def test_extrato_nao_decide_a_natureza_do_objeto():
    # "data da assinatura" do extrato do DOERJ fazia o contrato virar "serviço corporativo"
    at = ae.atribuir("CONTRATAÇÃO DE EMPRESA ESPECIALIZADA EM SERVIÇOS DE VIGILÂNCIA", "SEPM", REG, UNID,
                     extra="EXTRATO DE CONTRATO. DATA DA ASSINATURA: 01/02/2026. PUBLICACAO NO DOERJ.", sedes=SEDES)
    assert at["abrangencia"] is None and at["cod_ibge"] is None
    assert ae.abrangencia("assinatura anual de periódicos", "SEPM")[0] == "sede"


def _fonte_siga(regs):
    import sqlite3
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE contratos_tcerj (id TEXT, sei_norm TEXT, valor_contrato REAL, status TEXT, unidade TEXT, objeto TEXT, "
              "fornecedor TEXT, cnpj TEXT, vig_inicio TEXT, vig_fim TEXT, data_contratacao TEXT)")
    c.executemany("INSERT INTO contratos_tcerj VALUES(?,?,?,?,?,?,?,?,?,?,?)", regs)
    return c


def _pncp(cid, valor, ini, ass):
    return {"contrato_id": cid, "orgao": "FUNDO ESTADUAL DE SAÚDE", "fornecedor_cnpj": "11111111000111", "fornecedor_nome": "F",
            "objeto": "o", "valor": valor, "vig_ini": ini, "vig_fim": "2027-01-01", "data_assinatura": ass, "status": "em_execucao",
            "fontes": ["pncp"], "processos": set(), "extra": "", "tce_ids": [], "situacao_fonte": None}


def test_juncao_pncp_siga_e_um_para_um_por_cnpj_valor_e_data():
    u, cn = "FES - FUNDO ESTADUAL DE SAÚDE", "11.111.111/0001-11"
    linhas = [_pncp("P1", 1000.0, "2026-01-10", "2026-01-05")]
    src = _fonte_siga([
        ("a", "0800010000012026", 1000.0, "Ativo", u, "obj a", "F", cn, "10/01/2026", "09/01/2027", "2026-01-05T00:00:00.000"),      # o MESMO contrato
        ("b", "0800010000022026", 1000.0, "Ativo", u, "obj b", "F", cn, "10/07/2026", "09/07/2027", "2026-07-01T00:00:00.000"),      # recontratação de igual valor
        ("c", "0800010000032026", 1005.0, "Ativo", u, "obj c", "F", cn, "10/01/2026", "09/01/2027", "2026-01-05T00:00:00.000"),      # fecha a mesma chave: repetição
        ("d", "0800010000042026", 500.0, "Em Aberto", u, "PEDIDO DE EMPENHO", "F", cn, "", "", "2026-03-01T00:00:00.000"),           # sem vigência
        ("e", "0800010000052026", 500.0, "Em Aberto", u, "PEDIDO DE EMPENHO", "F", cn, "", "", "2026-04-01T00:00:00.000"),           # outro processo: outro contrato
        ("f", "0800010000062026", 900.0, "Cancelado", u, "x", "F", cn, "", "", "2026-03-01T00:00:00.000"),
        ("g", "0800010000072026", 900.0, "Em Edição", u, "x", "F", cn, "", "", "2026-03-01T00:00:00.000"),
        ("h", "0800010000082026", 900.0, "Ativo", "PREFEITURA MUNICIPAL DE NITEROI", "x", "F", cn, "", "", "2026-03-01T00:00:00.000"),
    ])
    fora = {"municipal": 0, "outro": 0}
    est = ae._integrar_tcerj(src, linhas, "2026-11-14", fora)
    assert (est["juntados"], est["novos"], est["repetidos"], est["cancelado"], est["rascunho"], fora["municipal"]) == (1, 3, 1, 1, 1, 1)
    p1 = linhas[0]
    assert p1["fontes"] == ["pncp", "tcerj"] and p1["tce_ids"] == ["a"] and p1["processos"] == {"0800010000012026"}
    por_id = {k["contrato_id"]: k for k in linhas}
    assert por_id["TCERJ-b"]["status"] == "em_execucao" and por_id["TCERJ-d"]["status"] == "sem_vigencia"
    assert por_id["TCERJ-d"]["situacao_fonte"] == "Em Aberto" and "TCERJ-e" in por_id
    assert sum(k["valor"] for k in linhas) == 3000.0                     # nada somado em dobro, nada engolido


def test_mesma_data():
    k = {"vig_ini": "2026-01-10", "data_assinatura": "2026-01-05"}
    assert ae.mesma_data(k, "2026-01-10", None) == 0 and ae.mesma_data(k, None, "2026-01-08") == 3
    assert ae.mesma_data(k, "2026-03-10", "2026-03-01") is None and ae.mesma_data(k, None, None) is None


def test_pago_do_mapa_e_o_da_pericia_so_ob_contabilizada_e_sem_devolvida(tmp_path):
    import sqlite3
    db = tmp_path / "compliance.db"
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE contratos_tcerj (id TEXT, processo TEXT, sei_norm TEXT, data_contratacao TEXT, valor_contrato REAL,
      status TEXT, unidade TEXT, objeto TEXT, fornecedor TEXT, cnpj TEXT, vig_inicio TEXT, vig_fim TEXT, num_contratacao TEXT);
    CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, ug_pagadora TEXT, data_emissao TEXT,
      status TEXT, credor TEXT, nome_credor TEXT, processo TEXT, valor REAL, exercicio INTEGER,
      nl TEXT DEFAULT '', competencia TEXT DEFAULT '', gd TEXT DEFAULT '', status_envio TEXT DEFAULT '');
    CREATE TABLE ordens_bancarias (numero_ob TEXT, ug_codigo TEXT, data_emissao TEXT, valor REAL);
    """)
    con.execute("INSERT INTO contratos_tcerj VALUES ('J','SEI-200001/000001/2026','','2026-01-10',100000.0,'Ativo','ORG','AQUISIÇÃO DE ITENS',"
                "'FORN J','10101010000110','10/01/2026','10/12/2026','1')")
    O = ("INSERT INTO ob_orcamentaria_siafe (numero_ob,ug_emitente,ug_pagadora,data_emissao,status,credor,nome_credor,processo,valor,"
         "exercicio,nl,competencia,gd,status_envio) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    con.executemany(O, [
        ("2026OB00101", "700700", "700700", "01/02/2026", "Contabilizado", "10101010000110", "J", "SEI-200001/000001/2026", 40000.0,
         2026, "2026NL00010", "02/2026", "2026GD00001", "Erro no Pagamento"),                       # devolvida pelo banco: NÃO é pago
        ("2026OB00102", "700700", "700700", "05/02/2026", "Contabilizado", "10101010000110", "J", "SEI-200001/000001/26", 40000.0,
         2026, "2026NL00010", "02/2026", "", "Processado e Pago"),                                  # paga (ano do processo com 2 dígitos)
        ("2026OB00103", "700700", "700700", "07/03/2026", "Contabilizado", "10101010000110", "J", "SEI-200001/000001/2026", 10000.0,
         2026, "2026NL00011", "03/2026", "", "Processado e Pago"),
        ("2026OB00104", "700700", "700700", "08/03/2026", "Anulado", "10101010000110", "J", "SEI-200001/000001/2026", 99999.0,
         2026, "2026NL00012", "03/2026", "", ""),                                                   # anulada: NÃO é pago
    ])
    con.commit()
    con.close()
    linhas = [{"contrato_id": "TCERJ-J", "tce_ids": ["J"]}, {"contrato_id": "PNCP-X", "tce_ids": []}]
    pg = ae._pagamentos(db, linhas, log=lambda m: None)
    assert pg["TCERJ-J"]["pago"] == 50000.0 and pg["TCERJ-J"]["n_obs"] == 3
    assert pg["TCERJ-J"]["mensal"] == {"2026-02": 40000.0, "2026-03": 10000.0}       # por mês da OB; a devolvida entra com 0,00
    assert pg["PNCP-X"]["pago"] is None and "PNCP" in pg["PNCP-X"]["motivo"]         # sem vínculo: INDISPONÍVEL com motivo, não zero


def test_api_ficha_do_municipio_por_grau_ano_e_mes(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from compliance_agent.territorio import agrega, api, base
    monkeypatch.setattr(base, "DATA", tmp_path)
    monkeypatch.setattr(base, "DB", tmp_path / "territorio.db")
    db = base.abrir(escrita=True)
    C = ("INSERT INTO territorio_contrato_estado(contrato_id,fonte,orgao,fornecedor_cnpj,fornecedor_nome,objeto,valor,vig_ini,vig_fim,status,"
         "pago,cod_ibge,multi,municipios_json,metodo,confianca,grau,data_assinatura,n_obs,pago_mensal_json,alerta,situacao_fonte) "
         "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,'[]',?,?,?,?,?,?,?,?)")
    db.executemany(C, [
        ("a", "PNCP + TCE-RJ/SIGA", "SES - X", "11111111000111", "EMPRESA A", "obra", 1000.0, "2025-03-01", "2030-01-01", "em_execucao",
         300.0, "3303302", "texto", "media", "explicito", "2025-02-20", 2, '{"2025-04": 100.0, "2025-05": 200.0}', None, "Ativo"),
        ("b", "TCE-RJ/SIGA", "SES - X", "12345678901", "PESSOA FISICA", "show", 50.0, None, None, "sem_vigencia",
         None, "3303302", "unidade", "alta", "unidade", "2026-01-15", 0, None, None, "Em Aberto"),
        ("c", "PNCP", "SECC - CASA CIVIL", "22222222000122", "EMPRESA C", "software", 700.0, "2026-01-01", "2030-01-01", "em_execucao",
         900.0, "3303302", "sede", "baixa", "sede", "2026-01-01", 1, None, "Indício (perícia contábil): pago supera o valor", None),
    ])
    base.por_meta(db, "estado_versao", "12")
    db.commit()
    db.close()
    agrega.rodar(log=lambda m: None)
    app = FastAPI()
    app.include_router(api.router)
    cli = TestClient(app)
    j = cli.get("/api/territorio/estado?periodo=tudo").json()
    nit = next(m for m in j["municipios"] if m["cod_ibge"] == "3303302")
    assert j["graus"] == ["explicito", "unidade"] and nit["n_contratos"] == 2 and nit["valor_contratado"] == 1050.0    # sede fora por padrão
    assert nit["por_grau"]["sede"] == {"n": 1, "valor": 700.0} and nit["n_alertas"] == 0
    b = j["baldes"]
    assert b["atribuido_explicito"]["valor"] == 1000.0 and b["atribuido_unidade"]["n"] == 1 and b["atribuido_sede"]["valor"] == 700.0
    assert b["sem_vigencia"]["n"] == 1 and b["com_pago"] == {"n": 2, "valor": 1700.0, "pago": 1200.0}
    j = cli.get("/api/territorio/estado?periodo=tudo&graus=explicito,unidade,sede,inventado").json()
    nit = next(m for m in j["municipios"] if m["cod_ibge"] == "3303302")
    assert j["graus"] == ["explicito", "unidade", "sede"] and nit["n_contratos"] == 3 and nit["n_alertas"] == 1
    assert cli.get("/api/territorio/estado?periodo=vigentes").json()["baldes"]["total"]["n"] == 2          # sem vigência não é "vigente"
    f = cli.get("/api/territorio/estado/3303302?periodo=tudo").json()
    assert f["kpis"]["n_contratos"] == 2 and f["kpis"]["n_sem_vigencia"] == 1 and f["kpis"]["pago"] == 300.0 and f["alertas"] == []
    assert [g["n"] for g in f["por_grau"]] == [1, 1, 1] and [g["incluido"] for g in f["por_grau"]] == [True, True, False]
    a25 = next(a for a in f["serie"]["anos"] if a["ano"] == "2025")
    assert a25["valor"] == 1000.0 and a25["pago"] == 300.0
    assert [(m["mes"], m["n"], m["valor"], m["pago"]) for m in a25["meses"]] == [("2025-02", 1, 1000.0, 0.0), ("2025-04", 0, 0.0, 100.0), ("2025-05", 0, 0.0, 200.0)]
    pf = next(c for c in f["contratos"] if c["contrato_id"] == "b")
    assert pf["fornecedor_cnpj"] is None and pf["fornecedor_doc"] == "123.***.***-01"            # CPF nunca sai inteiro (LGPD)
    assert "12345678901" not in cli.get("/api/territorio/estado/3303302?periodo=tudo").text
    assert pf["grau"] == "unidade" and pf["situacao_fonte"] == "Em Aberto" and pf["status"] == "sem_vigencia"
    f = cli.get("/api/territorio/estado/3303302?periodo=tudo&graus=sede").json()
    assert f["kpis"]["n_contratos"] == 1 and len(f["alertas"]) == 1 and f["serie"]["pago_sem_serie_mensal"] == {"n": 1, "valor": 900.0}


_DOE = ("Contrato nº 009/2023, que consiste na prestação de serviços de lo- cação de veículos. DATA DA ASSINATURA: 28/08/2026. "
        "FUNDAMENTO DO ATO: Processo nº SEI-210123/000699/2023. Id: 2760396 CORPO DE BOMBEIROS EXTRATO DE INSTRUMENTO CONTRATUAL "
        "I N S T R U M E N TO : Termo de Contrato nº 077/2026 PA R T E S : O Estado e a empresa GE HEAL- THCARE DO BRASIL LTDA "
        "O B J E TO : Aquisição de Licença de Software para o quartel de Itaperuna VIGÊNCIA: 12 meses VALOR TOTAL: R$ 49.900,00 "
        "FUNDAMENTO: Processo nº SEI-270042/000111/2026. Id: 2760397 ATO DA PRESIDENTE DESIGNA ANA MONNERAT MA- CHADO para a comissão "
        "do Contrato nº 009/2023, Processo nº SEI- 330002/026133/2026. Id: 2763020")


def test_extrato_do_doerj_so_a_clausula_objeto_do_ato_que_cita_o_processo():
    # controle positivo: o ato que cita o processo, só a cláusula OBJETO (rótulos espaçados do Diário entendidos)
    assert ae.objeto_do_extrato(_DOE, "2700420001112026") == ["Aquisição de Licença de Software para o quartel de Itaperuna"]
    # negativos: (1) processo citado em ato SEM cláusula OBJETO não ganha texto nenhum — nem o do vizinho
    assert ae.objeto_do_extrato(_DOE, "2101230006992023") == [] and ae.objeto_do_extrato(_DOE, "3300020261332026") == []
    # (2) processo que não está no trecho
    assert ae.objeto_do_extrato(_DOE, "0800010000012026") == []
    # (3) o defeito medido: "HEAL- THCARE" do ato vizinho virava a sigla HEAL (Niterói) e "MONNERAT" virava distrito (Duas Barras)
    for proc in ("2101230006992023", "3300020261332026"):
        extra = " ".join(ae.objeto_do_extrato(_DOE, proc))
        assert ae.atribuir("AQUISIÇÃO DE MEDICAMENTOS.", "FES - FUNDO ESTADUAL DE SAÚDE", REG, UNID, extra=extra)["cod_ibge"] is None
    at = ae.atribuir("Aquisição de licença", "FUNESBOM - FUNDO ESPECIAL DO CORPO DE BOMBEIROS", REG, UNID,
                     extra=" ".join(ae.objeto_do_extrato(_DOE, "2700420001112026")))
    assert at["cod_ibge"] == "3302205" and at["grau"] == "explicito"                     # Itaperuna, escrito no objeto do extrato


def test_endereco_da_contratada_nao_e_local_de_execucao():
    # o defeito medido na conferência à mão (amostra de 14/11/2026)
    obj = ("FORNECIMENTO DE ÁGUA E TRATAMENTO DE ESGOTO DAS UNIDADES DO INSTITUTO ESTADUAL DO AMBIENTE, EM FAVOR DA ÁGUAS DE JUTURNAÍBA "
           "SITUADA NA RODOVIA AMARAL PEIXOTO SN, KM 91 - BANANEIRAS - ARARUAMA - RIO DE JANEIRO.")
    assert ae.atribuir(obj, "INEA - INSTITUTO ESTADUAL DO AMBIENTE", REG, UNID)["cod_ibge"] is None
    assert ae.atribuir("serviços de vigilância pela empresa X, com sede em Macaé/RJ, CEP 20020-000", "SEPM", REG, UNID)["cod_ibge"] is None
    # controle positivo: o imóvel SITUADO (o objeto, não a parte) continua valendo
    at = ae.atribuir("LOCAÇÃO DO IMÓVEL SITUADO NA RUA SÃO GONÇALO, Nº 02, GOYTACAZES, CAMPOS DOS GOYTACAZES/RJ", "SEGOV", REG, UNID)
    assert at["cod_ibge"] == "3301009" and at["grau"] == "explicito"


def test_palavra_solta_nao_vira_natureza_corporativa():
    # "gerenciamento seguro" (adjetivo) e "nova licença" de técnico não são seguro nem licença de software
    assert ae.abrangencia("LOCAÇÃO DE TOTENS PARA PESQUISA DE SATISFAÇÃO INCLUINDO ENTREGA GARANTIA MANUTENÇÃO GERENCIAMENTO SEGURO E LOGÍSTICA REVERSA",
                          "FSERJ - FUNDAÇÃO SAÚDE DO EST. DO RIO DE JANEIRO") is None
    assert ae.abrangencia("renovação da licença sanitária de dois técnicos", "SEPM") is None
    assert ae.abrangencia("contratação de seguro predial", "SEPM")[0] == "sede"
    assert ae.abrangencia("aquisição de licenças de uso do software X", "SEPM")[0] == "sede"
