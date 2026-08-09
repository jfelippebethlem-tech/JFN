# -*- coding: utf-8 -*-
"""Task 10 — detectores de gastos PCRJ (DB semeado, sem rede)."""
import pytest

from compliance_agent.emendas import db as edb
from compliance_agent.pcrj import gastos_db, pericia_gastos


@pytest.fixture
def con_semeado(tmp_path):
    con = edb.conectar(tmp_path / "t.db")
    edb.init_schema(con)
    gastos_db.init_schema(con)
    con.execute("""create table socios_receita (cnpj_basico text, ident text, nome_socio text,
                   nome_norm text, doc_socio text, qualificacao_cod text, qualificacao_txt text,
                   data_entrada text, faixa_etaria text, fonte_mes text)""")
    con.execute("""create table alertas (id integer primary key, tipo text, severidade text,
                   titulo text, descricao text, evidencias text, status text,
                   pessoa_id integer, empresa_id integer, contrato_id integer,
                   processo_sei_id integer, ordem_bancaria_id integer,
                   data_referencia text, created_at text)""")
    con.commit()
    return con


def test_d7_fracionamento(con_semeado):
    con = con_semeado
    for i in range(3):   # 3 empenhos abaixo do teto p/ mesmo credor+órgão em 90 dias
        con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                       orgao_nome, fornecedor_documento, fornecedor_nome, tipo,
                       valor_global, data_assinatura)
                       values (?,2025,'42498733000148','PCRJ','11222333000181','ACME',
                               'Empenho',50000,?)""",
                    (f"C{i}", f"2025-03-{10 + i:02d}"))
    achados = pericia_gastos.d7_fracionamento(con)
    assert len(achados) == 1 and achados[0]["risco"] >= 6
    assert "indício" in achados[0]["descricao"].lower()
    assert achados[0]["evidencias"]["n_contratos"] == 3


def test_d7_ignora_acima_do_teto(con_semeado):
    con = con_semeado
    for i in range(3):
        con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                       fornecedor_documento, tipo, valor_global, data_assinatura)
                       values (?,2025,'42498733000148','11222333000181','Empenho',900000,?)""",
                    (f"G{i}", f"2025-03-{10 + i:02d}"))
    assert pericia_gastos.d7_fracionamento(con) == []


def test_d8_credor_recem_aberto(con_semeado):
    con = con_semeado
    con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                   fornecedor_documento, fornecedor_nome, tipo, valor_global, data_assinatura)
                   values ('N1',2025,'42498733000148','11222333000181','NOVATA LTDA',
                           'Contrato',800000,'2025-03-01')""")
    def consulta_fake(cnpj):
        return {"data_inicio_atividade": "2025-01-15", "razao_social": "NOVATA LTDA"}
    achados = pericia_gastos.d8_credor_recem_aberto(con, consulta_cnpj=consulta_fake)
    assert len(achados) == 1 and achados[0]["risco"] >= 7
    assert "dias" in achados[0]["descricao"]


def test_d9_socio_na_folha(con_semeado):
    con = con_semeado
    con.execute("""insert into pcrj_despesa (exercicio, orgao, credor_documento, credor_nome,
                   natureza, fonte_recurso, empenhado, liquidado, pago, arquivo_origem)
                   values (2023,'SMS','11222333000181','ACME','339039','100',
                           500000,500000,500000,'x.csv')""")
    con.execute("""insert into socios_receita (cnpj_basico, nome_socio, nome_norm, doc_socio)
                   values ('11222333','CARLOS PEREIRA DIAS','CARLOS PEREIRA DIAS','***111222**')""")
    folha = {"CARLOS PEREIRA DIAS": {"orgao": "SMS", "cargo": "ASSESSOR"}}
    achados = pericia_gastos.d9_socio_na_folha(con, folha_norm=folha)
    assert len(achados) == 1
    a = achados[0]
    assert a["risco"] <= 6 and "homônim" in a["descricao"].lower()   # nome = indício


def test_d10_rede_concorrentes_e_aditivos(con_semeado):
    con = con_semeado
    # mesmo sócio (raiz) em 2 fornecedores contratados pelo mesmo órgão no ano
    con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj, orgao_nome,
                   fornecedor_documento, fornecedor_nome, tipo, valor_global, data_assinatura)
                   values ('R1',2025,'42498733000148','PCRJ','11222333000181','ALFA',
                           'Contrato',100000,'2025-02-01')""")
    con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj, orgao_nome,
                   fornecedor_documento, fornecedor_nome, tipo, valor_global, data_assinatura)
                   values ('R2',2025,'42498733000148','PCRJ','44555666000199','BETA',
                           'Contrato',120000,'2025-02-15')""")
    con.execute("""insert into socios_receita (cnpj_basico, nome_socio, nome_norm, doc_socio)
                   values ('11222333','MESMO DONO','MESMO DONO','***999888**'),
                          ('44555666','MESMO DONO','MESMO DONO','***999888**')""")
    # aditivo estourado: global 2x o inicial
    con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                   fornecedor_documento, fornecedor_nome, tipo, valor_inicial, valor_global,
                   data_assinatura)
                   values ('A1',2024,'42498733000148','77888999000155','GAMA','Contrato',
                           100000,210000,'2024-05-01')""")
    # split 2026-07-18: d10 = SÓ rede societária; aditivo estourado virou detector próprio (d11)
    achados = pericia_gastos.d10_rede_concorrentes(con)
    tipos = {a["evidencias"].get("subtipo") for a in achados}
    assert tipos == {"rede_socios"}
    aditivos = pericia_gastos.d11_aditivo_estourado(con)
    assert {a["evidencias"].get("subtipo") for a in aditivos} == {"aditivo_estourado"}
    assert all(a["detector"] == "d11_aditivo_estourado" for a in aditivos)


