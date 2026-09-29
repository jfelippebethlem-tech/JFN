# -*- coding: utf-8 -*-
"""Acervo (20/09/2026): normalização do nº, ficha unificada e busca única sobre bases mínimas."""
from __future__ import annotations

import json
import sqlite3

from compliance_agent import acervo


def test_norm_reconhece_as_grafias_do_estado_e_da_prefeitura():
    assert acervo.norm("SEI-080001/000633/2024") == ("estado", "SEI-080001/000633/2024")
    assert acervo.norm("270099/000714/2022") == ("estado", "SEI-270099/000714/2022")
    assert acervo.norm("030001_087722_2024") == ("estado", "SEI-030001/087722/2024")
    assert acervo.norm("000700.007924/2026-97") == ("prefeitura", "000700.007924/2026-97")
    assert acervo.norm("sme-pro-2025/38233") == ("prefeitura", "SME-PRO-2025/38233")
    assert acervo.norm("limpeza hospitalar") is None


def _bases(tmp_path, monkeypatch):
    comp = tmp_path / "compliance.db"
    c = sqlite3.connect(comp)
    c.executescript("""
    CREATE TABLE sei_arvore (numero_sei, objeto, nivel_risco, n_membros, n_docs, n_obs, total_pago, fornecedores, txt_path, atualizado_em, lifecycle, ultima_ob, situacao, encerrado, anexo_b2);
    INSERT INTO sei_arvore VALUES ('SEI-080001/000633/2024','Apoio ao Hospital de Nova Iguaçu','medio',1,10,5,115000000.0,
        '[{"cnpj": "10497795000149", "nome": "Fundo Municipal De Saude", "valor": 115000000.0}]','/x.txt','2026-09-01','ativo','2026-08-01','',0,NULL);
    CREATE TABLE processo_avaliacao (numero_sei, score100, grau, faixa, achados_json, lacunas_json, docs_chave_json, acatamento_json, escalada_json, cnpj_vencedor, confianca, cobertura_json, avaliado_em, versao, sintese_json);
    INSERT INTO processo_avaliacao VALUES ('080001/000633/2024', 72.5, 'ALTO', 'ALTO', '[{"codigo":"A1","grau":"alto","diz":"contrato antes do parecer","apoio":"doc 3"}]', '[]', '[]', NULL, NULL, '10497795000149', 'media', NULL, '2026-09-02', 3, NULL);
    CREATE TABLE ob_orcamentaria_siafe (numero_ob, ug_emitente, credor, nome_credor, data_emissao, processo, valor, status);
    INSERT INTO ob_orcamentaria_siafe VALUES ('2025OB1','080001','10497795000149','FUNDO MUN SAUDE','01/03/2025','SEI-080001/000633/2024', 1000.0, 'Contabilizado');
    INSERT INTO ob_orcamentaria_siafe VALUES ('2025OB2','080001','10497795000149','FUNDO MUN SAUDE','01/04/2025','SEI-080001/000633/2024', 2000.0, 'Contabilizado');
    INSERT INTO ob_orcamentaria_siafe VALUES ('2025OB3','080001','10497795000149','FUNDO MUN SAUDE','02/04/2025','SEI-080001/000633/2024', 9000.0, 'Anulado');
    """)
    c.commit(); c.close()
    pc = tmp_path / "pcrj.db"
    p = sqlite3.connect(pc)
    p.executescript("""
    CREATE TABLE pcrj_processo (numero_processo, sistema, interessado, assunto, orgao, andamento_json, disponivel, coletado_em);
    INSERT INTO pcrj_processo VALUES ('000700.007924/2026-97','SEI.RIO',NULL,'CONTRATAÇÃO: SERVIÇOS','E/SUBG',NULL,1,'2026-09-15');
    CREATE TABLE pcrj_sei_arvore (numero, doc, tipo, data, inclusao, unidade);
    INSERT INTO pcrj_sei_arvore VALUES ('000700.007924/2026-97','5479825','Ordem de Serviço','03/07/2026','03/07/2026','E/SUBG/CCPAR/GGOV');
    CREATE TABLE pcrj_processo_doc (numero_processo, seq, tipo, titulo, texto, url, coletado_em);
    INSERT INTO pcrj_processo_doc VALUES ('000700.007924/2026-97',4071,'ccon_integra','Contrato 70/2026','CONTRATO Nº 70/2026 … valor total R$ 52.041.528,00','u','2026-09-16');
    CREATE TABLE contasrio_contrato (contrato, favorecido_doc, favorecido_nome, orgao, ano, forma_contratacao, objeto, valor_atualizado, total_pago, vigencia_ini, vigencia_fim, processo, url_ccon);
    INSERT INTO contasrio_contrato VALUES ('2608939','00801512000157','AGILE CORP','1601 - SME',2026,'Licitação - Pregão','manipulação de alimentos',54466163.28,2030147.16,'01/07/2026','30/06/2028','000700.007924/2026-97','https://x?contrato=2608939');
    CREATE TABLE pcrj_emergencia_sinal (contrato, processo, favorecido_doc, favorecido_nome, orgao, ano, valor_atualizado, total_pago, vigencia_ini, vigencia_fim, fundamento, incumbente_contrato, incumbente_desde, certame_citado, prorrogada, motivo, grau, detalhe, gerado_em);
    """)
    p.commit(); p.close()
    monkeypatch.setattr(acervo, "DB_COMPLIANCE", comp)
    monkeypatch.setattr(acervo, "DB_ACHADOS", tmp_path / "nao_existe.db")
    monkeypatch.setattr(acervo, "DB_PCRJ", pc)
    monkeypatch.setattr(acervo, "DB_LAI", tmp_path / "lai.db")
    monkeypatch.setattr(acervo, "ARQUIVO_SEI", tmp_path / "sei_arquivo")
    cat = sqlite3.connect(tmp_path / "sei_rj_catalogo.db")
    cat.executescript("""CREATE TABLE sei_rj_processo (numero, tipo, id_tipo, unidade_sigla, unidade_nome, orgao, data, coletado_em);
    INSERT INTO sei_rj_processo VALUES ('SEI-080001/000633/2024','Contratação: Inexigibilidade','100000549','SES/SUBGC','Subsecretaria de Gestão','SES','2024-03-05','x');
    INSERT INTO sei_rj_processo VALUES ('SEI-150016/000001/2025','Administrativo: Termo de Ajuste de Contas - TAC','100001192','DEGASE/DG','Direção-Geral','DEGASE','2025-01-02','x');""")
    cat.commit(); cat.close()
    monkeypatch.setattr(acervo, "DB_SEI_RJ", tmp_path / "sei_rj_catalogo.db")
    arq = tmp_path / "sei_arquivo" / "080001_000633_2024" / "texto"
    arq.mkdir(parents=True)
    (arq / "000_despacho.txt").write_text("Despacho de liquidação …", encoding="utf-8")
    (arq.parent / "manifest.json").write_text(json.dumps({"docs": [{"i": "0", "titulo": "Despacho", "tipo": "liquidacao", "texto": "texto/000_despacho.txt", "chars": "24", "ocr": "False"}],
                                                        "docs_na_arvore": 10, "gerado_em": "2026-08-01"}), encoding="utf-8")


