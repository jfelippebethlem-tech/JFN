"""Lentes de contrato, licitação e terceiro setor (PCRJ)."""
import sqlite3

import pytest

from tools import lentes_pcrj_contrato as C

DDL_CONTRATOS = """
CREATE TABLE pcrj_contratos (numero_controle_pncp TEXT, ano INT, orgao_cnpj TEXT, orgao_nome TEXT,
  unidade TEXT, fornecedor_documento TEXT, fornecedor_nome TEXT, tipo TEXT, objeto TEXT,
  valor_inicial REAL, valor_global REAL, data_assinatura TEXT, vigencia_ini TEXT,
  vigencia_fim TEXT, num_aditivos INT, fonte TEXT)"""
DDL_LICITACOES = """
CREATE TABLE pcrj_licitacoes (numero_controle_pncp TEXT, ano INT, modalidade TEXT, objeto TEXT,
  valor_estimado REAL, situacao TEXT, data_abertura TEXT, orgao_cnpj TEXT, orgao_nome TEXT,
  amparo TEXT, fonte TEXT, coletado_em TEXT)"""
DDL_DESPESA = """
CREATE TABLE pcrj_despesa (id INTEGER, exercicio INT, orgao TEXT, unidade TEXT,
  credor_documento TEXT, credor_nome TEXT, natureza TEXT, fonte_recurso TEXT,
  empenhado REAL, liquidado REAL, pago REAL, arquivo_origem TEXT, coletado_em TEXT)"""
DDL_RESULTADO = """
CREATE TABLE pncp_resultado (certame TEXT, orgao_cnpj TEXT, orgao_nome TEXT, uf TEXT,
  municipio TEXT, modalidade TEXT, objeto TEXT, data_pub TEXT, item TEXT, fornecedor_cnpj TEXT,
  fornecedor_nome TEXT, valor_homologado REAL, ordem_classificacao INT, porte_fornecedor INT,
  coletado_em TEXT, unidade_codigo TEXT, unidade_nome TEXT, item_descricao TEXT,
  unidade_medida TEXT, valor_unitario REAL, quantidade REAL)"""
DDL_EDITAL = """
CREATE TABLE edital_documento (numero_controle_pncp TEXT, ano INT, orgao_cnpj TEXT, objeto TEXT,
  material_servico TEXT, valor_estimado REAL, texto TEXT, itens_json TEXT,
  documento_disponivel INT, coletado_em TEXT)"""
RAIZ = "42498733000148"


@pytest.fixture()
def banco(tmp_path):
    def _criar(contratos=(), licitacoes=(), despesa=(), resultado=(), editais=()):
        p = tmp_path / "c.db"
        con = sqlite3.connect(p)
        for ddl in (DDL_CONTRATOS, DDL_LICITACOES, DDL_DESPESA, DDL_RESULTADO, DDL_EDITAL):
            con.execute(ddl)
        con.executemany("INSERT INTO pcrj_contratos (numero_controle_pncp,ano,orgao_cnpj,"
                        "fornecedor_documento,fornecedor_nome,tipo,objeto,valor_inicial,"
                        "valor_global,data_assinatura,vigencia_ini,vigencia_fim,num_aditivos) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", contratos)
        con.executemany("INSERT INTO pcrj_licitacoes (numero_controle_pncp,ano,modalidade,objeto,"
                        "valor_estimado,situacao,orgao_cnpj) VALUES (?,?,?,?,?,?,?)", licitacoes)
        con.executemany("INSERT INTO pcrj_despesa (exercicio,orgao,credor_documento,credor_nome,"
                        "natureza,empenhado,liquidado,pago) VALUES (?,?,?,?,?,?,?,?)", despesa)
        con.executemany("INSERT INTO pncp_resultado (certame,fornecedor_cnpj,fornecedor_nome,"
                        "valor_homologado) VALUES (?,?,?,?)", resultado)
        con.executemany("INSERT INTO edital_documento (numero_controle_pncp,orgao_cnpj) "
                        "VALUES (?,?)", editais)
        con.commit()
        con.close()
        return str(p)
    return _criar


def _c(num, forn, aditivos=0, assin="2024-06-15", vi="2024-07-01", vf="2025-06-30",
       valor=1_000_000.0, objeto="OBJETO"):
    return (num, 2024, RAIZ, "1" * 14, forn, "Contrato (termo inicial)", objeto,
            valor, valor, assin, vi, vf, aditivos)


# ── aditivos ─────────────────────────────────────────────────────────────────────────────────

def test_aditivos_em_serie(banco):
    db = banco(contratos=[_c("A", "ALFA", aditivos=4), _c("B", "BETA", aditivos=1),
                          _c("C", "GAMA", aditivos=0)])
    r = C.aditivos_em_serie(db)
    assert [a["fornecedor"] for a in r["achados"]] == ["ALFA"]
    assert r["com_ao_menos_um_aditivo"] == 2


