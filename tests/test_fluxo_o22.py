# -*- coding: utf-8 -*-
"""O2.2 — o que a sombra de 24/11 mediu de errado no planejador (2,7× os recálculos do despachante), cada regra com
o teste que a reproduz: (1) cadeia agrupada como no `propagacao.despachar` antigo — evento de DERIVADO não abre
janela, dependente espera o derivado a montante que está PRONTO (e só esse), N eventos = 1 job, intervalo mínimo
contado de qualquer execução da rotina; (2) tetos na RESERVA: concorrência por fonte/provedor, ritmo da assinatura;
(3) agenda sem sobreposição; (4) nó como restrição dura, volta só sem heartbeat do nó primário (§3.5); (5) supervisor
no grafo real + `agenda sincronizar` com ativo=false. Banco SEMPRE em esquema temporário (tests/fluxo_pg.py)."""
import copy
import json

import pytest

from compliance_agent.fluxo import fila, governador, grafo as G, planejador as P, supervisor as S
from compliance_agent.fluxo.fila import Resultado
from tests.fluxo_pg import DSN, chave_lock, con, esquema_tmp, precisa_pg  # noqa: F401 — fixtures


@pytest.fixture()
def base():
    """f1 → u (derivado a montante) → d (dependente de f1 E de u). Mesmo desenho de certeza/conformidade."""
    estagios = {e: {"tipo": e.lower(), "nome": e, "recursos": ["cpu_leve"], "nos": ["vm1"], "volta": {"nos": ["vm2"]},
                    "timeout_s": 60, "efeito": "efeito verificável do estágio", "depende": []} for e in G.ESTAGIOS}
    return {"versao": 1, "nos": ["vm1", "vm2", "itcampo"],
            "concorrencia": {"por_fonte": {"max": 1, "motivo": "x"}, "siafe_sessao": {"max": 1, "motivo": "y"},
                             "assinatura_claude": {"max": 4, "motivo": "z"}},
            "estagios": estagios, "fontes": {"f1": "fonte 1"},
            "rotinas": {
                "up": {"estagio": "E10", "descricao": "derivado u", "comando": ["bash", "tools/x.sh"], "nos": ["vm1"],
                      "evento": {"depende": ["f1"], "debounce_s": 600, "intervalo_min_s": 0},
                      "efeito": {"descricao": "arquivo regravado", "arquivo": "data/u.json"}},
                "dn": {"estagio": "E10", "descricao": "derivado d", "comando": ["bash", "tools/x.sh"], "nos": ["vm1"],
                      "evento": {"depende": ["f1", "up"], "debounce_s": 600, "intervalo_min_s": 0},
                      "efeito": {"descricao": "arquivo regravado", "arquivo": "data/d.json"}},
                "sx": {"estagio": "E1", "descricao": "coleta s", "comando": ["bash", "tools/x.sh"], "nos": ["vm1"],
                      "concorrencia": ["siafe_sessao", "por_fonte"], "ritmo": "triagem",
                      "agenda": [{"cron": "*/5 * * * *"}],
                      "efeito": {"descricao": "arquivo regravado", "arquivo": "data/s.json"}}}}


def _vivo(con, no, idade_s=0):
    con.execute("INSERT INTO nos(no, slots, heartbeat_em) VALUES (%s, '{}', now() - make_interval(secs => %s)) "
                "ON CONFLICT (no) DO UPDATE SET heartbeat_em = EXCLUDED.heartbeat_em", (no, idade_s))


def _ja(con):
    con.execute("UPDATE jobs SET disponivel_em = now() WHERE estado = 'fila'")


def _enq(con, g, rid, chave=None, evento=True, **kw):
    c = g.contrato_da_rotina(rid)
    return fila.enfileirar(con, G.tipo_da_rotina(rid), chave or G.tipo_da_rotina(rid), g.payload(rid, evento=evento),
                           recursos=c["recursos"], volta=c["volta"], no_preferido=c["no_preferido"], **kw)


# ── grafo (puro) ──
def test_contrato_leva_nos_e_volta_so_quando_a_rotina_declara(base):
    g = G.validar_dict(base)
    c = g.contrato_da_rotina("up")
    assert c["nos"] == ["vm1"] and c["volta"] is None          # legado preso ao nó: a volta do estágio NÃO vale
    base["rotinas"]["up"]["volta"] = {"nos": ["vm2"]}
    c = G.validar_dict(base).contrato_da_rotina("up")
    assert c["volta"]["nos"] == ["vm2"]


