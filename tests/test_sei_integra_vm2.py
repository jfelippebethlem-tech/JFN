# -*- coding: utf-8 -*-
"""VM-2 como nó de íntegras: a fila exportada segue a ordem da VM-1, a VM-1 cede a vez enquanto a VM-2 bate
o ponto, e captura vazia da VM-2 não sobrescreve arquivo com conteúdo na VM-1."""
from __future__ import annotations

import json
import os
import time

import tools.sei_integra_fila as F
import tools.sei_integra_vm2 as V


def _arquivo_bom(pasta):
    (pasta / "texto").mkdir(parents=True)
    (pasta / "texto" / "000_a.txt").write_text("x" * 100, encoding="utf-8")
    (pasta / "manifest.json").write_text(json.dumps({"docs": [{"chars": 100}], "gerado_em": "2026-11-01"}),
                                         encoding="utf-8")


def _isolar(monkeypatch, tmp_path):
    (tmp_path / "data" / "sei_arquivo").mkdir(parents=True)
    monkeypatch.setattr(F, "ARQUIVO", tmp_path / "data" / "sei_arquivo")
    monkeypatch.setattr(V, "RAIZ", tmp_path)
    monkeypatch.setattr(V, "PRE", tmp_path / "pre_ausente.json")   # sem isto lia o pré-cálculo REAL da VM-1
    monkeypatch.setattr(F, "_fila_reler_por_ob", lambda: [])
    monkeypatch.setattr(F, "_fila_execucao", lambda: [])                # sem isto lia a sei_fila_captura REAL
    monkeypatch.setattr(F, "_fila_inscrita", lambda: ["SEI-300000/000003/2025"])
    monkeypatch.setattr(F, "_fila_geral", lambda: [{"sei": "SEI-300000/000004/2025"}])


