# -*- coding: utf-8 -*-
"""Encadeamento dos estágios NATIVOS pelo motor (revisão de falhas caladas de 25/11/2026, frente F1).

1.1  o handler nativo emite a fonte curta (`arvore/documento_novo`…); o grafo só tinha id de rotina — o evento era
     marcado processado e nenhum job nascia. Agora: rota 'fonte/tipo' → job do estágio seguinte (config/fluxo.yaml
     `nativos`), evento sem consumidor fica PENDENTE e a saúde diz BLOQUEADO, e o boot recusa evento emitido sem
     rota/terminal/dívida. A catraca confere o `emite` do yaml contra o código dos handlers.
1.2  o motivo da conferência chega ao `erro_resumo` · 1.12 `Adiado` (SemCota) volta sem gastar tentativa ·
1.15 evento descartado (dependente em quarentena / malformado) visível · S1 SIGTERM não usa a conexão · S4 saída 0
     sem JSON é falha, não "efeito vazio". Os de banco em ESQUEMA TEMPORÁRIO (tests/fluxo_pg.py)."""
import copy
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from compliance_agent.fluxo import executar, fila, governador, grafo as G, planejador as P, supervisor as S
from compliance_agent.fluxo.fila import Resultado
from tests.fluxo_pg import DSN, chave_lock, con, esquema_tmp, precisa_pg  # noqa: F401 — fixtures

ESTAGIOS_DIR = Path(G.RAIZ) / "compliance_agent" / "aplicacao" / "estagios"
SHA = "ab" * 32


@pytest.fixture(scope="module")
def real():
    return G.carregar()


# ── boot e catraca (puros) ──
def test_boot_recusa_evento_emitido_sem_consumidor():
    dados = yaml.safe_load(G.CAMINHO.read_text(encoding="utf-8"))
    d = copy.deepcopy(dados)
    d["nativos"]["rotas"] = [r for r in d["nativos"]["rotas"] if r["evento"] != "arvore/documento_novo"]
    with pytest.raises(ValueError, match="E2 emite arvore/documento_novo, que não tem consumidor"):
        G.validar_dict(d)
    d = copy.deepcopy(dados)
    d["nativos"]["terminais"]["texto/sem_ocr"] = "mentira"                 # rota E terminal: recusa
    with pytest.raises(ValueError, match="tem rota E é terminal"):
        G.validar_dict(d)
    d = copy.deepcopy(dados)
    d["nativos"]["rotas"].append({"evento": "texto/texto_novo", "estagio": "E8", "forma": "aquisicao"})
    with pytest.raises(ValueError, match="forma aquisicao só serve ao estágio texto"):
        G.validar_dict(d)


# tipo de evento não literal no código → os valores que ele pode ter (conferidos no próprio fonte)
NAO_LITERAL = {("arvore", "DOC_NOVO"): ({"documento_novo"}, 'SEM_MUDANCA, SEM_DOC_NOVO, DOC_NOVO = "sem_mudanca", '
                                                             '"sem_documento_novo", "documento_novo"'),
               ("confirmar_ocr", 'ef["estado"]'): ({"confirmado", "a_conferir"},
                                                   'CONFIRMADO, A_CONFERIR = "confirmado", "a_conferir"')}
_RX_EV = re.compile(r'"fonte":\s*"([a-z_]+)",\s*"tipo":\s*(?:"([a-z_]+)"|([A-Za-z_][\w\[\]"]*))')


def test_catraca_emite_do_yaml_confere_com_o_codigo_dos_handlers(real):
    """O `nativos.emite` é a lista do que cada handler emite: a catraca relê o código. Evento novo num handler sem
    entrar no yaml (e portanto sem rota/terminal/dívida) quebra aqui — nunca some calado na produção."""
    for ek, est in real.estagios.items():
        arq = ESTAGIOS_DIR / f"{est.tipo}.py"
        if not arq.exists():
            assert not real.nativos.emite.get(ek), f"{ek} declara emissão sem handler nativo"
            continue
        src = arq.read_text(encoding="utf-8")
        achados: set[str] = set()
        for fonte, lit, expr in _RX_EV.findall(src):
            if lit:
                achados.add(f"{fonte}/{lit}")
                continue
            valores, prova = NAO_LITERAL.get((est.tipo, expr), (None, None))
            assert valores is not None, f"{arq.name}: tipo de evento não literal {expr!r} — declare em NAO_LITERAL"
            assert prova in src, f"{arq.name}: os valores de {expr} mudaram"
            achados |= {f"{fonte}/{v}" for v in valores}
        assert achados == set(real.nativos.emite.get(ek, [])), (ek, sorted(achados))


