# -*- coding: utf-8 -*-
"""Propagação automática (compliance_agent/propagacao.py): o mapa é são, a fonte que muda suja quem depende dela,
o despachante só limpa com EFEITO medido, e o painel vence o cache pela marca do despachante. Tudo em `tmp_path`."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import time
from pathlib import Path

import pytest

from compliance_agent import propagacao as P

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture()
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DATA", tmp_path)
    c = P.conectar(tmp_path / "p.db")
    yield c
    c.close()


def _cfg(**ders):
    return {"fontes": {"f": {"nome": "Fonte", "sonda": {}}, "g": {"nome": "Outra", "sonda": {}}},
            "derivados": ders, "cerebro": []}


def _der(depende, **kw):
    return dict({"nome": "D", "depende": depende, "comando": ["true"], "debounce_s": 0}, **kw)


# ───────────── o mapa real ─────────────
def test_mapa_de_producao_e_valido_e_sem_ciclo():
    cfg = P.carregar(RAIZ / "config" / "propagacao.yaml")
    assert P.validar(cfg) == []
    assert len(cfg["derivados"]) >= 10 and len(cfg["fontes"]) >= 15


def test_todo_comando_do_mapa_existe_no_repositorio():
    """Derivado que aponta para módulo/arquivo que não existe falharia calado a cada evento."""
    for did, d in P.carregar(RAIZ / "config" / "propagacao.yaml")["derivados"].items():
        if d.get("tipo") == "cache":
            continue
        argv = d["comando"]
        if "-m" in argv:
            assert importlib.util.find_spec(argv[argv.index("-m") + 1]) is not None, did
        else:
            assert (RAIZ / argv[1]).exists(), did


# 24/11/2026 (dono: "sim, dentro do ritmo"): fila de LLM entra no grafo SÓ pelo guarda de ritmo da assinatura
_LLM = ("lex_execucao", "fila_analise_sei.sh", "triagem_alertas", "conferencia_opus", "sei_ficha_acervo")


def test_comandos_do_mapa_so_chamam_llm_pelo_guarda_de_ritmo():
    """A leitura por modelo do vínculo (Batch API) e o juiz seguem fora; fila de LLM só com `ritmo:` declarado."""
    for did, d in P.carregar(RAIZ / "config" / "propagacao.yaml")["derivados"].items():
        linha = " ".join(d.get("comando", []))
        assert " modelo" not in linha and "juiz" not in linha and "api-" not in linha, did
        if any(x in linha for x in _LLM):
            assert d.get("ritmo"), f"{did} chama LLM sem o guarda `ritmo:`"


def test_ritmo_negado_o_derivado_espera_e_liberado_roda(con):
    cfg = _cfg(lex=_der(["f"], ritmo="lex_execucao"), outro=_der(["f"]))
    P.emitir(con, cfg, "f", "processo capturado")
    pedidos = []
    nega = lambda t: pedidos.append(t) or "ritmo semanal da assinatura — 38% acima do ritmo (37%)"  # noqa: E731
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None), ritmo=nega)
    ids = [x["id"] for x in feitos]
    assert "outro" in ids and "lex" not in ids and set(pedidos) == {"lex_execucao"}     # controle: sem ritmo anda
    assert con.execute("SELECT adiado FROM derivado WHERE id='lex'").fetchone()[0].startswith("ritmo: ritmo semanal")
    assert "lex" in P._sujos(con)                                                   # a pendência espera
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None), ritmo=lambda t: None)
    assert "lex" in [x["id"] for x in feitos] and "lex" not in P._sujos(con)


def test_guarda_de_ritmo_ilegivel_fecha_a_porta(monkeypatch):
    from compliance_agent.llm import contingencia

    def quebra(_t):
        raise ValueError("arquivo ilegível")
    monkeypatch.setattr(contingencia, "motivo_bloqueio", quebra)
    assert P._motivo_ritmo("lex_execucao").startswith("guarda de ritmo ilegível")
    monkeypatch.setattr(contingencia, "motivo_bloqueio", lambda t: None)
    assert P._motivo_ritmo("lex_execucao") is None


def test_teto_do_vinculo_ob_contrato_tem_folga_sobre_a_rodada_medida():
    """21/11/2026: `regra --gravar` relê todo o acervo dos processos de pagamento (5.030 processos, ~0,75 MB de texto
    cada, sob `nice 15`). A maior rodada que TERMINOU levou 1.796 s (execução 213 de data/propagacao.db) com teto de
    1.800 s; 12 das 25 últimas estouraram o teto e não gravaram nada. Teto com folga de 1,5× sobre a rodada medida e
    abaixo do intervalo mínimo (duas rodadas nunca se sobrepõem)."""
    d = P.carregar(RAIZ / "config" / "propagacao.yaml")["derivados"]["vinculo_ob_contrato"]
    maior_rodada_ok_s = 1796
    assert int(d["timeout_s"]) >= 1.5 * maior_rodada_ok_s
    assert int(d["timeout_s"]) < int(d["intervalo_min_s"])


def test_validar_acusa_ciclo_e_dependencia_inexistente():
    erros = P.validar(_cfg(a=_der(["b"]), b=_der(["a"]), c=_der(["nao_existe"]), d=_der([])))
    assert any("ciclo" in e for e in erros)
    assert any("nao_existe" in e for e in erros)
    assert any("nunca ficaria sujo" in e for e in erros)


# ───────────── sondas ─────────────
def test_sonda_sql_primeira_leitura_e_linha_de_base_depois_evento(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "RAIZ", tmp_path)
    db = sqlite3.connect(tmp_path / "x.db")
    db.execute("CREATE TABLE t(a)")
    db.execute("INSERT INTO t VALUES (1)")
    db.commit()
    s = {"db": "x.db", "sql": "SELECT MAX(rowid) FROM t", "unidade": "OB(s)"}
    base, ev = P._sonda_sql(s, None)
    assert ev == []                                    # controle negativo: 1ª leitura nunca é evento
    assert P._sonda_sql(s, base)[1] == []              # controle negativo: nada mudou
    db.executemany("INSERT INTO t VALUES (?)", [(2,), (3,)])
    db.commit()
    assert P._sonda_sql(s, base)[1] == ["+2 OB(s)"]    # controle positivo


def test_sonda_sql_que_falha_levanta_e_nao_vira_sem_mudanca(tmp_path, monkeypatch, con):
    monkeypatch.setattr(P, "RAIZ", tmp_path)
    sqlite3.connect(tmp_path / "x.db").close()
    cfg = {"fontes": {"f": {"nome": "F", "sonda": {"db": "x.db", "sql": "SELECT 1 FROM nao_existe"}}},
           "derivados": {"d": _der(["f"])}, "cerebro": []}
    assert P.sondar(con, cfg) == 0
    erro = con.execute("SELECT erro FROM sonda WHERE fonte='f'").fetchone()[0]
    assert "nao_existe" in erro                        # INDISPONÍVEL declarado


def test_sonda_log_so_linhas_novas_inteiras_e_com_minimo(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "RAIZ", tmp_path)
    log = tmp_path / "l.log"
    log.write_text("LOTE a (sweep): 9 aprovado(s), 0 em quarentena\n")
    s = {"log": "l.log", "regex": r"LOTE (\S+) \((\w+)\): (\d+) aprovado", "minimo": [3, 1], "texto": "lote {1}: {3}"}
    pos, ev = P._sonda_log(s, None)
    assert ev == []                                    # o que já estava no log não é evento
    with log.open("a") as f:
        f.write("LOTE b (integras): 0 aprovado(s), 0 em quarentena\nLOTE c (sweep): 2 aprovado(s), 1 em q\nLOTE d (sweep): 5 aprov")
    pos2, ev = P._sonda_log(s, pos)
    assert ev == ["lote c: 2"]                         # zero aprovados não conta; linha pela metade espera
    with log.open("a") as f:
        f.write("ado(s)\n")
    assert P._sonda_log(s, pos2)[1] == ["lote d: 5"]


def test_status_siafe_vem_da_tabela_e_soma_as_transicoes(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "RAIZ", tmp_path)
    db = sqlite3.connect(tmp_path / "x.db")
    db.execute("CREATE TABLE ob_status_recoleta(data_emissao, recoletado_em, sem_mudanca, transicoes)")
    db.execute("INSERT INTO ob_status_recoleta VALUES ('01/09/2026', '2026-11-13T05:00:00', 0, 'Erro no Pagamento=5')")
    db.commit()
    s = {"db": "x.db", "sql": "SELECT COALESCE(MAX(recoletado_em), ''), COUNT(*) FROM ob_status_recoleta",
         "detalhe": "SELECT data_emissao, transicoes FROM ob_status_recoleta WHERE recoletado_em > ? AND sem_mudanca = 0",
         "extrator": "siafe_status"}
    base, ev = P._sonda_sql(s, None)
    assert ev == []
    db.executemany("INSERT INTO ob_status_recoleta VALUES (?,?,?,?)", [
        ("29/09/2026", "2026-11-14T05:21:57", 0, "Enviado ao Banco=2;Erro no Pagamento=1;Processado e Pago=939"),
        ("29/10/2026", "2026-11-14T05:29:53", 0, "Erro no Pagamento=68;Parcialmente Pago=7")])
    db.commit()
    nova, ev = P._sonda_sql(s, base)
    assert len(ev) == 1 and "em 2 dia(s)" in ev[0]     # só o que foi recoletado DEPOIS da leitura anterior
    assert "939 → Processado e Pago" in ev[0] and "69 → Erro no Pagamento" in ev[0] and "Enviado ao Banco" not in ev[0]
    db.execute("INSERT INTO ob_status_recoleta VALUES ('30/10/2026', '2026-11-14T06:00:00', 0, 'Enviado ao Banco=4')")
    db.commit()
    assert P._sonda_sql(s, nova)[1] == []              # controle negativo: nenhum status saiu do intermediário


def test_sonda_pasta_lista_so_os_arquivos_mais_novos(tmp_path):
    (tmp_path / "a.md").write_text("x")
    base, ev = P._sonda_pasta({"pasta": str(tmp_path), "glob": "*.md"}, None)
    assert ev == []
    time.sleep(0.02)
    (tmp_path / "b.md").write_text("y")
    assert P._sonda_pasta({"pasta": str(tmp_path), "glob": "*.md"}, base)[1] == ["b.md"]


# ───────────── sujo → recálculo ─────────────
def test_evento_suja_so_quem_depende_e_recalculo_limpa(con):
    cfg = _cfg(a=_der(["f"]), b=_der(["g"]))
    P.emitir(con, cfg, "f", "mudou")
    assert set(P._sujos(con)) == {"a"}
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda did, d: (True, None))
    assert [x["id"] for x in feitos] == ["a"]
    assert P._sujos(con) == {}


def test_cascata_derivado_recalculado_suja_o_dependente_no_mesmo_ciclo(con):
    cfg = _cfg(a=_der(["f"], debounce_s=0), b=_der(["a"], debounce_s=9999))
    P.emitir(con, cfg, "f", "mudou")
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda did, d: (True, None))
    assert [x["id"] for x in feitos] == ["a", "b"]     # o evento do derivado não abre janela de junção


def test_janela_de_juncao_conta_do_primeiro_evento_e_fonte_que_nao_para_nao_adia(con):
    cfg = _cfg(a=_der(["f"], debounce_s=600))
    P.emitir(con, cfg, "f", "agora")
    assert P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None)) == []
    assert con.execute("SELECT adiado FROM derivado WHERE id='a'").fetchone()[0] == "juntando eventos da fonte"
    con.execute("UPDATE evento SET quando = quando - 700")          # o 1º evento já tem 700 s…
    con.commit()
    P.emitir(con, cfg, "f", "a fonte segue emitindo")              # …e chega outro agora: não reabre a janela
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None))
    assert [x["id"] for x in feitos] == ["a"] and P._sujos(con) == {}   # um recálculo cobre os dois eventos


def test_falha_mantem_sujo_registra_erro_e_recua(con):
    cfg = _cfg(a=_der(["f"]))
    P.emitir(con, cfg, "f", "mudou")
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (False, "quebrou"))
    assert feitos[0]["ok"] is False
    assert "a" in P._sujos(con)                        # continua sujo: nada foi dado por recalculado
    est, erro, falhas, prox = con.execute(
        "SELECT ultimo_estado, ultimo_erro, falhas, proxima_tentativa FROM derivado WHERE id='a'").fetchone()
    assert (est, erro, falhas) == ("falhou", "quebrou", 1) and prox > time.time() + 1000
    assert P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None)) == []   # em recuo


def test_evento_que_chega_durante_o_calculo_nao_se_perde(con):
    cfg = _cfg(a=_der(["f"]))
    P.emitir(con, cfg, "f", "primeiro")

    def rodar(did, d):
        P.emitir(con, cfg, "f", "chegou no meio")
        return True, None
    P.despachar(con, cfg, carga=lambda: (0.0,), executar=rodar)
    assert P._sujos(con)["a"]["n"] == 1                # o evento do meio segue pendente


def test_um_pesado_por_ciclo_e_carga_alta_adia(con):
    cfg = _cfg(a=_der(["f"], peso="pesado", prioridade=1), b=_der(["f"], peso="pesado", prioridade=2), c=_der(["f"]))
    P.emitir(con, cfg, "f", "mudou")
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None))
    assert [x["id"] for x in feitos] == ["a", "c"]
    assert con.execute("SELECT adiado FROM derivado WHERE id='b'").fetchone()[0] == "um pesado por ciclo"
    feitos = P.despachar(con, cfg, carga=lambda: (9.5,), executar=lambda *_: (True, None))
    assert feitos == [] and "carga" in con.execute("SELECT adiado FROM derivado WHERE id='b'").fetchone()[0]


def test_pesado_respeita_o_semaforo_unico_da_vm1(con, tmp_path):
    """23/11/2026: 5 pesados ao mesmo tempo com swap 100% — o despachante e os crons pesados (`tools/pesado.sh`)
    passam a dividir UMA trava (`locks/pesado_vm1.lock`): ocupada por um cron, o derivado pesado espera; o leve não.
    Enquanto roda, o derivado pesado segura a trava (um cron pesado que chegar espera)."""
    import fcntl
    cfg = _cfg(a=_der(["f"], peso="pesado"), c=_der(["f"]))
    P.emitir(con, cfg, "f", "mudou")
    (tmp_path / "locks").mkdir(exist_ok=True)
    cron = open(tmp_path / "locks" / "pesado_vm1.lock", "w")
    fcntl.flock(cron, fcntl.LOCK_EX | fcntl.LOCK_NB)                  # um cron pesado está rodando
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None))
    assert [x["id"] for x in feitos] == ["c"]
    assert "semáforo" in con.execute("SELECT adiado FROM derivado WHERE id='a'").fetchone()[0]
    fcntl.flock(cron, fcntl.LOCK_UN)
    cron.close()

    def rodar(did, d):
        if did == "a":                                                  # durante o pesado, a trava está tomada
            with open(tmp_path / "locks" / "pesado_vm1.lock", "w") as fh:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True, None
    assert [x["id"] for x in P.despachar(con, cfg, carga=lambda: (0.0,), executar=rodar)] == ["a"]
    with open(tmp_path / "locks" / "pesado_vm1.lock", "w") as fh:     # e foi solta no fim
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_derivado_espera_o_de_que_depende_quando_esse_esta_pronto(con):
    cfg = _cfg(x=_der(["f"], peso="pesado", prioridade=0), a=_der(["f"], peso="pesado", prioridade=1), b=_der(["f", "a"]))
    P.emitir(con, cfg, "f", "mudou")
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None))
    assert [x["id"] for x in feitos] == ["x"]          # `a` ficou para o próximo ciclo (um pesado por ciclo)…
    assert con.execute("SELECT adiado FROM derivado WHERE id='b'").fetchone()[0] == "aguardando derivado de que depende"


def test_derivado_nao_espera_o_de_que_depende_se_esse_ainda_junta_eventos(con):
    """O vínculo junta lotes SEI por 30 min; a perícia não fica esse tempo sem a correção que já chegou."""
    cfg = _cfg(a=_der(["f"], debounce_s=9999), b=_der(["f", "a"]))
    P.emitir(con, cfg, "f", "mudou")
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None))
    assert [x["id"] for x in feitos] == ["b"] and "a" in P._sujos(con)


def test_rodada_fora_do_despachante_conta_no_intervalo_minimo(con, tmp_path, monkeypatch):
    """O cron diário da gestão Couto (rede) regrava o arquivo de efeito: o despachante não roda de novo logo depois."""
    import os
    monkeypatch.setattr(P, "RAIZ", tmp_path)
    (tmp_path / "saida.json").write_text("{}")
    cfg = _cfg(a=_der(["f"], intervalo_min_s=3600, efeito={"arquivo": "saida.json"}))
    P.emitir(con, cfg, "f", "mudou")
    assert P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None)) == []   # arquivo novo
    assert con.execute("SELECT adiado FROM derivado WHERE id='a'").fetchone()[0] == "intervalo mínimo entre execuções"
    os.utime(tmp_path / "saida.json", (time.time() - 4000, time.time() - 4000))
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None))
    assert [x["id"] for x in feitos] == ["a"]          # controle positivo: arquivo velho não segura


def test_comando_que_roda_sem_regravar_o_arquivo_e_falha(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "RAIZ", tmp_path)
    monkeypatch.setattr(P, "DATA", tmp_path)
    alvo = tmp_path / "saida.json"
    alvo.write_text("{}")
    import os
    os.utime(alvo, (time.time() - 500, time.time() - 500))
    ok, erro = P._rodar_comando("x", {"comando": ["true"], "efeito": {"arquivo": "saida.json"}})
    assert ok is False and "sem efeito" in erro        # controle negativo: rc 0 não basta
    ok, erro = P._rodar_comando("x", {"comando": ["touch", str(alvo)], "efeito": {"arquivo": "saida.json"}})
    assert ok is True and erro is None                 # controle positivo
    ok, erro = P._rodar_comando("x", {"comando": ["false"]})
    assert ok is False and "código 1" in erro


# ───────────── painel ─────────────
def test_estado_sem_base_e_indisponivel_nunca_tudo_em_dia(tmp_path):
    d = P.estado(_cfg(a=_der(["f"])), db=tmp_path / "nao_existe.db")
    assert d["ok"] is False and d["estado"] == "INDISPONIVEL" and "derivados" not in d


def test_estado_mostra_sujo_falha_e_despachante_parado(con, tmp_path):
    cfg = _cfg(a=_der(["f"]), b=_der(["g"]))
    P.emitir(con, cfg, "f", "OB nova")
    P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (False, "quebrou"))
    d = P.estado(cfg, db=tmp_path / "p.db")
    assert d["estado"] == "PARADO"                     # nenhum ciclo completo registrado
    a = next(x for x in d["derivados"] if x["id"] == "a")
    assert a["sujo"] and a["ultimo_estado"] == "falhou" and a["ultimo_erro"] == "quebrou" and a["motivos"] == ["f: OB nova"]
    assert d["resumo"] == {"derivados": 2, "sujos": 1, "atrasados": 0, "com_falha": 1, "fontes": 2, "fontes_com_erro": 0}
    json.dumps(d)                                      # serializável para a rota


# ───────────── SLO (24/11/2026: "ok" com 24 de 36 sujos, 17 há mais de 2 h) ─────────────
def _ciclo_vivo(con):
    con.execute("INSERT OR REPLACE INTO meta(k, v) VALUES ('ultimo_ciclo', ?)",
                (json.dumps({"quando": time.time(), "segundos": 1, "eventos": 0, "feitos": []}),))
    con.commit()


def test_slo_padrao_e_duas_horas_alem_do_intervalo_e_frescor_declarado_vence():
    assert P.slo_s({}) == 7200
    assert P.slo_s({"intervalo_min_s": 86400}) == 86400 + 7200        # esperar o intervalo por desenho não é atraso
    assert P.slo_s({"intervalo_min_s": 86400, "frescor_max_s": 90000}) == 90000
    assert P.slo_s({}, {"slo_padrao_s": 600}) == 600
    erros = P.validar(_cfg(a=_der(["f"], intervalo_min_s=7200, frescor_max_s=3600)))
    assert erros == ["a: frescor_max_s menor que intervalo_min_s (ficaria ATRASADO por desenho)"]


def test_estado_atrasado_lista_quem_passou_do_slo_mesmo_com_ciclo_vivo(con, tmp_path):
    cfg = _cfg(velho=_der(["f"]), novo=_der(["g"]), espera=_der(["f"], intervalo_min_s=86400))
    P.emitir(con, cfg, "f", "OB nova", quando=time.time() - 3 * 3600)     # 3 h: além do SLO de 2 h
    P.emitir(con, cfg, "g", "contrato", quando=time.time() - 600)        # 10 min: dentro
    con.execute("INSERT INTO derivado(id, adiado) VALUES ('velho', 'semáforo de pesado da VM-1 ocupado')")
    _ciclo_vivo(con)
    d = P.estado(cfg, db=tmp_path / "p.db")
    assert d["estado"] == "ATRASADO" and d["ok"] is True
    assert [a["id"] for a in d["atrasados"]] == ["velho"]                 # 'espera' tem SLO 26 h; 'novo' 10 min
    assert d["atrasados"][0]["sujo_ha_h"] == 3.0 and d["atrasados"][0]["slo_h"] == 2.0
    assert d["atrasados"][0]["adiado"].startswith("semáforo")
    assert d["resumo"]["atrasados"] == 1 and d["resumo"]["sujos"] == 3
    por = {x["id"]: x for x in d["derivados"]}
    assert por["velho"]["atrasado"] and not por["novo"]["atrasado"] and not por["espera"]["atrasado"]
    # controle negativo: tudo dentro do SLO e ciclo vivo = "ok"
    con.execute("DELETE FROM pendencia WHERE derivado='velho'")
    con.commit()
    d = P.estado(cfg, db=tmp_path / "p.db")
    assert d["estado"] == "ok" and d["atrasados"] == []


def test_sensor_da_automelhoria_abre_um_item_por_derivado_atrasado():
    from tools.automelhoria_geral import sensor_propagacao
    est = {"ok": True, "estado": "ATRASADO", "atrasados": [
        {"id": "lentes", "nome": "Lentes", "sujo_ha_h": 27.3, "slo_h": 8.0, "peso": "pesado", "adiado": "carga 22"}]}
    itens = sensor_propagacao(est)
    assert [i["assinatura"] for i in itens] == ["propagacao:atrasado:lentes"]
    assert "27.3 h" in itens[0]["titulo"] and "carga 22" in itens[0]["detalhe"]
    assert [i["assinatura"] for i in sensor_propagacao({"ok": True, "estado": "PARADO", "atrasados": []})] == ["propagacao:parado"]
    assert sensor_propagacao({"ok": True, "estado": "ok", "atrasados": []}) == []
    assert sensor_propagacao({"ok": False, "estado": "INDISPONIVEL"}) == []    # base ausente: nada a medir


def test_marca_do_despachante_vence_o_cache_do_painel(tmp_path, monkeypatch):
    from rotas import investigacao as inv
    monkeypatch.setattr(inv, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(inv, "_INVALIDAR", {"mtime": None, "marcas": {}})
    monkeypatch.setattr(inv, "_cache", {"periodo:ob_siafe:v2": (time.time() - 60, "velho"),
                                        "intel:fenix:60": (time.time() - 60, "fica")})
    assert inv._cache_get("periodo:ob_siafe:v2", 3600) == "velho"      # sem marca: só o TTL
    (tmp_path / "_invalidar.json").write_text(json.dumps({"periodo:ob_siafe": time.time()}))
    assert inv._cache_get("periodo:ob_siafe:v2", 3600) is None         # controle positivo: vencido pela marca
    assert inv._cache_get("intel:fenix:60", 3600) == "fica"            # controle negativo: outro prefixo
    inv._cache["periodo:ob_siafe:v2"] = (time.time() + 1, "novo")
    assert inv._cache_get("periodo:ob_siafe:v2", 3600) == "novo"       # recalculado depois da marca: vale
    (tmp_path / "_invalidar.json").write_text("{lixo")
    assert inv._cache_get("intel:fenix:60", 3600) == "fica"            # marca ilegível não derruba a rota


def test_cache_renovado_le_so_o_cabecalho_do_arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DATA", tmp_path)
    (tmp_path / "cache_painel").mkdir()
    agora = time.time()
    (tmp_path / "cache_painel" / "a.json").write_text(json.dumps({"k": "periodo:ob_siafe:v2", "t": agora, "v": [1]}))
    assert P._cache_renovado("periodo:ob_siafe", agora - 5) is True
    assert P._cache_renovado("periodo:ob_siafe", agora + 5) is False
    assert P._cache_renovado("governo_couto:base", agora - 5) is False


def test_rota_devolve_indisponivel_quando_o_estado_falha(monkeypatch):
    from rotas import propagacao as R

    def quebra():
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(P, "estado", quebra)
    d = json.loads(R.api_sistema_propagacao().body)
    assert d["ok"] is False and d["estado"] == "INDISPONIVEL" and "locked" in d["motivo"]


# ───────────── trava por tarefa (15/11/2026: cron e despachante gravando juntos) ─────────────
def test_tarefa_com_trava_ocupada_nao_e_disparada_e_espera(con, tmp_path):
    import fcntl
    cfg = _cfg(a=_der(["f"], peso="pesado"))
    P.emitir(con, cfg, "f", "mudou")
    caminho = P.trava_da_tarefa("a", cfg["derivados"]["a"])
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fora = caminho.open("a")
    fcntl.flock(fora, fcntl.LOCK_EX | fcntl.LOCK_NB)          # o cron-rede está rodando
    rodou = []
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda did, d: rodou.append(did) or (True, None))
    assert feitos == [] and rodou == []
    assert "já rodando" in con.execute("SELECT adiado FROM derivado WHERE id='a'").fetchone()[0]
    assert set(P._sujos(con)) == {"a"}                        # continua sujo: roda quando o cron soltar
    fcntl.flock(fora, fcntl.LOCK_UN); fora.close()
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda did, d: rodou.append(did) or (True, None))
    assert rodou == ["a"]                                     # controle positivo


def test_rodar_comando_segura_a_trava_enquanto_o_filho_vive(tmp_path, monkeypatch):
    import fcntl
    monkeypatch.setattr(P, "RAIZ", tmp_path)
    monkeypatch.setattr(P, "DATA", tmp_path)
    marca = tmp_path / "durante.txt"
    d = {"comando": ["sh", "-c", f"flock -n {tmp_path}/locks/x.lock true; echo $? > {marca}"]}
    ok, _ = P._rodar_comando("x", d)
    assert ok and marca.read_text().strip() == "1"            # de dentro, a trava estava tomada
    with (tmp_path / "locks" / "x.lock").open("a") as fh:     # e foi solta no fim
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fora = (tmp_path / "locks" / "x.lock").open("a")
    fcntl.flock(fora, fcntl.LOCK_EX | fcntl.LOCK_NB)
    ok, erro = P._rodar_comando("x", {"comando": ["true"]})
    assert ok is False and "já rodando" in erro


def test_carga_efetiva_nao_cai_no_mergulho_de_1_minuto():
    """15/11/2026: carga de 1 min em 3 com a de 5 min em 20 não libera tarefa pesada."""
    assert P._carga_efetiva((3.0, 20.0, 18.0)) == 20.0
    assert P._carga_efetiva((9.5,)) == 9.5


def test_paciencia_sobe_o_teto_da_leve_em_vez_de_descer(con, monkeypatch):
    """18/11/2026: o teto final da paciência (12) valia para os dois pesos — subia o da pesada (7 → 12) mas DESCIA o
    da leve (14 → 12): com a VM-1 vivendo em carga 14–17, a tarefa leve ficava mais presa quanto mais esperava."""
    cfg = _cfg(lv=_der(["f"]))
    P.emitir(con, cfg, "f", "mudou")
    con.execute("UPDATE evento SET quando = quando - ?", (P.CARGA_PACIENCIA_S + 60,))   # sujo há mais de 2 h
    feitos = P.despachar(con, cfg, carga=lambda: (16.0,), executar=lambda *_: (True, None))
    assert [x["id"] for x in feitos] == ["lv"]


# ───────────── fome do despachante (24/11/2026: pesados 20–45 h parados, dependentes atrás deles) ─────────────
def test_dependente_nao_espera_derivado_barrado_pela_carga_ou_semaforo(con, tmp_path):
    import fcntl
    cfg = _cfg(a=_der(["f"], peso="pesado", prioridade=1), b=_der(["f", "a"], prioridade=2))
    P.emitir(con, cfg, "f", "mudou")
    (tmp_path / "locks").mkdir(exist_ok=True)
    cron = open(tmp_path / "locks" / "pesado_vm1.lock", "w")
    fcntl.flock(cron, fcntl.LOCK_EX | fcntl.LOCK_NB)                  # sei_compactar segura o semáforo
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None))
    assert [x["id"] for x in feitos] == ["b"]                          # antes: b "aguardando derivado" para sempre
    assert "semáforo" in con.execute("SELECT adiado FROM derivado WHERE id='a'").fetchone()[0]
    cron.close()


def test_pesado_atrasado_pede_a_vez_e_a_retira_quando_pega_o_semaforo(con, tmp_path):
    import fcntl
    cfg = _cfg(a=_der(["f"], peso="pesado"))
    P.emitir(con, cfg, "f", "mudou", quando=time.time() - P.CARGA_PACIENCIA_S - 60)
    (tmp_path / "locks").mkdir(exist_ok=True)
    cron = open(tmp_path / "locks" / "pesado_vm1.lock", "w")
    fcntl.flock(cron, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None)) == []
    pedido = tmp_path / "locks" / "pesado_vm1.pedido"
    assert json.loads(pedido.read_text())["derivado"] == "a"
    assert "vez pedida" in con.execute("SELECT adiado FROM derivado WHERE id='a'").fetchone()[0]
    fcntl.flock(cron, fcntl.LOCK_UN)
    cron.close()
    assert [x["id"] for x in P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None))] == ["a"]
    assert not pedido.exists()


def test_pesado_recente_nao_pede_a_vez(con, tmp_path):
    import fcntl
    cfg = _cfg(a=_der(["f"], peso="pesado"))
    P.emitir(con, cfg, "f", "mudou")
    (tmp_path / "locks").mkdir(exist_ok=True)
    cron = open(tmp_path / "locks" / "pesado_vm1.lock", "w")
    fcntl.flock(cron, fcntl.LOCK_EX | fcntl.LOCK_NB)
    P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None))
    assert not (tmp_path / "locks" / "pesado_vm1.pedido").exists()
    cron.close()


def test_alem_do_slo_o_teto_de_carga_sobe_so_com_memoria(con):
    cfg = _cfg(a=_der(["f"], peso="pesado"))
    P.emitir(con, cfg, "f", "mudou", quando=time.time() - 3 * 3600)    # SLO 2 h estourado
    assert P.despachar(con, cfg, carga=lambda: (20.0,), executar=lambda *_: (True, None), memoria=lambda: 500) == []
    assert "teto 12" in con.execute("SELECT adiado FROM derivado WHERE id='a'").fetchone()[0]   # sem memória: não
    feitos = P.despachar(con, cfg, carga=lambda: (20.0,), executar=lambda *_: (True, None), memoria=lambda: 6000)
    assert [x["id"] for x in feitos] == ["a"]
    P.emitir(con, cfg, "f", "de novo")                                   # recente: teto normal (7)
    assert P.despachar(con, cfg, carga=lambda: (20.0,), executar=lambda *_: (True, None), memoria=lambda: 6000) == []


def test_pesado_sh_devolve_a_vez_com_pedido_fresco(tmp_path):
    """tools/pesado.sh: com pedido fresco do despachante, toma a trava, devolve e sai 0 sem rodar o comando."""
    import subprocess
    src = (RAIZ / "tools" / "pesado.sh").read_text().replace("cd /home/ubuntu/JFN", f"cd {tmp_path}")
    sh = tmp_path / "pesado.sh"
    sh.write_text(src)
    (tmp_path / "data" / "locks").mkdir(parents=True)
    pedido = tmp_path / "data" / "locks" / "pesado_vm1.pedido"
    pedido.write_text('{"derivado": "lentes"}')
    marca = tmp_path / "rodou"
    env = {"PATH": "/usr/bin:/bin", "PESADO_CARGA_MAX": "999"}
    r = subprocess.run(["bash", str(sh), "teste", "5", "touch", str(marca)], env=env, timeout=30)
    assert r.returncode == 0 and not marca.exists()
    assert "vez pedida pelo despachante" in (tmp_path / "data" / "pesado_vm1.log").read_text()
    import os
    os.utime(pedido, (time.time() - 3600, time.time() - 3600))         # pedido velho: roda normal
    r = subprocess.run(["bash", str(sh), "teste", "5", "touch", str(marca)], env=env, timeout=30)
    assert r.returncode == 0 and marca.exists()


# ───────────── evento de verdade do produtor (24/11/2026) ─────────────
def test_avisar_grava_evento_e_suja_dependentes(tmp_path, monkeypatch):
    import yaml
    cfgp = tmp_path / "p.yaml"
    cfgp.write_text(yaml.safe_dump(_cfg(a=_der(["f"]))))
    monkeypatch.setattr(P, "CONFIG", cfgp)
    monkeypatch.setattr(P, "DATA", tmp_path)
    assert P.avisar("f", "OB nova") is None                             # sob pytest, sem a chave: não grava
    monkeypatch.setenv("JFN_PROPAGACAO_EM_TESTE", "1")
    eid = P.avisar("f", "1.234 OB(s) ingeridas")
    con = sqlite3.connect(tmp_path / "propagacao.db")
    assert con.execute("SELECT fonte, detalhe FROM evento WHERE id=?", (eid,)).fetchone() == ("f", "1.234 OB(s) ingeridas")
    assert con.execute("SELECT derivado FROM pendencia WHERE evento_id=?", (eid,)).fetchall() == [("a",)]
    con.close()


def test_avisar_fonte_desconhecida_nao_derruba_o_coletor(tmp_path, monkeypatch, capsys):
    import yaml
    cfgp = tmp_path / "p.yaml"
    cfgp.write_text(yaml.safe_dump(_cfg(a=_der(["f"]))))
    monkeypatch.setattr(P, "CONFIG", cfgp)
    monkeypatch.setattr(P, "DATA", tmp_path)
    monkeypatch.setenv("JFN_PROPAGACAO_EM_TESTE", "1")
    assert P.avisar("nao_existe", "x") is None
    assert "não emitido" in capsys.readouterr().err


def test_todo_avisar_do_repositorio_aponta_fonte_do_mapa():
    """Catraca: coletor que avisa fonte que não existe no yaml perderia o evento calado (só stderr)."""
    import re
    fontes = set(P.carregar(RAIZ / "config" / "propagacao.yaml")["fontes"])
    rx = re.compile(r"propagacao\.avisar\(\s*\"([a-z_]+)\"")
    achados = {}
    for arq in list((RAIZ / "compliance_agent").rglob("*.py")) + list((RAIZ / "tools").glob("*.py")):
        for f in rx.findall(arq.read_text(encoding="utf-8", errors="ignore")):
            achados.setdefault(f, []).append(arq.name)
    assert {"siafe_ob", "contratos_tcerj", "sancoes"} <= set(achados)
    assert set(achados) <= fontes, {f: a for f, a in achados.items() if f not in fontes}


# ───────────── pesado DESTACADO (24/11/2026: um pesado de 1 h segurava o ciclo inteiro) ─────────────
def _esperar_fim(con, did, teto=40):
    fim = time.time() + teto
    while time.time() < fim:
        if con.execute("SELECT ultimo_estado FROM derivado WHERE id=?", (did,)).fetchone()[0] != "rodando":
            return
        time.sleep(0.3)
    raise AssertionError(f"{did} não terminou em {teto} s")


def test_pesado_roda_destacado_e_o_leve_anda_enquanto_isso(tmp_path, monkeypatch):
    import fcntl
    import yaml
    cfg = {"fontes": {"f": {"nome": "Fonte", "sonda": {}}},
           "derivados": {"pes": _der(["f"], peso="pesado", prioridade=1, comando=["sleep", "3"]),
                         "dep": _der(["f", "pes"], prioridade=2),            # depende do pesado: espera
                         "lev": _der(["f"], prioridade=3)},                  # não depende: anda já
           "cerebro": []}
    cfgp = tmp_path / "p.yaml"
    cfgp.write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr(P, "CONFIG", cfgp)
    monkeypatch.setattr(P, "DATA", tmp_path)
    con = P.conectar(tmp_path / "p.db")
    P.emitir(con, cfg, "f", "mudou")
    t0 = time.time()
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), memoria=lambda: 9999)
    assert time.time() - t0 < 2.5                                          # o ciclo não esperou o pesado
    assert feitos[0]["id"] == "pes" and feitos[0]["destacado"] and feitos[0]["pid"]
    assert [x["id"] for x in feitos[1:]] == ["lev"]                        # controle: o leve andou
    assert con.execute("SELECT ultimo_estado FROM derivado WHERE id='pes'").fetchone()[0] == "rodando"
    with open(tmp_path / "locks" / "pesado_vm1.lock", "w") as fh:          # o filho segura o semáforo
        with pytest.raises(BlockingIOError):
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # 2º ciclo com o filho vivo: não relança; o dependente espera
    assert P.despachar(con, cfg, carga=lambda: (0.0,), memoria=lambda: 9999) == []
    assert "rodando destacado" in con.execute("SELECT adiado FROM derivado WHERE id='pes'").fetchone()[0]
    assert con.execute("SELECT adiado FROM derivado WHERE id='dep'").fetchone()[0] == "aguardando derivado de que depende"
    _esperar_fim(con, "pes")
    assert con.execute("SELECT ultimo_estado, pid FROM derivado WHERE id='pes'").fetchone() == ("ok", None)
    assert "pes" not in P._sujos(con) and P._motivos(con, "dep")[0].startswith("pes: recalculado")   # o filho emitiu
    with open(tmp_path / "locks" / "pesado_vm1.lock", "w") as fh:          # e soltou o semáforo ao sair
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), memoria=lambda: 9999)
    assert [x["id"] for x in feitos] == ["dep"]
    con.close()


def test_filho_destacado_morto_vira_falha_sem_relancar_no_laco(con):
    cfg = _cfg(a=_der(["f"], peso="pesado"))
    P.emitir(con, cfg, "f", "mudou")
    con.execute("INSERT INTO derivado(id, ultimo_estado, ultimo_inicio, pid) VALUES ('a', 'rodando', ?, 999999)",
                (time.time() - 60,))
    con.commit()
    lancados = []
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), memoria=lambda: 9999,
                         destacar=lambda *a: lancados.append(a[1]) or 1)
    assert feitos == [] and lancados == []                                 # recuo: não relança no mesmo ciclo
    est, erro, falhas, prox = con.execute(
        "SELECT ultimo_estado, ultimo_erro, falhas, proxima_tentativa FROM derivado WHERE id='a'").fetchone()
    assert est == "falhou" and "morreu" in erro and falhas == 1 and prox > time.time()
    assert "a" in P._sujos(con)                                            # a pendência fica


def test_pesado_que_termina_com_erro_registra_falha_no_filho(tmp_path, monkeypatch):
    import yaml
    cfg = {"fontes": {"f": {"nome": "Fonte", "sonda": {}}},
           "derivados": {"pes": _der(["f"], peso="pesado", comando=["false"])}, "cerebro": []}
    cfgp = tmp_path / "p.yaml"
    cfgp.write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr(P, "CONFIG", cfgp)
    monkeypatch.setattr(P, "DATA", tmp_path)
    con = P.conectar(tmp_path / "p.db")
    P.emitir(con, cfg, "f", "mudou")
    P.despachar(con, cfg, carga=lambda: (0.0,), memoria=lambda: 9999)
    _esperar_fim(con, "pes")
    est, erro = con.execute("SELECT ultimo_estado, ultimo_erro FROM derivado WHERE id='pes'").fetchone()
    assert est == "falhou" and "código 1" in erro
    assert con.execute("SELECT estado FROM execucao WHERE derivado='pes'").fetchone()[0] == "falhou"
    con.close()


def test_leve_destacado_roda_sem_o_semaforo_de_pesado(tmp_path, monkeypatch):
    """Fila de LLM (espera de rede) roda destacada SEM tomar o semáforo de pesado da VM-1."""
    import fcntl
    import yaml
    cfg = {"fontes": {"f": {"nome": "Fonte", "sonda": {}}},
           "derivados": {"fila": _der(["f"], destacado=True, comando=["sleep", "2"])}, "cerebro": []}
    cfgp = tmp_path / "p.yaml"
    cfgp.write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr(P, "CONFIG", cfgp)
    monkeypatch.setattr(P, "DATA", tmp_path)
    (tmp_path / "locks").mkdir()
    cron = open(tmp_path / "locks" / "pesado_vm1.lock", "w")
    fcntl.flock(cron, fcntl.LOCK_EX | fcntl.LOCK_NB)                   # um pesado segura o semáforo
    con = P.conectar(tmp_path / "p.db")
    P.emitir(con, cfg, "f", "mudou")
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), memoria=lambda: 9999, ritmo=lambda t: None)
    assert feitos and feitos[0]["id"] == "fila" and feitos[0]["destacado"]
    _esperar_fim(con, "fila")
    assert con.execute("SELECT ultimo_estado FROM derivado WHERE id='fila'").fetchone()[0] == "ok"
    cron.close()
    con.close()


def test_cache_espera_o_deploy_e_comando_nao(con, tmp_path):
    """24/11/2026: caches pediam rota ao painel no meio do restart do deploy (URLError)."""
    cfg = _cfg(cache=dict(_der(["f"]), tipo="cache", prefixos=["x:"], urls={"x": "x:"}), cmd=_der(["f"]))
    P.emitir(con, cfg, "f", "mudou")
    (tmp_path / ".deploy_em_curso").touch()
    feitos = P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None))
    assert [x["id"] for x in feitos] == ["cmd"]
    assert con.execute("SELECT adiado FROM derivado WHERE id='cache'").fetchone()[0] == "painel reiniciando (deploy em curso)"
    import os
    os.utime(tmp_path / ".deploy_em_curso", (time.time() - 700, time.time() - 700))   # marca velha: não segura
    assert [x["id"] for x in P.despachar(con, cfg, carga=lambda: (0.0,), executar=lambda *_: (True, None))] == ["cache"]


def test_filho_que_registrou_o_fim_na_corrida_nao_e_dado_como_morto(tmp_path, monkeypatch):
    """26/11/2026 (o «teste instável» do portão era corrida real): o conferidor lia a linha 'rodando', o filho gravava o
    próprio fim («código 1») e saía, e o conferidor via o PID morto e SOBRESCREVIA com «morreu sem registrar o fim».
    Antes de declarar a morte, relê: só conclui se ainda é o mesmo filho em 'rodando'."""
    import yaml
    cfg = {"fontes": {"f": {"nome": "Fonte", "sonda": {}}},
           "derivados": {"pes": _der(["f"], peso="pesado", comando=["false"])}, "cerebro": []}
    (tmp_path / "p.yaml").write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr(P, "CONFIG", tmp_path / "p.yaml")
    monkeypatch.setattr(P, "DATA", tmp_path)
    con = P.conectar(tmp_path / "p.db")
    con.execute("INSERT OR REPLACE INTO derivado(id, ultimo_estado, pid, ultimo_inicio) VALUES ('pes', 'rodando', 4242, 1)")
    con.commit()

    def filho_termina_na_corrida(pid, did):
        con.execute("UPDATE derivado SET ultimo_estado='falhou', ultimo_erro='saiu com código 1', pid=NULL "
                    "WHERE id='pes'")
        con.commit()
        return False
    monkeypatch.setattr(P, "_pid_vivo", filho_termina_na_corrida)
    assert P._rodando_destacado(con, cfg) == set()
    assert con.execute("SELECT ultimo_erro FROM derivado WHERE id='pes'").fetchone()[0] == "saiu com código 1"
    con.close()
