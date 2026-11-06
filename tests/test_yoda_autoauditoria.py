# -*- coding: utf-8 -*-
"""Loop de automelhoria do Yoda: detecta falha de conversa, agrupa, e acusa conserto que não pegou."""
import time

import tools.yoda_autoauditoria as Y


def _m(papel, texto, ts, sessao="s1", ferramenta=""):
    return {"sessao": sessao, "papel": papel, "texto": texto, "ferramenta": ferramenta, "ts": ts}


def test_incapaz_e_repeticao_do_caso_siafe():
    msgs = [_m("user", "[J FN id=45338178] Siafe codigo 4ZuteXbN", 100),
            _m("assistant", "o comando `siafecodigo` não é uma ferramenta válida.", 101),
            _m("user", "[J FN id=45338178] *siafe codigo 4ZuteXbN*", 116),
            _m("assistant", "o comando `siafecodigo` não está disponível nas ferramentas.", 119)]
    tipos = {(f["tipo"], f["assinatura"]) for f in Y.detectar(msgs)}
    assert ("incapaz", "incapaz:siafe codigo #") in tipos
    assert ("repeticao", "repeticao:siafe codigo #") in tipos


def test_injecao_do_sistema_nao_e_falha_do_dono():
    msgs = [_m("user", "[IMPORTANT: Background process proc_1 completed (exit code -15).", 100),
            _m("user", "[CONTEXT COMPACTION — REFERENCE ONLY] resumo", 101)]
    assert Y.detectar(msgs) == []


def test_resposta_normal_nao_e_falha():
    msgs = [_m("user", "quanto o ITERJ pagou em 2024", 100),
            _m("assistant", "O ITERJ pagou R$ 1.234,56 em 2024 a 3 credores.", 105)]
    assert Y.detectar(msgs) == []


def test_skill_agrupa_pelo_nome():
    msgs = [_m("user", '[IMPORTANT: The user has invoked the "relatorio" skill, indicating ...] mgs', 100),
            _m("tool", "Traceback (most recent call last): boom", 101),
            _m("assistant", "Gerando.", 102)]
    assert {f["assinatura"] for f in Y.detectar(msgs)} == {"erro_ferramenta:/relatorio"}


def test_segredo_e_redigido():
    assert "sk-" not in Y._redigir("minha chave sk-ac77c59650664fd9893c948adaa7a8f5 ok")


def test_conserto_que_nao_pegou_vira_reincidiu(tmp_path):
    fila = tmp_path / "fila.json"
    f1 = {"tipo": "incapaz", "assinatura": "incapaz:siafe codigo #", "ts": 100.0, "quando": "a",
          "pedido": "siafe codigo X1", "resposta": "não está disponível"}
    Y.atualizar_fila([f1], fila)
    assert Y.resolver("incapaz:siafe codigo #", "plugin", fila)
    r = Y.atualizar_fila([{**f1, "ts": time.time() + 10, "quando": "b"}], fila)
    assert r["reincidiu"] == ["incapaz:siafe codigo #"]
    assert r["fila"]["incapaz:siafe codigo #"]["status"] == "REINCIDIU"


def test_janela_sobreposta_nao_conta_duas_vezes(tmp_path):
    fila = tmp_path / "fila.json"
    f1 = {"tipo": "incapaz", "assinatura": "incapaz:x", "ts": 100.0, "quando": "a", "pedido": "x", "resposta": "y"}
    Y.atualizar_fila([f1], fila)
    r = Y.atualizar_fila([f1], fila)
    assert r["fila"]["incapaz:x"]["n"] == 1


def test_licao_entra_na_memoria_do_yoda_sem_apagar_o_resto(tmp_path):
    mem = tmp_path / "MEMORY.md"
    mem.write_text("AMBIENTE: dono\n§\nROTINAS: bom dia 07:30", encoding="utf-8")
    fila = {"incapaz:siafe codigo #": {"tipo": "incapaz", "status": "resolvido", "licao": "use /siafe",
                                       "exemplo": {"pedido": "x", "resposta": "y"}}}
    assert Y.gravar_licoes_no_yoda(fila, mem).startswith("gravado")
    partes = mem.read_text(encoding="utf-8").split("\n§\n")
    assert partes[:2] == ["AMBIENTE: dono", "ROTINAS: bom dia 07:30"]
    assert partes[2].startswith(Y._MARCA) and "use /siafe" in partes[2]
    # idempotente: segunda rodada não duplica a entrada
    assert Y.gravar_licoes_no_yoda(fila, mem) == "sem mudança"
    assert mem.read_text(encoding="utf-8").count(Y._MARCA) == 1


def test_nao_estoura_o_limite_da_memoria(tmp_path):
    mem = tmp_path / "MEMORY.md"
    original = "X" * 5800
    mem.write_text(original, encoding="utf-8")
    fila = {"a": {"tipo": "incapaz", "status": "resolvido", "licao": "L" * 400, "exemplo": {"pedido": "", "resposta": ""}}}
    assert Y.gravar_licoes_no_yoda(fila, mem).startswith("não gravado")
    assert mem.read_text(encoding="utf-8") == original