def test_payload_leva_as_restricoes_da_reserva(base):
    g = G.validar_dict(base)
    p = g.payload("sx", evento=True)
    assert p["nos"] == ["vm1"] and p["ritmo"] == "triagem"
    assert g.payload("sx")["ritmo"] == "triagem"                 # D2 (24/11): o guarda vale também na agenda
    assert p["estagio"] == "E1"                                   # portão da religação (O2.3)
    assert p["concorrencia"] == ["siafe_sessao", "por_fonte:sx"]   # por_fonte é teto POR fonte, não um global
    assert g.payload("dn")["montante"] == ["legado:up"]             # f1 é fonte, não rotina: não entra
    assert "montante" not in g.payload("up") and g.tetos() == {"por_fonte": 1, "siafe_sessao": 1,
                                                               "assinatura_claude": 4}
    assert g.ritmos() == {"triagem"}


def test_evento_de_derivado_nao_abre_janela(base):
    g = G.validar_dict(base).grafo_planejador()
    assert {d["tipo"]: d["abre_janela"] for d in g["f1"]} == {"legado:up": True, "legado:dn": True}
    assert [d["abre_janela"] for d in g["up"]] == [False]


def test_validador_recusa_volta_com_no_desconhecido(base):
    d = copy.deepcopy(base)
    d["rotinas"]["up"]["volta"] = {"nos": ["vm9"]}
    with pytest.raises(ValueError, match="nó desconhecido"):
        G.validar_dict(d)


def test_yaml_real_ritmo_e_sessao_siafe_declarados():
    g = G.carregar()
    ritmo = {rid: r.ritmo for rid, r in g.rotinas.items() if r.ritmo}
    assert ritmo == {"lex_execucao_fila": "lex_execucao", "sei_fichas_fila": "sei_ficha", "triagem_lote": "triagem",
                     "conferencia_opus_fila": "conferencia_opus",
                     "automelhoria_executor": "automelhoria_executor"}   # 26/11: o executor (Opus) pela trava de ritmo
    com_ritmo = {x["payload"]["rotina"] for x in g.agenda_linhas() if "ritmo" in x["payload"]}
    assert com_ritmo == set(ritmo)                                 # D2: as 4 fundidas levam o ritmo na agenda
    deps = {d["tipo"]: d for ds in g.grafo_planejador().values() for d in ds}
    assert deps["legado:triagem_lote"]["payload"]["ritmo"] == "triagem"
    for rid in ("siafe_status_releitura", "siafe_documentos_varredura"):
        assert "siafe_sessao" in g.payload(rid)["concorrencia"]
    assert set(g.tetos()) == set(g.concorrencia)


# ── (1) cadeia ──
@precisa_pg
def test_cadeia_dependente_espera_o_montante_pronto_e_roda_uma_vez(con, base):
    """O excesso medido (certeza 14×3): d rodava junto com u e era reaberto quando u concluía."""
    g = G.validar_dict(base)
    gp, ct = g.grafo_planejador(), g.contrato()
    fila.emitir(con, "f1", "mudou")
    fila.emitir(con, "f1", "mudou de novo")
    assert P.propagar_eventos(con, gp, ct) == 2
    assert con.execute("SELECT count(*) FROM jobs").fetchone()[0] == 2        # u e d, um job cada
    _ja(con)
    j = fila.reservar(con, "vm1", {"cpu_leve": 2})
    assert j.tipo == "legado:up"
    assert fila.reservar(con, "vm1", {"cpu_leve": 2}) is None                 # d espera u (que está rodando)
    fila.concluir(con, j.ficha, Resultado(efeito_conferido=True, eventos=[{"fonte": "up", "tipo": "concluido"}]))
    assert P.propagar_eventos(con, gp, ct) == 1                               # o evento de u cai no d que já espera
    enfileiramentos = con.execute("SELECT count(*) FROM jobs WHERE tipo = 'legado:dn'").fetchone()[0]
    assert enfileiramentos == 1
    j = fila.reservar(con, "vm1", {"cpu_leve": 2})
    assert j.tipo == "legado:dn"
    fila.concluir(con, j.ficha, Resultado(efeito_conferido=True))
    assert P.propagar_eventos(con, gp, ct) == 0 and fila.reservar(con, "vm1", {"cpu_leve": 2}) is None


@precisa_pg
def test_dependente_nao_espera_montante_que_ainda_junta_eventos(con, base):
    """'só espera o derivado de que depende se ESSE está pronto para rodar' (propagacao.despachar)."""
    g = G.validar_dict(base)
    _enq(con, g, "up", atraso_s=600)                                          # u na janela de junção
    _enq(con, g, "dn")
    assert fila.reservar(con, "vm1", {"cpu_leve": 2}).tipo == "legado:dn"


