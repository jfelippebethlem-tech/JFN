# -*- coding: utf-8 -*-
"""Decisões jurídicas do dono (24/11/2026, noite — `o53-paridade-fatia2.md`), aplicadas EM SOMBRA (e9-sombra-3):
controle positivo e negativo de cada uma.

  1. OB com GD sem valor apurado: paga pelo valor cheio; régua do valor LÍQUIDO → `?:DEVOLUCAO_NAO_APURADA`
  2. OS/OSC = fornecedor com regime próprio (`I:REGIME_PROPRIO_MROSC` na dispensa/soma); RJPREV = ente público pela raiz
  3. X1 exclui renovação, prorrogação, reajuste, repactuação e reequilíbrio (natureza por `limites_aditivo`)
  4. sede de fachada: imóvel residencial não é 2º sinal (só residencial → INCERTO)
  5. candidato ao P4 por OB fica INDETERMINADO (`?:SEM_NE`) até a NE por UG (O4.11)
  + deduplicação do espelho TCE-RJ pela chave canônica (`dominio.contrato_id`)
"""
import sqlite3

import pytest

from compliance_agent.aplicacao.detectores import candidato_p4_siafe as CP
from compliance_agent.aplicacao.detectores import contabil_siafe as CS
from compliance_agent.aplicacao.detectores import emergencia_recorrente as P5
from compliance_agent.aplicacao.detectores import sede_fachada as SF
from compliance_agent.aplicacao.detectores import troca_gestao as T
from compliance_agent.aplicacao.estagios import elegibilidade as E
from compliance_agent.detectores.x1_crescimento_aditivo import X1CrescimentoAditivo
from compliance_agent.dominio.contrato_id import chave_espelho_tcerj, deduplicar
from compliance_agent.limites_aditivo import classificar_natureza
from compliance_agent.limites_dispensa import limite_dispensa


def _ob(**kw) -> E.Fatos:
    base = dict(unidade="ob_siafe", chave="010100|2025OB1|2025", paga=True, credor_classe="PJ_PRIVADA",
                natureza_pagamento="PARCELA_CONTRATO", nao_e_contratacao_nova=True, credor_e_fornecedor=True,
                elemento="39")
    base.update(kw)
    return E.Fatos(**base)


def test_versao_da_e9_subiu_com_a_regra():
    assert E.VERSAO == "e9-sombra-4" and "valor_liquido" in E.EXIGES_OB    # 4: decisões delegadas de 24/11


# ── 1. devolução sem valor apurado ──────────────────────────────────────────────────────────────────────────────
def test_d1_positivo_gd_nao_apurada_fica_indeterminada_no_liquido():
    ex = _ob(devolucao="nao_apurada").exiges()
    assert ex["valor_liquido"] == "?:DEVOLUCAO_NAO_APURADA"
    assert ex["execucao"] == "E" and ex["fornecedor"] == "E"        # o pago é a OB pelo valor cheio: não some
    nova = _ob(devolucao="nao_apurada", natureza_pagamento="CONTRATACAO_NOVA", nao_e_contratacao_nova=False)
    assert nova.exiges()["soma_art75"] == "?:DEVOLUCAO_NAO_APURADA"


def test_d1_negativo_sem_gd_ou_apurada_segue_elegivel():
    assert _ob().exiges()["valor_liquido"] == "E" and _ob(devolucao="apurada").exiges()["valor_liquido"] == "E"
    assert _ob(devolucao="nao_apurada", paga=False).exiges()["valor_liquido"] == "I:NAO_PAGA"
    assert E.devolucao_ob("2025GD00001", "Processado e Pago", None) == "nao_apurada"
    assert E.devolucao_ob("2025GD00001", "Processado e Pago", 10.0) == "apurada"
    assert E.devolucao_ob("OB já encaminhada ao banco", "", None) == ""       # lixo de coleta na coluna gd