def test_ficha_estado_reune_arvore_avaliacao_obs_e_arquivo(tmp_path, monkeypatch):
    _bases(tmp_path, monkeypatch)
    f = acervo.ficha("080001/000633/2024")
    assert f["ok"] and f["esfera"] == "estado" and f["numero"] == "SEI-080001/000633/2024" and f["existe"]
    assert f["identidade"]["objeto"].startswith("Apoio") and f["avaliacao_360"]["grau"] == "ALTO"
    assert f["obs"]["n"] == 2 and f["obs"]["total"] == 3000.0 and f["obs"]["por_credor"][0]["credor"] == "10497795000149"
    assert f["documentos"][0]["titulo"] == "Despacho" and f["achados"][0]["codigo"] == "A1"
    assert "avaliar_360" in [a["id"] for a in f["acoes"]] and f["cobertura"]["arquivo"].startswith("1 documento")
    t = acervo.texto_documento("SEI-080001/000633/2024", "0")
    assert t["ok"] and "liquidação" in t["texto"]


def test_ficha_prefeitura_reune_catalogo_arvore_integra_contrato(tmp_path, monkeypatch):
    _bases(tmp_path, monkeypatch)
    f = acervo.ficha("000700.007924/2026-97")
    assert f["ok"] and f["esfera"] == "prefeitura" and f["identidade"]["tipo"].startswith("CONTRATAÇÃO")
    seqs = {d["seq"] for d in f["documentos"]}
    assert "5479825" in seqs and "4071" in seqs and any(d.get("com_texto") for d in f["documentos"])
    assert f["contratos"][0]["nome"] == "AGILE CORP" and f["obs"]["total"] == 2030147.16
    assert acervo.texto_documento("000700.007924/2026-97", "4071")["ok"]
    assert acervo.texto_documento("000700.007924/2026-97", "5479825")["ok"] is False   # a árvore lista, o SEI não abre


def test_busca_por_numero_cnpj_e_texto(tmp_path, monkeypatch):
    _bases(tmp_path, monkeypatch)
    r = acervo.buscar("080001/000633/2024")
    assert r["tipo"] == "numero" and r["n"] == 1 and r["hits"][0]["esfera"] == "estado"
    r = acervo.buscar("10.497.795/0001-49")
    assert r["tipo"] == "cnpj" and any(h["numero"] == "SEI-080001/000633/2024" for h in r["hits"])
    r = acervo.buscar("alimentos")
    assert r["esferas"]["prefeitura"] >= 1 and r["hits"][0]["numero"] == "000700.007924/2026-97"
    r = acervo.buscar("hospital", esfera="estado")
    assert r["n"] == 1 and r["hits"][0]["fonte"] == "sei_arvore"
    assert acervo.buscar("")["ok"] is False