def test_rodar_todas_cobertura(con_semeado):
    r = pericia_gastos.rodar_todas(con_semeado)
    assert set(r["cobertura"]) == {"d7", "d8", "d9", "d10", "d11", "d12"}


def test_teto_dispensa_datado_por_ano():
    """O teto vem da FONTE ÚNICA, nunca de um número digitado aqui.

    Este teste afirmava `teto_dispensa(2026) == 62_725.68` — e **62.725,68 não é o teto de
    2026 nem de ano nenhum**: o de 2026 é R$ 65.492,11 (Decreto 12.807/2025) e o de 2025 é
    R$ 62.725,59. O teste estava travando o valor errado, o que é pior que não haver teste:
    impedia a correção. Agora ele compara com `limites_dispensa`, onde os valores foram
    conferidos verbatim nos decretos — assim não há como os dois divergirem de novo.
    """
    from compliance_agent.limites_dispensa import LIMITES, limite_dispensa

    for ano in LIMITES:
        assert pericia_gastos.teto_dispensa(ano) == limite_dispensa(ano, "compras")
    assert pericia_gastos.teto_dispensa(2026) == 65_492.11      # Decreto 12.807/2025
    assert pericia_gastos.teto_dispensa(2025) == 62_725.59      # Decreto 12.343/2024
    assert pericia_gastos.teto_dispensa(2024) == 59_906.02      # Decreto 11.871/2023
    # ano futuro sem decreto publicado usa o último conhecido — fallback honesto
    assert pericia_gastos.teto_dispensa(2027) == pericia_gastos.teto_dispensa(max(LIMITES))
    assert pericia_gastos.teto_dispensa() > 0


