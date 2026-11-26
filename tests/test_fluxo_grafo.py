# -*- coding: utf-8 -*-
"""O grafo da Esteira Única (O2.1): config/fluxo.yaml real carrega e é coerente; o validador recusa ciclo,
referência quebrada, recurso/cron inválido, efeito sem prova e topologia no comando; e o planejador consome o grafo
(agenda + eventos com agrupar/intervalo mínimo) — os de banco em ESQUEMA TEMPORÁRIO (tests/fluxo_pg.py)."""
import copy
import re
from pathlib import Path

import pytest
import yaml

from compliance_agent.fluxo import fila, grafo as G, planejador as P
from tests.fluxo_pg import con, esquema_tmp, precisa_pg  # noqa: F401 — fixtures

YAML_REAL = Path(G.CAMINHO)


@pytest.fixture(scope="module")
def real():
    return G.carregar()


@pytest.fixture()
def base():
    """Um grafo mínimo válido (dict) que cada teste estraga de um jeito."""
    estagios = {e: {"tipo": e.lower(), "nome": e, "recursos": ["cpu_leve"], "nos": ["vm1"], "volta": {"nos": ["vm2"]},
                    "timeout_s": 60, "efeito": "efeito verificável do estágio", "depende": []} for e in G.ESTAGIOS}
    estagios["E2"]["depende"] = ["E1"]
    return {"versao": 1, "nos": ["vm1", "vm2", "itcampo"], "concorrencia": {"por_fonte": {"max": 1, "motivo": "x"}},
            "estagios": estagios, "fontes": {"f1": "fonte 1", "f2": "fonte 2"},
            "rotinas": {
                "ra": {"estagio": "E1", "descricao": "rotina a", "comando": ["{py}", "-c", "print(1)"],
                      "agenda": [{"cron": "*/5 * * * *"}], "efeito": {"descricao": "imprime um", "log_contem": "1"}},
                "rb": {"estagio": "E10", "descricao": "rotina b", "comando": ["bash", "tools/x.sh"],
                      "evento": {"depende": ["f1", "ra"], "debounce_s": 30, "intervalo_min_s": 600},
                      "efeito": {"descricao": "arquivo regravado", "arquivo": "data/b.json"}}}}


# ── yaml real ──
def test_yaml_real_carrega_com_os_18_estagios(real):
    assert list(real.estagios) == list(G.ESTAGIOS)
    assert len(real.rotinas) >= 100 and real.agenda_linhas() and real.grafo_planejador()


def test_yaml_real_sem_topologia_sensivel():
    txt = YAML_REAL.read_text(encoding="utf-8")
    assert "/home/" not in txt and "/opt/" not in txt
    assert not re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", txt), "IP no fluxo.yaml"
    assert not re.search(r"\b(vm1|vm2)-ts\b|tailbbe|\.ts\.net", txt), "host da Tailnet no fluxo.yaml"
    assert not re.search(r"(?i)(senha|password|token|api[_-]?key)\s*[:=]", txt)


def test_yaml_real_toda_rotina_tem_contrato_e_alvo_existente(real):
    from compliance_agent.aplicacao.estagios import legado
    contrato = real.contrato()
    for rid, r in real.rotinas.items():
        c = contrato[G.tipo_da_rotina(rid)]
        assert c["recursos"] and c["timeout_s"] > 0 and c["no_preferido"] in G.NOS
        for argv in r.argvs():
            assert legado._alvo_existe([legado.expandir(a) for a in argv]), f"{rid}: {argv[:3]} não existe"


def test_yaml_real_agenda_com_ids_unicos_e_cron_valido(real):
    linhas = real.agenda_linhas()
    ids = [x["id"] for x in linhas]
    assert len(ids) == len(set(ids))
    for x in linhas:
        P.Cron(x["cron_expr"])
        assert x["tipo_job"].startswith(G.PREFIXO_LEGADO) and x["payload"]["timeout_s"] > 60


def test_yaml_real_duplicacoes_viraram_uma_entrada(real):
    doerj = real.rotinas["doerj"]
    assert [a.args for a in doerj.agenda] == [["{ontem}"], ["{hoje}"]]
    assert [a.cron for a in real.rotinas["sweep_dados"].agenda] == ["0 10,16 * * *"]
    # o cron-rede que repetia o derivado virou o horário do PRÓPRIO derivado (uma rotina, agenda + evento)
    tl = real.rotinas["triagem_lote"]
    assert tl.evento and [a.cron for a in tl.agenda] == ["17 8-22 * * *"]
    assert sum(r.comando == tl.comando for r in real.rotinas.values()) == 1
    mantidas = {d.mantida for d in real.duplicacoes}
    assert {"triagem_lote", "conferencia_opus_fila", "sei_compactar", "doerj", "qualidade_juiz"} <= mantidas