def test_docstring_declara_que_o_teto_de_25_e_intestavel():
    """`valor_global` espelha `valor_inicial` em 100% — zero acima do teto é falta de DADO."""
    d = C.aditivos_em_serie.__doc__
    assert "25" in d and ("bloquead" in d.lower() or "impossível" in d.lower())


# ── vigência medida em DIAS ─────────────────────────────────────────────────────────────────

def test_cinco_anos_menos_um_dia_nao_estoura_o_limite(banco):
    """Regressão: por ano-calendário, 2026-09-23 a 2031-09-22 dava '5' e marcava 65 contratos."""
    db = banco(contratos=[_c("A", "ALFA", vi="2026-09-23", vf="2031-09-22")])
    assert C.vigencia_acima_do_prazo(db)["n"] == 0


def test_vigencia_realmente_acima_de_cinco_anos_e_marcada(banco):
    db = banco(contratos=[_c("A", "ALFA", vi="2020-01-01", vf="2027-01-01")])
    r = C.vigencia_acima_do_prazo(db)
    assert r["n"] == 1 and r["achados"][0]["duracao_anos"] > 5


# ── sazonalidade: o pico é medido, não presumido ────────────────────────────────────────────

def test_pico_e_medido_e_pode_nao_ser_dezembro(banco):
    """Medido no acervo real: março tem 336 assinaturas e dezembro 290."""
    contratos = ([_c(f"M{i}", "X", assin="2024-03-10") for i in range(5)]
                 + [_c(f"D{i}", "X", assin="2024-12-20") for i in range(3)])
    r = C.sazonalidade_das_assinaturas(banco(contratos=contratos))
    assert r["mes_de_pico"] == 3
    assert r["dezembro"]["contratos"] == 3
    assert len(r["achados"]) == 2, "a série mensal inteira vai no retorno"


def test_dezembro_continua_reportado_mesmo_sem_ser_o_pico(banco):
    contratos = [_c(f"M{i}", "X", assin="2024-03-10") for i in range(5)]
    r = C.sazonalidade_das_assinaturas(banco(contratos=contratos))
    assert r["dezembro"]["contratos"] == 0


# ── controle: contrato retroativo ────────────────────────────────────────────────────────────

def test_contrato_retroativo_e_detectado(banco):
    db = banco(contratos=[_c("A", "ALFA", assin="2024-08-01", vi="2024-07-01")])
    assert C.contrato_assinado_apos_o_inicio_da_vigencia(db)["n"] == 1


def test_contrato_normal_nao_e_marcado(banco):
    db = banco(contratos=[_c("A", "ALFA", assin="2024-06-15", vi="2024-07-01")])
    assert C.contrato_assinado_apos_o_inicio_da_vigencia(db)["n"] == 0


# ── estimativa ancorada no orçamento ────────────────────────────────────────────────────────

def test_estimativa_absurda_e_ancorada_no_orcamento_nao_em_percentil(banco):
    """'100× a mediana' marcava 10,43% porque a mediana municipal é R$ 62.400,00."""
    lic = [("PEQ", 2025, "Dispensa", "objeto", 60_000.0, "Divulgada", RAIZ),
           ("ABSURDO", 2025, "Dispensa", "objeto", 347_037_696_000.0, "Divulgada", RAIZ)]
    desp = [(2022, "SME", "1" * 14, "X", "33903901", 1e9, 1e9, 1e9)]
    r = C.estimativa_fora_de_escala(banco(licitacoes=lic, despesa=desp))
    assert [a["certame"] for a in r["achados"]] == ["ABSURDO"]
    assert r["orcamento_anual_de_referencia"] == pytest.approx(1e9)


def test_sem_orcamento_de_referencia_e_indisponivel(banco):
    lic = [("X", 2025, "Dispensa", "o", 1e12, "Divulgada", RAIZ)]
    r = C.estimativa_fora_de_escala(banco(licitacoes=lic))
    assert r["prevalencia"] is None and "_indisponivel" in r


# ── objeto aberto ───────────────────────────────────────────────────────────────────────────

def test_objeto_curto_mas_claro_nao_e_generico(banco):
    """A régua de brevidade marcava 'Aquisição de MOBILIÁRIO ESCOLAR' — que é claro."""
    lic = [("A", 2025, "Pregão", "Aquisição de MOBILIÁRIO ESCOLAR", 1e6, "Divulgada", RAIZ)]
    assert C.objeto_generico(banco(licitacoes=lic))["n"] == 0


def test_objeto_com_termo_aberto_e_marcado(banco):
    lic = [("A", 2025, "Pregão", "execução de serviços gerais de manutenção", 1e6, "D", RAIZ),
           ("B", 2025, "Pregão", "aquisição de medicamentos e outros", 1e6, "D", RAIZ),
           ("C", 2025, "Pregão", "Aquisição de livros didáticos", 1e6, "D", RAIZ)]
    r = C.objeto_generico(banco(licitacoes=lic))
    assert {a["certame"] for a in r["achados"]} == {"A", "B"}


