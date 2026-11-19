# -*- coding: utf-8 -*-
"""Recoleta do `status_envio` das OBs em estado intermediário (foto do dia da coleta, nunca atualizada).

Verificação Fable 13/11/2026: 37.982 OBs de 2026 seguiam "Enviado ao Banco" e 2,4% das conferíveis tinham sido
devolvidas depois. Dados sintéticos."""
import asyncio
import sqlite3
from datetime import datetime

from compliance_agent import siafe_status_ob as S

AGORA = datetime(2026, 11, 13, 5, 30)


def _base(db):
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE ob_orcamentaria_siafe(numero_ob,ug_emitente,exercicio,data_emissao,status,valor,"
              "status_envio, PRIMARY KEY (numero_ob, ug_emitente, exercicio))")
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,2026,?,'Contabilizado',?,?)", [
        ("2026OB00001", "100100", "01/09/2026", 1_000.0, "Enviado ao Banco"),
        ("2026OB00002", "100100", "02/09/2026", 900_000.0, "Enviado ao Banco"),
        ("2026OB00003", "100100", "02/09/2026", 5.0, "Aguardando Envio"),
        ("2026OB00004", "100100", "03/09/2026", 50_000.0, "Enviado Manualmente"),   # meio de envio, estável
        ("2026OB00005", "100100", "03/09/2026", 70_000.0, "Processado e Pago"),
        ("2026OB00006", "100100", "12/11/2026", 9_000_000.0, "Enviado ao Banco"),   # recente: é do verificador
        ("2026OB00007", "200200", "01/09/2026", 2_000.0, "Enviado ao Banco"),
    ])
    c.commit()
    c.close()


def test_fila_por_valor_intermediario_sem_dias_recentes_nem_status_estavel(tmp_path):
    db = tmp_path / "c.db"
    _base(db)
    f = S.fila(2026, db=db, agora=AGORA)
    assert [d["data"] for d in f] == ["02/09/2026", "01/09/2026"]
    assert f[0] == {"data": "02/09/2026", "n": 2, "valor": 900_005.0, "exercicio": 2026, "motivo": "nao_final"}
    assert S.fila(2026, db=db, max_dias=1, agora=AGORA)[0]["data"] == "02/09/2026"


def _coletor(db, novos):
    """Simula `coletar_por_data`: o SIAFE devolve o status atual e a ingestão substitui a linha."""
    async def coletar(ex, data):
        c = sqlite3.connect(db)
        for num, ug, st in novos.get(data, []):
            c.execute("UPDATE ob_orcamentaria_siafe SET status_envio=? WHERE numero_ob=? AND ug_emitente=?",
                      (st, num, ug))
        c.commit()
        c.close()
        return {"ok": True, "data": data}
    return coletar


def test_recoleta_registra_transicoes_e_conta_as_devolvidas(tmp_path):
    db = tmp_path / "c.db"
    _base(db)
    col = _coletor(db, {"02/09/2026": [("2026OB00002", "100100", "Erro no Pagamento"),
                                       ("2026OB00003", "100100", "Processado e Pago")],
                        "01/09/2026": [("2026OB00001", "100100", "Processado e Pago")]})
    r = asyncio.run(S.recoletar(2026, db=db, agora=AGORA, _coletar_dia=col))
    assert r["viraram_erro_no_pagamento"] == 1
    d = {x["data"]: x for x in r["dias"]}
    assert d["02/09/2026"]["transicoes"] == {"Erro no Pagamento": 1, "Processado e Pago": 1}
    assert d["02/09/2026"]["intermed_depois"] == 0 and d["01/09/2026"]["intermed_depois"] == 1   # 200200 segue
    assert S.fila(2026, db=db, agora=AGORA) == []                       # recolhidos agora: fora até o refresco


