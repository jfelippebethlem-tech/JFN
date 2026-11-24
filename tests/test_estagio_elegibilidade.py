# -*- coding: utf-8 -*-
"""E9 `elegibilidade` (O4.7, SOMBRA ⚖️): vereditos puros por exigência, cobertura do registro de detectores, adaptador
sobre um compliance.db de brinquedo (lote × por chave), idempotência e efeito no PostgreSQL (esquema temporário) e a
rotina inativa do config/fluxo.yaml. Partes de PG só rodam com JFN_EVIDENCIAS_DSN (VM-2) — nunca no `dominio` real."""
import re
import sqlite3
import uuid

import pytest

from compliance_agent.aplicacao.estagios import Contexto, estagio_de
from compliance_agent.aplicacao.estagios import elegibilidade as E
from compliance_agent.dominio.regime import Regime
from compliance_agent.fluxo import grafo as G
from tests.fluxo_pg import DSN, precisa_pg


def _ob(**kw) -> E.Fatos:
    base = dict(unidade="ob_siafe", chave="010100|2025OB00001|2025", paga=True, credor_classe="PJ_PRIVADA")
    base.update(kw)
    return E.Fatos(**base)


def _ct(**kw) -> E.Fatos:
    base = dict(unidade="compra_direta_tcerj", chave="SEI-1", credor_classe="PJ_PRIVADA", regime="L14133",
                dispensa_valor=True, teto=62725.59)
    base.update(kw)
    return E.Fatos(**base)


# ── vereditos puros: controle positivo e negativo de cada motivo ──────────────────────────────────────────────
@pytest.mark.parametrize("kw, soma, fornecedor, execucao", [
    # contratação nova de empresa privada: entra na soma do art. 75 §1º (controle POSITIVO da soma)
    (dict(natureza_pagamento="CONTRATACAO_NOVA", credor_e_fornecedor=True), "E", "E", "I:SEM_CONTRATO"),
    # transferência a município / sem contraprestação (MAPA-DE-REGIMES §1)
    (dict(natureza_pagamento="TRANSFERENCIA", nao_e_contratacao_nova=True, credor_e_fornecedor=False,
          credor_classe="PJ_SEM_CADASTRO"), "I:TRANSFERENCIA", "I:TRANSFERENCIA", "I:TRANSFERENCIA"),
    # OS/OSC (contrato de gestão, el. 85): fora da soma, MAS fornecedor e execução de contrato (plano §4.3)
    (dict(natureza_pagamento="TRANSFERENCIA", nao_e_contratacao_nova=True, credor_e_fornecedor=True,
          credor_classe="OS_OSC"), "I:TRANSFERENCIA", "E", "E"),
    # serviço contínuo (el. 37, locação de mão de obra) e parcela de contrato
    (dict(natureza_pagamento="PARCELA_CONTRATO", nao_e_contratacao_nova=True, credor_e_fornecedor=True,
          elemento="37"), "I:SERVICO_CONTINUO", "E", "E"),
    (dict(natureza_pagamento="PARCELA_CONTRATO", nao_e_contratacao_nova=True, credor_e_fornecedor=True,
          elemento="39"), "I:PARCELA_CONTRATO", "E", "E"),
    # DEA (Lei 4.320 art. 37): fora da soma do exercício
    (dict(natureza_pagamento="CONTRATACAO_NOVA", credor_e_fornecedor=True, origem_exercicio="DEA"), "I:DEA", "E",
     "I:SEM_CONTRATO"),
    # ente público pela natureza jurídica 1xxx (art. 75 IX) — vence qualquer natureza
    (dict(natureza_pagamento="CONTRATACAO_NOVA", credor_e_fornecedor=True, credor_classe="ENTE_PUBLICO"),
     "I:ENTE_PUBLICO", "I:ENTE_PUBLICO", "I:ENTE_PUBLICO"),
    (dict(natureza_pagamento="FOLHA_BENEFICIO", nao_e_contratacao_nova=True, credor_e_fornecedor=False,
          credor_classe="PF"), "I:FOLHA_BENEFICIO", "I:FOLHA_BENEFICIO", "I:FOLHA_BENEFICIO"),
    (dict(natureza_pagamento="INDETERMINADO", nao_e_contratacao_nova=True, credor_e_fornecedor=False),
     "I:TRIBUTO_DIVIDA", "I:TRIBUTO_DIVIDA", "I:TRIBUTO_DIVIDA"),
    # indenização a empresa: fora da soma, mas continua fornecedor (TAC — sinal de outra régua, não "limpo")
    (dict(natureza_pagamento="INDENIZACAO", nao_e_contratacao_nova=True, credor_e_fornecedor=False),
     "I:INDENIZACAO", "E", "I:INDENIZACAO"),
    # OB não paga (invariante 1)
    (dict(paga=False, natureza_pagamento="CONTRATACAO_NOVA", credor_e_fornecedor=True), "I:NAO_PAGA", "I:NAO_PAGA",
     "I:NAO_PAGA"),
    # sem NE ligada: INDETERMINADO, nunca elegível (INDISPONÍVEL ≠ 0)
    (dict(natureza_pagamento="INDETERMINADO", natureza_despesa=None), "?:SEM_NE", "E", "?:SEM_NE"),
    (dict(natureza_pagamento="INDETERMINADO", natureza_despesa="33903900", credor_e_fornecedor=True),
     "?:SEM_VINCULO", "E", "?:SEM_VINCULO"),
    (dict(natureza_pagamento="INDETERMINADO", credor_classe="PF"), "?:SEM_NE", "?:PF_SEM_NE", "?:SEM_NE"),
])
def test_vereditos_ob(kw, soma, fornecedor, execucao):
    ex = _ob(**kw).exiges()
    assert ex == {"universo": "E", "soma_art75": soma, "fornecedor": fornecedor, "execucao": execucao}