def test_d7_usa_o_teto_do_ANO_da_contratacao(con_semeado):
    """O teto sobe todo ano; um valor único faz falso positivo num ano e falso negativo noutro.

    Cenário: mesmo valor de contrato (R$ 61.000) em 2024 e em 2026.
      · 2024 — teto R$ 59.906,02 → está ACIMA do teto, não é dispensa, NÃO pode entrar;
      · 2026 — teto R$ 65.492,11 → está abaixo do teto, PODE entrar.
    Com teto único (o que havia), os dois anos recebiam o mesmo tratamento e um deles saía
    errado — foi o defeito medido: 46 contratos de 2024 entravam indevidamente e 35 de 2026
    sumiam.
    """
    con = con_semeado
    con.execute("delete from pcrj_contratos")
    for i, (ano, dia) in enumerate([(2024, "05"), (2024, "15"), (2024, "25"),
                                    (2026, "05"), (2026, "15"), (2026, "25")]):
        con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                       fornecedor_documento, fornecedor_nome, orgao_nome, tipo, valor_global,
                       data_assinatura)
                       values (?,?,?,?,?,?,?,?,?)""",
                    (f"nc{i}", ano, "111", "222", "FORN X", "ORGAO Y", "contrato",
                     61_000.0, f"{ano}-03-{dia}"))
    con.commit()
    anos = {a["evidencias"]["controles_pncp"][0] for a in pericia_gastos.d7_fracionamento(con)}
    achados = pericia_gastos.d7_fracionamento(con)
    assert len(achados) == 1, (
        "só 2026 pode acender: em 2024 R$ 61.000 está ACIMA do teto de R$ 59.906,02 "
        f"e não é contratação por dispensa. Achados: {[a['titulo'] for a in achados]}")
    assert "2026" in achados[0]["descricao"], "a evidência tem de citar o teto do ano certo"
    assert "65.492,11" in achados[0]["descricao"]
    assert anos


def test_d8_usa_cadastro_local_antes_da_api(con_semeado):
    con = con_semeado
    con.execute("""create table empresas (cnpj text, razao_social text, situacao text,
                   data_abertura text, cep text)""")
    con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                   fornecedor_documento, fornecedor_nome, tipo, valor_global, data_assinatura)
                   values ('L1',2025,'42498733000148','11222333000181','LOCAL LTDA',
                           'Contrato',900000,'2025-03-01')""")
    con.execute("insert into empresas (cnpj, data_abertura) values ('11222333000181','2025-01-15')")
    def api_fora_do_ar(cnpj):
        return None   # minhareceita indisponível — antes disso o D8 zerava silenciosamente
    achados = pericia_gastos.d8_credor_recem_aberto(con, consulta_cnpj=api_fora_do_ar)
    assert len(achados) == 1 and "LOCAL" in achados[0]["titulo"]


def test_d12_coendereco_entre_concorrentes(con_semeado):
    con = con_semeado
    con.execute("""create table empresas (cnpj text, razao_social text, situacao text,
                   data_abertura text, cep text)""")
    # dois fornecedores do MESMO órgão/ano com o MESMO CEP → indício OCDE
    for doc, nome in (("11222333000181", "ALFA"), ("44555666000199", "BETA")):
        con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                       orgao_nome, fornecedor_documento, fornecedor_nome, tipo, valor_global,
                       data_assinatura) values (?,2025,'42498733000148','PCRJ',?,?,
                       'Contrato',100000,'2025-02-01')""", (f"CE-{doc}", doc, nome))
        con.execute("insert into empresas (cnpj, cep) values (?, '20031-170')", (doc,))
    achados = pericia_gastos.d12_coendereco_concorrentes(con)
    assert len(achados) == 1
    assert achados[0]["evidencias"]["cep"] == "20031-170"
    assert "OCDE" in achados[0]["descricao"] or "endereço" in achados[0]["descricao"]


def test_d12_guard_cep_popular(con_semeado):
    con = con_semeado
    con.execute("""create table empresas (cnpj text, razao_social text, situacao text,
                   data_abertura text, cep text)""")
    # CEP compartilhado por MUITAS empresas da base (edifício comercial) → guard descarta
    for i in range(2):
        doc = f"1122233300018{i}"
        con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                       fornecedor_documento, tipo, valor_global, data_assinatura)
                       values (?,2025,'42498733000148',?,'Contrato',100000,'2025-02-01')""",
                    (f"CP{i}", doc))
        con.execute("insert into empresas (cnpj, cep) values (?, '20000-000')", (doc,))
    for i in range(6):  # +6 empresas quaisquer no mesmo CEP = popular
        con.execute("insert into empresas (cnpj, cep) values (?, '20000-000')", (f"9988877700010{i}",))
    assert pericia_gastos.d12_coendereco_concorrentes(con) == []


