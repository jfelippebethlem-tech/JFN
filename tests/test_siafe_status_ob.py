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
    assert f[0] == {"data": "02/09/2026", "n": 2, "valor": 900_005.0}
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
    r = asyncio.run(S.recoletar(2026, db=db, _coletar_dia=col))
    assert r["viraram_erro_no_pagamento"] == 1
    d = {x["data"]: x for x in r["dias"]}
    assert d["02/09/2026"]["transicoes"] == {"Erro no Pagamento": 1, "Processado e Pago": 1}
    assert d["02/09/2026"]["intermed_depois"] == 0 and d["01/09/2026"]["intermed_depois"] == 1   # 200200 segue
    assert S.fila(2026, db=db, agora=datetime.now()) == []              # recolhidos agora: fora até o refresco


def test_dia_sem_mudanca_espera_o_dobro_para_voltar(tmp_path):
    db = tmp_path / "c.db"
    _base(db)
    col = _coletor(db, {})
    asyncio.run(S.recoletar(2026, db=db, _coletar_dia=col))
    asyncio.run(S.recoletar(2026, db=db, _coletar_dia=col))     # fila vazia: nada recolhido de novo
    sem = sqlite3.connect(db).execute("SELECT sem_mudanca FROM ob_status_recoleta WHERE data_emissao='02/09/2026'"
                                      ).fetchone()[0]
    assert sem == 1
    assert [S.espera_dias(n) for n in range(6)] == [3, 6, 12, 24, 24, 24]


def test_falha_da_coleta_nao_conta_como_sem_mudanca_e_prazo_para_entre_dias(tmp_path):
    db = tmp_path / "c.db"
    _base(db)

    async def ocupado(ex, data):
        raise TimeoutError("browser_lock")
    r = asyncio.run(S.recoletar(2026, db=db, _coletar_dia=ocupado))
    assert all(x["erro"] == "navegador_ocupado" for x in r["dias"])
    assert len(S.fila(2026, db=db, agora=AGORA)) == 2                 # voltam na próxima passada
    r = asyncio.run(S.recoletar(2026, db=db, prazo=100.0, _coletar_dia=ocupado, _relogio=lambda: 101.0))
    assert r["dias"] == [{"data": "02/09/2026", "pulado": "prazo"}]


def test_ob_que_sumiu_da_tabela_nao_vira_pago(tmp_path):
    db = tmp_path / "c.db"
    _base(db)

    async def apaga(ex, data):
        c = sqlite3.connect(db)
        c.execute("DELETE FROM ob_orcamentaria_siafe WHERE numero_ob='2026OB00002'")
        c.commit()
        c.close()
        return {"ok": True}
    r = asyncio.run(S.recoletar(2026, db=db, max_dias=1, _coletar_dia=apaga))
    assert r["dias"][0]["transicoes"] == {"nao_reencontrada": 1, "Aguardando Envio": 1}