def test_tfe_sem_par_siafe_nao_vira_elegivel():
    f = _ob(unidade="ob_tfe", tem_par_siafe=False, natureza_pagamento=None)
    assert f.exiges() == {"universo": "E", "soma_art75": "?:TFE_SEM_PAR_SIAFE", "fornecedor": "?:TFE_SEM_PAR_SIAFE",
                          "execucao": "?:TFE_SEM_PAR_SIAFE"}
    # ente público pelo cadastro decide mesmo sem o par (fonte primária do credor)
    assert _ob(unidade="ob_tfe", tem_par_siafe=False, credor_classe="ENTE_PUBLICO").exiges()["fornecedor"] == \
        "I:ENTE_PUBLICO"


@pytest.mark.parametrize("kw, disp, regime, forn", [
    ({}, "E", "E", "E"),                                                           # controle positivo
    (dict(dispensa_valor=False), "I:NAO_DISPENSA_VALOR", "E", "E"),                # inexigibilidade / emergência
    (dict(dispensa_valor=None), "?:MODALIDADE_DESCONHECIDA", "E", "E"),
    (dict(credor_classe="ENTE_PUBLICO"), "I:ENTE_PUBLICO", "E", "I:ENTE_PUBLICO"),
    (dict(regime=Regime.INDETERMINADO.value, teto=None), "?:REGIME_INDETERMINADO", "?:REGIME_INDETERMINADO", "E"),
    (dict(regime=Regime.L13979_COVID.value, teto=None), "I:COVID_SEM_TETO", "E", "E"),
    (dict(regime=Regime.OUTRO.value, teto=None), "I:REGIME_OUTRO", "?:REGIME_OUTRO", "E"),
    (dict(regime="L13303", teto=None), "?:TETO_INDETERMINADO", "E", "E"),          # 13.303 art. 29 §3º
    (dict(credor_classe="SEM_DOC"), "E", "E", "?:SEM_CNPJ"),
    (dict(credor_classe="PJ_SEM_CADASTRO"), "E", "E", "?:CREDOR_SEM_CADASTRO"),
])
def test_vereditos_contratacao(kw, disp, regime, forn):
    assert _ct(**kw).exiges() == {"universo": "E", "dispensa_valor": disp, "regime": regime, "fornecedor": forn}


