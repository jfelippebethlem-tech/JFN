# -*- coding: utf-8 -*-
"""Ordem cronológica (Dec. RJ 49.134/2024 art. 9º): pela data da NL, por fonte; só bens/serviços/locação/obras."""
import sqlite3

from compliance_agent.ordem_cronologica_siafe import ordem_cronologica


def _bases(tmp_path):
    db, est = tmp_path / "c.db", tmp_path / "e.db"
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE ne_siafe(numero,ug_emitente,exercicio,fonte,natureza,status);
    CREATE TABLE nl_siafe(numero,ug_emitente,exercicio,ano_nl,data_emissao,status,ne,credor,nome_credor,valor,processo);
    CREATE TABLE ob_orcamentaria_siafe(numero_ob,ug_emitente,nl,status,data_emissao,valor);
    CREATE TABLE siafe_documento_cobertura(tipo,ug_emitente,exercicio,completo,colhidas,em);
    INSERT INTO siafe_documento_cobertura VALUES ('NE','100',2025,1,4,''),('NL','100',2025,1,4,'');
    """)
    c.executemany("INSERT INTO ne_siafe VALUES (?,?,2025,?,?,'Contabilizado')", [
        ("2025NE1", "100", "500", "339039"), ("2025NE2", "100", "500", "339039"),
        ("2025NE3", "100", "759", "339039"),          # outra fonte: fila separada
        ("2025NE4", "100", "500", "339014"),          # diária: fora da ordem (alínea e)
    ])
    c.executemany("INSERT INTO nl_siafe VALUES (?,'100',2025,2025,?,'Contabilizado',?,?,?,?,?)", [
        ("2025NL1", "01/03/2025", "2025NE1", "11111111000101", "ANTIGA", 100.0, "SEI-A"),   # liquidada 1º
        ("2025NL2", "10/03/2025", "2025NE2", "22222222000101", "NOVA", 200.0, "SEI-B"),     # liquidada depois
        ("2025NL3", "05/03/2025", "2025NE3", "33333333000101", "OUTRA FONTE", 50.0, ""),
        ("2025NL4", "02/03/2025", "2025NE4", "44444444000101", "DIARIA", 9.0, ""),
    ])
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,'100',?,'Contabilizado',?,?)", [
        ("OB2", "2025NL2", "12/03/2025", 200.0),      # a nova foi paga em 12/03
        ("OB1", "2025NL1", "30/04/2025", 100.0),      # a antiga só em 30/04: furaram a fila dela
        ("OB3", "2025NL3", "06/03/2025", 50.0),
        ("OB4", "2025NL4", "03/03/2025", 9.0),
    ])
    c.commit()
    c.close()
    e = sqlite3.connect(est)
    e.execute("CREATE TABLE empresas(cnpj_basico,natureza_cod)")
    e.execute("CREATE TABLE estabelecimentos(cnpj_basico,matriz_filial,cnae_principal)")
    for b in ("11111111", "22222222", "33333333", "44444444"):
        e.execute("INSERT INTO empresas VALUES (?, '2062')", (b,))
        e.execute("INSERT INTO estabelecimentos VALUES (?, '1', '4120400')", (b,))
    e.commit()
    e.close()
    return db, est


def test_nl_liquidada_depois_e_paga_antes_fura_a_fila(tmp_path):
    db, est = _bases(tmp_path)
    r = ordem_cronologica(db, est)
    assert r["n"] == 1
    a = r["achados"][0]
    assert a["nl"] == "2025NL2" and a["fonte"] == "500"
    assert a["passou_na_frente_de"][0]["nl"] == "2025NL1"
    assert a["passou_na_frente_de"][0]["dias_esperando"] == 49        # 12/03 → 30/04
    assert a["forca"] == "forte"
    assert "art. 9" in r["nota"] and "indício" in r["nota"].lower()


def test_fonte_diferente_e_natureza_excepcionada_nao_contam(tmp_path):
    db, est = _bases(tmp_path)
    nls = {a["nl"] for a in ordem_cronologica(db, est)["achados"]}
    assert "2025NL3" not in nls and "2025NL4" not in nls


def test_resto_a_pagar_tem_fila_propria_e_estatal_fica_fora(tmp_path):
    """04/11/2026: NL de 2019 (RP) sem pagamento aparecia preterida por NL de 2025; e a Imprensa Oficial
    (estatal, alíneas m/n) entrava na fila."""
    db, est = _bases(tmp_path)
    c = sqlite3.connect(db)
    c.execute("INSERT INTO ne_siafe VALUES ('2019NE9','100',2025,'500','339039','Contabilizado')")
    c.execute("INSERT INTO nl_siafe VALUES ('2019NL9','100',2025,2019,'31/12/2019','Contabilizado','2019NE9',"
              "'99999999000101','RP ANTIGO',5.0,'')")
    c.commit()
    c.close()
    e = sqlite3.connect(est)
    e.execute("INSERT INTO empresas VALUES ('99999999', '2062')")
    e.execute("INSERT INTO estabelecimentos VALUES ('99999999', '1', '4120400')")
    e.execute("UPDATE empresas SET natureza_cod='2011' WHERE cnpj_basico='22222222'")   # a "nova" vira estatal
    e.commit()
    e.close()
    r = ordem_cronologica(db, est)
    assert all(x["nl"] != "2025NL2" for x in r["achados"])                       # estatal fora
    assert all(y["nl"] != "2019NL9" for x in r["achados"] for y in x["passou_na_frente_de"])  # RP noutra fila


def test_inversao_de_poucos_dias_e_agenda_nao_quebra(tmp_path):
    """A PD vai ao Tesouro com 2 dias úteis (Dec. 49.134 art. 14 §3º): 3 dias de espera não é achado."""
    db, est = _bases(tmp_path)
    c = sqlite3.connect(db)
    c.execute("UPDATE ob_orcamentaria_siafe SET data_emissao='15/03/2025' WHERE numero_ob='OB1'")
    c.commit()
    c.close()
    r = ordem_cronologica(db, est)
    assert r["n"] == 0 and r["inversoes_curtas"] == 1


def test_ug_sem_nl_completa_fica_fora(tmp_path):
    """04/11/2026: 166100 tinha só 1.000 NL (coleta capada) e o detector acusou 346 quebras."""
    db, est = _bases(tmp_path)
    c = sqlite3.connect(db)
    c.execute("UPDATE siafe_documento_cobertura SET completo=0 WHERE tipo='NL'")
    c.commit()
    c.close()
    r = ordem_cronologica(db, est)
    assert r["n"] == 0 and r["ugs_cobertas"] == []


def test_preterida_sem_ob_na_base_nao_vira_quebra(tmp_path):
    """Sem OB na base não prova que não pagou (cobertura da OB é parcial): vai para `pendentes`, não para quebra."""
    db, est = _bases(tmp_path)
    c = sqlite3.connect(db)
    c.execute("DELETE FROM ob_orcamentaria_siafe WHERE numero_ob='OB1'")
    c.commit()
    c.close()
    r = ordem_cronologica(db, est)
    assert r["n"] == 0 and r["pendentes"] == 1
