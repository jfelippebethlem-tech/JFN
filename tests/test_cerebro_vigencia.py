# -*- coding: utf-8 -*-
"""Recuperação × registro de fatos — medido em 20/11/2026 (consultas reais, só leitura): perguntando pelo rótulo de
9 fatos que já tiveram o valor corrigido, o `caso` não mostrava o valor VIGENTE em nenhuma das 108 linhas
devolvidas, e a memória #456 (ativa, sem chave, sem data) trazia o valor superado sem aviso. O verificador de
certeza não a via: só lia o registro LOCAL de memórias, e ela foi gravada à mão por uma sessão.

  · `caso` abre com o valor vigente do registro de fatos, marca o que traz valor superado, distingue o histórico
    datado e afunda o superado na lista; registro fora do ar é dito, nunca calado;
  · o verificador passa a perguntar ao cérebro também pelas MEMÓRIAS que trazem o valor superado.

Sem rede, sem tocar em data/."""
from datetime import datetime, timedelta, timezone

import pytest

from compliance_agent import cerebro_busca as B
from compliance_agent.certeza import citacoes, fatos

FATO = "iss_nao_retido:00801512000157:180100:valor"
BRT = timezone(timedelta(hours=-3))


@pytest.fixture()
def registro(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CERTEZA_DIR", str(tmp_path / "certeza"))
    cz = fatos.conectar()
    for valor, dia, hora in ((2437189.45, 18, 19), (2560162.04, 19, 18)):
        vig = fatos.vigente(cz, FATO)
        r = fatos.registrar(cz, {
            "fato_id": FATO, "valor": valor, "unidade": "BRL", "estado": "VERIFICADO", "nivel_prova": 2,
            "fonte": "NFS-e × OB SIAFE", "consulta": "data/iss_nao_retido.json", "data_ref": "2026-11-19T18:00:00",
            "hash_fonte": str(valor), "produtor": "teste", "rotulo": "ISS não retido — AGILE × UG 180100",
            "meta": {"apelidos": ["AGILE CORP SERVIÇOS ESPECIALIZADOS LTDA.", "00801512000157"], "termos": ["ISS"],
                     "superados": [2270009.39]}},
            vig["hash_versao"] if vig else None, agora=datetime(2026, 11, dia, hora, tzinfo=BRT).timestamp())
        assert r["status"] in ("novo", "atualizado"), r
    yield cz
    cz.close()


def _mem(i, texto):
    return {"id": i, "kind": "semantica", "source": "claude-vm1", "created_at": "2026-11-18T20:37:16+00:00", "content": texto}


@pytest.fixture()
def cerebro_falso(monkeypatch):
    mems = [_mem(456, "AGILE × SEEDUC — ISS não retido: R$ 2.270.009,39 sobre R$ 45.400.187,67 brutos."),
            _mem(471, "JFN — em 18/11/2026 a nota foi corrigida (ISS não retido: R$ 2.437.189,45)."),
            _mem(900, "AGILE: o recolhimento pela empresa segue INDISPONÍVEL.")]
    notas = [{"nota": "casos/agile.md", "titulo": "AGILE", "trecho": "ISS não retido de R$ 2.437.189,45 em 38 processos",
              "pernas": {"local": 1}, "resgate": False},
             {"nota": "casos/outro.md", "titulo": "Outro", "trecho": "sem número", "pernas": {"local": 2}, "resgate": False}]
    monkeypatch.setattr(B.cerebro, "recordar", lambda q, k=8, kind=None: list(mems))
    monkeypatch.setattr(B, "buscar_fundido", lambda q, k=10, **kw: {"notas": list(notas), "pernas": {"local": "ok 2"}})


def test_caso_abre_com_o_vigente_marca_o_superado_e_distingue_o_historico(registro, cerebro_falso):
    out = B.caso("ISS não retido AGILE")
    linhas = out.splitlines()
    pos = {m: next(i for i, l in enumerate(linhas) if m in l) for m in ("R$ 2.560.162,04", "#456", "#471", "#900", "casos/agile.md")}
    assert pos["R$ 2.560.162,04"] < min(pos["#456"], pos["#471"], pos["casos/agile.md"]), "o vigente vem antes de tudo"
    assert f"<!--fato:{FATO}-->" in linhas[pos["R$ 2.560.162,04"]] and "VERIFICADO" in linhas[pos["R$ 2.560.162,04"]]
    assert "VALOR SUPERADO" in linhas[pos["#456"] + 1] and "R$ 2.560.162,04" in linhas[pos["#456"] + 1]
    assert "histórico" in linhas[pos["#471"] + 1].lower() and "VALOR SUPERADO" not in linhas[pos["#471"] + 1]
    assert "VALOR SUPERADO" in linhas[pos["casos/agile.md"] + 1], "nota é documento vivo: valor antigo é superado"
    assert pos["#900"] < pos["#456"] and pos["#471"] < pos["#456"], "o que traz valor superado desce na lista"
    assert "CONFLITO" in out and "2 " in next(l for l in linhas if "CONFLITO" in l)


def test_controle_negativo_sem_fato_tocado_nao_ha_aviso_nem_bloco(registro, monkeypatch):
    monkeypatch.setattr(B.cerebro, "recordar", lambda q, k=8, kind=None: [_mem(1, "Limpeza urbana: contrato vigente.")])
    monkeypatch.setattr(B, "buscar_fundido", lambda q, k=10, **kw: {"notas": [], "pernas": {"local": "ok 0"}})
    out = B.caso("limpeza urbana")
    assert "VALOR SUPERADO" not in out and "CONFLITO" not in out and "Registro de fatos" not in out


def test_registro_de_fatos_fora_do_ar_e_dito_nao_calado(tmp_path, monkeypatch, cerebro_falso):
    monkeypatch.setenv("JFN_CERTEZA_DIR", str(tmp_path / "vazio"))       # sem certeza.db
    out = B.caso("ISS não retido AGILE")
    assert "INDISPONÍVEL" in out and "não foram conferidos" in out
    assert not (tmp_path / "vazio" / "certeza.db").exists(), "a leitura não pode criar o banco"


def test_verificador_acha_memoria_gravada_a_mao_com_valor_superado(registro):
    sup = {"cerebro": {"busca": True}}
    achadas = [{"id": 456, "chave": None, "content": "ISS não retido: R$ 2.270.009,39 sobre R$ 45.400.187,67 brutos."},
               {"id": 471, "chave": None, "content": "em 18/11/2026 a nota foi corrigida (R$ 2.437.189,45); antes R$ 2.270.009,39."},
               {"id": 955, "chave": None, "content": "ISS não retido da AGILE: R$ 2.560.162,04 (era R$ 2.270.009,39)."}]
    v = citacoes.varrer(registro, sup, buscar=lambda q, k: [], recordar=lambda q, k: achadas)
    assert [(d["superficie"], d["local"], d["tipo"]) for d in v["divergencias"]] == [
        ("cerebro_memoria", "memória #456", "memoria_do_cerebro_com_valor_superado")]
    # curada quando a memória é substituída (a busca por aquele valor não a devolve mais)
    citacoes.conciliar(registro, v["divergencias"], v["conferidas"], 1.0)
    v = citacoes.varrer(registro, sup, buscar=lambda q, k: [], recordar=lambda q, k: achadas[1:])
    assert citacoes.conciliar(registro, v["divergencias"], v["conferidas"], 2.0)["abertas"] == 0