def test_classe_do_credor_pela_receita_nunca_pelo_nome():
    nat = {"11111111": "1031", "22222222": "2062", "33333333": "3999"}
    assert E.classe_credor("11.111.111/0001-91", nat) == ("ENTE_PUBLICO", "11111111", "1031")
    assert E.classe_credor("22222222000100", nat) == ("PJ_PRIVADA", "22222222", "2062")
    assert E.classe_credor("33333333000100", nat) == ("OS_OSC", "33333333", "3999")
    assert E.classe_credor("44444444000100", nat) == ("PJ_SEM_CADASTRO", "44444444", None)
    assert E.classe_credor("12345678900", nat) == ("PF", None, None)              # PF: o documento NÃO é guardado
    assert E.classe_credor(None, nat) == ("SEM_DOC", None, None)
    # formato do SIAFE: código de UG como credor (repasse entre unidades) e inscrição genérica (folha, listas)
    assert E.classe_credor("296100", nat) == ("UG_PROPRIA", None, None)
    assert E.classe_credor("CG0004700", nat) == ("INSCRICAO_GENERICA", None, None)
    assert _ob(credor_classe="UG_PROPRIA", natureza_pagamento="CONTRATACAO_NOVA").exiges() == {
        "universo": "E", "fornecedor": "I:UG_PROPRIA", "execucao": "I:UG_PROPRIA", "soma_art75": "I:UG_PROPRIA"}
    assert _ob(credor_classe="INSCRICAO_GENERICA", natureza_pagamento="INDETERMINADO").exiges()["fornecedor"] == \
        "?:INSCRICAO_GENERICA"


@pytest.mark.parametrize("txt, esp", [("Lei n 14.133/2021, Art. 75, II", "II"), ("Lei 8.666/93, Art. 24, inciso I", "I"),
                                      ("Lei 13.303/2016, Art. 29, II", "II"), ("Pequenas Compras", "II"),
                                      ("Lei n 14.133/2021, Art. 74, I", None), ("Art. 75, VIII (emergência)", None)])
def test_inciso_dispensa_por_valor(txt, esp):
    assert E.inciso_dispensa_valor(txt) == esp


# ── registro de detectores ─────────────────────────────────────────────────────────────────────────────────────
def test_todo_detector_de_contratacao_tem_exigencia():
    """Invariante 3: detector registrado com domínio de contratação (fonte = tabela bruta de OB/contrato) sem
    exigência declarada aqui fica sem elegibilidade — falha até ser mapeado em DETECTORES."""
    reg = E.carregar_registro()
    faltam = sorted(set(E.detectores_de_contratacao(reg)) - set(E.DETECTORES))
    assert not faltam, f"detector(es) de contratação sem exigência na E9: {faltam}"
    sobram = sorted(set(E.DETECTORES) - set(reg))
    assert not sobram, f"DETECTORES cita detector que não está no registro: {sobram}"


def test_exigencias_validas_por_unidade():
    for det, m in E.DETECTORES.items():
        assert E.exiges_do_detector(det), det
        for u, x in E.exiges_do_detector(det).items():
            if u in E.NAO_MATERIALIZADAS:
                continue
            assert u in E.UNIDADES, (det, u)
            assert x in (E.EXIGES_OB if u in E.UNIDADES_OB else E.EXIGES_CONTRATO), (det, u, x)
        de, ate = m.get("janela") or (None, None)
        assert de is None or ate is None or de <= ate


def test_fracionamento_le_a_soma_do_art75():
    """Os detectores de fracionamento/teto usam a exigência que exclui transferência, serviço contínuo e DEA."""
    for det in ("det.P4Fracionamento", "fracionamento_siafe", "intel.fracionamento", "rules.ob_fracionamento",
                "couto.D07"):
        x = E.exiges_do_detector(det)
        assert set(x.values()) <= {"soma_art75", "dispensa_valor"}, det


