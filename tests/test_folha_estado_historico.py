"""27/11/2026 (dono: «não há margem nenhuma para erros de confiabilidade»): competência da folha do Estado só é
COMPLETA com todas as páginas de todos os cargos lidas e o total batendo com o da API; senão não ganha o marcador
ok_ e é refeita — o casador de benefícios só lê competência marcada."""
import gzip
import json

from tools import folha_estado_historico as H


def _api(monkeypatch, total_api, erro_no_cargo=None, linhas_por_cargo=3):
    def get(_c, params):
        if "codCargo" not in params:
            return {"totalElements": total_api}
        if params["codCargo"] == erro_no_cargo:
            return None
        regs = [{"nomeServidor": f"P{params['codCargo']}{k}", "cpf": "***.456.789-**", "orgao": "SEEDUC",
                 "funcaoCargo": "ASSESSOR", "vinculo": "CARGO COMISSAO", "totalVantagens": 1000.0} for k in range(linhas_por_cargo)]
        return {"remuneracoes": regs, "totalPages": 1}
    monkeypatch.setattr(H.F, "_get", get)
    monkeypatch.setattr(H.F, "_cargos", lambda c: [1, 2])
    monkeypatch.setattr(H, "PAUSA", 0)


def test_pagina_com_erro_nao_marca(tmp_path, monkeypatch):
    _api(monkeypatch, 6, erro_no_cargo=2)
    r = H.competencia(tmp_path, "2020-01")
    assert "erro" in r and not (tmp_path / "ok_2020-01").exists()


def test_total_da_api_diferente_nao_marca(tmp_path, monkeypatch):
    _api(monkeypatch, 100)                                # API diz 100, a partição trouxe 6
    r = H.competencia(tmp_path, "2020-01")
    assert "erro" in r and r["diferenca_api"] == 94 and not (tmp_path / "ok_2020-01").exists()


def test_competencia_integra_marca_e_nao_e_refeita(tmp_path, monkeypatch):
    _api(monkeypatch, 6)
    r = H.competencia(tmp_path, "2020-01")
    assert "erro" not in r and r["linhas"] == 6 and (tmp_path / "ok_2020-01").exists()
    linha = json.loads(gzip.open(tmp_path / "gesperj_2020-01.jsonl.gz", "rt").readline())
    assert linha["cpf"] == "XX456789XXX"                  # a máscara no formato da casa (janela 4–9)
    monkeypatch.setattr(H.F, "_get", lambda *a: (_ for _ in ()).throw(AssertionError("refez mês completo")))
    assert H.competencia(tmp_path, "2020-01")["linhas"] == 6


def test_segunda_instancia_nao_grava_por_cima(tmp_path, monkeypatch, capsys):
    """27/11/2026: duas execuções gravaram os mesmos arquivos de mês após o reboot da VM-1."""
    import fcntl
    _api(monkeypatch, 6)
    tmp_path.mkdir(exist_ok=True)
    trava = open(tmp_path / ".lock", "w")
    fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)                  # a "outra" execução
    assert H.main([str(tmp_path), "--de", "2020-01", "--ate", "2020-01"]) == 1
    assert "OUTRA EXECUÇÃO" in capsys.readouterr().out and not (tmp_path / "gesperj_2020-01.jsonl.gz").exists()


def test_incompleta_nao_imprime_ok(tmp_path, monkeypatch, capsys):
    _api(monkeypatch, 100)                                             # total da API diverge ⇒ incompleta
    assert H.main([str(tmp_path), "--de", "2020-01", "--ate", "2020-01"]) == 1
    assert "folha_estado_historico: INCOMPLETO" in capsys.readouterr().out