def test_grafo_real_encadeia_os_nativos(real):
    gp, ct, term = real.grafo_planejador(), real.contrato(), real.terminais()
    cadeia = {"coleta/ob_nova": "arvore", "arvore/documento_novo": "capturar", "capturar/versao_nova": "texto",
              "texto/pagina_escaneada": "ocr", "ocr/numero_ia": "confirmar_ocr", "texto/sem_ocr": "arquivar",
              "texto/texto_novo": "fatos", "confirmar_ocr/confirmado": "fatos",
              "coleta/fonte_mudou": "elegibilidade", "elegibilidade/mudou": "detectar",
              "detectar/achado_processo": "periciar", "fatos/mudou": "periciar", "periciar/laudo": "conferir",
              "conferir/veredito": "calibrar"}
    for ev, tipo in cadeia.items():
        assert tipo in [d["tipo"] for d in gp[ev]], ev
    # 26/11/2026: o original só sai (E7) DEPOIS de o E6 conferir — nunca direto do E5 (corrida E6 × E7)
    assert "ocr/terminado" not in gp
    for ev in ("confirmar_ocr/confirmado", "confirmar_ocr/a_conferir"):
        assert "arquivar" in [d["tipo"] for d in gp[ev]], ev
    dep = gp["arvore/documento_novo"][0]
    assert dep["payload"]["estagio"] == "E3" and dep["payload"]["concorrencia"] == ["sei_rj_ip"]
    assert ct["capturar"]["recursos"] == ["navegador"] and ct["expandir:texto"]["recursos"] == ["cpu_leve"]
    alvo = gp["capturar/versao_nova"][0]["payload"]["alvo"]
    assert alvo["tipo"] == "texto" and alvo["payload"]["estagio"] == "E4"
    assert "arquivar/arquivado" in term and "eco/concluido" in term
    assert all(f"{rid}/concluido" in term for rid in real.rotinas if rid not in gp)     # fim da cadeia legada
    assert real.dividas() == {}                                           # toda rota em dívida virou rota
    assert [d["tipo"] for d in gp["texto/invalido"]] == ["arvore"] and gp["texto/invalido"][0]["max_reaberturas"] == 3
    assert [d["tipo"] for d in gp["sei_relacionado/citado"]] == ["arvore"]
    assert sorted(d["tipo"] for d in gp["detectar/achados"]) == ["caso", "conferir"]
    assert [d["tipo"] for d in gp["caso/versao"]] == ["entregar"] and "enviar" not in gp["caso/versao"][0]["payload"]


def test_jobs_nativos_por_forma():
    d = {"tipo": "capturar", "forma": "processo"}
    assert P.jobs_nativos(d, "270006/000236/2026", {}) == [
        ("capturar", "capturar:270006/000236/2026", {"processo": "270006/000236/2026"})]
    assert P.jobs_nativos({"tipo": "fatos", "forma": "processo"}, "p1|sei:9", {})[0][1] == "fatos:p1"
    assert P.jobs_nativos({"tipo": "ocr", "forma": "documento"}, "p1|sei:9", {"sha256": SHA}) == [
        ("ocr", f"ocr:p1|sei:9|{SHA[:16]}", {"processo": "p1", "doc_id": "sei:9", "sha256": SHA})]
    assert P.jobs_nativos({"tipo": "texto", "forma": "aquisicao"}, "p1", {"aquisicao_id": "aq-7"}) == [
        ("expandir:texto", "expandir:texto:aq-7", {"aquisicao_id": "aq-7", "processo": "p1"})]
    assert P.jobs_nativos({"tipo": "elegibilidade", "forma": "unidade"}, "ob_siafe", {})[0][1] == \
        "elegibilidade:ob_siafe:todos"
    assert P.jobs_nativos({"tipo": "detectar", "forma": "detectores"}, "ob_siafe:2025", {}) == [
        ("expandir:detectar", "expandir:detectar:ob_siafe:2025", {"unidade": "ob_siafe", "exercicio": "2025"})]
    assert P.jobs_nativos({"tipo": "conferir", "forma": "laudo"}, "p1", {}) == [
        ("conferir", "conferir:laudo:p1", {"alvo": "laudo", "ref": "p1"})]
    assert P.jobs_nativos({"tipo": "calibrar", "forma": "agrupado"}, None, {}) == [("calibrar", "calibrar", {})]
    for forma, det in (("documento", {"sha256": "curto"}), ("aquisicao", {})):
        with pytest.raises(ValueError):
            P.jobs_nativos({"tipo": "x", "forma": forma}, "p1|d", det)