def test_yaml_real_derivados_da_propagacao_estao_todos(real):
    prop = yaml.safe_load((G.RAIZ / "config" / "propagacao.yaml").read_text(encoding="utf-8"))
    for did, d in prop["derivados"].items():
        r = real.rotinas[did]
        assert r.evento and sorted(r.evento.depende) == sorted(d["depende"])
        # D3 (dono, 24/11): certeza e conformidade com o DOBRO do intervalo do propagacao.yaml (cadeia longa)
        fator = 2 if did in ("certeza", "conformidade") else 1
        assert r.evento.intervalo_min_s == fator * int(d.get("intervalo_min_s", 0)), did
        if (d.get("efeito") or {}).get("arquivo"):
            assert r.efeito.arquivo == d["efeito"]["arquivo"]


def test_grafo_planejador_agrupa_e_leva_o_intervalo(real):
    deps = {d["tipo"]: d for d in real.grafo_planejador()["siafe_ob"]}
    pc = deps["legado:pericia_contabil"]
    assert pc["agrupar"] is True and pc["intervalo_min_s"] == 3600 and pc["debounce_s"] == 600
    assert pc["payload"]["rotina"] == "pericia_contabil"


# ── validação ──
def test_base_minima_valida(base):
    g = G.validar_dict(base)
    assert g.contrato()["legado:rb"]["no_preferido"] == "vm1"


def test_ciclo_entre_rotinas_recusado(base):
    base["rotinas"]["ra"]["evento"] = {"depende": ["rb"]}
    with pytest.raises(ValueError, match="ciclo de dependência entre rotinas"):
        G.validar_dict(base)


def test_ciclo_entre_estagios_recusado(base):
    base["estagios"]["E1"]["depende"] = ["E2"]
    with pytest.raises(ValueError, match="ciclo de dependência entre estágios: E1 → E2 → E1"):
        G.validar_dict(base)


def test_achar_ciclo_puro():
    assert G.achar_ciclo({"a": ["b"], "b": ["c"], "c": []}) is None
    assert G.achar_ciclo({"a": ["b"], "b": ["c"], "c": ["a"]}) == ["a", "b", "c", "a"]
    assert G.achar_ciclo({"x": ["x"]}) == ["x", "x"]


@pytest.mark.parametrize("estraga,msg", [
    (lambda d: d["estagios"].pop("E18"), "faltam"),
    (lambda d: d["rotinas"]["rb"]["evento"].update(depende=["nao_existe"]), "não é fonte nem rotina"),
    (lambda d: d["rotinas"]["ra"].update(recursos=["rede"]), "recurso inexistente"),
    (lambda d: d["rotinas"]["ra"]["agenda"][0].update(cron="61 * * * *"), "intervalo"),
    (lambda d: d["rotinas"]["ra"].update(efeito={"descricao": "sem prova nenhuma"}), "efeito sem prova"),
    (lambda d: d["rotinas"]["ra"].update(comando=["/home/fulano/x.sh"]), "caminho de casa"),
    (lambda d: d["rotinas"]["ra"].update(agenda=[]), "sem gatilho"),
    (lambda d: d["rotinas"]["ra"].update(ativa=False), "bloqueio"),
    (lambda d: d["rotinas"]["ra"].update(passos=[["x"]]), "exatamente um"),
    (lambda d: d["rotinas"]["ra"].update(concorrencia=["sem_teto"]), "concorrência sem_teto"),
    (lambda d: d["rotinas"]["ra"].update(nos=["vm9"]), "nó desconhecido"),
    (lambda d: d["rotinas"]["ra"].update(campo_estranho=1), "Extra inputs"),
])
def test_validador_recusa(base, estraga, msg):
    d = copy.deepcopy(base)
    estraga(d)
    with pytest.raises(ValueError, match=msg):
        G.validar_dict(d)


def test_agenda_linhas_numera_horarios(base):
    base["rotinas"]["ra"]["agenda"].append({"cron": "0 3 * * *", "args": ["--x"]})
    linhas = {x["id"]: x for x in G.validar_dict(base).agenda_linhas()}
    assert set(linhas) == {"ra#1", "ra#2"} and linhas["ra#2"]["payload"]["args"] == ["--x"]


# ── planejador consumindo o grafo (PG, esquema temporário) ──
def _carregar_agenda(con, g):
    for x in g.agenda_linhas():
        con.execute("INSERT INTO agenda(id, cron_expr, tipo_job, payload) VALUES (%s, %s, %s, %s)",
                    (x["id"], x["cron_expr"], x["tipo_job"], __import__("json").dumps(x["payload"])))


@precisa_pg
def test_agenda_do_grafo_vira_job_com_contrato(con, base):
    g = G.validar_dict(base)
    _carregar_agenda(con, g)
    assert P.materializar_agenda(con, g.contrato()) == 0                 # recém-criada: só calcula
    con.execute("UPDATE agenda SET proximo = now() - interval '1 minute'")
    assert P.materializar_agenda(con, g.contrato()) == 1
    tipo, rec, no, payload = con.execute("SELECT tipo, recursos, no_preferido, payload FROM jobs").fetchone()
    assert tipo == "legado:ra" and rec == ["cpu_leve"] and no == "vm1" and payload["rotina"] == "ra"


