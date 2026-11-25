# -*- coding: utf-8 -*-
"""O8.5 — o orquestrador do ensaio ponta a ponta (tools/ensaio_o85.py) com 3 itens SINTÉTICOS pelo motor real
(fila no PG em esquema `ensaio_o85_<run>_fluxo` temporário, processo-filho `tools.ensaio_o85 filho` → `fluxo.executar`).

Prova: (a) encadeamento — os eventos REAIS que o estágio A gravou viram os jobs do estágio B, contagem batendo;
(b) efeito não conferido ⇒ passagem REPROVADA (nunca "feito"); (c) 2ª passada seguida = 0 leitura, 0 download,
0 LLM — pela idempotência do motor (a chave já tem job) e pela do handler (reaberto, não relê); (d) o sensor E18
`leitura.repetida_pct` dispara (> 0, fora do SLO 0) com uma releitura injetada. Mais: o `--com-llm` recusa antes de
28/11/2026 19h (BRT), a amostra é estratificada e reprodutível, e o esquema de produção é recusado."""
import uuid
from datetime import datetime

import pytest

from tests.fluxo_pg import DSN, precisa_pg
from tools import ensaio_o85 as E


# ── puros ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_com_llm_recusa_antes_da_virada_e_libera_depois():
    assert not E.liberado_llm(datetime(2026, 11, 28, 18, 59, tzinfo=E.BRT))
    assert E.liberado_llm(datetime(2026, 11, 28, 19, 0, tzinfo=E.BRT))


def test_cmd_rodar_com_llm_recusa_antes_da_virada(monkeypatch, capsys):
    monkeypatch.setattr(E, "liberado_llm", lambda agora=None: False)
    assert E.main(["rodar", "--run", "x1", "--com-llm"]) == 2
    assert "28/11/2026 19h" in capsys.readouterr().err


def test_esquemas_sempre_do_ensaio_nunca_de_producao():
    e = E.esquemas("r1")
    assert set(e.values()) == {f"ensaio_o85_r1_{k}" for k in ("fluxo", "cap", "fatos", "dom", "sombra")}
    for ruim in ("", "R1", "a;b", "fluxo" * 5):
        with pytest.raises(ValueError):
            E.esquemas(ruim)


def test_sortear_estratificado_reprodutivel_e_com_teto_de_ocr():
    cands = [{"processo": f"270006/{i:06d}/2025", "couto": i % 2 == 0, "escaneadas": 10 * (i % 3)} for i in range(20)]
    a = E.sortear(cands, 6, semente=85, max_escaneadas=40)
    b = E.sortear(list(reversed(cands)), 6, semente=85, max_escaneadas=40)
    assert [x["processo"] for x in a] == [x["processo"] for x in b]                  # não depende da ordem
    assert sum(x["escaneadas"] for x in a) <= 40
    assert {x["estrato"] for x in a} == {"couto", "antes_couto"}
    assert [x["processo"] for x in E.sortear(cands, 6, semente=86, max_escaneadas=40)] != [x["processo"] for x in a]


def test_classificar_abstencao_so_para_estagio_de_llm_sem_llm():
    assert E.classificar("fatos", "quarentena", "SemCota: leitor sem cota", False) == "ABSTEVE(sem_llm_no_ensaio)"
    assert E.classificar("fatos", "quarentena", "SemCota", True) == "falhou"
    assert E.classificar("texto", "quarentena", "SemCota", False) == "falhou"
    assert E.classificar("texto", "falhou_efeito", None, False) == "falhou_efeito"
    assert E.classificar("texto", "feito", None, False) == "feito"


def test_navegador_replay_so_baixa_o_que_falta(tmp_path):
    import json
    src = tmp_path / "acervo" / "integra_270006_000001_2025"
    src.mkdir(parents=True)
    for i in range(3):
        (src / f"{i:03d}.pdf").write_bytes(b"%PDF-1.4 " + bytes([i]) * 10)
    man = {"completo": True, "docs": [{"i": i, "arquivo": f"{i:03d}.pdf", "titulo": f"Doc ({100 + i})", "ok": True,
                                       "url": f"https://sei/x?id_documento={100 + i}"} for i in range(3)]}
    (src / "manifest.json").write_text(json.dumps(man))
    nav = E.NavegadorReplay(tmp_path / "acervo")
    pg = nav.arvore("270006/000001/2025", 0)
    assert len(pg.docs) == 3 and pg.proxima is None and pg.via == "replay:acervo"
    from compliance_agent.dominio import documento_id as DI
    ids = DI.ids_documentos([{"titulo": d["titulo"], "i": d["i"]} for d in man["docs"]])
    out = nav.capturar("270006/000001/2025", {"docs": [[ids[0], "Doc", 10, ""]]}, tmp_path / "cache")
    assert sorted(p.name for p in out.glob("*.pdf")) == ["001.pdf", "002.pdf"]       # o guardado não é "baixado"
    assert json.loads((out / "manifest.json").read_text())["delta"] == {"modo": "replay", "baixados": 2,
                                                                          "mantidos": 1}


def test_destino_do_ensaio_confere_md5_e_e_local(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"conteudo")
    d = E.DestinoEnsaio(tmp_path / "frio")
    g = d.guardar(f)
    assert g["md5"] == E._md5(f) and d.conferir(g["chave"], g["md5"]) and not d.conferir(g["chave"], "0" * 32)


# ── motor real (PG) ───────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def ens(tmp_path):
    import psycopg

    from compliance_agent.fluxo import schema
    run = "t" + uuid.uuid4().hex[:8]
    e = E.Ensaio(run=run, passada=1, base=tmp_path, dsn=DSN, estagios_extra="tests.ensaio_o85_falso")
    e.dir.mkdir(parents=True)
    with psycopg.connect(DSN, autocommit=True) as c:
        schema.aplicar(c, e.esq["fluxo"])
    try:
        yield e
    finally:
        with psycopg.connect(DSN, autocommit=True) as c:
            for s in e.esq.values():
                c.execute(f'DROP SCHEMA IF EXISTS "{s}" CASCADE')