# ── propagação no PG ──
def _no(con, no="vm2"):
    con.execute("INSERT INTO nos(no, slots, heartbeat_em) VALUES (%s, %s, now())",
                (no, json.dumps(governador.SLOTS_INICIAIS["itcampo"])))


@precisa_pg
def test_evento_nativo_vira_job_do_estagio_seguinte(con, real):
    """1.1 reproduzido: antes, `arvore/documento_novo` era marcado processado e NENHUM job capturar nascia."""
    gp, ct, term, div = real.grafo_planejador(), real.contrato(), real.terminais(), real.dividas()
    _no(con)
    p = "270006/000236/2026"
    fila.emitir(con, "arvore", "documento_novo", p, {"tree_hash": "t"})
    fila.emitir(con, "capturar", "versao_nova", p, {"aquisicao_id": "aq-1", "n": 3})
    fila.emitir(con, "texto", "pagina_escaneada", f"{p}|sei:1", {"sha256": SHA, "paginas": [2]})
    fila.emitir(con, "arquivar", "arquivado", f"{p}|sei:1", {"sha256": SHA})                 # terminal
    fila.emitir(con, "fora_do_grafo", "x", "k")                                             # ninguém consome
    assert P.propagar_eventos(con, gp, ct, terminais=term) == 4
    jobs = {c: (t, pl) for c, t, pl in con.execute("SELECT chave, tipo, payload FROM jobs")}
    assert set(jobs) == {f"capturar:{p}", "expandir:texto:aq-1", f"ocr:{p}|sei:1|{SHA[:16]}"}
    t, pl = jobs[f"capturar:{p}"]
    assert t == "capturar" and pl["processo"] == p and pl["estagio"] == "E3" and pl["evento"]["tipo"] == \
        "documento_novo"
    assert jobs["expandir:texto:aq-1"][1]["alvo"]["tipo"] == "texto"
    rec = con.execute("SELECT recursos, volta FROM jobs WHERE tipo = 'ocr'").fetchone()
    assert rec[0] == ["gpu"] and rec[1]["nos"] == ["vm2"] and rec[1]["recursos"] == ["cpu_pesado"]
    pend = con.execute("SELECT fonte || '/' || tipo FROM eventos WHERE processado_em IS NULL").fetchall()
    assert pend == [("fora_do_grafo/x",)]                                 # fica, não some
    s = P.saude(con, grafo=gp, terminais=term, dividas=div)
    assert s["estado"] == "BLOQUEADO"
    assert any("evento sem consumidor: fora_do_grafo/x ×1" in m for m in s["motivos"])


@precisa_pg
def test_evento_descartado_fica_registrado_e_a_saude_ve(con, real):
    """1.15: dependente em quarentena não reabre (só por gente) e evento malformado não vira job — os dois são
    processados COM `detalhe.descartado`, e a saúde conta (antes: processado_em sem registro nenhum)."""
    gp, ct, term = real.grafo_planejador(), real.contrato(), real.terminais()
    _no(con)
    fila.enfileirar(con, "capturar", "capturar:p9")
    con.execute("UPDATE jobs SET estado = 'quarentena', concluido_em = now()")
    fila.emitir(con, "arvore", "documento_novo", "p9")
    fila.emitir(con, "texto", "sem_ocr", "p9|sei:2", {"texto_sha": "x"})                    # sem sha256
    assert P.propagar_eventos(con, gp, ct, terminais=term) == 2
    desc = [r[0] for r in con.execute("SELECT detalhe->'descartado' FROM eventos ORDER BY id")]
    assert "capturar:p9 em quarentena" in desc[0][0] and "sha256" in desc[1][0]
    s = P.saude(con, grafo=gp, terminais=term)
    assert any("2 evento(s) descartado(s)" in m for m in s["motivos"])


@precisa_pg
def test_ciclo_mede_os_nos_esperados(con):
    _no(con, "vm2")
    r = P.ciclo(con, grafo={}, nos_esperados=("vm1", "vm2"))
    assert r["saude"]["estado"] == "DEGRADADO" and any("nó vm1" in m for m in r["saude"]["motivos"])