def test_d1_ob_paga_acima_le_valor_liquido_e_abate_a_guia_apurada():
    # E9-9 (decisão delegada 24/11): todo credor, pelo valor líquido — a GD não apurada continua '?' (decisão 1)
    assert E.exiges_do_detector("e10.ob_paga_acima_liquidado") == {"ob_siafe": "registro_liquido"}
    assert E.exiges_do_detector("e10.ob_antes_da_liquidacao") == {"ob_siafe": "universo"}

    def it(ob, valor, dev):
        return {"chave_e9": ob, "grupo": "NL1|010100", "numero_ob": ob, "ug": "010100", "exercicio": 2025,
                "data": None, "nl": "NL1", "valor": valor, "devolvido": dev, "mesmo_credor": True,
                "credor_raiz": "11111111", "nl_status": "Contabilizado", "nl_valor": 100.0, "nl_data": None, "e9": "E"}
    assert CS.PAGO_ACIMA.detectar([it("A", 80.0, None), it("B", 40.0, 30.0)]) == []      # 80 + (40 − 30) = 90
    ds = CS.PAGO_ACIMA.detectar([it("A", 80.0, None), it("B", 40.0, 5.0)])                 # 80 + 35 = 115
    assert len(ds) == 1 and ds[0].valores["excedente"] == 15.0


def test_d1_adaptador_le_a_gd_da_ob_e_a_guia(tmp_path):
    p = tmp_path / "c.db"
    c = sqlite3.connect(p)
    c.executescript("""
    CREATE TABLE empresas_cadastro(cnpj_basico, razao_social, natureza_cod);
    CREATE TABLE nl_siafe(numero, ug_emitente, ne);
    CREATE TABLE ne_siafe(numero, ug_emitente, natureza, ano_ne);
    CREATE TABLE vinculo_ob_contrato(ob, ug, estado);
    CREATE TABLE compras_diretas_tcerj(processo, unidade, enquadramento_legal, afastamento, ano_processo, valor);
    CREATE TABLE contratos_tcerj(processo, cnpj);
    CREATE TABLE ob_orcamentaria_siafe(numero_ob, ug_emitente, ug_liquidante, nl, credor, nome_credor, tipo_ob, valor,
      exercicio INTEGER, data_emissao, status, status_envio, gd, tipo_regularizacao);
    CREATE TABLE gd_siafe(numero, ug_emitente, exercicio, ano_gd, data_emissao, tipo_baixa, status, ug_liquidante,
      ob, valor, coletado_em);
    INSERT INTO ob_orcamentaria_siafe VALUES
      ('2025OB1','010100','010100','','22222222000100','ACME','Orçamentária',100,2025,'10/03/2025','Contabilizado',
       'Processado e Pago','2025GD00001',''),
      ('2025OB2','010100','010100','','22222222000100','ACME','Orçamentária',100,2025,'10/03/2025','Contabilizado',
       'Processado e Pago','2025GD00002',''),
      ('2025OB3','010100','010100','','22222222000100','ACME','Orçamentária',100,2025,'10/03/2025','Contabilizado',
       '','','');
    INSERT INTO gd_siafe VALUES ('2025GD00002','010100',2025,2025,'11/03/2025','','Contabilizado','010100',
      '2025OB2',40,'');
    """)
    c.commit()
    c.close()
    q = E.Consultas(E.abrir_fonte(p))
    por = {f.numero_ob: f for f in E.iterar("ob_siafe", q)}
    assert (por["2025OB1"].devolucao, por["2025OB2"].devolucao, por["2025OB3"].devolucao) == \
        ("nao_apurada", "apurada", "")
    assert E.recalcular("ob_siafe", "010100|2025OB1|2025", E.Consultas(E.abrir_fonte(p), em_lote=False)).devolucao \
        == "nao_apurada"                                                  # conferência por chave = lote