# ── adaptador sobre um compliance.db de brinquedo ─────────────────────────────────────────────────────────────
_DDL = """
CREATE TABLE empresas_cadastro(cnpj_basico, razao_social, natureza_cod);
CREATE TABLE nl_siafe(numero, ug_emitente, ne);
CREATE TABLE ne_siafe(numero, ug_emitente, natureza, ano_ne);
CREATE TABLE vinculo_ob_contrato(ob, ug, estado);
CREATE TABLE ob_orcamentaria_siafe(numero_ob, ug_emitente, ug_liquidante, nl, credor, nome_credor, tipo_ob, valor,
  exercicio INTEGER, data_emissao, status, status_envio, tipo_regularizacao, PRIMARY KEY(numero_ob, ug_emitente));
CREATE TABLE ordens_bancarias(numero_ob, ug_codigo, exercicio INTEGER, favorecido_cpf, favorecido_nome, valor,
  data_emissao);
CREATE TABLE contratos_tcerj(id INTEGER, processo, num_contratacao, unidade, criterio_julgamento, ano_processo INTEGER,
  data_contratacao, valor_contrato, cnpj);
CREATE TABLE compras_diretas_tcerj(processo, unidade, enquadramento_legal, afastamento, ano_processo INTEGER, valor,
  fornecedor);
CREATE TABLE siga_contratos(id_contrato, orgao, fundamento, modalidade, data, valor, cnpj);
CREATE TABLE pcrj_contratos(numero_controle_pncp, ano INTEGER, orgao_nome, data_assinatura, valor_global,
  valor_inicial, fornecedor_documento);
CREATE TABLE contratos(id INTEGER, numero, orgao_contrat, modalidade, data_assinatura, valor_total);
INSERT INTO empresas_cadastro VALUES ('11111111','MUNICIPIO X','1244'),('22222222','ACME LTDA','2062'),
  ('33333333','OS SAUDE','3999');
INSERT INTO nl_siafe VALUES ('2025NL1','010100','2025NE1'),('2025NL2','010100','2025NE2'),('2025NL3','010100','2024NE3');
INSERT INTO ne_siafe VALUES ('2025NE1','010100','33903900',2025),('2025NE2','010100','33504100',2025),
  ('2024NE3','010100','33909200',2024);
INSERT INTO vinculo_ob_contrato VALUES ('2025OB1','010100','VERIFICADO');
INSERT INTO ob_orcamentaria_siafe VALUES
  ('2025OB1','010100','010100','2025NL1','22222222000100','ACME LTDA','Orçamentária',1000,2025,'10/03/2025','Contabilizado','',''),
  ('2025OB2','010100','010100','2025NL2','33333333000100','OS SAUDE','Orçamentária',5000,2025,'11/03/2025','Contabilizado','',''),
  ('2025OB3','010100','010100','2025NL3','22222222000100','ACME LTDA','Orçamentária',700,2025,'12/03/2025','Contabilizado','',''),
  ('2025OB4','010100','010100','','11111111000100','MUNICIPIO X','',300,2025,'13/03/2025','Contabilizado','',''),
  ('2025OB5','010100','010100','2025NL1','22222222000100','ACME LTDA','Orçamentária',900,2025,'14/03/2025','Anulado','',''),
  ('2025OB6','010100','010100','','12345678900','FULANO','',90,2025,'14/03/2025','Contabilizado','','');
INSERT INTO ordens_bancarias VALUES ('2025OB1','010100',2025,'22222222000100','ACME LTDA',1000,'2025-03-10'),
  ('2025OB9','010100',2025,'22222222000100','ACME LTDA',10,'2025-03-10');
INSERT INTO contratos_tcerj VALUES (1,'SEI-1','N1','SEC X','Menor Preço (Lei nº 8.666/93)',2023,'2023-02-01T00:00:00.000',
  50000,'22222222000100'),(2,'SEI-2','N2','SEC X','Menor Preço',2025,'2025-05-01T00:00:00.000',9000,'11111111000100');
INSERT INTO compras_diretas_tcerj VALUES ('SEI-1','SEC X','Lei n 14.133/2021, Art. 75, II','Dispensa',2025,30000,'ACME'),
  ('SEI-3','SEC X','Lei n 14.133/2021, Art. 74, I','Inexigibilidade',2025,80000,'ARTISTA');
INSERT INTO siga_contratos VALUES ('81085','SEC X','Art 24 Lei 8666/93, inciso II','Dispensa','06/01/2021',1000,'22222222000100');
INSERT INTO pcrj_contratos VALUES ('P-1',2024,'SMS','2024-02-22',100,100,'12345678900');
INSERT INTO contratos VALUES (1,'215/2024','PM',NULL,NULL,10);
"""