@precisa_pg
def test_expandir_cria_um_job_por_versao_e_confere(con, esquema_tmp, monkeypatch, real):
    from compliance_agent.aplicacao.estagios import Contexto, texto as T
    from compliance_agent.fluxo import expandir as X
    monkeypatch.setenv(fila.ENV_ESQUEMA, esquema_tmp)
    monkeypatch.setenv("JFN_EVIDENCIAS_DSN", DSN)
    versoes = [("p1", "sei:1", SHA), ("p1", "sei:2", "cd" * 32)]

    class _Con:
        def close(self):
            pass
    monkeypatch.setattr(T, "conectar", lambda *a, **k: _Con())
    monkeypatch.setattr(T, "jobs_da_aquisicao", lambda c, aq: [
        {"tipo": "texto", "chave": T.chave_job("texto", p, d, s),
         "payload": {"processo": p, "doc_id": d, "sha256": s, "estagio": "E4"}} for p, d, s in versoes])
    payload = {**real.grafo_planejador()["capturar/versao_nova"][0]["payload"], "aquisicao_id": "aq-1"}
    ctx = Contexto(no="vm2", tipo="expandir:texto", chave="expandir:texto:aq-1", ficha=1, tentativa=1)
    r = X.ESTAGIO.handler(payload, ctx)
    assert r.efeito["criados"] == 2 and X.ESTAGIO.efeito(payload, ctx, r)
    assert con.execute("SELECT count(*), min(recursos::text) FROM jobs WHERE tipo = 'texto'").fetchone() == (
        2, "{cpu_leve}")
    assert X.ESTAGIO.handler(payload, ctx).efeito["ja_existentes"] == 2            # idempotente pela chave
    versoes.append(("p1", "sei:3", "ef" * 32))                                      # a fonte mudou: não confere
    assert not X.ESTAGIO.efeito(payload, ctx, r)


# ── filho e supervisor ──
def _estagio_falso(monkeypatch, handler=None, efeito=None):
    from compliance_agent.aplicacao.estagios import Estagio
    est = Estagio(handler=handler or (lambda p, c: Resultado(efeito={"x": 1})),
                  efeito=efeito or (lambda p, c, r: True))
    monkeypatch.setattr(executar, "estagio_de", lambda tipo: est)


def _rodar_filho(tmp_path, modo, resultado=None):
    e, s = tmp_path / "e.json", tmp_path / "s.json"
    e.write_text(json.dumps({"tipo": "falso", "chave": "falso:1", "ficha": 1, "no": "vm2", "tentativa": 1,
                             "payload": {}, "resultado": resultado}), encoding="utf-8")
    rc = executar.main([modo, str(e), str(s)])
    return rc, json.loads(s.read_text(encoding="utf-8"))


def test_semcota_dos_estagios_de_llm_e_adiado():
    from compliance_agent.aplicacao.estagios import conferir, fatos, periciar
    assert all(issubclass(m.SemCota, fila.Adiado) and issubclass(m.SemCota, RuntimeError)
               for m in (conferir, fatos, periciar))


def test_filho_adiado_sai_4_com_a_reabertura(tmp_path, monkeypatch, capsys):
    reabre = datetime(2026, 11, 28, 22, 0, tzinfo=timezone.utc)

    def h(p, c):
        raise fila.Adiado("ritmo contido", reabre)
    _estagio_falso(monkeypatch, handler=h)
    rc, out = _rodar_filho(tmp_path, "rodar")
    assert rc == executar.SAIDA_ADIADO == S.SAIDA_ADIADO
    assert out == {"adiado": "Adiado: ritmo contido", "reabre_em": reabre.isoformat()}
    assert "Adiado: ritmo contido" in capsys.readouterr().err


def test_filho_conferir_devolve_o_motivo(tmp_path, monkeypatch):
    def ef(p, c, r):
        r.efeito["conferencia"] = {"omitidos": 2, "ok": False}
        return False
    _estagio_falso(monkeypatch, efeito=ef)
    rc, out = _rodar_filho(tmp_path, "conferir", {"efeito": {"x": 1}, "eventos": []})
    assert rc == 0 and out == {"conferido": False, "conferencia": {"omitidos": 2, "ok": False}}


class _Proc:
    def __init__(self, rc):
        self.rc, self.pid = rc, 0

    def poll(self):
        return self.rc


def _sup(esquema):
    return S.Supervisor(no="teste", dsn=DSN, esquema=esquema, slots={"cpu_leve": 2}, grafo={},
                        isolamento="subprocesso", chave_lideranca=chave_lock(), medir=lambda: governador.Medida())