def test_ordem_bombeiros_dinheiro_geral_e_score_preserva_ordem(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    d = tmp_path / "data"
    (d / "bombeiros_sei_fila.json").write_text(json.dumps(
        [{"sei": "SEI-100000/000001/2025", "score": 10}, {"sei": "SEI-100000/000002/2025", "score": 40}]))
    (d / "sei_fila_dinheiro.json").write_text(json.dumps(
        [{"sei": "SEI-200000/000001/2025", "score": 9e9}, {"sei": "SEI-100000/000002/2025", "score": 1}]))
    _arquivo_bom(F.ARQUIVO / "200000_000001_2025")          # já arquivado com conteúdo: pula
    fila = V.montar_fila(10, k_bombeiros=1)
    assert [e["sei"] for e in fila] == ["SEI-100000/000002/2025", "SEI-300000/000003/2025",
                                        "SEI-300000/000004/2025"]
    assert [e["fonte"] for e in fila] == ["bombeiros", "geral", "geral"]
    # `--fila` reordena por score desc — o score tem de reproduzir a ordem exportada
    assert sorted(fila, key=lambda e: -e["score"]) == fila


def test_vazio_nao_sobrescreve_arquivo_bom(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    _arquivo_bom(F.ARQUIVO / "100000_000001_2025")
    assert V.aceita(["100000_000001_2025", "100000_000009_2025", "../etc"]) == ["100000_000009_2025"]


def test_vm1_cede_a_vez_so_com_batida_fresca(monkeypatch, tmp_path):
    marca = tmp_path / ".integras_na_vm2"
    monkeypatch.setattr(F, "DELEGADO_VM2", marca)
    assert not F._delegado_vm2()
    marca.write_text("x")
    assert F._delegado_vm2()
    velho = time.time() - 31 * 3600
    os.utime(marca, (velho, velho))
    assert not F._delegado_vm2()


def test_reserva_expira(monkeypatch, tmp_path):
    r = tmp_path / "reserva.json"
    monkeypatch.setattr(F, "RESERVA_VM2", r)
    r.write_text(json.dumps({"ts": time.time(), "procs": ["100000/000001/2025"]}))
    assert F._reservados_vm2() == {"100000/000001/2025"}
    r.write_text(json.dumps({"ts": time.time() - 13 * 3600, "procs": ["100000/000001/2025"]}))
    assert F._reservados_vm2() == set()


def test_devolver_monta_lote_sem_falha_do_navegador(monkeypatch, tmp_path):
    log = tmp_path / "fila.log"
    log.write_text(
        "[2026-11-13 16:51:08]   270032/000052/2023: SEM ÁRVORE (processo não abriu) — via='cracked' "
        "erro_cracked=\"link 'Pesquisa' NÃO ESTÁ no DOM (o clique nunca aconteceu)\"\n"
        "[2026-11-13 16:51:08]   270032/000052/2023: sem_arvore\n"
        "[2026-11-13 17:00:00]   270003/004118/2024: ok\n", encoding="utf-8")
    arq = tmp_path / "sei_arquivo"
    _arquivo_bom(arq / "270003_004118_2024")
    monkeypatch.setattr(F, "LOG", log)
    monkeypatch.setattr(F, "ARQUIVO", arq)
    monkeypatch.setattr(F, "CACHE", tmp_path / "sei_cache")
    monkeypatch.setattr(V, "RESUMO", tmp_path / "resumo.jsonl")
    import tools.vm2_lote as L
    monkeypatch.setattr(L, "LOTES", tmp_path / "lotes")
    monkeypatch.setattr(L, "julgar", lambda *a: {"legivel": True, "corresponde": True})
    enviados = []
    monkeypatch.setattr(L, "enviar", lambda base: enviados.append(base) or {"aprovados": ["270003/004118/2024"]})
    monkeypatch.setattr(L, "reenviar_pendentes", lambda: [])
    V.devolver(0)
    man = json.loads((enviados[0] / "MANIFESTO.json").read_text())
    assert list(man["processos"]) == ["270003/004118/2024"]
    assert man["processos"]["270003/004118/2024"]["preconferencia"]["versao"] == 1   # 23/11: o nó pré-confere
    assert "270032/000052/2023" in man["nao_entregues"]
    assert "arquivo/270003_004118_2024/manifest.json" in man["arquivos"]
    assert not (arq / "270003_004118_2024").exists()          # cópia local sai depois de ir para o lote


def test_tirar_da_fila_mantem_adiados(tmp_path):
    fila = tmp_path / "f.json"
    fila.write_text(json.dumps([{"sei": "SEI-100000/000001/2025"}, {"sei": "SEI-100000/000002/2025"}]))
    V._tirar_da_fila(fila, ["100000/000001/2025"])
    assert [e["sei"] for e in json.loads(fila.read_text())] == ["SEI-100000/000002/2025"]


def test_fila_usa_precalculo_fresco_e_ignora_velho(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    monkeypatch.setattr(V, "PRE", tmp_path / "pre.json")
    caro = []
    monkeypatch.setattr(F, "_fila_geral", lambda: caro.append(1) or [{"sei": "SEI-300000/000004/2025"}])
    (tmp_path / "pre.json").write_text(json.dumps({"ts": time.time(), "reler": [], "geral": ["SEI-400000/000001/2025"]}))
    assert "SEI-400000/000001/2025" in [e["sei"] for e in V.montar_fila(10)] and not caro
    (tmp_path / "pre.json").write_text(json.dumps({"ts": time.time() - 27 * 3600, "reler": [], "geral": []}))
    assert "SEI-300000/000004/2025" in [e["sei"] for e in V.montar_fila(10)] and caro


def test_nos_nao_pegam_processo_reservado_por_outro(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    monkeypatch.setattr(V, "RESERVA", tmp_path / "data" / ".integras_vm2_reserva.json")
    monkeypatch.setattr(V, "PRE", tmp_path / "pre.json")
    (tmp_path / "data" / ".integras_vm2_reserva.json").write_text(json.dumps(
        {"ts": time.time(), "procs": ["300000/000003/2025"]}))
    fila = V.exportar(10, no="itcampo", validade_h=3)
    assert [e["sei"] for e in fila] == ["SEI-300000/000004/2025"]
    reg = json.loads((tmp_path / "data" / ".integras_itcampo_reserva.json").read_text())
    assert reg["procs"] == ["300000/000004/2025"] and reg["validade_h"] == 3
    # a fila da VM-1 enxerga as duas reservas; a de 3 h vence sozinha (nó fora do ar devolve a fila)
    monkeypatch.setattr(F, "RESERVA_VM2", tmp_path / "data" / ".integras_vm2_reserva.json")
    assert F._reservados_vm2() == {"300000/000003/2025", "300000/000004/2025"}
    reg["ts"] = time.time() - 4 * 3600
    (tmp_path / "data" / ".integras_itcampo_reserva.json").write_text(json.dumps(reg))
    assert F._reservados_vm2() == {"300000/000003/2025"}


def test_batida_de_qualquer_no_faz_a_vm1_ceder(monkeypatch, tmp_path):
    monkeypatch.setattr(F, "DELEGADO_VM2", tmp_path / ".integras_na_vm2")
    assert not F._delegado_vm2()
    (tmp_path / ".integras_na_itcampo").write_text("x")
    assert F._delegado_vm2()
    velho = time.time() - 5 * 3600                      # nó de rodadas curtas vale 4 h, não 30
    os.utime(tmp_path / ".integras_na_itcampo", (velho, velho))
    assert not F._delegado_vm2()


def test_restrito_confirmado_nao_vai_para_a_fila(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    (tmp_path / "data" / "sei_restritos.json").write_text(json.dumps({
        "3000000000032025": {"numero": "300000/000003/2025", "status": "RESTRITO"},
        "3000000000042025": {"numero": "300000/000004/2025", "status": "RESTRITO?"}}))
    assert [e["sei"] for e in V.montar_fila(10)] == ["SEI-300000/000004/2025"]


def test_restrito_confirmado_volta_a_fila_depois_de_30_dias(monkeypatch, tmp_path):
    # 14/11/2026: acesso de unidade muda — restrito confirmado é retentado após 30 dias da última leitura
    _isolar(monkeypatch, tmp_path)
    (tmp_path / "data" / "sei_restritos.json").write_text(json.dumps({
        "a": {"numero": "300000/000003/2025", "status": "RESTRITO", "ultima": "2026-01-02 10:00"},
        "b": {"numero": "300000/000004/2025", "status": "RESTRITO",
              "ultima": time.strftime("%Y-%m-%d %H:%M")},
        "c": {"numero": "300000/000005/2025", "status": "RESTRITO"}}))   # sem data: segue fora (conservador)
    assert [e["sei"] for e in V.montar_fila(10)] == ["SEI-300000/000003/2025"]


def test_recaptura_de_execucao_vem_antes_e_rele_o_arquivado(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    _arquivo_bom(F.ARQUIVO / "500000_000001_2025")          # arquivado "completo", mas sem doc de execução
    monkeypatch.setattr(F, "_fila_execucao", lambda: ["SEI-500000/000001/2025"])
    fila = V.montar_fila(10, k_bombeiros=1)
    assert fila[0] == {"sei": "SEI-500000/000001/2025", "fonte": "execucao", "score": len(fila)}


def test_fila_execucao_sai_quando_recapturado_depois_da_inscricao(monkeypatch, tmp_path):
    import sqlite3
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sei_fila_captura (numero_sei TEXT PRIMARY KEY, sei_norm TEXT, motivo TEXT,"
                " total_pago REAL, n_docs INTEGER, visto_em TEXT)")
    m = F.MOTIVO_EXECUCAO + " — recaptura 18/11"
    con.executemany("INSERT INTO sei_fila_captura VALUES (?,?,?,?,?,?)", [
        ("SEI-600000/000001/2025", "", m, 10.0, None, "2026-11-18 18:00:00"),   # arquivo velho: relê
        ("SEI-600000/000002/2025", "", m, 20.0, None, "2026-11-18 18:00:00"),   # recapturado depois: sai
        ("SEI-600000/000003/2025", "", m, 5.0, None, "2026-11-18 18:00:00"),    # sem arquivo: captura
        ("SEI-600000/000004/2025", "", "nunca_capturado", 99.0, None, "2026-11-18 18:00:00")])
    con.commit(); con.close()
    (tmp_path / "arq").mkdir()
    monkeypatch.setattr(F, "DB", db)
    monkeypatch.setattr(F, "ARQUIVO", tmp_path / "arq")
    for tag, quando in (("600000_000001_2025", "2026-11-01 00:00:00"), ("600000_000002_2025", "2026-11-18 19:00:00")):
        _arquivo_bom(F.ARQUIVO / tag)
        from datetime import datetime, timezone
        ts = datetime.strptime(quando, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        os.utime(F.ARQUIVO / tag / "manifest.json", (ts, ts))
    assert F._fila_execucao() == ["SEI-600000/000001/2025", "SEI-600000/000003/2025"]


def test_reprovado_duas_vezes_em_24h_sai_da_exportacao(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    q = tmp_path / "data" / "vm2_quarentena"
    agora = time.strftime("%Y%m%d-%H%M%S")
    for i, lote in enumerate((f"integras-{agora}-1", f"integras-{agora}-2", "integras-20200101-000000-1")):
        (q / lote).mkdir(parents=True)
        (q / lote / "300000_000003_2025.motivo.json").write_text("{}")
        if i == 2:                                                       # lote velho não conta
            (q / lote / "300000_000004_2025.motivo.json").write_text("{}")
    assert V._quarentena_repetida() == {"300000/000003/2025"}
    assert [e["sei"] for e in V.montar_fila(10)] == ["SEI-300000/000004/2025"]


def _log_lotes(caminho, blocos):
    """blocos = [(origem, [(proc, status), ...]), ...] no formato que `vm2_conferencia` grava no log da VM-1."""
    linhas = []
    for k, (origem, itens) in enumerate(blocos):
        linhas.append(f"[2026-11-18 10:{k:02d}:00] {origem}: lote integras-x-{k} conferido — 0 aprovado(s), 0 em quarentena")
        for proc, st in itens:
            linhas.append(f"[2026-11-18 10:{k:02d}:01] ÍNTEGRA {proc} …")
            linhas.append(f"[2026-11-18 10:{k:02d}:02]   {proc}: {st}")
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def test_timeouts_seguidos_na_vm2_mandam_o_processo_ao_itcampo(monkeypatch, tmp_path):
    """18/11/2026: `080007/002208/2021` (1.953 documentos) estourou o teto de 900 s da VM-2 19 vezes sem um PDF novo
    — só enumerar a árvore passa do teto. N timeouts SEGUIDOS na VM-2 tiram o processo da exportação DELA; o it-campo
    (teto de 3 h) continua recebendo."""
    _isolar(monkeypatch, tmp_path)
    log = tmp_path / "fila.log"
    monkeypatch.setattr(F, "LOG", log)
    vm2 = V.ORIGENS_VM2[0]
    _log_lotes(log, [
        (vm2, [("300000/000003/2025", "timeout"), ("300000/000004/2025", "timeout")]),
        (vm2, [("300000/000003/2025", "timeout")]),
        ("Jorge", [("300000/000003/2025", "timeout")]),                 # timeout no it-campo não conta para a VM-2
        (vm2, [("300000/000004/2025", "ok")]),                           # ok zera a sequência
        (vm2, [("300000/000003/2025", "adiado"), ("300000/000003/2025", "timeout")]),   # adiado não diz nada
        (vm2, [("300000/000004/2025", "timeout")]),
    ])
    assert V._timeouts_seguidos_vm2(limite=3) == {"300000/000003/2025"}
    assert [e["sei"] for e in V.exportar(10, no="itcampo1", validade_h=3)] == \
        ["SEI-300000/000003/2025", "SEI-300000/000004/2025"]
    (tmp_path / "data" / ".integras_itcampo1_reserva.json").unlink()      # reserva do it-campo não interfere aqui
    assert [e["sei"] for e in V.exportar(10, no="vm2", validade_h=3)] == ["SEI-300000/000004/2025"]


def test_sem_log_nenhum_processo_sai(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    monkeypatch.setattr(F, "LOG", tmp_path / "nao_existe.log")
    assert V._timeouts_seguidos_vm2() == set()


def test_exportar_simultaneo_de_dois_nos_nao_reserva_o_mesmo_processo(monkeypatch, tmp_path):
    """22/11/2026 (it-campo): sessões que pediam fila no MESMO segundo (s5+s6 às 20:02:30; s1+s2+s4 às 23:56:07)
    recebiam a MESMA fila — cada `exportar` lia as reservas alheias antes de a outra gravar a sua. Terminando juntas,
    pediam juntas de novo: 4 sessões em passo travado, 35% das capturas em dobro (medido em 22 h com n=4)."""
    import threading
    monkeypatch.setattr(V, "RAIZ", tmp_path)
    (tmp_path / "data").mkdir()
    todos = [f"300000/{i:06d}/2025" for i in range(6)]

    def montar(max_n, k_bombeiros=0, excluir=()):
        livres = [p for p in todos if p not in excluir][:max_n]
        time.sleep(0.3)                                    # a montagem real leva segundos
        return [{"sei": f"SEI-{p}"} for p in livres]

    monkeypatch.setattr(V, "montar_fila", montar)
    out = {}
    ts = [threading.Thread(target=lambda no=no: out.__setitem__(no, V.exportar(3, no, 3.0))) for no in ("itcampo5", "itcampo6")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    a, b = ({e["sei"] for e in out[no]} for no in ("itcampo5", "itcampo6"))
    assert a and b and not (a & b)


def test_releitura_precalculada_nao_volta_depois_de_recapturada(monkeypatch, tmp_path):
    """23/11/2026 (it-campo, s1): `140001/039864/2025` e `030001/005404/2026` foram capturados ok a cada volta (00:37,
    00:44, 00:48 …). Estavam na lista `reler` PRÉ-CALCULADA às 00:25 (vale 26 h) — e quem está em `reler` pula o
    filtro de já arquivado. Arquivo regravado DEPOIS do pré-cálculo já leu as OB que o pré-cálculo conhecia: sai."""
    _isolar(monkeypatch, tmp_path)
    monkeypatch.setattr(V, "PRE", tmp_path / "pre.json")
    monkeypatch.setattr(F, "_fila_geral", lambda: [])
    monkeypatch.setattr(F, "_fila_inscrita", lambda: [])
    for tag in ("500000_000001_2025", "500000_000002_2025"):
        _arquivo_bom(F.ARQUIVO / tag)
    ts_pre = time.time() - 3600
    velho = ts_pre - 86400                                      # 500000/000002: arquivo ANTERIOR ao pré-cálculo
    for f in (F.ARQUIVO / "500000_000002_2025" / "texto").glob("*.txt"):
        os.utime(f, (velho, velho))
    (tmp_path / "pre.json").write_text(json.dumps({"ts": ts_pre, "geral": [],
                                                   "reler": ["SEI-500000/000001/2025", "SEI-500000/000002/2025"]}))
    assert [e["sei"] for e in V.montar_fila(10)] == ["SEI-500000/000002/2025"]


def _conf(ts, proc, st, arvore=18, teor=2):
    if st == "APROVADO":
        return f"[{ts}] CONFERÊNCIA {proc}: APROVADO [ok] {{\"docs\": {arvore}, \"arvore\": {arvore}}} motivos=[]"
    return (f"[{ts}] CONFERÊNCIA {proc}: QUARENTENA [ok] {{\"docs\": {arvore}, \"arvore\": {arvore}, \"com_teor\": {teor}, "
            f"\"juizo_claude\": {{\"legivel\": true}}}} motivos=['só {teor}/{arvore} documentos com teor (< 60%)']")


def test_recaptura_convergente_mesma_arvore_mesmo_motivo_sai_por_7_dias(monkeypatch, tmp_path):
    """23/11/2026 (plano de reescrita, Fase 0e): a guarda antiga lia pastas da quarentena que o frio leva à VM-2 após
    6 h. O log é permanente: mesma árvore + mesma categoria de motivo nas 2 últimas reprovações, sem aprovação
    depois, = recapturar não muda nada; fica fora 7 dias e vai ao reparo."""
    _isolar(monkeypatch, tmp_path)
    agora = time.strftime("%Y-%m-%d %H:%M:%S")
    velho = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 9 * 86400))
    linhas = [_conf(agora, "100000/000001/2025", "QUARENTENA", 18, 2),
              _conf(agora, "100000/000001/2025", "QUARENTENA", 18, 3),      # números do motivo variam: mesma categoria
              _conf(agora, "100000/000002/2025", "QUARENTENA", 18),
              _conf(agora, "100000/000002/2025", "QUARENTENA", 25),          # árvore cresceu: recapturar vale
              _conf(agora, "100000/000003/2025", "QUARENTENA"),
              _conf(agora, "100000/000003/2025", "QUARENTENA"),
              _conf(agora, "100000/000003/2025", "APROVADO"),                # aprovado depois: livre
              _conf(velho, "100000/000004/2025", "QUARENTENA"),
              _conf(velho, "100000/000004/2025", "QUARENTENA"),              # fora da janela de 7 dias
              _conf(agora, "100000/000005/2025", "QUARENTENA")]              # uma só reprovação
    (tmp_path / "data" / "vm2_conferencia.log").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    assert V._recaptura_convergente() == {"100000/000001/2025"}