@pytest.fixture()
def fonte(tmp_path):
    p = tmp_path / "compliance.db"
    c = sqlite3.connect(p)
    c.executescript(_DDL)
    c.commit()
    c.close()
    return p


def test_adaptador_ob_siafe_pela_cadeia_ob_nl_ne(fonte):
    q = E.Consultas(E.abrir_fonte(fonte))
    por = {f.numero_ob: f for f in E.iterar("ob_siafe", q)}
    assert por["2025OB1"].natureza_pagamento == "PARCELA_CONTRATO" and por["2025OB1"].vinculo_contrato is True
    assert por["2025OB1"].exiges()["soma_art75"] == "I:PARCELA_CONTRATO"
    assert por["2025OB2"].exiges() == {"universo": "E", "soma_art75": "I:TRANSFERENCIA", "fornecedor": "E",
                                       "execucao": "E"}                                   # OS/OSC
    assert por["2025OB3"].origem_exercicio == "DEA" and por["2025OB3"].exiges()["soma_art75"] == "I:DEA"
    assert por["2025OB4"].exiges()["fornecedor"] == "I:ENTE_PUBLICO"
    assert por["2025OB5"].paga is False and por["2025OB5"].exiges()["fornecedor"] == "I:NAO_PAGA"
    assert por["2025OB6"].credor_classe == "PF" and por["2025OB6"].credor_raiz is None
    assert por["2025OB4"].motivo_legado                                   # a régua de hoje também o tira (comparação)


def test_adaptador_tfe_contratos_e_paridade_lote_por_chave(fonte):
    con = E.abrir_fonte(fonte)
    lote, chave = E.Consultas(con), E.Consultas(con, em_lote=False)
    for u in E.UNIDADES:
        itens = list(E.iterar(u, lote))
        assert itens, u
        for f in itens:                                   # o MESMO cálculo pela consulta por chave (efeito)
            g = E.recalcular(u, f.chave, chave)
            assert g is not None and E.linha(g)[0] == E.linha(f)[0], (u, f.chave)
    tfe = {f.numero_ob: f for f in E.iterar("ob_tfe", lote)}
    assert tfe["2025OB1"].tem_par_siafe and tfe["2025OB1"].natureza_pagamento == "PARCELA_CONTRATO"
    assert tfe["2025OB9"].exiges()["fornecedor"] == "?:TFE_SEM_PAR_SIAFE"
    cd = {f.chave: f for f in E.iterar("compra_direta_tcerj", lote)}
    assert cd["SEI-1"].credor_classe == "PJ_PRIVADA"                       # CNPJ do contrato do mesmo processo
    assert cd["SEI-1"].exiges()["dispensa_valor"] == "E" and cd["SEI-1"].teto
    assert cd["SEI-3"].exiges()["dispensa_valor"] == "I:NAO_DISPENSA_VALOR"
    ct = {f.chave: f for f in E.iterar("contrato_tcerj", lote)}
    assert ct["SEI-1|N1"].regime == "L8666"                               # lei declarada no critério
    assert ct["SEI-2|N2"].exiges()["fornecedor"] == "I:ENTE_PUBLICO"


def test_sem_cpf_na_linha_gravada(fonte):
    q = E.Consultas(E.abrir_fonte(fonte))
    for u in ("ob_siafe", "contrato_pcrj"):
        for f in E.iterar(u, q):
            row, _ = E.linha(f)
            assert not any(isinstance(v, str) and re.search(r"\b12345678900\b", v) for v in row), (u, row)


def test_fonte_ausente_e_permanente(tmp_path):
    from compliance_agent.aplicacao.estagios import ErroPermanente
    with pytest.raises(ErroPermanente):
        E.abrir_fonte(tmp_path / "nao_existe.db")
    with pytest.raises(ErroPermanente):
        E._escopo({"unidade": "inventada"})