def _filho(con, tmp_path, fase, rc, saida, resultado=None, chave="eco:f"):
    fila.enfileirar(con, "eco", chave)
    job = fila.reservar(con, "teste", ["cpu_leve"])
    pasta = tmp_path / chave.replace(":", "_")
    pasta.mkdir()
    if saida is not None:
        (pasta / f"{fase}.saida.json").write_text(saida, encoding="utf-8")
    return S.Filho(job=job, fase=fase, proc=_Proc(rc), pasta=pasta, inicio=0.0, tempo_max=1e9, resultado=resultado)


@precisa_pg
def test_supervisor_adiado_saida_ausente_e_motivo_da_conferencia(con, esquema_tmp, tmp_path):
    sup = _sup(esquema_tmp)
    try:
        reabre = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        sup.filhos = [_filho(con, tmp_path, "rodar", S.SAIDA_ADIADO,
                             json.dumps({"adiado": "SemCota: juiz sem cota", "reabre_em": reabre}), chave="eco:a")]
        assert sup._colher()["adiado"] == 1                                   # 1.12
        assert con.execute("SELECT estado, tentativas, erro_tipo, erro_resumo FROM jobs WHERE chave = 'eco:a'"
                           ).fetchone() == ("fila", 0, "adiado", "SemCota: juiz sem cota")
        sup.filhos = [_filho(con, tmp_path, "conferir", 0, "{corrompido", {"efeito": {}}, chave="eco:s")]
        assert sup._colher()["falhou"] == 1                                   # S4: não vira "efeito vazio"
        assert con.execute("SELECT estado, erro_tipo FROM jobs WHERE chave = 'eco:s'").fetchone() == ("fila", "saida")
        sup.filhos = [_filho(con, tmp_path, "conferir", 0, json.dumps({"conferido": False,
                                                                       "conferencia": {"omitidos": 3}}),
                             {"efeito": {"versoes": 2}}, chave="eco:c")]
        assert sup._colher()["volta_efeito"] == 1                             # 1.2: volta, com o motivo
        resumo, efeito = con.execute("SELECT erro_resumo, efeito FROM jobs WHERE chave = 'eco:c'").fetchone()
        assert resumo == 'efeito não conferido: {"omitidos": 3}' and efeito["conferencia"] == {"omitidos": 3}
    finally:
        sup.filhos = []
        sup.fechar()


class _Explode:
    closed = False

    def execute(self, *a, **k):
        raise AssertionError("o handler de SIGTERM usou a conexão do laço (psycopg não é reentrante)")


@precisa_pg
def test_sigterm_so_levanta_a_bandeira_e_o_laco_devolve_os_jobs(con, esquema_tmp, tmp_path):
    """S1: `parar` roda DENTRO do handler de sinal — talvez no meio de uma consulta na mesma conexão."""
    sup = _sup(esquema_tmp)
    try:
        f = _filho(con, tmp_path, "rodar", None, None, chave="eco:t")
        f.proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
        sup.filhos = [f]
        real, sup.con = sup.con, _Explode()
        sup.parar()
        sup.con = real
        assert sup._parar and sup.filhos == [f]
        assert sup.encerrar_filhos() == 1
        assert f.proc.poll() is not None
        assert con.execute("SELECT estado, erro_tipo FROM jobs WHERE chave = 'eco:t'").fetchone() == ("fila", "parada")
    finally:
        sup.fechar()


# ── pendências fechadas (2ª rodada da F1): ritmo, volta com recursos, rotas que eram dívida, agenda E17/E18 ──
def test_estagios_de_llm_levam_o_ritmo_e_todo_estagio_tem_slot(real):
    """O ritmo da assinatura segura E8/E11/E12 NA RESERVA (antes o job rodava, relia o texto e adiava). E todo
    estágio nativo tem slot num nó da lista ou da volta (com os recursos da volta): sem it-campo, o E5 roda na CPU."""
    gp = real.grafo_planejador()
    assert gp["texto/texto_novo"][0]["payload"]["ritmo"] == "leitura_integral"
    assert gp["fatos/mudou"][0]["payload"]["ritmo"] == "pericia_integral"
    assert gp["periciar/laudo"][0]["payload"]["ritmo"] == "conferencia_e12"
    assert gp["detectar/achados"][0]["payload"]["alvo"]["payload"].get("ritmo") in (None, "conferencia_e12")
    assert {"leitura_integral", "pericia_integral", "conferencia_e12"} <= real.ritmos()
    from compliance_agent.aplicacao.estagios import conferir, fatos, periciar
    assert (fatos.TAREFA, periciar.TAREFA, conferir.TAREFA) == ("leitura_integral", "pericia_integral",
                                                                "conferencia_e12")
    for ek, e in real.estagios.items():
        c = real.contrato_do_estagio(ek)
        na_lista = any(all(real.slots_do_no(n).get(r) for r in c["recursos"]) for n in c["nos"])
        v = c["volta"] or {}
        na_volta = any(all(real.slots_do_no(n).get(r) for r in (v.get("recursos") or c["recursos"]))
                       for n in v.get("nos") or [])
        assert na_lista, ek
        assert not v or na_volta, f"{ek}: a volta {v} não tem slot (declare volta.recursos)"