@precisa_pg
def test_dependente_nao_espera_montante_barrado_ha_muito(con, base):
    """u elegível mas parado (sem slot) há mais que ESPERA_MONTANTE_MAX_S: barrado por fora, d segue."""
    g = G.validar_dict(base)
    _enq(con, g, "up")
    _enq(con, g, "dn")
    con.execute("UPDATE jobs SET recursos = '{gpu}' WHERE tipo = 'legado:up'")   # ninguém aqui tem GPU
    assert fila.reservar(con, "vm1", {"cpu_leve": 2}) is None                 # u acabou de ficar pronto: espera
    con.execute("UPDATE jobs SET disponivel_em = now() - make_interval(secs => %s) WHERE tipo = 'legado:up'",
                (fila.ESPERA_MONTANTE_MAX_S + 60,))
    assert fila.reservar(con, "vm1", {"cpu_leve": 2}).tipo == "legado:dn"


@precisa_pg
def test_evento_de_derivado_enfileira_sem_debounce(con, base):
    g = G.validar_dict(base)
    fila.emitir(con, "up", "concluido")
    P.propagar_eventos(con, g.grafo_planejador(), g.contrato())
    espera = con.execute("SELECT extract(epoch FROM disponivel_em - now()) FROM jobs").fetchone()[0]
    assert espera <= 1


@precisa_pg
def test_intervalo_minimo_conta_execucao_de_qualquer_chave_da_rotina(con, base):
    """A rodada da agenda (chave `:agenda:`) também conta para o intervalo do evento (a 'rede' do despachante)."""
    base["rotinas"]["dn"]["evento"]["intervalo_min_s"] = 1800
    g = G.validar_dict(base)
    _enq(con, g, "dn", chave="legado:dn:agenda:dn:2026-11-24T10:00")
    con.execute("UPDATE jobs SET estado = 'feito', concluido_em = now() - interval '300 seconds'")
    fila.emitir(con, "up", "concluido")
    P.propagar_eventos(con, g.grafo_planejador(), g.contrato())
    espera = con.execute("SELECT extract(epoch FROM disponivel_em - now()) FROM jobs WHERE chave = 'legado:dn'"
                         ).fetchone()[0]
    assert 1490 <= espera <= 1501


@precisa_pg
def test_evento_cai_no_job_da_agenda_da_mesma_rotina(con, base):
    """Rede fundida (agenda + evento): job da agenda em fila absorve o evento; rodando, o evento espera."""
    g = G.validar_dict(base)
    _enq(con, g, "dn", chave="legado:dn:agenda:dn:x")
    fila.emitir(con, "f1", "mudou")
    P.propagar_eventos(con, g.grafo_planejador(), g.contrato())
    assert con.execute("SELECT count(*) FROM jobs WHERE tipo = 'legado:dn'").fetchone()[0] == 1
    _ja(con)
    con.execute("DELETE FROM jobs WHERE tipo = 'legado:up'")
    j = fila.reservar(con, "vm1", {"cpu_leve": 1})
    fila.emitir(con, "f1", "mudou durante")
    assert P.propagar_eventos(con, g.grafo_planejador(), g.contrato()) == 0   # d rodando: o evento fica pendente
    fila.concluir(con, j.ficha, Resultado(efeito_conferido=True))
    assert P.propagar_eventos(con, g.grafo_planejador(), g.contrato()) == 1


# ── (2) tetos na reserva ──
@precisa_pg
def test_concorrencia_por_provedor_vale_entre_nos(con, base):
    g = G.validar_dict(base)
    base2 = copy.deepcopy(base)
    base2["rotinas"]["sx2"] = {**base["rotinas"]["sx"], "nos": ["vm2"]}
    g2 = G.validar_dict(base2)
    _enq(con, g, "sx")
    _enq(con, g2, "sx2")
    tetos = g.tetos()
    a = fila.reservar(con, "vm1", {"cpu_leve": 1}, tetos=tetos)
    assert a is not None
    assert fila.reservar(con, "vm2", {"cpu_leve": 1}, tetos=tetos) is None    # siafe_sessao = 1 no mundo todo
    fila.concluir(con, a.ficha, Resultado(efeito_conferido=True))
    assert fila.reservar(con, "vm2", {"cpu_leve": 1}, tetos=tetos).tipo == "legado:sx2"


