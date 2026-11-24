# -*- coding: utf-8 -*-
"""Gateway LLM, O6.1 (c): cache composto (chave = sha256 dos componentes; qualquer um mudou ⇒ miss), hit/miss no
trace, o cache guarda a resposta MASCARADA (sem CPF, sem mapa), o acerto passa de novo pela validação, e o prefixo
do prompt é fixo (sistema estável, sem o marcador aleatório). Backends dublês; nenhuma chamada real."""
import json
import sqlite3

import pytest

from compliance_agent.adaptadores.llm import cache as C
from compliance_agent.adaptadores.llm import gateway as G
from compliance_agent.adaptadores.llm import prompt_seguro as PS

SIS = "Você classifica documentos de licitação. Regras fixas: A, B, C."
MSG = [{"role": "system", "content": SIS}, {"role": "user", "content": "Classifique o documento abaixo."}]


def _cpf(base9: str) -> str:
    d = [int(x) for x in base9]
    for n in (9, 10):
        d.append((sum(v * p for v, p in zip(d, range(n + 1, 1, -1))) * 10 % 11) % 10)
    c = "".join(map(str, d))
    return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(tmp_path / "trace.db"))
    monkeypatch.setenv("JFN_LLM_CACHE_DB", str(tmp_path / "cache.db"))
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "estado"))
    monkeypatch.setattr(G, "_pre_assinatura", lambda t: None)
    return tmp_path


def _backend(texto="classe: edital"):
    vistos = []

    def b(**kw):
        vistos.append(kw)
        return G.Retorno(texto=texto)
    return vistos, b


def _trace(tmp_path):
    con = sqlite3.connect(tmp_path / "trace.db")
    return [r[0] for r in con.execute("SELECT cache FROM llm_trace WHERE origem='gateway' ORDER BY rowid")]


BASE = dict(tarefa="conferencia_opus", prompt_version="v1", classe_dado="publico", modelo_pref=None, regra="r1",
            schema=None, contexto={"ug": "133100"}, doc_texto="Edital de pregão eletrônico 12/2026.",
            doc_sha=None, versao_extracao="ext-1", sistema=SIS)


def _chamar(b, **mud):
    p = {**BASE, **mud}
    doc = PS.Documento("d1", p["doc_texto"], versao_sha256=p["doc_sha"], versao_extracao=p["versao_extracao"])
    msg = [{"role": "system", "content": p["sistema"]}, MSG[1]]
    return G.chamar(p["tarefa"], msg, prompt_version=p["prompt_version"], classe_dado=p["classe_dado"],
                    modelo_pref=p["modelo_pref"], regra=p["regra"], schema=p["schema"], contexto=p["contexto"],
                    documentos=[doc], cache=True, backends={"assinatura_claude": b, "free_llm": b})


def test_miss_depois_hit_sem_chamar_de_novo(_isolado):
    vistos, b = _backend()
    r1 = _chamar(b)
    r2 = _chamar(b)
    assert len(vistos) == 1 and r1.texto == r2.texto == "classe: edital"
    assert r1.extras["cache"] == "miss" and r2.extras["cache"] == "hit"
    assert r2.custo_usd == 0.0 and r2.provedor == "assinatura_claude" and r2.camada == 2
    assert _trace(_isolado) == ["miss", "hit"]


@pytest.mark.parametrize("mudanca", [
    {"doc_texto": "Edital de pregão eletrônico 13/2026."}, {"doc_sha": "f" * 64}, {"versao_extracao": "ext-2"},
    {"prompt_version": "v2"}, {"modelo_pref": "claude-opus-5-5"}, {"regra": "r2"}, {"schema": {"classe": ""}},
    {"contexto": {"ug": "133101"}}, {"sistema": SIS + " D."}, {"classe_dado": "interno"},
], ids=lambda m: next(iter(m)))
def test_qualquer_componente_mudou_e_miss(mudanca):
    vistos, b = _backend('{"classe": "edital"}')
    _chamar(b)
    _chamar(b, **mudanca)
    assert len(vistos) == 2