# ── 2. OS/OSC e RJPREV ──────────────────────────────────────────────────────────────────────────────────────────
def test_d2_positivo_osc_e_fornecedor_e_fica_fora_da_dispensa():
    ob = _ob(credor_classe="OS_OSC", natureza_pagamento="CONTRATACAO_NOVA", nao_e_contratacao_nova=False).exiges()
    assert ob["fornecedor"] == "E" and ob["soma_art75"] == "I:REGIME_PROPRIO_MROSC"
    ct = E.Fatos(unidade="compra_direta_tcerj", chave="SEI-1", credor_classe="OS_OSC", regime="L14133",
                 dispensa_valor=True, teto=62725.59).exiges()
    assert ct["fornecedor"] == "E" and ct["dispensa_valor"] == "I:REGIME_PROPRIO_MROSC"


def test_d2_negativo_empresa_privada_segue_na_dispensa():
    ct = E.Fatos(unidade="compra_direta_tcerj", chave="SEI-1", credor_classe="PJ_PRIVADA", regime="L14133",
                 dispensa_valor=True, teto=62725.59).exiges()
    assert ct["dispensa_valor"] == "E"


def test_d2_rjprev_e_ente_publico_pela_raiz_nunca_pelo_nome():
    nat = {"17713878": "3069", "48307566": "3328", "55555555": "3069"}
    assert E.classe_credor("17713878000177", nat) == ("ENTE_PUBLICO", "17713878", "3069")
    assert E.classe_credor("48307566000197", nat)[0] == "ENTE_PUBLICO"
    assert E.classe_credor("55555555000155", nat)[0] == "OS_OSC"         # outra fundação 3069: a raiz decide
    assert _ob(credor_classe="ENTE_PUBLICO").exiges()["fornecedor"] == "I:ENTE_PUBLICO"


# ── 3. X1: só o acréscimo de objeto conta ───────────────────────────────────────────────────────────────────────
def _x1(*aditivos):
    return X1CrescimentoAditivo().avaliar({"processo": "P", "valor_inicial": 9550.0, "aditivos": list(aditivos)}).valores


@pytest.mark.parametrize("texto", [
    "Renovação de Apólice de Seguros para a frota da CMRJ de 8 (oito) veículos por mais 12 (doze) meses.",
    "RENOVAÇÃO CONTRATUAL POR MAIS 12 MESES",
    "Prorrogação do prazo de vigência por 12 meses",
    "Reajuste contratual pelo IPCA",
    "Repactuação dos preços por convenção coletiva",
    "Reequilíbrio econômico-financeiro do contrato",
])
def test_d3_negativo_renovacao_prorrogacao_reajuste_nao_contam(texto):
    v = _x1({"tipo": "valor", "valor": 14134.88, "descricao_objeto": texto, "justificativa": texto})
    assert v["n_aditivos_de_valor"] == 0 and v["estouro_teto"] is False and v["fora_do_teto_por_natureza"]


def test_d3_positivo_acrescimo_de_objeto_conta():
    v = _x1({"tipo": "valor", "valor": 5000.0, "descricao_objeto": "acréscimo quantitativo de 8 veículos"})
    assert v["n_aditivos_de_valor"] == 1 and v["estouro_teto"] is True


def test_d3_renovacao_do_objeto_nao_vira_prazo():
    assert classificar_natureza("Aquisição de Renovação dos Serviços de Suporte Técnico")[0] == ""
    assert classificar_natureza("Acréscimo quantitativo de serviço de renovação de ar")[0] == "valor"


# ── 4. sede de fachada: residencial não é 2º sinal ──────────────────────────────────────────────────────────────
def _sede(classe=None, endereco=None, sinais='[{"id": "email_compartilhado", "direcao": "suspeita"}]'):
    return {"chave_e9": "x", "cnpj": "11111111000111", "grupo": "11111111000111", "n_ob": 1, "pago": 10.0, "e9": "E",
            "sede": {"veredito": "suspeita", "apuravel": 1, "score": 60, "sinais": sinais},
            "endereco": None if endereco is None else {"status": "INDICIO", "nivel": "ALTO", "evidencia": endereco},
            "foto": None if classe is None else {"classe": classe, "coerencia": None, "predio": "k", "fonte": "sv"}}