def test_dia_sem_mudanca_espera_o_dobro_para_voltar(tmp_path):
    db = tmp_path / "c.db"
    _base(db)
    col = _coletor(db, {})
    asyncio.run(S.recoletar(2026, db=db, agora=AGORA, _coletar_dia=col))
    asyncio.run(S.recoletar(2026, db=db, agora=AGORA, _coletar_dia=col))     # fila vazia: nada recolhido de novo
    sem = sqlite3.connect(db).execute("SELECT sem_mudanca FROM ob_status_recoleta WHERE data_emissao='02/09/2026'"
                                      ).fetchone()[0]
    assert sem == 1
    assert [S.espera_dias(n) for n in range(6)] == [3, 6, 12, 24, 24, 24]


def test_falha_da_coleta_nao_conta_como_sem_mudanca_e_prazo_para_entre_dias(tmp_path):
    db = tmp_path / "c.db"
    _base(db)

    async def ocupado(ex, data):
        raise TimeoutError("browser_lock")
    r = asyncio.run(S.recoletar(2026, db=db, agora=AGORA, _coletar_dia=ocupado))
    assert all(x["erro"] == "navegador_ocupado" for x in r["dias"])
    assert len(S.fila(2026, db=db, agora=AGORA)) == 2                 # voltam na próxima passada
    r = asyncio.run(S.recoletar(2026, db=db, prazo=100.0, agora=AGORA, _coletar_dia=ocupado, _relogio=lambda: 101.0))
    assert r["dias"] == [{"data": "02/09/2026", "exercicio": 2026, "pulado": "prazo"}]


def test_ob_que_sumiu_da_tabela_nao_vira_pago(tmp_path):
    db = tmp_path / "c.db"
    _base(db)

    async def apaga(ex, data):
        c = sqlite3.connect(db)
        c.execute("DELETE FROM ob_orcamentaria_siafe WHERE numero_ob='2026OB00002'")
        c.commit()
        c.close()
        return {"ok": True}
    r = asyncio.run(S.recoletar(2026, db=db, max_dias=1, agora=AGORA, _coletar_dia=apaga))
    assert r["dias"][0]["transicoes"] == {"nao_reencontrada": 1, "Aguardando Envio": 1}


# ── releitura ampliada (19/11/2026): vários exercícios, não final amplo, consolidação, parada no login ──────────

def _base_ampla(db):
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE ob_orcamentaria_siafe(numero_ob,ug_emitente,exercicio,data_emissao,status,valor,"
              "status_envio,coletado_em, PRIMARY KEY (numero_ob, ug_emitente, exercicio))")
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?)", [
        ("2026OB00010", "100100", 2026, "05/09/2026", "Não contabilizado", 300.0, "Aguardando Geração RE",
         "2026-09-05 10:00:00"),
        ("2026OB00011", "100100", 2026, "06/09/2026", "Contabilizado", 200.0, "", "2026-09-06 10:00:00"),
        ("2024OB00001", "100100", 2024, "10/03/2024", "Contabilizado", 5_000.0, "Enviado ao Banco",
         "2026-08-11 10:00:00"),
        # consolidação: dia de 25/10 com tudo final, mas a foto é de 26/10 (1 dia depois) — relê uma vez
        ("2026OB00020", "100100", 2026, "25/10/2026", "Contabilizado", 700.0, "Processado e Pago",
         "2026-10-26 08:00:00"),
        # dia de 20/10 com foto tirada 30 dias depois: já consolidado
        ("2026OB00021", "100100", 2026, "20/09/2026", "Contabilizado", 900.0, "Processado e Pago",
         "2026-10-25 08:00:00"),
    ])
    c.commit()
    c.close()


def test_nao_final_inclui_nao_contabilizado_e_envio_vazio(tmp_path):
    db = tmp_path / "c.db"
    _base_ampla(db)
    assert {d["data"] for d in S.fila(2026, db=db, agora=AGORA)} == {"05/09/2026", "06/09/2026"}