@precisa_pg
def test_por_fonte_e_um_teto_por_rotina(con, base):
    base["rotinas"]["sx"]["concorrencia"] = ["por_fonte"]
    base["rotinas"]["tx"] = {**base["rotinas"]["sx"], "descricao": "coleta t"}
    g = G.validar_dict(base)
    _enq(con, g, "sx")
    _enq(con, g, "tx")
    tetos = g.tetos()
    assert fila.reservar(con, "vm1", {"cpu_leve": 2}, tetos=tetos) is not None
    assert fila.reservar(con, "vm1", {"cpu_leve": 2}, tetos=tetos) is not None   # fontes diferentes: as duas


@precisa_pg
def test_ritmo_bloqueado_nao_reserva(con, base):
    g = G.validar_dict(base)
    _enq(con, g, "sx", chave="legado:sx:agenda:sx:x", evento=False)          # D2: a agenda também obedece
    assert fila.reservar(con, "vm1", {"cpu_leve": 1}, ritmo_bloqueado={"triagem"}) is None
    con.execute("DELETE FROM jobs")
    _enq(con, g, "sx")
    assert fila.reservar(con, "vm1", {"cpu_leve": 1}, ritmo_bloqueado={"triagem"}) is None
    assert fila.reservar(con, "vm1", {"cpu_leve": 1}, ritmo_bloqueado={"outra"}) is not None


def test_ritmo_do_supervisor_reusa_o_guarda_e_fecha_a_porta_na_falha(monkeypatch):
    from compliance_agent.llm import contingencia
    monkeypatch.setattr(contingencia, "motivo_bloqueio", lambda t: None if t == "conferencia_opus" else "contido")
    assert S.motivo_ritmo("conferencia_opus") is None and S.motivo_ritmo("triagem") == "contido"

    def quebra(_t):
        raise OSError("arquivo ilegível")
    monkeypatch.setattr(contingencia, "motivo_bloqueio", quebra)
    assert "ilegível" in S.motivo_ritmo("triagem")


# ── (3) agenda sem sobreposição ──
@precisa_pg
def test_agenda_nao_materializa_com_job_da_rotina_em_fila_ou_reservado(con):
    con.execute("INSERT INTO agenda(id, cron_expr, tipo_job, proximo) VALUES ('h', '0 * * * *', 'eco', "
                "now() - interval '1 minute')")
    fila.enfileirar(con, "eco", "eco:agenda:h:anterior")
    fila.reservar(con, "vm1", ["cpu_leve"])                                   # a da hora anterior ainda roda
    assert P.materializar_agenda(con) == 0
    assert con.execute("SELECT proximo > now() FROM agenda").fetchone()[0]    # o horário passa, não acumula
    con.execute("UPDATE jobs SET estado = 'feito'")
    con.execute("UPDATE agenda SET proximo = now() - interval '1 minute'")
    assert P.materializar_agenda(con) == 1


# ── (4) nó ──
@precisa_pg
def test_no_e_restricao_dura_sem_volta(con, base):
    g = G.validar_dict(base)
    _enq(con, g, "up")
    _vivo(con, "vm1", idade_s=3600)                                           # vm1 fora há 1 h
    assert fila.reservar(con, "vm2", {"cpu_leve": 1}) is None                 # legado preso à VM-1: não migra
    assert fila.reservar(con, "vm1", {"cpu_leve": 1}) is not None


@precisa_pg
def test_volta_so_migra_sem_heartbeat_do_no_primario(con, base):
    base["rotinas"]["up"]["volta"] = {"nos": ["vm2"]}
    g = G.validar_dict(base)
    _enq(con, g, "up")
    _vivo(con, "vm1")
    assert fila.reservar(con, "vm2", {"cpu_leve": 1}) is None                 # primário vivo: preferência
    _vivo(con, "vm1", idade_s=P.NO_SEM_HEARTBEAT_S + 60)
    assert fila.reservar(con, "vm2", {"cpu_leve": 1}) is not None             # §3.5: migra


# ── (5) supervisor no grafo real + sincronizar agenda ──
@precisa_pg
def test_supervisor_carrega_o_grafo_real_e_passa_o_contrato(esquema_tmp, monkeypatch):
    visto = {}
    original = P.ciclo

    def espiao(con, grafo=None, contrato=None, terminais=None, nos_esperados=(), dividas=None, ritmo_bloqueado=None):
        visto.update(grafo=grafo, contrato=contrato, terminais=terminais, nos=nos_esperados, dividas=dividas)
        return original(con, grafo, contrato, terminais, nos_esperados, dividas, ritmo_bloqueado)
    monkeypatch.setattr(P, "ciclo", espiao)
    sup = S.Supervisor(no="teste", dsn=DSN, esquema=esquema_tmp, slots={"cpu_leve": 1}, isolamento="subprocesso",
                       chave_lideranca=chave_lock(), medir=lambda: governador.Medida(), ritmo=lambda t: None)
    try:
        sup.uma_volta()
    finally:
        sup.fechar()
    real = G.carregar()
    assert visto["grafo"] == real.grafo_planejador() and visto["contrato"] == real.contrato()
    assert visto["terminais"] == real.terminais() and visto["dividas"] == real.dividas()     # 1.1
    assert visto["nos"] == tuple(real.nos)                                                    # 1.15
    assert sup.tetos == real.tetos() and sup.ritmos == real.ritmos()