def test_politica_mudou_as_camadas_e_miss(_isolado, monkeypatch):
    import yaml
    vistos, b = _backend()
    _chamar(b)
    pol = yaml.safe_load(G._caminho_politica().read_text(encoding="utf-8"))
    pol["tarefas"]["conferencia_opus"] = {"camadas": [1, 2], "critica": False}
    arq = _isolado / "pol.yaml"
    arq.write_text(yaml.safe_dump(pol, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("JFN_LLM_POLITICA", str(arq))
    _chamar(b)
    assert len(vistos) == 2


def test_cache_desligado_por_padrao_nao_cria_banco(_isolado):
    vistos, b = _backend()
    for _ in range(2):
        G.chamar("classificacao", MSG, prompt_version="v1", classe_dado="publico", backends={"free_llm": b})
    assert len(vistos) == 2 and not (_isolado / "cache.db").exists() and _trace(_isolado) == [None, None]


def test_cache_guarda_mascarado_e_devolve_desmascarado(_isolado):
    cpf = _cpf("274185963")
    vistos, b = _backend("o credor é [CPF_1]")
    r1 = _chamar(b, doc_texto=f"Credor CPF {cpf}.")
    r2 = _chamar(b, doc_texto=f"Credor CPF {cpf}.")
    assert len(vistos) == 1 and r1.texto == r2.texto == f"o credor é {cpf}"
    bruto = (_isolado / "cache.db").read_bytes()
    assert cpf.encode() not in bruto and cpf.replace(".", "").replace("-", "").encode() not in bruto
    con = sqlite3.connect(_isolado / "cache.db")
    [(comp, texto)] = con.execute("SELECT componentes, texto FROM llm_cache").fetchall()
    assert texto == "o credor é [CPF_1]" and "Credor" not in comp and json.loads(comp)["montagem"] == "spot-v1"


def test_falha_e_indeterminado_nao_entram_no_cache(_isolado):
    vistos, b = _backend('{"x": 1}')                 # sem a chave pedida: falha de schema
    with pytest.raises(G.SemProvedor):
        _chamar(b, schema={"classe": ""})
    con = sqlite3.connect(_isolado / "cache.db")
    assert con.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 0


def test_acerto_e_revalidado_e_cai_para_miss_se_reprovar(_isolado):
    doc = PS.Documento("d1", "O valor global é de R$ 10,00 no total.")
    cit = {"documento_id": "d1", "versao_sha256": doc.versao_sha256, "pagina": 1, "trecho": "valor global é de R$ 10,00"}
    vistos, b = _backend(json.dumps({"v": "10", "citacoes": [cit]}))

    def ch(ver=None):
        return G.chamar("conferencia_opus", MSG, prompt_version="v1", classe_dado="publico", schema={"v": ""},
                        exigir_citacao=True, documentos=[doc], cache=True, verificador=ver,
                        backends={"assinatura_claude": b})
    assert ch().estado == G.RESPONDIDO
    r = ch(ver=lambda c, d: (False, "verificador novo reprova"))
    assert len(vistos) == 2 and r.extras["cache"] == "miss" and r.estado == G.INDETERMINADO_FALHA_CITACAO


def test_invalidar_por_documento_e_por_tarefa(_isolado):
    vistos, b = _backend()
    _chamar(b)
    assert C.invalidar(documento_id="outro") == 0
    assert C.invalidar(documento_id="d1") == 1
    _chamar(b)
    assert C.invalidar(tarefa="conferencia_opus") == 1
    _chamar(b)
    assert len(vistos) == 3
    with pytest.raises(ValueError):
        C.invalidar()


# ── prefixo fixo ──────────────────────────────────────────────────────────────────────────────────────
def test_prefixo_fixo_sistema_estavel_e_marcador_so_no_variavel():
    vistos, b = _backend()
    for texto in ("Primeiro documento.", "Segundo documento, bem diferente."):
        G.chamar("conferencia_opus", MSG, prompt_version="v1", classe_dado="publico",
                 documentos=[PS.Documento("d1", texto)], backends={"assinatura_claude": b})
    a, c = vistos
    assert a["sistema"] == c["sistema"] and a["sistema"].startswith(SIS) and PS.REGRA_DADOS in a["sistema"]
    tok_a = a["prompt"].split("marcador=")[1][:10]
    tok_c = c["prompt"].split("marcador=")[1][:10]
    assert tok_a != tok_c and tok_a not in a["sistema"] and tok_c not in c["sistema"]
    assert a["prompt"].startswith(MSG[1]["content"] + "\n\n<<<DADOS") and c["prompt"].startswith(MSG[1]["content"])


def test_sem_documento_e_sem_schema_o_par_do_chamador_passa_intacto():
    vistos, b = _backend()
    G.chamar("classificacao", MSG, prompt_version="v1", classe_dado="publico", backends={"free_llm": b})
    assert vistos[0]["sistema"] == SIS and vistos[0]["prompt"] == MSG[1]["content"]