@precisa_pg
def test_eventos_de_fontes_diferentes_viram_um_job_agrupado(con, base):
    g = G.validar_dict(base)
    fila.emitir(con, "f1", "mudou")
    fila.emitir(con, "ra", "concluido")
    assert P.propagar_eventos(con, g.grafo_planejador(), g.contrato()) == 2
    linhas = con.execute("SELECT chave, payload FROM jobs").fetchall()
    assert [c for c, _ in linhas] == ["legado:rb"]                       # UM job, não um por fonte
    assert linhas[0][1]["rotina"] == "rb" and linhas[0][1]["timeout_s"] == 120
    espera = con.execute("SELECT extract(epoch FROM disponivel_em - now()) FROM jobs").fetchone()[0]
    assert 25 <= espera <= 31                                           # debounce de 30 s


@precisa_pg
def test_intervalo_minimo_adia_a_reabertura(con, base):
    g = G.validar_dict(base)
    fila.enfileirar(con, "legado:rb", "legado:rb", {"rotina": "rb"})
    con.execute("UPDATE jobs SET estado = 'feito', concluido_em = now() - interval '100 seconds'")
    fila.emitir(con, "f1", "mudou de novo")
    P.propagar_eventos(con, g.grafo_planejador(), g.contrato())
    estado, espera = con.execute("SELECT estado, extract(epoch FROM disponivel_em - now()) FROM jobs").fetchone()
    assert estado == "fila" and 490 <= espera <= 501                   # 600 s de intervalo − 100 s já passados


@precisa_pg
def test_sem_agrupar_mantem_um_job_por_chave(con, base):
    base["rotinas"]["rb"]["evento"]["agrupar"] = False
    g = G.validar_dict(base)
    fila.emitir(con, "f1", "x", chave="p1")
    fila.emitir(con, "f1", "x", chave="p2")
    P.propagar_eventos(con, g.grafo_planejador(), g.contrato())
    assert sorted(r[0] for r in con.execute("SELECT chave FROM jobs")) == ["legado:rb:p1", "legado:rb:p2"]


def test_chave_duplicada_no_yaml_e_recusada(tmp_path):
    """Religação O9.0 (25/11/2026): `timeout_s` acrescentado numa rotina que já tinha `timeout_s: 900` mais abaixo —
    o yaml.safe_load ficou calado com a ÚLTIMA (900) e o conserto não teve efeito. Chave repetida é erro."""
    texto = Path(G.CAMINHO).read_text(encoding="utf-8")
    alvo = "    comando: ['{py}', -m, tools.sei_rj_catalogo]\n"
    assert alvo in texto
    p = tmp_path / "fluxo.yaml"
    p.write_text(texto.replace(alvo, alvo + "    timeout_s: 1\n"), encoding="utf-8")
    with pytest.raises(G.ErroGrafo, match="duplicad"):
        G.carregar(p)


def test_rotina_sem_dependente_e_terminal_tambem_no_vocabulario_antigo(real):
    """26/11/2026: a ponte retransmitiu do propagacao.db um `ob_reemitida/mudou` (vocabulário do despachante antigo,
    que rodou no vazamento de 25/11) e a saúde ficou BLOQUEADO por evento sem consumidor. Rotina sem dependente é o
    fim da cadeia nos dois vocabulários."""
    t = real.terminais()
    assert "ob_reemitida/concluido" in t and "ob_reemitida/mudou" in t


def test_estagio_do_codigo_bate_com_o_yaml():
    """26/11/2026: recursos/prioridade do estágio existiam em DUAS cópias — `ESTAGIO` no código e `estagios:` do
    config/fluxo.yaml — e o motor só lê o yaml. Mudei o E6 para cpu_pesado/55 no código e nada mudou: o governador
    seguiu matando o job (cpu_leve, teto 1G) até mandá-lo à quarentena. Cópia que diverge é proibida."""
    import importlib
    import pkgutil

    import compliance_agent.aplicacao.estagios as E
    g = G.carregar()
    ct = g.contrato()
    divergem = []
    for m in pkgutil.iter_modules(E.__path__):
        est = getattr(importlib.import_module(f"{E.__name__}.{m.name}"), "ESTAGIO", None)
        if est is None or m.name not in ct:
            continue
        c = ct[m.name]
        if list(est.recursos or []) != list(c.get("recursos") or []) or est.prioridade != c.get("prioridade"):
            divergem.append(f"{m.name}: código {est.recursos} p{est.prioridade} × yaml {c.get('recursos')} "
                            f"p{c.get('prioridade')}")
    assert not divergem, divergem
