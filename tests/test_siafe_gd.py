# -*- coding: utf-8 -*-
"""Guia de Devolução (GD) do SIAFE-Rio: parser da grade, tabela própria, vínculo com a OB e fila por valor.

Dados sintéticos (repositório público): números, UGs e valores inventados."""
import asyncio
import sqlite3
from datetime import datetime

from compliance_agent import siafe_documento as N
from compliance_agent import siafe_gd as G

_HEADER = ["Número", "UG Emitente", "Data Emissão", "Tipo de Baixa", "Status", "Cód. UG Liquidante", "OB", "Valor"]


def _gd(num="2026GD00007", ug="700700", ob="2026OB00201", valor="20.000,00", status="Contabilizado"):
    return [num, ug, "03/02/2026", "Devolução", status, ug, ob, valor]


def test_tela_gd_fica_na_execucao_financeira_com_grade_propria():
    t = N.TIPOS["GD"]
    assert t["tela"] == "Guia de Devolução" and t["menu"] == "Execução Financeira"
    assert t["tbl"] == "pt1:tblGuiaDevolucao" and N._tbl(t) == "pt1:tblGuiaDevolucao"
    assert N._tbl(N.TIPOS["NE"]) == N.TBL                         # NE/NL seguem na grade de sempre


def test_ingere_gd_pelo_nome_do_cabecalho(tmp_path):
    db = tmp_path / "c.db"
    r = N.ingerir(2026, _HEADER, [_gd(), ["Total", "", ""]], db=db, tipo="GD")
    assert r["ok"] and r["ingeridas"] == 1
    row = sqlite3.connect(db).execute("SELECT numero, ug_emitente, ano_gd, data_emissao, tipo_baixa, status, "
                                      "ug_liquidante, ob, valor FROM gd_siafe").fetchone()
    assert row == ("2026GD00007", "700700", 2026, "03/02/2026", "Devolução", "Contabilizado", "700700",
                   "2026OB00201", 20000.0)


def test_ordem_das_colunas_diferente_nao_desloca_o_valor(tmp_path):
    db = tmp_path / "c.db"
    ordem = list(range(len(_HEADER)))[::-1]
    N.ingerir(2026, [_HEADER[i] for i in ordem], [[_gd()[i] for i in ordem]], db=db, tipo="GD")
    assert sqlite3.connect(db).execute("SELECT ob, valor FROM gd_siafe").fetchone() == ("2026OB00201", 20000.0)


def test_numero_de_ob_nao_entra_como_gd(tmp_path):
    r = N.ingerir(2026, _HEADER, [_gd(num="2026OB00201")], db=tmp_path / "c.db", tipo="GD")
    assert r["ingeridas"] == 0


def test_mesmo_numero_de_gd_em_duas_ugs_nao_se_apaga_e_migracao_e_idempotente(tmp_path):
    db = tmp_path / "c.db"
    for _ in range(2):                                            # rodar de novo não duplica nem quebra
        N.ingerir(2026, _HEADER, [_gd(ug="700700"), _gd(ug="800800")], db=db, tipo="GD")
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM gd_siafe").fetchone()[0] == 2
    ddl = con.execute("SELECT sql FROM sqlite_master WHERE name='gd_siafe'").fetchone()[0]
    assert "PRIMARY KEY (numero, ug_emitente, exercicio)" in ddl


def test_devolvido_soma_por_ob_e_ug_e_ignora_guia_cancelada(tmp_path):
    db = tmp_path / "c.db"
    N.ingerir(2026, _HEADER, [
        _gd("2026GD00001", "700700", "2026OB00201", "15.000,00"),
        _gd("2026GD00002", "700700", "2026OB00201", "5.000,00"),          # duas guias para a mesma OB
        _gd("2026GD00003", "700700", "2026OB00201", "9.999,00", "Cancelado"),
        _gd("2026GD00001", "800800", "2026OB00201", "1.000,00"),          # mesma OB, OUTRA UG
    ], db=db, tipo="GD")
    dev = G.devolvido_por_ob(sqlite3.connect(db))
    assert dev == {("2026OB00201", "700700"): 20000.0, ("2026OB00201", "800800"): 1000.0}


def test_sem_tabela_de_gd_nada_e_conhecido(tmp_path):
    assert G.devolvido_por_ob(sqlite3.connect(tmp_path / "vazio.db")) == {}


def _base_ob(db):
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE ob_orcamentaria_siafe(numero_ob,ug_emitente,exercicio,status,valor,gd,status_envio)")
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,2026,'Contabilizado',?,?,?)", [
        ("2026OB00001", "111111", 9_000_000.0, "", "Processado e Pago"),        # maior pago, sem GD
        ("2026OB00002", "222222", 50_000.0, "2026GD00001", "Parcialmente Pago"),  # GD sem valor conhecido
        ("2026OB00003", "333333", 800_000.0, "2026GD00001", "Erro no Pagamento"),  # integral: já se sabe
        ("2026OB00004", "222222", 10.0, "", "Processado e Pago"),
    ])
    c.commit()
    c.close()


def test_fila_comeca_pela_ug_com_gd_sem_valor_apurado(tmp_path):
    db = tmp_path / "c.db"
    _base_ob(db)
    assert G.fila_gd(2026, db=db, max_ugs=3, agora=datetime(2026, 11, 13)) == ["222222", "111111", "333333"]


def test_fila_pula_ug_completa_e_fresca(tmp_path):
    db = tmp_path / "c.db"
    _base_ob(db)
    N.registrar_cobertura("GD", "222222", 2026, True, 3, db=db)
    assert G.fila_gd(2026, db=db, max_ugs=1)[0] == "111111"


def test_gd_so_e_completa_se_cobre_as_guias_que_as_ob_citam(tmp_path):
    db = tmp_path / "c.db"
    _base_ob(db)
    assert N.cobertura_gd_pela_ob("222222", 2026, db=db) == 0.0
    N.ingerir(2026, _HEADER, [_gd("2026GD00001", "222222", "2026OB00002")], db=db, tipo="GD")
    assert N.cobertura_gd_pela_ob("222222", 2026, db=db) == 1.0
    assert N.cobertura_gd_pela_ob("111111", 2026, db=db) is None           # nenhuma OB cita GD: nada a conferir


def test_coleta_da_fila_registra_cobertura_e_para_no_prazo(tmp_path, monkeypatch):
    db = tmp_path / "c.db"
    _base_ob(db)
    chamadas = []

    async def coletar(ug, ex, tipo, ate):
        chamadas.append((ug, tipo))
        return {"ok": True, "colhidas": 0, "capou": False}
    r = asyncio.run(G.coletar_fila(2026, max_ugs=3, db=db, _coletar=coletar))
    assert chamadas == [("222222", "GD"), ("111111", "GD"), ("333333", "GD")]
    porque = {u["ug"]: u["completo"] for u in r["ugs"]}
    assert porque == {"222222": False, "111111": True, "333333": False}   # 0 de 1 guia citada ≠ completa
    monkeypatch.setattr(N, "_passou", lambda ate: ate == "2026-11-13T05:50")
    r = asyncio.run(G.coletar_fila(2026, max_ugs=3, ate="2026-11-13T05:50", db=db, _coletar=coletar))
    assert r["ugs"][0].get("pulada") == "prazo" and len(chamadas) == 3