def test_d10_nao_acusa_rede_que_ainda_nao_existia(con_semeado):
    """O QSA é retrato de HOJE; o contrato é de ontem. Sem corte de vigência o detector acusava
    rede societária inexistente à época — medido em 2026-08-09, **54 dos 649 alertas (8,3%)**,
    inclusive ROMA×MEDKA em 2024, cujo administrador comum só entrou em março de 2026.
    Mesma família de `situacao-cadastral-vigencia-na-data`.

    Vínculo SEM data não é descartado: ausência de dado não vira prova de nada.
    """
    con = con_semeado
    for pncp, forn, nome in (("T1", "11222333000181", "ALFA"), ("T2", "44555666000199", "BETA")):
        con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                       orgao_nome, fornecedor_documento, fornecedor_nome, tipo, valor_global,
                       data_assinatura) values (?,2024,'42498733000148','PCRJ',?,?,'Contrato',
                       100000,'2024-02-01')""", (pncp, forn, nome))
    con.execute("""insert into socios_receita (cnpj_basico, nome_socio, nome_norm, doc_socio,
                   data_entrada) values ('11222333','TARDIO','TARDIO','***777666**','20130101'),
                                        ('44555666','TARDIO','TARDIO','***777666**','20260326')""")
    con.execute("""insert into socios_receita (cnpj_basico, nome_socio, nome_norm, doc_socio,
                   data_entrada) values ('11222333','SEM DATA','SEM DATA','***555444**',''),
                                        ('44555666','SEM DATA','SEM DATA','***555444**','')""")
    nomes = {a["titulo"] for a in pericia_gastos.d10_rede_concorrentes(con)}
    assert not any("TARDIO" in t for t in nomes), (
        "sócio que entrou em 2026 não descreve rede de 2024")
    assert any("SEM DATA" in t for t in nomes), (
        "vínculo sem data não pode ser descartado — ausência de dado não é prova")


def test_poda_retira_alerta_que_o_detector_nao_produz_mais(con_semeado):
    """Consertar o detector não limpa o painel: os 54 alertas anacrônicos do d10 continuaram
    afirmando o que o detector já não afirmava. A poda tira o superado."""
    con = con_semeado
    con.execute("""insert into alertas (tipo, severidade, titulo, descricao, evidencias, status)
                   values ('pcrj_d10_rede_concorrentes','media','Rede societária — FANTASMA',
                           'alerta de uma versão anterior do detector','{}','novo')""")
    for pncp, forn, nome in (("P1", "11222333000181", "ALFA"), ("P2", "44555666000199", "BETA")):
        con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                       orgao_nome, fornecedor_documento, fornecedor_nome, tipo, valor_global,
                       data_assinatura) values (?,2025,'42498733000148','PCRJ',?,?,'Contrato',
                       100000,'2025-02-01')""", (pncp, forn, nome))
    con.execute("""insert into socios_receita (cnpj_basico, nome_socio, nome_norm, doc_socio,
                   data_entrada) values ('11222333','VIVO','VIVO','***111222**','20200101'),
                                        ('44555666','VIVO','VIVO','***111222**','20200101')""")
    pericia_gastos.rodar_todas(con, gravar_alertas=True)
    restantes = [r[0] for r in con.execute(
        "select titulo from alertas where tipo='pcrj_d10_rede_concorrentes'")]
    assert not any("FANTASMA" in t for t in restantes), "alerta superado ficou no painel"
    assert any("VIVO" in t for t in restantes), "o alerta que o detector ainda produz sumiu"


def test_poda_nao_apaga_detector_que_zerou(con_semeado):
    """INDISPONÍVEL ≠ 0: detector que zerou pode ter zerado porque a FONTE sumiu. Apagar aí
    transformaria falha de coleta em 'nada a apurar' — o pior estrago num painel de fiscalização."""
    con = con_semeado
    con.execute("""insert into alertas (tipo, severidade, titulo, descricao, evidencias, status)
                   values ('pcrj_d10_rede_concorrentes','media','Rede societária — ANTIGO',
                           'de quando a fonte existia','{}','novo')""")
    r = pericia_gastos.rodar_todas(con, gravar_alertas=True)   # sem contratos: d10 devolve 0
    assert con.execute("select count(*) from alertas where titulo like '%ANTIGO%'").fetchone()[0] == 1
    assert "POUPADOS" in r["poda"], "o poupamento tem de sair declarado, não calado"


