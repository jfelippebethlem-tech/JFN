# -*- coding: utf-8 -*-
"""Gateway LLM, §3.11: CPF (com DV) e conta bancária mascarados ANTES de qualquer envio, com mapa reversível local;
desmascara na volta; sobrou CPF válido ⇒ nada sai. Máscara centralizada em `dominio/mascara` (a de
`leitura_integral` é a mesma função). CPFs sintéticos montados em tempo de execução (nenhum literal no repo)."""
import sqlite3

import pytest

from tests.autorizacao_paga_dubles import autorizar
from compliance_agent import leitura_integral as L
from compliance_agent.adaptadores.llm import gateway as G
from compliance_agent.adaptadores.llm import prompt_seguro as PS
from compliance_agent.dominio import mascara as M
from compliance_agent.dominio.digitos import cpf_valido


def _cpf(base9: str, fmt: str = "pontuado") -> str:
    d = [int(x) for x in base9]
    for n in (9, 10):
        d.append((sum(v * p for v, p in zip(d, range(n + 1, 1, -1))) * 10 % 11) % 10)
    c = "".join(map(str, d))
    if fmt == "cru":
        return c
    if fmt == "espaco":
        return f"{c[:3]} {c[3:6]} {c[6:9]} {c[9:]}"
    return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"


CPF_A, CPF_B = _cpf("274185963"), _cpf("381726495")
assert cpf_valido(CPF_A) and cpf_valido(CPF_B)


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    # 24/11/2026: estes testes exercitam a camada paga COM dublê — o dono "autoriza" num livro temporário
    autorizar(tmp_path, monkeypatch)
    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(tmp_path / "trace.db"))
    monkeypatch.setenv("JFN_LLM_CACHE_DB", str(tmp_path / "cache.db"))
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "estado"))
    monkeypatch.setattr(G, "_pre_assinatura", lambda t: None)
    return tmp_path


def _captura(texto="ok"):
    vistos = []

    def b(**kw):
        vistos.append(kw)
        return G.Retorno(texto=texto(kw) if callable(texto) else texto)
    return vistos, b


# ── a função do domínio ───────────────────────────────────────────────────────────────────────────────
def test_leitura_integral_reexporta_a_mesma_mascara():
    assert L.mascarar is M.mascarar and L.desmascarar is M.desmascarar
    t = f"Pague a João, CPF {CPF_A}, Agência 1234-5 Conta corrente nº 98765-4. CNPJ 12.345.678/0001-90."
    m, mapa = L.mascarar(t)
    assert CPF_A not in m and "98765-4" not in m and "[CPF_1]" in m and "[CONTA_1]" in m
    assert "12.345.678/0001-90" in m and L.desmascarar(m, mapa) == t


def test_estrito_mascara_cpf_com_espaco_so_com_dv_valido():
    esp = _cpf("274185963", "espaco")
    invalido = esp[:-1] + str((int(esp[-1]) + 1) % 10)            # mesmo formato, DV errado
    t = f"titular {esp}; protocolo {invalido}"
    m0, _ = M.mascarar(t)
    assert esp in m0                                               # modo antigo (leitura_integral) não pega espaço
    m, mapa = M.mascarar(t, estrito=True)
    assert esp not in m and invalido in m and M.desmascarar(m, mapa) == t


def test_cpfs_expostos_conta_so_dv_valido_nos_tres_formatos():
    assert M.cpfs_expostos(f"{CPF_A} {_cpf('381726495', 'cru')} {_cpf('274185963', 'espaco')}") == 3
    assert M.cpfs_expostos("123.456.789-00 e 11111111111") == 0     # DV inválido e repetido
    m, _ = M.mascarar(f"{CPF_A} e {_cpf('274185963', 'espaco')}", estrito=True)
    assert M.cpfs_expostos(m) == 0


def test_mapa_compartilhado_numera_em_sequencia_e_repete_o_mesmo_valor():
    mapa = {}
    a, _ = M.mascarar(f"x {CPF_A}", mapa)
    b, _ = M.mascarar(f"y {CPF_B} e de novo {CPF_A}", mapa)
    assert a == "x [CPF_1]" and b == "y [CPF_2] e de novo [CPF_1]" and mapa == {"[CPF_1]": CPF_A, "[CPF_2]": CPF_B}