@pytest.mark.parametrize("classe", ["casa_residencial", "predio_residencial"])
def test_d4_negativo_so_foto_residencial_e_incerto(classe):
    ds = SF.detectar([_sede(classe)])
    assert len(ds) == 1 and ds[0].estado == "INCERTO" and ds[0].valores["nao_residenciais"] == ["sede"]


def test_d4_positivo_foto_nao_residencial_e_indicio():
    ds = SF.detectar([_sede("terreno_baldio")])
    assert len(ds) == 1 and ds[0].estado == "INDICIO"
    ds = SF.detectar([_sede("casa_residencial", endereco="Endereço não localizado no OSM")])
    assert ds[0].estado == "INDICIO" and ds[0].valores["nao_residenciais"] == ["sede", "endereco"]


def test_d4_sede_real_so_residencial_nao_conta_como_sinal_independente():
    so_res = '[{"id": "complemento_residencial", "direcao": "suspeita"}, {"id": "x", "direcao": "substancia"}]'
    assert SF.detectar([_sede("terreno_baldio", sinais=so_res)])[0].estado == "INCERTO"
    assert SF.detectar([_sede("casa_residencial", endereco="imóvel residencial", sinais=so_res)])[0].estado == \
        "INCERTO"


# ── 5. candidato ao P4 sem NE ───────────────────────────────────────────────────────────────────────────────────
def test_d5_candidato_p4_sem_ne_fica_indeterminado(tmp_path):
    teto = limite_dispensa(2025, "compras")
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe(ug_emitente, credor, nome_credor, data_emissao, valor, processo, "
                "numero_ob, status, nl, exercicio INTEGER)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [("010100", "11111111000111", "ACME SERVICOS LTDA", f"0{i}/03/2025", teto * 0.5, f"P{i}",
                      f"2025OB{i}", "Contabilizado", None, 2025) for i in (1, 2, 3)])
    con.commit()
    con.close()
    itens = CP.carregar(sqlite3.connect(f"file:{p}?mode=ro", uri=True)).itens
    for c in itens:
        c["e9"] = "?:SEM_NE"
    assert CP.detectar(itens) == []                                      # nunca "elegível por omissão"
    for c in itens:
        c["e9"] = "E"
    assert len(CP.detectar(itens)) == 1                                  # controle positivo da mesma série
    assert E.exiges_do_detector("e10.candidato_p4_siafe") == {"ob_siafe": "soma_art75"}
    assert _ob(natureza_pagamento="INDETERMINADO", natureza_despesa=None).exiges()["soma_art75"] == "?:SEM_NE"


# ── deduplicação do espelho TCE-RJ ──────────────────────────────────────────────────────────────────────────────
def test_dedup_chave_canonica_junta_grafias_e_separa_contratos_distintos():
    a = chave_espelho_tcerj("EMOP", "SEI-330003/000613/2026", cnpj="34.551.839/0001-30", valor=48625672.99)
    assert a == chave_espelho_tcerj("EMOP", "SEI330003/000613/2026", cnpj="34551839000130", valor="48625672.990")
    assert a == chave_espelho_tcerj("EMOP", "330003/000613/2026", cnpj="34551839000130", valor=48625672.99)
    assert a != chave_espelho_tcerj("EMOP", "330003/000613/2026", cnpj="34551839000130", valor=1.0)
    assert a != chave_espelho_tcerj("OUTRA", "330003/000613/2026", cnpj="34551839000130", valor=48625672.99)
    assert chave_espelho_tcerj("EMOP", "SEI-330003/000613A/2026") != chave_espelho_tcerj("EMOP", "330003/000613/2026")
    assert chave_espelho_tcerj("EMOP", "E-12/345/2001") is None          # processo não reconhecido: nunca funde
    assert chave_espelho_tcerj("EMATER", "LOTE1-520002/001480/2026", valor=1.0) != \
        chave_espelho_tcerj("EMATER", "LOTE3-520002/001480/2026", valor=1.0)       # lotes distintos do processo