def test_poda_nunca_apaga_alerta_com_triagem_humana(con_semeado):
    """`status` guarda a decisão de quem fiscaliza — o detector não pode desfazê-la.

    Medido em 2026-08-09: os 21 alertas triados do acervo (15 descartados, 6 confirmados) são
    TODOS `pcrj_d7_fracionamento`, a mesma família que a poda varre. Sobreviveram por sorte — o
    título do d7 não mudou naquela rodada — e a recalibração do d7 os teria destruído em silêncio.

    O teste roda sobre o d10 porque a poda só age em detector que PRODUZIU achado; com o d7 zerado
    nesta base semeada o tipo seria poupado inteiro e o teste não provaria nada.
    """
    con = con_semeado
    for pncp, forn, nome in (("Q1", "11222333000181", "ALFA"), ("Q2", "44555666000199", "BETA")):
        con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                       orgao_nome, fornecedor_documento, fornecedor_nome, tipo, valor_global,
                       data_assinatura) values (?,2025,'42498733000148','PCRJ',?,?,'Contrato',
                       100000,'2025-02-01')""", (pncp, forn, nome))
    con.execute("""insert into socios_receita (cnpj_basico, nome_socio, nome_norm, doc_socio,
                   data_entrada) values ('11222333','VIVO','VIVO','***111222**','20200101'),
                                        ('44555666','VIVO','VIVO','***111222**','20200101')""")
    for titulo, status in (("Rede societária — CONFIRMADO PELO FISCAL", "confirmado"),
                           ("Rede societária — DESCARTADO PELO FISCAL", "descartado"),
                           ("Rede societária — SO VISTO", "novo")):
        con.execute("""insert into alertas (tipo, severidade, titulo, descricao, evidencias, status)
                       values ('pcrj_d10_rede_concorrentes','media',?,'versão anterior','{}',?)""",
                    (titulo, status))
    r = pericia_gastos.rodar_todas(con, gravar_alertas=True)
    vivos = {t for (t,) in con.execute(
        "select titulo from alertas where tipo='pcrj_d10_rede_concorrentes'")}
    assert "Rede societária — CONFIRMADO PELO FISCAL" in vivos, "poda destruiu decisão do fiscal"
    assert "Rede societária — DESCARTADO PELO FISCAL" in vivos, "poda destruiu decisão do fiscal"
    assert "Rede societária — SO VISTO" not in vivos, "alerta sem triagem e superado deve sair"
    assert "PRESERVADOS" in r["poda"], "a preservação tem de sair declarada"


def test_d7_severidade_considera_o_EXCESSO_nao_so_a_contagem(con_semeado):
    """Cinco fatias a 1,05× do teto não é a mesma coisa que cinco a 3× — e pesavam igual.

    Medido em 2026-08-09 nos 698 alertas com teto legível: mediana 1,70×, p75 2,41×, máximo
    16,56×. A contagem sozinha não separava; o excesso separa. Nada é escondido — o caso rente ao
    teto continua saindo, só não ocupa a faixa ALTA da fila.
    """
    con = con_semeado
    teto = pericia_gastos.teto_dispensa(2025)

    def semear(doc, valor, n):
        for i in range(n):
            con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                           orgao_nome, fornecedor_documento, fornecedor_nome, tipo, valor_global,
                           data_assinatura) values (?,2025,'42498733000148','PCRJ',?,?,'Contrato',
                           ?,?)""", (f"{doc}-{i}", doc, f"F{doc}", valor, f"2025-03-{i+1:02d}"))

    semear("11111111000191", teto * 0.21, 5)      # 5 fatias → soma ≈ 1,05× o teto
    semear("22222222000122", teto * 0.60, 5)      # 5 fatias → soma ≈ 3,00× o teto
    por = {a["evidencias"]["fornecedor"]: a for a in pericia_gastos.d7_fracionamento(con)}
    rente, folgado = por["11111111000191"], por["22222222000122"]
    assert rente["risco"] < folgado["risco"], "o excesso tem de separar dois achados de igual contagem"
    assert rente["risco"] <= 7, "rente ao teto não pode ocupar a faixa ALTA"
    assert folgado["risco"] >= 8
