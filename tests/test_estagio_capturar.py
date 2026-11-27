# -*- coding: utf-8 -*-
"""E3 `capturar` (O3.3): delta por id_documento (só o que falta), > 40 documentos em lotes até o fim, omitido calado
do "Gerar PDF" pego na conferência (efeito falha) e recapturado SOZINHO na tentativa seguinte, restrito declarado
(não é omitido), arquivo de outro dono recusado, versões sha256 no PG, idempotência e, depois de convergir, o E2 diz
"sem mudança" e o E3 não é acionado. Navegador sempre FALSO (tests/sei_falso.py); PG só em esquema temporário."""
import json

import pytest
import yaml

from compliance_agent.aplicacao.estagios import Contexto, estagio_de
from compliance_agent.aplicacao.estagios import arvore as A
from compliance_agent.aplicacao.estagios import capturar as C
from tests.fluxo_pg import DSN, precisa_pg
from tests.sei_falso import SEIFalso, arvore_falsa
from tests.test_estagio_arvore import PROC, pg  # noqa: F401 — fixture do esquema temporário


def _ctx(tipo: str, ficha: int) -> Contexto:
    return Contexto(no="vm2", tipo=tipo, chave=f"{tipo}:{PROC}", ficha=ficha, tentativa=1)


def _e2(nav, nome, ficha):
    ctx = _ctx("arvore", ficha)
    r = A._handler({"processo": PROC, "dsn": DSN, "esquema": nome}, ctx)
    assert A._efeito({"dsn": DSN, "esquema": nome}, ctx, r)
    return r


def _e3(nome, ficha, raiz):
    ctx = _ctx("capturar", ficha)
    r = C._handler({"processo": PROC, "dsn": DSN, "esquema": nome, "raiz": str(raiz),
                    "evento": {"detalhe": {"lente": ["bombeiros"]}}}, ctx)
    return r, C._efeito({"dsn": DSN, "esquema": nome}, ctx, r)


# ── puro ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _manifesto(tmp_path, docs, ok, donos=None):
    out = tmp_path / "integra_x"
    out.mkdir()
    for i in ok:
        (out / f"{i:03d}.pdf").write_bytes(b"%PDF " + str(i).encode())
    (out / "donos.json").write_text(json.dumps(donos if donos is not None else
                                               {f"{i:03d}.pdf": str(500_000 + i) for i in ok}))
    (out / "manifest.json").write_text(json.dumps({"completo": True, "docs": [
        {"i": i, "arquivo": f"{i:03d}.pdf", "titulo": x["t"], "id_documento": str(500_000 + i), "ok": i in ok}
        for i, x in enumerate(docs)]}))
    return out


def test_apurar_omitido_restrito_e_arquivo_de_outro_dono(tmp_path):
    docs = arvore_falsa(6)
    out = _manifesto(tmp_path, docs, ok={0, 1, 2}, donos={"000.pdf": "500000", "001.pdf": "999", "002.pdf": "500002"})
    ap = C.apurar(out, ja_tinha={"sei:90000005"}, restritos={"500004"})
    assert [v["doc_id"] for v in ap["versoes"]] == ["sei:90000000", "sei:90000002"]
    assert ap["sem_dono"] == ["sei:90000001"]                          # arquivo de outro documento: não vira versão
    assert [o["doc_id"] for o in ap["omitidos"]] == ["sei:90000001", "sei:90000003"]
    assert ap["restritos"] == ["sei:90000004"]                          # restrito declarado, não omitido
    assert ap["versoes"][0]["sha256"] == C.sha256_arquivo(out / "000.pdf")


def test_apurar_sem_manifesto_e_erro(tmp_path):
    with pytest.raises(RuntimeError, match="sem manifesto"):
        C.apurar(tmp_path, set(), set())


def test_registro_e_rotina_inativa_no_fluxo():
    assert estagio_de(f"capturar:{PROC}") is C.ESTAGIO
    rot = yaml.safe_load(open(A.RAIZ / "config" / "fluxo.yaml", encoding="utf-8"))["rotinas"]["capturar_e3"]
    assert rot["estagio"] == "E3" and rot["ativa"] is False and "parada de obras" in rot["bloqueio"]


# ── PostgreSQL ───────────────────────────────────────────────────────────────────────────────────────────────
@precisa_pg
def test_mais_de_40_omitido_calado_volta_e_so_ele_e_recapturado(pg, monkeypatch, tmp_path):  # noqa: F811
    con, nome = pg
    nav = SEIFalso(arvore_falsa(95, restritos=(90,)), omitir_no_pdf={57}, perder_no_laco={57})
    monkeypatch.setattr(A, "obter_navegador", lambda: nav)
    assert _e2(nav, nome, 1).efeito["faltantes"] == 94                   # 95 − 1 restrito
    r1, ok1 = _e3(nome, 1, tmp_path)
    assert nav.lotes[0] == [40, 40, 14]                                  # lotes de 40 até o fim, nunca só o 1º
    assert not ok1 and r1.efeito["omitidos"] == 1 and r1.efeito["restritos"] == 1
    assert r1.efeito["conferencia"]["faltas_recontadas"] == 1 and len(r1.efeito["versoes"]) == 93
    # 26/11/2026: incompleto MAS com progresso nesta posse ⇒ `continua` (o motor reabre sem gastar tentativa)
    assert r1.efeito["conferencia"]["novas_nesta_posse"] == 93 and r1.efeito["conferencia"]["continua"] is True
    assert r1.efeito["marcador"]["omitidos_pelo_pdf"] == 1
    # a tentativa seguinte só busca o que faltou (delta + retomada pelo id)
    r2, ok2 = _e3(nome, 2, tmp_path)
    assert ok2 and nav.baixados[1] == [57] and r2.efeito["omitidos"] == 0
    assert r2.efeito["marcador"]["omitidos_pdf_recuperados_pelo_laco"] == 0
    n = con.execute("SELECT count(*), count(DISTINCT doc_id) FROM versoes WHERE processo = %s AND hash_de = 'binario'",
                    (PROC,)).fetchone()
    assert n == (94, 94)
    aq = con.execute("SELECT count(*) FROM aquisicao WHERE fonte = 'sei:e3'").fetchone()[0]
    assert aq == 2 and r2.eventos[0]["fonte"] == "capturar"
    # convergiu: hash igual e nada faltando ⇒ E2 sem mudança, nenhum evento, E3 não é chamado
    antes = len(nav.baixados)
    r3 = _e2(nav, nome, 3)
    assert r3.efeito["estado"] == A.SEM_MUDANCA and r3.eventos == [] and len(nav.baixados) == antes


