# -*- coding: utf-8 -*-
"""Estágio `legado:<rotina>` (O2.1): roda o comando antigo com teto, trava e log; efeito conferido = rc 0 E a prova
declarada (arquivo regravado / log_contem / sem traceback), relida do mundo. Tudo numa raiz temporária: o teste
nunca escreve em data/ do repo."""
import json
import sys
from datetime import datetime

import pytest
import yaml

from compliance_agent.aplicacao import estagios as EST
from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, legado as L
from compliance_agent.fluxo import grafo as G
from compliance_agent.fluxo.fila import Resultado

PY = "{py}"


def _estagios():
    return {e: {"tipo": e.lower(), "nome": e, "recursos": ["cpu_leve"], "nos": ["vm1"], "volta": {"nos": []},
                "timeout_s": 30, "efeito": "efeito verificável do estágio"} for e in G.ESTAGIOS}


@pytest.fixture()
def raiz(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "RAIZ", tmp_path)
    G.carregar_grafo_cache.cache_clear()
    yield tmp_path
    G.carregar_grafo_cache.cache_clear()


def _grafo(raiz, monkeypatch, **rotinas):
    base = {"versao": 1, "nos": ["vm1", "vm2", "itcampo"], "concorrencia": {}, "estagios": _estagios(),
            "fontes": {"f": "fonte"}, "rotinas": {}}
    for rid, r in rotinas.items():
        r.setdefault("estagio", "E1")
        r.setdefault("descricao", f"rotina {rid}")
        r.setdefault("agenda", [{"cron": "* * * * *"}])
        r.setdefault("efeito", {"descricao": "imprime ok no log", "log_contem": "ok"})
        base["rotinas"][rid] = r
    arq = raiz / "fluxo.yaml"
    arq.write_text(yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv(L.ENV_GRAFO, str(arq))
    G.carregar_grafo_cache.cache_clear()
    return G.carregar(arq)


def _ctx(rid, no="vm1"):
    return Contexto(no=no, tipo=f"legado:{rid}", chave=f"legado:{rid}:t", ficha=7, tentativa=1)


def _rodar(rid, payload=None, no="vm1"):
    payload = {"rotina": rid, **(payload or {})}
    r = L.handler(payload, _ctx(rid, no))
    return r, L.efeito(payload, _ctx(rid, no), Resultado(efeito=json.loads(json.dumps(r.efeito)), eventos=r.eventos))


def test_sucesso_com_log_contem(raiz, monkeypatch):
    _grafo(raiz, monkeypatch, ok=dict(comando=[PY, "-c", "print('ok')"]))
    r, conferido = _rodar("ok")
    assert r.efeito["rc"] == 0 and r.efeito["rcs"] == [0] and conferido is True
    assert r.eventos == [{"fonte": "ok", "tipo": "concluido"}]
    assert "ok" in (raiz / "data/logs/fluxo/ok.log").read_text()


def test_log_sem_o_esperado_nao_confere(raiz, monkeypatch):
    _grafo(raiz, monkeypatch, mudo=dict(comando=[PY, "-c", "print('nada')"]))
    _, conferido = _rodar("mudo")
    assert conferido is False


def test_traceback_com_rc_zero_nao_confere(raiz, monkeypatch):
    cod = "import traceback\ntry:\n    1/0\nexcept ZeroDivisionError:\n    traceback.print_exc()\nprint('ok')"
    _grafo(raiz, monkeypatch, engole=dict(comando=[PY, "-c", cod]))
    r, conferido = _rodar("engole")
    assert r.efeito["rc"] == 0 and conferido is False


def test_traceback_de_execucao_anterior_nao_contamina(raiz, monkeypatch):
    (raiz / "data/logs/fluxo").mkdir(parents=True)
    (raiz / "data/logs/fluxo/limpo.log").write_text("Traceback (most recent call last):\n antigo\n")
    _grafo(raiz, monkeypatch, limpo=dict(comando=[PY, "-c", "print('ok')"]))
    assert _rodar("limpo")[1] is True                              # só o trecho DESTA execução conta


def test_arquivo_de_efeito_regravado_confere_e_velho_nao(raiz, monkeypatch):
    ef = {"descricao": "arquivo regravado", "arquivo": "data/saida.json"}
    _grafo(raiz, monkeypatch,
           grava=dict(comando=[PY, "-c", "open('data/saida.json','w').write('{}')"], efeito=ef),
           nao_grava=dict(comando=[PY, "-c", "pass"], efeito=ef))
    (raiz / "data").mkdir(exist_ok=True)
    assert _rodar("grava")[1] is True
    import os
    os.utime(raiz / "data/saida.json", (1, 1))                     # arquivo de ontem: quem não grava não prova
    assert _rodar("nao_grava")[1] is False


def test_rc_diferente_de_zero_e_falha_transitoria(raiz, monkeypatch):
    _grafo(raiz, monkeypatch, quebra=dict(comando=[PY, "-c", "import sys; sys.exit(3)"]))
    with pytest.raises(L.FalhaTransitoria, match=r"rc=\[3\]"):
        L.handler({"rotina": "quebra"}, _ctx("quebra"))


def test_teto_de_tempo_mata_o_grupo(raiz, monkeypatch):
    _grafo(raiz, monkeypatch, lento=dict(comando=[PY, "-c", "import time; time.sleep(30)"], timeout_s=1))
    t0 = datetime.now()
    with pytest.raises(L.FalhaTransitoria, match="estourou o teto de 1 s"):
        L.handler({"rotina": "lento"}, _ctx("lento"))
    assert (datetime.now() - t0).total_seconds() < 25


def test_passos_todos_rodam_e_um_falho_derruba(raiz, monkeypatch):
    marca = "open('data/p3','w').write('x')"
    _grafo(raiz, monkeypatch,
           seq=dict(passos=[[PY, "-c", "print('ok')"], [PY, "-c", "raise SystemExit(2)"], [PY, "-c", marca]]),
           seq_para=dict(passos=[[PY, "-c", "raise SystemExit(2)"], [PY, "-c", marca.replace("p3", "p4")]],
                         parar_no_erro=True))
    (raiz / "data").mkdir(exist_ok=True)
    with pytest.raises(L.FalhaTransitoria, match=r"rc=\[2\]"):
        L.handler({"rotina": "seq"}, _ctx("seq"))
    assert (raiz / "data/p3").exists()                             # `;` do cron: o passo seguinte roda
    with pytest.raises(L.FalhaTransitoria):
        L.handler({"rotina": "seq_para"}, _ctx("seq_para"))
    assert not (raiz / "data/p4").exists()                         # `&&`: para no erro


def test_inativa_vai_a_quarentena(raiz, monkeypatch):
    _grafo(raiz, monkeypatch, off=dict(comando=[PY, "-c", "print('ok')"], ativa=False, bloqueio="fora do repo"))
    with pytest.raises(ErroPermanente, match="fora do repo"):
        L.handler({"rotina": "off"}, _ctx("off"))


def test_rotina_desconhecida_e_alvo_inexistente_sao_permanentes(raiz, monkeypatch):
    _grafo(raiz, monkeypatch, sumiu=dict(comando=["bash", "tools/nao_existe.sh"]),
           mod=dict(comando=[PY, "-m", "tools.modulo_que_nao_existe_xyz"]))
    with pytest.raises(ErroPermanente, match="não está"):
        L.handler({"rotina": "fantasma"}, _ctx("fantasma"))
    with pytest.raises(ErroPermanente, match="não existe"):
        L.handler({"rotina": "sumiu"}, _ctx("sumiu"))
    with pytest.raises(ErroPermanente, match="não existe"):
        L.handler({"rotina": "mod"}, _ctx("mod"))


def test_no_errado_e_transitorio(raiz, monkeypatch):
    _grafo(raiz, monkeypatch, so_vm2=dict(comando=[PY, "-c", "print('ok')"], nos=["vm2"]))
    with pytest.raises(L.FalhaTransitoria, match="não em vm1"):
        L.handler({"rotina": "so_vm2"}, _ctx("so_vm2", "vm1"))
    assert _rodar("so_vm2", no="vm2")[1] is True


def test_condicao_de_dia_da_semana(raiz, monkeypatch):
    _grafo(raiz, monkeypatch, domingo=dict(comando=[PY, "-c", "print('ok')"], condicao={"dia_semana_iso": 7}))
    monkeypatch.setattr(L, "_agora", lambda: datetime(2026, 11, 24, 4, 30, tzinfo=L.FUSO))     # terça
    r, conferido = _rodar("domingo")
    assert r.efeito["pulado"] == "condicao" and conferido is True
    assert not (raiz / "data/logs/fluxo/domingo.log").exists()
    monkeypatch.setattr(L, "_agora", lambda: datetime(2026, 11, 29, 4, 30, tzinfo=L.FUSO))     # domingo
    r, conferido = _rodar("domingo")
    assert r.efeito["rc"] == 0 and conferido is True
    # "pulado" declarado num domingo é mentira: não confere
    assert L.efeito({"rotina": "domingo"}, _ctx("domingo"),
                    Resultado(efeito={"rotina": "domingo", "pulado": "condicao"})) is False


def test_trava_ocupada_e_transitoria(raiz, monkeypatch):
    import fcntl
    _grafo(raiz, monkeypatch, travada=dict(comando=[PY, "-c", "print('ok')"], trava="data/locks/x.lock"))
    (raiz / "data/locks").mkdir(parents=True)
    with open(raiz / "data/locks/x.lock", "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(L.FalhaTransitoria, match="ocupada"):
            L.handler({"rotina": "travada"}, _ctx("travada"))
    assert _rodar("travada")[1] is True


def test_args_do_horario_com_datas(raiz, monkeypatch):
    _grafo(raiz, monkeypatch, data=dict(comando=[PY, "-c", "import sys; print('ok', sys.argv[1:])"]))
    monkeypatch.setattr(L, "_agora", lambda: datetime(2026, 11, 24, 6, 50, tzinfo=L.FUSO))
    r, conferido = _rodar("data", {"args": ["{ontem}", "{hoje}"]})
    assert conferido and "['2026-11-23', '2026-11-24']" in (raiz / "data/logs/fluxo/data.log").read_text()


def test_env_do_arquivo_chega_ao_filho_e_nao_ao_log(raiz, monkeypatch):
    (raiz / ".env").write_text("# comentario\nexport SEGREDO_TESTE='valor-secreto-123'\n")
    cod = "import os; print('ok' if os.environ.get('SEGREDO_TESTE', '')[::-1] == '321-oterces-rolav' else 'faltou')"
    _grafo(raiz, monkeypatch, env=dict(comando=[PY, "-c", cod], carregar_env=True, env={"OUTRA": "1"}))
    r, conferido = _rodar("env")
    assert conferido is True
    assert "valor-secreto-123" not in (raiz / "data/logs/fluxo/env.log").read_text()
    assert "valor-secreto-123" not in json.dumps(r.efeito)


def test_efeito_nao_aceita_resultado_adulterado(raiz, monkeypatch):
    _grafo(raiz, monkeypatch, ok=dict(comando=[PY, "-c", "print('ok')"]))
    r, _ = _rodar("ok")
    for mexe in ({"rcs": [0, 1]}, {"rc": 1}, {"log_ate": r.efeito["log_ate"] + 10_000}, {"rotina": "outra"},
                 {"log": "data/logs/fluxo/inexistente.log"}):
        assert L.efeito({"rotina": "ok"}, _ctx("ok"), Resultado(efeito={**r.efeito, **mexe})) is False


def test_registro_resolve_a_familia_legado():
    assert EST.estagio_de("legado:qualquer") is L.ESTAGIO
    assert EST.estagio_de("eco") is EST.REGISTRO["eco"]
    assert EST.estagio_de("nao_existe") is None


def test_python_do_placeholder_e_o_deste_processo():
    assert L.expandir("{py}") == sys.executable