# ── no gateway ────────────────────────────────────────────────────────────────────────────────────────
def test_nada_sai_com_cpf_ou_conta_e_a_resposta_volta_desmascarada(_isolado):
    vistos, b = _captura("o titular [CPF_1] recebeu na conta [CONTA_1]; o outro é [CPF_2]")
    doc = PS.Documento("d1", f"Credor CPF {CPF_B}, conta corrente nº 55443-2 em dia.", metadados={"Autor": CPF_A})
    r = G.chamar("classificacao", [{"role": "system", "content": f"regra {CPF_A}"},
                                   {"role": "user", "content": f"quem é {CPF_A}?"}],
                 prompt_version="v1", classe_dado="publico", documentos=[doc], backends={"free_llm": b})
    [kw] = vistos
    enviado = kw["sistema"] + kw["prompt"]
    for segredo in (CPF_A, CPF_B, "55443-2"):
        assert segredo not in enviado
    assert M.cpfs_expostos(enviado) == 0
    assert r.texto == f"o titular {CPF_A} recebeu na conta 55443-2; o outro é {CPF_B}"
    con = sqlite3.connect(_isolado / "trace.db")
    [(n,)] = con.execute("SELECT mascarados FROM llm_trace WHERE origem='gateway'").fetchall()
    assert n == 3
    bruto = (_isolado / "trace.db").read_bytes()
    assert CPF_A.encode() not in bruto and CPF_B.encode() not in bruto


def test_dados_do_json_tambem_voltam_desmascarados():
    _, b = _captura('{"titular": "[CPF_1]", "lista": ["[CPF_1]", 3]}')
    r = G.chamar("classificacao", [{"role": "user", "content": f"titular {CPF_A}"}], prompt_version="v1",
                 classe_dado="publico", schema={"titular": "", "lista": []}, backends={"free_llm": b})
    assert r.dados == {"titular": CPF_A, "lista": [CPF_A, 3]}


def test_sha_do_cabecalho_nunca_e_mascarado():
    sha = ("ab" + _cpf("274185963", "cru") + "c" * 64)[:64]       # sha com 11 dígitos seguidos e DV válido
    vistos, b = _captura()
    G.chamar("classificacao", [{"role": "user", "content": "leia"}], prompt_version="v1", classe_dado="publico",
             documentos=[PS.Documento("d1", "texto", versao_sha256=sha)], backends={"free_llm": b})
    assert f"versao_sha256={sha}" in vistos[0]["prompt"]


def test_sobrou_cpf_depois_da_mascara_nada_e_enviado(_isolado, monkeypatch):
    monkeypatch.setattr(M, "mascarar", lambda t, mapa=None, estrito=False: (t, mapa if mapa is not None else {}))
    vistos, b = _captura()
    with pytest.raises(G.MascaraFalhou):
        G.chamar("classificacao", [{"role": "user", "content": f"cpf {CPF_A}"}], prompt_version="v1",
                 classe_dado="publico", backends={"free_llm": b})
    assert vistos == []
    con = sqlite3.connect(_isolado / "trace.db")
    assert con.execute("SELECT erro FROM llm_trace WHERE origem='gateway'").fetchall() == [("recusado: máscara",)]


@pytest.mark.parametrize("classe", ["pessoal", "restrito"])
def test_pessoal_e_restrito_continuam_recusados_mesmo_com_mascara(classe):
    vistos, b = _captura()
    with pytest.raises(G.ClasseDadoRecusada):
        G.chamar("classificacao", [{"role": "user", "content": f"cpf {CPF_A}"}], prompt_version="v1",
                 classe_dado=classe, backends={"free_llm": b, "assinatura_claude": b, "api_anthropic": b})
    assert vistos == []


def test_estrito_nao_deixa_sobrar_nada_que_o_detector_acusa():
    """27/11/2026 (E8, processo 030001/110836/2026 em quarentena): o detector aceita separador MISTURADO (espaço numa
    posição, nada na outra) e a máscara não — o gateway barrou certo (nada saiu), mas o processo nunca seria lido.
    No modo estrito, tudo o que `cpfs_expostos` contaria vira marcador."""
    d = _cpf("274185963", "cru")
    for txt in (f"{d[:3]} {d[3:]}", f"{d[:3]}.{d[3:6]} {d[6:9]}-{d[9:]}", f"{d[:9]} {d[9:]}", f"{d[:3]} {d[3:6]}.{d[6:]}"):
        assert M.cpfs_expostos(txt) == 1
        m, mapa = M.mascarar(f"CPF {txt} fim", estrito=True)
        assert M.cpfs_expostos(m) == 0 and M.desmascarar(m, mapa) == f"CPF {txt} fim"
