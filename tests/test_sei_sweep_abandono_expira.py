# -*- coding: utf-8 -*-
"""Desistir de um processo não pode ser para sempre.

O sweep abandona depois de 3 tentativas sem documento. A regra existe para não martelar processo
vazio ou restrito — mas a docstring do próprio `_ja_lido_ok` diz que "a abertura do SEI é flaky".

Medido em 2026-08-04: **2.760 processos abandonados**, e as unidades deles são as MESMAS onde
milhares foram lidos com sucesso (UG 080002: 826 abandonados contra 1.284 lidos na mesma unidade)
— não é falta de acesso, é falha intermitente. Entre os abandonados estavam o
SEI-150001/011573/2021 (R$ 210 mi, o PRIMEIRO da fila por dinheiro) e o SEI-080001/005089/2022
(I.D.E.A.S, R$ 135 mi): a fila propunha justamente o que o sweep tinha desistido de ler.

2.131 dos 2.760 falharam pela última vez há mais de 14 dias, sob episódios de WAF/sessão que já
passaram. A tentativa expira. É a mesma família da isenção permanente já corrigida duas vezes
(`captura_vazia` e o arquivo sem teor): declarar a falha é honesto, transformá-la em exclusão
definitiva não era o combinado.
"""
import json
from datetime import datetime, timedelta

import tools.sei_sweep as S


def _ha(dias: float) -> str:
    return (datetime.now() - timedelta(days=dias)).isoformat()


def test_falha_antiga_expira_e_ganha_nova_chance():
    assert S._tentativa_expirou(_ha(30)) is True


def test_falha_recente_continua_valendo_a_guarda():
    """Os 629 que falharam dentro da janela seguem fora da fila — a guarda existe para não
    martelar, e afrouxá-la por completo devolveria o problema que ela resolve."""
    assert S._tentativa_expirou(_ha(2)) is False


def test_a_borda_da_janela_conta_como_expirada():
    assert S._tentativa_expirou(_ha(S._DIAS_PARA_NOVA_CHANCE + 0.1)) is True
    assert S._tentativa_expirou(_ha(S._DIAS_PARA_NOVA_CHANCE - 1)) is False


def test_sem_data_ou_com_data_ilegivel_NAO_expira():
    """Na dúvida, mantém o comportamento antigo: a ausência de dado não pode ser o gatilho que
    devolve o acervo inteiro à fila."""
    for ruim in (None, "", "ontem", 12345, "2026-13-45"):
        assert S._tentativa_expirou(ruim) is False, ruim


# ---------------------------------------------------------------- acesso restrito confirmado

def _registro(tmp_path, monkeypatch, entrada):
    S._registro_restritos.cache_clear()  # o registro é lido 1× por execução do sweep; aqui, por teste
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "sei_restritos.json").write_text(
        json.dumps({"1500010115732021": entrada}), encoding="utf-8")
    monkeypatch.setattr(S, "REPO", tmp_path)
    return "SEI-150001/011573/2021"


def test_restrito_confirmado_e_recente_NAO_volta_a_fila(tmp_path, monkeypatch):
    """311 dos 2.760 abandonados estão como RESTRITO (duas leituras 0-doc de processo que EXISTE
    no cadastro). Retentá-los gasta ~100s cada em acesso negado documentado — INDISPONÍVEL de
    verdade, e o sweep rende mais nos 2.262 sobre os quais não há evidência nenhuma."""
    proc = _registro(tmp_path, monkeypatch,
                     {"status": "RESTRITO", "restrito_score": 2, "ultima": _ha(10)[:19].replace("T", " ")})
    assert S._restrito_confirmado(proc) is True


def test_marca_de_restrito_TAMBEM_expira(tmp_path, monkeypatch):
    """Nível de acesso muda e o acesso do itkava é ampliado. Trocar uma isenção permanente por
    outra seria repetir exatamente o defeito que este arquivo corrige."""
    proc = _registro(tmp_path, monkeypatch,
                     {"status": "RESTRITO", "restrito_score": 2,
                      "ultima": _ha(S._DIAS_RECONFERIR_RESTRITO + 5)[:19].replace("T", " ")})
    assert S._restrito_confirmado(proc) is False


def test_RESTRITO_interrogacao_volta_a_fila(tmp_path, monkeypatch):
    """Uma leitura só não confirma nada — é justamente a segunda que confirma ou desmente."""
    proc = _registro(tmp_path, monkeypatch,
                     {"status": "RESTRITO?", "restrito_score": 1, "ultima": _ha(1)[:19].replace("T", " ")})
    assert S._restrito_confirmado(proc) is False


def test_sem_registro_nao_se_nega_leitura_a_ninguem(tmp_path, monkeypatch):
    S._registro_restritos.cache_clear()
    monkeypatch.setattr(S, "REPO", tmp_path)
    assert S._restrito_confirmado("SEI-150001/011573/2021") is False