# ── vencedor contumaz ───────────────────────────────────────────────────────────────────────

def test_vencedor_contumaz_conta_certames_distintos(banco):
    """Dois itens do mesmo certame não são duas vitórias."""
    res = [(f"CERT{i}", "1" * 14, "RECORRENTE", 1000.0) for i in range(6)]
    res += [("CERT0", "1" * 14, "RECORRENTE", 1000.0)]        # item extra do mesmo certame
    ed = [(f"CERT{i}", RAIZ) for i in range(6)]
    r = C.vencedor_contumaz(banco(resultado=res, editais=ed))
    assert r["n"] == 1 and r["achados"][0]["n_certames"] == 6


# ── terceiro setor ──────────────────────────────────────────────────────────────────────────

def test_concentracao_conta_quantas_entidades_fazem_metade(banco):
    # natureza NNNNNNNN: posições 3-4 são a MODALIDADE. Transferência a entidade privada é a
    # modalidade 50 -> "33503901". "33905001" seria modalidade 90 com elemento 50 (errei assim
    # na primeira escrita, e o teste pegou).
    desp = [(2022, "SMS", f"{i}" * 14, f"ONG {i}", "33503901", 0, 0, v)
            for i, v in ((1, 60.0), (2, 20.0), (3, 10.0), (4, 10.0))]
    r = C.concentracao_do_terceiro_setor(banco(despesa=desp))
    assert r["n"] == 1, "a maior sozinha já passa de metade"
    assert r["massa"] == pytest.approx(100.0)


def test_terceiro_setor_agrupa_por_documento_E_nome(banco):
    """A máscara colide: agrupar só por documento somaria entidades distintas."""
    desp = [(2022, "SMS", "***201901**", "ENTIDADE A", "33503901", 0, 0, 100.0),
            (2022, "SMS", "***201901**", "ENTIDADE B", "33503901", 0, 0, 100.0)]
    r = C.concentracao_do_terceiro_setor(banco(despesa=desp))
    assert r["universo"] == 2, "duas entidades, não uma"


def test_toda_lente_declara_o_contrato(banco):
    db = banco(contratos=[_c("A", "ALFA")],
               licitacoes=[("L", 2025, "Pregão", "objeto claro", 1000.0, "D", RAIZ)],
               despesa=[(2022, "SMS", "1" * 14, "X", "33503901", 0, 0, 10.0)])
    for fn in C.LENTES + C.CONTROLES:
        r = fn(db)
        assert {"lente", "universo", "n", "prevalencia", "massa", "achados"} <= set(r), fn.__name__
        if r["universo"] == 0:
            assert r["prevalencia"] is None, f"{fn.__name__}: universo vazio virou 0%"


# ── entidade paga como serviço em vez de parceria ───────────────────────────────────────────

def test_receber_pelas_duas_portas_nao_e_achado(banco):
    """Medido: 56,9% das entidades fazem isso. É a norma — hipótese descartada por prevalência."""
    desp = [(2022, "SMS", "1" * 14, "ONG", "33503901", 0, 0, 1_000_000.0),
            (2022, "SMS", "1" * 14, "ONG", "33903901", 0, 0, 1_000_000.0)]
    r = C.entidade_paga_como_servico(banco(despesa=desp))
    assert r["n"] == 0, "razão 1x não passa do corte de 10x"
    assert r["recebem_pelas_duas_portas"] == 1


def test_proporcao_invertida_e_o_que_discrimina(banco):
    desp = [(2022, "SMS", "1" * 14, "SEGUMED", "33503901", 0, 0, 700_000.00),
            (2022, "SMS", "1" * 14, "SEGUMED", "33903901", 0, 0, 80_000_000.00)]
    r = C.entidade_paga_como_servico(banco(despesa=desp))
    assert r["n"] == 1
    assert r["achados"][0]["razao"] == pytest.approx(80_000_000 / 700_000)


def test_entidade_sem_transferencia_alguma_fica_fora(banco):
    """Sem a porta da parceria não há proporção a inverter — é fornecedor comum, outra lente."""
    desp = [(2022, "SMS", "1" * 14, "EMPRESA", "33903901", 0, 0, 90_000_000.0)]
    assert C.entidade_paga_como_servico(banco(despesa=desp))["n"] == 0


def test_piso_evita_entidade_minuscula(banco):
    desp = [(2022, "SMS", "1" * 14, "ONG", "33503901", 0, 0, 10.0),
            (2022, "SMS", "1" * 14, "ONG", "33903901", 0, 0, 100_000.0)]
    assert C.entidade_paga_como_servico(banco(despesa=desp))["n"] == 0