def test_estagio_registrado():
    assert estagio_de("elegibilidade") is E.ESTAGIO
    assert estagio_de("elegibilidade:ob_siafe") is E.ESTAGIO


def test_rotina_e9_inativa_com_efeito_verificavel():
    g = G.carregar()
    r = g.rotinas["elegibilidade_sombra"]
    assert r.estagio == "E9" and r.ativa is False and "O4.10" in (r.bloqueio or "")
    unidades = {a[a.index("--unidade") + 1] for a in r.argvs()}
    assert unidades == set(E.UNIDADES)
    assert all("compliance_agent.aplicacao.estagios.elegibilidade" in a for a in r.argvs())
    linha_cli = "elegibilidade: 4687 linha(s) conferida(s) em dominio.elegibilidade (contrato_siga, exercício todos)"
    assert re.search(r.efeito.log_contem, linha_cli)
    assert not re.search(r.efeito.log_contem, "elegibilidade: 0 linha(s) conferida(s) em dominio.elegibilidade")


# ── PostgreSQL: esquema temporário (nunca o `dominio` real) ───────────────────────────────────────────────────
@pytest.fixture()
def pg():
    nome = f"tmp_e9_{uuid.uuid4().hex[:10]}"
    con = E.conectar(DSN, "public")
    try:
        E.aplicar_schema(con, nome)
        yield con, nome
    finally:
        con.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')
        con.close()


@precisa_pg
def test_schema_idempotente(pg):
    con, nome = pg
    E.aplicar_schema(con, nome)                                         # 2ª vez: nada muda, nada quebra
    assert E.verificar_schema(con) == []
    assert con.execute("SELECT versao FROM migracoes").fetchall() == [("dominio_001",)]


@precisa_pg
def test_gravar_idempotente_e_visao_por_detector(pg, fonte):
    con, _ = pg
    q = E.Consultas(E.abrir_fonte(fonte))
    assert E.sincronizar_detectores(con) > 50
    r1 = E.gravar(con, E.iterar("ob_siafe", q))
    assert r1["inseridas"] == 6 and r1["alteradas"] == 0
    r2 = E.gravar(con, E.iterar("ob_siafe", q))
    assert (r2["inseridas"], r2["alteradas"], r2["iguais"]) == (0, 0, 6)  # mesma entrada: 0 linha alterada
    linhas = dict(con.execute("SELECT chave, elegivel::text || ':' || coalesce(motivo, '') FROM "
                              "v_elegibilidade_detector WHERE detector = 'fracionamento_siafe' "
                              "AND unidade = 'ob_siafe'").fetchall())
    assert linhas["010100|2025OB3|2025"] == "false:DEA"
    assert linhas["010100|2025OB2|2025"] == "false:TRANSFERENCIA"
    assert con.execute("SELECT count(*) FROM elegibilidade_fonte").fetchone()[0] > 0


@precisa_pg
def test_handler_e_efeito_conferido(pg, fonte):
    con, nome = pg
    payload = {"unidade": "compra_direta_tcerj", "fonte": str(fonte), "dsn": DSN, "esquema": nome}
    ctx = Contexto(no="teste", tipo="elegibilidade", chave="elegibilidade:compra_direta_tcerj:todos", ficha=1,
                   tentativa=1)
    res = E.ESTAGIO.handler(payload, ctx)
    assert res.efeito["linhas"] == 2 and res.eventos
    assert E.ESTAGIO.efeito(payload, ctx, res) is True
    again = E.ESTAGIO.handler(payload, ctx)                             # reexecução: sem mudança, sem evento
    assert again.efeito["iguais"] == 2 and not again.eventos
    # efeito INDEPENDENTE: adulterar o veredito no PG faz a conferência por amostra recusar
    con.execute("UPDATE elegibilidade SET exiges = '{\"universo\": \"E\"}'::jsonb WHERE chave = 'SEI-1'")
    assert E.ESTAGIO.efeito({**payload, "amostra": 50}, ctx, again) is False
    # declarar mais linhas do que há também é recusado
    again.efeito["linhas"] = 99
    assert E.ESTAGIO.efeito(payload, ctx, again) is False