def test_formas_novas():
    assert P.jobs_nativos({"tipo": "materializar", "forma": "fixo", "chave": "siafe_stats"}, "ob_siafe", {}) == [
        ("materializar", "materializar:siafe_stats", {})]
    assert P.jobs_nativos({"tipo": "conferir", "forma": "achados"}, "e10.x:todos", {}) == [
        ("expandir:conferir", "expandir:conferir:e10.x:todos", {"rodada": "e10.x:todos"})]
    assert P.jobs_nativos({"tipo": "arvore", "forma": "citado", "max_profundidade": 1}, "p2", {"de": "p1"}) == [
        ("arvore", "arvore:p2", {"processo": "p2", "citado_por": "p1", "profundidade": 1})]
    with pytest.raises(P._Encerrado):
        P.jobs_nativos({"tipo": "arvore", "forma": "citado", "max_profundidade": 1}, "p3", {"de": "p2", "_prof_de": 1})
    from compliance_agent.fluxo import expandir as X
    res = {"itens": [{"processo": "270006/000236/2026", "cnpj": "12.345.678/0001-90", "descricao": "12345678000190"},
                     {"processos": ["080002/013622/2026"], "credor": "12345678000190", "valor": "99999999999999"}]}
    assert X.citados(res) == {"processo:270006/000236/2026", "processo:080002/013622/2026", "cnpj:12345678000190"}


def test_agenda_nativa_entra_na_agenda_do_pg_com_simular(real):
    linhas = {x["id"]: x for x in real.agenda_nativa()}
    m = linhas["e17_backup_compliance"]
    assert m["tipo_job"] == "manter" and m["payload"]["simular"] is True and m["payload"]["estagio"] == "E17"
    assert linhas["e18_observar_vm2"]["tipo_job"] == "observar" and linhas["e18_observar_vm2"]["payload"]["nos"] == ["vm2"]
    assert not set(linhas) & {x["id"] for x in real.agenda_linhas()}


@precisa_pg
def test_reserva_pela_volta_com_os_recursos_da_volta(con, real):
    """§3.5: it-campo fora ⇒ o E5 (gpu) reserva na VM-2 pedindo cpu_pesado; it-campo vivo ⇒ espera por ele."""
    gp, ct = real.grafo_planejador(), real.contrato()
    con.execute("INSERT INTO nos(no, slots, heartbeat_em) VALUES ('vm2', %s, now())",
                (json.dumps(real.slots_do_no("vm2")),))
    fila.emitir(con, "texto", "pagina_escaneada", "p1|sei:1", {"sha256": SHA})
    P.propagar_eventos(con, gp, ct)
    s = P.saude(con, grafo=gp)
    assert not any("gpu" in m for m in s["motivos"]), s                  # não é BLOQUEADO: a volta tem slot
    con.execute("INSERT INTO nos(no, slots, heartbeat_em) VALUES ('itcampo', '{}', now())")
    assert fila.reservar(con, "vm2", real.slots_do_no("vm2")) is None    # it-campo vivo: o E5 é dele
    con.execute("DELETE FROM nos WHERE no = 'itcampo'")
    j = fila.reservar(con, "vm2", real.slots_do_no("vm2"))
    assert j.tipo == "ocr" and j.recursos == ["cpu_pesado"]