def _docs(tmp_path, n=3):
    pasta = tmp_path / "docs"
    pasta.mkdir(exist_ok=True)
    for i in range(n):
        (pasta / f"d{i}.txt").write_text(f"documento sintético {i} — autorizo o pagamento de R$ {i},00",
                                         encoding="utf-8")
    return pasta


def _gatilho(ens, pasta, docs):
    from compliance_agent.fluxo import fila
    con = ens.con()
    try:
        for d in docs:
            fila.emitir(con, "coleta", "doc_novo", d, {"pasta": str(pasta)})
    finally:
        con.close()


def _g_ler(reler=False):
    return lambda evs: [E._job("t_ler", f"t_ler:{e['chave']}", {"pasta": e["detalhe"]["pasta"], "doc": e["chave"],
                                                                  "reler": reler}) for e in evs]


def _g_usar(falhar=()):
    return lambda evs: [E._job("t_usar", f"t_usar:{e['chave']}", {"pasta": e["detalhe"]["pasta"], "doc": e["chave"],
                                                                    "sha": e["detalhe"]["sha"],
                                                                    "falhar_efeito": e["chave"] in falhar})
                        for e in evs]


@precisa_pg
def test_encadeamento_efeito_segunda_passada_e_sensor(ens, tmp_path):
    from compliance_agent.fluxo import sensores as S
    pasta = _docs(tmp_path)
    docs = ["d0", "d1", "d2"]
    _gatilho(ens, pasta, docs)

    # (a) A lê e emite; B nasce SÓ dos eventos que A gravou, um job por evento, contagem batendo
    pa = E.passagem(ens, "EA", [("coleta", "doc_novo")], _g_ler(), "t_ler")
    assert pa["estado"] == "APROVADA" and pa["efeito_conferido"] == 3 and pa["eventos_emitidos"] == 3
    pb = E.passagem(ens, "EB", [("t_ler", "pronto")], _g_usar(falhar={"d2"}), "t_usar")
    assert pb["entrada"] == {"t_ler/pronto": 3} and pb["fila"]["criados"] == 3
    assert sorted(j["chave"] for j in pb["jobs"]) == [f"t_usar:{d}" for d in docs]
    # (b) o efeito declarado que não houve ⇒ falhou_efeito ⇒ passagem REPROVADA (nunca "feito")
    assert pb["estado"] == "REPROVADA" and pb["classes"] == {"feito": 2, "falhou_efeito": 1}
    l1 = E.resumo_leituras(ens, ens.rotulo)
    assert l1["leituras"] == 3 and l1["repetidas"] == 0 and l1["por_tipo"] == {"texto": 3}

    # (c) 2ª passada seguida: o gatilho volta, a chave já tem job ⇒ nada roda, nada é lido
    ens2 = E.Ensaio(run=ens.run, passada=2, base=ens.base, dsn=DSN, estagios_extra=ens.estagios_extra)
    _gatilho(ens2, pasta, docs)
    p2 = E.passagem(ens2, "EA", [("coleta", "doc_novo")], _g_ler(), "t_ler")
    assert p2["fila"]["ja_existentes"] == 3 and p2["jobs_rodados"] == 0
    # … e reaberta (`--forcar`): o handler roda, mas é idempotente pela chave — 0 leitura, 0 download, 0 LLM
    ens3 = E.Ensaio(run=ens.run, passada=3, forcar=True, base=ens.base, dsn=DSN, estagios_extra=ens.estagios_extra)
    _gatilho(ens3, pasta, docs)
    p3 = E.passagem(ens3, "EA", [("coleta", "doc_novo")], _g_ler(), "t_ler")
    assert p3["jobs_rodados"] == 3 and p3["eventos_emitidos"] == 0
    for e in (ens2, ens3):
        r = E.resumo_leituras(e, e.rotulo)
        assert (r.get("leituras"), r.get("downloads"), r.get("llm")) == (0, 0, 0)

    # (d) releitura injetada (outro job relê o mesmo documento) ⇒ o sensor do E18 sai do SLO 0
    con = ens.con()
    try:
        ctx = S.Ctx(no="vm2", con=con, agora=datetime.now().astimezone())
        antes = S.g_leitura(ctx)[0]
        assert antes.valor == 0.0
        ens4 = E.Ensaio(run=ens.run, passada=4, forcar=True, base=ens.base, dsn=DSN,
                        estagios_extra=ens.estagios_extra)
        _gatilho(ens4, pasta, ["d1"])
        E.passagem(ens4, "EA", [("coleta", "doc_novo")], _g_ler(reler=True), "t_ler")
        depois = S.g_leitura(ctx)[0]
        slo = S.carregar_slos().por_sensor()["leitura.repetida_pct"][1]
        assert depois.valor == 25.0 and depois.rotulos["repetidas"] == 1
        assert S.avaliar(slo, antes.valor)[0] == S.SAUDAVEL and S.avaliar(slo, depois.valor)[0] == S.DEGRADADO
        assert depois.rotulos["repetidas_amostra"][0]["estagio"] == "t_ler"
    finally:
        con.close()


@precisa_pg
def test_sensor_sem_registro_e_indisponivel(ens):
    from compliance_agent.fluxo import sensores as S
    con = ens.con()
    try:
        r = S.g_leitura(S.Ctx(no="vm2", con=con, agora=datetime.now().astimezone()))[0]
    finally:
        con.close()
    assert r.valor is None and "ausente" in r.motivo