def test_dedup_fica_o_registro_mais_antigo_nao_cancelado():
    linhas = [("SEI-330003/000613/2026", "Cancelado", "2026-03-27", 10.0),
              ("SEI330003/000613/2026", "Em Aberto", "2026-06-22", 10.0),
              ("330003/000613/2026", "Em Aberto", "2026-09-29", 10.0),
              ("E-12/345/2001", "Em Aberto", "2026-01-01", 10.0), ("E-12/345/2001", "Em Aberto", "2026-01-01", 10.0)]
    fic, m = deduplicar(linhas, chave=lambda r: chave_espelho_tcerj("EMOP", r[0], valor=r[3]),
                        ordem=lambda r: (r[1] == "Cancelado", r[2]), valor=lambda r: r[3])
    assert [r[0] for r in fic] == ["SEI330003/000613/2026", "E-12/345/2001", "E-12/345/2001"]
    assert m["grupos"] == 1 and m["removidas"] == 2 and m["valor_removido"] == 20.0


def test_dedup_d02_conta_o_contrato_republicado_uma_vez(tmp_path, monkeypatch):
    from compliance_agent import credor_institucional
    monkeypatch.setattr(credor_institucional, "_receita", lambda cnpj: None)
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE ob_orcamentaria_siafe(numero_ob, ug_emitente, exercicio INTEGER, data_emissao, credor, nome_credor,
      valor, processo, status, status_envio, gd, nl);
    CREATE TABLE contratos_tcerj(processo, num_contratacao, sei_norm, valor_contrato, unidade, data_contratacao, objeto,
      status, cnpj, fornecedor);
    CREATE TABLE compras_diretas_tcerj(sei_norm, ano_processo, valor, objeto, afastamento, enquadramento_legal, unidade,
      fornecedor, ingerido_em);
    INSERT INTO contratos_tcerj VALUES
      ('SEI-330003/000100/2025','1','3300030001002025',1e6,'EMOP','2025-05-01','OBRA','Vigente','34551839000130','X'),
      ('SEI330003/000613/2026','2','3300030006132026',3e6,'EMOP','2026-06-22','OBRA','Em Aberto','34551839000130','X'),
      ('330003/000613/2026','3','3300030006132026',3e6,'EMOP','2026-09-29','OBRA','Em Aberto','34551839000130','X');
    INSERT INTO compras_diretas_tcerj VALUES ('3300030006132026',2026,3e6,'OBRA','Dispensa',
      'Lei 14.133/2021, Art. 75, VIII','EMOP','X','2026-10-09T07:00:00');
    """)
    con.commit()
    det = T._EmergencialIncumbente(corte="2026-03-23")
    carga = det.carregar(sqlite3.connect(f"file:{p}?mode=ro", uri=True))
    for c in carga.itens:
        c["e9"] = "E"
    ds = det.detectar(carga.itens, carga.contexto)
    assert [d.processo for d in ds] == ["SEI330003/000613/2026"]          # antes: as duas grafias, R$ 6 mi
    assert carga.contexto["dedup_espelho"]["removidas"] == 1
    con.close()


def test_dedup_p5_grafias_do_mesmo_processo_sao_uma_emergencia():
    linhas = [("SEI-1/1", "U", 2026, "ACME", 10.0, "o", "e")]
    fic, m = P5._dedup([("SEI-330003/000001/2026", "U", 2026, "ACME", 10.0, "o", "e"),
                        ("330003/000001/2026", "U", 2026, "ACME", 10.0, "o", "e"),
                        ("330003/000001/2026", "U", 2026, "OUTRA", 10.0, "o", "e")] + linhas)
    assert len(fic) == 3 and m["removidas"] == 1