@precisa_pg
def test_ritmo_fechado_segura_na_reserva_e_nao_e_atrasado(con, real):
    gp, ct = real.grafo_planejador(), real.contrato()
    con.execute("INSERT INTO nos(no, slots, heartbeat_em) VALUES ('vm2', %s, now())",
                (json.dumps(real.slots_do_no("vm2")),))
    fila.emitir(con, "texto", "texto_novo", "p1|sei:1", {"sha256": SHA})
    P.propagar_eventos(con, gp, ct)
    con.execute("UPDATE jobs SET disponivel_em = now() - interval '1 hour'")
    assert fila.reservar(con, "vm2", real.slots_do_no("vm2"), ritmo_bloqueado=["leitura_integral"]) is None
    s = P.saude(con, grafo=gp, ritmo_bloqueado=["leitura_integral"])
    assert s["estado"] == "SAUDAVEL" and s["ritmo_segura"] == {"leitura_integral": 1}, s
    assert P.saude(con, grafo=gp)["estado"] == "ATRASADO"                # sem o ritmo medido, é fila parada
    assert fila.reservar(con, "vm2", real.slots_do_no("vm2")).tipo == "fatos"


@precisa_pg
def test_recaptura_em_laco_e_citado_alem_da_profundidade(con, real):
    gp, ct = real.grafo_planejador(), real.contrato()
    for _ in range(5):                                   # a mesma tela de WAF 5×: 3 reaberturas, depois laço
        fila.emitir(con, "texto", "invalido", "p1|sei:9", {"sha256": SHA, "motivo": "waf"})
        P.propagar_eventos(con, gp, ct)
        con.execute("UPDATE jobs SET estado = 'feito', concluido_em = now()")
    desc = [d for (d,) in con.execute("SELECT detalhe->'descartado' FROM eventos ORDER BY id")]
    assert desc[:3] == [None, None, None] and all("laço" in d[0] for d in desc[3:])
    con.execute("TRUNCATE jobs, eventos")
    fila.emitir(con, "sei_relacionado", "citado", "p2", {"de": "p1"})    # p1 veio da OB (sem profundidade)
    P.propagar_eventos(con, gp, ct)
    assert con.execute("SELECT payload->>'profundidade' FROM jobs WHERE chave = 'arvore:p2'").fetchone() == ("1",)
    fila.emitir(con, "sei_relacionado", "citado", "p3", {"de": "p2"})    # citado do citado: para
    P.propagar_eventos(con, gp, ct)
    assert fila.estado_de(con, "arvore:p3") is None
    enc = con.execute("SELECT detalhe->'encerrado', processado_em IS NOT NULL FROM eventos WHERE chave = 'p3'"
                      ).fetchone()
    assert enc[1] and "2 saltos" in enc[0][0]
    assert not any("descartado" in m for m in P.saude(con, grafo=gp)["motivos"])   # regra, não defeito


@precisa_pg
def test_agenda_nativa_sem_sobreposicao_por_linha(con, real):
    linhas = [x for x in real.agenda_nativa() if x["tipo_job"] == "manter"]
    P.sincronizar_agenda(con, linhas)
    con.execute("UPDATE agenda SET ativo = true, proximo = now() - interval '1 minute'")
    assert P.materializar_agenda(con, real.contrato()) == len(linhas) == 5       # as 5 rotinas, não 1
    assert P.materializar_agenda(con, real.contrato()) == 0


def test_teto_de_memoria_do_filho_nao_mata_o_chromium():
    """E16 (PDF) foi à quarentena na prova rf1b: Chromium não abre sob RLIMIT_AS (reserva dezenas de GB de VA)."""
    import resource
    assert S.RLIMIT_FILHO == resource.RLIMIT_DATA
    src = Path(S.__file__).read_text(encoding="utf-8")
    assert "setrlimit(resource.RLIMIT_AS" not in src


# ── r3 com LLM: a autorização do dono abre o ritmo do MOTOR só no escopo do ensaio O8.5 ──
def _medicao(con, pct: float):
    import time as _t
    from compliance_agent.fluxo import ritmo as R
    volta = datetime.now(timezone.utc).astimezone() + timedelta(days=3)
    R.publicar(con, {"em": "agora", "medido_ts": _t.time(), "sessao_pct": 10.0, "sessao_volta": None,
                     "semana_pct": pct, "semana_volta": volta.strftime("%Y-%m-%dT%H:%M:%S")}, "vm2")