@precisa_pg
def test_sincronizar_agenda_grava_inativo_idempotente(con, base):
    g = G.validar_dict(base)
    linhas = g.agenda_linhas()
    assert P.sincronizar_agenda(con, linhas) == {"novas": 1, "atualizadas": 0, "iguais": 0, "desativadas": 0}
    assert con.execute("SELECT id, ativo, proximo FROM agenda").fetchall() == [("sx", False, None)]
    assert P.sincronizar_agenda(con, linhas)["iguais"] == 1
    assert P.materializar_agenda(con) == 0                                    # nada ativo: nada dispara
    con.execute("UPDATE agenda SET ativo = true, proximo = now()")            # (a O9.0 religa assim)
    linhas[0]["cron_expr"] = "0 3 * * *"
    assert P.sincronizar_agenda(con, linhas)["atualizadas"] == 1
    assert con.execute("SELECT cron_expr, ativo, proximo FROM agenda").fetchone() == ("0 3 * * *", True, None)
    assert P.sincronizar_agenda(con, [])["desativadas"] == 1                  # saiu do yaml: desliga, não apaga
    assert con.execute("SELECT ativo FROM agenda").fetchone()[0] is False


def test_cli_agenda_sincronizar_existe():
    from compliance_agent.fluxo import __main__ as M
    with pytest.raises(SystemExit):
        M.main(["agenda", "sincronizar", "--help"])



# dívida declarada (O2.2): rotinas legadas de navegador presas à VM-1, onde a §3.4 dá 0 slot de navegador. Decidido
# (D1, 24/11): slot TRANSITÓRIO de navegador na VM-1 só para estas, até a O3.3 — catraca em tests/test_fluxo_o23.py.
NAVEGADOR_NA_VM1 = {"siafe_runner_diario", "siafe_runner_retentar", "siafe_drenar_capados", "siafe_documento_sweep",
                    "sweep_sei", "sweep_dados", "sei_integra_fila", "integra_fila_dinheiro", "varredura_sei_lane",
                    "sweep_integra_contratos_pcrj", "doerj", "pcrj_sei_busca_termos", "sei_busca_credor",
                    "verificacao_humana_manter", "sweep_sei_noturno"}


def test_catraca_rotinas_sem_slot_so_a_divida_declarada():
    """A 1ª sombra (capacidade infinita) escondia: sei_ocr_gpu herdava `gpu` do E5 presa à VM-1 (corrigido no yaml);
    a lista abaixo é a dívida que sobra, e só pode diminuir."""
    sem = G.rotinas_sem_slot(G.carregar())
    assert sem == []                                   # D1: as 15 têm o slot transitório; nenhuma outra sem slot


def test_rotinas_sem_slot_detecta(base):
    base["rotinas"]["up"]["recursos"] = ["gpu"]                               # vm1 não tem GPU
    assert [r for r, _f, _n in G.rotinas_sem_slot(G.validar_dict(base))] == ["up"]


@precisa_pg
def test_job_preso_no_ritmo_segura_a_agenda_sem_empilhar(con, base):
    """D2 (dono, 24/11): o ritmo vale para a rotina fundida INTEIRA. O job de evento preso no ritmo conta como
    pendente — a agenda não enfileira outro a cada horário (senão N jobs presos soltariam juntos quando abrisse)."""
    base["rotinas"]["sx"]["evento"] = {"depende": ["f1"]}
    g = G.validar_dict(base)
    _enq(con, g, "sx")                                                       # job de evento, com ritmo
    for x in g.agenda_linhas():
        con.execute("INSERT INTO agenda(id, cron_expr, tipo_job, payload, proximo) VALUES (%s, %s, %s, %s, "
                    "now() - interval '1 minute')", (x["id"], x["cron_expr"], x["tipo_job"], json.dumps(x["payload"])))
    assert P.materializar_agenda(con, g.contrato()) == 0
    assert con.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
    assert fila.reservar(con, "vm1", {"cpu_leve": 2}, ritmo_bloqueado={"triagem"}) is None
    assert fila.reservar(con, "vm1", {"cpu_leve": 2}, ritmo_bloqueado=set()) is not None   # abriu: roda uma vez