@precisa_pg
def test_mesma_posse_e_idempotente_e_efeito_pega_arquivo_trocado(pg, monkeypatch, tmp_path):  # noqa: F811
    con, nome = pg
    nav = SEIFalso(arvore_falsa(12))
    monkeypatch.setattr(A, "obter_navegador", lambda: nav)
    _e2(nav, nome, 1)
    r1, ok1 = _e3(nome, 5, tmp_path)
    r1b, ok1b = _e3(nome, 5, tmp_path)                                    # mesma posse de novo
    assert ok1 and ok1b and nav.baixados[1] == []                         # nada rebaixado
    assert con.execute("SELECT count(*) FROM versoes WHERE processo = %s", (PROC,)).fetchone()[0] == 12
    assert con.execute("SELECT count(*) FROM aquisicao WHERE fonte = 'sei:e3'").fetchone()[0] == 1
    alvo = tmp_path / f"integra_{PROC.replace('/', '_')}" / r1.efeito["versoes"][0][2]
    alvo.write_bytes(b"outro conteudo")
    assert not C._efeito({"dsn": DSN, "esquema": nome}, _ctx("capturar", 5), r1)


@precisa_pg
def test_legado_ja_guardado_nao_e_rebaixado(pg, monkeypatch, tmp_path):  # noqa: F811
    con, nome = pg
    docs = arvore_falsa(50)
    nav = SEIFalso(docs)
    monkeypatch.setattr(A, "obter_navegador", lambda: nav)
    _e2(nav, nome, 1)
    ids, _ = A.identidade(docs)
    for k in ids[:45]:                                                    # 45 já no acervo (texto do legado)
        con.execute("INSERT INTO versoes(processo, doc_id, sha256, chars, origem, vista_em, hash_de) VALUES "
                    "(%s,%s,%s,100,'sei_arquivo','x','texto')", (PROC, k, "t" + k))
    r, ok = _e3(nome, 1, tmp_path)
    assert ok and sorted(nav.baixados[0]) == list(range(45, 50)) and len(r.efeito["versoes"]) == 5


def test_captura_fora_da_vm2_e_espelhada_e_conferida(tmp_path, monkeypatch):
    """Religação O9.0 (26/11/2026): o E3 rodava no it-campo e gravava a captura no disco DELE; o E4 roda na VM-2 e não
    achava o manifest.json (todos os jobs de texto falhavam em < 1 s). A captura fora da VM-2 é espelhada nela
    (rsync --checksum) e conferida do outro lado (md5 do manifesto + nº de arquivos) — senão não conta como feita."""
    out = tmp_path / "integra_1_2_2026"
    out.mkdir()
    (out / "manifest.json").write_text('{"docs": []}')
    (out / "d1.pdf").write_bytes(b"%PDF")
    import hashlib
    md5 = hashlib.md5((out / "manifest.json").read_bytes()).hexdigest()
    cmds = []

    def rodar(argv, **k):
        cmds.append(argv)
        class R:
            returncode = 0
            stdout = f"{md5}\n2\n" if argv[0] == "ssh" else ""
            stderr = ""
        return R()
    monkeypatch.setattr(C.subprocess, "run", rodar)
    monkeypatch.setenv("JFN_E3_ESPELHO", "vm2-ts:JFN-worker/data/sei_cache")
    r = C.espelhar(out, no="itcampo")
    assert r["ok"] and r["destino"] == "vm2-ts:JFN-worker/data/sei_cache/integra_1_2_2026"
    assert cmds[0][0] == "rsync" and "--checksum" in cmds[0] and cmds[1][0] == "ssh"
    assert C.espelhar(out, no="vm2") is None                       # já está na VM-2: nada a espelhar
    monkeypatch.setattr(C.subprocess, "run", lambda argv, **k: type("R", (), {"returncode": 0, "stdout": "x\n1\n",
                                                                             "stderr": ""})())
    with pytest.raises(RuntimeError, match="espelho"):
        C.espelhar(out, no="itcampo")                                # md5 divergente: não conta como feita


def test_continua_so_com_progresso_e_sem_defeito():
    """Parcial sem nada novo nesta posse, ou com sha divergente/versão fora do PG, NÃO continua: é falha de verdade."""
    base = {"versoes_no_pg": True, "sha256_recalculado": True, "faltas_recontadas": 5, "arvore_nao_vazia": True,
            "ok": False}
    assert C.continua({**base, "novas_nesta_posse": 3}) is True
    assert C.continua({**base, "novas_nesta_posse": 0}) is False
    assert C.continua({**base, "novas_nesta_posse": 3, "sha256_recalculado": False}) is False
    assert C.continua({**base, "novas_nesta_posse": 3, "ok": True}) is False