@precisa_pg
def test_ritmo_do_motor_cede_a_autorizacao_so_no_escopo_e_abaixo_do_teto(con, tmp_path, monkeypatch):
    from compliance_agent.fluxo import ritmo as R
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path))
    (tmp_path / ".assinatura_liberada_dono.json").write_text(json.dumps(
        {"escopo": "passada --com-llm do ensaio O8.5 pela ASSINATURA (claude -p, backend cli); nunca API paga",
         "teto_semana_pct": 90.0}), encoding="utf-8")
    _medicao(con, 89.0)
    monkeypatch.delenv("JFN_ASSINATURA_ESCOPO", raising=False)
    assert "ritmo semanal" in R.motivo(con, "leitura_integral")          # sem o escopo: segura (produção)
    monkeypatch.setenv("JFN_ASSINATURA_ESCOPO", "ensaio_o85")
    assert R.motivo(con, "leitura_integral") is None                      # escopo + arquivo + abaixo do teto
    _medicao(con, 90.0)
    assert "ritmo semanal" in R.motivo(con, "leitura_integral")          # no teto: segura
    _medicao(con, 70.0)
    (tmp_path / ".assinatura_liberada_dono.json").write_text(json.dumps(
        {"escopo": "API paga", "teto_semana_pct": 90.0}), encoding="utf-8")
    assert "ritmo semanal" in R.motivo(con, "leitura_integral")          # arquivo de outro escopo: segura
    con.execute("TRUNCATE metricas")
    assert R.motivo(con, "leitura_integral").startswith("porta fechada")  # sem medição: nunca cede


def test_e11_e12_esperam_o_montante(real):
    gp = real.grafo_planejador()
    assert gp["fatos/mudou"][0]["payload"]["montante"] == ["detectar", "fatos"]
    assert gp["periciar/laudo"][0]["payload"]["montante"] == ["detectar", "periciar"]
    assert "montante" not in gp["texto/texto_novo"][0]["payload"]


def test_guarda_local_dos_handlers_de_llm_cede_so_no_escopo(monkeypatch):
    """r3 (25/11): o E8/E11 barravam pela contingência crua — a autorização do dono não chegava a eles."""
    from compliance_agent.aplicacao.estagios import fatos, periciar
    from compliance_agent.fluxo import ritmo as R
    from compliance_agent.llm import claude_motor, contingencia
    monkeypatch.setattr(contingencia, "motivo_bloqueio", lambda t="": "ritmo semanal da assinatura — contido")
    monkeypatch.setattr(contingencia, "estado", lambda: {"origem": "ritmo_semanal"})
    monkeypatch.setattr(claude_motor, "ritmo_liberado_pelo_dono", lambda: False)
    assert R.motivo_local("leitura_integral").startswith("ritmo semanal")
    assert fatos.motivo_assinatura().startswith("ritmo semanal") and periciar.motivo_assinatura()
    monkeypatch.setattr(claude_motor, "ritmo_liberado_pelo_dono", lambda: True)
    assert R.motivo_local("leitura_integral") is None
    assert fatos.motivo_assinatura() is None and periciar.motivo_assinatura() is None
    monkeypatch.setattr(contingencia, "estado", lambda: {"origem": "limite_assinatura"})   # limite da conta: nunca
    monkeypatch.setattr(contingencia, "motivo_bloqueio", lambda t="": "limite de uso da assinatura")
    assert R.motivo_local("leitura_integral") == "limite de uso da assinatura"
    assert S.motivo_ritmo("leitura_integral") == "limite de uso da assinatura"


@precisa_pg
def test_um_job_da_assinatura_por_no(con, esquema_tmp, tmp_path):
    """r3: 3 jobs de LLM no mesmo nó brigavam pela trava do claude_motor (um claude por máquina), adiavam e reliam."""
    sup = _sup(esquema_tmp)
    try:
        sup.ritmos = {"leitura_integral", "pericia_integral"}
        assert sup._bloqueio_da_reserva([]) == []
        f = _filho(con, tmp_path, "rodar", None, None, chave="eco:llm")
        f.job.payload = {"ritmo": "leitura_integral"}
        sup.filhos = [f]
        assert sup._bloqueio_da_reserva(["triagem"]) == ["leitura_integral", "pericia_integral", "triagem"]
        fila.enfileirar(con, "fatos", "fatos:p1", {"ritmo": "pericia_integral"})
        assert fila.reservar(con, "teste", ["cpu_leve"], ritmo_bloqueado=sup._bloqueio_da_reserva([])) is None
        f.job.payload = {}
        assert fila.reservar(con, "teste", ["cpu_leve"], ritmo_bloqueado=sup._bloqueio_da_reserva([])).chave == \
            "fatos:p1"
    finally:
        sup.filhos = []
        sup.fechar()