def test_fila_varios_junta_exercicios_por_valor_e_consolida_depois(tmp_path):
    db = tmp_path / "c.db"
    _base_ampla(db)
    f = S.fila_varios((2026, 2025, 2024), db=db, agora=AGORA)
    assert [(d["exercicio"], d["data"], d["motivo"]) for d in f] == [
        (2024, "10/03/2024", "nao_final"), (2026, "05/09/2026", "nao_final"), (2026, "06/09/2026", "nao_final"),
        (2026, "25/10/2026", "consolidacao")]


def test_consolidacao_conta_so_quem_mudou_e_sai_da_fila(tmp_path):
    db = tmp_path / "c.db"
    _base_ampla(db)

    async def devolve(ex, data):
        c = sqlite3.connect(db)
        c.execute("UPDATE ob_orcamentaria_siafe SET status_envio='Erro no Pagamento', coletado_em='2026-11-13 05:30:00'"
                  " WHERE data_emissao=?", (data,))
        c.commit()
        c.close()
        return {"ok": True}
    dias = [d for d in S.fila_varios((2026,), db=db, agora=AGORA) if d["motivo"] == "consolidacao"]
    r = asyncio.run(S._recoletar_dias(dias, db=db, _coletar_dia=devolve))
    assert r["dias"][0]["transicoes"] == {"Processado e Pago→Erro no Pagamento": 1}
    assert r["viraram_erro_no_pagamento"] == 1 and r["ob_que_mudaram"] == 1
    assert not [d for d in S.fila_varios((2026,), db=db, agora=AGORA) if d["motivo"] == "consolidacao"]


def test_releitura_pela_ingestao_real_nao_duplica_linha(tmp_path, monkeypatch):
    """A releitura grava pela ingestão canônica (INSERT OR REPLACE na PK numero_ob+ug_emitente+exercicio): o mesmo
    dia relido com o status novo SUBSTITUI a linha — nunca soma uma segunda."""
    from compliance_agent import siafe_ob_orcamentaria as M
    db = tmp_path / "c.db"
    monkeypatch.setattr(M, "_DB", db)
    cab = ["Número", "UG Emitente", "Data Emissão", "Status", "Credor", "Valor", "Status de Envio"]
    M.ingerir(2026, cab, [["2026OB00001", "100100", "02/09/2026", "Contabilizado", "11111111000101", "1.000,00",
                           "Enviado ao Banco"]])
    M.ingerir(2026, cab, [["2026OB00001", "100100", "02/09/2026", "Contabilizado", "11111111000101", "1.000,00",
                           "Erro no Pagamento"]])
    linhas = sqlite3.connect(db).execute("SELECT status_envio FROM ob_orcamentaria_siafe").fetchall()
    assert linhas == [("Erro no Pagamento",)]


def test_para_no_primeiro_login_que_falha(tmp_path):
    db = tmp_path / "c.db"
    _base(db)
    chamadas = []

    async def mfa(ex, data):
        chamadas.append(data)
        return {"ok": False, "etapa": "login_nav", "erro": "mfa_sem_codigo"}
    r = asyncio.run(S.recoletar(2026, db=db, agora=AGORA, _coletar_dia=mfa))
    assert chamadas == ["02/09/2026"] and r["ok"] is False and r["parou"] == "mfa_sem_codigo"


def test_rodar_nao_entra_na_janela_do_diario_e_prazo_para_antes_dela(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "ESTADO", tmp_path / "estado.json")
    r = S.rodar(agora=datetime(2026, 11, 19, 5, 10))
    assert "janela do diário" in r["pulado"] and (tmp_path / "estado.json").exists()
    assert S.prazo_fora_da_janela(datetime(2026, 11, 19, 3, 30), 80) == datetime(2026, 11, 19, 4, 0)
    assert S.prazo_fora_da_janela(datetime(2026, 11, 19, 14, 0), 80) == datetime(2026, 11, 19, 15, 20)