def test_catalogo_publico_do_estado_entra_na_ficha_na_busca_e_nas_estatisticas(tmp_path, monkeypatch):
    _bases(tmp_path, monkeypatch)
    f = acervo.ficha("080001/000633/2024")
    assert f["identidade"]["tipo"] == "Contratação: Inexigibilidade" and f["identidade"]["orgao_gerador"] == "SES"
    assert f["cobertura"]["catalogo_publico"] == "lido"
    b = acervo.buscar("termo de ajuste", esfera="estado")
    assert [h["numero"] for h in b["hits"]] == ["SEI-150016/000001/2025"] and b["hits"][0]["fonte"] == "catalogo_publico"
    assert acervo.estatisticas()["estado_catalogo"] == 2


def test_tac_do_doerj_entra_na_ficha_e_na_busca_por_fornecedor(tmp_path, monkeypatch):
    _bases(tmp_path, monkeypatch)
    c = sqlite3.connect(tmp_path / "compliance.db")
    c.executescript("""CREATE TABLE doerj_tac (data_doe, numero_tac, orgao, fornecedor, cnpj, valor, processo, objeto, data_assinatura, id_publicacao, gerado_em);
    INSERT INTO doerj_tac VALUES ('2026-06-02','696/2026','Fundação Saúde','ECO CONSULTORIA LTDA',NULL,311625.36,'SEI-080001/000633/2024','indenização por serviço','2026-05-30',282,'x');
    INSERT INTO doerj_tac VALUES ('2026-07-02','801/2026','Fundação Saúde','ECO CONSULTORIA LTDA',NULL,100.0,'SEI-080001/000633/2024','indenização por serviço','2026-06-30',300,'x');""")
    c.commit(); c.close()
    f = acervo.ficha("SEI-080001/000633/2024")
    assert [t["numero_tac"] for t in f["tac"]] == ["696/2026", "801/2026"]
    assert f["cobertura"]["doerj_tac"].startswith("2 extrato")
    b = acervo.buscar("eco consultoria", esfera="estado")
    h = [x for x in b["hits"] if x["fonte"] == "doerj_tac"]
    assert len(h) == 1 and h[0]["numero"] == "SEI-080001/000633/2024" and h[0]["n_tac"] == 2


def test_ob_anulada_fica_fora_do_total_e_aparece_na_lista(tmp_path, monkeypatch):
    """R$ 6,58 bi em OB Anulada/Excluída inflavam o total de 5.726 fichas (24/09/2026)."""
    _bases(tmp_path, monkeypatch)
    o = acervo.ficha("SEI-080001/000633/2024")["obs"]
    assert o["total"] == 3000.0 and o["n"] == 2
    assert o["n_nao_pagas"] == 1 and o["valor_nao_pago"] == 9000.0
    assert [x["numero_ob"] for x in o["lista"]] == ["2025OB3", "2025OB2", "2025OB1"]


def test_consulta_ao_vivo_pcrj_pedido_resposta(tmp_path, monkeypatch):
    """Canal VM-1 → VM-2: pedido em pedidos/, resposta em respostas/ (um escritor por pasta)."""
    import json as _j
    import os as _os
    _bases(tmp_path, monkeypatch)
    monkeypatch.setattr(acervo, "CONSULTA_PCRJ", tmp_path / "consulta")
    assert acervo.pedir_consulta_pcrj("SEI-080001/000633/2024")["ok"] is False
    r = acervo.pedir_consulta_pcrj("000700.007924/2026-97")
    assert r["ok"] and (tmp_path / "consulta/pedidos/000700_007924_2026_97.req").read_text() == "000700.007924/2026-97"
    f = acervo.ficha("000700.007924/2026-97")
    assert f["consulta_ao_vivo"] == {"pendente": True} and f["acoes"][0]["rota"] == "/api/pcrj/consultar"
    resp = tmp_path / "consulta/respostas"; resp.mkdir(parents=True)
    (resp / "000700_007924_2026_97.json").write_text(_j.dumps({"numero": "000700.007924/2026-97", "consultado_em": "2026-09-24 05:01:28",
                                                               "documentos": [{"numero": "5479825", "tipo": "Ordem de Serviço"}]}))
    ped = tmp_path / "consulta/pedidos/000700_007924_2026_97.req"
    _os.utime(ped, (1, 1))
    f = acervo.ficha("000700.007924/2026-97")
    assert f["consulta_ao_vivo"]["documentos"][0]["numero"] == "5479825"
    assert f["cobertura"]["consulta_ao_vivo"].startswith("SEI.RIO consultado em 2026-09-24")
